# Vendored upstream — ANS-6.4.3 G-P gamma-ray buildup factors

Source material for the **buildup** dataset (the buildup factor B(E, x) that corrects the
point-kernel for scattered photons, `I = I₀·B·e^(−μx)`; `HANDOFF_PLAN.md` §6.5/§7).

> **This dataset uses a DEGRADED provenance model** vs the NIST attenuation and ICRP-107
> emission data. Read `docs/plans/M2-buildup.md` for the full rationale. In short: there
> is **no clean, machine-readable, openly-licensed** ANS-6.4.3 G-P dataset, so we cannot
> reproduce the "verbatim bytes + independent re-parse" integrity model. Faithfulness is
> instead enforced by the validation suite (cross-source + within-source reconstruction
> + physics goldens). See the trust boundary below.

## Source chain

| Layer | Detail |
|---|---|
| Primary standard | **ANSI/ANS-6.4.3-1991**, *Gamma-Ray Attenuation Coefficients and Buildup Factors for Engineering Materials* (copyrighted/paywalled ANS standard — NOT redistributable). |
| Public-domain equivalent (what we vendor) | **NUREG/CR-5740 / ORNL/RSIC-49/R1**, D. K. Trubey, *New Gamma-Ray Buildup Factor Data for Point Kernel Calculations: ANS-6.4.3 Standard Reference Data*, Aug 1991. **Identical data** to the standard; a U.S. DOE/ORNL/NRC work, **public domain**. DOI [10.2172/7032799](https://doi.org/10.2172/7032799) (OSTI). |
| Machine-readable original (NOT used) | RSICC **DLC-129** ("ANS643", 5.25″ diskette, Fortran card images) — access-gated/likely export-controlled, not directly downloadable. |
| This repo | `NUREG-CR-5740.pdf` (the report, byte-for-byte as downloaded from OSTI — a 1991 scan with an unreliable ABBYY FineReader OCR layer) + `gp_exposure_transcription.json` (the hand-keyed, double-entered mirror of its appendix Table 5.1 **exposure** coefficients) + `b_value_spotchecks.json` (Table 3 B-values for the reconstruction test). |

## What was transcribed

Appendix **Table 5.1** of NUREG/CR-5740 gives, per material, two coefficient sub-tables:
*G-P Energy Absorption Buildup Factor Coefficients* (kerma) and *G-P Exposure Buildup
Factor Coefficients* (air-kerma). We transcribe the **exposure** set (consistent with the
μ_en/ρ-in-air dose path, §6.1), five Harima G-P coefficients `b, c, a, Xk, d` per energy.

**Materials & exposure-table PDF pages:** aluminium (103), iron (110), copper (111),
tungsten (116), lead (117), water (119), air (120), concrete (121).

Notes:
- **Lead** is tabulated on a 23-point grid starting at **0.03 MeV** (no 0.015/0.020);
  the `b=2.037` spike at 0.10 MeV is the real K-edge (0.088 MeV) effect.
- **Tungsten** uses the full 25-point grid; K-edge (0.0695 MeV) spike at 0.080 MeV.
- **Air** has a single table (labelled *energy absorption*); for the air medium that IS
  the air-kerma/exposure response, so it is used as air's exposure buildup.
- **PMMA, polyethylene, soft tissue are absent** — ANS-6.4.3 has no buildup data for
  them. Their absence is the honest contract; the M3 dose engine handles it loudly.

## Transcription method (double-entry)

Each coefficient was read from a **rendered page image** (the authoritative channel —
the OCR layer has demonstrable digit/row-shift errors) and reconciled against the ABBYY
OCR text (second channel); disagreements were resolved by re-inspecting the image at
higher zoom. See `docs/plans/M2-buildup.md`.

## Drift guard

The build (`../../build/build_buildup.py`) pins the SHA-256 of the source-of-record PDF
and **refuses to run** unless it matches:

```
96e102faee3b40c93f78b0ca9d190c6b10bf602b9f6a8cde01cfff8d9df68aa8
```

So the committed canonical files cannot be silently rebuilt from a different/corrupted
scan. (Unlike NIST/ICRP, this does *not* prove canonical==upstream — the transcription
is hand-keyed; it only pins the source the transcription was made from.)

## Trust boundary (honesty)

The verbatim-re-parse integrity check available for NIST/ICRP **does not exist here**
(hand-keyed from a scan). Faithfulness is instead enforced by reconstruction:
- the coefficients reproduce the report's *own* Table 3 exposure B-values to **≤ 2.6%
  for all 8 materials** (37 anchors, `b_value_spotchecks.json`) — Table 3 is an
  independent representation (the moments-method data the G-P fit approximates), so this
  catches systematic transcription errors and gives every material value-level coverage;
- **iron** is additionally matched against an independent open-access tabulation (EPJ
  Web Conf. 106, 03009 (2016), CC-BY) — 5 energies match exactly (its 0.50 & 10 MeV rows
  are garbled in the paper and excluded).

Beyond the anchored (E, mfp) points, the rest of each table is trusted to the
double-entered transcription. This mirrors the emissions trust boundary (golden nuclides
verified; bulk trusted to upstream).

## License

NUREG/CR-5740 is a **U.S. Government work — public domain** (NRC/DOE/ORNL); citation
requested. It carries **no** non-commercial restriction. The G-P coefficients themselves
are physical fit-constants (facts). The repo-license constraint comes solely from the
ICRP-107 emission data, not from this dataset.

## Re-vendoring (only to deliberately bump the source)

```sh
# re-download NUREG/CR-5740 from OSTI (DOI 10.2172/7032799), update EXPECTED_PDF_SHA256
# in data/build/build_buildup.py, re-verify the transcription against the new scan,
# rebuild, and re-run tests/test_buildup_data.py.
```
