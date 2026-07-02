"""Spent-fuel spontaneous-fission neutron dose — the multi-parent neutron source (M9).

Unlike a tabulated single-source term (Cf-252, AmBe → :mod:`engine.neutron_dose`), spent fuel
emits neutrons from MANY actinides at once, each decaying at its own rate. The source strength
is therefore intrinsic to the loaded inventory:

    S(t) = Σ_n  yield_n · A_n(t)            (neutrons/s, summed over SF emitters)
    dose_rate(t, d) = (h̄ / 4π d²) · S(t)    (Sv/s)

``yield_n`` (neutrons per decay of nuclide n) is built from the SCK-CEN ``_SF`` fission rate ×
the IAEA prompt ν̄ (see ``data/build/build_spent_fuel.py`` and the vector's ``neutron`` block);
``A_n(t)`` rides the SAME Bateman solve as every other view (§3 solve-once / evaluate-many), so
a multi-decade cooling sweep is one matvec of the fixed ``yield`` vector against the activity
grid. ``h̄`` is the spectrum-averaged fluence-to-dose coefficient (a single scalar per
quantity/geometry), folded against a **representative SF spectrum** — Cf-252's already-validated
ISO-8529 Maxwellian, justified by H*(10) flatness over 0.5–6 MeV (§11; the dominant emitter
Cm-244 is a near-identical Watt spectrum).

**Honesty (§11), surfaced never silent:**

* The source is SF + **(α,n)-on-oxygen** (M12) — a BEST ESTIMATE: for clean oxide fuel these two
  terms are essentially the complete intrinsic neutron source. The (α,n) yields are PANDA Table-13
  oxide values (``data/vendor/panda_alpha_n``), per gram of isotope → neutrons/decay; the same
  representative Cf-252 SF spectrum and shield T_n apply to both (the (α,n) spectrum is softer than
  SF, but h̄ is flat over 0.5–6 MeV — a real but small approximation). Residual ±factor on the
  thick-target (α,n) yield.
* The dominant emitters are modeled across the cooling range: SF — Cm-242 (short), Cm-244 (~1
  century), Cm-246/248 beyond (curium ν̄ sourced); (α,n) — Cm-242, then Am-241/Cm-244/Pu-238.
  Any residual from minor SF emitters without an evaluated ν̄ AND α-emitters absent from PANDA
  Table 13 is reported as the **dropped fraction** at the evaluated cooling (SF sized with a
  nominal ν̄; (α,n) with the Table-14 oxygen yield) and warned when non-negligible — so the user
  sees *how much*, if any, of the source is unmodeled (the under-count direction).
"""

from __future__ import annotations

import math
from typing import Optional

from engine import neutron_source as nsrc
from engine.neutron_dose import (
    GEOMETRIES,
    PSV_CM2_TO_SV_M2,
    QUANTITIES,
    NeutronDoseError,
    fold_spectrum,
    neutron_transmission,
)

_FOUR_PI = 4.0 * math.pi

#: Above this dropped SF-rate fraction at any evaluated time, emit a loud lower-bound warning.
_DROPPED_WARN_FRAC = 0.05


class SpentFuelNeutronModel:
    """Solve-once SF neutron-dose model for a loaded spent-fuel vector (fixed quantity/geometry).

    Parameters mirror the vector's ``neutron`` block: ``yields`` (modeled emitters,
    neutrons/decay), the representative ``spectrum_source`` key, and the ``dropped_sf_branch``
    map (+ nominal ν̄) used ONLY to size the lower-bound warning.
    """

    def __init__(
        self,
        yields: dict[str, float],
        spectrum_source: str,
        quantity: str = "ambient_H10",
        *,
        geometry: Optional[str] = None,
        dropped_sf_branch: Optional[dict[str, float]] = None,
        dropped_nubar_nominal: float = 3.0,
        alpha_n_yields: Optional[dict[str, float]] = None,
        dropped_alpha_branch: Optional[dict[str, float]] = None,
        nominal_O_yield_per_alpha: float = 5.9e-8,
        shield=None,
    ):
        if quantity not in QUANTITIES:
            raise NeutronDoseError(
                f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}"
            )
        if quantity == "effective" and geometry is None:
            raise NeutronDoseError(
                "effective dose requires an ICRP-116 geometry (e.g. 'AP', 'ISO')"
            )
        if quantity != "effective" and geometry is not None:
            raise NeutronDoseError(
                f"{quantity} takes no geometry; geometry applies only to effective dose"
            )
        if geometry is not None and geometry not in GEOMETRIES:
            raise NeutronDoseError(f"unknown geometry {geometry!r}; expected one of {GEOMETRIES}")

        self.yields = {k: float(v) for k, v in yields.items() if float(v) > 0.0}
        if not self.yields:
            raise NeutronDoseError("spent-fuel neutron model has no positive SF yields")
        self.spectrum_source = spectrum_source
        if not nsrc.has(spectrum_source):
            raise NeutronDoseError(f"representative SF spectrum {spectrum_source!r} not available")
        self.dropped_branch = {
            k: float(v) for k, v in (dropped_sf_branch or {}).items() if float(v) > 0.0
        }
        self.dropped_nubar = float(dropped_nubar_nominal)
        #: (α,n)-on-oxygen yields (M12), added to the SF source. Same representative spectrum and
        #: shield T_n (the (α,n) spectrum is softer than SF but h̄ is flat over 0.5–6 MeV — §11).
        self.alpha_n_yields = {
            k: float(v) for k, v in (alpha_n_yields or {}).items() if float(v) > 0.0
        }
        #: α-emitters absent from PANDA Table 13: branch (α/decay) × this nominal O-yield bounds
        #: their unmodeled (α,n) for the residual warning (never enters the dose).
        self.dropped_alpha_branch = {
            k: float(v) for k, v in (dropped_alpha_branch or {}).items() if float(v) > 0.0
        }
        self.nominal_O_yield = float(nominal_O_yield_per_alpha)

        self.quantity = quantity
        self.geometry = geometry
        self.si_unit = "Sv"
        self.warnings: list[dict] = []
        #: Spectrum-averaged coefficient h̄ (pSv·cm²) and per-neutron SI dose coefficient.
        self.hbar_pSv_cm2, warns = fold_spectrum(spectrum_source, quantity, geometry)
        self.warnings.extend(warns)
        #: Fast-neutron shield transmission T_n (M10) — a single scalar folded into ``coeff_si``;
        #: h̄ is untouched (no spectrum hardening). The same removal-cross-section gate as the
        #: single-source path (hydrogenous attenuates; γ-oriented stack → T_n=1 + loud warning).
        self.T_n, shield_warnings = neutron_transmission(shield)
        self.warnings.extend(shield_warnings)
        self.coeff_si = self.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2 * self.T_n

    def _geometric_factor(self, distance_m: float) -> float:
        if distance_m <= 0.0:
            raise NeutronDoseError(
                f"distance must be > 0 m (the point-source field is singular at 0); got {distance_m}"
            )
        return 1.0 / (_FOUR_PI * distance_m * distance_m)

    def dose_rate_series(self, evaluate_result: dict, distance_m: float) -> dict:
        """Spent-fuel neutron dose-rate series (Sv/s) from a ``SolvedInventory.evaluate`` result.

        Sums BOTH terms — S(t) = S_sf(t) + S_an(t), each Σ yield_n·A_n(t) over the modeled
        emitters (SF from ν̄; (α,n)-on-oxygen from PANDA, M12) — scales by h̄·T_n/4πd², and
        returns the SF/(α,n) split plus the per-time **dropped fraction**: the unmodeled residual
        from minor SF emitters without an evaluated ν̄ AND α-emitters absent from PANDA Table 13.
        A modeled emitter missing from the activity series is a loud error (never a silent zero)."""
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise NeutronDoseError(
                "dose_rate_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series = evaluate_result["series"]
        missing = [n for n in (self.yields | self.alpha_n_yields) if n not in series]
        if missing:
            raise NeutronDoseError(
                f"neutron emitter(s) {missing} absent from the activity series — the spent-fuel "
                "neutron source would be silently incomplete"
            )
        times = evaluate_result["times_s"]
        n_t = len(times)
        geom = self._geometric_factor(distance_m)
        k = geom * self.coeff_si

        rates: list[float] = []
        rates_sf: list[float] = []
        rates_an: list[float] = []
        dropped_frac: list[float] = []  # combined unmodeled residual (SF ν̄ + (α,n))
        dropped_sf_frac: list[float] = []  # SF-ν̄-only residual
        dropped_an_frac: list[float] = []  # (α,n)-only residual
        for i in range(n_t):
            s_sf = math.fsum(y * float(series[n][i]) for n, y in self.yields.items())
            s_an = math.fsum(y * float(series[n][i]) for n, y in self.alpha_n_yields.items())
            s = s_sf + s_an
            rates.append(k * s)
            rates_sf.append(k * s_sf)
            rates_an.append(k * s_an)
            s_drop_sf = self.dropped_nubar * math.fsum(
                b * float(series[n][i]) for n, b in self.dropped_branch.items() if n in series
            )
            s_drop_an = self.nominal_O_yield * math.fsum(
                b * float(series[n][i]) for n, b in self.dropped_alpha_branch.items() if n in series
            )
            s_drop = s_drop_sf + s_drop_an
            denom = s + s_drop
            dropped_frac.append(s_drop / denom if denom > 0.0 else 0.0)
            dropped_sf_frac.append(s_drop_sf / denom if denom > 0.0 else 0.0)
            dropped_an_frac.append(s_drop_an / denom if denom > 0.0 else 0.0)

        max_drop = max(dropped_frac) if dropped_frac else 0.0
        if max_drop > _DROPPED_WARN_FRAC:
            self.warnings.append(
                {
                    "reason": "dropped_unmodeled_neutron",
                    "max_dropped_frac": max_drop,
                    "message": (
                        f"up to {max_drop:.0%} of the neutron source at this cooling comes from "
                        "minor SF emitters without an evaluated ν̄ and/or α-emitters absent from "
                        "the PANDA (α,n) table, and is NOT in the dose — the modeled output is a "
                        "lower bound here (under-count) by that amount"
                    ),
                }
            )

        return {
            "quantity": self.quantity,
            "si_unit": self.si_unit,
            "per": "second",
            "times_s": list(times),
            "distance_m": distance_m,
            "source": "spent-fuel SF + (α,n)",
            "spectrum_source": self.spectrum_source,
            "spectrum_avg_coeff_pSv_cm2": self.hbar_pSv_cm2,
            "neutron_transmission": self.T_n,
            "rate_si": rates,
            "rate_si_sf": rates_sf,
            "rate_si_alpha_n": rates_an,
            "dropped_frac": dropped_frac,
            "dropped_sf_frac": dropped_sf_frac,
            "dropped_an_frac": dropped_an_frac,
            "warnings": list(self.warnings),
        }
