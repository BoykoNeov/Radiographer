# Follow-up — γ buildup OverflowError for thick high-Z + a low-energy line

**Status:** RESOLVED (2026-06-19). Buildup argument capped at the ANS-6.4.3 fit limit;
the OverflowError is gone, the §11 honesty note is surfaced, and regression tests guard it.
See "Resolution" below.
**Severity:** a single shield/line combination crashes the whole γ dose panel with a raw
`OverflowError`. Loud (not silent), but cryptic and over-broad. Pre-existing in the M6g/M3 γ path.

## Symptom
A γ dose request through a thick high-Z shield for a source with a LOW-ENERGY line raises
`OverflowError: (34, 'Result too large')` from the bridge. Reproduced with **no neutrons involved**:

```python
res = json.loads(bridge.solve(json.dumps({"nuclides": {"Am-241": 1.0}, "unit": "Ci"})))
out = json.loads(bridge.dose(res["handle"], json.dumps(
    {"times_s": [0.0], "quantity": "ambient_H10", "distance_m": 1.0, "shield": [["lead", 5.0]]})))
# out["ok"] is False, out["error"]["type"] == "OverflowError"
```

Am-241's 59 keV line through 5 cm lead is ~hundreds of mean free paths. The same bites Cf-252
(its low-E lines) — which is why M10's natural "shield a neutron source with lead, watch it do
nothing to neutrons" action trips it.

## Root cause
`engine/buildup.gp_buildup` computes the geometric-progression buildup
`B = 1 + (b−1)·(K^mfp − 1)/(K − 1)`. At mfp in the hundreds, `K^mfp` overflows float64. The
ANS-6.4.3 / NUREG-CR-5740 G-P fits are validated only to ~40 mfp; beyond that the formula is both
numerically unstable and physically meaningless. The transmitted fluence there is
`B·exp(−mfp) ≈ B·e^(−hundreds) ≈ 0` — the contribution is negligible, the overflow is an artifact.

**Note:** a naive "compute `B·exp(−mfp)` together to tame the growth" reassociation does NOT
generally fix it — at large mfp the G-P ratio `K(mfp)` likely exceeds e, so the combined form
`exp(mfp·(ln K − 1))` diverges the other way (advisor). The fix must address the EXTRAPOLATION,
not the float association.

## Proposed fix (its own task — physics + honesty, do not rush)
Cap the buildup **argument** at the table's validated mfp (e.g. clamp `mfp_eval = min(mfp, mfp_max)`
where `mfp_max ≈ 40`), and keep the exact `exp(−mfp)` attenuation at the TRUE mfp. The buildup is
then frozen at its last-valid value while the exponential drives transmission → 0 — bounded and
physically reasonable (the deep-penetration buildup of an already-negligible component). Surface a
§11 honesty line ("buildup extrapolated/capped beyond the fit range for very thick high-Z") and add
a regression test (Am-241 59 keV + thick lead → finite, ~0 transmission, no raise). Repairs M6g for
**every** low-energy source, independent of neutrons.

## Resolution (2026-06-19)
Implemented exactly as proposed — cap the **argument**, keep `exp(−mfp)` exact:

- `engine/buildup.py`: new constant `MFP_FIT_MAX = 40.0` (the ANS-6.4.3 / NUREG-CR-5740 fit
  validity bound). `gp_buildup` now clamps `mfp = min(mfp, MFP_FIT_MAX)` *inside the buildup
  formula only* — so `B` freezes at `B(40)` for deeper penetration and `K**mfp` can no longer
  overflow. No-op at/below 40 mfp, so every algebraic identity and tabulated check point is
  bit-for-bit unchanged. The lowest layer is capped so **every** caller is protected.
- `engine/dose.py`: `transmission`/`stack_transmission` now route through one shared core
  `_stack_transmission(layers, E) → (T, total_mfp)` (keeps the exact-equality n=1 reduction).
  `GammaDoseModel._lines_for` compares `total_mfp` against `buildup.MFP_FIT_MAX` (single source
  of truth — never a hardcoded 40) and, per nuclide, appends one aggregated §11 warning
  `reason="buildup_capped"` when deep lines were frozen. The exact `exp(−Σμx)` attenuation is
  unchanged, so the transmission of those deep lines is ~0 and the dose moves negligibly.
- `web/src/lib/Dose.svelte`: generalized the warnings `<summary>` copy (the list now also
  carries buildup-cap notes; the `reason` field distinguishes them).

**Tests added:** `tests/test_buildup_data.py` — `gp_buildup` finite + frozen at the limit for
100–1000 mfp (no raise), no-op ≤40; `tests/test_dose_gamma.py` — Am-241 `ambient_H10` through
5 cm lead builds with finite `coeff_si`, transmission `0 ≤ T < 1e-15`, and a `buildup_capped`
warning present.

**Verified:** the doc's exact bridge repro (`bridge.solve` Am-241 1 Ci → `bridge.dose`
`ambient_H10`, 1 m, `[["lead", 5.0]]`) now returns `out["ok"] is True` (was `OverflowError`);
full `pytest` green; `npm run build` 0 errors; built browser harness green (the M10 Cf-252 +
lead case now reports `γFailed=false`). The M10 JS containment split
(`recomputeGammaBeta`/`recomputeNeutron`) stays as defense-in-depth.

## What M10 did about it (containment only)
Made the γ/β and neutron dose paths fail INDEPENDENTLY (`state.svelte.ts`: `recomputeDose` split
into `recomputeGammaBeta` + `recomputeNeutron`). A γ overflow now clears only the γ/β series and
sets `doseError`; the neutron card still renders (lead → `T_n=1` + steer-to-hydrogenous). The
underlying γ crash is unchanged — only its blast radius. See `docs/plans/M10-neutron-shielding.md`.
