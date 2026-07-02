"""Regression suite for the bundled ICRP-107 emission spectra (HANDOFF_PLAN.md §7).

The datasets are the project (CLAUDE.md), so each table is validated the moment it
lands. Four independent pillars, per the M2 design review:

1. **Structural** — every canonical file matches the schema and is physically sane.
2. **Transform integrity** — canonical == upstream, re-derived *independently* of
   ``build_emissions.transform`` (so a bug in the extractor cannot hide behind itself):
   the full multiset of (category, energy, value) triples must survive the rebuild.
3. **Coverage** — every radioactive nuclide rd knows has an emission file; a missing
   one would be a silent dose hole (§11), so this is a hard assertion.
4. **Physics goldens** — a handful of marquee nuclides asserted against *independent*
   NNDC/ENSDF nominal intensities (NOT copied from the ICRP file), incl. a β⁺ emitter
   to pin the annihilation-photon convention.

The half-life check is a *parse canary* (did we read the right file and its time_unit
correctly), not a physics claim — rd remains the single source of truth for half-lives.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import radioactivedecay as rd

from engine import emissions as em

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "data" / "vendor" / "icrp107"
CANON = ROOT / "data" / "emissions"

ALL = sorted(p.stem for p in CANON.glob("*.json"))

# ICRP-107 expresses half-lives in these units only (enumerated from the data); an
# unrecognised unit must hard-fail so a parse bug can't silently become NaN.
UNIT_S = {
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
    "y": 365.25 * 86400.0,
    "ms": 1e-3,
    "us": 1e-6,
}

# How each canonical group maps back to upstream ICRP categories (for the
# independent integrity check). Inverse of the build's routing.
CANON_TO_UPSTREAM = {
    "photons": ("origin", {"gamma", "X", "annihilation"}, "E_MeV", "yield"),
    "betas": ("kind", {"beta-", "beta+"}, "E_mean_MeV", "yield"),
    "alphas": (None, {"alpha"}, "E_MeV", "yield"),
    "electrons": ("origin", {"auger", "IE"}, "E_MeV", "yield"),
    "neutrons": (None, {"neutron"}, "E_MeV", "yield"),
    "beta_spectra": (None, {"b-spectra"}, "E_MeV", "intensity"),
}


def _load_upstream(name: str) -> dict:
    """Decode an upstream file's two JSON layers (it is a JSON-string of JSON)."""
    return json.loads(json.load(open(VENDOR / f"{name}.json", encoding="utf-8")))


def _upstream_triples(name: str) -> list[tuple[str, float, float]]:
    out = []
    for cat, rows in _load_upstream(name)["emissions"].items():
        for e, v in rows:
            out.append((cat, e, v))
    return sorted(out)


def _canonical_triples(data: dict) -> list[tuple[str, float, float]]:
    """Re-project a canonical file back into (upstream_category, E, value) triples."""
    out = []
    for group, (tagkey, cats, ekey, vkey) in CANON_TO_UPSTREAM.items():
        for entry in data.get(group, []):
            cat = entry[tagkey] if tagkey else next(iter(cats))
            out.append((cat, entry[ekey], entry[vkey]))
    for cat, rows in data.get("extra", {}).items():
        for e, v in rows:
            out.append((cat, e, v))
    return sorted(out)


# --------------------------------------------------------------------------- #
# 0. The dataset exists (fail-first sentinel before the build has run).
# --------------------------------------------------------------------------- #


def test_dataset_is_present_and_complete():
    assert len(ALL) == 1252, (
        f"expected 1252 canonical emission files, found {len(ALL)}; "
        "run `python data/build/build_emissions.py`"
    )


# --------------------------------------------------------------------------- #
# 1. Structural / schema.
# --------------------------------------------------------------------------- #


def test_schema_and_physical_sanity():
    for name in ALL:
        data = em.load_emissions(name)  # validates version + name
        for group in ("photons", "betas", "alphas", "electrons", "neutrons", "beta_spectra"):
            assert isinstance(data[group], list)
        # photons ascending in energy (dose engine relies on it)
        es = [p["E_MeV"] for p in data["photons"]]
        assert es == sorted(es), f"{name}: photons not sorted by energy"
        for p in data["photons"]:
            assert p["origin"] in {"gamma", "X", "annihilation"}
            assert p["E_MeV"] > 0 and math.isfinite(p["E_MeV"])
            assert p["yield"] >= 0 and math.isfinite(p["yield"])
        for b in data["betas"]:
            assert b["kind"] in {"beta-", "beta+"}
            assert b["E_mean_MeV"] >= 0 and b["yield"] >= 0
        for e in data["electrons"]:
            assert e["origin"] in {"auger", "IE"}
        for s in data["beta_spectra"]:
            assert s["E_MeV"] >= 0 and s["intensity"] >= 0  # E starts at 0


def test_loader_raises_on_missing_nuclide():
    with pytest.raises(em.EmissionsError):
        em.load_emissions("Xx-999")


# --------------------------------------------------------------------------- #
# 2. Transform integrity — independent of the build's transform().
# --------------------------------------------------------------------------- #


def test_transform_preserves_every_upstream_value():
    """No emission line dropped, duplicated, mis-routed, or value-mangled."""
    for name in ALL:
        data = em.load_emissions(name)
        assert _canonical_triples(data) == _upstream_triples(name), name


def test_annihilation_routed_into_photons():
    na22 = em.load_emissions("Na-22")
    ann = [p for p in na22["photons"] if p["origin"] == "annihilation"]
    assert ann and all(abs(p["E_MeV"] - 0.511) < 1e-3 for p in ann)


# --------------------------------------------------------------------------- #
# 3. Coverage — no silent dose holes (§11).
# --------------------------------------------------------------------------- #


def test_every_radioactive_nuclide_has_emissions():
    have = set(ALL)
    missing = []
    stable_with_file = []
    for n in rd.DEFAULTDATA.nuclides:
        nuc = rd.Nuclide(n)
        finite = math.isfinite(nuc.half_life("s"))
        if finite and n not in have:
            missing.append(n)
        if not finite and n in have:
            stable_with_file.append(n)
    assert not missing, f"radioactive nuclides with no emission file: {missing[:20]}"
    # The converse: emission files should be radioactive nuclides only.
    assert not stable_with_file, f"stable nuclides with an emission file: {stable_with_file[:20]}"


# --------------------------------------------------------------------------- #
# 4. Half-life parse canary (rd stays the source of truth for half-lives).
# --------------------------------------------------------------------------- #


def test_half_life_parse_canary():
    worst = 0.0
    for name in ALL:
        up = _load_upstream(name)
        unit = up["time_unit"]
        assert unit in UNIT_S, f"{name}: unknown time_unit {unit!r}"
        icrp_s = up["half_life"] * UNIT_S[unit]
        rd_s = rd.Nuclide(name).half_life("s")
        assert math.isfinite(rd_s) and rd_s > 0, name
        rel = abs(icrp_s - rd_s) / rd_s
        worst = max(worst, rel)
        # Gross mismatch == a parse/unit/mapping bug (those are orders of magnitude).
        assert rel < 0.05, f"{name}: half-life parse mismatch {rel:.3%} (unit={unit})"
    # Regression sentinel: the real ICRP-vs-nubase spread is ~0.002% (year residual).
    assert worst < 0.005, f"half-life spread grew to {worst:.4%} — investigate"


# --------------------------------------------------------------------------- #
# 5. Physics goldens — independent NNDC/ENSDF nominal intensities, hardcoded.
#    (energy_MeV, half-window_MeV, yield_low, yield_high)
# --------------------------------------------------------------------------- #

GOLDENS = {
    # Co-60: dual gamma, both ~100% (NNDC 99.85 % / 99.9826 %).
    "Co-60": [(1.1732, 1e-3, 0.995, 1.0), (1.3325, 1e-3, 0.995, 1.0)],
    # Ba-137m: the 661.7 keV line, ~89.9 % per Ba-137m decay.
    "Ba-137m": [(0.6617, 1e-3, 0.85, 0.92)],
    # Am-241: 59.54 keV gamma, ~35.9 %.
    "Am-241": [(0.05954, 5e-4, 0.33, 0.39)],
    # Na-22 gamma: 1274.5 keV, ~99.94 %.
    "Na-22": [(1.2746, 1e-3, 0.99, 1.0)],
    # I-131: 364.5 keV, ~81.5 %.
    "I-131": [(0.3645, 1e-3, 0.78, 0.84)],
    # Tc-99m: 140.5 keV, ~88.5 %.
    "Tc-99m": [(0.1405, 1e-3, 0.86, 0.90)],
}


@pytest.mark.parametrize("nuclide", sorted(GOLDENS))
def test_photon_goldens_against_independent_values(nuclide):
    photons = em.photons(nuclide)
    for energy, window, ylo, yhi in GOLDENS[nuclide]:
        near = [p for p in photons if abs(p["E_MeV"] - energy) <= window]
        assert near, f"{nuclide}: no photon line near {energy} MeV"
        y = max(p["yield"] for p in near)
        assert ylo <= y <= yhi, f"{nuclide}: line {energy} MeV yield {y} not in [{ylo},{yhi}]"


def test_na22_annihilation_is_per_photon_convention():
    """ICRP annihilation yield is per *photon* (~2× the β⁺ branch), not per positron.

    Na-22 has a ~90.3 % β⁺ branch ⇒ ~1.81 annihilation photons/decay. If this were
    per-positron (~0.90) every positron-emitter's photon dose would be 2× low.
    """
    ann = [p for p in em.photons("Na-22") if p["origin"] == "annihilation"]
    total = sum(p["yield"] for p in ann)
    assert 1.7 <= total <= 1.85, f"Na-22 annihilation photon yield {total} (expected ~1.81)"
