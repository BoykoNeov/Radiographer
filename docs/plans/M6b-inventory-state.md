# M6b — Inventory panel + central app-state store

**Status:** ✅ done — gate green in a real headless browser, dev **and** built.
**Parent:** `docs/plans/M6-ui.md` (second M6 chunk; M6a was the boot foundation).
**Milestone (HANDOFF_PLAN.md §10):** M6 UI. This chunk builds the single
source-of-truth state object and the inventory panel that writes to it — the
substrate every later view (curves, DAG, dose, shield) reads from. §9 is the UX
contract; the M6-ui "cross-cutting invariants" (#1 solve-once, #2 handle
lifecycle, #3 no-silent-errors, #4 shared color) are the rules it must not break.

## Goal

A working inventory panel backed by a reactive central store: add isotopes
(name + quantity + per-isotope unit), edit/remove, choose precision, and
save/load — every change driving **one** Bateman solve, with the shared
per-species palette assigned on solve and a versioned JSON serializer that later
chunks extend rather than replace.

## Load-bearing decisions (a fresh session must not re-derive these)

1. **Per-entry units — the engine learned a second solve form.** §9 wants a unit
   *per isotope* (Co-60 in Bq alongside Cs-137 in g). Mixed units can't be merged
   client-side (Bq→atoms needs per-nuclide λ; mass→atoms needs atomic mass —
   neither known until *after* a solve) and separate solves can't be combined
   (shared daughters). So the engine converts each entry to atoms via `rd` and
   **sums** them: `SolvedInventory.from_entries(entries, precision)`, and
   `bridge.solve` **dispatches on the presence of `entries`** (the old
   `{nuclides, unit}` form is untouched — every existing test + the M6a selfcheck
   still use it). The single-unit form was *incidental* (a thin `rd.Inventory`
   wrapper), **not** a LOCKED decision, so extending it honors the contract rather
   than relitigating it. Duplicate nuclide across entries → atom sum (tested,
   intentional). *This was the only engine change M6b needed.*

2. **Central store = a Svelte 5 runes class singleton in `state.svelte.ts`.** The
   `.svelte.ts` extension is load-bearing — it compiles the `$state` runes; a
   plain `.ts` would silently not be reactive. The store owns the inventory model,
   the live engine `Handle`, the shared color map, and save/load. The
   `BridgeClient` is **injected after boot** (`setClient`), which also fetches the
   add-by-name nuclide list once.

3. **Handle lifecycle: release-old-always (#2).** Every solve releases the prior
   handle and keeps the new one *only on success* → the Python `_REGISTRY` never
   leaks and at most one handle is live. A failed solve leaves `handle = null` +
   a visible error (#3), never a stale handle or a blank.

4. **t=0 (reference time / source-age) is NOT a re-solve trigger in M6b.** M6-ui
   invariant #1 lists it as one, but §8 ("cooling time = just forward decay —
   free") and §9 ("reference origin") treat source-age as an **evaluation
   offset**, not a re-solve. That contradiction is **resolved here in favor of
   offset**: M6b only *stores* `referenceTimeS`; its semantics (a shift applied at
   `evaluate` time) land in M6d with the time control. (Recorded so M6d doesn't
   wire it to a re-solve.)

5. **Shared palette owned by the store, reassigned fresh per solve (#4).** A
   `ColorRegistry` (`palette.ts`) mints a stable color per nuclide (Tableau-20
   base, golden-angle HSL overflow) and caches it, so a nuclide that persists
   across re-solves keeps its color. The store calls `registry.assignAll(closure)`
   and assigns the returned **new `Record` reference** to `$state` — a Svelte 5
   `$state` `Map`/`Set` mutated in place would *not* re-render; a fresh object does.
   Colors cover the **full descendant closure** (parents + daughters), because all
   downstream views render daughters.

6. **Versioned save/load envelope, loud-refuse on the unknown (`persist.ts`).**
   `{ schema:"radiographer.app-state", version:1, inventory:{entries,precision,
   reference_time_s} }`. Loading a file with a *newer* version throws a loud
   `PersistError` (rather than silently dropping fields it can't read — §11). M6b
   serializes only the inventory slice; M6d/f/g add sibling sections (distance,
   shield, geometry, time) and **bump the version**. The full app-state round-trip
   test is M6h; the inventory round-trip (exact: order, numeric type, unit,
   precision, t₀) is asserted now in the gate.

7. **Boot self-check gated behind `?selfcheck=1`.** The M6a kill-early benchmarks
   run the multi-second U-238 HP path — fine for the gate, user-hostile as the
   real app's default boot. The shell now boots straight to the inventory panel;
   the self-check runs only when the harness sets `?selfcheck=1`. (Solve is
   synchronous on the main thread — Pyodide is not in a worker — so a `double`
   solve is instant but an HP solve freezes the UI briefly; the "Solving…" state
   paints via a `setTimeout(0)` yield before the blocking call, and cannot animate
   *during* compute.)

## The gate (what "M6b done" means)

`drive_browser.mjs` keeps the M6a boot benchmarks (under `?selfcheck=1`) and adds
six M6b checks driven through the **rendered panel** (dev + built):

| check | measured |
|---|---|
| add-by-name list loaded (`nuclides()` bridge fn) | 1512 nuclides |
| Co-60 add → solved closure + shared colors | `[Co-60, Ni-60]`, Co-60 = `#4e79a7` |
| legend swatches rendered in the DOM | 2 items, swatch `rgb(78,121,167)` |
| second species (Cs-137 in **g**) → distinct + stable colors | Cs-137 `#59a14f`, Co-60 unchanged |
| save/load round-trip **exact** (order, number, unit, precision, t₀) | identical, no drift |
| unknown nuclide → **visible error, no handle minted/leaked** (#3) | inline error, handle/entries unchanged |

## Key files

- `engine/bridge.py` — new `nuclides()` (the add-by-name source) + `solve`
  dispatch on the `entries` form. `engine/inventory.py` — new
  `SolvedInventory.from_entries`. Tests in `tests/test_bridge.py`.
- `web/src/lib/types.ts` — `InventoryEntry`, `UNIT_OPTIONS`, `Precision`.
- `web/src/lib/palette.ts` — `ColorRegistry` (stable per-species colors).
- `web/src/lib/persist.ts` — versioned envelope + serialize/deserialize + file
  download/upload + localStorage autosave.
- `web/src/lib/state.svelte.ts` — `AppState` runes singleton (`appState`).
- `web/src/lib/Inventory.svelte` — the panel (add row + datalist, entry table,
  precision/t₀ controls, save/load, status, shared-palette legend).
- `web/src/lib/bridge.ts` — `nuclides()` client method; `SolveSpec` is now the
  two-form union (`entries` | `nuclides+unit`).
- `web/src/App.svelte` — boots → `setClient` → renders the panel; self-check
  gated behind `?selfcheck=1`; exposes `window.__APP__` for the gate.
- `web/drive_browser.mjs` — boot benchmarks + the six M6b panel checks.

## Deferred / open (not M6b)

- **Duplicate-nuclide *rows* in the panel UX.** The engine sums atoms correctly,
  but whether the panel should *let* a user add two rows of one nuclide (vs merge
  or warn) is a UX call — deferred, not blocking.
- **Full app-state round-trip test → M6h** (M6b ships the inventory slice; later
  chunks extend the envelope and bump the version).
- **Boot-error red banner still unverified** (M6a carry-over): the gate proves the
  *bridge*/*panel* surface errors loudly, but `App.svelte`'s `phase==="error"`
  banner is never triggered (no boot failure injected). **M6h must assert it.**
- **Reference-time (t₀) control + offset semantics → M6d.**
