"""Build canonical per-material G-P buildup files from the vendored transcription.

Source  : data/vendor/ans643/NUREG-CR-5740.pdf  (public-domain ORNL/NRC report, the
          same data as ANSI/ANS-6.4.3-1991; see data/vendor/ans643/PROVENANCE.md) and
          data/vendor/ans643/gp_exposure_transcription.json (the hand-keyed,
          double-entered mirror of its appendix Table 5.1 exposure coefficients).
Output  : data/buildup/<material>.json   (this project's canonical schema)

Design contract: HANDOFF_PLAN.md §6.5/§7 and docs/plans/M2-buildup.md. Dev-time step
only; the browser/Pyodide runtime reads the generated canonical files.

DEGRADED PROVENANCE (vs attenuation/emissions): there is no clean machine-readable
ANS-6.4.3 source, so the "vendored bytes" are the **scanned PDF** and the transcription
is hand-keyed. This build therefore cannot re-derive canonical==upstream by an
independent parser; faithfulness is instead enforced by the validation suite
(tests/test_buildup_data.py: algebraic goldens, smoothness, EPJ cross-source, and the
within-source Table-3 reconstruction). We still pin the PDF hash so the transcription's
source of record cannot drift silently, and we fail loud on any structural surprise.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SOURCE = (
    "ANSI/ANS-6.4.3-1991 via NUREG/CR-5740 (Trubey 1991), "
    "G-P exposure (air-kerma) buildup factor coefficients, "
    "point isotropic source, infinite medium"
)
RESPONSE = "exposure"

DATA_DIR = Path(__file__).resolve().parents[1]               # .../data
VENDOR_DIR = DATA_DIR / "vendor" / "ans643"
PDF_PATH = VENDOR_DIR / "NUREG-CR-5740.pdf"
TRANSCRIPTION_PATH = VENDOR_DIR / "gp_exposure_transcription.json"
OUT_DIR = DATA_DIR / "buildup"

# Pinned hash of the vendored source-of-record PDF. Re-keying from a different scan
# (or a corrupted file) must fail rather than silently rebuild.
EXPECTED_PDF_SHA256 = (
    "96e102faee3b40c93f78b0ca9d190c6b10bf602b9f6a8cde01cfff8d9df68aa8"
)

# The ANS-6.4.3 source-energy span (15 keV – 15 MeV). Rows outside are not data.
E_MIN_MEV, E_MAX_MEV = 0.015, 15.0
_GP_KEYS = ("b", "c", "a", "Xk", "d")


class BuildError(Exception):
    """A structural / integrity failure in the buildup build. Never swallowed."""


def verify_pdf() -> None:
    if not PDF_PATH.is_file():
        raise BuildError(f"vendored source PDF absent: {PDF_PATH}")
    got = hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()
    if got != EXPECTED_PDF_SHA256:
        raise BuildError(
            "vendored NUREG/CR-5740 PDF drifted from the pinned hash\n"
            f"  expected {EXPECTED_PDF_SHA256}\n  got      {got}\n"
            "If intentional, re-verify the transcription against the new scan and "
            "update EXPECTED_PDF_SHA256 deliberately."
        )


def _validate(mid: str, rec: dict) -> None:
    e = rec["E_MeV"]
    cols = {k: rec[k] for k in _GP_KEYS}
    n = len(e)
    if n == 0:
        raise BuildError(f"{mid}: empty energy grid")
    for k, v in cols.items():
        if len(v) != n:
            raise BuildError(f"{mid}: column {k} has {len(v)} rows, expected {n}")
    if e != sorted(e):
        raise BuildError(f"{mid}: energies not ascending")
    if len(set(e)) != n:
        raise BuildError(f"{mid}: duplicate energies (buildup grid has no edges)")
    if not (E_MIN_MEV - 1e-9 <= e[0] and e[-1] <= E_MAX_MEV + 1e-9):
        raise BuildError(f"{mid}: energy out of ANS-6.4.3 span: {e[0]}..{e[-1]} MeV")
    for i, ei in enumerate(e):
        for k in _GP_KEYS:
            x = cols[k][i]
            if not isinstance(x, (int, float)) or not math.isfinite(x):
                raise BuildError(f"{mid}: non-finite {k} at {ei} MeV: {x!r}")
        if cols["Xk"][i] <= 0:
            raise BuildError(f"{mid}: non-positive Xk {cols['Xk'][i]} at {ei} MeV")
        # Loose sanity only: b ("buildup at 1 mfp") must stay in a generous physical
        # band. Deliberately NOT a tight "b >= 1": whether exposure b dips below 1 at
        # high energy is data, not an assumption (docs/plans/M2-buildup.md). A tight
        # bound would tempt silent "fixing" of a transcribed value.
        b = cols["b"][i]
        if not (0.0 < b < 12.0):
            raise BuildError(f"{mid}: implausible b {b} at {ei} MeV")


def build() -> int:
    verify_pdf()
    payload = json.loads(TRANSCRIPTION_PATH.read_text(encoding="utf-8"))
    materials = payload["materials"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for mid, rec in sorted(materials.items()):
        _validate(mid, rec)
        e = rec["E_MeV"]
        gp = [{k: rec[k][i] for k in _GP_KEYS} for i in range(len(e))]
        canonical = {
            "schema_version": SCHEMA_VERSION,
            "material": mid,
            "name": rec["name"],
            "response": RESPONSE,
            "source": SOURCE,
            "E_MeV": e,
            "gp": gp,
        }
        (OUT_DIR / f"{mid}.json").write_text(
            json.dumps(canonical, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        count += 1
    return count


if __name__ == "__main__":
    try:
        n = build()
    except (BuildError, KeyError) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical buildup files into {OUT_DIR}")
