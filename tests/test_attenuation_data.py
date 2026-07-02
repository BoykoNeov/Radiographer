"""Regression suite for the bundled NIST mass attenuation data (HANDOFF_PLAN.md §7).

The datasets are the project (CLAUDE.md), so each table is validated the moment it
lands. Four independent pillars, mirroring the emissions suite:

1. **Structural** — schema, array alignment, physical sanity, and the free invariant
   ``μ_en/ρ ≤ μ/ρ`` on *every* row (the cheapest catch for a swapped-column parse).
2. **Transform integrity** — canonical == vendored, re-parsed from the raw NIST HTML by
   an *independent* method (stdlib ``HTMLParser``, not the build's regex), incl. the
   density re-derived independently from the ``tab1``/``tab2`` index pages. A drop, dup,
   mis-row, value-mangle, or wrong-density would break the multiset equality.
3. **Coverage** — every required dose medium and shield has a file; both directions.
4. **Physics goldens** — μ/ρ, μ_en/ρ and a *narrow-beam* HVL checked against
   independent published values (textbook-rounded), hardcoded with windows; plus the
   Pb K-edge. Narrow-beam on purpose: μ alone gives ln2/μ; published *broad-beam*
   HVL/TVL include buildup (~10–15 % larger) and belong to M3, where buildup exists.

Trust boundary (honesty, like emissions): NIST XCOM and Hubbell & Seltzer share the
Berger/Hubbell cross-section lineage, so these goldens catch transcription / unit /
column / edge errors — *not* an independent re-evaluation of the underlying physics
(there is no independent modern source; H&S is the field standard).
"""

from __future__ import annotations

import math
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from engine import attenuation as at

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "data" / "vendor" / "nist_xraymac"
CANON = ROOT / "data" / "attenuation"

# Independent material registry (intentionally a restatement, not imported from the
# build): id -> (kind, vendor relpath, density key). Element density is keyed by Z in
# tab1; compound density by the EXACT NIST material name in tab2.
ELEMENTS = {  # id -> (Z, vendor page)
    "lead": (82, "elem/z82.html"),
    "tungsten": (74, "elem/z74.html"),
    "iron": (26, "elem/z26.html"),
    "copper": (29, "elem/z29.html"),
    "aluminium": (13, "elem/z13.html"),
}
COMPOUNDS = {  # id -> (exact tab2 name, vendor page)
    "water": ("Water, Liquid", "comp/water.html"),
    "air": ("Air, Dry (near sea level)", "comp/air.html"),
    "tissue_soft": ("Tissue, Soft (ICRU-44)", "comp/tissue.html"),
    "concrete": ("Concrete, Ordinary", "comp/concrete.html"),
    "pmma": ("Polymethyl Methacrylate", "comp/pmma.html"),
    "polyethylene": ("Polyethylene", "comp/polyethylene.html"),
}
# NIST standard photon energy grid (MeV), 1 keV – 20 MeV — the 36 base points every
# material is tabulated at (high-Z pages add extra near-edge mesh on top of these). Used
# to assert *completeness*: the integrity test proves canonical == vendored, but cannot
# see a row both parsers' shared row-filter would drop, so this anchors against the grid.
NIST_STD_E = [
    1.0e-3,
    1.5e-3,
    2.0e-3,
    3.0e-3,
    4.0e-3,
    5.0e-3,
    6.0e-3,
    8.0e-3,
    1.0e-2,
    1.5e-2,
    2.0e-2,
    3.0e-2,
    4.0e-2,
    5.0e-2,
    6.0e-2,
    8.0e-2,
    1.0e-1,
    1.5e-1,
    2.0e-1,
    3.0e-1,
    4.0e-1,
    5.0e-1,
    6.0e-1,
    8.0e-1,
    1.0,
    1.25,
    1.5,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    8.0,
    10.0,
    15.0,
    20.0,
]

DOSE_MEDIA = {"air", "water", "tissue_soft"}
SHIELDS = {"lead", "tungsten", "iron", "copper", "aluminium", "concrete", "pmma", "polyethylene"}
REQUIRED = set(ELEMENTS) | set(COMPOUNDS)

ALL = sorted(p.stem for p in CANON.glob("*.json"))


# --------------------------------------------------------------------------- #
# Independent HTML parsing (stdlib HTMLParser) — NOT the build's regex path.
# --------------------------------------------------------------------------- #


class _TableParser(HTMLParser):
    """Collect every <tr> as a list of stripped <td> texts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _independent_rows(relpath: str) -> list[tuple[str | None, float, float, float]]:
    """(edge_label|None, E_MeV, mu/rho, muen/rho) for each data row of a NIST page.

    A data row is one whose **last three** cells are floats with the first of those in
    the NIST tabulation range [1e-3, 20] MeV; an optional non-empty cell before them is
    the absorption-edge label. This mirrors the table's physical shape but is derived
    here without any reference to the build's parser.
    """
    p = _TableParser()
    p.feed((VENDOR / relpath).read_text(encoding="utf-8"))
    out = []
    for cells in p.rows:
        if len(cells) < 3:
            continue
        tail = cells[-3:]
        if not all(_is_float(c) for c in tail):
            continue
        e, mu, muen = (float(c) for c in tail)
        if not (1e-3 <= e <= 20.0):
            continue
        label = None
        lead = cells[:-3]
        for c in lead:
            if c:  # first non-empty cell before the numeric triple is the edge label
                label = re.sub(r"\s+", " ", c)  # normalise nbsp/spaces, as the build does
                break
        out.append((label, e, mu, muen))
    return out


def _independent_density(material: str) -> float:
    """Re-derive density from tab1 (elements, by Z) / tab2 (compounds, by exact name)."""
    if material in ELEMENTS:
        z, _ = ELEMENTS[material]
        p = _TableParser()
        p.feed((VENDOR / "tab1.html").read_text(encoding="utf-8"))
        for cells in p.rows:
            # tab1 row: [Z, Sym, Name, Z/A, I, density]
            if len(cells) >= 6 and cells[0].strip() == str(z) and _is_float(cells[-1]):
                return float(cells[-1])
        raise AssertionError(f"density for Z={z} not found in tab1")
    name, _ = COMPOUNDS[material]
    p = _TableParser()
    p.feed((VENDOR / "tab2.html").read_text(encoding="utf-8"))
    for cells in p.rows:
        # tab2 row: [Name, Z/A, I, density, ...composition]
        if cells and cells[0].strip() == name and len(cells) >= 4 and _is_float(cells[3]):
            return float(cells[3])
    raise AssertionError(f"density for {name!r} not found in tab2")


# --------------------------------------------------------------------------- #
# 0. The dataset exists (fail-first sentinel before the build has run).
# --------------------------------------------------------------------------- #


def test_dataset_is_present_and_complete():
    have = set(ALL)
    missing = sorted(REQUIRED - have)
    assert not missing, (
        f"missing attenuation files {missing}; run `python data/build/build_attenuation.py`"
    )


# --------------------------------------------------------------------------- #
# 1. Structural / schema / physical sanity.
# --------------------------------------------------------------------------- #


def test_schema_and_physical_sanity():
    for m in REQUIRED:
        data = at.load_attenuation(m)  # validates version/name/alignment/rho
        e = data["E_MeV"]
        mu = data["mu_rho_cm2_g"]
        muen = data["muen_rho_cm2_g"]
        assert e == sorted(e), f"{m}: energies not non-decreasing"
        assert 1e-3 - 1e-12 <= e[0] and e[-1] <= 20.0 + 1e-9, f"{m}: energy out of range"
        for ei, mi, mei in zip(e, mu, muen):
            assert math.isfinite(ei) and ei > 0
            assert math.isfinite(mi) and mi > 0
            assert math.isfinite(mei) and mei > 0
            # Free physical invariant: you cannot absorb more energy than you attenuate.
            # This is the cheapest catch for a swapped μ/ρ ↔ μ_en/ρ parse.
            assert mei <= mi * (1 + 1e-9), f"{m}: μ_en/ρ {mei} > μ/ρ {mi} at {ei} MeV"
        # Edge markers: valid label, energy present as a duplicate in the grid.
        for edge in data.get("edges", []):
            assert edge["label"] and isinstance(edge["label"], str)
            assert e.count(edge["E_MeV"]) >= 2, (
                f"{m}: edge {edge['label']} at {edge['E_MeV']} is not a duplicated energy"
            )
        # Elements carry Z; compounds do not.
        if m in ELEMENTS:
            assert data.get("Z") == ELEMENTS[m][0]
        else:
            assert "Z" not in data


def test_loader_raises_on_missing_material():
    with pytest.raises(at.AttenuationError):
        at.load_attenuation("unobtainium")


# --------------------------------------------------------------------------- #
# 2. Transform integrity — independent of the build's parser.
# --------------------------------------------------------------------------- #


def test_canonical_rows_match_independent_parse():
    """No row dropped, duplicated, mis-ordered, or value-mangled vs the raw HTML."""
    for m in REQUIRED:
        _, page = ELEMENTS[m] if m in ELEMENTS else COMPOUNDS[m]
        indep = sorted((e, mu, muen) for (_lab, e, mu, muen) in _independent_rows(page))
        data = at.load_attenuation(m)
        canon = sorted(zip(data["E_MeV"], data["mu_rho_cm2_g"], data["muen_rho_cm2_g"]))
        assert canon == indep, f"{m}: canonical rows differ from independent HTML parse"


def test_density_matches_independent_index():
    for m in REQUIRED:
        assert at.density(m) == _independent_density(m), f"{m}: density mismatch"


def test_edges_match_independent_parse():
    for m in REQUIRED:
        _, page = ELEMENTS[m] if m in ELEMENTS else COMPOUNDS[m]
        indep = sorted(
            (lab, e) for (lab, e, _mu, _muen) in _independent_rows(page) if lab is not None
        )
        canon = sorted((edge["label"], edge["E_MeV"]) for edge in at.edges(m))
        assert canon == indep, f"{m}: edge markers differ from independent parse"


# --------------------------------------------------------------------------- #
# 3. Coverage — dose media + shields, both directions.
# --------------------------------------------------------------------------- #


def test_required_coverage_both_directions():
    have = set(ALL)
    assert DOSE_MEDIA <= have, f"missing dose media: {sorted(DOSE_MEDIA - have)}"
    assert SHIELDS <= have, f"missing shields: {sorted(SHIELDS - have)}"
    # No stray files outside the declared registry.
    assert have <= REQUIRED, f"unexpected attenuation files: {sorted(have - REQUIRED)}"


def test_full_energy_grid_present():
    """No base-grid row silently dropped (the integrity test can't see this).

    `water` is edge-free, so its grid *is* the base grid — anchoring the literal to it
    externally catches a *systematic* drop a water-derived grid would hide. Then every
    material must contain the full base grid. ``float("1.00000E-03") == 1.0e-3`` exactly,
    so set membership needs no tolerance.
    """
    assert sorted(set(at.energies("water"))) == NIST_STD_E, "water grid != NIST base grid"
    base = set(NIST_STD_E)
    for m in REQUIRED:
        missing = sorted(base - set(at.energies(m)))
        assert not missing, f"{m}: missing base-grid energies {missing}"


# --------------------------------------------------------------------------- #
# 4. Physics goldens — independent published values (textbook-rounded), hardcoded.
# --------------------------------------------------------------------------- #


def _row_at(material: str, energy: float, tol_frac: float = 0.01) -> tuple[float, float]:
    """Return (μ/ρ, μ_en/ρ) at the unique non-edge grid point near `energy`."""
    e = at.energies(material)
    mu = at.mu_rho(material)
    muen = at.muen_rho(material)
    hits = [(mu[i], muen[i]) for i, ei in enumerate(e) if abs(ei - energy) <= tol_frac * energy]
    assert len(hits) == 1, f"{material}: expected one grid row near {energy} MeV, got {len(hits)}"
    return hits[0]


def test_golden_water_coefficients():
    # Water @ 1.25 MeV (Co-60 mean): μ/ρ ≈ 0.0632, μ_en/ρ ≈ 0.0297 cm²/g.
    mu, muen = _row_at("water", 1.25)
    assert 0.061 <= mu <= 0.066, mu
    assert 0.0287 <= muen <= 0.0306, muen
    # Water @ 0.1 MeV: μ/ρ ≈ 0.1707, μ_en/ρ ≈ 0.0255 cm²/g.
    mu, muen = _row_at("water", 0.1)
    assert 0.165 <= mu <= 0.176, mu
    assert 0.0247 <= muen <= 0.0263, muen


def test_golden_air_energy_absorption():
    # Air @ 1.25 MeV: μ_en/ρ ≈ 0.0267 cm²/g.
    _mu, muen = _row_at("air", 1.25)
    assert 0.0258 <= muen <= 0.0277, muen


def test_golden_lead_narrow_beam_hvl():
    # Lead @ 1.25 MeV: μ/ρ ≈ 0.0588 cm²/g, ρ = 11.35 → narrow-beam HVL = ln2/μ ≈ 1.04 cm.
    mu, _muen = _row_at("lead", 1.25)
    rho = at.density("lead")
    hvl_cm = math.log(2) / (mu * rho)
    assert 0.95 <= hvl_cm <= 1.15, f"Pb narrow-beam HVL {hvl_cm:.3f} cm @1.25 MeV"


def test_golden_high_z_attenuates_more():
    # At 0.1 MeV photoelectric dominates → lead ≫ aluminium in μ/ρ.
    mu_pb, _ = _row_at("lead", 0.1)
    mu_al, _ = _row_at("aluminium", 0.1)
    assert mu_pb > 10 * mu_al, f"Pb μ/ρ {mu_pb} not ≫ Al μ/ρ {mu_al} at 0.1 MeV"


def test_golden_densities():
    # Density feeds M3 shielding as μ = (μ/ρ)·ρ; only lead's ρ is otherwise anchored
    # (via the HVL golden). Anchor the rest externally so a mis-keyed tab lookup can't
    # silently corrupt a shield. Values: standard handbook densities (g/cm³).
    expect = {
        "aluminium": 2.699,
        "iron": 7.874,
        "copper": 8.96,
        "tungsten": 19.30,
        "concrete": 2.30,
        "air": 1.205e-3,
    }
    for m, rho in expect.items():
        assert abs(at.density(m) - rho) / rho < 0.01, (m, at.density(m))


def test_golden_lead_k_edge():
    # Pb K-edge ≈ 88.0 keV; μ/ρ steps UP across it (photoelectric onset).
    edges = at.edges("lead")
    k = [edge for edge in edges if edge["label"] == "K"]
    assert k, "lead has no K edge"
    e_k = k[0]["E_MeV"]
    assert abs(e_k - 0.0880) < 1e-3, f"Pb K-edge at {e_k} MeV (expected ~0.088)"
    e = at.energies("lead")
    mu = at.mu_rho("lead")
    idx = [i for i, ei in enumerate(e) if ei == e_k]
    assert len(idx) == 2, "K-edge energy should appear twice (below/above)"
    assert mu[idx[1]] > mu[idx[0]], "μ/ρ should jump up across the K edge"
