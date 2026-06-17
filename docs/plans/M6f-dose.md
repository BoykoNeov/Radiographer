# M6f — Dose calculator + breakdown

**Status:** M6f-1 in progress.
**Parent:** `docs/plans/M6-ui.md` (sixth M6 chunk; M6a boot, M6b inventory/state,
M6c curves, M6d time control). M6e (chain DAG) is a sibling consumer of the same
M6d contract and is **not a dependency** — M6f was taken next by user request.
**Milestone (HANDOFF_PLAN.md §10):** M6 UI. **Resolves §13 #3** (effective-dose
default geometry). The §9 dose calculator, the §11 honesty register, and §12 units
are the invariants this chunk must not violate.

## Goal

A live dose calculator hung off the solved inventory: inputs = distance + exposure
time; outputs = the dose-rate at the cursor time and the accumulated dose over the
exposure window, broken down by radiation type (γ / β / n). Selectable **H\*(10)**
(default) vs **effective + geometry**; neutron grayed out for user inventories
(§6.3 gate). One Bateman solve, evaluated many (§3) — the dose path is a **pure
evaluate** off the live handle and never re-solves.

## Load-bearing decisions (a fresh session must not re-derive these)

1. **γ and n are Sv; β is Gy — they are DIFFERENT QUANTITIES and are NEVER summed
   (advisor; invariant #5; §6.2 LOCKED).** `dose()` (γ) and `neutron_dose()` (n)
   return **Sv** (H\*(10) or effective). `beta_dose()` returns **Gy at 7 mg/cm²**
   — the skin dose Hp(0.07) (w_R=1), a different depth/geometry/meaning. The §9
   "linear stacked bar (γ + β + n = total)" must therefore be read as
   **same-quantity-only**: the stacked total is **γ (+ n when a prebuilt source
   exists), in Sv**; **β rides as a separate, clearly-labelled element in its own
   Gy / Hp(0.07) panel**, shown alongside but **never added** to the Sv total. For
   a user inventory (neutron grayed) the Sv group is γ-only — a degenerate single
   segment now; the stack/grouped-log machinery is built ready and becomes a real
   stack the moment a neutron source lands (M7). This shapes the data model: we do
   NOT feed three segments into one summed scale.

2. **Accumulated dose INTEGRATES, never rate×time (advisor; §11).** rate×exposure
   silently overestimates whenever the window ≈ a half-life (6 h on Tc-99m → ~30%
   high) — the wrong-but-quiet failure §11 forbids. Coefficients are
   time-independent, so ∫rate dt = Σ Cₙ ∫Aₙ(t) dt: we **trapezoid-integrate the
   dose-rate series** over `[currentTimeS, currentTimeS + exposureS]`. Pure
   evaluate-many, no engine change.

3. **The dose is "solve once, evaluate many" exactly like the curves: a per-(distance,
   quantity, geometry) RATE SERIES over the curve grid, then cursor-INDEX.** Rather
   than call `dose()` per cursor tick, the store computes the γ/β dose-rate series
   over the **same `curveX` display grid** as M6c (evaluated at the absolute times
   `referenceTimeS + curveX`), once per inventory × distance × quantity × geometry.
   The cursor then **interpolates** that series at `cursorOffsetS` for the live
   breakdown bar, and the accumulated integral is a trapezoid over the same series
   — so **scrub and animate make zero bridge calls** (the M6d smooth-slider payoff,
   §3). Recompute triggers mirror the curves' (solve, source-age t₀) **plus** the
   dose-specific inputs (distance, quantity, geometry). The cursor and exposure are
   pure client-side derives — they never recompute the series. The dose path must
   **never** route through `state.solve()` (gate asserts registry stays 1 across a
   distance change).

4. **§13 #3 RESOLVED — effective-dose default geometry = AP.** For a point source at
   a stated distance the implied scenario is a person *facing* it, so AP is both the
   physically natural geometry and the conservative one (AP gives the highest E in
   ICRP-116 for a frontal photon field). Low-stakes: H\*(10) is the primary/default
   quantity and geometry is a visible, changeable dropdown — but a default must be
   picked and recorded (done here **and** in HANDOFF_PLAN §13). The dropdown offers
   AP / PA / ISO / LLAT / RLAT / ROT (the six ICRP-116 geometries shipped in M2).

5. **Color: modality palette for the γ/β/n bar; species palette (#4) lives in the
   per-line gamma table (M6f-2).** The breakdown bar is per-*modality* (the bridge
   sums over nuclides → one γ number, one β number), so it uses a small fixed
   modality palette, not the per-species colors. Invariant #4's "dose breakdown
   shares one color per species" is satisfied where species actually appear: the
   **per-line gamma table** (lines colored by parent nuclide), which is M6f-2.

6. **Distance is shared by γ and β; v1 requires distance > 0.** Both modalities read
   the one distance input. γ's point-source field is singular at 0 (loud error);
   contact beta (distance 0, the dominant real β scenario) is a deferred nuance.
   Default distance 1 m. β at 1 m is air-attenuated to near-nothing — that honest
   "β is irrelevant at this distance" sliver is the §9 teaching point, not a bug.

## M6f-1 / M6f-2 split

- **M6f-1 (this slice):** cursor-time γ/β breakdown (same-quantity stacked + grouped-
  log toggle), H\*(10)/effective + geometry, distance + exposure inputs, accumulated
  dose by integration, neutron grayed, warnings surfaced, units labelled. Gate:
  Co-60 H\*(10)@1 m benchmark through the rendered path + pure-evaluate invariants.
- **M6f-2:** uncertainty made visible (fill bands on dose-vs-distance; error whiskers
  on the grouped-log bar — γ ±10–15 %, β ±20–30 %, n order-of-mag) + the **per-line
  gamma table** (needs a new `dose_lines` bridge endpoint exposing
  `GammaDoseModel._per_line_constant_si` × cursor activity, colored by species, #4).
  Note: dose-vs-**thickness** is M6g (shield), not here.

## Key files

- `web/src/lib/dosemath.ts` — pure, testable helpers: `interpAt` (cursor index into
  a series), `trapzWindow` (the accumulated integral), and SI dose-rate / dose
  formatting (`formatDoseRate`, `formatDose` → auto n/µ/m prefix, rate per hour).
- `web/src/lib/types.ts` — `DoseQuantity`, `DOSE_QUANTITY_OPTIONS`, `GEOMETRY_OPTIONS`,
  `DEFAULT_GEOMETRY = "AP"`, `MODALITY_COLORS`.
- `web/src/lib/state.svelte.ts` — dose inputs (`doseDistanceM`, `doseQuantity`,
  `doseGeometry`, `exposureS`); `gammaDoseSeries` / `betaDoseSeries` (rate_si over
  `curveX`); `recomputeDose()`; setters; wired into `solve()` and
  `setReferenceTimeS()` (recompute series), with cursor/exposure as pure derives.
- `web/src/lib/Dose.svelte` — the calculator + breakdown (pure renderer).
- `web/src/App.svelte` — mounts `<Dose/>`; label → (M6f).
- `web/drive_browser.mjs` — `runM6f`.

## The gate (what "M6f-1 done" means)

`drive_browser.mjs` keeps M6a/b/c/d and adds M6f checks, through the rendered path
(dev + built):

| check | asserts |
|---|---|
| **Co-60 H\*(10)@1 m benchmark** read off the rendered γ rate equals an independent `dose()` call AND ∈ the M3 band (0.308 mGy·m²·GBq⁻¹·h⁻¹ × H\*(10)/Kₐ ≈ 1.05–1.30) | UI plumbs the validated number, not a fabricated one (§11) |
| change distance 1→2 m: handle stable, registry size stays **1**, γ rate drops **4×** | dose is a pure evaluate (§3, #1/#2), inverse-square renders |
| β shown as a separate **Gy / Hp(0.07)** element; γ total is **Sv** and excludes β | quantities never summed (#1, §6.2 LOCKED) |
| neutron element grayed with the "prebuilt sources only" note for a user inventory | §6.3 gate |
| effective + AP geometry: dropdown appears, dose recomputes, registry stays 1 | §13 #3 path live, still pure-evaluate |
| short-lived source over a ~half-life window: accumulated < rate@cursor × exposure | accumulated INTEGRATES, not multiplies (#2, §11) |

## Deferred / open (not M6f-1)

- **Dose-input persistence → M6h** (NOT a silent drop, §11). `doseDistanceM`,
  `doseQuantity`, `doseGeometry`, `exposureS` are output-affecting state, like the
  M6d cursor. Following the M6d precedent they stay **transient** in M6f-1; the
  versioned-serializer extension + the full round-trip test land in M6h (where the
  cursor restore-after-solve ordering trap is also handled). The M6b serializer is
  untouched here.
- **Per-line gamma table + uncertainty viz → M6f-2** (decision #5).
- **Cross-quantity bar comparison is intentionally NOT offered (advisor).** The
  breakdown bar gives γ and β their own y-axes (Sv, Gy), each auto-ranging to its
  own bar — so the heights are deliberately **not** comparable across quantities
  (comparing Sv to Gy magnitudes would itself be the §6.2 violation). The cards
  carry the true magnitudes; the §9 "negligible sliver" framing only applies
  *within* a quantity, which becomes a real stack once a neutron source adds an n
  contributor to the Sv axis (M7).
- **Contact beta (distance 0) → future** (decision #6).
- **Neutron dose for prebuilt sources → M7** (the `neutron_dose` path is built but
  exercised only when a source with a `source` key is loaded; user inventories gray
  it out).
