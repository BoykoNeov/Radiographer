"""Regression suite for the bundled fission-product fallout vector (§8 / §13 #5; M7d).

The datasets are the project (CLAUDE.md). Pillars:

1. **Structural** — schema/id invariants, non-empty, every nuclide solvable, yields positive.
2. **Cited goldens (NOT from memory)** — the dominant cumulative yields match the textbook
   ENDF/B U-235 thermal values (Cs-137 ≈ 6.2 %, I-131 ≈ 2.9 %, Zr-95 ≈ 6.5 %, …); a parse/
   unit slip misses these by far more than the tolerance.
3. **The physics golden — Way–Wigner t⁻¹·² (7:10 rule).** This is what makes the vector
   honest rather than a fabricated mix: seed the vector, decay it forward through the Bateman
   engine, and confirm the gross-γ source strength (Σ Aₙ·Ēγ,ₙ) falls as ≈ t⁻¹·² over H+1 h …
   ~30 d. A wrong inventory would not reproduce the law.
"""

from __future__ import annotations

import math

import pytest

from engine import emissions as em
from engine import fallout as fo
from engine.inventory import SolvedInventory

VECTOR_ID = "u235_fission_fallout"

# Textbook ENDF/B U-235 THERMAL cumulative fission yields (per fission) for the dominant
# long-lived γ emitters — an INDEPENDENT golden (these are standard, widely tabulated values),
# not a copy of the build's output. Tolerance covers evaluation/rounding differences.
PUBLISHED_CUMULATIVE_YIELDS = {
    "Cs-137": 0.0619,
    "I-131": 0.0289,
    "Zr-95": 0.0650,
    "Ba-140": 0.0621,
    "Sr-90": 0.0578,
    "Mo-99": 0.0611,
    "Ce-144": 0.0550,
}


def _vector() -> dict:
    return fo.load_vector(VECTOR_ID)


# --------------------------------------------------------------------------- #
# 1. Structural.
# --------------------------------------------------------------------------- #

def test_vector_present_and_structural():
    assert VECTOR_ID in fo.available_sources()
    rec = _vector()
    assert rec["id"] == VECTOR_ID
    assert rec["yield_type"] == "cumulative"
    assert rec["entries"], "empty fallout vector is a data hole"
    assert rec["n_nuclides"] == len(rec["entries"])
    for e in rec["entries"]:
        assert e["yield_per_fission"] > 0
        SolvedInventory.from_spec({e["name"]: 1.0}, "atoms")  # every nuclide must be solvable


def test_loader_rejects_unknown_vector():
    with pytest.raises(fo.FalloutError):
        fo.load_vector("no-such-vector")


# --------------------------------------------------------------------------- #
# 2. Cited goldens — dominant yields match textbook ENDF/B U-235 thermal values.
# --------------------------------------------------------------------------- #

def test_dominant_yields_match_published():
    yld = {e["name"]: e["yield_per_fission"] for e in _vector()["entries"]}
    for name, ref in PUBLISHED_CUMULATIVE_YIELDS.items():
        assert name in yld, f"{name} missing from the fallout vector"
        assert yld[name] == pytest.approx(ref, rel=0.05), f"{name} yield {yld[name]} vs published {ref}"


# --------------------------------------------------------------------------- #
# 3. The physics golden — Way–Wigner t⁻¹·² (7:10) decay law.
# --------------------------------------------------------------------------- #

def _gross_gamma_slope(t_lo_s: float, t_hi_s: float, n: int = 30) -> float:
    """log-log slope of the gross-γ source strength Σ Aₙ(t)·Ēγ,ₙ over [t_lo, t_hi]."""
    inv = {e["name"]: e["yield_per_fission"] for e in _vector()["entries"]}
    sol = SolvedInventory.from_spec(inv, "atoms")
    grid = [t_lo_s * (t_hi_s / t_lo_s) ** (i / n) for i in range(n + 1)]
    res = sol.evaluate(grid, axis="activity", unit="Bq")

    def ebar(name: str) -> float:  # mean γ energy per decay (MeV)
        try:
            return sum(p.get("E_MeV", 0.0) * p.get("yield", 0.0) for p in em.photons(name))
        except Exception:  # noqa: BLE001 - nuclide without emission data contributes nothing
            return 0.0

    eb = {nm: ebar(nm) for nm in res["nuclides"]}
    s = [sum(res["series"][nm][j] * eb[nm] for nm in res["nuclides"]) for j in range(len(grid))]
    return (math.log(s[-1]) - math.log(s[0])) / (math.log(grid[-1]) - math.log(grid[0]))


def test_gross_gamma_follows_way_wigner_t_minus_1_2():
    # The 7:10 rule: gross γ ∝ t⁻¹·². Over H+1 h … 30 d the decayed vector must reproduce it.
    # A broken inventory (wrong nuclides / unit slip) would land far from −1.2.
    HOUR = 3600.0
    slope = _gross_gamma_slope(1 * HOUR, 30 * 24 * HOUR)
    assert slope == pytest.approx(-1.2, abs=0.1), f"gross-γ slope {slope:.3f} ≠ Way–Wigner −1.2"


def test_catalog_source_loadable_shape():
    # The §8 picker record: a Weapons-material source whose inventory is atoms, loaded at t=0.
    cat = fo.catalog()
    assert len(cat) >= 1
    src = next(s for s in cat if s["id"] == VECTOR_ID)
    assert src["category"] == "Weapons material"
    assert src["referenceTimeS"] == 0.0
    assert all(e["unit"] == "atoms" and e["quantity"] > 0 for e in src["entries"])
    assert "7:10" in src["blurb"] or "t⁻¹" in src["blurb"]
