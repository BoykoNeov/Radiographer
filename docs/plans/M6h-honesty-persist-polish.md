# M6h — Honesty-register surfacing + full save/load round-trip + end-to-end UI test

**Status:** in progress — final M6 chunk.
**Parent:** `docs/plans/M6-ui.md` (eighth/last M6 chunk). **Milestone (HANDOFF_PLAN.md
§10):** M6 UI. The §11 honesty register, §9 save/load, and §12 units are the invariants
this chunk completes and must not violate.

## Goal

Close out M6: (1) make the §11 honesty register a *visible in-app artifact*; (2) extend
the M6b versioned serializer to the FULL app state (dose / shield / view / time cursor)
with a discriminating round-trip test; (3) an end-to-end headless UI test; (4) units /
loading / error polish. After M6h the browser app is feature-complete for v1 (M7 =
prebuilt sources + teaching demos remain).

## Load-bearing decisions (a fresh session must not re-derive these)

1. **The round-trip test must assert "identical VIEWS", not just string equality (advisor).**
   M6b's check is `serialize() before === after`. That is necessary but CANNOT catch the
   bug M6h exists to prevent: a view-affecting field *missing from the serializer* is absent
   from both `before` and `after`, so the strings match while the view silently reverts to
   default on load. §9 says "load JSON → **identical views**" precisely to guard that. So the
   M6h gate (`runM6h`):
   - sets a **non-default value in EVERY persisted field** (if a saved value equals its
     default, a dropped field is invisible);
   - captures a **rendered** value per view (γ card `data-rate-si`, a curve `y`, the cursor
     shape `x0`, the y-axis label, shield `data-testid="shield-atten"`, the distance input
     field value), then `clear()` → `loadFromText` → asserts each rendered value matches
     **and** `serialize()` matches.

2. **All persisted-field validation lives in the DESERIALIZER (advisor).** `loadFromText`
   restores by **direct field assignment** before `solve()` (so `solve()`'s internal
   `recomputeCurves`/`recomputeDose` pick the values up) — this BYPASSES the setters' guards
   (`setDoseDistanceM` rejects ≤0, `setShieldThicknessCm` rejects <0, the quantity/geometry/
   axis setters are enum-typed, etc.). Therefore `deserializeState` must itself reject:
   distance > 0, exposure ≥ 0, thickness ≥ 0, cursor finite, `quantity`/`geometry`/`axis`/
   units in their enums, `shieldMaterial` null-or-string. No silent clamp on load (§11).

3. **The cursor ordering trap (M6d carry-forward).** `loadFromText` → `solve()` →
   `resetCursor()` clobbers a naively-restored cursor. So: set every recompute-affecting
   field (entries, precision, referenceTimeS, axis, units, logY, dose inputs, shield) by
   direct assignment **before** `solve()`; then restore `cursorOffsetS` **after** `solve()`
   via `setCursorOffsetS` (which reads the now-set `cursorRange` and clamps to the new
   envelope). The dose series is built over `curveX` independent of the cursor, so restoring
   the cursor after solve needs no extra recompute.

4. **Persist-or-ephemeral is a CONSCIOUS, documented decision per field (advisor; §11
   no-silent-drop).**
   - **Persisted (store state, output/view-affecting):** `entries`, `precision`,
     `referenceTimeS` (v1 inventory slice); `doseDistanceM`, `doseQuantity`, `doseGeometry`,
     `exposureS` (dose); `shieldMaterial`, `shieldThicknessCm` (shield); `axis`,
     `activityUnit`, `massUnit`, `logY` (view); `cursorOffsetS` (time).
   - **Ephemeral (pure cosmetic / write-only entry fields, NOT output-affecting):**
     `Dose.svelte` `mode` (stacked↔grouped breakdown style) and `expUnit` (the display unit
     of the exposure entry — `exposureS` SI is the truth); `TimeControl.svelte`
     `gotoVal/gotoUnit/ageVal/ageUnit` (write-only "go to"/"set" entry fields with
     placeholders, not model mirrors). Documented here, not silently dropped.

5. **Component-local stale-display is a §11 wrong-but-quiet bug — fix it in THIS chunk, not
   end-polish (advisor).** Most view state reads the store directly (`Curves.svelte`
   axis/unit/logY; `TimeControl.svelte` cursor/source-age; `Shield.svelte` `thickStr` has a
   store→local sync `$effect`), so it round-trips. The exception is `Dose.svelte`:
   `distanceStr` and `expVal` are component-local `$state` with NO store→local sync — after a
   load that changes `doseDistanceM`/`exposureS` the input fields show stale values while the
   dose uses the loaded ones. Add the missing sync `$effect` (mirroring `Shield.svelte`
   lines 25–28). This is a prerequisite of the "identical views" round-trip, not polish.

6. **The consolidated register's real job is the items with NO inline home (advisor).** Most
   §11 items are already inline "next to the numbers" (point-source/no-air, separate γ/β
   quantities, buildup approximation, scoring floor, brems crossover) — keep them there (the
   spec's "not buried"). The new panel COMPLEMENTS, carrying chiefly the **degraded-trust
   provenance** that has no inline home: the photon **H*(10)** table is transcribed from an
   *unmerged* OpenMC PR #3256 (DEGRADED; cross-checked, see `docs/plans/M2-conversion.md`),
   while effective dose (ICRP-116) is CLEAN — plus the global "not for safety decisions",
   point-source/no-air, and the H*(10)-vs-effective non-comparability locks.

7. **Autosave (localStorage) stays DEFERRED — now an explicit decision, not a fall-through.**
   `persist.ts` originally deferred localStorage autosave "to M6h". M6h ships the portable
   FILE save/load round-trip (the source-of-truth path) but NOT autosave: it needs
   boot-restore wiring that interacts with the heavy Pyodide boot, and service-worker
   first-load caching is already a documented stretch. Recorded loudly here and in the
   `persist.ts` note (pointer updated), not silently skipped.

## Key files

- `web/src/lib/persist.ts` — `STATE_VERSION` → 2; `PersistableState` gains
  `dose`/`shield`/`view`/`cursorOffsetS`; `serializeState`/`deserializeState` extended with
  loud per-field validation (decision #2); autosave note updated (#7).
- `web/src/lib/state.svelte.ts` — `toPersistable` + `loadFromText` extended (the ordering
  trap, #3).
- `web/src/lib/Dose.svelte` — store→local sync `$effect` for `distanceStr`/`expVal` (#5).
- `web/src/lib/Honesty.svelte` — NEW: the consolidated register panel (#6).
- `web/src/App.svelte` — mount `<Honesty/>`; the top-of-page "not for safety decisions"
  disclaimer already present; label → (M6h).
- `web/drive_browser.mjs` — `runM6h`: discriminating full-state round-trip (#1) + DOM
  presence of disclaimer/register; wired into the runner.

## The gate (what "M6h done" means)

`drive_browser.mjs` keeps M6a–g and adds M6h, dev + built:

| check | asserts |
|---|---|
| full-state round-trip: non-default in every field → clear → load → rendered views identical AND serialize identical | the serializer can't silently drop a view-affecting field (#1) |
| load rejects out-of-range fields loudly (distance ≤ 0, bad enum, newer version) | validation lives in the deserializer, no silent clamp (#2) |
| honesty register + disclaimer render in the DOM (incl. degraded-trust H*(10) provenance) | the §11 register is a visible artifact (#6, §0) |
| a truncated-exposure window surfaces a visible banner (not silently extrapolated) | the no-silent-error warning path renders (§11; spec "warnings render") |

## Deferred / open (not M6h)

- **localStorage autosave + service-worker first-load caching** (#7) — post-v1 polish.
- **Prebuilt sources + teaching demos + chart-of-nuclides** — M7 (the neutron card,
  source-γ override, and (N,Z) layout are already wired/ready).
