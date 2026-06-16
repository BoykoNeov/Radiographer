"""M4 beta SKIN-dose benchmarks (HANDOFF_PLAN.md §6.2, §10, §11).

External beta is a **skin-dose** problem: absorbed dose to the 7 mg/cm² basal layer,
averaged over 1 cm², from a point source. The engine applies the **Loevinger** beta
point-source dose function (arXiv physics/0310150, reproducing Loevinger 1956) per
beta branch — endpoint-based, NOT a spectrum fold, and discrete IC/Auger electrons
are excluded (Loevinger's domain). Budget is ±20–30 % (§6.2); published beta skin-dose
values themselves disagree by ~50 %, so the validation brackets multiple references
rather than chasing one.

Pillars:
- **Energy conservation** — the kernel normalization ∫ J·ρ·4πx² dx = Ē_β exactly
  (anchors B/α; NOT the ν shape — that needs the benchmarks below).
- **Co-60 point on skin** — VARSKIN 5 (NUREG/CR-6918, EGSnrc-validated) Table 4-1.
- **Distributed disk, 0.16–2.28 MeV** — the high-E shape check across C-14…Y-90,
  bracketed by VARSKIN 5 + Kocher-Eckerman 1987 + Delacroix 1986 + Piechowski 1988.
- **Range cutoff** — H-3 betas never reach 7 mg/cm² ⇒ zero skin dose (the correct
  "no external tritium hazard" result); dose falls with air gap.
- **Cs-137 is beta-only** — VARSKIN excludes progeny too, so this is apples-to-apples
  for the IC-electron exclusion.

Internally MeV/g per decay (Loevinger's natural unit) → Gy at the boundary; w_R=1 so
absorbed dose to skin (Gy) ≡ shallow dose equivalent Hp(0.07) (Sv) numerically.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from engine.beta_dose import (
    BetaDoseError,
    BetaSkinDoseModel,
    bremsstrahlung_lines,
    loevinger_c,
    loevinger_J,
    loevinger_nu,
    shield_z_eff,
)
from engine.dose import GammaDoseModel

UCI = 3.7e4  # Bq per microcurie
HR = 3600.0  # s
MEV_G_TO_GY = 1.602176634e-10


def mGy_per_uCi_hr(gy_per_decay: float) -> float:
    return gy_per_decay * UCI * HR * 1000.0


# --- kernel: energy conservation (normalization, not shape) --------------------------


@pytest.mark.parametrize("E_max,Ebar", [(2.28, 0.93), (1.71, 0.695), (0.546, 0.196)])
def test_loevinger_kernel_conserves_energy(E_max, Ebar):
    # All emitted energy is absorbed in a large sphere: ∫ J(x)·ρ·4πx² dx = Ē_β (MeV/decay).
    # This is the Loevinger normalization (B fixed by it); independent of distance units.
    rho = 1.06
    xs = np.geomspace(1e-5, 30.0 / (rho * loevinger_nu(E_max)), 400000)
    J = np.array([loevinger_J(x, E_max, Ebar, rho) for x in xs])
    absorbed = np.trapezoid(J * rho * 4 * math.pi * xs**2, xs)
    assert absorbed == pytest.approx(Ebar, rel=2e-3)


def test_loevinger_c_breaks_at_named_energies():
    assert loevinger_c(0.3) == 2.0
    assert loevinger_c(1.0) == 1.5
    assert loevinger_c(2.0) == 1.0


def test_loevinger_nu_decreases_with_energy_and_floors_below_0p036():
    # Apparent absorption coefficient must fall with energy (higher E penetrates further).
    assert loevinger_nu(0.5) > loevinger_nu(2.0)
    with pytest.raises(BetaDoseError):
        loevinger_nu(0.03)  # ν undefined at/below 0.036 MeV (range below basal layer)


# --- Co-60 point on skin: the low-E MC benchmark -------------------------------------


def test_co60_point_skin_dose_matches_varskin():
    # VARSKIN 5 (NUREG/CR-6918 Rev.2, Table 4-1): 1 µCi Co-60 point on skin, 1 h,
    # β dose at 7 mg/cm² over 1 cm² = 34.5 mGy. Co-60's dominant β ends at 0.318 MeV
    # (its spectrum max 1.49 MeV is a 0.12 % branch — the per-branch model must not
    # apply 1.49 MeV to the whole nuclide). Budget ±25 %.
    m = BetaSkinDoseModel(["Co-60"])
    dose_mGy = mGy_per_uCi_hr(m.skin_dose_per_decay("Co-60", 0.0))
    assert dose_mGy == pytest.approx(34.5, rel=0.25)


# --- distributed disk, high-E shape (the multi-reference bracket) ---------------------


def _distributed_disk_mGy(nuclide: str, model: BetaSkinDoseModel) -> float:
    """1 µCi/cm² over a 2-cm-dia disk, 7 mg/cm², on-axis, 1 h (VARSKIN Table 4-4 geometry).
    Reuses the engine's public ``loevinger_J`` to validate its energy dependence."""
    rho_t = model.rho_t
    depth_cm = model.depth_cm
    r_src = 1.0  # cm (2-cm diameter)
    s = np.concatenate([[0.0], np.geomspace(depth_cm / 200, r_src, 6000)])
    xg = np.sqrt(s**2 + depth_cm**2)
    integ = np.zeros_like(s)
    for E_max, Ebar, y in model.branches[nuclide]:
        integ += y * np.array([loevinger_J(x, E_max, Ebar, rho_t) for x in xg])
    per_decay_per_cm2 = np.trapezoid(integ * 2 * math.pi * s, s) * MEV_G_TO_GY  # Gy·cm²/decay
    return per_decay_per_cm2 * UCI * HR * 1000.0  # × σ(Bq/cm²) × t → mGy


# published spread (mGy): VARSKIN5, Kocher-Eckerman'87, Delacroix'86, Piechowski'88
_DISK_REFS = {
    "C-14": [11.1, 12.2, 10.7, 12.0],
    "Sr-90": [49.7, 67.6, 69.9, 59.0],
    "P-32": [58.6, 88.7, 91.5, 70.0],
    "Y-90": [59.4, 88.7, 91.8, 75.0],
}


@pytest.mark.parametrize("nuclide", list(_DISK_REFS))
def test_distributed_disk_within_published_spread(nuclide):
    # The energy-dependence check across 0.156→2.28 MeV. "Truth" spans ~50 % between
    # codes; the model must land inside the published bracket (not pinned to one code).
    m = BetaSkinDoseModel([nuclide])
    dose = _distributed_disk_mGy(nuclide, m)
    refs = _DISK_REFS[nuclide]
    assert 0.85 * min(refs) <= dose <= 1.15 * max(refs)


# --- range cutoff & distance fall-off -------------------------------------------------


def test_tritium_gives_zero_skin_dose():
    # H-3 (E_max 0.0186 MeV) betas cannot reach the 7 mg/cm² basal layer — the correct
    # "no external tritium skin hazard" result (§12 external≠internal). Recorded, not silent.
    m = BetaSkinDoseModel(["H-3"])
    assert m.skin_dose_per_decay("H-3", 0.0) == 0.0
    assert any(w.get("nuclide") == "H-3" for w in m.warnings)


def test_skin_dose_falls_with_air_gap_and_ranges_out():
    # Beta dose drops with source-skin distance and effectively vanishes once the air
    # mass-thickness exceeds the beta range — the teaching contrast with γ's slow 1/d².
    m = BetaSkinDoseModel(["Sr-90", "Y-90"])
    acts = {"Sr-90": 1e6, "Y-90": 1e6}
    contact = m.dose_rate(acts, 0.0)
    near = m.dose_rate(acts, 0.10)  # 10 cm
    far = m.dose_rate(acts, 2.0)  # 2 m — beyond Y-90's ~0.4 g/cm² reach in air? (≈2.4 g/cm²)
    assert contact > near > far
    assert far < 1e-3 * contact


def test_stable_or_non_beta_nuclide_contributes_zero():
    # A stable / alpha-only nuclide legitimately emits no betas → zero, not a data hole.
    m = BetaSkinDoseModel(["Ba-137"])  # stable
    assert m.skin_dose_per_decay("Ba-137", 0.0) == 0.0


# --- Cs-137: beta-only, IC excluded (apples-to-apples) -------------------------------


def test_cs137_uses_own_betas_not_ba137m():
    # The Loevinger model is beta-only; Cs-137's skin dose comes from its OWN betas
    # (0.514 MeV dominant), NOT Ba-137m's 0.662 γ or its 624 keV K-IC electron (excluded,
    # §11). VARSKIN likewise excludes progeny, so this is the apples-to-apples comparison.
    m = BetaSkinDoseModel(["Cs-137", "Ba-137m"])
    cs = m.skin_dose_per_decay("Cs-137", 0.0)
    ba = m.skin_dose_per_decay("Ba-137m", 0.0)  # Ba-137m: γ + IC, negligible β
    assert cs > 0.0
    assert ba < 0.05 * cs


# --- solve-once / evaluate-many over a time grid -------------------------------------


def test_dose_rate_series_tracks_activity_at_fixed_distance():
    from engine.inventory import SolvedInventory

    # P-32 → S-32 (stable, no betas): a clean single-beta-emitter, so the dose-rate series
    # tracks P-32's activity exactly across the grid (a parent+daughter case like Sr-90→Y-90
    # would NOT — the daughter grows in and contributes its own beta dose).
    inv = SolvedInventory.from_spec({"P-32": 1e9}, "Bq")
    grid = [0.0, 1.234e6, 3.702e6]  # ~1 and ~3 P-32 half-lives (14.3 d)
    res = inv.evaluate(grid, axis="activity", unit="Bq")
    m = BetaSkinDoseModel(res["nuclides"])
    out = m.dose_rate_series(res, 0.0)
    assert len(out["rate_si"]) == len(grid)
    assert out["si_unit"] == "Gy" and out["quantity"] == "beta_skin"
    a = res["series"]["P-32"]
    for j in range(len(grid)):
        assert out["rate_si"][j] / out["rate_si"][0] == pytest.approx(a[j] / a[0], rel=1e-9)


# --- bremsstrahlung-in-shield: the §6.2 "more lead = more dose" gotcha ----------------


def test_bremsstrahlung_energy_scales_with_z_and_conserves():
    # Radiated energy/decay = Σ yield·(3.5e-4·Z·E_max)·Ē (Cember); the Kramers triangular
    # spectrum must conserve that energy. Lead (Z 82) radiates ~12× acrylic (Z 6.6).
    m = BetaSkinDoseModel(["Y-90"])
    br = m.branches["Y-90"]
    z_pb, z_ac = shield_z_eff("lead"), shield_z_eff("pmma")
    e_expect_pb = sum(y * (3.5e-4 * z_pb * emax) * ebar for emax, ebar, y in br)
    lines_pb = bremsstrahlung_lines("Y-90", "lead", br)
    e_lines_pb = sum(line["E_MeV"] * line["yield"] for line in lines_pb)
    assert e_lines_pb == pytest.approx(e_expect_pb, rel=0.02)  # spectrum conserves radiated E
    e_ac = sum(y * (3.5e-4 * z_ac * emax) * ebar for emax, ebar, y in br)
    assert e_expect_pb / e_ac == pytest.approx(z_pb / z_ac, rel=1e-6)


def test_high_z_shield_brems_dose_exceeds_low_z():
    # The teaching crossover: a beta-stopping shield of LEAD emits far more penetrating
    # bremsstrahlung than ACRYLIC — "more lead can increase dose" (§6.2). Brems photons go
    # through the validated γ machinery (photon_override), unattenuated by the thin shield.
    acts = {"Y-90": 1e9}

    def brems_air_kerma(material: str) -> float:
        m = BetaSkinDoseModel(["Y-90"], shield=(material, 1.0))
        override = m.bremsstrahlung_override()
        g = GammaDoseModel(["Y-90"], "air_kerma", shield=None, photon_override=override)
        return g.dose_rate(acts, 1.0)

    pb = brems_air_kerma("lead")
    ac = brems_air_kerma("pmma")
    assert ac > 0.0
    assert pb > 5.0 * ac  # Z 82 vs 6.6 ⇒ ~12× more radiated energy


def test_no_shield_means_no_bremsstrahlung():
    m = BetaSkinDoseModel(["Y-90"])  # free beta — no stopping medium, no brems source
    assert m.bremsstrahlung_override() == {}


def test_unknown_shield_z_is_loud_not_silent():
    with pytest.raises(BetaDoseError):
        shield_z_eff("unobtainium")
