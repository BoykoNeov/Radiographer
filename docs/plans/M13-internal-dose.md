# M13 — Internal / committed dose (ICRP dose coefficients, Sv/Bq)

**Status:** ✅ **COMPLETE** — data layer + engine + bridge + all particulate batches + gas/vapour
(schema v2) + **UI panel (step 8)** all landed; dev + built gates green. Done so far: ICRP-119 vendored + PROVENANCE;
`build_internal_dose.py` (both populations) with the cross-table transcription checks enforced at
build time (ingestion **equal-f1⇒equal-e** + `DIFFERING_F1_INGESTION` exceptions; inhalation
worker-1µm↔public-1µm per shipped type; gas/vapour `_validate_gas_vapour`); `engine/internal_dose.py`
(loader + `InternalDoseModel`, three coverage states, f1/form/per-nuclide-coeff provenance);
**bridge `internal_dose()`**; `tests/test_internal_dose.py` + bridge tests, green; `DATA_DIRS` +
data README registered.
**Coverage = 40 nuclides (schema v2):** 5 micro-slice actinides (all F/M/S) + 8 fission/activation
products (default type only) + **actinide-expansion core: U-234/235/236, Np-237, Pu-238/240/241/242,
Am-243, Cm-242/243/244/245/246** (all cross-checkable types) + **actinide remainder: Th-228/230/232,
Pa-231** (Type M & S; default M) + **non-actinide expansion: Pb-210, Sb-125, Sn-126, Pm-147,
Eu-154/155** (default type only) + **gas/vapour: H-3 (HTO/OBT), I-129, I-131 (elemental/methyl
vapour)**. A pre-existing U-238 worker-5µm-S transcription error was found and fixed; the
non-actinide batch corrected the **Po-210 default type M → F** (Annex E catch-all); the Th/Pa batch
caught a Pa-231 worker-5µm-S full-page miscount (Pa-230's row). **The actinide expansion is now
complete.** **Still open:** the **UI panel** (step 8) — the last M13 piece.
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
- **Inhalation absorption type** *(LOCKED scope revised 2026-06-20 — see note)*: each nuclide
  ships a **`default_type`** and the fold uses it. **`default_type` = the ICRP "unspecified /
  all-other-compounds" catch-all per element**, read from **ICRP-119 Annex E (Table E.1)** — NOT
  a max()/"most restrictive" pick and NOT from memory. (The earlier "match the validation source"
  rule was unworkable: ICRP publishes several values per nuclide conditioned on chemical form, so
  there is no single value to match — the catch-all designation is the principled discriminator.
  Advisor, 2026-06-20.)
  - **Revision to "capture all F/M/S":** the original LOCKED rule (capture every F/M/S type,
    "≈0 marginal cost while reading the page") held for the 5 actinides but its premise is **false
    on the public side** — Annex G is a dense multi-age table that needs per-type 300-DPI crops
    (a full-page read miscounts adjacent columns; caught a Co-60 silent slip), and the E/A/G f1
    reads conflict on non-default types. More decisively: **v1 folds only the default type** (the
    bridge passes `absorption_type=None`; no UI toggle), so a non-default value would be shipped
    but never folded — an unvalidated number for zero benefit (honesty register). **Decision:**
    actinides keep all F/M/S; the **fission-product batch ships the default type only**;
    non-default capture moves to the deferred type-toggle extension (where the correct shape is a
    per-nuclide `{nuclide: type}` map, not a global scalar).
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
5. **Bulk transcribe** the rest of the curated set into the now-test-guarded schema.
   - ✅ **Fission-product batch** (default-type only): Co-60, Se-79, Sr-90, Tc-99, Ru-106,
     Cs-134, Cs-137, Ce-144. Worker (Annex A 5µm+1µm+ingestion), public (Annex F ingestion +
     Annex G inhalation 1µm, crop-read), Annex E default types. All cross-checks pass.
   - 🚧 **Actinide expansion batch** (all *cross-checkable* tabulated types per the user, so the
     data is extension-ready for the per-nuclide absorption-type toggle). **Decision (user,
     2026-06-20):** also **re-crop-verify the already-shipped worker 5 µm column** — it is the one
     column the build's inhalation cross-check never touches (the check validates the **1 µm**
     column; the worker *ships* 5 µm), so it is the soft spot. This surfaced a real pre-existing
     bug: **U-238 worker 5 µm S was `6.3E-06` (U-236's value); corrected to `5.7E-06`** (commit
     e10a5a6), and its regression golden + the PROVENANCE "errors caught" note were fixed.
     - ✅ **Done & committed (27 nuclides):** U-234/235/236 (+ U-238 S fix), Np-237,
       Pu-238/240/241/242, Am-243, Cm-242/243/244/245/246. Per-element only types tabulated in
       **both** Annex A (worker) and Annex G (public) ship: worker **Np/Am/Cm = M only**, worker
       **Pu = M & S (no F)**. Re-verified existing micro-slice **Ra-226, Pu-239, Am-241** correct.
     - ✅ **Thorium + Protactinium DONE (40 nuclides).** Th-228/230/232, Pa-231 — **Type M & S**,
       default M. **Annex E** catch-all for both Th and Pa = **Type M, f1 5E-04** ("unspecified
       compounds"; Type-S oxides f1 2E-04). Worker (Annex A printed p.53/54, **5 µm crop-read
       twice**), public ingestion (Annex F PDF p.86, Adult, f1 0.0005 == worker → equal-f1 holds),
       public inhalation (Annex G PDF p.116/117, 1 µm Adult — Type F dropped, no worker counterpart).
       **Dual thorium f1 resolved:** the 0.0002 the table lists per nuclide is the Type-S oxide
       ingestion route, NOT the default → ship the f1 5E-04 value, no `DIFFERING_F1_INGESTION`
       entry. **Crop-verification caught a real bug:** the full-page Pa-231 S read (5.7E-07/7.1E-07)
       was **Pa-230's** S row; the true Pa-231 S 5µm = 1.7E-05 (1µm 3.2E-05). All M & S cross-check
       vs worker 1 µm at 1.06–1.09×; equal-f1 ingestion ≤4.5%. Shipped worker ing: Th-228 7.2E-08,
       Th-230 2.1E-07, Th-232 2.2E-07, Pa-231 7.1E-07. Tests: `ACTINIDE_REMAINDER` group +
       `test_thorium_dual_f1_resolves_to_annex_e_default` + `test_thorium_protactinium_ship_M_and_S`.
     - ✅ **Non-actinide expansion DONE (33 nuclides total):** Pb-210, Sb-125, Sn-126, Pm-147,
       Eu-154/155 — **default type only** (Annex E: Pb F, Sb F, Sn F, Pm M, Eu M), both
       populations, worker 5 µm crop-read **twice**. All build cross-checks pass (every nuclide
       shares worker↔public ingestion f1 → equal-e holds; Pb-210 adult f1 = 0.2 via Annex F
       footnote). **Re-verified** the 8 fission-product + Po-210 worker 5 µm defaults — all
       transcription-correct. **Po-210 `default_type` corrected M → F** (ICRP-119 Annex E lists
       Polonium "Unspecified compounds" = Type F; the micro-slice's M violated the LOCKED catch-all
       rule — folds 7.1E-07 worker / 6.0E-07 public now, ~3× lower; user decision 2026-06-20).
6. ✅ Bridge `internal_dose()` + bridge tests (route/population; default-type fold; no global
   absorption_type — F/M/S is per-compound, out of v1 scope).
7. ✅ **Gases/vapours DONE (schema v2 → 36 nuclides):** H-3 (HTO/OBT), I-129, I-131
   (elemental I₂ / methyl CH₃I vapour). **Chemical forms, not F/M/S** — engine inhalation
   validation widened from the global `ABSORPTION_TYPES` tuple to `INHALATION_FORMS`
   (`= F/M/S + HTO/OBT/vapour_elemental/vapour_methyl`); a localized `forms` map added to H-3
   ingestion (HTO vs OBT differ on ingestion too) selected by `ingestion_form`. Inhalation from
   Annex B (worker) / Annex H (public); H-3 ingestion Annex A/F. **Iodine ships vapour-only**
   (locked scope — particulate-F out of scope, so the Annex-E particulate catch-all does not bind
   the vapour default). Defaults: H-3 → HTO, iodine → elemental. New build cross-check
   `_validate_gas_vapour` (worker==public per form, two independently typeset annexes — weaker than
   the differing-AMAD particulate check, stated so). FGR-13 NOT used as external anchor (it
   publishes risk/Bq, not Sv/Bq). Coverage-state tests swapped I-131 → **Zr-95** as the uncovered
   example (I-131 is now covered; Zr-95 is off the roadmap so it stays a real gap). Bridge folds
   the default form unchanged (no new param). All tests green (dev gate). **Scope advisory:** this
   nearly re-ran the Po-210 trap — an earlier draft added iodine particulate-F and would have
   defaulted to vapour while Annex E says iodine-particulate = F; pulling back to vapour-only (the
   locked scope) removed the conflict.
8. ✅ **UI panel + honesty block DONE** (commit pending; dev + built gates green). New
   `web/src/lib/InternalDose.svelte` (mounted in `App.svelte` after the external Dose/Shield
   panels). Mirrors `DecayHeat.svelte` (scalar-series, distance/quantity-free) + `gammaLinesAtCursor`
   (cursor breakdown). Bridge `InternalDoseOk` + `internal_dose()` client (bridge.ts); store
   `internalRoute`/`internalPopulation` (**EPHEMERAL** — not serialized, like the curve axis; the
   panel labels the active scenario) + `recomputeInternalDose()` (recompute on solve + source-age
   + route + population, NEVER the external-dose inputs) + cursor getters
   (`internalCommittedAtCursor`, `internalBreakdownAtCursor`, `internalActiveUncoveredAtCursor`).
   Wired into `solve()` success + `setReferenceTimeS()`; cleared in `clearChain` (covers the
   empty/failed-solve branches). Schema-v2 `internal_dose` JSON rebuilt into the web runtime zip
   (`build-archive.mjs --force`). Gate scene `runM13` (6 checks): committed E(50) > 0 +
   breakdown Σ == headline (interp ∘ matvec reconciliation); route + population toggles RE-FOLD
   (registry stays 1 — never a re-solve, §3); committed is a scalar (no integrate control) +
   honesty block present; active-uncovered → loud lower-bound banner; Cs-137 inverse-hazard case
   (see below). **Cross-validation bonus:** the gate's Cs-137 1 GBq ingestion folds to exactly
   13.0 Sv = 1e9 Bq × 1.3e-8 Sv/Bq — the canonical ICRP-72 coefficient, confirming the fold.

   **Two UI-layer honesty decisions made at this step (the panel intentionally diverges from the
   engine's raw `series.lower_bound`):**
   - **Stable-daughter refinement.** The engine flags EVERY uncovered closure nuclide (it has no
     activity at construction), so a stable end-product (Pb-206 after Po-210, Ba-137 after Cs-137)
     sets `lower_bound=true` even though a stable nuclide has zero activity ⇒ zero possible
     committed dose. Left raw, the loud banner would fire on essentially every chain (all end
     stable) — meaningless noise. The panel drives the banner off
     `internalActiveUncoveredAtCursor` (uncovered nuclides with NONZERO activity at the cursor),
     which is exactly the plan's stated `uncovered` definition ("nonzero activity but no
     coefficient"). A future session seeing `series.lower_bound===true` against a quiet UI banner
     should NOT log it as a bug — the divergence is deliberate.
   - **Activity-share ≠ dose-share (the inverse wrong-but-quiet hazard, advisor-caught on the
     canonical nuclide).** On plain **Cs-137**, the Ba-137m daughter (2.6 min, uncovered) sits in
     secular equilibrium → ~49% activity share → the loud banner fires — yet Ba-137m's committed
     *intake* dose is negligible (it decays before uptake). There is no dose-share available for an
     uncovered nuclide (that's the gap), so the banner keeps the (technically-correct) lower-bound
     flag but a mandatory muted caveat states activity share is NOT dose share and that short-lived
     equilibrium progeny (Ba-137m) contribute negligibly while longer-lived omissions (Y-90, Nb-95)
     matter. A dedicated Cs-137 gate scene asserts both the banner and the caveat render.

   **The honesty block MUST surface these
   default-choice caveats (the engine silently folds ONE form/type — the "wrong-but-quiet" §11
   hazard):**
   - **Co-60** default Type M; oxide is Type S, ~2–3× higher.
   - **H-3** ingestion default HTO; **OBT is ~2.3× higher** (4.2E-11 vs 1.8E-11).
   - **Po-210** default Type **F** (the Annex-E unspecified-compound form); **Type M is ~3× higher**
     (worker 2.2E-6 vs 7.1E-7) and is the value many regulatory tables cite. The M→F switch lowered
     the folded dose ~3× — the *dangerous* direction — so this caveat is mandatory, not optional.
   - **Iodine** inhalation default **elemental vapour**; methyl is ~25% lower, and **particulate
     iodine is NOT modeled** (vapour-only scope) — a user comparing to a particulate textbook value
     (I-131 F adult 7.4E-9, ~2.7× below elemental) must be told.
   Also: hypothetical intake; lower bound when uncovered; never summed with external H*(10).
   **Note:** the schema bump to v2 means the web runtime bundle must be regenerated at THIS step
   (build-archive picks up the new JSON; the bundle currently carries no internal_dose data at all,
   and nothing in `web/src` loads it yet, so there is no stale-v1 crash — pytest is the gate now).
9. Serializer bump only if the panel state is persisted (decide at UI step).

## Open / deferred

- Public age groups (infant→15 y), non-default absorption types/forms & f1 values — extensions.
  (The schema-v2 data already carries OBT and methyl-vapour alternatives + actinide F/M/S, so a
  future per-nuclide type/form toggle has the values; the bridge just folds the default for now.)
- Full ~800-nuclide ICRP-119 coverage (machine-readable via ORNL Radiological Toolbox DB) —
  deferred; curated set + loud coverage gaps is the v1 contract.
- **DONE:** **Th-228/230/232, Pa-231** — the actinide-expansion remainder, landed this batch
  (step 5; Type M & S, Annex E default M, thorium dual-f1 resolved to f1 5E-04).
- **DONE:** inhalation of gases/vapours (H-3, iodine) — landed in schema v2 (step 7).
