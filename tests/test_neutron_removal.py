"""Regression suite for the bundled NCRP-20 fast-neutron removal cross-sections (M10, §6.3).

The datasets are the project (CLAUDE.md), so the data lands with its validation. These tests
exercise the **committed JSON** and re-derive every physics anchor INDEPENDENTLY of the build
script, from two separate published sources:

1. **Structural** — schema, required keys, Σ_R > 0, hydrogen present in the shipped set.
2. **Mixture-rule exactness (Akyıldırım 2019, Table 2)** — recomputing glucose C₆H₁₂O₆ from
   the elemental Σ_R/ρ {H 0.602, C 0.051, O 0.041} reproduces its published 0.129 cm⁻¹ EXACTLY.
   This is the same machinery that builds the shipped materials, checked against its own worked
   example (validates the implementation, not just the data).
3. **Independent cross-source (El Abd 2017, Table 1)** — the engine's water Σ_R matches a
   SEPARATE group's MEASURED value (0.1023 cm⁻¹) to a few percent. Two unrelated sources agree.
4. **Physical sanity** — relaxation length 1/Σ_R and TVL ln10/Σ_R land in the expected cm range
   for hydrogenous shields; the loader rejects malformed records.
"""

from __future__ import annotations

import math

import pytest

from engine import neutron_removal as nr

# NCRP-20 (1957) measured elemental mass removal cross-sections (cm²/g), independent of the
# build script's copy — re-stated here so a typo in either is caught by the cross-checks below.
SIGMA_MASS = {"H": 0.602, "C": 0.051, "O": 0.041}
ATOMIC_W = {"H": 1.008, "C": 12.011, "O": 15.999}

SHIPPED = ("water", "polyethylene", "pmma")


def _compound_sigma_r(stoich: dict[str, int], rho: float) -> float:
    """Mixture-rule Σ_R (cm⁻¹) from scratch: Σ_R = ρ·Σ w_i·(Σ_R/ρ)_i."""
    masses = {el: n * ATOMIC_W[el] for el, n in stoich.items()}
    total = sum(masses.values())
    sigma_mass = sum((masses[el] / total) * SIGMA_MASS[el] for el in stoich)
    return rho * sigma_mass


# -- 1. structural -----------------------------------------------------------

def test_shipped_set_present():
    assert set(SHIPPED) <= nr.available_materials()


@pytest.mark.parametrize("material", SHIPPED)
def test_record_schema(material):
    rec = nr.load_removal(material)
    assert rec["schema_version"] == nr.SCHEMA_VERSION
    assert rec["material"] == material
    assert nr.sigma_r_cm1(material) > 0.0
    assert nr.density(material) > 0.0
    # Every shipped material is hydrogenous — that is the whole point of the set (§6.3).
    assert nr.hydrogen_weight_fraction(material) > 0.0


# -- 2. mixture-rule exactness vs Akyıldırım (2019) Table 2 -------------------

def test_glucose_reproduces_akyildirim_table2():
    """Glucose C₆H₁₂O₆, ρ=1.562 → Akyıldırım (2019) Table 2 publishes Σ_R = 0.129 cm⁻¹."""
    sigma = _compound_sigma_r({"C": 6, "H": 12, "O": 6}, 1.562)
    assert sigma == pytest.approx(0.129, abs=5e-4)


# -- 3. independent cross-source: water vs El Abd (2017) Table 1 -------------

def test_water_matches_independent_measurement():
    """Engine water Σ_R vs El Abd et al. (2017) MEASURED 0.1023 cm⁻¹ — separate group, ~1.5%."""
    measured = 0.1023
    assert nr.sigma_r_cm1("water") == pytest.approx(measured, rel=0.03)


@pytest.mark.parametrize("material,stoich", [
    ("water", {"H": 2, "O": 1}),
    ("polyethylene", {"C": 1, "H": 2}),
    ("pmma", {"C": 5, "H": 8, "O": 2}),
])
def test_shipped_values_match_independent_mixture_rule(material, stoich):
    """The committed Σ_R equals a from-scratch mixture-rule recompute at the file's density."""
    expected = _compound_sigma_r(stoich, nr.density(material))
    assert nr.sigma_r_cm1(material) == pytest.approx(expected, rel=1e-4)


# -- 4. physical sanity ------------------------------------------------------

@pytest.mark.parametrize("material", SHIPPED)
def test_relaxation_length_in_hydrogenous_range(material):
    """1/Σ_R is the fast-neutron relaxation length; ~5–12 cm for these hydrogenous shields."""
    relax_cm = 1.0 / nr.sigma_r_cm1(material)
    assert 5.0 < relax_cm < 12.0


def test_water_relaxation_and_tvl():
    sigma = nr.sigma_r_cm1("water")
    assert (1.0 / sigma) == pytest.approx(9.6, abs=0.6)          # relaxation length ~9.6 cm
    assert (math.log(10.0) / sigma) == pytest.approx(22.0, abs=2.0)  # TVL ~22 cm


def test_missing_material_raises():
    with pytest.raises(nr.RemovalError):
        nr.load_removal("lead")  # γ shield, no removal data — loud, not transparent-zero here
