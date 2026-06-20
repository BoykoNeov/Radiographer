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

1. **Ingestion f1-ratio.** Worker (Annex A) and public-adult (Annex F) ingestion use the same
   biokinetics, so `e_public / e_worker == f1_public / f1_worker`. Po-210 (worker f1 0.1 →
   public f1 0.5) reconciles to **exactly 5×**; matched-f1 actinides → 1×.
2. **Inhalation worker-1µm ↔ public-adult-1µm**, for **every shipped absorption type** (not
   just the default). Annex A's 1 µm column must agree with Annex G's public-adult 1 µm value to
   ~40 % (same HRTM lung model, ~same reference person). A public type with **no** worker
   counterpart is REFUSED by the build — so no uncross-checked value can ship. Public types
   lacking a worker analog (Po-210 S, Ra-226 F/S, Am-241 F/S) and the **suspect Pu-239 F** (read
   `1.6E-05` == its own S value, breaking 15y→adult monotonicity — a mis-column) were **dropped**;
   they will be crop-read in the later UI absorption-type batch. Result: the public file ships
   only types validated against the worker column (public inhalation types ⊆ worker types).

**Errors these checks actually caught** (recorded for honesty):
- **Am-241** public-adult Type-M adult misread as `9.6E-05` (that is the *F*-row value) →
  corrected to **`4.2E-05`** via a 300-DPI crop (worker M 1 µm = 3.9E-05 confirms).
- **U-238** worker 5 µm M/S first captured from the **1 µm** column (`2.6E-06`/`5.7E-06`) →
  corrected to the 5 µm values **`1.6E-06`/`6.3E-06`** (the worker table has both columns
  adjacent — easy to cross).
- **Po-210** worker-1µm default cross-check value first taken from the F row (`6.0E-07`) →
  corrected to the M row **`3.0E-06`** (matches public M `3.3E-06`).

**Trust boundary (honesty):** these checks prove **transcription fidelity**, not methodology —
ICRP-119 is the sole methodology source, so true methodological independence is not on the
table (the once-considered ANL/Argonne fact sheets publish *lifetime cancer-risk* coefficients,
a different quantity, not e(50), so they cannot validate the dose values).

## Coverage

A **curated slice** (the M13 micro-slice: Po-210, Ra-226, U-238, Pu-239, Am-241 — clean
particulates), extensible like spent-fuel's `GRID_POINTS`. A tracked nuclide absent from the
shipped set makes a committed-dose estimate a **LOWER BOUND**, surfaced loudly by the engine
(§11). Noble gases (Kr/Xe/Rn/…) have **no intake coefficient** (Annex C is submersion dose
*rate*, a different quantity) — the engine treats them as a distinct "N/A" state, not a gap.
