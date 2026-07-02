"""Regression suite for the bundled fluence-to-dose conversion coefficients (§6.4, §7).

The datasets are the project (CLAUDE.md), so each table is validated the moment it lands.
Four independent pillars, mirroring the attenuation/buildup suites:

1. **Structural** — schema, array alignment, ascending E, positive finite coefficients,
   and the quantity/geometry/particle/units invariants.
2. **Transform integrity** — canonical == vendored, re-parsed from the raw OpenMC ``.txt``
   by an *independent* method (``numpy.loadtxt``, not the build's float-first split). A
   drop, dup, mis-row, or value-mangle breaks the multiset equality.
3. **Coverage** — all 6 effective geometries + H*(10); both directions (no strays).
4. **Physics goldens (citable & independent, NOT from memory or OpenMC itself):**
   - Effective: vendored AP coeffs vs a **separate group's** ICRP-116 piecewise-poly fit
     (PMC6074822, ≤3%) across the energy range, + a geometry-ordering relation (catches a
     column swap). Absolute ICRP-116 values from OpenMC are *not* re-asserted as "goldens" —
     the transform-integrity pillar already proves canonical == OpenMC wholesale.
   - H*(10): the derived ``H*(10)/Ka = (H*(10)/Φ)/(Ka/Φ)`` reproduces the canonical
     ICRU-57 **sphere** response, anchored to the **IAEA** slab Hp(10,0°)/Ka table at the
     energies where sphere==slab (low-E coincidence + MeV re-convergence); the 50–200 keV
     interior is checked structurally (slab ≠ sphere there). See docs/plans/M2-conversion.md.

Trust boundary (honesty): integrity proves canonical == vendored; faithfulness to true
ICRP-74/116 is anchored at the golden energies and otherwise trusted to OpenMC (effective:
verbatim incl. corrigendum; H*(10): the unmerged PR #3256 transcription). Same shape as
the emissions/buildup golden-subset boundary.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from engine import conversion as cv

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "data" / "vendor" / "openmc_dose"
CANON = ROOT / "data" / "conversion"

EFFECTIVE_SRC = VENDOR / "icrp116_photons.txt"
AMBIENT_SRC = VENDOR / "icrp74_photons_H10.txt"
EFFECTIVE_SRC_N = VENDOR / "icrp116_neutrons.txt"
AMBIENT_SRC_N = VENDOR / "icrp74_neutrons_H10.txt"

GEOMETRIES = ("AP", "PA", "LLAT", "RLAT", "ROT", "ISO")
REQUIRED = (
    {"hstar10", "hstar10_neutron"}
    | {f"effective_{g}" for g in GEOMETRIES}
    | {f"effective_neutron_{g}" for g in GEOMETRIES}
)
ALL = sorted(p.stem for p in CANON.glob("*.json"))

# --------------------------------------------------------------------------- #
# Independent cross-check data (cited, hardcoded — NOT read from the build).
# --------------------------------------------------------------------------- #

# ICRP-74 Table A.1 — air kerma per fluence Ka/Φ (pGy·cm²), monoenergetic photons, on the
# SAME 25-energy grid as the H*(10)/Φ table. Transcribed from OpenMC's *independent*
# generate_photon_effective_dose.py (the module that derives ICRP-74 effective dose),
# so dividing H*(10)/Φ by it is a cross-source check, not circular.
ICRP74_KA_PHI = {
    0.01: 7.43,
    0.015: 3.12,
    0.02: 1.68,
    0.03: 0.721,
    0.04: 0.429,
    0.05: 0.323,
    0.06: 0.289,
    0.08: 0.307,
    0.1: 0.371,
    0.15: 0.599,
    0.2: 0.856,
    0.3: 1.38,
    0.4: 1.89,
    0.5: 2.38,
    0.6: 2.84,
    0.8: 3.69,
    1.0: 4.47,
    1.5: 6.14,
    2.0: 7.55,
    3.0: 9.96,
    4.0: 12.1,
    5.0: 14.1,
    6.0: 16.1,
    8.0: 20.1,
    10.0: 24.0,
}

# IAEA training doc "Quantities" — Hp(10,0°)/Ka (Sv/Gy), monoenergetic photons, ICRU
# slab. Sphere H*(10)/Ka and slab Hp(10,0°)/Ka COINCIDE at low E (geometry irrelevant) and
# RE-CONVERGE at MeV energies (backscatter vanishes); they diverge only in the 50–200 keV
# backscatter regime (slab > sphere). Used as the independent anchor where they coincide.
IAEA_HP_KA = {0.015: 0.264, 0.03: 1.112, 0.04: 1.490, 1.0: 1.167, 3.0: 1.117}

# Independent reproduction of ICRP-116 photon effective dose, AP geometry: the piecewise-
# polynomial fit of Veinot et al., "Piecewise Polynomial Approximations to the ICRP 116
# Effective Dose Coefficients" (PMC6074822). h(E) = exp(Σ_k c_k · ln(E)^k), E in MeV, three
# energy intervals; the paper states it reproduces ICRP-116 to ≤ 3%. This is a SEPARATE
# group's transcription+fit of ICRP-116 — not OpenMC — so matching it is genuine
# cross-source corroboration (the transform-integrity test only proves canonical == OpenMC).
ICRP116_AP_FIT = (  # (E_lo, E_hi, [c0, c1, c2, c3, c4])
    (0.010, 0.060, [8.3446, 9.5872, 3.5195, 0.5075, 0.0179]),
    (0.060, 1.5, [1.4903, 0.7900, -0.0401, 0.0722, 0.0273]),
    (1.5, 40.0, [1.4872, 0.8632, -0.1937, 0.0667, -0.0087]),
)


def _icrp116_ap_fit(energy: float) -> float:
    x = math.log(energy)
    for lo, hi, c in ICRP116_AP_FIT:
        if lo - 1e-9 < energy <= hi + 1e-9:
            return math.exp(sum(c[k] * x**k for k in range(5)))
    raise ValueError(f"{energy} MeV outside the fitted range")


# --------------------------------------------------------------------------- #
# 0. The dataset exists (fail-first sentinel before the build has run).
# --------------------------------------------------------------------------- #


def test_dataset_is_present_and_complete():
    missing = sorted(REQUIRED - set(ALL))
    assert not missing, (
        f"missing conversion files {missing}; run `python data/build/build_conversion.py`"
    )


# --------------------------------------------------------------------------- #
# 1. Structural / schema / physical sanity.
# --------------------------------------------------------------------------- #


def test_effective_schema_and_sanity():
    for g in GEOMETRIES:
        d = cv.load("effective", g)  # validates version/quantity/geom/units/align
        e, c = d["E_MeV"], d["coeff_pSv_cm2"]
        assert e == sorted(e) and len(set(e)) == len(e), f"{g}: E not strictly ascending"
        assert e[0] == pytest.approx(0.01) and e[-1] == pytest.approx(10000.0), f"{g}: grid bounds"
        for ei, ci in zip(e, c):
            assert math.isfinite(ei) and ei > 0
            assert math.isfinite(ci) and ci > 0


def test_ambient_schema_and_sanity():
    d = cv.load("ambient_H10")
    assert d["geometry"] is None
    e, c = d["E_MeV"], d["coeff_pSv_cm2"]
    assert e == sorted(e) and len(set(e)) == len(e)
    assert e[0] == pytest.approx(0.01) and e[-1] == pytest.approx(10.0), "H*(10) grid 0.01–10 MeV"
    for ei, ci in zip(e, c):
        assert math.isfinite(ei) and ei > 0
        assert math.isfinite(ci) and ci > 0


def test_loader_rejects_bad_quantity_and_geometry():
    with pytest.raises(cv.ConversionError):
        cv.load("ambient_H10", "AP")  # H*(10) takes no geometry
    with pytest.raises(cv.ConversionError):
        cv.load("effective")  # effective requires a geometry
    with pytest.raises(cv.ConversionError):
        cv.load("effective", "TOP")  # not a real geometry
    with pytest.raises(cv.ConversionError):
        cv.load("equivalent")  # unknown quantity


# --------------------------------------------------------------------------- #
# 2. Transform integrity — independent re-parse (numpy, not the build's split).
# --------------------------------------------------------------------------- #


def _independent_table(path: Path) -> np.ndarray:
    """Re-parse a vendored OpenMC dose table independently (3 header lines, then data)."""
    return np.loadtxt(path, skiprows=3, encoding="utf-8")


def test_effective_rows_match_independent_parse():
    indep = _independent_table(EFFECTIVE_SRC)  # cols: E, AP, PA, LLAT, RLAT, ROT, ISO
    e_indep = indep[:, 0]
    for gi, g in enumerate(GEOMETRIES, start=1):
        d = cv.load("effective", g)
        assert np.allclose(d["E_MeV"], e_indep, rtol=0, atol=0), f"{g}: energy grid drift"
        assert np.array_equal(d["coeff_pSv_cm2"], indep[:, gi]), (
            f"{g}: canonical coeffs differ from independent parse"
        )


def test_ambient_rows_match_independent_parse():
    indep = _independent_table(AMBIENT_SRC)  # cols: E, H*(10)/Φ
    d = cv.load("ambient_H10")
    assert np.array_equal(d["E_MeV"], indep[:, 0]), "H*(10): energy grid drift"
    assert np.array_equal(d["coeff_pSv_cm2"], indep[:, 1]), (
        "H*(10): canonical coeffs differ from independent parse"
    )


# --------------------------------------------------------------------------- #
# 3. Coverage — all quantities/geometries, both directions.
# --------------------------------------------------------------------------- #


def test_required_coverage_both_directions():
    have = set(ALL)
    assert REQUIRED <= have, f"missing: {sorted(REQUIRED - have)}"
    assert have <= REQUIRED, f"unexpected conversion files: {sorted(have - REQUIRED)}"


# --------------------------------------------------------------------------- #
# 4a. Effective goldens — independent ICRP-116 Table A.1 values + ordering.
# --------------------------------------------------------------------------- #


def _coeff_at(quantity: str, geometry: str | None, energy: float) -> float:
    e = cv.energies(quantity, geometry)
    c = cv.coefficients_pSv_cm2(quantity, geometry)
    hits = [c[i] for i, ei in enumerate(e) if abs(ei - energy) <= 1e-6 * energy]
    assert len(hits) == 1, f"{quantity}/{geometry}: expected one grid row near {energy} MeV"
    return hits[0]


def test_golden_effective_ap_vs_independent_icrp116_fit():
    """Cross-source: vendored AP coeffs vs an INDEPENDENT ICRP-116 fit (PMC6074822, ≤3%).

    Spans all three fit intervals (30 keV / 0.1–1.5 MeV / 6 MeV). A wrong column, unit, or
    geometry would miss by far more than the paper's 3% fit accuracy; the observed match is
    ≤1.2%. This is the only effective-dose check that tests OpenMC → true ICRP-116 (the
    transform-integrity pillar proves only canonical == OpenMC).
    """
    for energy in (0.03, 0.05, 0.1, 0.5, 1.0, 1.5, 6.0):
        got = _coeff_at("effective", "AP", energy)
        ref = _icrp116_ap_fit(energy)
        assert got == pytest.approx(ref, rel=0.03), (
            f"effective AP @ {energy} MeV: vendored {got} vs independent fit {ref:.3f} (>3%)"
        )


def test_golden_effective_geometry_ordering():
    # At 1 MeV the frontal AP field gives the largest E; the rotational ROT exceeds the
    # isotropic ISO; lateral/posterior are smaller (ICRP-116 §3.2 geometry physics).
    vals = {g: _coeff_at("effective", g, 1.0) for g in GEOMETRIES}
    assert vals["AP"] == max(vals.values()), vals
    assert vals["AP"] > vals["PA"] > vals["ISO"], vals
    assert vals["ROT"] > vals["ISO"] > vals["RLAT"], vals


# --------------------------------------------------------------------------- #
# 4b. H*(10) goldens — derived H*(10)/Ka vs the independent IAEA table.
# --------------------------------------------------------------------------- #


def _derived_h10_over_ka() -> dict[float, float]:
    """H*(10)/Ka = (H*(10)/Φ) / (Ka/Φ) on the shared ICRP-74 grid (no interpolation)."""
    e, h10 = cv.ambient_h10()
    out = {}
    for ei, hi in zip(e, h10):
        key = min(ICRP74_KA_PHI, key=lambda k: abs(k - ei))
        assert abs(key - ei) <= 1e-6 * max(ei, key), f"H*(10) grid mismatch vs Ka/Φ at {ei}"
        out[round(ei, 6)] = hi / ICRP74_KA_PHI[key]
    return out


def test_golden_h10_over_ka_matches_iaea_anchors():
    """Independent cross-source anchor where sphere H*(10)/Ka == slab Hp(10,0°)/Ka.

    Low-E (≤40 keV) coincidence + MeV (≥1 MeV) re-convergence. The 50–200 keV backscatter
    regime is intentionally NOT anchored here (slab ≠ sphere) — checked structurally below.
    """
    derived = _derived_h10_over_ka()
    for energy, iaea in IAEA_HP_KA.items():
        got = derived[round(energy, 6)]
        assert got == pytest.approx(iaea, rel=0.015), (
            f"H*(10)/Ka at {energy} MeV: derived {got:.4f} vs IAEA {iaea} (>1.5%)"
        )


def test_golden_h10_sphere_response_shape():
    """The ICRU-57 sphere signature: a single peak ~1.7–1.8 near 60–80 keV, then monotone.

    This distinguishes the shipped ambient (sphere) quantity from both the slab Hp (peak
    ~1.90) and the new ICRU-95 vintage — the structural check over the 50–200 keV interior
    that the cited anchors deliberately skip.
    """
    derived = _derived_h10_over_ka()
    peak_e = max(derived, key=lambda k: derived[k])
    assert 0.05 <= peak_e <= 0.08, f"H*(10)/Ka peaks at {peak_e} MeV (expected 60–80 keV)"
    assert 1.70 <= derived[peak_e] <= 1.80, f"sphere peak {derived[peak_e]:.3f} (expected ~1.77)"
    # H*(10)/Φ has TWO low-energy features: a spike to a local max ~20 keV, then the
    # Compton dip to a local minimum ~60 keV; above that dip it rises monotonically. (The
    # global min is the 10 keV attenuation floor, not the Compton dip.) Restrict to the
    # Compton branch E ≥ 30 keV to locate the dip and assert the monotone rise above it.
    e, h10 = cv.ambient_h10()
    branch = [(ei, hi) for ei, hi in zip(e, h10) if ei >= 0.03 - 1e-9]
    i_dip = min(range(len(branch)), key=lambda i: branch[i][1])
    assert 0.05 <= branch[i_dip][0] <= 0.08, (
        f"H*(10)/Φ Compton minimum at {branch[i_dip][0]} MeV (expected ~60 keV)"
    )
    above = [hi for _ei, hi in branch[i_dip:]]
    assert all(above[i] < above[i + 1] for i in range(len(above) - 1)), "monotone above the dip"


def test_accessor_helpers_agree_with_load():
    e1, c1 = cv.ambient_h10()
    assert (e1, c1) == (cv.energies("ambient_H10"), cv.coefficients_pSv_cm2("ambient_H10"))
    e2, c2 = cv.effective("AP")
    assert (e2, c2) == (cv.energies("effective", "AP"), cv.coefficients_pSv_cm2("effective", "AP"))


# =========================================================================== #
# NEUTRON (M5) — the same four pillars on the particle="neutron" tables.
# The neutron effective table is CLEAN (blob-SHA == OpenMC tree); the neutron H*(10) table
# is the DEGRADED unmerged-PR transcription. Transform integrity proves canonical == vendored
# here; faithfulness of the H*(10) values to true ICRP-74 is the M5 ISO-8529 spectrum-averaged
# triangle in tests/test_dose_neutron.py (the independent cross-check for the degraded table).
# =========================================================================== #


def test_neutron_effective_schema_and_sanity():
    for g in GEOMETRIES:
        d = cv.load("effective", g, "neutron")  # validates version/quantity/geom/units/particle
        assert d["particle"] == "neutron"
        e, c = d["E_MeV"], d["coeff_pSv_cm2"]
        assert e == sorted(e) and len(set(e)) == len(e), f"{g}: E not strictly ascending"
        # Neutron effective grid spans thermal (1e-9 MeV) → 10 GeV.
        assert e[0] == pytest.approx(1e-9) and e[-1] == pytest.approx(10000.0), f"{g}: grid bounds"
        for ei, ci in zip(e, c):
            assert math.isfinite(ei) and ei > 0
            assert math.isfinite(ci) and ci > 0


def test_neutron_ambient_schema_and_sanity():
    d = cv.load("ambient_H10", None, "neutron")
    assert d["geometry"] is None and d["particle"] == "neutron"
    e, c = d["E_MeV"], d["coeff_pSv_cm2"]
    assert e == sorted(e) and len(set(e)) == len(e)
    # Neutron H*(10) grid: thermal (1e-9 MeV) → 20 MeV (the ICRP-74 neutron end, below the
    # 10 GeV effective end — the off-grid contract differs by particle, enforced by the engine).
    assert e[0] == pytest.approx(1e-9) and e[-1] == pytest.approx(20.0), (
        "neutron H*(10) grid 1e-9–20 MeV"
    )
    for ei, ci in zip(e, c):
        assert math.isfinite(ei) and ei > 0
        assert math.isfinite(ci) and ci > 0


def test_neutron_effective_rows_match_independent_parse():
    indep = _independent_table(EFFECTIVE_SRC_N)  # cols: E, AP, PA, LLAT, RLAT, ROT, ISO
    e_indep = indep[:, 0]
    for gi, g in enumerate(GEOMETRIES, start=1):
        d = cv.load("effective", g, "neutron")
        assert np.array_equal(d["E_MeV"], e_indep), f"{g}: neutron energy grid drift"
        assert np.array_equal(d["coeff_pSv_cm2"], indep[:, gi]), (
            f"{g}: neutron canonical coeffs differ from independent parse"
        )


def test_neutron_ambient_rows_match_independent_parse():
    indep = _independent_table(AMBIENT_SRC_N)  # cols: E, H*(10)/Φ
    d = cv.load("ambient_H10", None, "neutron")
    assert np.array_equal(d["E_MeV"], indep[:, 0]), "neutron H*(10): energy grid drift"
    assert np.array_equal(d["coeff_pSv_cm2"], indep[:, 1]), (
        "neutron H*(10): canonical coeffs differ from independent parse"
    )


def test_particle_isolation():
    """Photon and neutron are distinct datasets; the embedded particle field guards mixing."""
    assert cv.energies("ambient_H10") != cv.energies("ambient_H10", None, "neutron")
    assert cv.energies("effective", "AP") != cv.energies("effective", "AP", "neutron")
    with pytest.raises(cv.ConversionError):
        cv.load("ambient_H10", None, "muon")  # unknown particle


def test_golden_neutron_h10_dip_and_fast_rise():
    """The neutron H*(10)/Φ signature: an epithermal hump (~0.5 eV), a valley minimum in the
    ~1–5 keV "neutron dip", a steep monotone climb to a broad ~1 MeV plateau, with fast
    neutrons scoring tens of times higher than thermal (the w_R(E) weighting baked into the
    coefficient). This qualitative shape distinguishes the neutron table from the photon one
    and catches a column/particle mix-up — without asserting memorized values (faithfulness of
    the degraded H*(10) table to true ICRP-74 is the ISO-8529 triangle's job).
    """
    e, h = cv.ambient_h10("neutron")

    def _at(energy: float) -> float:
        return h[min(range(len(e)), key=lambda i: abs(e[i] - energy))]

    # The intermediate "neutron dip": the local minimum between the epithermal hump and the
    # fast rise. Search the intermediate window (excludes the thermal-floor global min at 1e-9).
    window = [(ei, hi) for ei, hi in zip(e, h) if 5e-5 <= ei <= 1e-2]
    dip_e, dip_h = min(window, key=lambda t: t[1])
    assert 1e-3 <= dip_e <= 5e-3, f"neutron H*(10) dip at {dip_e} MeV (expected ~1–5 keV)"

    # Epithermal hump sits above both the dip and the thermal point.
    assert _at(5e-7) > _at(2.53e-8) > dip_h, "epithermal hump > thermal > keV dip"

    # Steep monotone climb from the dip up to the ~1 MeV plateau.
    climb = [hi for ei, hi in zip(e, h) if dip_e <= ei <= 1.0]
    assert all(climb[i] < climb[i + 1] for i in range(len(climb) - 1)), "monotone dip → 1 MeV"

    # Fast neutrons score far above thermal and the dip.
    assert _at(1.0) > 20 * _at(2.53e-8), "fast ≫ thermal"
    assert _at(1.0) > 30 * dip_h, "fast ≫ dip"
