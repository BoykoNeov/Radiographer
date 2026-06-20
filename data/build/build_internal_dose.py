"""Build canonical internal (committed) dose-coefficient files from ICRP-119.

Source  : data/vendor/icrp119/icrp119.pdf  (ICRP Publication 119, Compendium of Dose
          Coefficients based on ICRP Publication 60; free from icrp.org). Committed
          effective dose coefficients e(50), Sv/Bq, read VISUALLY from the rendered table
          pages (``pdftotext -layout`` scrambles these grids — the M12 lesson; see
          data/vendor/icrp119/PROVENANCE.md).
            - Worker (ICRP-68): Annex A, Table A.1 — ingestion + inhalation, 5 µm AMAD
              (occupational default), types F/M/S.
            - Public adult (ICRP-72): Annex F (ingestion) + Annex G (inhalation, 1 µm AMAD),
              "Adult" column, types F/M/S.
Output  : data/internal_dose/worker.json + data/internal_dose/public_adult.json

Design contract: HANDOFF_PLAN.md §2/§11 (internal dose = Future), docs/plans/M13-internal-dose.md.
Dev-time step only; the browser/Pyodide runtime reads the generated canonical files. The
schema + filenames MUST match ``engine.internal_dose``.

PROVENANCE / VALIDATION — these coefficients are HAND-TRANSCRIBED from a PDF, so the §12
transcription trap is the dominant risk. Two independent cross-checks are enforced here at
build time (a value that fails refuses to build), exploiting that ICRP-119 typesets the SAME
numbers twice in independent annexes:

  (1) **Ingestion f1-ratio check.** For a nuclide whose worker and public-adult ingestion use
      the SAME biokinetics, e_public / e_worker == f1_public / f1_worker (intestinal absorption
      scales the swallowed coefficient). Po-210 (worker f1 0.1 → public f1 0.5) reconciles to
      EXACTLY 5×; matched-f1 actinides reconcile to ~1×.
  (2) **Inhalation worker-1µm ↔ public-adult-1µm check** (documented in PROVENANCE, applied to
      the default type): Annex A also lists the worker 1 µm value, which must agree with the
      Annex G public-adult 1 µm value to ~20 % (same lung model, ~same reference person). This
      check CAUGHT a first-pass misread of Am-241 (M adult read as 9.6E-05 — actually the
      F-row value; corrected to 4.2E-05 via a 300-DPI crop).

The coverage is a CURATED slice (not all ~800 ICRP-119 nuclides); a tracked nuclide absent
here makes a committed-dose estimate a LOWER BOUND, surfaced loudly by the engine (§11).
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1
UNITS = "Sv_per_Bq"
PROGENY_CONVENTION = "parent_only_in_vivo_ingrowth"  # NOT the "+"-bundled equilibrium entries

DATA_DIR = Path(__file__).resolve().parents[1]  # .../data
OUT_DIR = DATA_DIR / "internal_dose"

# Source-of-record: e(50) in Sv/Bq read from ICRP-119 (PDF pages are printed-page + 2).
# Each inhalation entry ships ALL tabulated F/M/S types + a default_type (ICRP-recommended
# absorption type for unspecified chemical form — Type M for these actinide oxides/hydroxides;
# also the commonly-cited value). Ingestion ships e + the f1 used.

# WORKER — ICRP-68, Annex A / Table A.1, 5 µm AMAD inhalation (occupational default).
WORKER = {
    "population": "worker",
    "icrp_publication": "ICRP-68 (via ICRP-119 Annex A, Table A.1)",
    "age": "adult",
    "amad_um": 5.0,
    "coefficients": {
        # Po-210  (printed p.52): ingestion f1 0.1; inhalation 5µm F/M
        "Po-210": {"ingestion": {"e_Sv_Bq": 2.4e-07, "f1": 0.1},
                   "inhalation": {"default_type": "M", "types": {"F": 7.1e-07, "M": 2.2e-06}}},
        # Ra-226  (printed p.53): ingestion f1 0.2; inhalation 5µm M only
        "Ra-226": {"ingestion": {"e_Sv_Bq": 2.8e-07, "f1": 0.2},
                   "inhalation": {"default_type": "M", "types": {"M": 2.2e-06}}},
        # U-238   (printed p.54): ingestion f1 0.02; inhalation 5µm F/M/S
        "U-238": {"ingestion": {"e_Sv_Bq": 4.4e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.8e-07, "M": 1.6e-06, "S": 6.3e-06}}},
        # Pu-239  (printed p.55): ingestion f1 0.0005; inhalation 5µm M/S
        "Pu-239": {"ingestion": {"e_Sv_Bq": 2.5e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 3.2e-05, "S": 8.3e-06}}},
        # Am-241  (printed p.56): ingestion f1 0.0005; inhalation 5µm M only
        "Am-241": {"ingestion": {"e_Sv_Bq": 2.0e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 2.7e-05}}},
    },
}

# PUBLIC ADULT — ICRP-72, Annex F (ingestion) + Annex G (inhalation, 1 µm AMAD), Adult column.
PUBLIC_ADULT = {
    "population": "public_adult",
    "icrp_publication": "ICRP-72 (via ICRP-119 Annexes F & G)",
    "age": "adult",
    "amad_um": 1.0,
    # PUBLIC inhalation ships ONLY absorption types cross-validated against the worker 1 µm
    # column (_WORKER_1UM below). Types with no worker counterpart — and the suspect Pu-239 F
    # (read 1.6E-05, == its own S value, breaking 15y→adult monotonicity: a mis-column, advisor)
    # — are DROPPED here, to be re-read via 300-DPI crops in the later UI absorption-type batch.
    "coefficients": {
        # Po-210  (Annex F printed p.84 / Annex G printed p.114): ingestion f1 0.5
        "Po-210": {"ingestion": {"e_Sv_Bq": 1.2e-06, "f1": 0.5},
                   "inhalation": {"default_type": "M",
                                  "types": {"F": 6.0e-07, "M": 3.3e-06}}},   # dropped S (no worker S)
        "Ra-226": {"ingestion": {"e_Sv_Bq": 2.8e-07, "f1": 0.2},
                   "inhalation": {"default_type": "M",
                                  "types": {"M": 3.5e-06}}},                 # dropped F,S (no worker F,S)
        "U-238": {"ingestion": {"e_Sv_Bq": 4.5e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.0e-07, "M": 2.9e-06, "S": 8.0e-06}}},
        "Pu-239": {"ingestion": {"e_Sv_Bq": 2.5e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M",
                                  "types": {"M": 5.0e-05, "S": 1.6e-05}}},   # dropped suspect F
        # Am-241: M adult = 4.2E-05 (corrected from a first-pass misread of 9.6E-05 = the F row)
        "Am-241": {"ingestion": {"e_Sv_Bq": 2.0e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M",
                                  "types": {"M": 4.2e-05}}},                 # dropped F,S (no worker F,S)
    },
}

# Worker 1 µm inhalation per type (Annex A, read from the same 300-DPI crops as the shipped
# 5 µm worker values) — for the cross-annex consistency check ONLY; NOT shipped (worker ships
# 5 µm). EVERY public-adult inhalation type must match its worker 1 µm counterpart (same HRTM
# lung model, ~same reference person) — this auto-flags a mis-column on ANY type, not just the
# default. A public type with no worker counterpart here is REFUSED (must be dropped or crop-read).
_WORKER_1UM = {
    "Po-210": {"F": 6.0e-07, "M": 3.0e-06},
    "Ra-226": {"M": 3.2e-06},
    "U-238": {"F": 4.9e-07, "M": 2.6e-06, "S": 7.3e-06},
    "Pu-239": {"M": 4.7e-05, "S": 1.5e-05},
    "Am-241": {"M": 3.9e-05},
}


class BuildError(Exception):
    """Loud failure — a structural surprise or a failed consistency check. Never swallowed."""


def _validate_consistency() -> None:
    """The two build-time transcription cross-checks (see module docstring)."""
    wc, pc = WORKER["coefficients"], PUBLIC_ADULT["coefficients"]
    for nuc in wc:
        # (1) ingestion f1-ratio: e_public/e_worker == f1_public/f1_worker
        we, wf = wc[nuc]["ingestion"]["e_Sv_Bq"], wc[nuc]["ingestion"]["f1"]
        pe, pf = pc[nuc]["ingestion"]["e_Sv_Bq"], pc[nuc]["ingestion"]["f1"]
        got, want = pe / we, pf / wf
        if abs(got - want) / want > 0.10:
            raise BuildError(
                f"{nuc} ingestion f1-ratio check FAILED: e_public/e_worker={got:.3g} "
                f"!= f1_public/f1_worker={want:.3g} (>10% — suspected transcription error)"
            )
        # (2) inhalation: EVERY shipped public-adult 1µm type ≈ worker 1µm same type (same lung
        # model). Every public type MUST have a worker-1µm counterpart — no unchecked value ships.
        w1_types = _WORKER_1UM[nuc]
        for atype, p1 in pc[nuc]["inhalation"]["types"].items():
            if atype not in w1_types:
                raise BuildError(
                    f"{nuc} inhalation Type-{atype} has NO worker-1µm counterpart to validate "
                    "against — refusing to ship an uncross-checked value (drop it or crop-read it)"
                )
            w1 = w1_types[atype]
            if not (1 / 1.4 <= p1 / w1 <= 1.4):
                raise BuildError(
                    f"{nuc} inhalation Type-{atype} worker-1µm↔public-adult check FAILED: "
                    f"public={p1:.3g} vs worker-1µm={w1:.3g} (>40% — suspected misread)"
                )


def _build_one(spec: dict) -> dict:
    out = {
        "schema_version": SCHEMA_VERSION,
        "population": spec["population"],
        "icrp_publication": spec["icrp_publication"],
        "age": spec["age"],
        "amad_um": spec["amad_um"],
        "units": UNITS,
        "progeny_convention": PROGENY_CONVENTION,
        "source_ref": "ICRP Publication 119 (2012), Compendium of Dose Coefficients based on "
                      "ICRP Publication 60; e(50) committed effective dose, Sv/Bq.",
        "coefficients": spec["coefficients"],
    }
    # Structural sanity: every coefficient positive and in a physical range.
    for nuc, rec in spec["coefficients"].items():
        for route in ("ingestion", "inhalation"):
            if route not in rec:
                continue
            vals = ([rec[route]["e_Sv_Bq"]] if route == "ingestion"
                    else list(rec[route]["types"].values()))
            for v in vals:
                if not (1e-13 < v < 1e-3):
                    raise BuildError(f"{nuc}/{route}: e={v} outside plausible Sv/Bq range")
        if "inhalation" in rec:
            dt = rec["inhalation"]["default_type"]
            if dt not in rec["inhalation"]["types"]:
                raise BuildError(f"{nuc}: default_type {dt!r} not among tabulated types")
    return out


def main() -> None:
    _validate_consistency()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for spec in (WORKER, PUBLIC_ADULT):
        out = _build_one(spec)
        path = OUT_DIR / f"{spec['population']}.json"
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}  ({len(out['coefficients'])} nuclides)")


if __name__ == "__main__":
    main()
