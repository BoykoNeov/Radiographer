# M3 — Gamma dose core

**Status:** done ✅
**Milestone (HANDOFF_PLAN.md §10):** point-kernel + inverse-square + attenuation +
G-P buildup, validated against the §10 benchmarks before moving on.

## Results (done)

- **`engine/photon_interp.py`** — edge-aware log–log `interp_mu_rho` / `interp_muen_rho`,
  B-space `interp_buildup`, log–log `interp_conversion`; pure `OffGridError(reason)`.
- **`engine/dose.py`** — `GammaDoseModel` (solve-once per-nuclide `C_n`),
  `dose_rate` / `dose_rate_series`, `transmission`, `DoseError`. SI internal; one
  conversion block.
- **`engine/bridge.py`** — `dose(handle, request_json)` closes the loop: one solve → one
  model → one matvec over the time grid; domain errors structured (no traceback).
- **Tests:** `tests/test_photon_interp.py` (18) + `tests/test_dose_gamma.py` (11) +
  2 bridge dose tests. **Full suite 158 pass**, no M0–M2 regression.
- **Validation:** Co-60 air-kerma **0.3056** vs lit 0.308 (−0.8 %); "1 Ci @ 1 m" → 1.30 R/h;
  Cs-137 via secular equilibrium (Cs-137 + Ba-137m spectra) **0.0766** vs lit 0.077 (−0.4 %);
  inverse-square exact; broad-beam HVL/TVL > narrow-beam and within ±30 % of named tables.

### Decisions resolved here

- **10 keV dose-scoring floor δ (all quantities).** Cs-137 came out +12 % until we matched
  the air-kerma-rate constant's defining cutoff: the soft Ba L X-rays (4–6 keV) inflate air
  kerma in the bare-point-vacuum model but transmit ~0.1 % through 1 m of air, so they don't
  reach a detector. The >10 keV band alone = 0.0767 (lit 0.077). Imposed via the existing
  logged-skip path; H\*(10)/effective already had it via the conversion grid → one rule now.
  Recorded in HANDOFF_PLAN §11. *Not* fixed by intervening-air attenuation (rejected: would
  make `C_n` distance-dependent and compute a different quantity — see §11 future-work note).
- **Air-kerma (exposure) buildup applied to all three quantities** — documented in §11.

## Goal

Turn the M2 datasets into an external **gamma dose-rate** engine for a point source,
and prove it against published constants. "Done" =

- A `GammaDoseModel` that, given the nuclides in a solved inventory + a dose quantity
  + optional single-layer shield, computes a dose-rate **time series** from the
  inventory's activity series — **without re-summing the line spectrum per slider tick**
  (§3 "solve once, evaluate many" applies to the dose layer too).
- The three energy-axis interpolators (`engine/photon_interp.py`) that own the
  off-grid contracts the M2 loaders deliberately deferred.
- Benchmarks passing (§ Validation), each anchored to a **named** reference.

## Plan

### Dose chain (§6), single layer (layered shield deferred — see Decisions)

```
dose_rate(d) = (1 / 4π d²) · Σ_nuclides A_n · Σ_lines [ per-line const ]_i · [ shield ]_i
[ shield ]_i = B(E_i, μ_i x) · exp(−μ_i x)          μ_i = (μ/ρ)_shield(E_i)·ρ_shield ;  μ_i x in mfp
```

Per-line constant depends on the **quantity**, never on distance/time/activity:

- `air_kerma` (validation + teaching): `E_i[J] · y_i · (μ_en/ρ)_air(E_i)[m²/kg]`  → Gy/s
- `ambient_H10` (§6.4 default): `y_i · h*(10)/Φ(E_i)[Sv·m²]`                       → Sv/s
- `effective`  (§6.4, needs geometry): `y_i · e/Φ(E_i, geom)[Sv·m²]`              → Sv/s

The **shield factor multiplies fluence**, so it is identical across all three quantities
(it attenuates the photon field, not the scoring). The buildup B applied is the
**air-kerma (exposure)** buildup for *all* quantities — a documented approximation
(B of dose-equivalent ≠ B of air-kerma); see honesty register update below.

### Solve-once factorization (the interface decision)

Precompute, once per (quantity, medium, shield, geometry):

```
C_n = Σ_lines [ per-line const ]_i · [ shield ]_i      # SI per decay, one scalar per nuclide
```

Then evaluate-many is a single matvec against the activity series from
`inventory.SolvedInventory.evaluate(axis="activity", unit="Bq")`:

```
dose_rate(t, d) = (1 / 4π d²) · Σ_n C_n · A_n(t)
```

Distance is a free scalar (1/4πd² factors out of every quantity). Only a shield or
quantity change re-folds `C_n`. **Do not** write `dose_rate(activities, d, shield,
quantity)` and call it per tick — that re-folds the line sum every slider move.

### Two-severity off-grid policy (no silent errors, but the right severity)

Interpolators stay **pure**: raise `OffGridError(reason=BELOW_FLOOR | ABOVE_GRID)`.
The **dose engine owns the policy** (it knows the line *and* the quantity, and grid ends
are quantity-specific):

- **BELOW_FLOOR** (1 keV attenuation / 10 keV conversion / 15–30 keV buildup) → **logged
  skip**: low energy × usually tiny yield ⇒ negligible dose. Recorded in a structured
  `warnings`/`skipped` list in the result (Python `logging` is invisible in Pyodide;
  §11 wants these on screen).
- **ABOVE_GRID** (>10 MeV H\*(10); >15 MeV buildup; >20 MeV attenuation) → **loud
  `DoseError`**: dropping a high-energy line *underestimates* dose — the dangerous
  direction for a tool people may trust (§11). Won't fire for ordinary decay gammas
  (≤ ~2.6 MeV) but is enforced.

Stable / no-emission nuclides in the closure contribute `C_n = 0` (legitimate — a stable
daughter is not a data hole); a *radioactive* nuclide with no emission file still raises
in the loader.

### Edge-aware interpolation (the one that bites)

`data/attenuation/*.json` duplicates the energy at absorption edges (Pb K-edge 0.0880045
appears twice: μ/ρ 1.91 just below, 7.683 just above). A naive `np.interp` straddling the
edge returns the wrong side. The interpolator must select the bracketing segment with
**distinct** endpoints (log–log within the segment), never interpolate across a
zero-width edge step. Tested at 0.085 MeV (pre-K-edge segment) and 0.09 MeV (post-edge).

Buildup interpolation is in **B-space, not coefficient-space**: the G-P coefficients (Xk
especially) are not smooth in energy, so evaluate `B` at the two bracketing grid energies
(via `engine.buildup.gp_buildup`) and interpolate **ln B vs ln E**.

## Key files & decisions

- `engine/photon_interp.py` — `interp_mu_rho`, `interp_muen_rho` (edge-aware log–log),
  `interp_buildup(material, E, mfp)` (B-space log-E), `interp_conversion(quantity, E,
  geometry)` (log–log); `OffGridError(reason)`. Pure; no dose policy.
- `engine/dose.py` — `GammaDoseModel`, `DoseError`; SI internally, convert to
  Gy/Sv/R + per-hour at the boundary in one place.
- `tests/test_photon_interp.py`, `tests/test_dose_gamma.py` — written first (TDD).
- Bridge entry point in `engine/bridge.py` for dose-rate over a handle's activity series.

### Decisions

- **§6.4 layered-shield buildup OPEN — DEFERRED (not resolved).** M3 ships **single-layer**
  shields only, where buildup is unambiguous. The Pb-then-water "whose B?" question
  (last-layer vs Harima–Kitazume) is chosen later, before the multi-layer shield UI (M6)
  lands. HANDOFF_PLAN §6.4 / §13 stays OPEN.
- **Air-kerma buildup used for all three quantities** — documented approximation; added to
  the §11 honesty register this milestone.

## Validation benchmarks (§10) — each with a named reference

- **Co-60 air kerma**: 1 GBq @ 1 m, unshielded ⇒ ≈ **0.308 mGy·m²·GBq⁻¹·h⁻¹** (air-kerma
  rate constant Γ; e.g. NIST/IAEA). Tol ±3 %. Hand-check: 0.307. Propagates to
  "1 Ci Co-60 @ 1 m ≈ 1.30 R/h" (1 R = 8.76 mGy air kerma).
- **Cs-137 air kerma**: load Cs-137, decay to secular equilibrium, **sum Cs-137 + Ba-137m**
  spectra (the 0.662 line is Ba-137m's, scaled by the 0.944 branch ⇒ ≈0.85 γ/decay) ⇒
  ≈ **0.077 mGy·m²·GBq⁻¹·h⁻¹** (Unger & Trubey). Tol ±10 %. This is the real end-to-end
  coupling test (must NOT hardcode 0.662 onto Cs-137).
- **Inverse-square**: dose ∝ 1/d² exactly.
- **Broad-beam HVL/TVL** (attenuation + buildup): solve `B·exp(−μx) = 0.5` (and 0.1) for x;
  HVL_broad > HVL_narrow (= ln2/μ); compare to a named shielding table with a **loose**
  tolerance (point-isotropic B vs broad-beam slab geometry differ — honest caveat).

## Open questions / risks

- Geometry mismatch in the HVL/TVL check: our buildup is point-isotropic-source-in-
  infinite-medium *exposure* B; published HVL/TVL are often broad-beam slab. Validate the
  *direction* (buildup increases penetration) tightly; the absolute match loosely + named.
- `medium` for `air_kerma` is `air` in v1; tissue/water kerma is a trivial extension once
  needed (data already bundled).
