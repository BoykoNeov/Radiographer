# Follow-up — beta skin-dose ~30 s freeze on a large inventory (vectorize the Loevinger kernel)

**Status:** RESOLVED (2026-07-02). The 8000-point contact integral now evaluates the Loevinger
kernel with one vectorized numpy call per branch instead of an 8001-iteration Python loop. Cold
fallout load dropped from ~30 s to ~2.2 s; dose numbers unchanged to float precision (7e-16). A
regression test asserts the vectorized kernel matches the scalar one. See "Resolution" below.
**Severity:** UX — clicking the 177-nuclide fission-product fallout source (§13 #5) froze the
whole tab for ~30 s (a single synchronous main-thread block), with the browser on the edge of its
"page unresponsive" dialog and the headless gate racing its click timeout. Not wrong, just frozen.

## Symptom
Loading the fallout catalog source (or any large beta-emitting inventory) freezes the renderer for
~30 s. The earlier gate fix (commit 560d959) bumped the source-click timeout to 120 s so the gate
stopped flaking, but explicitly did **not** address the freeze itself — see
[[gate-fallout-30s-freeze]].

## Root cause — profile, don't guess
A per-call profile of the whole `solve()` cascade (cold end-to-end for ground truth, warm
`__BRIDGE__` breakdown for attribution; script at
`M:\claud_projects\temp\radiographer-review\profile_fallout.mjs`) was decisive:

| call | before | after |
|---|---|---|
| solve (177-nuclide Bateman) | 50 ms | 50 ms |
| evaluate ×2 (curves + DAG activity) | ~100 ms | ~100 ms |
| chain | 18 ms | 18 ms |
| dose (γ) | 150 ms | 150 ms |
| dose_lines | 210 ms | 170 ms |
| decay_heat | 126 ms | 76 ms |
| internal_dose | 21 ms | 21 ms |
| **beta_dose** | **31,089 ms** | **661 ms** |
| **cold end-to-end** | **29–33 s** | **2.2–2.3 s** |

It was **not** the Bateman solve (50 ms) and **not** "many separable calls." It was one call —
`beta_dose` — at 98 % of the freeze, ~200× slower than the conceptually similar γ `dose` over the
same inventory. That gap is not inherent cost; it is an un-vectorized inner loop.

`engine/beta_dose.BetaSkinDoseModel._contact_dose_per_decay` builds an 8000-point radial grid
(`_radial_grid`) and, **per nuclide × per beta branch**, evaluated the Loevinger kernel with a
pure-Python list comprehension:

```python
total += y * np.array([loevinger_J(xi, e_max, ebar, self.rho_t) for xi in x])  # 8001 scalar calls
```

Across the 183-nuclide fallout closure (many multi-branch beta emitters) that is on the order of a
million+ interpreted scalar `loevinger_J` calls — each doing several `math.exp`/divisions — under
WASM CPython. The γ path is analytic/vectorized per line, hence 150 ms.

## Resolution
Vectorize the kernel over the radial grid. The per-branch constants (ν, c, z, t, α, B) do not
depend on `x`, so they are computed once and only the two distance-dependent terms are evaluated
over the array:

- New `engine/beta_dose._loevinger_J_array(x_cm, E_max, Ebar, rho)` — `np.exp`/`np.where` reproduce
  the scalar `math.exp` / the `x < t` branch element-for-element. `x_cm` is always ≥ the basal-layer
  depth > 0, so `B / x_cm` never divides by zero.
- `_contact_dose_per_decay` calls it once per branch instead of the list comprehension.
- The scalar `loevinger_J` is **left unchanged** — the energy-conservation and VARSKIN tests call it
  directly, and it stays the readable reference definition.

This is the "solve once, evaluate many" discipline intact: `dose_rate_series` still folds the fixed
per-nuclide coefficient against the activity grid; only the coefficient's construction got faster.

### Why not a worker or a progress bar?
The task framed the fix as "progress UI or off-thread solve." Profiling ruled both out: with the
freeze at ~2.2 s (below the frozen-tab / unresponsive-dialog threshold, and the store already paints
`status="solving"` via `yieldToPaint()` before the block), a Web Worker's async ripple + stale-
response guarding on every rapid setter change (the distance slider) is complexity a 2 s block does
not justify. The root-cause fix beat both named options for a fraction of the effort.

## Validation
- `tests/test_dose_beta.py::test_loevinger_array_matches_scalar_kernel` — asserts the vectorized
  kernel equals the scalar loop to `rtol=1e-12` across four endpoints (measured max diff 7e-16).
- Full suite green (503 passed, 1 skipped); the existing beta benchmarks (energy conservation,
  Co-60/VARSKIN, distributed-disk bracket, tritium-zero, distance monotonicity) unchanged.
- Browser gate green dev + built; re-profile confirms cold fallout load 2.2–2.3 s, longest
  main-thread freeze 2.25 s (was 29.2 s).

## If it needs to get faster still
`beta_dose` is now 661 ms (dominant but acceptable). Further wins, in order of safety, would be:
cache the radial grid on the model (it is rebuilt per `_contact_dose_per_decay` call); vectorize
across branches (stack `(branch, x)` into one 2-D `np.exp`); or reduce `_radial_grid` from 8000
points — but the last changes the dose numbers and would need re-validation, so it is a last resort.
