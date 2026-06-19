# M6g — Shield builder

**Status:** done — gate green dev + built (M6a–f + 4 M6g checks); pytest green
(materials + dose_thickness reconciliation/monotonicity/fail-loud).
**Parent:** `docs/plans/M6-ui.md` (seventh M6 chunk; M6f dose is the upstream the
shield extends). **Milestone (HANDOFF_PLAN.md §10):** M6 UI. The §9 shield builder,
the §11 honesty register, and §12 units are the invariants this chunk must not violate.

## Goal

A single-layer shield hung off the existing dose calculator: pick a material +
thickness; the γ / β breakdown and all dose readouts recompute *through the shield*
(pure evaluate off the live handle — never a re-solve, §3). New outputs: dose
with/without shield + attenuation factor, a **dose-vs-thickness** band, a
**dose-vs-time** shielded-vs-unshielded overlay, and the **β-bremsstrahlung-in-shield**
secondary photon dose ("more lead can *increase* dose").

## Load-bearing decisions (a fresh session must not re-derive these)

1. **The engine already supports single-layer shields — M6g is plumbing + UI, not new
   physics.** `dose()`, `dose_lines()`, and `beta_dose()` all accept
   `shield=(material, thickness_cm)` (thickness in **cm**, §12). M6f wired none; M6g
   passes the shield through `recomputeDose`. The only new engine code is two *listing /
   sweep* endpoints (#2, #4), each TDD'd.

2. **γ-shield picker is RESTRICTED to the 8 ANS-6.4.3 buildup materials (advisor).**
   `GammaDoseModel` **raises** (`DoseError`) for a shield material with no buildup data —
   PMMA, polyethylene, tissue_soft (dose.py:33). Those are exactly the β/neutron-optimal
   low-Z/hydrogenous materials, so offering them would error out the *entire* γ panel on
   selection — a broken UI, not a graceful degrade (§11 forbids both the crash-looking
   state and a silent unshielded number). v1 therefore offers only the materials with
   buildup: **air, aluminium, concrete, copper, iron, lead, tungsten, water**. They span
   low-Z → high-Z, so the **aluminium-vs-lead bremsstrahlung contrast** (the M6g β
   deliverable) is delivered in full. The `has_buildup` flag from `materials()` (#2) is
   the no-drift gate — the UI never hardcodes the list.
   - **DEFERRED to M7 (consistent with neutron already being M7):** PMMA/polyethylene and
     the §9 "steer neutron → hydrogenous" guidance. Neutron dose is grayed for user
     inventories, so **nothing in v1 consumes hydrogenous steering** — trimming it now
     costs no v1 capability. (Recorded loudly here, not silently dropped.)

3. **`materials()` bridge endpoint is the no-drift material source.**
   `-> {ok, materials:[{id, has_buildup, density_g_cm3}]}` from
   `attenuation.available_materials()` × `buildup.has_material()`. The UI filters the γ
   picker to `has_buildup`. Radiation-type guidance (high-Z → brems warning) is a small
   curated map in `types.ts` keyed by id — UX guidance, NOT silently-dangerous data, with
   the engine's fail-loud as the backstop.

4. **Dose-vs-thickness = Design-A, the dose_lines analog (advisor; M6f-2 #10).** Thickness
   transmission `B(E,μx)·exp(−μx)` is nonlinear and per-line, so — unlike the γ
   dose-vs-**distance** band (exact inverse-square, reconstructed client-side) — it **must**
   come from the engine. `dose_thickness()` returns DISTANCE- and TIME-free per-nuclide
   coefficients `C_n(x)` over a client-supplied thickness grid; the client folds `1/4πd²`
   and `A_n(cursor)` → a curve that is **live on scrub and distance with zero re-fetch**,
   recomputed only on (material, quantity, geometry, thickness-grid) change. **`x=0` is
   evaluated with `shield=None`** so the curve's zero point is the exact unshielded baseline.
   **Reconciliation invariant (the anti-drift test):** the client guarantees the
   currently-selected thickness is a grid point, so the swept curve's value there equals
   the breakdown bar's γ rate **exactly** (one `GammaDoseModel` assembly path — the
   `dose_lines` Σ==card analog).

5. **Attenuation factor is an AT-CURSOR ratio, not a constant.** The unshielded baseline is
   spectrum- and time-dependent, so `recomputeDose` computes an unshielded γ series
   alongside the shielded one (only when a shield is active) and the factor =
   shielded/unshielded **at the cursor** — labelled "at cursor", never a global μx number.

6. **β-bremsstrahlung-in-shield is surfaced, not just plumbed (M6g deliverable).** `beta_dose`
   already returns a secondary `bremsstrahlung` γ-dose series when a shield is present (the
   β-stopping shield is photon-thin → brems scored with `shield=None`, documented §11). M6g
   captures it as its own series and shows the "more lead → more (photon) dose" readout +
   the high-Z warning. It is a **γ (Sv) quantity**, shown next to — never summed into — the
   β skin (Gy) number (§6.2 LOCKED).

7. **Shield state is TRANSIENT in M6g (persist → M6h).** `shieldMaterial`,
   `shieldThicknessCm` are output-affecting state like the M6d cursor and the M6f dose
   inputs; following that precedent they stay transient here, and the versioned-serializer
   extension + full round-trip test land in M6h (NOT a silent drop, §11).

## Key files

- `engine/bridge.py` — `materials()`, `dose_thickness()`.
- `tests/test_bridge.py` — material listing + the dose_thickness reconciliation/monotonicity.
- `web/src/lib/bridge.ts` — `MaterialInfo`, `DoseThicknessOk`, `materials()`,
  `dose_thickness()`; beta response extended to carry `bremsstrahlung`.
- `web/src/lib/types.ts` — `MATERIAL_GUIDANCE` (radiation-type tags / high-Z brems flag).
- `web/src/lib/state.svelte.ts` — shield state + setters, `availableMaterials`,
  `recomputeDose` shield wiring, `attenuationFactorAtCursor`, `bremsRateAtCursor`,
  `gammaThicknessCurve`.
- `web/src/lib/Shield.svelte` — the shield builder view (pure renderer).
- `web/src/App.svelte` — mounts `<Shield/>`; label → (M6g).
- `web/drive_browser.mjs` — `runM6g`.

## The gate (what "M6g done" means)

`drive_browser.mjs` keeps M6a–f and adds M6g, dev + built:

| check | asserts |
|---|---|
| add lead shield: γ rate drops, attenuation factor < 1, handle stable, registry stays **1** | shield is a pure evaluate (§3, #1), never a re-solve |
| dose-vs-thickness curve at the selected thickness == breakdown bar γ rate (rel < 1e-6) | the two engine paths can't drift (#4, the Σ==card analog) |
| lead vs aluminium β-brems: lead's bremsstrahlung γ rate > aluminium's | high-Z brems contrast renders (#2, #6) |
| material picker lists only `has_buildup` materials (no PMMA/poly/tissue) | the fail-loud trap is sidestepped (#2) |

## Deferred / open (not M6g)

- **Shield persistence + round-trip → M6h** (#7).
- **Honesty-register surfacing of the shielded state → M6h.** M6g adds a "through
  <material> <x> cm" tag to the Dose panel header so a shielded number is never read as
  bare (advisor §11 flag — the dose card silently drops when a shield is active). The
  fuller in-app honesty register (per-modality accuracy tooltips, scoring-floor / buildup-
  approximation notes next to the numbers) is M6h's job.
- **PMMA / polyethylene + "steer neutron → hydrogenous" → M7** (#2) — neutron has no v1
  consumer.
- **Multi-layer stack → post-v1** (§13 #2; single-layer is unambiguous for buildup).
