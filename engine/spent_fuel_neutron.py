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

* SF only — (α,n) on the oxygen in UO₂ is NOT in the dataset, so the result is a LOWER BOUND.
* The dominant SF emitters are modeled across the cooling range: Cm-242 at short cooling,
  Cm-244 through ~1 century, and Cm-246/248 beyond (the curium ν̄ now sourced — see
  ``data/build/build_spent_fuel.py``). Any residual SF rate from minor emitters that still
  lack an evaluated ν̄ is reported as the **dropped SF-rate fraction** at the evaluated cooling
  time (estimated with a nominal ν̄) and warned when non-negligible — so the user sees *how
  much*, if any, of the source is unmodeled, in the dangerous (under-count) direction. For the
  shipped vectors this stays well under 0.1 % out to 1 Myr.
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
    ):
        if quantity not in QUANTITIES:
            raise NeutronDoseError(f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}")
        if quantity == "effective" and geometry is None:
            raise NeutronDoseError("effective dose requires an ICRP-116 geometry (e.g. 'AP', 'ISO')")
        if quantity != "effective" and geometry is not None:
            raise NeutronDoseError(f"{quantity} takes no geometry; geometry applies only to effective dose")
        if geometry is not None and geometry not in GEOMETRIES:
            raise NeutronDoseError(f"unknown geometry {geometry!r}; expected one of {GEOMETRIES}")

        self.yields = {k: float(v) for k, v in yields.items() if float(v) > 0.0}
        if not self.yields:
            raise NeutronDoseError("spent-fuel neutron model has no positive SF yields")
        self.spectrum_source = spectrum_source
        if not nsrc.has(spectrum_source):
            raise NeutronDoseError(f"representative SF spectrum {spectrum_source!r} not available")
        self.dropped_branch = {k: float(v) for k, v in (dropped_sf_branch or {}).items() if float(v) > 0.0}
        self.dropped_nubar = float(dropped_nubar_nominal)

        self.quantity = quantity
        self.geometry = geometry
        self.si_unit = "Sv"
        self.warnings: list[dict] = []
        #: Spectrum-averaged coefficient h̄ (pSv·cm²) and per-neutron SI dose coefficient.
        self.hbar_pSv_cm2, warns = fold_spectrum(spectrum_source, quantity, geometry)
        self.warnings.extend(warns)
        self.coeff_si = self.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2

    def _geometric_factor(self, distance_m: float) -> float:
        if distance_m <= 0.0:
            raise NeutronDoseError(
                f"distance must be > 0 m (the point-source field is singular at 0); got {distance_m}"
            )
        return 1.0 / (_FOUR_PI * distance_m * distance_m)

    def dose_rate_series(self, evaluate_result: dict, distance_m: float) -> dict:
        """SF neutron dose-rate series (Sv/s) from a ``SolvedInventory.evaluate`` activity result.

        Sums S(t)=Σ yield_n·A_n(t) over the modeled emitters, scales by h̄/4πd², and reports the
        per-time dropped SF-rate fraction (the unmodeled lower-bound gap). A modeled emitter
        missing from the activity series is a loud error (never a silent zero)."""
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise NeutronDoseError(
                "dose_rate_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series = evaluate_result["series"]
        missing = [n for n in self.yields if n not in series]
        if missing:
            raise NeutronDoseError(
                f"SF emitter(s) {missing} absent from the activity series — the spent-fuel neutron "
                "source would be silently incomplete"
            )
        times = evaluate_result["times_s"]
        n_t = len(times)
        geom = self._geometric_factor(distance_m)

        rates: list[float] = []
        dropped_frac: list[float] = []
        for i in range(n_t):
            s = math.fsum(y * float(series[n][i]) for n, y in self.yields.items())
            rates.append(geom * self.coeff_si * s)
            s_drop = self.dropped_nubar * math.fsum(
                b * float(series[n][i]) for n, b in self.dropped_branch.items() if n in series
            )
            dropped_frac.append(s_drop / (s + s_drop) if (s + s_drop) > 0.0 else 0.0)

        max_drop = max(dropped_frac) if dropped_frac else 0.0
        if max_drop > _DROPPED_WARN_FRAC:
            self.warnings.append(
                {
                    "reason": "dropped_sf_unmodeled",
                    "max_dropped_frac": max_drop,
                    "message": (
                        f"up to {max_drop:.0%} of the SF neutron source at this cooling comes from "
                        "minor emitters without an evaluated ν̄ and is NOT in the dose — "
                        "the modeled neutron output is a lower bound (under-count)"
                    ),
                }
            )

        return {
            "quantity": self.quantity,
            "si_unit": self.si_unit,
            "per": "second",
            "times_s": list(times),
            "distance_m": distance_m,
            "source": "spent-fuel SF",
            "spectrum_source": self.spectrum_source,
            "spectrum_avg_coeff_pSv_cm2": self.hbar_pSv_cm2,
            "rate_si": rates,
            "dropped_sf_frac": dropped_frac,
            "warnings": list(self.warnings),
        }
