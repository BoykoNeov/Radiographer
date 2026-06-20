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
| `worker` | ICRP-68 | Annex A (Table A.1) | 5 µm | particulates: ingestion + inhalation types F/M/S; table also lists 1 µm |
| `public_adult` | ICRP-72 | Annex F (ingestion) + Annex G (inhalation) | 1 µm | "Adult" column; inhalation types F/M/S |
| **gas/vapour** (schema v2) | ICRP-68 / ICRP-72 | **Annex B** (worker inhalation) + **Annex H** (public inhalation) + Annex A/F (H-3 ingestion) | n/a | H-3 (HTO/OBT), iodine (elemental I₂ / methyl CH₃I vapour). **No AMAD** — chemical forms, not F/M/S. Reference-adult, age-independent → worker == public. |

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
3. **Gas/vapour worker ↔ public, per form (schema v2 — `_validate_gas_vapour`).** H-3 (HTO/OBT)
   and iodine (elemental/methyl vapour) have **no AMAD**: the coefficient is reference-adult and
   age-independent, so the worker (Annex B) and public (Annex H) values are **identical**, asserted
   exactly per form. **Honesty — this is the WEAKEST guard in the file.** The worker and public
   numbers are *hand-entered identical literals* (I typed the same value into both dicts), so the
   build assertion passes *by construction* and only proves I entered them consistently, NOT that
   either matches ICRP. There is no differing second column to triangulate against (unlike the
   5µm/1µm particulate check, which compares two genuinely different numbers). The reads *were*
   taken from two independently typeset tables (Annex B p.59 vs Annex H p.121), so a one-sided
   slip *during reading* would have shown up — but **gas/vapour transcription fidelity ultimately
   rests on the manual read, not on this check.** The values do match the well-known ICRP-68/72
   coefficients (HTO 1.8E-11, OBT ~4.1E-11, I-131 elemental 2.0E-08, methyl 1.5E-08).

**Absorption-type coverage differs by batch.** The 5 micro-slice actinides ship all tabulated
F/M/S; the fission products ship the **ICRP default type only** (Annex E "unspecified compounds"
catch-all per element — Co M, Se F, Sr F, Tc F, Ru F, Cs F, Ce M). Reason: v1 folds *only* the
default type (the bridge passes `absorption_type=None`; no UI type toggle), so a non-default type
would be a shipped-but-never-folded, unvalidated number — the honesty hazard for zero v1 benefit.
Non-default capture is deferred to the type-toggle extension. (The micro-slice's earlier dropping
of Po-210 S, Ra-226 F/S, Am-241 F/S, suspect Pu-239 F still stands.)

**Errors these checks actually caught** (recorded for honesty):
- **Po-210** `default_type` was **M**, but ICRP-119 **Annex E (Table E.1)** lists Polonium
  "Unspecified compounds" = **Type F** (f1 0.1) — and the LOCKED rule is "default = the Annex E
  catch-all". The original micro-slice chose M as the "commonly-cited" Po-210 inhalation value
  (and many regulatory tables do cite Type M, ~3E-6); the **M13 non-actinide re-verify** caught
  the rule violation and corrected it to **F**, so the folded committed inhalation dose is now
  **7.1E-07** (worker) / **6.0E-07** (public), ~3× lower than the M value. Both F and M values
  remain tabulated in the data; only which one is *folded* (the default) changed. This was NOT a
  transcription error — the F/M values were always right — but a default-type-selection error
  that the build's value cross-checks cannot catch (they validate every type, not the choice of
  default); only re-reading Annex E does. (User decision, 2026-06-20: switch to F, rule-compliant.)
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
- **Pa-231** (actinide-remainder batch) worker 5 µm **S** misread `5.7E-07` (1 µm `7.1E-07`) on a
  first-pass full-page read — those are **Pa-230's** S-row values (the adjacent row above). A
  300-DPI crop gives the true Pa-231 **S 5 µm `1.7E-05`** (1 µm `3.2E-05`). Like the U-238 S bug,
  this lived in the 5 µm column (never cross-checked) on a non-default type (never folded), so only
  the crop catches it; the Pa-231 **M** values (folded) were read correctly throughout.
- **Co-60** (fission-product batch) public-M adult 1 µm misread as `1.7E-08` from the full-page
  extract (a **15y↔adult column miscount** — adjacent ages differ <40%, so it slipped *inside*
  the inhalation-check tolerance, a silent error). A 300-DPI crop gave the true **`1.0E-08`**
  (worker-1µm M `9.6E-09` → 1.04×). Lesson: the dense Annex G table is **crop-read only**;
  `pdftotext` scrambles it and full-page extracts induce column miscounts.

**Trust boundary (honesty):** these checks prove **transcription fidelity**, not methodology —
ICRP-119 is the sole methodology source, so true methodological independence is not on the
table (the once-considered ANL/Argonne fact sheets publish *lifetime cancer-risk* coefficients,
a different quantity, not e(50), so they cannot validate the dose values). The gas/vapour batch
considered **EPA FGR-13** as an external anchor for H-3/iodine but did **not** use it: FGR-13
("Cancer Risk Coefficients…") publishes *risk per Bq*, not Sv/Bq — the same wrong-quantity problem
as the Argonne sheets — so it cannot validate a dose coefficient. The real gas/vapour guard is the
two-annex worker↔public form-matched check (Annex B vs Annex H), as for every other nuclide.

## Coverage

A **curated slice** (40 nuclides), extensible like spent-fuel's `GRID_POINTS`:
- **Actinide micro-slice** (all F/M/S): Po-210, Ra-226, U-238, Pu-239, Am-241.
- **Fission/activation products** (default type only): Co-60, Se-79, Sr-90, Tc-99, Ru-106,
  Cs-134, Cs-137, Ce-144.
- **Actinide expansion** (all *cross-checkable* tabulated types; 300-DPI crop-verified):
  U-234/235/236, Np-237, Pu-238/240/241/242, Am-243, Cm-242/243/244/245/246. Per element the
  worker (Annex A, ICRP-68) tabulates fewer absorption types than the public Annex G (ICRP-72):
  worker **Np/Am/Cm = M only**, worker **Pu = M & S (no F)**. A public type without a worker-1µm
  counterpart cannot be cross-checked, so it is **not shipped** — the shipped set is "all types
  tabulated for *both* populations", which the build's per-type worker-1µm↔public guard enforces.
- **Actinide remainder** (Th-228/230/232, Pa-231) — **Type M & S** (worker tabulates only M & S,
  no F; public Annex G also lists F, dropped for lack of a worker counterpart). default M (Annex E
  Th/Pa "unspecified compounds" = Type M, f1 5E-04). Worker Annex A printed p.53 (Th) / p.54 (Pa),
  5 µm column 300-DPI crop-read **twice**. The **dual thorium ingestion f1** (the table lists both
  0.0005 and 0.0002 per nuclide) resolves to the Annex E catch-all **f1 5E-04** (Type M); the
  0.0002 is the Type-S oxide route, not the default — so ingestion ships the f1 5E-04 value and the
  worker↔public equal-f1 check holds (no `DIFFERING_F1_INGESTION` entry). All M & S cross-check vs
  the worker 1 µm column at 1.06–1.09×. (Pa-231 S full-page miscount caught — see "Errors caught".)
- **Non-actinide expansion** (default type only — Annex E: Pb F, Sb F, Sn F, Pm M, Eu M):
  Pb-210, Sb-125, Sn-126, Pm-147, Eu-154/155. Worker 5 µm shipped value 300-DPI crop-read TWICE
  (it is the one column the build never cross-checks — the U-238/Po-210 soft spot). All six share
  worker↔public ingestion f1, so the equal-f1 check holds (Pb-210's adult f1 is 0.2 via the
  Annex F footnote, NOT the 0.4 child column). This batch also re-verified the existing 8
  fission-product + Po-210 worker 5 µm defaults (all correct) and corrected the Po-210 default
  type (see "Errors caught").
- **Gas/vapour** (schema v2 — chemical forms, NOT F/M/S): **H-3** (HTO / OBT), **I-129**, **I-131**
  (elemental I₂ / methyl CH₃I vapour, vapour-only). Inhalation from Annex B (worker) / Annex H
  (public); H-3 ingestion from Annex A/F per form; iodine ingestion is a single value. Defaults
  (representative unspecified-exposure form): H-3 → HTO, iodine → elemental. **Iodine ships
  vapour-only** (the locked scope) — the Annex A particulate-F form is out of scope, which is why
  the Annex-E particulate catch-all does NOT bind the vapour default choice (Annex E classifies
  aerosol absorption types only). H-3 OBT ingestion is ~2.3× HTO; methyl iodide vapour is lower
  than elemental — both surfaced as honesty caveats, not folded by default.

A tracked nuclide absent from the shipped set makes a committed-dose estimate a **LOWER BOUND**,
surfaced loudly by the engine (§11). The actinide expansion is now **complete** (the Th/Pa
remainder landed this batch). Noble gases (Kr/Xe/Rn/…) have **no intake coefficient** (Annex C
is submersion dose *rate*, a different quantity) — the engine treats them as a distinct "N/A"
state, not a gap.
