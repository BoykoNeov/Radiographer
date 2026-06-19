# M7 — Prebuilt sources + teaching demos + chart-of-nuclides

**Status:** M7a + M7b + **M7c done** ✅; **M7d done** ✅ (parts 1–4, gate green dev + built).
All §8/§13 #5 sources shipped — **nothing left sourcing-gated**. Every source is CITED + validated
(no fabrication): the §11 "cite or defer, never reconstruct" discipline held throughout, and
even fallout — which the user authorized to build on speculative data — landed on a clean cited
ENDF source rather than the speculative fallback.

**M7d (parts 1–3) — DONE.** Three commits, gate green:
- *Part 1 — weapons-grade Pu pit* (`sources.ts`): an α/γ inventory (~93.5% Pu-239 / 6% Pu-240
  / 0.5% Pu-241, 4 kg), the §13 #5 piece that ships regardless. Treated like `fresh-fuel` (a
  UI manifest, no regression test). Teaching: external ≠ internal; in-growing Am-241 (59.5 keV
  γ) from Pu-241. Pu-240 SF-neutron output is a LOUD card caveat (external underestimate), never
  silently modelled — mirrors the M7c spent-fuel-neutron defer.
- *Part 2 — AmBe (α,n) source* (`data/neutron_sources/AmBe.json` + `build_ambe()`): the M5-deferred
  source, now SOURCED. Spectrum = IAEA TRS-403 (2001) Table 4.V ISO 8529 Am–Be column (open
  access, CITED not reconstructed); folds to h̄ = 393.6 pSv·cm² vs the standard's published
  H*(10) = 391 (+0.66%), cross-validated by folding the table's own Cf-252 column (378 vs 385)
  the same way. neutrons_per_decay = 2.2e6 n/s/Ci → 5.95e-5 (the one construction-dependent
  number, ±15% caveat). 4.438 MeV reaction γ at R=0.575 (Liu et al.). **Crux (advisor):** bin
  edges are geometric midpoints between tabulated points (geomean = E_i) so bins don't OVERLAP
  — a naïve E_i·r^±½ on the 10/decade grid stores overlapping bins that still sum to 1 and fold
  correctly (a silent data-integrity trap). **source_gamma is the first non-empty path** (Cf-252
  ships []): the 4.438 MeV line flows engine→bridge→UI, rendered as a γ-card sub-line + its own
  stacked-bar segment summing into the Sv total.
- *Part 3 — honesty surfacing*: a "Prebuilt source catalog (M7)" register group (pit SF-neutron
  defer, AmBe provenance/yield-caveat, fallout caveats).
- *Part 4 — bomb fallout* (`data/fallout/u235_fission_fallout.json` + `build_fallout.py`,
  `engine/fallout.py`): the §13 #5 second half. **ENDF/B-VIII.0 U-235 thermal CUMULATIVE
  fission yields** (MF=8/MT=459), vendored from NNDC (`data/vendor/endf_nfy/`, SHA in
  PROVENANCE.md) — a CITED table, not the authorized speculative fallback. 177 nuclides
  (cumulative yield ≥ 1e-3/fission). **Validation (honesty anchor):** seeded + decayed through
  the Bateman engine, the gross-γ source strength follows the **Way–Wigner t⁻¹·² (7:10) law to
  −1.22** over H+1 h…30 d (regression test); dominant yields match textbook ENDF (Cs-137 6.19%,
  I-131 2.89%, …). **Why cumulative not independent (crux):** independent yields sit on sub-second
  precursors absent from ICRP-107 → drop ~69% of fragments + underfeed long-lived γ emitters;
  cumulative ≈ the H+1 h chain-fed inventory (double-counts within chains — a shape-preserving
  approximation, so the 7:10 DECAY is meaningful, absolute level approximate, t<H+1 h unreliable).
  Thermal U-235 is a representative mix (real weapon = fast U/Pu); all caveated. Wiring mirrors
  M7c: `bridge.fallout_catalog()` → `appState.falloutSources` → picker (Weapons-material group,
  beside the pit); `data/fallout` added to the build-archive bundle.

**Advisor note (process):** I first deferred fallout after only a *local* data check; the advisor
pushed back — the user said "build it" and I'd skipped the web-sourcing I gave AmBe. The redo
found ENDF/B-VIII.0 yields cleanly. Lesson: give every gated piece the same sourcing effort
before concluding "defer".

**M7c (spent fuel + decay heat) — DONE.** Three commits, gate green:
- *Part 1 — decay-heat engine* (`engine/decay_heat.py`): W(t) = Σ A_n·Ē_rec,n, recoverable
  energy from the bundled ICRP-107 spectra (no new dataset); α-recoil Q_α = E_α·A/(A−4);
  discrete-β path only (no double-count). Anchored to FETCHED published specific powers
  (Pu-238 0.567 W/g = the recoil discriminator; Po-210; Co-60). Bridge `decay_heat`.
- *Part 2 — discharge vectors* (`data/spent_fuel/*.json`, §13 #4 RESOLVED): CC-BY SCK-CEN
  Serpent2 PWR UOX library (Mendeley DOI 10.17632/shv89y2zzd), shipped at 45 & 20 GWd/tHM
  @4.0%. The §11 no-fabrication discipline met with a *citable, machine-readable* source,
  NOT memory. **Basis pivot (the crux):** the dataset's `_A` activity column carries a fixed
  ~0.535 geometry factor on a different volume basis than the mass-density column, so activity
  is derived as λN from the mass-density (atom-inventory) columns. Doubly validated — Cs-137
  matches a from-scratch fission-yield estimate to ~5%, and the inferred HM density 8.88 g/cm³
  = U-in-UO₂. `build_spent_fuel.py` streams the gitignored 370 MB CSV; regression suite
  re-derives every anchor from the committed JSON.
- *Part 3 — UI wiring*: `engine/spent_fuel.py` + `bridge.spent_fuel_catalog()` turn the
  vectors into §8 picker sources (inventory from `data/`, loaded `unit="g"`, at discharge);
  `DecayHeat.svelte` readout (live at the cursor); Honesty.svelte + §11 carry the spent-fuel
  provenance/basis, the short-cooling underestimate, and the spent-fuel-neutron defer.
  Default cursor homes to ~2.7 yr cooling (4.9 kW/tHM) — sane, past the <1-day incomplete regime.

**Explicit M7c defer:** spent-fuel *neutron* output (SF + (α,n), Cm-244) — the dataset carries
`_SF`/`_AN`, but v1 models only γ/β/decay-heat for spent fuel (a future hook).
**Milestone (HANDOFF_PLAN.md §10, §8):** the curated **prebuilt source catalog** —
named inventories (+ optional tabulated neutron term) each with a one-line "what it
teaches" — plus the teaching demos that fall out of §5 (secular / transient
equilibrium). **Chart-of-nuclides is NOT in this milestone — it already shipped in
M6e** (Cytoscape dagre + (N,Z) preset); the only M6e→M7 tie-in is the SF pseudo-sink
visual, which lands the moment a spontaneous-fission source (Cf-252, spent fuel) is
loadable.

## Goal

"Done" = a user can load any catalog source with one click — the inventory, the
reference time, and (for neutron sources) the neutron term are populated — every
existing view (curves, DAG, dose, shield) lights up live off the one Bateman solve,
and the **neutron dose path is wired end-to-end** (no longer grayed) for prebuilt
neutron sources. Each source carries a teaching blurb; the §5 equilibrium demos land
with a default time-range that actually *shows* the equilibrium.

**Validation through the UI (the M6 analogue of a per-dataset regression test):** the
headless driver asserts a **Cf-252 neutron-dose number through the rendered path**
(anchor: the M5 validation triangle, h̄ ≈ 373 / fold 383 pSv·cm²), and that loading a
preset populates the inventory + solves.

## The risk split — sequence by sourcing risk, NOT by §8 list order (advisor)

§8 mixes two very different kinds of work. Build the locked low-risk core first; do
**not** start the sourcing-gated chunks until citable data is in hand.

### Locked / low-risk (build now — no user decision needed)
- **M7a — Catalog infra + simple inventory-only presets.** ✅ DONE. `sources.ts`
  (typed manifest: Co-60, Cs-137, Mo-99/Tc-99m, K-40 banana, Am-241 smoke detector,
  Radium dial, fresh LEU fuel — + Cf-252 used by M7b); `Sources.svelte` picker
  (category cards, blurbs, caveats); `appState.neutronSource` + `loadSource()` +
  orphan guard (hand-edits drop the source key). Mounted above the inventory panel.
- **M7b — Neutron dose wiring + Cf-252 as a loadable source.** ✅ DONE. All 5 touch
  points landed; gate green dev + built. Cf-252 H\*(10) renders **383.18 pSv·cm²** —
  the M5 validated-triangle value — through the rendered card path.

### Sourcing-gated (do NOT start until data is sourced or the user defers)
- **M7c — Spent fuel (parameterized, §8 / §13 #4).** Discharge vectors per
  (enrichment, burnup) are **published ORIGEN/SCALE inventory vectors** — dozens of
  nuclides with specific activities. **This is M7's AmBe/Cross-Berger:**
  reconstructing a discharge vector from memory fabricates physics data into a tool
  people may trust, invisibly. **Source it from a citable table (with a regression
  test the moment it lands, §7) or defer — never reconstruct.** Decay-heat (W, §5)
  ties in here and is currently unbuilt.
- **M7d — Bomb fragment (§13 #5) + AmBe + final polish.** The Pu/U **pit** half of #5
  is trivial (an α-emitter inventory) and can ship regardless; the **fallout** vector
  (7:10 rule) needs a real fission-product mix → same sourcing discipline as M7c.
  AmBe stays deferred from M5 until a clean ISO 8529-1 spectrum is sourced. Final
  honesty-register surfacing for the catalog lands here.

**User scope decision (tee'd up before M7c/M7d, NOT blocking the core):** which of
spent-fuel-vectors / fallout / AmBe to attempt now vs defer to post-v1.

## M7b — neutron-wiring touch points (enumerated so none drops)

The engine + bridge + JS client method (`bridge.ts:neutron_dose`) **all already
exist** (M5). M7b is pure wiring:

1. **Inventory model gains a neutron `source` key** (`neutronSource: string | null`
   in app state). A preset load sets entries *and* the source key. The §6.3 gray-out
   gate is `neutronSource != null`.
2. **`recomputeDose()`** calls `neutron_dose(handle, {source, quantity, distance_m,
   geometry})` when a source is set → `neutronDoseSeries`; add `neutronRateAtCursor`
   / `neutronAccumulated` getters — the same solve-once / cursor-index pattern as γ.
3. **Dose.svelte** un-grays the neutron card (currently a placeholder with the
   "arrives in M7" note).
4. **Persist → v3** (additive `neutronSource`, validated in the deserializer,
   round-trip asserts identical *views* — the exact M6h pattern).
5. **Driver assertion** — a Cf-252 neutron-dose number through the rendered path.

### Two correctness flags on M7b
- **γ + n CAN sum** (both Sv, same H\*(10)/effective quantity) → they go in the same
  stacked-bar total. **β cannot** (Gy, Hp(0.07)) → stays its own panel (the §6.2 /
  invariant-#5 lock is about γ-vs-β, not γ-vs-n). The honesty caveat on n is only
  about table *vintage* (ICRP-74 n vs ICRP-116 photon effective), not the quantity.
- **Orphaned source key = a no-silent-error edge.** If the user removes Cf-252 from
  the inventory while `neutronSource="Cf-252"`, `neutron_dose` raises (parent
  missing). Gate the neutron getter on "parent still in the solve closure" (or clear
  the key on inventory edits) — never let it surface as a generic dose error or a
  blank card.

## Key files & decisions
- **Catalog manifest** = a typed TS constant in `web/src/lib` (e.g.
  `sources.ts`) — preset id, label, blurb, inventory spec, optional `neutronSource`,
  default time-range/distance. Cite the preset *quantities* (1 GBq Co-60, the
  K-40-in-a-banana figure) in comments though they're not regression-grade. **Physics
  numbers stay in validated `data/`** (the neutron terms already there; any discharge
  vectors land there with a test — §7).
- A **source-picker UI** (in `Inventory.svelte` or a small `Sources.svelte`) that
  loads a preset into the store (entries + reference time + neutron source key).
- Teaching demos ≈ the presets with framing: Cs-137 secular (→ Ba-137m) and
  Mo-99/Tc-99m transient equilibrium land with a default time-range that shows it.
- **Radium dial** models *closed* Rn-222 (real dials leak radon) — a one-line
  teaching caveat, not a code change.

## Explicit defers (NOT silent omissions, §11)
- **Decay heat (W)** — §5-optional, tied to spent-fuel cooling (M7c); unbuilt in v1.
- **Spent-fuel vectors / fallout vector / AmBe** — pending the user scope decision +
  citable data (see the risk split).

## Open questions / risks
- §13 **#4** (spent-fuel enrichment/burnup grid) and **#5** (bomb-fragment pit +
  fallout) remain OPEN — gated on data sourcing + the user scope decision.
- First-load caching (service worker) was deferred from M6h → still post-v1.
