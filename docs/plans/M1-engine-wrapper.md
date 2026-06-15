# M1 — Engine wrapper

**Status:** done ✅
**Milestone (HANDOFF_PLAN.md §10):** Python module exposing inventory solve
(double + on-demand HP), chain DAG edge list, and time evaluation, returning
JSON/arrays. Bridge to a trivial JS harness.

## Results (done)

- **42 native tests pass** (`pytest`, reuse `m0/.venv` + `PYTHONUTF8=1`).
- **Solve-once delivers the perf rule:** native per-eval **0.35–0.96 µs**
  (~240–680× faster than rd's per-`.decay()` re-solve); a 2000-point grid in
  <2 ms. **In real Chrome/WASM: 7.8 µs/eval** — still microseconds, far under
  the M0 ~0.65 ms naive cost. Browser harness PASS (Pyodide 1.2 s + install
  2.1 s).
- **The validity floor is per-nuclide, not global** — the one non-obvious
  numerics decision. A global atom-scaled floor wrongly zeroed short-lived
  daughters with tiny atom counts but large activities (Po-212: 300 ns,
  ~5e-7 atoms, ~1.28 Bq). Replaced with the per-row cancellation bound
  `noise_i = NOISE_SAFETY·eps·Σ_j|C[i,j]·P_j|`: clip `|N|<noise` to 0, raise on
  a negative beyond `-noise`. Verified it preserves all meaningful daughters,
  clips U-238's deep deep-chain garbage at t=1 d, and never false-raises.
- HP path recovers deep-chain truth (U-238 Th-230 ~9.2e-19 Bq) the double path
  honestly floors to 0.

## Goal

A pure-Python physics-core package (`engine/`) that runs unchanged natively
(fast pytest loop) and in Pyodide (browser evidence), exposing across a clean
JSON bridge:

1. **Inventory solve** with the *true* **solve-once / evaluate-many** path
   (HANDOFF_PLAN §3) — factorize once, evaluate a whole time grid cheaply.
2. **Chain DAG** node + edge list (nuclide topology with Z/A, half-life, decay
   modes, branching) for the Cytoscape view (§8/§9), including reconvergence.
3. **Time evaluation** returning plain arrays per axis (atoms / activity / mass).

"Done" = the native regression suite passes (solve-once reproduces
`radioactivedecay` to ~1e-12 on meaningful nuclides; deep-chain doubles proven
to be *known noise* vs an HP truth, not silently tolerated; DAG reconverges;
bridge round-trips) **and** the browser harness runs the same engine in Pyodide.

## Plan / accepted approach

### Solve-once math (validated empirically before coding)
`radioactivedecay` solves `N(t) = C · diag(exp(−t·λ)) · C⁻¹ · N₀` but re-runs the
whole sparse multiply on every `.decay()`. We factorize:

- once: restrict to the **descendant-closure index set** of the loaded nuclides
  (closed under the operation — proven), take dense submatrices `C`, `C⁻¹`, `λ`,
  `N₀`, and precompute `b = C⁻¹ N₀`.
- per time grid: `N(t) = C · (exp(−t·λ) ⊙ b)`, vectorized over all times as one
  matmul `(E * b) @ Cᵀ`.

Verified: reproduces `rd.decay()` to machine precision on meaningful nuclides
(Cs-137, Mo-99, U-238 head, mixed Th-232+Co-60).

### Two floors — the engine validity floor is M1's job (no-silent-errors)
Below `peak · 1e-15` (in **atoms**, where the cancellation happens) double
precision is meaningless — `rd` itself returns garbage/negatives there (U-238
deep daughters). The engine must not hand that out as real:

- clip `|N| < floor` to 0 (noise → honest zero), report `floor`/`peak`;
- a **negative above the floor** is a loud `EngineError` (real bug or a chain too
  stiff for double → recommend `precision='hp'`), never silently clipped.

This is distinct from the M6 **UI display floor** (the 12–15-decade log-axis
clip, §9) — looser, presentational. Don't conflate them.

### Metadata from the solve (§9)
`solve()` returns: closure nuclide list + half-lives, the **auto time-range**
`[0.01·min_finite_t½, 10·max_finite_t½]` (s), and **`hp_recommended`** when the
finite half-life span over the closure exceeds ~1e12.

### HP — minimal, on-demand (advisor-confirmed)
`precision='hp'` evaluates via `rd.InventoryHP.decay(t)` per requested time
(slow, exact). No sympy solve-once. The slider uses double only; HP is the
"computing…" path for a few specific times. No validity-floor clip in HP (it's
exact); negatives still raise.

### Bridge — registry + branded string handle
Stateful solve-once means JS keeps a handle, not a re-solve. Pure JSON in/out
(no PyProxy lifetime issues, native-testable): `solve(spec)→{handle,meta}`,
`evaluate(handle,req)→{series}`, `chain(handle)→{nodes,edges}`, `release(handle)`.
Errors cross as a loud structured `{"ok":false,"error":{type,message}}`, never a
fallback number.

### DAG — shares the solve's closure
Nodes = the same closure set (no recompute → no drift). Each node carries Z, A,
N=A−Z (free from `rd.Nuclide`, needed for the locked (N,Z) chart layout §8/§9).
Edges = every closure member's direct progeny (reconvergence falls out). The
spontaneous-fission branch is the pseudo-target `'SF'` → emitted as an honest
terminal "fission products" sink node; a *real* progeny outside the closure
raises (drift guard).

## Key files & decisions

- `engine/inventory.py` — `SolvedInventory` (solve-once, evaluate-many, floor,
  metadata, HP path), `EngineError`, unit constants.
- `engine/chain.py` — `build_dag(solved)` → nodes/edges.
- `engine/bridge.py` — registry + JSON facade.
- `tests/` — `test_inventory.py`, `test_chain.py`, `test_bridge.py`.
- `web/index.html` (+ driver) — Pyodide harness loading `engine/` and exercising
  the bridge in-browser.
- `pyproject.toml` — pytest config (`pythonpath=["."]`).

Dev env: reuse `m0/.venv` (pinned rd 0.6.1 / numpy / scipy) + pytest. Native runs
need `PYTHONUTF8=1` (decay-mode strings contain β/α).

## Open questions / risks

- **HP path unverified in Pyodide.** The browser harness exercises the *double*
  path only; the on-demand `precision='hp'` path (sympy/mpmath) has run natively
  but never in WASM. Low risk — M0 confirmed sympy loads in Pyodide — but verify
  when the UI first wires the "computing…" HP button (M6).
- HP evaluate-many is O(times) slow solves; acceptable for v1 (rare, few times).
- `'SF'` sink is topology-only; neutron/fission source terms remain M5/tabulated.
- Browser engine-loading uses a file manifest written into the Pyodide FS; if the
  package grows (M2 datasets) revisit zip/wheel packaging.

## Hardening tests added (advisor follow-up)

- **Overlapping multi-species load** (`{Mo-99, Tc-99m}`, `{U-238, U-234}`): the
  union-closure `b = C⁻¹·n0` with multi-entry `n0` is exact at t=0
  (`C·C⁻¹·n0 = n0`) and tracks rd at non-zero time — the generator/aged-source
  case M2+ depends on.
- **No-false-raise sweep** across 32 isotopes × 3 axes over each one's extended
  auto-range: the `N < -noise` honesty guard never false-fires on valid input.
