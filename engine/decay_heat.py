"""Decay heat (thermal power) engine — recoverable decay energy (HANDOFF_PLAN §5).

§5 calls decay heat an *optional output that "falls straight out of the decay
energies."* It is HP-relevant for spent fuel (M7c) but the physics is **general**:
the locally-deposited power of any solved inventory, computed from the SAME bundled
ICRP-107 emission spectra the gamma/beta dose engines read — **no new dataset**.

    decay_heat(t) = Σ_nuclides  A_n(t) · Ē_rec,n            [W]
    Ē_rec,n = recoverable energy per decay (J)              [solve once]

So, like the dose engines, this obeys §3 ("solve once, evaluate many"): the
per-nuclide coefficient ``Ē_rec`` (W per Bq) is assembled once from the emission
file; the whole time grid is then one matvec against the activity series from
``inventory.SolvedInventory.evaluate``.

**The quantity computed (an honesty-register definition, §11):** the *bulk
recoverable* decay energy — what is deposited locally in a large medium —

    Ē_rec = Σ_β Ē_β·y   (mean β/β⁺ kinetic energy; antineutrino energy EXCLUDED,
                          which is exactly why decay heat ≠ Q-value)
          + Σ_γ E·y      (all tabulated photons: γ, X-ray, annihilation)
          + Σ_e E·y      (IC / Auger electrons)
          + Σ_α E_α·y · A/(A−4)   (α PARTICLE energy + the heavy-recoil nucleus,
                                    a locally-stopped ~2 %: Q_α = E_α·A/(A−4))

Documented limits (§11): spontaneous-fission / fission fragment energy is NOT in
this sum (it is not in the ICRP-107 per-decay line data) — negligible except for
SF sources (Cf-252), where the dominant decay mode is α anyway. A daughter with no
emission file is a *stable end-product* (legitimately zero heat), matching the
``dose.py`` convention; a radioactive nuclide is never silently zeroed because the
descendant closure only reaches such stable sinks at zero activity.

No silent errors (CLAUDE.md): a malformed/negative emission energy raises
:class:`DecayHeatError`, never a quiet skip.
"""

from __future__ import annotations

import re
from typing import Sequence

from engine import emissions as emissions

#: MeV → J (same constant as dose.py; §12 store internally in SI).
MEV_TO_J = 1.602176634e-13

#: Emission channels that contribute locally-deposited energy. ``alpha`` is handled
#: separately (it needs the per-nuclide recoil factor), so it is not in this map.
_E_FIELD = {"betas": "E_mean_MeV", "photons": "E_MeV", "electrons": "E_MeV"}

_NUCLIDE_RE = re.compile(r"^([A-Za-z]+)-(\d+)([a-z]*)$")


class DecayHeatError(Exception):
    """Loud failure in the decay-heat path — never swallowed, never a fallback number."""


def _mass_number(nuclide: str) -> int:
    """Mass number A from a nuclide id (``Pu-238`` → 238, ``Ba-137m`` → 137)."""
    m = _NUCLIDE_RE.match(nuclide)
    if not m:
        raise DecayHeatError(f"cannot parse mass number from nuclide {nuclide!r}")
    return int(m.group(2))


def _channel_sum(nuclide: str, channel: str, e_field: str) -> float:
    """Σ E·y over one emission channel (MeV/decay). Loud on a malformed entry."""
    total = 0.0
    for line in emissions.load_emissions(nuclide).get(channel, []):
        try:
            e = float(line[e_field])
            y = float(line["yield"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DecayHeatError(
                f"{nuclide}: malformed {channel} entry {line!r} ({exc})"
            ) from exc
        if e < 0.0 or y < 0.0:
            raise DecayHeatError(
                f"{nuclide}: negative {channel} energy/yield ({e}, {y}) — not physical"
            )
        total += e * y
    return total


def recoverable_energy_MeV(nuclide: str) -> dict:
    """Per-decay recoverable (locally-deposited) energy of ``nuclide``, by channel.

    Returns ``{"total", "beta", "photon", "electron", "alpha", "alpha_recoil"}`` in
    MeV/decay, where ``alpha`` is the bare ICRP-107 particle energy and
    ``alpha_recoil`` is the heavy-nucleus recoil added by the ``A/(A−4)`` factor
    (the two sum into ``total``). A nuclide with no emission file (a stable
    end-product) returns all-zero — the ``dose.py`` convention.
    """
    if not emissions.has_emissions(nuclide):
        return {
            "total": 0.0,
            "beta": 0.0,
            "photon": 0.0,
            "electron": 0.0,
            "alpha": 0.0,
            "alpha_recoil": 0.0,
        }

    beta = _channel_sum(nuclide, "betas", _E_FIELD["betas"])
    photon = _channel_sum(nuclide, "photons", _E_FIELD["photons"])
    electron = _channel_sum(nuclide, "electrons", _E_FIELD["electrons"])

    alpha_particle = _channel_sum(nuclide, "alphas", "E_MeV")
    alpha_recoil = 0.0
    if alpha_particle > 0.0:
        a = _mass_number(nuclide)
        if a <= 4:
            raise DecayHeatError(f"{nuclide}: α recoil needs mass number A > 4, got {a}")
        # Q_α = E_α·A/(A−4); the recoil increment is E_α·[A/(A−4) − 1] = E_α·4/(A−4).
        alpha_recoil = alpha_particle * (4.0 / (a - 4))

    total = beta + photon + electron + alpha_particle + alpha_recoil
    return {
        "total": total,
        "beta": beta,
        "photon": photon,
        "electron": electron,
        "alpha": alpha_particle,
        "alpha_recoil": alpha_recoil,
    }


#: One-line definition of the computed quantity — surfaced in the UI (honesty, §11).
DEFINITION = (
    "Decay heat = bulk recoverable decay power: mean β kinetic energy "
    "(antineutrino energy excluded), all photons (γ/X/annihilation), IC/Auger "
    "electrons, and α particle + recoil-nucleus energy (Q_α = E_α·A/(A−4)). "
    "Spontaneous-fission/fragment energy is not included (ICRP-107 per-decay lines "
    "only); negligible except SF sources, which are α-dominated anyway."
)


class DecayHeatModel:
    """Solve-once per-nuclide decay-heat coefficients (W per Bq) for an inventory.

    Build once from the nuclides of a solved inventory; :meth:`heat_series` is then a
    cheap matvec of the fixed coefficients against the activity grid (§3).
    """

    def __init__(self, nuclides: Sequence[str]):
        self.nuclides = list(nuclides)
        #: Per-nuclide recoverable energy per decay, by channel (MeV/decay).
        self.E_rec_MeV: dict[str, dict] = {}
        #: Per-nuclide coefficient: W per Bq == J per decay == Ē_rec·MEV_TO_J.
        self.coeff_w_per_bq: dict[str, float] = {}
        for nuclide in self.nuclides:
            channels = recoverable_energy_MeV(nuclide)
            self.E_rec_MeV[nuclide] = channels
            self.coeff_w_per_bq[nuclide] = channels["total"] * MEV_TO_J

    def heat(self, activities_bq: dict[str, float]) -> float:
        """Total decay heat (W) at a single time from nuclide → activity (Bq).

        Every contributing nuclide (coefficient ≠ 0) must be present — a missing one
        is a loud error, never a silent zero (CLAUDE.md no-silent-errors)."""
        total = 0.0
        for nuclide, c in self.coeff_w_per_bq.items():
            if c == 0.0:
                continue
            if nuclide not in activities_bq:
                raise DecayHeatError(
                    f"no activity supplied for heat-contributing nuclide {nuclide!r}"
                )
            total += c * float(activities_bq[nuclide])
        return total

    def heat_series(self, evaluate_result: dict) -> dict:
        """Decay-heat time series from a ``SolvedInventory.evaluate`` activity result.

        The §3 "evaluate many" path: one matvec of the fixed W-per-Bq coefficients
        against the activity grid, no per-tick re-summation. Returns the total power
        (W) and the per-nuclide breakdown (the dominant-contributor view §5/§9)."""
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise DecayHeatError(
                "heat_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series: dict[str, list[float]] = evaluate_result["series"]
        times = evaluate_result["times_s"]
        total = [0.0] * len(times)
        by_nuclide: dict[str, list[float]] = {}
        for nuclide, c in self.coeff_w_per_bq.items():
            if c == 0.0:
                continue
            if nuclide not in series:
                raise DecayHeatError(
                    f"no activity series for heat-contributing nuclide {nuclide!r}"
                )
            col = series[nuclide]
            contrib = [c * float(a) for a in col]
            by_nuclide[nuclide] = contrib
            for j, w in enumerate(contrib):
                total[j] += w
        return {
            "quantity": "decay_heat",
            "si_unit": "W",
            "times_s": list(times),
            "total_W": total,
            "by_nuclide_W": by_nuclide,
            "coeff_W_per_Bq": dict(self.coeff_w_per_bq),
            "E_rec_MeV": {n: ch["total"] for n, ch in self.E_rec_MeV.items()},
            "channels_MeV": dict(self.E_rec_MeV),
            "definition": DEFINITION,
        }
