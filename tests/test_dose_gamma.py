"""M3 gamma dose-core benchmarks (HANDOFF_PLAN.md §6, §10).

"Near-quantitative" gets its teeth from published constants, each anchored to a NAMED
reference at a few-percent tolerance (sources disagree in the third decimal — don't chase
it). These tests validate the whole §6 chain end to end:

- **Co-60 air-kerma rate constant** — line-sum × μ_en/ρ_air × inverse-square, daughter
  stable so the source spectrum is unambiguous.
- **Cs-137 via secular equilibrium** — the real coupling test: the 0.662 MeV line is
  emitted by **Ba-137m**, not Cs-137. The engine must sum BOTH nuclides' spectra weighted
  by their decayed activities, never hardcode 0.662 onto Cs-137.
- **Inverse-square**, **off-grid skip-vs-error severity**, **no-buildup shield loudness**,
  and **broad-beam HVL/TVL** (attenuation + buildup).

Internally everything is SI (Gy/s, Sv/s); we convert to mGy/h / R/h at the boundary.
"""

from __future__ import annotations

import math

import pytest

from engine.buildup import BuildupError
from engine.dose import DoseError, GammaDoseModel, stack_transmission, transmission
from engine.inventory import SolvedInventory
from engine.photon_interp import ABOVE_GRID, BELOW_FLOOR

GBQ = 1.0e9
CI = 3.7e10            # Bq per curie
R_TO_MGY_AIRKERMA = 8.76  # 1 R ≈ 8.76 mGy air kerma


def mGy_per_h(gy_per_s: float) -> float:
    return gy_per_s * 1000.0 * 3600.0


# --- Co-60: the gamma-dose reference case --------------------------------------------

def test_co60_air_kerma_rate_constant():
    # Co-60 (1.173 + 1.333 MeV) air-kerma rate constant Γ ≈ 0.308 mGy·m²·GBq⁻¹·h⁻¹
    # (e.g. NIST / IAEA TRS-398 era tabulations). Hand-check: 0.307.
    m = GammaDoseModel(["Co-60"], "air_kerma")
    k = m.dose_rate({"Co-60": GBQ}, 1.0)  # Gy/s at 1 m per 1 GBq
    assert mGy_per_h(k) == pytest.approx(0.308, rel=0.03)


def test_co60_one_curie_at_one_metre_rule_of_thumb():
    # "1 Ci Co-60 at 1 m ≈ 1.3 R/h" — the classic field rule.
    m = GammaDoseModel(["Co-60"], "air_kerma")
    k_mgy_h = mGy_per_h(m.dose_rate({"Co-60": CI}, 1.0))
    assert k_mgy_h / R_TO_MGY_AIRKERMA == pytest.approx(1.30, rel=0.05)


# --- Cs-137: the secular-equilibrium coupling test -----------------------------------

def test_cs137_air_kerma_via_secular_equilibrium():
    # Load Cs-137, decay 1 h (>> Ba-137m's 2.55 min) → equilibrium, then dose-sum BOTH
    # nuclides' spectra. Published Cs-137 air-kerma constant ≈ 0.077 mGy·m²·GBq⁻¹·h⁻¹
    # (Unger & Trubey 1982). The ~0.85 γ/decay this bakes in is the 0.944 branch × 0.897.
    inv = SolvedInventory.from_spec({"Cs-137": GBQ}, "Bq")
    res = inv.evaluate([3600.0], axis="activity", unit="Bq")
    acts = {n: res["series"][n][0] for n in res["nuclides"]}

    m = GammaDoseModel(res["nuclides"], "air_kerma")
    k = m.dose_rate(acts, 1.0)
    assert mGy_per_h(k) == pytest.approx(0.077, rel=0.10)


def test_cs137_dose_is_emitted_by_ba137m_not_cs137():
    # Guards against hardcoding 0.662 onto Cs-137: the per-nuclide dose coefficient for
    # Ba-137m (0.662, y≈0.90) must dwarf Cs-137's own (only a 0.2835 MeV line at y≈6e-6).
    m = GammaDoseModel(["Cs-137", "Ba-137m", "Ba-137"], "air_kerma")
    assert m.coeff_si["Ba-137m"] > 1000.0 * m.coeff_si["Cs-137"]
    assert m.coeff_si["Ba-137"] == 0.0  # stable daughter contributes nothing


# --- conversion-path absolute calibration (separate machinery from μ_en/ρ) -----------

def test_co60_hstar10_to_air_kerma_ratio_is_physical():
    # H*(10) runs through a wholly separate path (interp_conversion → pSv·cm²→Sv·m²) than
    # air_kerma (μ_en/ρ). A factor slip in that conversion (the easiest place to drop a
    # 10²) would pass every line-sum test silently. The h*(10)/Kₐ ratio is physics: ≈1.77
    # at 60 keV, declining to ~1.1–1.15 at Co-60's MeV lines (ICRU sphere, M2-conversion).
    acts = {"Co-60": GBQ}
    ka = GammaDoseModel(["Co-60"], "air_kerma").dose_rate(acts, 1.0)
    h10 = GammaDoseModel(["Co-60"], "ambient_H10").dose_rate(acts, 1.0)
    assert 1.05 < h10 / ka < 1.30


def test_co60_effective_ap_to_air_kerma_ratio_is_physical():
    # effective dose is only reachable through GammaDoseModel with a geometry; AP/Kₐ for a
    # ~1.25 MeV field is near unity (ICRP-116). Calibrates the effective path + units.
    acts = {"Co-60": GBQ}
    ka = GammaDoseModel(["Co-60"], "air_kerma").dose_rate(acts, 1.0)
    eff = GammaDoseModel(["Co-60"], "effective", geometry="AP").dose_rate(acts, 1.0)
    assert 0.85 < eff / ka < 1.15


# --- evaluate-many: the C_n matvec over a time grid ----------------------------------

def test_dose_rate_series_is_proportional_to_activity_over_grid():
    # The headline "solve once, evaluate many": dose at each time = (1/4πd²)·Σ C_n·A_n(t).
    # For a single-nuclide source the rate must track the activity exactly across the whole
    # grid — locks the per-row matvec accumulation (not just a single time point).
    inv = SolvedInventory.from_spec({"Co-60": GBQ}, "Bq")
    grid = [0.0, 5.0e7, 1.663e8, 5.0e8]  # spans ~Co-60's 5.27 y half-life
    res = inv.evaluate(grid, axis="activity", unit="Bq")
    m = GammaDoseModel(res["nuclides"], "ambient_H10")
    out = m.dose_rate_series(res, 1.0)

    assert len(out["rate_si"]) == len(grid)
    a = res["series"]["Co-60"]
    for j in range(len(grid)):
        assert out["rate_si"][j] / out["rate_si"][0] == pytest.approx(a[j] / a[0], rel=1e-12)
    assert out["si_unit"] == "Sv" and out["scoring_floor_MeV"] == 0.010


# --- per-line decomposition (M6f-2 per-line γ table source) --------------------------

def test_per_line_rows_sum_to_coefficient_exactly():
    # The §9 per-line table and the total dose share ONE coefficient-assembly path: a
    # nuclide's per-line rows must sum to its C_n EXACTLY (==, not approx), or the table
    # would silently disagree with the dose it explains. Cs-137+Ba-137m exercises a
    # multi-nuclide closure where the 0.662 line lives on the daughter.
    m = GammaDoseModel(["Co-60", "Cs-137", "Ba-137m", "Ba-137"], "ambient_H10")
    rows = m.per_line_rows()
    assert rows, "expected scored photon lines"
    for nuclide in m.nuclides:
        per_n = [r["coeff_si"] for r in rows if r["nuclide"] == nuclide]
        assert sum(per_n) == m.coeff_si[nuclide], f"{nuclide}: rows must sum to C_n exactly"
    # every row carries the table columns; energies are physical and yields positive
    for r in rows:
        assert r["E_MeV"] > 0.0 and r["yield"] > 0.0 and r["origin"] is not None
    # the two Co-60 gammas (1.17, 1.33 MeV) are present and dominate
    co = sorted((r for r in rows if r["nuclide"] == "Co-60"), key=lambda r: -r["coeff_si"])
    assert len(co) >= 2
    assert co[0]["E_MeV"] == pytest.approx(1.3325, abs=2e-3) or co[0]["E_MeV"] == pytest.approx(
        1.1732, abs=2e-3
    )


def test_per_line_rows_exclude_below_floor_lines():
    # Below-floor (sub-10-keV) lines are LOGGED SKIPS, not zero-coefficient rows: they must
    # be absent from the per-line table yet recorded in warnings (same skip semantics the
    # total dose uses, so the table never lists a line the dose didn't score).
    m = GammaDoseModel(["Co-60"], "ambient_H10")
    rows = m.per_line_rows()
    assert all(r["E_MeV"] >= 0.010 for r in rows), "no sub-floor line may appear as a row"
    assert m.warnings and all(w["reason"] == BELOW_FLOOR for w in m.warnings)
    # the skipped energies are not silently in the rows
    skipped_E = {w["E_MeV"] for w in m.warnings}
    assert not ({r["E_MeV"] for r in rows} & skipped_E)


# --- inverse-square ------------------------------------------------------------------

def test_inverse_square_law_exact():
    m = GammaDoseModel(["Co-60"], "air_kerma")
    k1 = m.dose_rate({"Co-60": GBQ}, 1.0)
    k2 = m.dose_rate({"Co-60": GBQ}, 2.0)
    assert k2 == pytest.approx(k1 / 4.0, rel=1e-12)


# --- off-grid: two severities --------------------------------------------------------

def test_below_floor_lines_skipped_with_warnings_not_errors():
    # Co-60 carries many sub-10-keV X-ray lines (down to ~14 eV) below the H*(10) 10 keV
    # scoring floor. These are LOGGED SKIPS (negligible dose), never errors; the dominant
    # gammas still score a real, positive dose.
    m = GammaDoseModel(["Co-60"], "ambient_H10")
    assert m.warnings, "expected below-floor X-ray skips to be recorded"
    assert all(w["reason"] == BELOW_FLOOR for w in m.warnings)
    assert m.dose_rate({"Co-60": GBQ}, 1.0) > 0.0


def test_above_grid_line_raises_loudly(monkeypatch):
    # Dropping a high-energy line UNDERESTIMATES dose — the dangerous direction (§11).
    # No natural decay gamma exceeds 10 MeV, so inject an 11 MeV line: for H*(10) (grid
    # ends at 10 MeV) it must be a LOUD error, not a silent skip.
    from engine import emissions

    real = emissions.photons

    def fake(nuclide):
        if nuclide == "Co-60":
            return [{"E_MeV": 11.0, "yield": 0.5, "origin": "gamma"}]
        return real(nuclide)

    monkeypatch.setattr(emissions, "photons", fake)
    with pytest.raises(DoseError) as exc:
        GammaDoseModel(["Co-60"], "ambient_H10")
    assert exc.value.reason == ABOVE_GRID


# --- shielding: no silent surrogate --------------------------------------------------

def test_no_buildup_shield_material_raises_loudly():
    # PMMA has no ANS-6.4.3 buildup; a shield calc through it must fail loudly, never
    # silently fall back to B=1 (buildup.py contract, §6.5).
    with pytest.raises((DoseError, BuildupError)):
        GammaDoseModel(["Co-60"], "air_kerma", shield=("pmma", 1.0))


def test_lead_shield_attenuates_dose():
    bare = GammaDoseModel(["Co-60"], "air_kerma")
    shielded = GammaDoseModel(["Co-60"], "air_kerma", shield=("lead", 2.0))
    k_bare = bare.dose_rate({"Co-60": GBQ}, 1.0)
    k_shield = shielded.dose_rate({"Co-60": GBQ}, 1.0)
    assert 0.0 < k_shield < k_bare


# --- broad-beam HVL / TVL (attenuation + buildup) ------------------------------------

def _solve_thickness(material: str, E_MeV: float, frac: float) -> float:
    """Thickness (cm) at which broad-beam transmission B·exp(−μx) drops to ``frac``."""
    lo, hi = 0.0, 50.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if transmission(material, E_MeV, mid) > frac:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def test_broad_beam_hvl_exceeds_narrow_beam_lead():
    # Buildup (scattered photons) always INCREASES penetration, so the broad-beam HVL is
    # larger than the narrow-beam ln2/μ. Direction is asserted tightly; the absolute value
    # is anchored loosely to a named table (point-isotropic B ≠ broad-beam slab geometry).
    from engine import attenuation as att
    from engine import photon_interp as pi

    E = 1.25  # ~Co-60 mean energy
    mu = pi.interp_mu_rho("lead", E) * att.density("lead")  # cm⁻¹
    hvl_narrow = math.log(2.0) / mu
    hvl_broad = _solve_thickness("lead", E, 0.5)

    assert hvl_broad > hvl_narrow
    # Co-60 lead HVL ≈ 1.2 cm (broad-beam shielding tables, e.g. NCRP-49 era); loose tol.
    assert hvl_broad == pytest.approx(1.2, rel=0.30)


def test_broad_beam_tvl_exceeds_narrow_beam_lead():
    from engine import attenuation as att
    from engine import photon_interp as pi

    E = 1.25
    mu = pi.interp_mu_rho("lead", E) * att.density("lead")
    tvl_narrow = math.log(10.0) / mu
    tvl_broad = _solve_thickness("lead", E, 0.1)

    assert tvl_broad > tvl_narrow
    # Co-60 lead TVL ≈ 4.0 cm (broad-beam tables); loose tol for the geometry mismatch.
    assert tvl_broad == pytest.approx(4.0, rel=0.30)


# --- multi-layer shields (§13 #2 / §6.4: last-layer / total-mfp approximation) --------
#
# A stack is ordered SOURCE-SIDE → DETECTOR-SIDE; the last element is adjacent to the
# detector. transmission = B_last(E, Σ μx) · exp(−Σ μx): attenuation exact and
# order-invariant, buildup taken as the detector-side material over the whole depth.

def _stack_mfp(layers, E_MeV):
    """Total mean-free-paths Σ μᵢxᵢ of a layer stack at energy E (cm⁻¹ · cm)."""
    from engine import attenuation as att
    from engine import photon_interp as pi

    return sum(
        pi.interp_mu_rho(mat, E_MeV) * att.density(mat) * x for mat, x in layers
    )


def test_stack_single_layer_reduces_to_tuple():
    # A one-element layer list must be bit-for-bit identical to the bare-tuple shield —
    # the n=1 reduction that guarantees no regression of the M6g single-layer path.
    E = 1.0
    assert stack_transmission([("lead", 2.0)], E) == transmission("lead", E, 2.0)

    one = GammaDoseModel(["Co-60"], "air_kerma", shield=[("lead", 2.0)])
    tup = GammaDoseModel(["Co-60"], "air_kerma", shield=("lead", 2.0))
    assert one.coeff_si["Co-60"] == tup.coeff_si["Co-60"]


def test_stack_same_material_equals_single_summed():
    # Two layers of the SAME material (x1 then x2) == one layer of (x1+x2), exactly:
    # same μ, same total mfp, same buildup material → identical transmission. (Necessary
    # but NOT sufficient — order-invariant, so it cannot catch a reversed-stack bug.)
    E = 1.0
    two = stack_transmission([("lead", 1.0), ("lead", 2.0)], E)
    one = transmission("lead", E, 3.0)
    assert two == pytest.approx(one, rel=1e-12)


def test_stack_order_locks_detector_side():
    # THE anti-bug test (advisor): a dissimilar stack in both orders. Attenuation is
    # order-invariant; buildup is NOT — it must take the DETECTOR-SIDE (last) material.
    from engine import photon_interp as pi

    E = 1.0
    lead_water = [("lead", 1.0), ("water", 5.0)]   # detector-side = water
    water_lead = [("water", 5.0), ("lead", 1.0)]   # detector-side = lead

    mfp = _stack_mfp(lead_water, E)
    assert _stack_mfp(water_lead, E) == pytest.approx(mfp, rel=1e-12)  # (a) same Σμx
    atten = math.exp(-mfp)

    t_lw = stack_transmission(lead_water, E)
    t_wl = stack_transmission(water_lead, E)

    # (c) each order == B_(detector-side material)(Σ mfp) · exp(−Σ mfp), exactly.
    assert t_lw == pytest.approx(pi.interp_buildup("water", E, mfp) * atten, rel=1e-12)
    assert t_wl == pytest.approx(pi.interp_buildup("lead", E, mfp) * atten, rel=1e-12)
    # (b) the two orders DIFFER (water builds up more than lead at 1 MeV) — a reversed
    # layer list would silently swap these, so they must not be equal.
    assert t_lw != t_wl
    assert t_lw / atten == pytest.approx(pi.interp_buildup("water", E, mfp), rel=1e-12)


def test_stack_monotonic_thickening_fixed_stack():
    # The TRUE monotonicity invariant. Last-layer is NOT monotonic across material/order
    # changes (see the artifact test below) — but holding the stack's COMPOSITION and ORDER
    # fixed, thickening ANY single layer keeps the detector-side material L unchanged, raises
    # the total mfp, and B_L grows sub-exponentially → B_L·exp(−τ) strictly falls.
    E = 1.0
    base = stack_transmission([("lead", 1.0), ("water", 5.0)], E)
    thicker_inner = stack_transmission([("lead", 2.0), ("water", 5.0)], E)  # +source-side
    thicker_outer = stack_transmission([("lead", 1.0), ("water", 6.0)], E)  # +detector-side
    assert 0.0 < thicker_inner < base
    assert 0.0 < thicker_outer < base


def test_stack_lastlayer_artifact_low_z_behind_high_z():
    # KNOWN last-layer limitation — NOT a bug, do NOT "fix" it into a fabrication. A
    # high-buildup low-Z layer (water) on the DETECTOR side of a high-Z layer (lead) makes
    # the computed transmission HIGHER than the lead alone, because water's large buildup is
    # applied over the WHOLE penetration depth (including the lead portion). The error is
    # order-dependent and runs both ways — the reverse order (high-Z detector-side) instead
    # UNDER-counts. Surfaced in the honesty register (§11), never silently. (advisor)
    E = 1.0
    lead_alone = stack_transmission([("lead", 1.0)], E)
    lead_then_water = stack_transmission([("lead", 1.0), ("water", 5.0)], E)
    assert lead_then_water > lead_alone  # the documented non-physical increase


def test_stack_non_buildup_layer_anywhere_raises():
    # A material without ANS-6.4.3 buildup ANYWHERE in the stack must fail loudly — the
    # per-layer gate, not just the first slot (§6.5, no silent B=1 surrogate).
    with pytest.raises((DoseError, BuildupError)):
        GammaDoseModel(["Co-60"], "air_kerma", shield=[("lead", 1.0), ("pmma", 1.0)])
    with pytest.raises((DoseError, BuildupError)):
        GammaDoseModel(["Co-60"], "air_kerma", shield=[("pmma", 1.0), ("lead", 1.0)])
