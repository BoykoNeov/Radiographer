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
from engine.dose import DoseError, GammaDoseModel, transmission
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
