"""External neutron dose engine — prebuilt point source (HANDOFF_PLAN.md §6.3).

v1 does **not** derive neutron output from a loaded inventory (SF + (α,n) is ORIGEN/SOURCES
territory); it scores a **tabulated** prebuilt source (Cf-252, …; §8). Neutron output is
grayed out for user-defined inventories — the gate is "is there a source key?", enforced at
the bridge.

The dose chain, factored so it obeys §3 ("solve once, evaluate many") at the dose layer too:

    dose_rate(t, d) = (neutrons_per_decay · A_parent(t) / 4π d²) · h̄
    h̄ = Σ_bins φ_i · h(E_i)            (one scalar per source/quantity/geometry)

``h̄`` is the **spectrum-averaged** fluence-to-dose coefficient: the normalized per-bin
fluence fractions ``φ_i`` (Σ = 1) folded against the neutron ICRP-74/ICRP-116 coefficient at
each bin's representative energy. It depends on the source, the dose **quantity**, and the
**geometry** — but NOT on distance, time, or activity. So a multi-decade time slider is a
single matvec of the fixed per-decay coefficient ``C = neutrons_per_decay · h̄`` against the
parent's activity series; distance is a free scalar (1/4πd²). Only a quantity/geometry change
re-folds ``h̄``.

Two quantities (§6.4), both **Sv** (the conversion coefficients already fold the radiation
weighting w_R(E) — it is **NOT** applied again here):

* ``ambient_H10`` — ambient dose equivalent H*(10) (ICRP-74); operational default. No geometry.
* ``effective``   — effective dose E (ICRP-116) per irradiation geometry AP/PA/LLAT/RLAT/ROT/ISO.

No silent errors (CLAUDE.md), at the right severity (mirrors the gamma engine): a spectrum
bin **below** the conversion-grid floor (thermal 1e-9 MeV) is a logged skip recorded in
``warnings`` (negligible); a bin **above** the grid end (20 MeV for H*(10)) is a loud
:class:`NeutronDoseError`, because dropping flux *underestimates* dose (the dangerous
direction). Source-correlated γ (AmBe 4.438 MeV, …) is scored separately through the gamma
engine via :meth:`source_gamma_override`.
"""

from __future__ import annotations

import math
from typing import Optional

from engine import neutron_source as nsrc
from engine import photon_interp as pi

#: Supported dose quantities (§6.4). Both are Sv; ``effective`` needs an ICRP-116 geometry.
QUANTITIES: tuple[str, ...] = ("ambient_H10", "effective")
GEOMETRIES: tuple[str, ...] = ("AP", "PA", "LLAT", "RLAT", "ROT", "ISO")

# (pSv·cm²) → (Sv·m²): 1e-12 Sv · 1e-4 m². Same factor as the gamma engine (§12: store SI).
PSV_CM2_TO_SV_M2 = 1.0e-16
_FOUR_PI = 4.0 * math.pi


class NeutronDoseError(Exception):
    """Loud failure in the neutron-dose path — never swallowed, never a fallback number."""


def fold_spectrum(source_key: str, quantity: str, geometry: Optional[str]) -> tuple[float, list[dict]]:
    """h̄ = Σ_bins φ_i · h(E_rep_i) in pSv·cm² for a tabulated neutron spectrum (Σ φ = 1).

    The spectrum-averaged fluence-to-dose coefficient, shared by the single-source
    :class:`NeutronDoseModel` and the spent-fuel multi-parent model (both fold the SAME way —
    only the source of the per-decay strength differs). Below-floor bins are logged skips; a
    bin **above** the conversion grid is a loud error (dropping flux underestimates dose, the
    dangerous direction). Returns ``(hbar_pSv_cm2, warnings)``.
    """
    frac = nsrc.spectrum(source_key)[2]
    reps = nsrc.representative_energies(source_key)
    warnings: list[dict] = []
    hbar = 0.0
    skipped_frac = 0.0
    for f, e in zip(frac, reps):
        if f <= 0.0:
            continue
        try:
            coeff = pi.interp_conversion(quantity, e, geometry, particle="neutron")
        except pi.OffGridError as off:
            if off.reason == pi.BELOW_FLOOR:
                skipped_frac += f
                warnings.append(
                    {"source": source_key, "E_MeV": e, "fluence_frac": f,
                     "reason": pi.BELOW_FLOOR, "message": str(off)}
                )
                continue
            raise NeutronDoseError(
                f"{source_key}: spectrum bin at {e:g} MeV (fraction {f:g}) is above the "
                f"neutron {quantity} grid — refusing to extrapolate ({off})."
            ) from off
        hbar += f * coeff
    if skipped_frac > 0.0:
        warnings.append(
            {"source": source_key, "reason": "below_floor_total", "skipped_fluence_frac": skipped_frac,
             "message": (f"{skipped_frac:.3g} of the fluence is below the neutron conversion-grid "
                         "floor and was dropped (negligible thermal tail)")}
        )
    return hbar, warnings


class NeutronDoseModel:
    """Solve-once neutron dose coefficient for a fixed (source, quantity, geometry).

    Build once from a prebuilt source key; then :meth:`dose_rate` / :meth:`dose_rate_series`
    are cheap (no per-call spectrum fold).
    """

    def __init__(
        self,
        source_key: str,
        quantity: str = "ambient_H10",
        *,
        geometry: Optional[str] = None,
    ):
        if quantity not in QUANTITIES:
            raise NeutronDoseError(
                f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}"
            )
        if quantity == "effective" and geometry is None:
            raise NeutronDoseError("effective dose requires an ICRP-116 geometry (e.g. 'AP', 'ISO')")
        if quantity != "effective" and geometry is not None:
            raise NeutronDoseError(
                f"{quantity} takes no geometry; geometry applies only to effective dose"
            )

        try:
            self.source = source_key
            self.parent = nsrc.parent_nuclide(source_key)
            self.neutrons_per_decay = nsrc.neutrons_per_decay(source_key)
        except nsrc.NeutronSourceError as exc:
            # Re-surface as a dose error so the bridge's structured-error set covers it, but
            # keep the underlying message (no swallowing).
            raise NeutronDoseError(str(exc)) from exc

        self.quantity = quantity
        self.geometry = geometry
        self.si_unit = "Sv"
        self.warnings: list[dict] = []
        #: Spectrum-averaged coefficient h̄ in pSv·cm² (exposed for transparency/validation).
        self.hbar_pSv_cm2 = self._fold_spectrum()
        #: Per-PARENT-DECAY SI dose coefficient (Sv·m² per decay): dose_rate = (C/4πd²)·A_parent.
        self.coeff_si = self.neutrons_per_decay * self.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2

    # -- coefficient assembly (solve once) --------------------------------

    def _fold_spectrum(self) -> float:
        """h̄ = Σ_bins φ_i · h(E_rep_i) in pSv·cm² (shared :func:`fold_spectrum`)."""
        hbar, warns = fold_spectrum(self.source, self.quantity, self.geometry)
        self.warnings.extend(warns)
        return hbar

    def source_gamma_override(self) -> dict[str, list[dict]]:
        """``{parent: [{E_MeV, yield}]}`` for scoring source-correlated γ through the gamma
        engine's ``photon_override`` (reaction γ are NOT in the ICRP-107 decay lines). Empty
        when the source has no modeled γ (e.g. Cf-252 prompt-fission γ, §11)."""
        lines = [
            {"E_MeV": float(g["E_MeV"]), "yield": float(g["yield_per_decay"]), "origin": "source_gamma"}
            for g in nsrc.source_gammas(self.source)
            if float(g.get("yield_per_decay", 0.0)) > 0.0
        ]
        return {self.parent: lines} if lines else {}

    # -- evaluation (evaluate many) ---------------------------------------

    def _geometric_factor(self, distance_m: float) -> float:
        if distance_m <= 0.0:
            raise NeutronDoseError(
                f"distance must be > 0 m (the point-source field is singular at 0); got {distance_m}"
            )
        return 1.0 / (_FOUR_PI * distance_m * distance_m)

    def dose_rate(self, activities_bq: dict[str, float], distance_m: float) -> float:
        """Neutron dose rate (Sv/s) at a single time. ``activities_bq`` must carry the parent."""
        geom = self._geometric_factor(distance_m)
        if self.parent not in activities_bq:
            raise NeutronDoseError(
                f"no activity supplied for the source parent {self.parent!r} "
                f"(needed to scale the tabulated neutron term)"
            )
        return geom * self.coeff_si * float(activities_bq[self.parent])

    def dose_rate_series(self, evaluate_result: dict, distance_m: float) -> dict:
        """Neutron dose-rate time series from a ``SolvedInventory.evaluate`` activity result.

        The §3 "evaluate many" path: one matvec of the fixed per-decay coefficient against the
        parent's activity grid, no per-tick re-fold. Rate per second in Sv.
        """
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise NeutronDoseError(
                "dose_rate_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series = evaluate_result["series"]
        if self.parent not in series:
            raise NeutronDoseError(
                f"no activity series for the source parent {self.parent!r}"
            )
        geom = self._geometric_factor(distance_m)
        times = evaluate_result["times_s"]
        parent_col = series[self.parent]
        rates = [geom * self.coeff_si * float(a) for a in parent_col]
        return {
            "quantity": self.quantity,
            "si_unit": self.si_unit,
            "per": "second",
            "times_s": list(times),
            "distance_m": distance_m,
            "source": self.source,
            "parent": self.parent,
            "neutrons_per_decay": self.neutrons_per_decay,
            "spectrum_avg_coeff_pSv_cm2": self.hbar_pSv_cm2,
            "rate_si": rates,
            "warnings": list(self.warnings),
        }
