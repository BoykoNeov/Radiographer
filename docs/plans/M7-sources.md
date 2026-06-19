# M7 — Prebuilt sources + teaching demos + chart-of-nuclides

**Status:** M7a + M7b done ✅ (gate green dev + built); M7c/M7d sourcing-gated, pending
the user scope decision + citable data. The Pu/U **pit** (trivial α inventory) is
ready to drop into the catalog whenever #5 is confirmed.
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
