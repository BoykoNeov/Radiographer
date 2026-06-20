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

  (1) **Ingestion equal-f1 check** (reframed in the M13 fission-product batch — see below).
      When a nuclide's worker (Annex A) and public-adult (Annex F) ingestion f1 are EQUAL, the
      committed-dose coefficient is identical (same biokinetics) → e_worker == e_public. This
      is the strong, ASSUMPTION-FREE transcription check (independent typesetting), and it holds
      exactly for the matched-f1 actinides and all but one fission product. When f1 DIFFERS, the
      nuclide must be a documented exception in ``DIFFERING_F1_INGESTION`` (else a misread f1
      would silently route a value around all cross-checking); the ratio e∝f1 is NOT asserted
      there because it is physically invalid for ingested β-emitters (see that set's note).
  (2) **Inhalation worker-1µm ↔ public-adult-1µm check**, for every SHIPPED public type: Annex A
      also lists the worker 1 µm value, which must agree with the Annex G public-adult 1 µm value
      to ~40 % (same HRTM lung model, ~same reference person). This caught a first-pass misread
      of Am-241 (M adult read as 9.6E-05 — actually the F-row value; corrected to 4.2E-05 via a
      300-DPI crop), and — in the fission-product batch — a Co-60 public-M adult miscount (15y
      column read as adult, 1.7E-08 vs the true 1.0E-08; the crop resolved it to a 1.04× match).

The coverage is a CURATED slice (not all ~800 ICRP-119 nuclides); a tracked nuclide absent
here makes a committed-dose estimate a LOWER BOUND, surfaced loudly by the engine (§11).

**Absorption-type coverage (M13 fission-product batch):** the 5 actinides ship all tabulated
F/M/S types; the fission products ship the ICRP default type ONLY (the "unspecified compounds"
catch-all from ICRP-119 Annex E, Table E.1). Rationale: v1 folds only the default type (the
bridge passes ``absorption_type=None`` and there is no UI type toggle), so a non-default type
would be a shipped-but-never-folded, unvalidated number — the honesty-register hazard for zero
v1 benefit. Non-default capture is deferred to the type-toggle extension (see docs/plans). The
default type per element is read from Annex E, not chosen by value or memory.
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
        # NOTE (M13 actinide-expansion batch): worker 5µm S CORRECTED 6.3E-06 -> 5.7E-06. The
        # 6.3E-06 was U-236's 5µm S (adjacent row); a 300-DPI crop of printed p.54 gives U-238
        # 5µm S = 5.7E-06 (1µm S = 7.3E-06). This shipped value was never cross-checked because
        # the build's inhalation check validates the 1µm column, not the shipped worker 5µm, and
        # S is a non-default type (never folded in v1). See PROVENANCE.md.
        "U-238": {"ingestion": {"e_Sv_Bq": 4.4e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.8e-07, "M": 1.6e-06, "S": 5.7e-06}}},
        # Pu-239  (printed p.55): ingestion f1 0.0005; inhalation 5µm M/S
        "Pu-239": {"ingestion": {"e_Sv_Bq": 2.5e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 3.2e-05, "S": 8.3e-06}}},
        # Am-241  (printed p.56): ingestion f1 0.0005; inhalation 5µm M only
        "Am-241": {"ingestion": {"e_Sv_Bq": 2.0e-07, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 2.7e-05}}},

        # --- M13 fission/activation-product batch (default-type-only inhalation, 5 µm) ---
        # default_type = ICRP-119 Annex E "unspecified compounds" catch-all per element.
        # Co-60  (Annex A printed p.28): ingestion f1 0.1; inhalation 5µm M (Annex E: Co M)
        "Co-60": {"ingestion": {"e_Sv_Bq": 3.4e-09, "f1": 0.1},
                  "inhalation": {"default_type": "M", "types": {"M": 7.1e-09}}},
        # Se-79  (printed p.30): ingestion f1 0.8; inhalation 5µm F (Annex E: Se F)
        "Se-79": {"ingestion": {"e_Sv_Bq": 2.9e-09, "f1": 0.8},
                  "inhalation": {"default_type": "F", "types": {"F": 1.6e-09}}},
        # Sr-90  (printed p.31): ingestion f1 0.3; inhalation 5µm F (Annex E: Sr F)
        "Sr-90": {"ingestion": {"e_Sv_Bq": 2.8e-08, "f1": 0.3},
                  "inhalation": {"default_type": "F", "types": {"F": 3.0e-08}}},
        # Tc-99  (printed p.33): ingestion f1 0.8; inhalation 5µm F (Annex E: Tc F)
        "Tc-99": {"ingestion": {"e_Sv_Bq": 7.8e-10, "f1": 0.8},
                  "inhalation": {"default_type": "F", "types": {"F": 4.0e-10}}},
        # Ru-106 (printed p.34): ingestion f1 0.05; inhalation 5µm F (Annex E: Ru F)
        "Ru-106": {"ingestion": {"e_Sv_Bq": 7.0e-09, "f1": 0.05},
                   "inhalation": {"default_type": "F", "types": {"F": 9.8e-09}}},
        # Cs-134 (printed p.40): ingestion f1 1.0; inhalation 5µm F (Annex E: Cs F, all compounds)
        "Cs-134": {"ingestion": {"e_Sv_Bq": 1.9e-08, "f1": 1.0},
                   "inhalation": {"default_type": "F", "types": {"F": 9.6e-09}}},
        # Cs-137 (printed p.40): ingestion f1 1.0; inhalation 5µm F
        "Cs-137": {"ingestion": {"e_Sv_Bq": 1.3e-08, "f1": 1.0},
                   "inhalation": {"default_type": "F", "types": {"F": 6.7e-09}}},
        # Ce-144 (printed p.41): ingestion f1 0.0005; inhalation 5µm M (Annex E: Ce M)
        "Ce-144": {"ingestion": {"e_Sv_Bq": 5.2e-09, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 2.3e-08}}},

        # ============ M13 ACTINIDE-EXPANSION BATCH (all tabulated F/M/S) ============
        # User chose full F/M/S capture (extension-ready for the per-nuclide type toggle), so
        # every tabulated type ships and gets a worker-1µm counterpart in _WORKER_1UM. Worker
        # Annex A (Table A.1), 5 µm AMAD shipped; ingestion = the f1-matched public row. All
        # values 300-DPI crop-verified (the full-page Annex G adult column miscounts — see
        # PROVENANCE). default_type per element from Annex E (U: M).
        # --- Uranium (printed p.54; Annex A) ---
        "U-234": {"ingestion": {"e_Sv_Bq": 4.9e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 6.4e-07, "M": 2.1e-06, "S": 6.8e-06}}},
        "U-235": {"ingestion": {"e_Sv_Bq": 4.6e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 6.0e-07, "M": 1.8e-06, "S": 6.1e-06}}},
        "U-236": {"ingestion": {"e_Sv_Bq": 4.6e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 6.1e-07, "M": 1.9e-06, "S": 6.3e-06}}},
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

        # --- M13 fission/activation-product batch (default-type-only inhalation, 1 µm adult) ---
        # Ingestion = Annex F "Adult" column + the adult f1 (footnote-adjusted where flagged).
        # Inhalation = Annex G "Adult" column, default type only (crop-read; cross-checked vs the
        # worker 1 µm column in _WORKER_1UM below). Co-60 (printed p.72/89), Se-79 (73/91),
        # Sr-90 (74/93), Tc-99 (75/95), Ru-106 (75/96), Cs-134/137 (77/102), Ce-144 (78/103).
        "Co-60": {"ingestion": {"e_Sv_Bq": 3.4e-09, "f1": 0.1},     # adult f1 0.1 (Annex F **)
                  "inhalation": {"default_type": "M", "types": {"M": 1.0e-08}}},
        "Se-79": {"ingestion": {"e_Sv_Bq": 2.9e-09, "f1": 0.8},
                  "inhalation": {"default_type": "F", "types": {"F": 1.1e-09}}},
        "Sr-90": {"ingestion": {"e_Sv_Bq": 2.8e-08, "f1": 0.3},     # adult f1 0.3 (Annex F *)
                  "inhalation": {"default_type": "F", "types": {"F": 2.4e-08}}},
        # Tc-99 DIFFERING-f1 exception: public adult ingestion f1 0.5 vs worker 0.8 (see set below)
        "Tc-99": {"ingestion": {"e_Sv_Bq": 6.4e-10, "f1": 0.5},
                  "inhalation": {"default_type": "F", "types": {"F": 2.9e-10}}},
        "Ru-106": {"ingestion": {"e_Sv_Bq": 7.0e-09, "f1": 0.05},
                   "inhalation": {"default_type": "F", "types": {"F": 7.9e-09}}},
        "Cs-134": {"ingestion": {"e_Sv_Bq": 1.9e-08, "f1": 1.0},
                   "inhalation": {"default_type": "F", "types": {"F": 6.6e-09}}},
        "Cs-137": {"ingestion": {"e_Sv_Bq": 1.3e-08, "f1": 1.0},
                   "inhalation": {"default_type": "F", "types": {"F": 4.6e-09}}},
        "Ce-144": {"ingestion": {"e_Sv_Bq": 5.2e-09, "f1": 5e-04},
                   "inhalation": {"default_type": "M", "types": {"M": 3.6e-08}}},

        # ============ M13 ACTINIDE-EXPANSION BATCH (all tabulated F/M/S) ============
        # Public adult: Annex F (ingestion, "Adult" column) + Annex G (inhalation, 1 µm "Adult"
        # column). Inhalation adult values are 300-DPI crop-verified (full-page reads miscount the
        # adult vs 15y column). Each type cross-checked vs the worker 1 µm column (_WORKER_1UM).
        # --- Uranium (ingestion f1 0.02 == worker f1 → equal-e check; default M) ---
        "U-234": {"ingestion": {"e_Sv_Bq": 4.9e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.6e-07, "M": 3.5e-06, "S": 9.4e-06}}},
        "U-235": {"ingestion": {"e_Sv_Bq": 4.7e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.2e-07, "M": 3.1e-06, "S": 8.5e-06}}},
        "U-236": {"ingestion": {"e_Sv_Bq": 4.6e-08, "f1": 0.02},
                  "inhalation": {"default_type": "M",
                                 "types": {"F": 5.3e-07, "M": 3.2e-06, "S": 8.7e-06}}},
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
    # Fission-product batch — worker 1 µm, DEFAULT type only (public ships default only):
    "Co-60": {"M": 9.6e-09},
    "Se-79": {"F": 1.2e-09},
    "Sr-90": {"F": 2.4e-08},
    "Tc-99": {"F": 2.9e-10},
    "Ru-106": {"F": 8.0e-09},
    "Cs-134": {"F": 6.8e-09},
    "Cs-137": {"F": 4.8e-09},
    "Ce-144": {"M": 3.4e-08},
    # M13 actinide-expansion batch — worker 1 µm, ALL F/M/S (300-DPI crop-verified, Annex A):
    "U-234": {"F": 5.5e-07, "M": 3.1e-06, "S": 8.5e-06},
    "U-235": {"F": 5.1e-07, "M": 2.8e-06, "S": 7.7e-06},
    "U-236": {"F": 5.2e-07, "M": 2.9e-06, "S": 7.9e-06},
}

#: Nuclides whose worker (Annex A) and public-adult (Annex F) ingestion **f1 differ**, so the
#: equal-f1 cross-check (1) cannot apply. The naive ratio e_public/e_worker == f1_public/f1_worker
#: is NOT asserted here because it is physically valid only when the systemic (f1-scaled) dose
#: dominates: committed ingestion dose is affine in f1, ``e = G + f1·(S−G)``, where ``G`` is the
#: f1-INDEPENDENT GI-transit (e.g. colon) dose. The ratio holds only when ``G ≈ 0``:
#:   * Po-210 (α, retained systemically → G≈0): worker f1 0.1 → public f1 0.5 reconciles to an
#:     EXACT 5×, asserted as a golden in tests/test_internal_dose.py.
#:   * Tc-99 (β, large colon transit dose → G≫0): worker (f1 0.8) 7.8E-10, public (f1 0.5)
#:     6.4E-10. Solving the two-population affine model gives G≈4.1E-10, S≈8.7E-10 (both > 0).
#: Each value here is a published ICRP-68/72 anchor. A nuclide whose f1 differs but is ABSENT
#: from this set raises at build time (a misread f1 must not silently skip cross-checking).
DIFFERING_F1_INGESTION: set[str] = {"Po-210", "Tc-99"}


class BuildError(Exception):
    """Loud failure — a structural surprise or a failed consistency check. Never swallowed."""


def _validate_consistency() -> None:
    """The two build-time transcription cross-checks (see module docstring)."""
    wc, pc = WORKER["coefficients"], PUBLIC_ADULT["coefficients"]
    for nuc in wc:
        we, wf = wc[nuc]["ingestion"]["e_Sv_Bq"], wc[nuc]["ingestion"]["f1"]
        pe, pf = pc[nuc]["ingestion"]["e_Sv_Bq"], pc[nuc]["ingestion"]["f1"]
        # (1) ingestion cross-check — equal-f1 ⇒ equal-e (assumption-free); differing-f1 ⇒ must
        # be a documented exception (the ratio e∝f1 is invalid; see DIFFERING_F1_INGESTION).
        if wf == pf:
            if abs(pe - we) / we > 0.10:
                raise BuildError(
                    f"{nuc} ingestion equal-f1 check FAILED: e_public={pe:.3g} != "
                    f"e_worker={we:.3g} at shared f1={wf} (>10% — suspected transcription error)"
                )
        elif nuc not in DIFFERING_F1_INGESTION:
            raise BuildError(
                f"{nuc} ingestion f1 differs (worker={wf}, public={pf}) but it is not in "
                "DIFFERING_F1_INGESTION — verify the f1 reads (a misread f1 must not skip the check)"
            )
        else:
            # Affine sanity for a documented differing-f1 nuclide: e = G + f1·(S−G); solving the
            # two populations must give G >= 0 and S > 0 (catches gross/sign/decade misreads).
            slope = (pe - we) / (pf - wf)            # = S − G
            g = we - wf * slope                      # GI-transit (f1-independent) intercept
            s = g + slope                            # f1=1 (fully absorbed) coefficient
            if not (g >= -1e-12 and s > 0.0):
                raise BuildError(
                    f"{nuc} differing-f1 affine solve nonphysical: G={g:.3g}, S={s:.3g} "
                    "(suspected transcription error in an ingestion e or f1)"
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
