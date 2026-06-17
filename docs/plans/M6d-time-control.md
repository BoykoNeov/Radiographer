# M6d — Time control (slider + cursor + source-age offset + animate)

**Status:** ✅ done — gate green in a real headless browser, dev **and** built.
**Parent:** `docs/plans/M6-ui.md` (fourth M6 chunk; M6a boot, M6b inventory/state,
M6c curves). **Milestone (HANDOFF_PLAN.md §10):** M6 UI. This chunk adds the §9
time control and **pays off the M6b source-age deferral**: t₀ becomes an
evaluation offset, wired at `evaluate` time, never a re-solve (§3, invariant #1).

## Goal

A single **log** time slider, auto-ranged per inventory, with one half-life tick
per species; a numeric "go to" entry + unit; a definable **source-age t₀**; and a
play/pause **animate** that sweeps equal log-time steps. Every control moves only a
**cursor** over the already-solved M6c curves — one Bateman solve, evaluated many
(§3). The cursor exposes the single absolute time M6e (DAG) and M6f (dose) consume.

## Load-bearing decisions (a fresh session must not re-derive these)

1. **The downstream contract is one value: `currentTimeS` (advisor).** The DAG and
   dose only ever need *one absolute decay time* to feed `evaluate`/`dose`:
   `currentTimeS = referenceTimeS + cursorOffsetS` (a store getter). M6e/M6f read
   **that**; the x-axis presentation is reversible and touches nothing downstream.
   Build M6e/M6f against `currentTimeS`, not against the slider internals.

2. **t₀ is added at EVALUATE time (data model "A").** The locked language —
   "definable t=0 / source-age sets the reference origin", "evaluation offset",
   "forward decay is free" (§8/§9) — means the offset is *added to the evaluated
   time*: `eval_abs = referenceTimeS + displayTime`. `setReferenceTimeS` therefore
   now **re-evaluates** (`recomputeCurves`) — that *is* the M6d wiring of the
   M6b-stored field — but it is an evaluate, **never a re-solve** (#1). The "t₀ is
   just a marker" reading was rejected: it drains "offset" of meaning.

3. **Two time coordinates, one rule: plot DISPLAY, evaluate ABSOLUTE.** The store
   keeps `curveX` (the display grid = `logGrid(time_range_s)`) and evaluates the
   overlay at `referenceTimeS + curveX`. `Curves.svelte` plots `curveX`. So the
   x-axis, cursor, and half-life ticks all live in one coordinate (display time =
   seconds since the reference origin), and at **t₀=0 everything is byte-identical
   to M6c** — the M6c gate stays green untouched. (The "wasted decades when t₀ is
   large" view-quality issue is an *auto-range* refinement, deferred to M7 with
   spent fuel — it changes nothing about correctness or the downstream contract.)

4. **Cursor moves are `Plotly.relayout({shapes})`, NOT `react()` (the smooth-slider
   payoff).** `Curves.svelte` has two `$effect`s: the trace rebuild (`react`) depends
   on curve/grid/colors/logY and reads the cursor with **`untrack`** so a cursor
   move does *not* re-run it; a second cursor-only effect depends on `cursorOffsetS`
   and does a cheap shapes-only `relayout` (guarded on the plot already existing).
   This is what makes scrub/animate cheap on top of solve-once (§3).

5. **Cursor is homed on every solve; range is per-inventory.** `time_range_s` changes
   with the inventory, so a stale cursor would point off-range (advisor blind spot).
   `solve()` success calls `resetCursor()` → geometric midpoint of the log envelope
   (`√(lo·hi)`); empty/failed solves reset it to 0. `setCursorOffsetS` clamps to the
   range. Moving the cursor never evaluates or solves (the curves already span it).

6. **Animate is cancellable three ways (advisor: an orphaned loop is a silent-error
   vector).** The `animating` flag lives in the **store** (observable + the kill
   switch); `solve()` clears it, so any inventory change stops a running sweep before
   the handle is released. The frame loop (`setInterval`) lives in `TimeControl.svelte`
   and bails when the flag is false; a guard `$effect` tears the timer down on
   external cancel; `onDestroy` clears it on unmount; a manual scrub calls `stopAnim`.

7. **Source-age t₀ moved out of the inventory panel.** M6b parked a placeholder
   "Reference time t₀" input in `Inventory.svelte`; M6d removes it and owns t₀ in
   `TimeControl.svelte` (with a unit dropdown). The M6b round-trip gate sets
   `referenceTimeS` *programmatically*, so removing the DOM input leaves it green.

8. **Time-unit util is loud.** `types.ts` gained `TIME_UNITS` (s/min/h/d/y; year =
   Julian 365.25 d = 31 557 600 s, rd's convention), `toSeconds` (throws on an
   unknown unit — no silent 0), and `humanTime` (display-only readouts/tick labels).

## The gate (what "M6d done" means)

`drive_browser.mjs` keeps the M6a boot self-check + M6b panel + M6c curve checks
and adds four M6d checks, driven through the rendered app path (dev + built):

| check | measured |
|---|---|
| log slider spans the display auto-range; one half-life tick per **finite** species | slider=[0.19, 9.98] (=log₁₀ range), ticks=2 of [Cs-137, Ba-137m, Ba-137] (Ba-137 stable → no tick) |
| cursor moves via **`relayout`** (vline `shape.x0` follows), handle stable, 1 live (#1/#2) | cursor≈target, shapeX==cursor, handleStable, size 1→1 |
| **OFFSET CONTRACT** (the M6f de-risk): t₀=t½(Cs-137) ⇒ rendered `A(t₀+x)/A(x)=exp(−λt½)=0.5` exactly (x cancels); `currentTimeS == referenceTimeS+cursorOffsetS`; offset is an evaluate, not a re-solve | ratio=0.50000, sum-check holds, handleStable, size 1→1 |
| animate advances the cursor then stops; no re-solve, no handle leak (§3/#2) | advanced, stopped, handleStable, size 1 |

Plus a hygiene fix: `runM6c`'s setup now resets `referenceTimeS=0` (M6b's round-trip
leaves t₀=5 yr; M6c passes either way — secular-eq ratio is t₀-invariant — but the
reset makes the M6c checks order-independent now that t₀ feeds the evaluate).

## Key files

- `web/src/lib/types.ts` — `TimeUnit`, `TIME_UNITS`, `DEFAULT_TIME_UNIT`,
  `toSeconds`, `humanTime`.
- `web/src/lib/state.svelte.ts` — `cursorOffsetS`, `curveX`, `animating` state; the
  `currentTimeS` + `cursorRange` getters (the downstream contract); `setCursorOffsetS`
  (clamp), `setReferenceTimeS` (now re-evaluates), `resetCursor`; `recomputeCurves`
  evaluates at `t₀ + grid` and stores `curveX`; `solve()` cancels animation + homes
  the cursor.
- `web/src/lib/Curves.svelte` — plots `curveX`; the split trace/cursor `$effect`s
  (`react` with `untrack`ed cursor + `relayout`-only cursor moves); the vline shape.
- `web/src/lib/TimeControl.svelte` — the log slider + half-life ticks (shared
  palette), numeric go-to + unit, source-age t₀ + unit, the cancellable animate loop.
- `web/src/lib/Inventory.svelte` — removed the M6b t₀ placeholder.
- `web/src/App.svelte` — mounts `<TimeControl/>` below `<Curves/>`; label → (M6d).
- `web/drive_browser.mjs` — `runM6d` (the four checks) + the `runM6c` t₀ reset.

## Deferred / open (not M6d)

- **DAG live encoding consumes `currentTimeS` → M6e**; **dose at the cursor consumes
  `currentTimeS` → M6f.** The contract (decision #1) is the whole point of M6d.
- **Large-t₀ "wasted decades" auto-range refinement → M7** (decision #3). Spent fuel
  (the only big-t₀ case) is M7; the current wiring is correct, just not view-optimal
  for ages ≫ the auto-range.
- **Cursor persistence — explicitly deferred to M6h (not a silent drop, §11).**
  `cursorOffsetS` is new state but is **not** in the M6b serializer (`toPersistable`)
  yet. The call: it is *output-affecting* (it feeds `currentTimeS` → M6f dose), so
  unlike M6c's axis/unit (view-preference, decision #6) it is **not** mere view
  state — but its correct restore has an ordering trap: `loadFromText` calls
  `solve()`, which calls `resetCursor()`, so a naively-restored cursor gets clobbered
  to the midpoint; it must be re-applied *after* `solve()` and clamped to the new
  range. That belongs in **M6h's full app-state round-trip** (where every later
  field is wired + tested and the cursor→`currentTimeS`→dose reproducibility is
  decided), not bolted on here. Until then the cursor is **transient view-state**.
  `referenceTimeS` (source-age) **is** persisted already (M6b) and round-trip-tested.
- **Linear *time* axis (single-half-life zoom)** — still deferred (needs a linear
  grid = a second evaluate); M6c's `logY` remains y-axis only.
- **Animate/cursor error states untested** — like M6b/M6c degenerate states, no
  failure is injected here; M6h injects + asserts. The all-stable slider-disable and
  the cancel-on-resolve paths render correctly but are unasserted in this gate.
