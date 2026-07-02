"""Build canonical fluence-to-dose conversion files from the vendored OpenMC tables.

Source  : data/vendor/openmc_dose/icrp116_{photons,neutrons}.txt   (ICRP-116 effective dose
          per fluence, per geometry — verbatim from OpenMC, MIT) and
          data/vendor/openmc_dose/icrp74_{photons,neutrons}_H10.txt (ICRP-74/ICRU-57 ambient
          dose equivalent H*(10) per fluence — from OpenMC PR #3256, unmerged).
Output  : data/conversion/effective_<GEOM>.json (6, photon) +
          data/conversion/effective_neutron_<GEOM>.json (6, neutron) +
          data/conversion/hstar10.json (photon) + data/conversion/hstar10_neutron.json (neutron)

Design contract: HANDOFF_PLAN.md §6.4/§7, docs/plans/M2-conversion.md (photon),
docs/plans/M5-neutron.md (neutron). Dev-time step only; the browser/Pyodide runtime reads
the generated canonical files. The filename convention here MUST match
``engine.conversion._filename`` (photon: ``hstar10.json`` / ``effective_<GEOM>.json``;
neutron: ``hstar10_neutron.json`` / ``effective_neutron_<GEOM>.json``).

PROVENANCE — two trust levels (see data/vendor/openmc_dose/PROVENANCE.md):
- **effective** (ICRP-116, photon AND neutron): the vendored bytes ARE OpenMC's tree blob
  (git-blob-SHA match), so the tests re-parse them independently → canonical == upstream is
  proven.
- **ambient H*(10)** (ICRP-74, photon AND neutron): vendored from an *unmerged* PR (a
  transcription); the build still pins each sha256 so the source-of-record cannot drift
  silently, and the tests enforce faithfulness via independent cross-checks (photon: the
  OpenMC Ka/Φ → ICRU-57 sphere response anchored to IAEA; neutron: the M5 ISO-8529 averaged
  fluence-to-dose triangle).

All inputs are pinned by sha256; the build refuses to run on drift, and fails loud on any
structural surprise (bad row, non-ascending energy, wrong column count).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

SCHEMA_VERSION = 1
GEOMETRIES = ("AP", "PA", "LLAT", "RLAT", "ROT", "ISO")
UNITS = "pSv_cm2"

DATA_DIR = Path(__file__).resolve().parents[1]  # .../data
VENDOR_DIR = DATA_DIR / "vendor" / "openmc_dose"
OUT_DIR = DATA_DIR / "conversion"

# Per-particle vendored sources. Photon (M2) and neutron (M5) share the exact same table
# layout (effective = energy + 6 geometry columns; H*(10) = energy + 1 column), so the
# parsing/validation/writing is identical — only the inputs, the ``particle`` field, and the
# output filenames differ.
EFFECTIVE_SRC = {
    "photon": VENDOR_DIR / "icrp116_photons.txt",
    "neutron": VENDOR_DIR / "icrp116_neutrons.txt",
}
AMBIENT_SRC = {
    "photon": VENDOR_DIR / "icrp74_photons_H10.txt",
    "neutron": VENDOR_DIR / "icrp74_neutrons_H10.txt",
}

# Pinned sha256 of the vendored sources-of-record. Re-vendoring from a different file (or a
# corrupted download) must fail rather than silently rebuild. The effective files' identity
# to OpenMC's tree is additionally proven by their git-blob-SHA in the tests; the ambient
# files are the unmerged PR #3256 transcription (fork commit f89d146).
EXPECTED_SHA256 = {
    EFFECTIVE_SRC["photon"]: "2fa54b79a69c680477875f2aefb2afd047b13403071905bce9a7ac2ad21d9cb5",
    EFFECTIVE_SRC["neutron"]: "a8beffe41c5ce37346b483328d3e3ccc33c5c300fb10942657819e22f936a602",
    AMBIENT_SRC["photon"]: "d96077643b7355c947235b7f578c848c4271aacde17e3027242c7a64a3b2f6be",
    AMBIENT_SRC["neutron"]: "64ebd63517bb92fadb7351f284f58c044c41d912992a569a94c319549a639d36",
}

EFFECTIVE_SOURCE = {
    "photon": (
        "ICRP-116 (2010) Table A.1, effective dose per fluence (incl. corrigendum), "
        "monoenergetic photons; via OpenMC openmc/data/dose/icrp116/photons.txt (MIT)"
    ),
    "neutron": (
        "ICRP-116 (2010) Table A.5, effective dose per fluence, monoenergetic neutrons; "
        "via OpenMC openmc/data/dose/icrp116/neutrons.txt (MIT)"
    ),
}
AMBIENT_SOURCE = {
    "photon": (
        "ICRP-74 (1996)/ICRU-57 ambient dose equivalent H*(10) per fluence, monoenergetic "
        "photons; via OpenMC PR #3256 icrp74/photons_H10.txt (MIT, unmerged)"
    ),
    "neutron": (
        "ICRP-74 (1996) ambient dose equivalent H*(10) per fluence, monoenergetic neutrons; "
        "via OpenMC PR #3256 icrp74/neutrons_H10.txt (MIT, unmerged)"
    ),
}


class BuildError(Exception):
    """A structural / integrity failure in the conversion build. Never swallowed."""


def _effective_filename(particle: str, geometry: str) -> str:
    """Canonical effective-dose filename — must match ``engine.conversion._filename``."""
    return (
        f"effective_{geometry}.json"
        if particle == "photon"
        else f"effective_neutron_{geometry}.json"
    )


def _ambient_filename(particle: str) -> str:
    """Canonical H*(10) filename — must match ``engine.conversion._filename``."""
    return "hstar10.json" if particle == "photon" else "hstar10_neutron.json"


def verify_sha256() -> None:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file():
            raise BuildError(f"vendored source absent: {path}")
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != expected:
            raise BuildError(
                f"vendored {path.name} drifted from the pinned sha256\n"
                f"  expected {expected}\n  got      {got}\n"
                "If intentional, re-verify against upstream and update EXPECTED_SHA256."
            )


def _data_rows(path: Path, n_cols: int) -> list[list[float]]:
    """Parse whitespace-delimited numeric rows from a vendored OpenMC dose table.

    A data row is any line whose first whitespace token parses as a float; it must then
    yield exactly ``n_cols`` floats (energy + the dose columns). The 3 header lines
    (title, blank, column header) are skipped by the float-first test, not a fixed count.
    Handles both space- and tab-delimited rows and scientific notation (``1.0E-9``).
    """
    rows: list[list[float]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        toks = line.split()
        if not toks:
            continue
        try:
            float(toks[0])
        except ValueError:
            continue  # header / prose line
        if len(toks) != n_cols:
            raise BuildError(
                f"{path.name}:{lineno}: expected {n_cols} columns, got {len(toks)}: {toks}"
            )
        try:
            rows.append([float(t) for t in toks])
        except ValueError as exc:
            raise BuildError(f"{path.name}:{lineno}: non-numeric cell ({exc}): {toks}")
    if not rows:
        raise BuildError(f"{path.name}: no data rows parsed")
    return rows


def _validate_series(tag: str, e: list[float], coeff: list[float]) -> None:
    if len(e) != len(coeff):
        raise BuildError(f"{tag}: ragged arrays (E={len(e)}, coeff={len(coeff)})")
    if e != sorted(e):
        raise BuildError(f"{tag}: energies not ascending")
    if len(set(e)) != len(e):
        raise BuildError(f"{tag}: duplicate energies (no edges in conversion grids)")
    for ei, ci in zip(e, coeff):
        if not (math.isfinite(ei) and ei > 0):
            raise BuildError(f"{tag}: non-positive/non-finite energy {ei!r}")
        # Conversion coefficients are strictly positive (a dose per unit fluence). Lower
        # bound only — magnitudes span 0.006 pSv·cm² (E@10 keV PA) → ~1300 (neutron ISO @10 GeV).
        if not (math.isfinite(ci) and ci > 0):
            raise BuildError(f"{tag}: non-positive/non-finite coeff {ci!r} at {ei} MeV")


def _write(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_effective(particle: str) -> int:
    """Build the 6 effective-dose files for one particle (energy + 6 geometry columns)."""
    rows = _data_rows(EFFECTIVE_SRC[particle], n_cols=1 + len(GEOMETRIES))
    e = [r[0] for r in rows]
    count = 0
    for gi, geom in enumerate(GEOMETRIES, start=1):
        coeff = [r[gi] for r in rows]
        _validate_series(f"effective/{particle}/{geom}", e, coeff)
        _write(
            OUT_DIR / _effective_filename(particle, geom),
            {
                "schema_version": SCHEMA_VERSION,
                "quantity": "effective",
                "particle": particle,
                "geometry": geom,
                "units": UNITS,
                "source": EFFECTIVE_SOURCE[particle],
                "E_MeV": e,
                "coeff_pSv_cm2": coeff,
            },
        )
        count += 1
    return count


def _build_ambient(particle: str) -> int:
    """Build the single H*(10) file for one particle (energy + 1 column)."""
    rows = _data_rows(AMBIENT_SRC[particle], n_cols=2)
    e = [r[0] for r in rows]
    c = [r[1] for r in rows]
    _validate_series(f"ambient_H10/{particle}", e, c)
    _write(
        OUT_DIR / _ambient_filename(particle),
        {
            "schema_version": SCHEMA_VERSION,
            "quantity": "ambient_H10",
            "particle": particle,
            "geometry": None,
            "units": UNITS,
            "source": AMBIENT_SOURCE[particle],
            "E_MeV": e,
            "coeff_pSv_cm2": c,
        },
    )
    return 1


def build() -> int:
    verify_sha256()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for particle in ("photon", "neutron"):
        count += _build_effective(particle)
        count += _build_ambient(particle)
    return count


if __name__ == "__main__":
    try:
        n = build()
    except (BuildError, KeyError) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical conversion files into {OUT_DIR}")
