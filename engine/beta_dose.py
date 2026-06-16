"""External **beta skin-dose** engine — point source, Loevinger kernel (HANDOFF_PLAN §6.2).

External beta is a *skin-dose* problem: absorbed dose to the **7 mg/cm² basal layer**
(0.07 mm), averaged over **1 cm²** (the 10 CFR 20.1201(c) shallow-dose quantity, also
what VARSKIN reports). We apply the **Loevinger** beta point-source dose-distribution
function (arXiv physics/0310150, reproducing Loevinger 1956) — an empirical *infinite-
medium* kernel — to the contact / on-skin geometry, and separate distance into an
**exact point-source geometry** factor (it cannot come from an infinite-medium kernel,
which has no cross-media geometric spreading — see the §"distance" note).

Honesty (§11): the model is **endpoint-based, NOT a spectrum fold** (Loevinger bakes the
spectrum shape into its empirical fit), and **discrete IC/Auger electrons are excluded**
(Loevinger's domain — e.g. Cs-137→Ba-137m's 624 keV K-IC electron is not counted). Budget
is **±20–30 %**; published beta skin-dose values disagree by ~50 %, and this model lands at
their median (Co-60 contact +15 % vs the VARSKIN EGSnrc benchmark). See
``docs/plans/M4-beta-dose.md``.

The kernel (arXiv physics/0310150, Eqs. 2–4), dose **per decay** J(x) at distance x (cm)
in an infinite medium of density ρ (g/cm³):

    J(x) = T1(x) + T2(x)
    T1(x) = [ B·t/x²  −  (B/x)·exp(1 − x/t) ] · Θ(t − x)
    T2(x) =   (B/x)·exp(1 − x/z)
    z = (ρ·ν)⁻¹ ,  t = c·z ,  B = (1/4π)·ρ·ν²·α·Ē ,  α = [3c² − (c²−1)·e]⁻¹
    ν = 18.6 / (E_max − 0.036)^1.37  cm²/g  (apparent absorption coefficient)
    c = 2 (E_max<0.5) | 1.5 (0.5–1.5) | 1 (1.5–3)

B is fixed by **energy conservation** (∫ J·ρ·4πx² dx = Ē exactly). J is MeV/g per decay →
Gy/decay ×1.602176634e-10. w_R = 1, so absorbed dose to skin (Gy) ≡ Hp(0.07) (Sv).

No silent errors (CLAUDE.md): a nuclide whose betas cannot reach the basal layer (E_max ≤
0.036 MeV, e.g. H-3) contributes **0** skin dose — the correct "no external tritium
hazard" result — recorded in ``warnings``, never a silent drop.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from engine import attenuation, emissions

#: Dose quantity tag crossing the bridge (§6.4 family; distinct from γ H*(10)/effective).
QUANTITY = "beta_skin"
#: Absorbed dose to skin (Gy); shallow dose equivalent Hp(0.07) in Sv is numerically equal
#: (radiation weighting factor w_R = 1 for electrons).
SI_UNIT = "Gy"

SKIN_DEPTH_MASS_GCM2 = 0.007  #: 7 mg/cm² basal-layer depth (10 CFR 20.1201(c))
SKIN_AVG_AREA_CM2 = 1.0  #: default dose-averaging area
#: Mean→endpoint ratio Ē/E_max for the *minor* branches whose endpoint ICRP-107 doesn't
#: give (the dominant branch uses the true spectrum endpoint). ≈0.40 is the measured ratio
#: of allowed beta spectra (C-14 0.31, Sr-90 0.36, Y-90 0.41, P-32 0.41); documented
#: approximation, NOT tuned to dose.
MEAN_TO_ENDPOINT_RATIO = 0.40
#: ν is undefined at/below 0.036 MeV (its denominator → 0); physically the beta range is
#: then below the basal layer ⇒ zero skin dose.
LOEV_EMIN_MEV = 0.036

MEV_G_TO_GY = 1.602176634e-10  #: 1 MeV/g → Gy  (= 1.602e-13 J / 1e-3 kg)


class BetaDoseError(Exception):
    """Loud failure in the beta skin-dose path — never swallowed, never a fallback number."""


# --- Loevinger kernel (pure functions) -----------------------------------------------


def loevinger_nu(E_max_MeV: float) -> float:
    """Apparent absorption coefficient ν (cm²/g) for endpoint ``E_max_MeV``.

    ``ν = 18.6 / (E_max − 0.036)^1.37`` (Loevinger 1956). Raises :class:`BetaDoseError`
    for ``E_max ≤ 0.036`` MeV, where ν is undefined and the range is below the basal layer.
    """
    if E_max_MeV <= LOEV_EMIN_MEV:
        raise BetaDoseError(
            f"Loevinger ν undefined for E_max={E_max_MeV:g} MeV ≤ {LOEV_EMIN_MEV} MeV "
            "(beta range below the 7 mg/cm² basal layer ⇒ zero skin dose)"
        )
    return 18.6 / (E_max_MeV - 0.036) ** 1.37


def loevinger_c(E_max_MeV: float) -> float:
    """Dimensionless Loevinger ``c`` (1956 parameterization), extended below 0.17 MeV with
    its lowest band value ``2.0``."""
    if E_max_MeV < 0.5:
        return 2.0
    if E_max_MeV < 1.5:
        return 1.5
    return 1.0


def loevinger_J(x_cm: float, E_max_MeV: float, Ebar_MeV: float, rho_g_cm3: float) -> float:
    """Loevinger dose **per decay** (MeV/g) at distance ``x_cm`` for one beta branch in an
    infinite medium of density ``rho_g_cm3``. Non-negative (clamped at 0 past the range)."""
    nu = loevinger_nu(E_max_MeV)
    c = loevinger_c(E_max_MeV)
    z = 1.0 / (rho_g_cm3 * nu)
    t = c * z
    alpha = 1.0 / (3.0 * c * c - (c * c - 1.0) * math.e)
    B = (rho_g_cm3 * nu * nu * alpha * Ebar_MeV) / (4.0 * math.pi)
    T2 = (B / x_cm) * math.exp(1.0 - x_cm / z)
    T1 = ((B * t / x_cm**2) - (B / x_cm) * math.exp(1.0 - x_cm / t)) if x_cm < t else 0.0
    val = T1 + T2
    return val if val > 0.0 else 0.0


def _branch_kernels(nuclide: str, spectrum_endpoint: float) -> list[tuple[float, float, float]]:
    """``[(E_max_i, Ebar_i, yield_i)]`` per beta branch.

    The highest-mean branch takes the *true* spectrum endpoint (the only endpoint ICRP-107
    exposes); minor branches estimate ``E_max = Ē / R`` (clipped to the endpoint). Branches
    that cannot reach the basal layer (E_max ≤ 0.036 MeV) are dropped.
    """
    lines = [
        (b["E_mean_MeV"], b["yield"])
        for b in emissions.betas(nuclide)
        if b.get("kind") in ("beta-", "beta+") and b.get("yield", 0.0) > 0.0
    ]
    if not lines:
        return []
    i_top = max(range(len(lines)), key=lambda i: lines[i][0])  # highest mean ⇒ highest endpoint
    out: list[tuple[float, float, float]] = []
    for i, (ebar, y) in enumerate(lines):
        e_max = (
            spectrum_endpoint
            if i == i_top
            else min(ebar / MEAN_TO_ENDPOINT_RATIO, spectrum_endpoint)
        )
        if e_max > LOEV_EMIN_MEV:
            out.append((e_max, ebar, y))
    return out


def _normalize_shield(shield) -> Optional[tuple[str, float]]:
    if shield is None:
        return None
    try:
        material, thickness_cm = shield
    except (TypeError, ValueError) as exc:
        raise BetaDoseError(
            f"shield must be None or (material, thickness_cm); got {shield!r}"
        ) from exc
    thickness_cm = float(thickness_cm)
    if thickness_cm < 0.0:
        raise BetaDoseError(f"shield thickness must be >= 0 cm; got {thickness_cm}")
    return str(material), thickness_cm


# --- bremsstrahlung-in-shield (§6.2 "more lead can increase dose"; §11 order-of-magnitude) -

#: Radiated-fraction constant: f = BREMS_YIELD_PER_MEV · Z · E_max is the fraction of a
#: beta's energy converted to bremsstrahlung in a thick target (Cember, *Introduction to
#: Health Physics*; e.g. ³²P in Pb → 3.5e-4·82·1.71 ≈ 0.049). Units 1/MeV.
BREMS_YIELD_PER_MEV = 3.5e-4
BREMS_NBINS = 40
BREMS_KMIN_MEV = 1.0e-3

#: Effective atomic number for bremsstrahlung production. Elements use their true Z; low-Z
#: compounds use a radiative-weighted effective Z (documented approximation — the brems
#: source term is order-of-magnitude per §11). Acrylic (pmma) / polyethylene are the
#: §6.2-recommended *low-Z* beta shields; lead/tungsten are the high-Z bremsstrahlung trap.
SHIELD_Z_EFF: dict[str, float] = {
    "polyethylene": 5.4,
    "pmma": 6.6,
    "tissue_soft": 7.4,
    "water": 7.5,
    "concrete": 13.0,
    "aluminium": 13.0,
    "iron": 26.0,
    "copper": 29.0,
    "tungsten": 74.0,
    "lead": 82.0,
}


def shield_z_eff(material: str) -> float:
    """Effective Z of ``material`` for bremsstrahlung. Raises on an unknown shield rather
    than guessing (no silent fallback)."""
    try:
        return SHIELD_Z_EFF[material]
    except KeyError as exc:
        raise BetaDoseError(
            f"no bremsstrahlung Z_eff for shield {material!r}; known: {sorted(SHIELD_Z_EFF)}"
        ) from exc


def _kramers_add(
    grid_k: np.ndarray, dk: np.ndarray, e_brems: float, e_max: float, acc: np.ndarray
) -> None:
    """Accumulate one branch's Kramers thick-target photon **number** spectrum onto ``acc``
    (photons/decay per bin). Thick-target intensity I(k) ∝ (E_max − k) (Kramers 1923),
    normalized so ∫I dk = ``e_brems``; number spectrum N(k) = I(k)/k."""
    if e_brems <= 0.0 or e_max <= BREMS_KMIN_MEV:
        return
    intensity = np.where(grid_k < e_max, 2.0 * e_brems * (e_max - grid_k) / e_max**2, 0.0)
    acc += np.where(grid_k > 0.0, intensity / grid_k, 0.0) * dk


def bremsstrahlung_lines(
    nuclide: str, shield_material: str, branches: Sequence[tuple[float, float, float]]
) -> list[dict]:
    """Synthetic thick-target bremsstrahlung photon lines from ``nuclide``'s betas stopped in
    ``shield_material`` — a photon source term for :class:`engine.dose.GammaDoseModel` (via
    its ``photon_override``). Empty if the nuclide has no betas. Order-of-magnitude (§11).

    Per branch: radiated energy/decay = yield · f · Ē with f = 3.5e-4·Z·E_max (Cember),
    spread over a Kramers triangular spectrum up to that branch's endpoint; branches summed
    onto one grid. These photons are **not** re-attenuated by the (photon-thin, beta-
    stopping) shield — a documented simplification (§11)."""
    if not branches:
        return []
    z = shield_z_eff(shield_material)
    endpoint = max(e_max for e_max, _, _ in branches)
    edges = np.linspace(BREMS_KMIN_MEV, endpoint, BREMS_NBINS + 1)
    k = 0.5 * (edges[:-1] + edges[1:])
    dk = np.diff(edges)
    yields = np.zeros_like(k)
    for e_max, ebar, y in branches:
        e_brems = y * (BREMS_YIELD_PER_MEV * z * e_max) * ebar  # MeV/decay radiated by this branch
        _kramers_add(k, dk, e_brems, e_max, yields)
    return [
        {"E_MeV": float(kk), "yield": float(yy), "origin": "bremsstrahlung"}
        for kk, yy in zip(k, yields)
        if yy > 0.0
    ]


class BetaSkinDoseModel:
    """Solve-once per-nuclide beta skin-dose kernels for a fixed (medium, shield).

    The §3 "solve once, evaluate many" split for beta: distance is **not** separable from
    the kernel the way γ's 1/4πd² is (beta ranges out), so the per-nuclide coefficient
    ``C_n^β(d)`` is recomputed per distance — but at a *fixed* distance it is a constant, so
    a time series is one matvec ``rate(t) = Σ C_n^β(d)·A_n(t)`` (no per-tick re-integration).

    distance(``d``) is modelled as **exact point-source geometry** (the scoring-disk solid
    angle) × **contact dosimetry** × **air-mass transmission** — the infinite-medium
    Loevinger kernel supplies only the contact dosimetry; it cannot represent cross-media
    geometric spreading (see module docstring / dev-doc). Validated within ~factor-2 of
    VARSKIN Table 4-2 across air gaps + covers; **monotonic non-increasing in distance**.
    """

    def __init__(
        self,
        nuclides: Sequence[str],
        *,
        medium: str = "tissue_soft",
        shield=None,
        avg_area_cm2: float = SKIN_AVG_AREA_CM2,
    ):
        self.medium = medium
        self.rho_t = attenuation.density(medium)  # g/cm³ scoring medium
        self.rho_air = attenuation.density("air")  # g/cm³ intervening air
        self.depth_cm = SKIN_DEPTH_MASS_GCM2 / self.rho_t  # 7 mg/cm² as a tissue depth
        self.disk_radius_cm = math.sqrt(avg_area_cm2 / math.pi)
        self.shield = _normalize_shield(shield)
        self.shield_mass_gcm2 = 0.0
        if self.shield is not None:
            material, thickness_cm = self.shield
            self.shield_mass_gcm2 = attenuation.density(material) * thickness_cm
        self.nuclides = list(nuclides)
        self.si_unit = SI_UNIT
        self.quantity = QUANTITY
        self.warnings: list[dict] = []
        #: per-nuclide branch kernels ``[(E_max, Ebar, yield)]`` (empty ⇒ no/too-soft betas)
        self.branches: dict[str, list[tuple[float, float, float]]] = {}
        for nuclide in self.nuclides:
            self.branches[nuclide] = self._build_branches(nuclide)

    # -- per-nuclide branch assembly (solve once) -------------------------

    def _build_branches(self, nuclide: str) -> list[tuple[float, float, float]]:
        if not emissions.has_emissions(nuclide):
            return []  # stable daughter — legitimately no betas
        endpoint = emissions.beta_endpoint_MeV(nuclide)
        if endpoint <= LOEV_EMIN_MEV:
            if emissions.betas(nuclide):
                self.warnings.append(
                    {
                        "nuclide": nuclide,
                        "reason": "below_basal_layer",
                        "endpoint_MeV": endpoint,
                        "message": (
                            f"{nuclide}: beta endpoint {endpoint:g} MeV ≤ {LOEV_EMIN_MEV} MeV — "
                            "range below the 7 mg/cm² basal layer ⇒ zero external skin dose"
                        ),
                    }
                )
            return []
        return _branch_kernels(nuclide, endpoint)

    # -- geometry + contact dosimetry -------------------------------------

    def _radial_grid(self) -> np.ndarray:
        # Near-axis-refined: the contact integrand ~ s/(s²+depth²) is peaked at width ~depth.
        return np.concatenate(
            ([0.0], np.geomspace(self.depth_cm / 200.0, self.disk_radius_cm, 8000))
        )

    def _contact_dose_per_decay(self, nuclide: str, absorber_mass_gcm2: float) -> float:
        """Disk-averaged contact dose (Gy/decay) with ``absorber_mass_gcm2`` of matter between
        the source and the basal layer (cover + air column), via the equivalent-tissue depth."""
        branches = self.branches[nuclide]
        if not branches:
            return 0.0
        offset_cm = absorber_mass_gcm2 / self.rho_t  # absorber as equivalent tissue depth
        s = self._radial_grid()
        x = np.sqrt(s**2 + (self.depth_cm + offset_cm) ** 2)
        total = np.zeros_like(s)
        for e_max, ebar, y in branches:
            total += y * np.array([loevinger_J(xi, e_max, ebar, self.rho_t) for xi in x])
        integral = np.trapezoid(total * 2.0 * math.pi * s, s) / (math.pi * self.disk_radius_cm**2)
        return float(integral) * MEV_G_TO_GY

    def _geometry_factor(self, distance_m: float) -> float:
        """Exact point-source geometry: fraction of the scoring disk's solid angle, normalized
        to 1 at contact. ``1 − d/√(d²+a²)`` → 1 at d=0, → a²/2d² (inverse-square) far."""
        if distance_m < 0.0:
            raise BetaDoseError(f"distance must be >= 0 m; got {distance_m}")
        d_cm = distance_m * 100.0
        return 1.0 - d_cm / math.sqrt(d_cm * d_cm + self.disk_radius_cm**2)

    def skin_dose_per_decay(self, nuclide: str, distance_m: float) -> float:
        """Beta skin dose **per decay** (Gy) at source-to-skin ``distance_m``.

        ``= contact_dose(absorber = ρ_air·d + shield_mass) × geometry_factor(d)``. Zero for a
        nuclide with no betas reaching the basal layer (recorded in :attr:`warnings`)."""
        if nuclide not in self.branches:
            raise BetaDoseError(f"nuclide {nuclide!r} not in this model")
        if not self.branches[nuclide]:
            return 0.0
        d_cm = distance_m * 100.0
        absorber = self.rho_air * d_cm + self.shield_mass_gcm2
        return self._contact_dose_per_decay(nuclide, absorber) * self._geometry_factor(distance_m)

    # -- bremsstrahlung-in-shield (§6.2) ----------------------------------

    def bremsstrahlung_override(self) -> dict[str, list[dict]]:
        """Per-nuclide thick-target bremsstrahlung photon lines for this model's shield —
        feed to ``GammaDoseModel(..., shield=None, photon_override=...)`` for the secondary
        photon dose. Empty when there is no shield (free betas don't radiate appreciably).
        This is the §6.2 "more lead can increase dose" mechanism: a high-Z shield that stops
        the beta emits penetrating X-rays the low-Z shield does not."""
        if self.shield is None:
            return {}
        material, _ = self.shield
        return {
            nuclide: bremsstrahlung_lines(nuclide, material, branches)
            for nuclide, branches in self.branches.items()
            if branches
        }

    # -- evaluation (evaluate many) ---------------------------------------

    def dose_rate(self, activities_bq: dict[str, float], distance_m: float) -> float:
        """Beta skin-dose rate (Gy/s) at one time. Every contributing nuclide must be present."""
        total = 0.0
        for nuclide, branches in self.branches.items():
            if not branches:
                continue
            if nuclide not in activities_bq:
                raise BetaDoseError(f"no activity supplied for contributing nuclide {nuclide!r}")
            total += self.skin_dose_per_decay(nuclide, distance_m) * float(activities_bq[nuclide])
        return total

    def dose_rate_series(self, evaluate_result: dict, distance_m: float) -> dict:
        """Beta skin-dose-rate time series from a ``SolvedInventory.evaluate`` activity result —
        one matvec of the fixed ``C_n^β(d)`` against the activity grid (§3 evaluate-many)."""
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise BetaDoseError(
                "dose_rate_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series: dict[str, list[float]] = evaluate_result["series"]
        times = evaluate_result["times_s"]
        coeff = {
            n: self.skin_dose_per_decay(n, distance_m) for n in self.branches if self.branches[n]
        }
        rates = [0.0] * len(times)
        for nuclide, c_n in coeff.items():
            if c_n == 0.0:
                continue
            if nuclide not in series:
                raise BetaDoseError(f"no activity series for contributing nuclide {nuclide!r}")
            for j, a in enumerate(series[nuclide]):
                rates[j] += c_n * float(a)
        return {
            "quantity": self.quantity,
            "si_unit": self.si_unit,
            "per": "second",
            "times_s": list(times),
            "distance_m": distance_m,
            "scoring_depth_mg_cm2": SKIN_DEPTH_MASS_GCM2 * 1000.0,
            "rate_si": rates,
            "warnings": list(self.warnings),
        }
