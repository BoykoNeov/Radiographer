# M0 — Pyodide smoke test

**Status:** done
**Milestone (HANDOFF_PLAN.md §10):** In Pyodide, in target browsers, install
`radioactivedecay`, solve a known chain (Cs-137), confirm it works and time it.
Kills the project early if the foundation doesn't hold.

## Goal

Prove the client-side physics foundation holds and is fast enough, with a *real
validation* (a physics invariant), not just "nothing threw". Resolve the M0 part
of §13 OPEN #6: pin Pyodide + `radioactivedecay` versions and determine the
spectral-data access path.

**Verdict: the foundation holds.** ✅

## What was built

All under `m0/` (self-contained; M1 will establish the real `engine/` + `web/`
structure):

- `m0/smoke.py` — single source of truth. `run_smoke() -> dict`. Runs unchanged
  in two hosts: native CPython 3.14 (fast dev loop) and Pyodide 314 (browser
  evidence). Asserts a physics invariant, times compute, probes the spectral path.
  No silent errors: failures are captured into the result and flip `overall_pass`,
  never swallowed or replaced with a fabricated number.
- `m0/index.html` — the browser harness (the deliverable). Loads Pyodide from the
  jsDelivr CDN, `micropip.install("radioactivedecay")`, runs `smoke.py` as a
  module, and **renders versions + timing + pass/fail to the DOM**. Exposes
  `window.__M0_RESULT__` / `window.__M0_DONE__` for automation.
- `m0/drive_browser.mjs` — Playwright driver. Serves `m0/` over http, drives
  `index.html` headless in the **installed Chrome** (`channel: "chrome"`, no
  browser-binary download), waits for the in-page result, exits non-zero on fail.
  This is the *real* evidence: real WASM engine, real CDN load, real timing.
- `m0/package.json` — `npm run smoke:browser`. Dev dep: `playwright`.

### How to run

- **Browser (real evidence):** `cd m0 && npm install` then `npm run smoke:browser`.
  Uses system Chrome; set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` on install (no
  bundled-Chromium download needed). A human can instead serve `m0/`
  (`python -m http.server`) and open `index.html`.
- **Native (fast logic loop, not browser evidence):** create a venv,
  `pip install radioactivedecay`, `python m0/smoke.py` (prints the result JSON
  via the file's `__main__` guard).

## Results & decisions

### Versions (resolves §13 #6, M0 part)

| Component | Shipped (Pyodide 314 lock = source of truth) |
|---|---|
| Pyodide | **314.0.0** (released 2026-06-09; new scheme tracks bundled CPython 3.14) |
| Python | 3.14.2 |
| radioactivedecay | **0.6.1** (pure-Python wheel via micropip) |
| numpy / scipy / sympy | 2.4.3 / 1.17.1 / 1.14.0 |
| pandas / networkx / micropip | 3.0.2 / 3.6.1 / 0.11.1 |

Pyodide re-versioned `0.29.4` → `314.0.0` to match CPython 3.14. All of
radioactivedecay's deps are prebuilt in 314's lock, so `micropip.install` needs
no source builds. **Fallback if 314 ever regresses:** Pyodide `0.29.4`
(2026-05-07, Python 3.13) — documented, not tested here.

### Physics validation (the real check)

Cs-137 → Ba-137m secular equilibrium. After 1 day (≫ Ba-137m's 2.55 min,
≪ Cs-137's 30.17 yr), `A(Ba-137m)/A(Cs-137)` must equal the Cs-137→Ba-137m
branching fraction. The branching is **pulled from radioactivedecay's own data**
(0.94399), not hardcoded. Measured ratio 0.943990; **relative error 1.6e-7**
(tol 1e-3). Pass.

### Timing — real browser, Chrome 149 (CDN warm, browser cache cold)

| Phase | Time | Meaning |
|---|---|---|
| Pyodide + base load | ~1.2 s | core runtime |
| micropip install | ~2.2 s | radioactivedecay + dep wheels |
| first run | ~7.0 s | **one-time** scipy/sympy import in WASM + first solve |
| **per evaluation** | **~0.65 ms** | the slider-tick cost |
| pure single solve | ~0.8 ms | compute only |

Total cold start to first result ≈ **10 s** — within §4's "several seconds to
tens of seconds", reads as expected not failure. The 7 s is dominated by the
**one-time** WASM import of the scientific stack, *not* the solve. The
per-evaluation cost (~0.65 ms) confirms the §3 "solve once, evaluate many" rule
is viable: a multi-decade log slider can scrub smoothly.

### Spectral-data path (de-risks M2; resolves §13 #6 spectral part)

`radioactivedecay`'s dataset is `icrp107_ame2020_nubase2020`, exposing **decay
topology only** — `progeny`, `branching_fraction`, `decay_mode`, `half_life`,
`nuclides`. Introspection of `Nuclide`, the module, and the `DecayData` object
found **no** photon/emission-line energy/yield fields.

**Conclusion:** emission spectra are *not* free from radioactivedecay. **M2 must
bundle ICRP-107 RAD / ENSDF source-term tables separately**, exactly as §7
anticipates. radioactivedecay still gives us the chain DAG (progeny, branching,
modes, half-lives) for M1.

## Open questions / risks (named follow-ups, not M0 blockers)

- **Cross-browser not yet verified.** Only the Chromium engine (Chrome 149) was
  exercised. Firefox (Gecko) and especially Safari/WebKit — Pyodide's historical
  trouble spot — remain unverified. Verify before/at M6 (UI).
- **First-load weight is real** (§4 / §11 honesty register): ~10 s warm-CDN cold
  start, mostly the one-time WASM scientific-stack import. M6 needs the loading
  UI + service-worker caching the plan already calls for.
- `radioactivedecay` re-solves analytically on every `.decay()`; M1 must
  implement the true solve-once (eigendecomposition, evaluate-many) path to keep
  the per-eval cost at/under the ~0.65 ms measured here.
