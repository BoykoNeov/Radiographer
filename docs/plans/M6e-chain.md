# M6e — Chain view (Cytoscape DAG)

**Status:** ✅ done — gate green in a real headless browser, dev **and** built.
**Parent:** `docs/plans/M6-ui.md` (fifth M6 chunk; M6a boot, M6b inventory/state,
M6c curves, M6d time control). **Milestone (HANDOFF_PLAN.md §10):** M6 UI. This
chunk renders the §8/§9 decay-chain DAG and **consumes the M6d cursor contract**:
the live node encoding is driven by `currentTimeS` (via the per-node activity at
the cursor), evaluated many off one solve (§3), never a re-solve.

## Goal

A Cytoscape DAG of the loaded inventory's descendant closure, with **two
switchable layouts** — **dagre** (compact Sugiyama) and the **(N, Z)
chart-of-nuclides preset** — node tooltips (half-life, Z/A/N, decay modes, live
activity), edge labels (mode + branching %), the shared per-species palette, and
a **live encoding** (node size + opacity ← activity at the time cursor) so
scrubbing shows the parent fade and a daughter grow in. The graph is built once
per topology change; a cursor move is a cheap batched restyle — the §3
"relayout-not-react" payoff, exactly like the M6d curve cursor.

## Load-bearing decisions (a fresh session must not re-derive these)

1. **The DAG owns a DEDICATED activity series — never reuse the display `curve`
   (advisor).** Live node encoding tracks **activity** (§5: radiation hazard
   tracks A=λN), but the M6c curve can be on the Atoms/Mass axis. So the store
   evaluates its own `chainActivity` (axis=activity, Bq) over the SAME `curveX`
   grid (at `referenceTimeS + curveX`), and `activityAtCursor` indexes it 1:1 with
   the curves/dose via `interpAt`. Reusing `curve` would break the DAG whenever
   the user switches the curve axis. Recompute triggers = **solve + source-age
   only** (NOT setAxis), and it runs **after** `recomputeCurves` (depends on
   `curveX`).

2. **Topology is time-independent → fetched ONLY on solve.** `chainDag`
   (`bridge.chain(handle)`: nodes+edges) changes solely with the inventory, so
   `fetchChain()` runs in `solve()` success — never on a source-age or cursor
   change. `clearChain()` mirrors `clearDose()` on empty/failed solve. The node
   set is the solve closure verbatim (`engine/chain.py`), so DAG and inventory
   can't drift.

3. **Build once per topology; the cursor is a cheap `cy.batch()` restyle (§3).**
   One `$effect` (deps `chainDag`, `colors`) builds/destroys the Cytoscape
   instance; it reads the cursor/layout **untracked**. A second `$effect` (dep
   `activityAtCursor`) does a batched per-node `node.style({width,height,opacity})`
   — NO rebuild, NO re-layout, NO bridge call. This is the smooth-slider payoff;
   the gate asserts a cursor move restyles nodes with the **handle stable +
   registry==1** (no re-solve).

4. **Live encoding = activity vs the FIXED global series peak (scheme B), log,
   `ENC_DECADES=6`.** Normalizing against the all-time peak (not a per-frame peak)
   makes absolute decay read as an overall fade and in-growth as a daughter
   swelling — the literal §9 "parent fade, daughter grow in" (a per-frame peak
   would freeze secular-equilibrium sizes). Size ∈ [22, 64] px, opacity ∈ [0.4,
   1] by log-fraction; ≤0 / below-floor activity (stable end-products, the SF
   sink) sits at the faded floor — an honest "negligible here", **never hidden**
   (advisor #4). All-stable inventory (no activity series) → neutral topology-only
   sizing, not a blank fade.

5. **(N, Z) preset = canonical Segrè chart (x=N, y=−Z); β⁻ reads as a diagonal.**
   The §8 wording "β⁻ a horizontal step" only holds on an A-vs-Z chart; the
   canonical (N, Z) chart makes α a down-left diagonal and β⁻ an up-left diagonal.
   These are the same sheared lattice, so the property §8 actually cares about —
   **re-convergence falls out because a shared daughter is one coordinate** — is
   basis-independent and holds regardless (advisor #3). Metastable isomers share
   (N, Z) with their ground state, so they're nudged diagonally (`state` rank ×
   0.33) to stay visible. The SF sink (null Z/N) is placed below the lowest-Z
   member.

6. **CYTOSCAPE MUTATES POSITION OBJECTS BY REFERENCE — the load-bearing footgun.**
   Cytoscape stores an element's `position` object by reference and a layout
   (dagre) **overwrites it in place**. Passing `presetPositions[id]` as an
   element's initial `position` therefore clobbered the canonical (N, Z) map with
   dagre coords (caught only by the gate: the chart toggle produced dagre
   positions). Fix: elements carry **no** initial `position`; the chart layout
   gets **fresh copies** of every coord (`{...presetPositions[id]}`). Same hazard
   if the layout's `positions` map were shared across runs.

7. **Layout toggle is applied IMPERATIVELY from the click handler, not a
   `$effect`.** `setLayout(mode)` sets `layoutMode` and runs `cy.layout(...).run()`
   directly — removing any effect-ordering ambiguity vs the build effect. The
   build effect applies the initial layout via the constructor `layout:` option
   (reading `layoutMode` untracked), so a re-solve preserves the chosen layout.

8. **Cytoscape is exposed as `window.__CY__` for the gate.** The DAG renders to a
   **canvas**, so there's no DOM to assert against (unlike Plotly's `.data`); the
   gate reads node/edge data, rendered `.width()`, and model `.position()` off the
   live instance. Cleared to null on destroy. (`node.position()` returns a LIVE
   reference — read scalars, don't compare serialized snapshots across mutations.)

## The gate (what "M6e done" means)

`drive_browser.mjs` keeps the M6a boot + M6b/M6c/M6d/M6f checks and adds five M6e
checks (driven through the rendered Cytoscape path; dev + built), on a Cs-137
baseline (Cs-137 → Ba-137m → Ba-137 stable; no SF) plus a Bi-212 re-convergence case:

| check | measured |
|---|---|
| DAG topology = solve closure, shared palette, mode+branching% edge labels | nodes=[Cs-137, Ba-137m, Ba-137], colorsMatch, 3 edges e.g. `β- 94.4%` |
| cursor move restyles nodes via cheap batch, **no re-solve** (handle stable, registry==1) | Ba-137m width 48.7→63.8 px (grows in), handleStable, size 1→1 |
| live encoding driven by **real activity** (not a placeholder): secular-eq ratio | A(Ba-137m)/A(Cs-137)=0.94399 off `activityAtCursor` |
| layout toggle dagre → **(N, Z) chart preset**: square N/Z lattice, distinct from dagre | chart Δ(Cs-137,Ba-137)=(70,70)=(N·s,−Z·s) [Δx≈Δy>0], dagre Δ=(0,−190) |
| **branch-and-reconverge** (the LOCKED reason for Cytoscape, §2/§4/§8): the Bi-212 ThC diamond reconverges at a SINGLE Pb-208 with ≥2 incoming edges, in **both** layouts | closure=[Bi-212, Po-212, Tl-208, Pb-208], Pb-208=1 node, indegree=2 from [Po-212, Tl-208] |

Error parity (§11): `recomputeChainActivity` clears `chainError` on a present
topology (so a recovering source-age leaves no stale banner) but **bails without
clearing when `chainDag` is null**, so a `fetchChain` closure-drift error stays loud.

## Key files

- `web/src/lib/Chain.svelte` — the renderer: build/destroy `$effect`, the live
  encoding `$effect`, `encode()` (scheme B), `nzPosition`/`buildPresetPositions`
  ((N, Z) grid + isomer nudge + SF sink), `layoutOptions` (dagre / preset with
  fresh-copy positions), imperative `setLayout`, the hover tooltip.
- `web/src/lib/state.svelte.ts` — `chainDag`, `chainActivity`, `chainError` state;
  the `activityAtCursor` getter; `fetchChain` (solve-only topology),
  `recomputeChainActivity` (solve + source-age, after `recomputeCurves`),
  `clearChain`; wired into `solve()` / `setReferenceTimeS()`.
- `web/src/lib/bridge.ts` — `ChainNode`/`ChainEdge`/`ChainOk` tightened to match
  `engine/chain.build_dag` (Z/A/N/state/half_life/modes; edge mode+branching).
- `web/src/App.svelte` — mounts `<Chain/>` between `<TimeControl/>` and `<Dose/>`.
- `web/src/vite-env.d.ts` — `window.__CY__` gate hook.
- `web/drive_browser.mjs` — `runM6e` (the four checks), wired before `runM6f`.
- `web/package.json` — added `cytoscape`, `cytoscape-dagre`, `dagre`,
  `@types/cytoscape`, `@types/dagre` (bundled via Vite; `cytoscape.use(dagre)`).

## Deferred / open (not M6e)

- **Per-emission decay ENERGIES in the node tooltip — DEFERRED, documented (not a
  silent drop, §11).** §9 lists "decay energies" on the node tooltip, but
  `build_dag` carries decay **topology** only; per-line photon/beta energies live
  in the emissions dataset and are surfaced in the **dose per-line gamma table
  (M6f-2)**. The tooltip shows half-life, Z/A/N, decay modes, and live activity;
  the hint points to the dose table for energies. (Extending `build_dag` with a
  per-node emission summary is the alternative if it's wanted on the diagram.)
- **SF pseudo-sink rendering is built but unexercised by the gate.** The Cs-137
  baseline has no SF branch; the sink node (gray "fission products" terminal,
  faded, placed below-left in the (N, Z) preset) renders for SF-branching nuclides
  (Cf-252, U-238…) — its visual is exercised once **M7 prebuilt sources** land.
- **Layout/encoding error states untested** — like M6b–M6d degenerate states, no
  failure is injected here (`chainError` renders but is unasserted); M6h injects +
  asserts. The all-stable neutral-sizing path renders but is unasserted in this gate.
- **Cursor/layout persistence** — `layoutMode` is transient component view-state
  (not persisted); the cursor persistence question is owned by M6h (see
  `docs/plans/M6d-time-control.md`).
