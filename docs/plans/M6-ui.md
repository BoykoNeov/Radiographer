# M6 — UI

**Status:** planning
**Milestone (HANDOFF_PLAN.md §10):** Build the JS/HTML rendering + interaction
layer on the proven physics core — chain view, time slider, overlay graphs, dose
calculator, shield builder, save/load. This is the pivot from Python/data to the
browser app; §9 is the UX contract, §3 ("solve once, evaluate many") and §11/§12
(honesty + units) are the invariants the UI must not violate.

## Goal

"Done" = a single-page, fully client-side app that boots Pyodide + the bundled
engine/data, lets a user load an inventory, and drives every §9 view live off
**one** Bateman solve per inventory:

- add/remove isotopes (name + quantity + unit); save/load app state as JSON;
- multi-species overlay curves (Plotly) with the Atoms·Mass·Activity toggle;
- a log time slider (auto-ranged, half-life ticks, numeric entry, definable t=0,
  animate) that scrubs a **cursor** over already-computed curves — never re-solves;
- a live decay-chain DAG (Cytoscape, dagre + (N,Z) layouts) whose node encoding
  tracks slider-time activity, sharing one color per species with the curves;
- a dose calculator: H\*(10) vs effective (+ geometry), live γ/β/n breakdown with
  uncertainty, per-line gamma table, neutron grayed out for user inventories;
- a shield builder: radiation-type-aware materials, dose-vs-thickness / dose-vs-time;
- the honesty register (§11) surfaced in-app, units labelled obsessively (§12).

**Validation through the UI is the analogue of the per-dataset regression test:**
the headless browser driver (extend `web/drive_browser.mjs`) must assert the known
physics benchmarks still hold *through the rendered app path* — Cs-137 secular
equilibrium ratio, a Co-60 air-kerma dose-rate benchmark — not just that pixels
appear. Each chunk lands with its assertion added to the driver.

## Cross-cutting invariants (apply to every chunk)

1. **Solve once, evaluate many (§3) — the load-bearing rule.** A new handle is
   created **only** when the *inventory* changes (isotopes/quantities/units/
   precision/t=0). Distance, shield, geometry, dose quantity, time cursor, axis
   mode, animate frames are all *evaluate*/recompute-coefficient axes — never a
   re-solve. The slider moves a client-side cursor over arrays already returned.
2. **Handle lifecycle.** On any inventory change: solve → swap in the new handle
   → **`release()` the old one** (don't leak `_REGISTRY`). One live handle at a
   time for v1's single-inventory app.
3. **No silent errors extends to the UI (CLAUDE.md, §11).** Bridge responses
   carry `ok:false` errors and `warnings[]` (scoring-floor skips, off-grid, etc.).
   The UI must **surface** both loudly — a failed solve/dose is a visible banner,
   warnings are shown, never swallowed or replaced by a blank chart.
4. **Shared per-species color (§9 LOCKED).** One palette assignment per nuclide,
   owned by app state (M6b), consumed identically by curves, DAG, and dose
   breakdown. Assign on solve; stable across re-solves where the nuclide persists.
5. **Units obsessively labelled (§12).** Gy vs Sv(H\*10) vs Sv(effective) vs
   Hp(0.07); Bq vs Ci; axis labels update with the axis toggle. The γ/β/n
   breakdown labels its quantities and **never sums Hp(0.07) into H\*(10)** (§11).

## Packaging — the M6a unknown, now grounded

Every engine loader resolves data via
`_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "<subdir>"` and
also exposes `set_data_root()`. **Consequence:** mirror the source tree into the
Pyodide FS as `/engine/*.py` + `/data/<subdir>/...` and `__file__` resolution
just works — no loader rewrite, `set_data_root()` is a fallback we likely won't
need. `emissions.available_nuclides()` does `_data_root.glob("*.json")`, so the
**directory tree must be real in the FS** (an in-memory map won't satisfy the glob).

**Runtime payload (measured):**

| dir | files | size | ship to browser? |
|---|---|---|---|
| `data/emissions/` | 1252 | ~48 MB | **yes** (dominant) |
| `data/conversion/` | 14 | ~23 KB | yes |
| `data/attenuation/` | 11 | ~24 KB | yes |
| `data/buildup/` | 8 | ~26 KB | yes |
| `data/neutron_sources/` | 1 | ~9 KB | yes |
| `data/vendor/` | 1281 | ~17 MB | **no — build input** |
| `data/build/` | 6 | ~43 KB | **no — build scripts** |

1252 individual fetches is a non-starter and 48 MB wants compression → **bundle
the runtime data dirs (NOT vendor/build) into one archive, fetch once, unpack via
`pyodide.unpackArchive` into the FS** (gzip/zip handles JSON's high redundancy;
the tree is preserved so the glob works). A small build/copy step assembles the
archive from the five runtime dirs. *Alternative considered:* lazy per-nuclide
emission fetch (only closure nuclides) — smaller first load, but breaks the
glob-based `available_nuclides()` and the "single read path" simplicity; hold as
a later optimization, not v1.

## Plan — chunked (M6a → M6h), dependency-ordered

Each chunk is a separable, committable slice with its own validation gate. Spin
out a `docs/plans/M6<x>-<slug>.md` when that chunk **starts** (don't pre-create —
empty scaffolds rot); this file is the overview/contract for all of them.

### M6a — Bootstrap & packaging  *(foundation; M0-style "kill early")*  ✅ DONE
**See `docs/plans/M6a-bootstrap.md`.** Gate green in a real headless browser (dev
+ built): all benchmarks round-trip, the 1252-file dataset tree mounts, and the
**HP-in-WASM risk is closed** (micropip auto-pulls sympy/mpmath). Stack: Vite +
Svelte 5 + TS; one combined engine+data zip (`fflate`) → `zipfile.extractall("/")`.

Replace the stale M1 smoke harness (`web/index.html` loads only 4 modules, no
data) with the real app shell.
- Load Pyodide (314.0.0; 0.29.4 fallback) + `micropip.install("radioactivedecay")`.
- Assemble + fetch the runtime-data archive; `unpackArchive` into `/data`; write
  all 13 `engine/*.py` into `/engine`; `import engine.bridge`.
- A typed JS **bridge client** wrapping every bridge fn (`solve`, `evaluate`,
  `chain`, `dose`, `beta_dose`, `neutron_dose`, `release`) — JSON in/out, with the
  branded `Handle` type (see typed-IDs OPEN).
- Loading/progress UI (first load is tens of MB — §11) + a loud error surface.
- **Verify the HP path in WASM** (M1 open risk — `precision:'hp'` had only run
  natively).
- **Validation gate (the kill-early bar):** extend `drive_browser.mjs` so the real
  browser boots, all engine modules import, and a **known dose benchmark
  round-trips through the bridge** (Co-60 air-kerma @ 1 m, or a Cs-137 M3
  value) — not just "page loaded."

### M6b — Inventory panel + central app-state model  ✅ DONE
**See `docs/plans/M6b-inventory-state.md`.** Gate green dev + built (M6a benchmarks
+ 6 panel checks). The `state.svelte.ts` runes singleton is the source of truth;
the engine gained a **per-entry-units solve form** (`from_entries`; `solve`
dispatches on `entries`) so §9's per-isotope unit is honored not silently dropped.
- The single source-of-truth state object: loaded nuclides {name, quantity, unit},
  precision, reference time/source-age (t=0). All views read from it.
- Add-by-name (validated against the new `bridge.nuclides()`) + quantity + per-entry
  unit (atoms/mass/Bq/Ci); remove; edit → re-solves (invariant #1/#2: new handle,
  release old).
- **Shared color palette** assigned here on solve (invariant #4): `ColorRegistry`,
  stable per nuclide across re-solves, reassigned as a fresh `Record` each solve.
- **Save/load — scoped to inventory state in this chunk.** Full app state (distance,
  shield, geometry, time cursor) is born in M6d/f/g; the serializer is **versioned
  and extended by each later chunk**, with the full round-trip test in M6h. (Do not
  ship a half-serializer that silently drops later fields — §11.)
- **Invariant #1 correction (resolved here):** invariant #1 lists **t=0** as a
  re-solve trigger, but §8/§9 treat source-age as a free **evaluation offset**.
  M6b only *stores* `referenceTimeS` and does **not** re-solve on it; M6d wires the
  offset at `evaluate` time. (So invariant #1's t=0 clause is superseded.)

### M6c — Time-evolution overlay curves (Plotly)
- One `evaluate()` over the auto-range grid → multi-species overlay on log-log.
- The docked **Atoms · Mass · Activity** segmented toggle (default Activity) +
  secondary unit (Bq/Ci, g/kg); y-axis label updates per §12.
- **Log-axis flooring** at ~12–15 decades below peak, **per axis-mode** (a stable
  end-product has zero activity but a growing atom/mass curve); honest gaps, no
  dive to −∞. **Linear-axis option** for the single-half-life zoom.
- Switching axis mode re-evaluates (cheap), never re-solves.

### M6d — Time control (slider + cursor)  ✅ DONE
**See `docs/plans/M6d-time-control.md`.** Gate green dev + built (M6a/b/c + 4 M6d
checks). The source-age **offset is wired at evaluate time** (`setReferenceTimeS`
re-evaluates, never re-solves); the store exposes **`currentTimeS = referenceTimeS
+ cursorOffsetS`** — the single absolute time M6e/M6f consume. Cursor moves ride a
cheap `Plotly.relayout` (not `react`); animate is cancellable (store `animating`
flag cleared by `solve()`).
- Single **log** time slider auto-ranged per inventory (from solve metadata
  `time_range_s`), with **half-life tick marks** (one per species).
- Numeric time entry + unit dropdown; **definable t=0 / source-age**.
- **Animate** button sweeping equal log-time steps — each frame a fresh
  *evaluation* of the solved inventory (§3), not a re-solve.
- The slider drives a **cursor** over M6c's curves; emits the current time that
  M6e (DAG) and M6f (dose) subscribe to.

### M6e — Chain view (Cytoscape DAG)  ✅ DONE
**See `docs/plans/M6e-chain.md`.** Gate green dev + built (M6a/b/c/d/f + 4 M6e
checks). The DAG owns a **dedicated activity series** (`chainActivity`, axis=Bq
over `curveX`) so the live encoding tracks activity independent of the curve axis;
topology (`chainDag`) is fetched **only on solve**, the cursor is a cheap batched
`cy.style()` restyle (no re-solve), the layout toggle is **imperative** (avoids
effect-ordering), and the **(N, Z) preset** uses fresh-copy positions to dodge
cytoscape's in-place position-object mutation.
- Render `chain(handle)` nodes/edges; **two layouts**: dagre (compact) and the
  **(N,Z) chart-of-nuclides preset** (nodes carry Z/A/N from M1).
- Node tooltip: half-life, Z/A/N, decay modes, **live activity**; edge label:
  mode + branching %. **Per-emission energies deferred** to the M6f-2 dose per-line
  table (`build_dag` is topology-only — see the doc; not a silent drop, §11).
- **Live encoding**: node size/opacity driven by the M6d slider-time **activity**
  (vs the fixed global series peak) → scrubbing shows parent fade / daughter
  in-growth (secular & transient equilibrium visible on the diagram). Shared palette (#4).
- SF pseudo-sink rendered as the honest "fission products" terminal (M1); its
  visual lands with M7 prebuilt SF sources (Cf-252…).

### M6f — Dose calculator + breakdown  *(resolves §13 #3 → **AP**)*  🚧 M6f-1 in progress
**See `docs/plans/M6f-dose.md`.** Split M6f-1 (cursor-time γ/β breakdown +
H\*(10)/effective+geometry + distance/exposure + accumulated-by-integration +
neutron grayed) / M6f-2 (uncertainty viz + per-line gamma table). Two LOCKED
honesty calls: γ(Sv) and β(Gy/Hp(0.07)) are **different quantities, never summed**
(§6.2/#5 → same-quantity-only stack, β in its own panel); accumulated dose
**integrates** the rate series, never rate×time (§11). Dose is solve-once /
evaluate-many like the curves: a per-(distance,quantity,geometry) rate series over
the curve grid, cursor-indexed (scrub/animate make zero bridge calls). **§13 #3
resolved → AP.**
- Inputs from inventory: distance, exposure time → dose-rate + accumulated dose.
- **H\*(10)** (default) vs **effective** + **geometry dropdown** when effective
  (AP/PA/LLAT/RLAT/ROT/ISO) — **resolve §13 #3 default (ISO vs AP) here** and
  record it in this doc *and* HANDOFF_PLAN §13.
- Per-type **breakdown** γ/β/n: **linear stacked bar** default + **grouped-log-bar**
  toggle (logs don't stack); **live** with distance/shield/time. Gamma slice →
  per-line table.
- **Neutron grayed out** for user inventories (no `source` key — §6.3 gate);
  available only via prebuilt neutron sources (those arrive in M7).
- **Uncertainty made visible (§9/§11):** fill bands on dose-vs-distance/-thickness
  curves; error whiskers on the grouped-log-bar view (γ ±10–15%, β ±20–30%, n
  order-of-mag); **not** on the stacked bar.
- Each modality labels its quantity; never blind-sum Hp(0.07) with H\*(10) (#5).

### M6g — Shield builder
- Ordered (material, thickness) stack; material list **radiation-type-aware**
  (warn high-Z for beta → bremsstrahlung crossover; steer neutron → hydrogenous).
- Outputs: dose with/without shield + attenuation factor; **dose-vs-thickness**
  and **dose-vs-time** graphs (live).
- **v1 ships single-layer** shields (per §13 #2 deferral — buildup is unambiguous
  for one layer; the layered approximation isn't needed until multi-layer lands).
  Beta bremsstrahlung-in-shield from the existing `beta_dose` brems path.

### M6h — Honesty-register surfacing + headless UI test + polish
- Surface §11 honesty items in-app (the register must be *visible*, §0): the
  "not for safety decisions" disclaimer, per-modality accuracy registers, scoring
  floor, degraded-table notes, point-source/no-air caveats — as tooltips/info
  panels next to the relevant numbers, not buried.
- **Full app-state save/load round-trip test** (the M6b serializer + every later
  field) — load JSON → identical views. **Includes the M6d time cursor**
  (`cursorOffsetS`, deferred from M6d as output-affecting state): mind the ordering
  trap — `loadFromText`→`solve()`→`resetCursor()` clobbers a naively-restored
  cursor, so restore it *after* `solve()` and clamp to the new range (see
  `docs/plans/M6d-time-control.md` "Deferred / open").
- End-to-end headless UI test (extend `drive_browser.mjs`): boot → load source →
  scrub → dose → shield → assert benchmark numbers and that warnings render.
- Units sweep (§12), loading/error polish, first-load caching (service worker is a
  possible stretch).

## Key files & decisions

- `web/` — a **Vite + TypeScript + Svelte/React** project: `index.html` entry,
  `src/` with the bridge client (typed `Handle`), the reactive app-state store,
  and per-view components (curves, time, chain, dose, shield), `public/` holding
  the runtime-data archive + Pyodide loader glue. The old M1 harness contents are
  retired into this app.
- `web/drive_browser.mjs` — extended into the per-chunk + end-to-end UI test
  driver (Playwright against the Vite dev server / built `dist/`).
- A small build/copy step to assemble the runtime-data archive (emissions +
  conversion + attenuation + buildup + neutron_sources; **excludes** vendor/build).
- No change expected to `engine/` (the `set_data_root()` hatch already exists);
  if a loader needs FS-friendliness, prefer extending the engine over a UI hack.
- **§13 #3** (effective-dose default geometry) is resolved in M6f.

## Open questions / risks

- **Framework — RESOLVED (user, 2026-06-17): Vite + a component framework
  (React/Svelte), with a build step.** The deciding constraint was the **locked
  live/reactive requirement** (§9): one slider scrub must update DAG encoding +
  curve cursor + dose bars together — genuinely reactive multi-view state, hard
  to reverse later. *Reconciliation with "no build-time backend" (§3/§4):* a
  **frontend** build tool only compiles to **static assets**; it is not a backend
  and the deployed app stays 100% client-side (Pyodide does all physics in the
  browser), so the locked all-on-device architecture is intact. Accepted cost:
  toolchain/repo complexity. *Sub-choice React vs Svelte — pick at M6a start;
  recommend **Svelte** (compiles away → tiny runtime, built-in reactivity fits
  the one-signal-many-views case; bundle stays lean), React fine if ecosystem
  familiarity is preferred.*
- **Packaging method (M6a).** Recommended: one archive + `unpackArchive`,
  assembled into the Vite `public/` dir as a static asset. Risk: archive build
  step + 48 MB first load (cached after). Lazy per-nuclide emission fetch is the
  fallback optimization if first load is unacceptable.
- **Typed IDs — RESOLVED (follows the build step): use TypeScript.** The Vite
  build makes real TS the natural choice (not JSDoc) for the branded `Handle` and
  nuclide IDs (CLAUDE.md typed-IDs preference).
- **HP path in WASM — RESOLVED (M6a).** `rd.InventoryHP` runs under WASM;
  `micropip.install("radioactivedecay")` auto-pulls sympy + mpmath. No extra step.
- **Plotly/Cytoscape** — now **bundled npm deps** (Vite), not CDN/import-map;
  size budget fine (§4, Pyodide dominates). Confirm tree-shaking (Plotly is
  large — consider `plotly.js-dist-min` or a custom bundle) and that Cytoscape +
  dagre layout are wired.
- **Prebuilt sources are M7**, not M6 — M6f's neutron path and source-aware
  inventory model must be built source-ready but exercised with user inventories
  + (for neutron) the Cf-252 key already shipped in M5.
