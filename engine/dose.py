"""External gamma dose engine — point source, single-layer shield (HANDOFF_PLAN.md §6).

The §6 photon chain, factored so it obeys §3 ("solve once, evaluate many") at the dose
layer too:

    dose_rate(t, d) = (1 / 4π d²) · Σ_nuclides C_n · A_n(t)
    C_n = Σ_lines [ per-line constant ]_i · [ shield factor ]_i        (one scalar / nuclide)

The per-nuclide coefficient ``C_n`` depends on the dose **quantity**, the **medium**, and
the **shield** — but NOT on distance, time, or activity. So a multi-decade time slider is a
single matvec of the fixed ``C_n`` against the activity series from
``inventory.SolvedInventory.evaluate``; distance is a free scalar (1/4πd² factors out of
every quantity). Only a shield/quantity change re-folds ``C_n``.

Three quantities (§6.4):

* ``air_kerma`` — air-kerma rate (Gy/s). The quantitatively-defensible reference path
  (validated against the Co-60 / Cs-137 air-kerma constants); per-line constant
  ``E·y·(μ_en/ρ)_air``. Medium defaults to air; tissue/water are a trivial extension.
* ``ambient_H10`` — ambient dose equivalent H*(10) (Sv/s); the §6.4 default operational
  quantity (what a survey meter reads). Per-line constant ``y · h*(10)/Φ(E)``.
* ``effective`` — effective dose E (Sv/s), per ICRP-116 irradiation geometry
  (AP/PA/LLAT/RLAT/ROT/ISO). Per-line constant ``y · e/Φ(E, geometry)``.

The **shield factor** ``B(E, μx)·exp(−μx)`` multiplies the photon *fluence*, so it is the
same across all three quantities. The buildup ``B`` applied is the **air-kerma (exposure)**
buildup for every quantity — a documented approximation (B of dose-equivalent ≠ B of
air-kerma); see HANDOFF_PLAN §11.

No silent errors (CLAUDE.md), at the right severity (advisor): a photon line **below** a
table floor (sub-keV X-rays, sub-10-keV for scoring) is a *logged skip* — negligible dose,
recorded in ``warnings``; a line **above** a grid end is a loud :class:`DoseError`, because
dropping a high-energy line *underestimates* dose (the dangerous direction). A shield made
of a material with no ANS-6.4.3 buildup (PMMA, polyethylene, soft tissue) fails loudly,
never a silent B=1 surrogate (§6.5).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from engine import attenuation as attenuation
from engine import buildup as buildup
from engine import emissions as emissions
from engine import photon_interp as pi

#: Supported dose quantities (§6.4). ``air_kerma`` is the validation/teaching reference;
#: ``ambient_H10`` is the operational default; ``effective`` needs an ICRP-116 geometry.
QUANTITIES: tuple[str, ...] = ("air_kerma", "ambient_H10", "effective")

# --- SI conversions, centralized in one place (§12: store internally in SI) ----------
MEV_TO_J = 1.602176634e-13  # J per MeV
CM2_PER_G_TO_M2_PER_KG = 0.1  # (cm²/g) → (m²/kg):  1e-4 m² / 1e-3 kg
PSV_CM2_TO_SV_M2 = 1.0e-16  # (pSv·cm²) → (Sv·m²): 1e-12 Sv · 1e-4 m²
_FOUR_PI = 4.0 * math.pi

#: Dose-**scoring** floor δ (MeV): photon lines below 10 keV are logged skips for ALL
#: quantities. This is the low-energy cutoff that *defines* the air-kerma-rate constant
#: Γ_δ — sub-δ photons don't penetrate to a detector at distance (a 4 keV X-ray transmits
#: ~0.1 % through 1 m of air), and conventional δ ∈ 10–30 keV all give the same answer
#: (the next lines up are ~32 keV K X-rays). It is distinct from the 1 keV attenuation
#: *table* floor, which only bounds shield μ look-ups for already-scored (≥10 keV) lines.
#: H*(10)/effective already enforce this via the conversion grid's 10 keV floor; this makes
#: air_kerma consistent. See HANDOFF_PLAN §11.
SCORING_FLOOR_MEV = 0.010

#: Base SI unit of each quantity's dose rate (per second).
_SI_UNIT = {"air_kerma": "Gy", "ambient_H10": "Sv", "effective": "Sv"}


class DoseError(Exception):
    """Loud failure in the gamma-dose path — never swallowed, never a fallback number.

    Carries an optional ``reason`` (e.g. :data:`engine.photon_interp.ABOVE_GRID`) when it
    originates from an off-grid energy that must not be silently dropped.
    """

    def __init__(self, message: str, *, reason: Optional[str] = None):
        super().__init__(message)
        self.reason = reason


def _normalize_shield(shield) -> Optional[list[tuple[str, float]]]:
    """Normalize any accepted shield spec to an ordered layer list (source→detector).

    Accepts ``None``, a single ``(material, thickness_cm)`` 2-tuple (a Python convenience,
    promoted to a one-layer stack), or a sequence of such layers. The **last** layer is
    adjacent to the detector — the buildup material in the last-layer approximation
    (§6.4, §13 #2). One normalize path so the order convention has a single owner.

    Discriminator: a string first element ⇒ a bare ``(material, cm)`` tuple; a sequence
    first element ⇒ a layer list. An empty stack normalizes to ``None`` (no shield).
    """
    if shield is None:
        return None
    try:
        n = len(shield)
    except TypeError as exc:
        raise DoseError(
            f"shield must be None, (material, cm), or [(material, cm), …]; got {shield!r}"
        ) from exc
    if n == 0:
        return None
    raw_layers = [shield] if isinstance(shield[0], str) else list(shield)
    out: list[tuple[str, float]] = []
    for layer in raw_layers:
        try:
            material, thickness_cm = layer
        except (TypeError, ValueError) as exc:
            raise DoseError(
                f"shield layer must be (material, thickness_cm); got {layer!r}"
            ) from exc
        thickness_cm = float(thickness_cm)
        if thickness_cm < 0.0:
            raise DoseError(f"shield thickness must be >= 0 cm; got {thickness_cm}")
        out.append((str(material), thickness_cm))
    return out or None


def transmission(material: str, E_MeV: float, thickness_cm: float) -> float:
    """Broad-beam transmission ``B(E, μx)·exp(−μx)`` of a single ``material`` layer.

    The point-kernel shield factor (§6.5): narrow-beam attenuation ``exp(−μx)`` corrected by
    the exposure buildup ``B`` for scattered photons. ``μ = (μ/ρ)·ρ`` (cm⁻¹), ``x`` in cm,
    ``μx`` in mean free paths. Off-grid energies raise :class:`OffGridError`. The
    :func:`stack_transmission` n=1 case is bit-for-bit identical to this.
    """
    mu_lin = pi.interp_mu_rho(material, E_MeV) * attenuation.density(material)  # cm⁻¹
    mfp = mu_lin * thickness_cm
    b = pi.interp_buildup(material, E_MeV, mfp)
    return b * math.exp(-mfp)


def stack_transmission(layers: Sequence[tuple[str, float]], E_MeV: float) -> float:
    """Broad-beam transmission of an ordered layer stack (source-side → detector-side).

    The **last-layer / total-mfp** approximation (§6.4, §13 #2 — LOCKED):

        T(E) = B_L(E, Σᵢ μᵢxᵢ) · exp(−Σᵢ μᵢxᵢ)        L = the last (detector-side) layer

    Narrow-beam attenuation ``exp(−Σ μx)`` is **exact** and order-invariant — the stack just
    sums mean-free-paths. The buildup ``B`` is the *only* approximation: it is taken for the
    detector-side material over the whole penetration depth. Reduces bit-for-bit to
    :func:`transmission` for n=1 (then L is the only layer).

    **Per-layer gate (no silent surrogate, §6.5):** *every* layer's material must have
    ANS-6.4.3 buildup data, not just the detector-side one — a non-buildup layer mid-stack
    would otherwise contribute attenuation only, an invisible underestimate. A layer with no
    buildup raises :class:`engine.buildup.BuildupError`; off-grid energies raise OffGridError.
    """
    layers = list(layers)
    if not layers:
        return 1.0
    total_mfp = 0.0
    for material, thickness_cm in layers:
        if not buildup.has_material(material):
            # Force the same loud failure the last-layer interp_buildup would give, but for
            # an interior layer too — never let it slip through as attenuation-only.
            raise buildup.BuildupError(
                f"shield layer {material!r} has no ANS-6.4.3 buildup data; every layer in a "
                "stack must have buildup (no silent attenuation-only surrogate, §6.5)."
            )
        mu_lin = pi.interp_mu_rho(material, E_MeV) * attenuation.density(material)  # cm⁻¹
        total_mfp += mu_lin * thickness_cm
    b = pi.interp_buildup(layers[-1][0], E_MeV, total_mfp)  # detector-side material
    return b * math.exp(-total_mfp)


class GammaDoseModel:
    """Solve-once per-nuclide dose coefficients for a fixed (quantity, medium, shield).

    Build once from the nuclides in a solved inventory; then :meth:`dose_rate` /
    :meth:`dose_rate_series` are cheap (no per-call line summation).
    """

    def __init__(
        self,
        nuclides: Sequence[str],
        quantity: str = "ambient_H10",
        *,
        medium: str = "air",
        shield=None,
        geometry: Optional[str] = None,
        photon_override: Optional[dict[str, list[dict]]] = None,
    ):
        if quantity not in QUANTITIES:
            raise DoseError(f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}")
        if quantity == "effective" and geometry is None:
            raise DoseError("effective dose requires an ICRP-116 geometry (e.g. 'AP', 'ISO')")
        if quantity != "effective" and geometry is not None:
            raise DoseError(
                f"{quantity} takes no geometry; geometry applies only to effective dose"
            )

        self.quantity = quantity
        self.medium = medium
        self.geometry = geometry
        self.shield = _normalize_shield(shield)
        self.si_unit = _SI_UNIT[quantity]
        #: Optional per-nuclide photon line list that **replaces** the nuclide's bundled
        #: ICRP-107 photon spectrum — used to score a *synthetic* photon source (e.g. M4
        #: beta-bremsstrahlung lines) through the identical per-line/quantity/scoring-floor
        #: machinery. ``None`` ⇒ use ``emissions.photons`` as usual.
        self.photon_override = photon_override or {}
        self.nuclides = list(nuclides)
        self.warnings: list[dict] = []
        #: Per-nuclide SI dose coefficient (J·m²/kg per decay for air_kerma; Sv·m² per
        #: decay for H*(10)/effective). ``dose_rate = (1/4πd²)·Σ C_n·A_n``.
        self.coeff_si: dict[str, float] = {}
        #: Per-nuclide, per-line scored contributions (the §9 per-line γ table source,
        #: M6f-2). Each row ``{E_MeV, yield, origin, coeff_si}`` where ``coeff_si =
        #: const·y·shield`` is the DISTANCE-FREE, per-decay SI per-line constant. By
        #: construction ``sum(row.coeff_si) == coeff_si[nuclide]`` (one assembly path, no
        #: drift), so the per-line table reconciles EXACTLY with the total dose. Below-floor
        #: lines are absent (logged in :attr:`warnings`); above-grid lines still raise.
        self.lines_si: dict[str, list[dict]] = {}

        for nuclide in self.nuclides:
            rows = self._lines_for(nuclide)
            self.lines_si[nuclide] = rows
            # Sequential float sum in line order — identical accumulation to the prior
            # ``total += …`` so the M3 benchmark coefficients are bit-for-bit unchanged.
            self.coeff_si[nuclide] = sum(r["coeff_si"] for r in rows)

    # -- coefficient assembly (solve once) --------------------------------

    def _per_line_constant_si(self, E_MeV: float) -> float:
        """Scoring constant per photon (SI), before yield/activity. Raises OffGridError."""
        if self.quantity == "air_kerma":
            if E_MeV < SCORING_FLOOR_MEV and not math.isclose(
                E_MeV, SCORING_FLOOR_MEV, rel_tol=1e-9
            ):
                # The Γ_δ low-energy cutoff: sub-10-keV photons don't penetrate to a
                # detector at distance. Logged skip (same severity as the conversion-grid
                # floor that H*(10)/effective already apply), never silent.
                raise pi.OffGridError(
                    pi.BELOW_FLOOR,
                    f"air_kerma: photon {E_MeV:g} MeV is below the {SCORING_FLOOR_MEV * 1e3:g} keV "
                    "dose-scoring floor δ (does not penetrate to distance)",
                    E_MeV=E_MeV,
                    bound=SCORING_FLOOR_MEV,
                )
            muen = pi.interp_muen_rho(self.medium, E_MeV) * CM2_PER_G_TO_M2_PER_KG  # m²/kg
            return E_MeV * MEV_TO_J * muen  # J·m²/kg
        coeff = pi.interp_conversion(self.quantity, E_MeV, self.geometry)  # pSv·cm²
        return coeff * PSV_CM2_TO_SV_M2  # Sv·m²

    def _shield_factor(self, E_MeV: float) -> float:
        if self.shield is None:
            return 1.0
        return stack_transmission(self.shield, E_MeV)

    def _lines_for(self, nuclide: str) -> list[dict]:
        """Scored photon lines for ``nuclide``: ``[{E_MeV, yield, origin, coeff_si}]`` where
        ``coeff_si = const_i · y_i · shield_i`` (SI per decay, distance-free). The single
        coefficient-assembly path: :attr:`coeff_si` is the sum of these rows and the §9
        per-line table is the rows themselves, so the two can never drift. Stable / no-photon
        nuclides yield ``[]``; below-floor lines are logged skips (absent from the rows);
        above-grid lines raise (dropping a high-energy line underestimates dose — §11)."""
        override = self.photon_override.get(nuclide)
        if override is None:
            if not emissions.has_emissions(nuclide):
                return []  # stable daughter — legitimately no emission, not a data hole
            lines = emissions.photons(nuclide)
        else:
            lines = override  # synthetic source (e.g. bremsstrahlung); bypasses has_emissions

        rows: list[dict] = []
        for line in lines:
            E = float(line["E_MeV"])
            y = float(line["yield"])
            if y <= 0.0:
                continue
            try:
                const = self._per_line_constant_si(E)
                shield = self._shield_factor(E)
            except pi.OffGridError as off:
                if off.reason == pi.BELOW_FLOOR:
                    self.warnings.append(
                        {
                            "nuclide": nuclide,
                            "E_MeV": E,
                            "yield": y,
                            "origin": line.get("origin"),
                            "reason": pi.BELOW_FLOOR,
                            "message": str(off),
                        }
                    )
                    continue
                # ABOVE_GRID: dropping a high-energy line underestimates dose — surface it.
                raise DoseError(
                    f"{nuclide}: photon line {E:g} MeV (yield {y:g}) is above the "
                    f"{self.quantity} grid — refusing to extrapolate ({off}).",
                    reason=off.reason,
                ) from off
            rows.append(
                {
                    "E_MeV": E,
                    "yield": y,
                    "origin": line.get("origin"),
                    "coeff_si": const * y * shield,
                }
            )
        return rows

    def per_line_rows(self) -> list[dict]:
        """Flatten the per-nuclide scored photon lines into one list (the §9 per-line γ
        table source: "the gamma slice expands to a per-line table"). Each row is
        ``{nuclide, E_MeV, yield, origin, coeff_si}`` with ``coeff_si`` the DISTANCE- and
        TIME-FREE per-decay SI constant (Sv·m² per decay for H*(10)/effective; J·m²/kg for
        air_kerma). The caller applies ``1/4πd²`` and the parent activity ``A_n(t)`` at the
        cursor, so the table is live on scrub/distance with no re-fold (§3). A nuclide's rows
        sum to :attr:`coeff_si` exactly; below-floor lines are absent (see :attr:`warnings`)."""
        out: list[dict] = []
        for nuclide in self.nuclides:
            for row in self.lines_si.get(nuclide, []):
                out.append({"nuclide": nuclide, **row})
        return out

    # -- evaluation (evaluate many) ---------------------------------------

    def _geometric_factor(self, distance_m: float) -> float:
        if distance_m <= 0.0:
            raise DoseError(
                f"distance must be > 0 m (the point-source field is singular at 0); "
                f"got {distance_m}"
            )
        return 1.0 / (_FOUR_PI * distance_m * distance_m)

    def dose_rate(self, activities_bq: dict[str, float], distance_m: float) -> float:
        """Dose rate (SI per second: Gy/s for air_kerma, Sv/s otherwise) at a single time.

        ``activities_bq`` maps nuclide → activity (Bq). Every contributing nuclide
        (coefficient ≠ 0) must be present — a missing one is a loud error, never a silent
        zero.
        """
        geom = self._geometric_factor(distance_m)
        total = 0.0
        for nuclide, c_n in self.coeff_si.items():
            if c_n == 0.0:
                continue
            if nuclide not in activities_bq:
                raise DoseError(f"no activity supplied for contributing nuclide {nuclide!r}")
            total += c_n * float(activities_bq[nuclide])
        return geom * total

    def dose_rate_series(self, evaluate_result: dict, distance_m: float) -> dict:
        """Dose-rate time series from a ``SolvedInventory.evaluate`` activity result.

        This is the §3 "evaluate many" path: one matvec of the fixed ``C_n`` against the
        activity grid, no per-tick re-summation. Returns the rate per second in
        :attr:`si_unit`, plus the off-grid ``warnings`` recorded at build time.
        """
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise DoseError(
                "dose_rate_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        geom = self._geometric_factor(distance_m)
        series: dict[str, list[float]] = evaluate_result["series"]
        times = evaluate_result["times_s"]
        rates = [0.0] * len(times)
        for nuclide, c_n in self.coeff_si.items():
            if c_n == 0.0:
                continue
            if nuclide not in series:
                raise DoseError(f"no activity series for contributing nuclide {nuclide!r}")
            col = series[nuclide]
            for j, a in enumerate(col):
                rates[j] += c_n * float(a)
        rates = [geom * r for r in rates]
        return {
            "quantity": self.quantity,
            "si_unit": self.si_unit,
            "per": "second",
            "times_s": list(times),
            "distance_m": distance_m,
            "rate_si": rates,
            "scoring_floor_MeV": SCORING_FLOOR_MEV,
            "warnings": list(self.warnings),
        }
