# M6c — Time-evolution overlay curves (Plotly)

**Status:** ✅ done — gate green in a real headless browser, dev **and** built.
**Parent:** `docs/plans/M6-ui.md` (third M6 chunk; M6a boot, M6b inventory/state).
**Milestone (HANDOFF_PLAN.md §10):** M6 UI. This chunk adds the first *graph* view:
the multi-species time-evolution overlay on log-log axes, driven by **one**
`evaluate()` per inventory. §9 is the UX contract; the M6-ui "cross-cutting
invariants" (#1 solve-once/evaluate-many, #3 no-silent-errors, #4 shared color,
#5 obsessive units) are the rules it must not break.

## Goal

A docked overlay plot that, off the already-solved handle, draws every closure
member as a curve; an **Atoms · Mass · Activity** segmented toggle (default
Activity) + secondary unit re-evaluate (cheap) and **never** re-solve; per-axis
log-flooring renders negligible/stable species as honest gaps; the y-axis label
tracks the quantity+unit obsessively (§12).

## Load-bearing decisions (a fresh session must not re-derive these)

1. **The store owns the axis + the evaluate; the component is a pure renderer.**
   `state.svelte.ts` gained `axis` / `activityUnit` / `massUnit` / `logY` /
   `curve` / `curveError` and a private `recomputeCurves()`. `Curves.svelte`
   reads `appState.curve/colors/axis/logY` and calls `appState.setAxis(...)` etc.
   — it **never touches the `BridgeClient`** (the store is the single client
   owner, M6b). This keeps "solve once, evaluate many" auditable in one place.

2. **Evaluate is an explicit method; render is a `$effect`.** `recomputeCurves()`
   is called imperatively at exactly three kinds of moment — solve success, and
   the axis/unit setters — never as a `$derived` (which would re-evaluate on every
   read). Pushing the result into Plotly *is* an imperative-library sync, so that
   (and only that) lives in a `$effect` calling **`Plotly.react()`** (not
   `newPlot`) — the cheap-update path M6d's cursor will ride on.

3. **The grid: log-spaced over `time_range_s`, t=0 omitted, no offset.** ~300
   points (`logGrid`) spanning the solve's auto-range (§9). The slider/cursor and
   the t=0 (source-age) **evaluation offset** are M6d — M6c deliberately ignores
   `referenceTimeS`. `time_range_s === null` (all-stable inventory) → no plot +
   an honest note. HP uses a coarser 60-pt grid (sympy is per-point).

4. **Flooring is a SINGLE GLOBAL value across all series, per axis-mode.**
   `floor = peak / 10^13` where `peak` is the max over **every** series × time at
   the current axis; any point `≤ floor` (or `≤ 0`) becomes `null` → Plotly draws
   a gap, never a dive toward −∞ (§9). Per-series flooring would redraw a
   negligible daughter at full height and destroy the "this species is irrelevant
   here" message §9 is built on. This is **distinct** from the engine's numerical
   validity floor (`floor_atoms`, double-precision noise); the display floor sits
   far above it. Linear-y passes values through unfloored (0 is plottable) — the
   single-half-life zoom case.

5. **x-axis stays log in M6c; `logY` toggles only the y-axis.** A linear *time*
   axis needs a linear grid = a second evaluate; deferred to the M6d zoom. `logY`
   is a pure render flag (no re-evaluate) — flooring is recomputed in the renderer.

6. **Axis/unit are ephemeral display state — NOT persisted in v1 (deliberate).**
   The M6b serializer covers the *inventory* slice; M6-ui names M6d/f/g (distance,
   shield, geometry, time) as the serializer-extending chunks — **M6c is not one**.
   Axis is a view preference, so `persist.ts` / `STATE_VERSION` are untouched and
   the M6b round-trip gate stays green. (A future enhancement could persist it.)

7. **Plotly = `plotly.js-basic-dist-min`** (scatter for M6c curves + bar for M6f
   dose breakdown — both covered; ~389 KB gzip in the built bundle, ~1% of the
   Pyodide payload per §4). It ships no own types, so `src/plotly-basic.d.ts`
   re-exports `@types/plotly.js`. The native Plotly legend uses the **shared
   per-species palette** (invariant #4 reaching the curve): each trace's
   `line.color = appState.colors[name]`.

## The gate (what "M6c done" means)

`drive_browser.mjs` keeps the M6a boot self-check + the six M6b panel checks and
adds four M6c checks driven **through the rendered Plotly path** — every assertion
reads the plot div's own `.data`/`.layout` (what the user sees), not the store
(dev + built):

| check | measured |
|---|---|
| overlay renders one trace per closure member, shared palette, §12 label | 3 traces [Cs-137, Ba-137m, Ba-137], colors match, yTitle="Activity (Bq)", axes log/log |
| **physics**: Cs-137 secular equilibrium A(Ba-137m)/A(Cs-137) ≈ 0.94399, read off the **rendered** curve nearest 1 d (~1% tol — the tight 1e-3 only holds at exactly 86400 s) | ratio=0.94399 @ t≈8.6e4 s |
| axis toggle re-evaluates, **never re-solves** (#1): click rendered "Atoms" → handle unchanged, exactly one live | handleStable, registry_size 1→1, axis=atoms |
| per-axis flooring: the stable end-product (Ba-137, t½=∞) is an honest **gap** on Activity (all null) yet **grows in** on Atoms — same nuclide, two axes, two visibilities (catches a per-series-floor bug the ratio check can't) | stable=Ba-137, atoms growing, activity all-null |

## Key files

- `web/src/lib/types.ts` — `Axis`, `AXIS_OPTIONS`, `ACTIVITY_UNITS`, `MASS_UNITS`,
  `ATOMS_UNIT`.
- `web/src/lib/state.svelte.ts` — axis/unit/logY/curve/curveError state, the
  `curveUnit` getter, the axis/unit/logY setters, `recomputeCurves()` (called on
  solve-success; cleared on empty/fail), and the `logGrid` helper.
- `web/src/lib/Curves.svelte` — the pure renderer: docked segmented toggle +
  secondary unit + log/linear checkbox; the `$effect`→`Plotly.react()` sync; the
  global per-axis flooring; the §12 y-axis label; empty / all-stable / error notes.
- `web/src/plotly-basic.d.ts` — types shim for `plotly.js-basic-dist-min`.
- `web/src/App.svelte` — mounts `<Curves/>` below `<Inventory/>`; label → (M6c).
- `web/drive_browser.mjs` — `runM6c` (the four rendered-path checks above).

## Deferred / open (not M6c)

- **Time slider + cursor + t=0 offset + animate → M6d.** M6c plots over the full
  auto-range; the cursor that scrubs THIS grid (and the source-age offset) is M6d.
- **Linear *time* axis (single-half-life zoom) → M6d** (needs a linear grid =
  a second evaluate). M6c's `logY` is y-axis only.
- **Half-life tick marks on the time control → M6d** (they belong on the slider).
- **Persisting axis/unit display state** — intentionally out (decision #6).
- **`curveError` banner + empty / all-stable notes are untested → M6h.** Like the
  M6b boot-error banner, no failure is injected in this gate, so the loud
  curve-path error surface and the two degenerate-state notes render correctly but
  are unasserted. M6h injects the failures and asserts them (don't add
  error-injection plumbing now). The four positive M6c checks now also cover all
  three toggle legs (Atoms/Mass/Activity) and the secondary-unit change path.
