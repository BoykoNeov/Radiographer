# M13 — Internal / committed dose (ICRP dose coefficients, Sv/Bq)

**Status:** in progress 🚧 — **data layer + engine landed** (micro-slice green); bridge + bulk
nuclides + UI pending. Done so far: ICRP-119 vendored + PROVENANCE; `build_internal_dose.py`
(both populations, 5 clean-particulate actinides) with the two cross-table transcription checks
enforced at build time; `engine/internal_dose.py` (loader + `InternalDoseModel`, three coverage
states); `tests/test_internal_dose.py` (26 tests, green); `DATA_DIRS` + data README registered.
**Milestone:** post-v1 extension — the single biggest unbuilt capability listed *Future* in
HANDOFF_PLAN §2 ("Internal / committed dose (ICRP dose coefficients in Sv/Bq)") and §11. The
tool has been **external-dose only**; this adds the **intake** pathway. User-chosen next batch
after M12.

## Goal

Given a solved inventory, compute the **committed effective dose E(50)** (Sv) that would result
from **intaking that inventory** by **ingestion** or **inhalation** at a chosen reference time,
folding per-nuclide ICRP dose coefficients (Sv/Bq) against the activity vector. "Done" = a new
internal-dose panel shows E(50) over the time grid for both routes and both populations, the
per-nuclide breakdown, coverage gaps surfaced loudly, an honesty block, and it's validated
end-to-end (dev + built gates) with a regression suite that lands with the data.

## The architecture fit — clean reuse of "solve once, evaluate many" (§3)

Committed effective dose from intaking the whole inventory at time `t`:

    E50(t) = Σ_nuclides  e_n[Sv/Bq] · A_n(t)            (Sv, a SCALAR per intake-time)

`e_n` is the per-nuclide committed-effective-dose coefficient for the chosen **route**
(ingestion / inhalation) and **population** (public-adult / worker). It depends on neither
distance, time, nor activity — so the time grid is a single matvec of the fixed `e_n` against
the activity series from `inventory.SolvedInventory.evaluate`, exactly like `GammaDoseModel`
(`engine/dose.py`). **No distance, no 1/4πd², no geometry.** Only a route/population change
re-folds `e_n`.

This mirrors `dose.py`'s `C_n` coefficient pattern; the bridge function mirrors `dose()`'s
series-over-grid + cursor-index shape, minus `distance_m`.

## The progeny convention — the one correctness trap (LOCKED)

ICRP-119/72/68 **base per-nuclide coefficients are "parent-only with in-vivo ingrowth"**: the
coefficient for nuclide *j* is the committed dose from intaking pure *j*, **including** dose from
*j*'s progeny ingrown **in the body** after intake. (Confirmed: ICRP-119 coefficients "do
contain a contribution from the ingrowth of radioactive progeny once ingested or inhaled";
guidance is to add separately-present progeny's own dose to the head-of-chain parent's.)

**Therefore summing `Σ e_n·A_n(t)` over the FULL tracked inventory is correct and does NOT
double-count** — the in-can progeny (already present at intake, an `A_n(t)` of its own) and the
in-body-ingrown progeny (folded into the parent's `e_n`) are physically distinct atom
populations. Cs-137(→Ba-137m) and Sr-90(→Y-90) are the first nuclides a tester hits; the math is
correct *iff* we ship the **base per-nuclide coefficients, not the equilibrium "+" entries**
(`Cs-137+`, `Sr-90+`), which pre-bundle progeny and WOULD double-count against our separately
tracked progeny activities.

**Build rule:** ingest only the individual-radionuclide rows from ICRP-119; never the "+" rows.
A regression test asserts the Cs-137 / Sr-90 coefficients are the parent-only values, not the
bundled ones.

## Scope (LOCKED for v1)

- **Routes:** ingestion **and** inhalation.
- **Populations:** **both, selectable** — **public adult (ICRP-72**, 1 µm AMAD ingestion/inhalation)
  and **worker (ICRP-68**, 5 µm AMAD). User toggles. (User decision, 2026-06-20.)
- **Inhalation absorption type:** capture **all tabulated F/M/S** values per nuclide (≈0 marginal
  cost while reading the page) plus a **`default_type`**. The fold uses `default_type`; the UI can
  toggle. **`default_type` = the ICRP-recommended / commonly-cited type, fixed by which value
  matches the independent validation source** — NOT a max()/"most restrictive" pick (that would
  disagree with every reference *and* make the validation triangle meaningless) and NOT picked from
  memory. (Advisor, 2026-06-20.)
- **Noble gases (Kr-85, Kr-81, Xe, Rn, Ar):** there is **no Sv/Bq intake coefficient** — ICRP-119
  Annex C gives *submersion effective-dose **rates*** for inert gases, a different quantity. These
  get a **third coverage state `intake_pathway: "none_noble_gas"`**, DISTINCT from "covered" and
  from "uncovered/undercount", so they never inflate the lower-bound flag (folding them as
  "uncovered" would falsely imply a missing intake dose that physically doesn't exist).
- **Ingestion f1:** ship ICRP's default/recommended f1 per nuclide; record it.
- **Nuclide set:** a **curated MVP set** (not all ~800), aligned to the radiologically dominant
  internal-dose contributors in the prebuilt sources + standard teaching nuclides. Extensible
  exactly like spent-fuel's `GRID_POINTS` — add a row, rebuild. Must-cover (from the spent-fuel
  + fallout vectors): Cs-137, Cs-134, Sr-90, I-131, I-129, H-3, Co-60, Tc-99, Ru-106, Ce-144,
  Eu-154/155, Pm-147, Sb-125, Sn-126, Se-79, Kr-85, Pu-238/239/240/241/242, Am-241/243,
  Cm-242/243/244/245/246, Np-237, U-234/235/236/238, Th-228/230/232, Pa-231, Ra-226, Pb-210,
  Po-210. (~50 nuclides.)
- **Age groups other than adult** (infant→15 y) and **non-default absorption types/f1** are
  explicit extensions — out of v1.

## Quantity / time semantics — differs from every existing dose panel (LOCKED)

- It is a **committed scalar in Sv (E(50))**, NOT a rate. The "series over the time grid" reads
  *"committed effective dose if the inventory were intaken at time t"* — a curve in **Sv, not
  Sv/s**. UI labels must say so.
- **Accumulate / integrate is DISABLED** for this panel — there is no rate to integrate over an
  exposure duration. (Contrast the external panels, which integrate a Sv/s rate.)
- E(50) is **effective Sv** but **NOT comparable** to external H\*(10) (Sv) or air-kerma (Gy) —
  same never-summed discipline already enforced for the external quantities (§6.4, §11). Different
  quantity, different scenario (a hypothetical intake vs an external field).

## Data sourcing (the critical path)

- **Primary:** **ICRP Publication 119** (Compendium of Dose Coefficients based on ICRP-60),
  freely downloadable from icrp.org — it consolidates the **ICRP-68 (worker)** and **ICRP-72
  (public)** committed-effective-dose coefficients we need, both routes, in one place. Vendor to
  `data/vendor/icrp119/PROVENANCE.md`. (Repo is already ICRP-107 non-commercial-bound, so adding
  ICRP-derived coefficients does not worsen the license position — see memory
  `icrp107-data-license-constraint`.)
- **Independent validation source (the "triangle"):** **IAEA GSR Part 3** Schedule III (free,
  authoritative, reproduces the ICRP-72 public values) and/or another independent compilation.
  Pick ~5 anchor nuclides (e.g. Cs-137, Sr-90, I-131, Pu-239, H-3) spanning routes/populations and
  cross-check the loaded values against the independent source to ±rounding. **No hand-asserted
  values from memory** (the §12 trap; advisor).
- **Read-time integrity** (the §12 / M12 trap): if extracting from rendered PDF tables, cross-check
  row pairing (e.g. against a known quantity) and record the check in PROVENANCE.md.

## Data schema (firm)

One file per population, `data/internal_dose/<population>.json` (mirrors the `conversion/`
file-per-variant style; coefficients are tiny scalars so a per-population table beats per-nuclide
files):

```jsonc
// data/internal_dose/public_adult.json   (and worker.json)
{
  "schema_version": 1,
  "population": "public_adult",          // | "worker"
  "icrp_publication": "ICRP-72",         // | "ICRP-68"
  "age": "adult",
  "amad_um": 1.0,                        // 5.0 for worker
  "units": "Sv_per_Bq",
  "progeny_convention": "parent_only_in_vivo_ingrowth",  // NOT "+"-bundled
  "source_ref": "...",
  "coefficients": {
    "Cs-137": {
      "ingestion":  { "e_Sv_Bq": 1.3e-08, "f1": 1.0 },
      "inhalation": { "default_type": "F",
                      "types": { "F": 4.6e-09, "M": 9.7e-09 } }   // f1 per type in Annex E (deferred)
    },
    // noble gases carry NO entry — the engine recognizes them by element set (see below)
  }
}
```

**Three coverage states, all explicit (no silent zero):** (a) **covered** — has the route's
sub-object; (b) **noble-gas N/A** — physically has no intake coefficient; *the engine detects these
by element set* (He/Ne/Ar/Kr/Xe/Rn) rather than a data-file entry, so noble gases simply carry no
coefficient and are excluded WITHOUT counting toward the lower-bound flag; (c) **uncovered** — a
tracked nuclide simply absent from the curated set, which DOES make the result a lower bound (loud).

## Engine — `engine/internal_dose.py`

- `InternalDoseError` (loud; never swallowed).
- `set_data_root` / `data_root` / `load(population)` / `has(population)` — loader mirroring
  `engine/conversion.py` (schema-version + embedded-field validation).
- `coefficient(nuclide, route, population) -> float` (Sv/Bq) — raises if the nuclide/route is
  absent (caller decides policy; the model collects rather than crashes — see below).
- `InternalDoseModel(route, population)` assembling the fixed `e_n` vector and:
  - `committed_dose_series(activities) -> {unit:"Sv", quantity:"committed_effective_E50",
    rate_series:[...Sv...], covered:[...], uncovered:[...], warnings:[...]}` — the matvec.
    **`uncovered`** = tracked nuclides with nonzero activity but no coefficient for this
    route/population; carried out prominently because a missing coefficient **underestimates**
    committed dose (the dangerous direction → honesty register). The returned number is then a
    **lower bound** flagged as such, mirroring the spent-fuel lower-bound pattern.
  - a per-nuclide breakdown for the cursor index (mirrors `dose_lines`).

**No silent errors:** an uncovered nuclide is a loud warning + an explicit lower-bound flag, never
a silent skip. A malformed/missing file raises.

## Bridge — `internal_dose(handle, request_json)`

Request: `{ route: "ingestion"|"inhalation", population: "public_adult"|"worker", grid... }`.
Returns the committed-E series (Sv) over the curve grid + cursor breakdown + `uncovered` +
warnings + the absorption-type/f1 provenance for the contributing nuclides. Same DoseOk-ish shape
as `dose()` minus `distance_m`, so the JS cursor/stacked-bar plumbing reuses cleanly.

## UI — new internal-dose panel

- Route selector (Ingestion / Inhalation), Population selector (Public adult / Worker).
- Headline: **committed E(50)** in **Sv** at the cursor time, labelled *"if {inhaled|ingested} at
  t = …"*. Curve in **Sv** (not Sv/s). Per-nuclide breakdown (top contributors).
- Shows the inhalation **absorption type** + ingestion **f1** in play (provenance, not buried).
- **Accumulate/integrate control hidden/disabled** for this panel.
- **Honesty block:** hypothetical reference-person intake; ICRP reference biokinetics; the 50-yr
  integration is **baked into the coefficient**; NOT comparable to external H\*(10)/air-kerma;
  **lower bound** when `uncovered` is non-empty (lists the uncovered nuclides + their activity
  share). Population/route/AMAD stated.

## Honesty register additions (§11)

- Committed dose is a **scenario** (a hypothetical intake of the whole inventory), not a measured
  field — state it.
- Coefficients are **reference-person, age-adult**, single default absorption type / f1 — real
  intakes vary by chemical form, particle size, individual.
- **Coverage is partial** (curated nuclide set) → uncovered tracked nuclides make the number a
  **lower bound**, surfaced per-calculation.
- Never summed with external quantities.

## Build / validation order (datasets-first, TDD)

1. `docs/plans/M13-internal-dose.md` (this file). ✅
2. **Micro-slice (green the whole pipeline first, advisor):** ~4 **clean-particulate** nuclides —
   the **actinide cluster** Pu-239, Am-241, U-238, Po-210, Ra-226 (worker Annex A pp.54–58, public
   ingestion Annex F pp.86–87, public inhalation Annex G pp.115–119). Visual-read each page once,
   transcribing every target nuclide on it. Build schema→build→loader→fold→tests green on these.
3. `data/vendor/icrp119/PROVENANCE.md` (read-time integrity notes) + **validate anchors against a
   DIFFERENT-units source** (Argonne/EPA fact sheet, mrem/pCi → Sv/Bq) to catch transcription slips;
   this fixes each nuclide's `default_type` (the type whose value matches). The triangle checks
   **transcription fidelity, not methodology** — ICRP is the sole methodology source.
4. `engine/internal_dose.py` + `tests/test_internal_dose.py` (schema, anchors, parent-only progeny
   assertion, three coverage states incl. noble-gas N/A, fold reconciliation Σ==series).
5. **Bulk transcribe** the rest of the curated set into the now-test-guarded schema: the other
   fission products (Cs-137, Sr-90, Co-60, Tc-99, Ru-106, Ce-144, …) and remaining actinides.
6. Bridge `internal_dose()` + bridge test.
7. **Gases/vapours (deferred special-casing):** H-3 (OBT/HTO, Annex B inhalation), I-131
   (elemental/methyl-iodide vapour, Annexes B/H), as a labeled refinement — NOT in the first slices.
8. UI panel + honesty block; dev + built gate green.
9. Serializer bump only if the panel state is persisted (decide at UI step).

## Open / deferred

- Public age groups (infant→15 y), non-default absorption types & f1 values — extensions.
- Full ~800-nuclide ICRP-119 coverage (machine-readable via ORNL Radiological Toolbox DB) —
  deferred; curated set + loud coverage gaps is the v1 contract.
- Inhalation of **gases/vapours** (special ICRP treatment) — out of v1.
