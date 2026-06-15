"""Build canonical per-material attenuation files from the vendored NIST tables.

Source  : data/vendor/nist_xraymac/  (verbatim NIST Hubbell & Seltzer pages, SRD 126;
          see data/vendor/nist_xraymac/PROVENANCE.md)
Output  : data/attenuation/<material>.json   (this project's canonical schema)

Design contract: HANDOFF_PLAN.md §7 (data layer is the critical path) and the M2
attenuation dev-doc (docs/plans/M2-attenuation.md). Dev-time step only: the
browser/Pyodide runtime reads the generated canonical files, never the NIST HTML.

No silent errors (CLAUDE.md): a drifted vendored byte (vs the pinned manifest hash), a
material whose density is absent from the index tables, a row that is not a numeric
triple, μ_en/ρ exceeding μ/ρ, or an unexpected energy range each **raises** rather than
being dropped or back-filled. Floats are parsed straight from the NIST text tokens with
``float()`` (no rounding), so the transform-integrity test can compare canonical vs
upstream by exact equality.

This module's HTML parsing is regex-based **on purpose**: the validation suite re-parses
the same pages with the stdlib ``HTMLParser`` so the integrity check is independent of
this extractor (a bug here cannot hide behind itself).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SOURCE = (
    "NIST X-Ray Mass Attenuation Coefficients "
    "(Hubbell & Seltzer, NIST SRD 126 / NISTIR 5632)"
)

DATA_DIR = Path(__file__).resolve().parents[1]                 # .../data
VENDOR_DIR = DATA_DIR / "vendor" / "nist_xraymac"
MANIFEST_PATH = VENDOR_DIR / "MANIFEST.sha256"
OUT_DIR = DATA_DIR / "attenuation"

# Pinned combined hash of the vendored NIST pages (sha256 over the sorted
# "<sha256>  <relpath>" manifest lines). Regenerating from drifted bytes must fail.
EXPECTED_MANIFEST_SHA256 = (
    "ebb10026976a004110bafd7a7766598e7e0b3926b933b34253c5a11e29a8fd8a"
)

# Material registry: id -> spec. Elements look up density by Z in tab1; compounds by
# their EXACT NIST display name in tab2. The id is this project's stable slug.
ELEMENTS = {  # id -> (Z, page)
    "lead": (82, "elem/z82.html"),
    "tungsten": (74, "elem/z74.html"),
    "iron": (26, "elem/z26.html"),
    "copper": (29, "elem/z29.html"),
    "aluminium": (13, "elem/z13.html"),
}
COMPOUNDS = {  # id -> (exact tab2 name, page)
    "water": ("Water, Liquid", "comp/water.html"),
    "air": ("Air, Dry (near sea level)", "comp/air.html"),
    "tissue_soft": ("Tissue, Soft (ICRU-44)", "comp/tissue.html"),
    "concrete": ("Concrete, Ordinary", "comp/concrete.html"),
    "pmma": ("Polymethyl Methacrylate", "comp/pmma.html"),
    "polyethylene": ("Polyethylene", "comp/polyethylene.html"),
}

# NIST tabulation spans 1 keV – 20 MeV; rows outside this are not data rows.
E_MIN_MEV, E_MAX_MEV = 1e-3, 20.0

_TR = re.compile(r"<TR[^>]*>(.*?)</TR>", re.S | re.I)
_TD = re.compile(r"<T[DH][^>]*>(.*?)</T[DH]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


class BuildError(Exception):
    """A structural / integrity failure in the data build. Never swallowed."""


def verify_vendor_manifest() -> None:
    """Recompute the vendored-bytes hash and refuse to build on any drift."""
    files = sorted(p.relative_to(VENDOR_DIR).as_posix()
                   for p in VENDOR_DIR.rglob("*.html"))
    if not files:
        raise BuildError(f"no vendored NIST pages under {VENDOR_DIR}")
    lines = [f"{hashlib.sha256((VENDOR_DIR / rel).read_bytes()).hexdigest()}  {rel}"
             for rel in files]
    manifest = "\n".join(lines)
    combined = hashlib.sha256(manifest.encode()).hexdigest()
    if combined != EXPECTED_MANIFEST_SHA256:
        raise BuildError(
            "vendored NIST bytes drifted from the pinned manifest hash\n"
            f"  expected {EXPECTED_MANIFEST_SHA256}\n  got      {combined}\n"
            "If this change is intentional, re-fetch, update EXPECTED_MANIFEST_SHA256 "
            "and MANIFEST.sha256 deliberately, and re-run the validation suite."
        )
    MANIFEST_PATH.write_text(manifest + "\n", encoding="utf-8")


def _cells(tr: str) -> list[str]:
    return [html.unescape(_TAG.sub("", c)).strip() for c in _TD.findall(tr)]


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_material_page(relpath: str) -> list[tuple[str | None, float, float, float]]:
    """Extract (edge_label|None, E_MeV, μ/ρ, μ_en/ρ) rows from a NIST page.

    A data row's **last three** cells are floats with the first in [1 keV, 20 MeV];
    an optional non-empty cell before them is the absorption-edge label.
    """
    body = (VENDOR_DIR / relpath).read_text(encoding="utf-8")
    rows: list[tuple[str | None, float, float, float]] = []
    for tr in _TR.findall(body):
        cells = _cells(tr)
        if len(cells) < 3:
            continue
        tail = cells[-3:]
        if not all(_is_float(c) for c in tail):
            continue
        e, mu, muen = (float(c) for c in tail)
        if not (E_MIN_MEV <= e <= E_MAX_MEV):
            continue
        if mu <= 0 or muen <= 0:
            raise BuildError(f"{relpath}: non-positive coefficient at {e} MeV")
        if muen > mu * (1 + 1e-9):
            raise BuildError(
                f"{relpath}: μ_en/ρ {muen} > μ/ρ {mu} at {e} MeV "
                "(columns swapped or mis-parsed?)"
            )
        label = next((c for c in cells[:-3] if c), None)
        if label is not None:
            # Edge labels are metadata, not physics: NIST writes element edges as a
            # bare shell ("K", "L1") and compound edges as "<Z> <shell>" (e.g. "18 K"
            # = argon K-edge in air), with inconsistent spaces/&nbsp;. Collapse runs of
            # whitespace to a single ASCII space so the marker is tidy and stable. The
            # numeric coefficients are never touched (exact-float faithfulness).
            label = re.sub(r"\s+", " ", label)
        rows.append((label, e, mu, muen))
    if not rows:
        raise BuildError(f"{relpath}: no data rows parsed")
    energies = [e for _l, e, _m, _me in rows]
    if energies != sorted(energies):
        raise BuildError(f"{relpath}: energies are not ascending as tabulated")
    return rows


def parse_density_index() -> tuple[dict[int, tuple[str, float]], dict[str, float]]:
    """(elements {Z: (name, ρ)}, compounds {name: ρ}) from tab1 / tab2."""
    elem: dict[int, tuple[str, float]] = {}
    for tr in _TR.findall((VENDOR_DIR / "tab1.html").read_text(encoding="utf-8")):
        cells = _cells(tr)  # [Z, Sym, Name, Z/A, I, density]
        if len(cells) >= 6 and cells[0].isdigit() and _is_float(cells[-1]):
            elem[int(cells[0])] = (cells[2], float(cells[-1]))
    comp: dict[str, float] = {}
    for tr in _TR.findall((VENDOR_DIR / "tab2.html").read_text(encoding="utf-8")):
        cells = _cells(tr)  # [Name, Z/A, I, density, ...composition]
        if len(cells) >= 4 and cells[0] and _is_float(cells[3]):
            comp[cells[0]] = float(cells[3])
    if not elem or not comp:
        raise BuildError("density index tables parsed empty (tab1/tab2)")
    return elem, comp


def build() -> int:
    verify_vendor_manifest()
    elem_rho, comp_rho = parse_density_index()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    for mid, (z, page) in sorted(ELEMENTS.items()):
        if z not in elem_rho:
            raise BuildError(f"{mid}: Z={z} absent from tab1 density index")
        name, rho = elem_rho[z]
        rows = parse_material_page(page)
        _write(mid, name, "element", rho, rows, extra={"Z": z})
        count += 1

    for mid, (nist_name, page) in sorted(COMPOUNDS.items()):
        if nist_name not in comp_rho:
            raise BuildError(f"{mid}: {nist_name!r} absent from tab2 density index")
        rho = comp_rho[nist_name]
        rows = parse_material_page(page)
        _write(mid, nist_name, "compound", rho, rows, extra={})
        count += 1

    return count


def _write(mid, name, kind, rho, rows, *, extra) -> None:
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "material": mid,
        "name": name,
        "kind": kind,
        **extra,
        "rho_g_cm3": rho,
        "source": SOURCE,
        "E_MeV": [e for _l, e, _m, _me in rows],
        "mu_rho_cm2_g": [m for _l, _e, m, _me in rows],
        "muen_rho_cm2_g": [me for _l, _e, _m, me in rows],
        "edges": [{"label": lab, "E_MeV": e}
                  for lab, e, _m, _me in rows if lab is not None],
    }
    out = OUT_DIR / f"{mid}.json"
    out.write_text(
        json.dumps(canonical, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        n = build()
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical attenuation files into {OUT_DIR}")
