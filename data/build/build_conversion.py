"""Build canonical fluence-to-dose conversion files from the vendored OpenMC tables.

Source  : data/vendor/openmc_dose/icrp116_photons.txt   (ICRP-116 effective dose per
          fluence, per geometry — verbatim from OpenMC, MIT) and
          data/vendor/openmc_dose/icrp74_photons_H10.txt (ICRP-74/ICRU-57 ambient dose
          equivalent H*(10) per fluence — from OpenMC PR #3256, unmerged).
Output  : data/conversion/effective_<GEOM>.json (6) + data/conversion/hstar10.json (1)

Design contract: HANDOFF_PLAN.md §6.4/§7 and docs/plans/M2-conversion.md. Dev-time step
only; the browser/Pyodide runtime reads the generated canonical files.

PROVENANCE — two trust levels (see data/vendor/openmc_dose/PROVENANCE.md):
- **effective** (ICRP-116): the vendored bytes ARE OpenMC's tree blob (git-blob-SHA match),
  so the tests re-parse them independently → canonical == upstream is proven.
- **ambient H*(10)** (ICRP-74): vendored from an *unmerged* PR (a transcription); the
  build still pins its sha256 so the source-of-record cannot drift silently, and the
  tests enforce faithfulness via an independent-quantity cross-check (OpenMC Ka/Φ → the
  canonical ICRU-57 sphere response) anchored to the IAEA slab table.

Both inputs are pinned by sha256; the build refuses to run on drift, and fails loud on
any structural surprise (bad row, non-ascending energy, wrong column count).
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
PARTICLE = "photon"

DATA_DIR = Path(__file__).resolve().parents[1]              # .../data
VENDOR_DIR = DATA_DIR / "vendor" / "openmc_dose"
EFFECTIVE_SRC = VENDOR_DIR / "icrp116_photons.txt"
AMBIENT_SRC = VENDOR_DIR / "icrp74_photons_H10.txt"
OUT_DIR = DATA_DIR / "conversion"

# Pinned sha256 of the vendored sources-of-record. Re-vendoring from a different file
# (or a corrupted download) must fail rather than silently rebuild. The effective file's
# identity to OpenMC's tree is additionally proven by its git-blob-SHA (e2591d85…) in the
# tests; the ambient file is the unmerged PR #3256 transcription (fork commit f89d146).
EXPECTED_SHA256 = {
    EFFECTIVE_SRC: "2fa54b79a69c680477875f2aefb2afd047b13403071905bce9a7ac2ad21d9cb5",
    AMBIENT_SRC: "d96077643b7355c947235b7f578c848c4271aacde17e3027242c7a64a3b2f6be",
}

EFFECTIVE_SOURCE = (
    "ICRP-116 (2010) Table A.1, effective dose per fluence (incl. corrigendum), "
    "monoenergetic photons; via OpenMC openmc/data/dose/icrp116/photons.txt (MIT)"
)
AMBIENT_SOURCE = (
    "ICRP-74 (1996)/ICRU-57 ambient dose equivalent H*(10) per fluence, monoenergetic "
    "photons; via OpenMC PR #3256 icrp74/photons_H10.txt (MIT, unmerged)"
)


class BuildError(Exception):
    """A structural / integrity failure in the conversion build. Never swallowed."""


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
        # bound only — magnitudes span 0.006 pSv·cm² (E@10 keV PA) → 276 (E@10 GeV ISO).
        if not (math.isfinite(ci) and ci > 0):
            raise BuildError(f"{tag}: non-positive/non-finite coeff {ci!r} at {ei} MeV")


def _write(path: Path, record: dict) -> None:
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build() -> int:
    verify_sha256()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    # --- effective dose (ICRP-116): energy + 6 geometry columns -------------------
    eff_rows = _data_rows(EFFECTIVE_SRC, n_cols=1 + len(GEOMETRIES))
    e_eff = [r[0] for r in eff_rows]
    for gi, geom in enumerate(GEOMETRIES, start=1):
        coeff = [r[gi] for r in eff_rows]
        _validate_series(f"effective/{geom}", e_eff, coeff)
        _write(
            OUT_DIR / f"effective_{geom}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "quantity": "effective",
                "particle": PARTICLE,
                "geometry": geom,
                "units": UNITS,
                "source": EFFECTIVE_SOURCE,
                "E_MeV": e_eff,
                "coeff_pSv_cm2": coeff,
            },
        )
        count += 1

    # --- ambient dose equivalent H*(10) (ICRP-74): energy + 1 column --------------
    amb_rows = _data_rows(AMBIENT_SRC, n_cols=2)
    e_amb = [r[0] for r in amb_rows]
    c_amb = [r[1] for r in amb_rows]
    _validate_series("ambient_H10", e_amb, c_amb)
    _write(
        OUT_DIR / "hstar10.json",
        {
            "schema_version": SCHEMA_VERSION,
            "quantity": "ambient_H10",
            "particle": PARTICLE,
            "geometry": None,
            "units": UNITS,
            "source": AMBIENT_SOURCE,
            "E_MeV": e_amb,
            "coeff_pSv_cm2": c_amb,
        },
    )
    count += 1
    return count


if __name__ == "__main__":
    try:
        n = build()
    except (BuildError, KeyError) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical conversion files into {OUT_DIR}")
