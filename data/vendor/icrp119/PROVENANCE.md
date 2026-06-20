# ICRP-119 — committed dose coefficients (internal dose, §M13)

**Source of record:** `icrp119.pdf`
ICRP Publication 119 (2012), *Compendium of Dose Coefficients based on ICRP Publication 60*
(Eckerman, Harrison, Menzel, Clement; Ann. ICRP 41 Suppl.). Free download from ICRP:
<https://www.icrp.org/docs/p%20119%20jaicrp%2041(s)%20compendium%20of%20dose%20coefficients%20based%20on%20icrp%20publication%2060.pdf>

- `sha256 = 5b891dd8a17a85fbfd60324eea6bb32e552284ae48b70eebabeb251c6c679516`
- 132 pages. Printed page = PDF page − 2.

## What we use

Committed **effective** dose coefficients **e(50)** (Sv/Bq) for intake by **ingestion** and
**inhalation**, for the M13 internal-dose engine. Two populations:

| Population | ICRP source | Annex (table) | AMAD | Notes |
|---|---|---|---|---|
| `worker` | ICRP-68 | Annex A (Table A.1) | 5 µm | ingestion + inhalation types F/M/S; table also lists 1 µm |
| `public_adult` | ICRP-72 | Annex F (ingestion) + Annex G (inhalation) | 1 µm | "Adult" column; inhalation types F/M/S |

Coefficients are **parent-only with in-vivo progeny ingrowth** (ICRP-119 base per-nuclide rows,
NOT the "+"-bundled equilibrium entries) — so summing over the full tracked inventory is correct
and does not double-count (see `docs/plans/M13-internal-dose.md`).

## Extraction method — VISUAL read, not `pdftotext`

`pdftotext -layout` **scrambles** these tables (the multi-line element-group headers and the
T½ column float out of row alignment — the same M12 lesson; e.g. it pairs "Be-7" with C-14's
"5730 y"). All values were read from the **rendered table pages** (Read tool / 300-DPI
`pdftoppm` crops for dense rows), the way M12 read PANDA from the rendered image.

## Read-time integrity — the §12 transcription trap, and how it is caught

Hand-transcribing ~Sv/Bq values is the dominant error risk. ICRP-119 typesets the **same
numbers twice in independent annexes**, which gives two cross-checks (both enforced at build
time in `data/build/build_internal_dose.py` — a value that fails refuses to build):

1. **Ingestion equal-f1 ⇒ equal-e** (reframed in the fission-product batch). Where worker
   (Annex A) and public-adult (Annex F) ingestion **f1 are equal**, the biokinetics are
   identical, so `e_worker == e_public` (asserted ≤10% for rounding). This is the strong,
   *assumption-free* transcription check. The original "ratio `e_public/e_worker == f1_public/
   f1_worker`" was discarded as the general rule: committed ingestion dose is **affine** in f1,
   `e = G + f1·(S−G)`, where `G` is the **f1-independent GI-transit (colon) dose**; the ratio
   holds only when `G ≈ 0` (systemic-dominated). It is exact for **Po-210** (α, retained →
   `G≈0`: worker f1 0.1 → public f1 0.5 reconciles to **exactly 5×**) but FAILS for **Tc-99**
   (β, large colon dose: worker f1 0.8 → 7.8E-10, public f1 0.5 → 6.4E-10; ratio 0.82 ≠ 0.625).
   Nuclides whose f1 differ are an explicit set `DIFFERING_F1_INGESTION = {Po-210, Tc-99}`; the
   build **raises** if an f1 differs for a nuclide *not* in the set (a misread f1 must not skip
   the check), and solves the two-population affine model asserting `G ≥ 0, S > 0`. (This is a
   legitimate *upgrade*, not a tolerance loosening — see CLAUDE.md "don't edit a check to pass".)
2. **Inhalation worker-1µm ↔ public-adult-1µm**, for **every shipped absorption type**. Annex A's
   1 µm column must agree with Annex G's public-adult 1 µm value to ~40 % (same HRTM lung model,
   ~same reference person). A public type with **no** worker counterpart is REFUSED by the build.

**Absorption-type coverage differs by batch.** The 5 micro-slice actinides ship all tabulated
F/M/S; the fission products ship the **ICRP default type only** (Annex E "unspecified compounds"
catch-all per element — Co M, Se F, Sr F, Tc F, Ru F, Cs F, Ce M). Reason: v1 folds *only* the
default type (the bridge passes `absorption_type=None`; no UI type toggle), so a non-default type
would be a shipped-but-never-folded, unvalidated number — the honesty hazard for zero v1 benefit.
Non-default capture is deferred to the type-toggle extension. (The micro-slice's earlier dropping
of Po-210 S, Ra-226 F/S, Am-241 F/S, suspect Pu-239 F still stands.)

**Errors these checks actually caught** (recorded for honesty):
- **Am-241** public-adult Type-M adult misread as `9.6E-05` (the *F*-row value) → corrected to
  **`4.2E-05`** via a 300-DPI crop (worker M 1 µm = 3.9E-05 confirms).
- **U-238** worker 5 µm M corrected from a first-pass **1 µm** read (`2.6E-06`) to the 5 µm
  value **`1.6E-06`**. ⚠️ **U-238 worker 5 µm S was itself wrong as shipped** (`6.3E-06`) until
  the M13 actinide-expansion batch: `6.3E-06` is **U-236's** 5 µm S (the adjacent row); a
  300-DPI crop of printed p.54 gives U-238 **5 µm S = `5.7E-06`** (1 µm S = `7.3E-06`).
  This slipped because the build's inhalation check validates the **1 µm** column (`7.3E-06`),
  never the shipped worker **5 µm** value, and S is a non-default type (never folded in v1).
  Corrected value `5.7E-06`; regression golden in `test_absorption_type_override` updated.
- **Po-210** worker-1µm default cross-check value first taken from the F row (`6.0E-07`) →
  corrected to the M row **`3.0E-06`** (matches public M `3.3E-06`).
- **Co-60** (fission-product batch) public-M adult 1 µm misread as `1.7E-08` from the full-page
  extract (a **15y↔adult column miscount** — adjacent ages differ <40%, so it slipped *inside*
  the inhalation-check tolerance, a silent error). A 300-DPI crop gave the true **`1.0E-08`**
  (worker-1µm M `9.6E-09` → 1.04×). Lesson: the dense Annex G table is **crop-read only**;
  `pdftotext` scrambles it and full-page extracts induce column miscounts.

**Trust boundary (honesty):** these checks prove **transcription fidelity**, not methodology —
ICRP-119 is the sole methodology source, so true methodological independence is not on the
table (the once-considered ANL/Argonne fact sheets publish *lifetime cancer-risk* coefficients,
a different quantity, not e(50), so they cannot validate the dose values).

## Coverage

A **curated slice** (16 nuclides), extensible like spent-fuel's `GRID_POINTS`:
- **Actinide micro-slice** (all F/M/S): Po-210, Ra-226, U-238, Pu-239, Am-241.
- **Fission/activation products** (default type only): Co-60, Se-79, Sr-90, Tc-99, Ru-106,
  Cs-134, Cs-137, Ce-144.
- **Actinide expansion** (all F/M/S; 300-DPI crop-verified, in progress): U-234, U-235, U-236.

A tracked nuclide absent from the shipped set makes a committed-dose estimate a **LOWER BOUND**,
surfaced loudly by the engine (§11). Still uncovered (future batches): the remaining must-cover
particulates (Sb-125, Sn-126, Pm-147, Eu-154/155, Pb-210, …), the **actinide expansion**
(Th/Pa/U/Np/Pu/Am/Cm isotopes), and the **gas/vapour special cases** (H-3 HTO/OBT, I-129/I-131
elemental & methyl-iodide vapour) which need a chemical-form schema bump, not F/M/S types.
Noble gases (Kr/Xe/Rn/…) have **no intake coefficient** (Annex C is submersion dose *rate*, a
different quantity) — the engine treats them as a distinct "N/A" state, not a gap.
