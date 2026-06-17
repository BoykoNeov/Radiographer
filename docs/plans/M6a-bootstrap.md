# M6a — Bootstrap & packaging

**Status:** ✅ done — gate green in a real headless browser, dev **and** built.
**Parent:** `docs/plans/M6-ui.md` (this is the first M6 chunk)
**Milestone (HANDOFF_PLAN.md §10):** M6 UI — foundation slice. M0-style "kill
early": if Pyodide + the full engine + the **whole** bundled dataset can't boot
in a real browser and reproduce a known dose benchmark, the browser app is not
viable and we learn it now, before any UI is built on top.

## Goal

Replace the stale M1 smoke harness (`web/index.html`, 4 modules, no data) with a
**Vite + Svelte + TypeScript** app shell that:

- loads Pyodide (CDN-injected, 314.0.0 with 0.29.4 fallback) + `micropip`
  installs `radioactivedecay`;
- fetches **one combined archive** (engine code + the 5 runtime data dirs),
  unpacks it into the Pyodide FS, and imports `engine.bridge`;
- exposes a **typed bridge client** (branded `Handle`, JSON in/out) wrapping all
  7 bridge functions;
- shows a loading/progress UI and a **loud error surface** (no blank-on-failure);
- passes a **kill-early gate** in a real headless browser (extend
  `web/drive_browser.mjs`): boot + a known dose benchmark round-trips + the
  packaging + HP-in-WASM risks are actually exercised.

## Load-bearing decisions (the four that a fresh session must not re-derive)

1. **One combined archive, extracted to `/`.** The zip contains both
   `engine/*.py` and `data/<runtime-dir>/*.json`; the browser writes it to the
   Pyodide FS and `zipfile.extractall('/')` reproduces `/engine/...` + `/data/...`.
   Then `sys.path.insert(0, '/')` and `import engine.bridge`. The engine's
   `Path(__file__).resolve().parents[1]` resolution makes `_DEFAULT_ROOT` =
   `/data/<dir>` with **no loader change** (verified: `/engine/x.py` →
   `parents[1]` = `/` → `/data/emissions`). *Why combined, not engine-via-bundler
   + data-via-archive:* a single mechanism avoids Vite's "glob outside project
   root" limitation for the `engine/*.py` source and keeps one source of truth for
   "what ships to the browser."
2. **Extract with Python `zipfile`, not `pyodide.unpackArchive`.** Full control
   over the target dir (`/`) and loud error surfacing; no dependence on
   `unpackArchive`'s `extractDir` semantics. `zipfile` is stdlib (present in
   Pyodide).
3. **Pyodide is CDN-injected at runtime**, not an npm import — this is the exact
   path M1 proved in a real browser. Avoids matching an npm `pyodide` package
   version to the CDN `indexURL` (the versions are unusual — 314.0.0 — but
   empirically work; do not "fix" them).
4. **Archive built by a pure-Node script using `fflate`** (`web/scripts/build-archive.mjs`)
   → `web/public/radiographer-runtime.zip` (a Vite static asset, git-ignored,
   generated). `fflate` keys are written with **forward slashes** so
   `extractall('/')` yields a real tree on Windows too. Excludes `data/vendor/`
   and `data/build/` (build inputs, ~17 MB, not runtime). mtime-aware: rebuilds
   only when a source is newer than the zip.

## The kill-early gate (what "M6a done" means)

`web/drive_browser.mjs` boots the real app in headless Chrome/Edge against the
Vite dev server, waits for `window.__M6A_DONE__`, and asserts
`window.__M6A_RESULT__.ok`. The in-app self-check (through the **typed bridge
client**, not raw Python) asserts, all from validated Python tests:

- **Packaging canary (the actual M6a risk).** After extraction, in boot Python:
  `len(available_nuclides()) == 1252` (pinned natively today). Solving 3 nuclides
  only proves ~3 files extracted; this proves the **whole 1252-file tree** mounted
  — and is the corruption canary for a bad (e.g. backslash) arcname.
- **Co-60 air-kerma @ 1 m** (`tests/test_bridge.py::test_dose_round_trip_co60_air_kerma`):
  solve {Co-60: 1e9 Bq} → `dose` air_kerma → `rate_si[0]·3.6e6 ≈ 0.308`
  mGy/h (rel 3 %), `scoring_floor_MeV == 0.010`, `warnings` non-empty. Exercises
  emissions + attenuation (μ_en/ρ) data.
- **Co-60 H\*(10)/Kₐ ratio** ∈ (1.05, 1.30) (`test_dose_gamma`): exercises the
  **conversion** (pSv·cm²) tables — a different data path than air-kerma.
- **Cs-137 secular equilibrium**: A(Ba-137m)/A(Cs-137) @ 1 d ≈ 0.94399 (abs 1e-3),
  `hp_recommended == false`. Exercises solve→evaluate + decay data.
- **HP path in WASM** (M1 open risk): solve {U-238: 1.0 Bq, precision:"hp"} →
  `ok`, `hp_recommended == true`; evaluate a small grid → all finite, ≥ 0. Proves
  `rd.InventoryHP` (→ sympy) runs under WASM. *Fallback if it fails on a sympy
  import:* `micropip.install(["radioactivedecay","sympy"])` (both pure-Python).
- **Loud error crosses the bridge**: solve {Zz-000} → `ok:false`,
  `error.type=="EngineError"`.

**Before declaring done:** run the gate once against `vite build` + `vite preview`
(`drive_browser.mjs --built`), not just the dev server — "boots in dev" ≠ "boots
built."

## Key files

- `web/` — Vite + Svelte + TS project: `index.html` (entry), `src/main.ts`,
  `src/App.svelte` (boot-status shell + loud error surface + sets the driver
  globals), `src/lib/pyodide-boot.ts` (the boot sequence + packaging canary),
  `src/lib/bridge.ts` (typed client, branded `Handle`, 7 fns), `src/lib/selfcheck.ts`
  (the gate benchmarks through the client), `vite.config.ts`, `tsconfig*.json`,
  `svelte.config.js`.
- `web/scripts/build-archive.mjs` — fflate archive builder (mtime-aware, `--force`).
- `web/drive_browser.mjs` — rewritten: ensure-archive → start Vite (dev, or
  `--built` = build+preview) → drive headless → assert `__M6A_RESULT__.ok`.
- `web/public/radiographer-runtime.zip` — generated, git-ignored.
- No change to `engine/` (the `set_data_root()` hatch already exists and is unused
  because `__file__` resolution just works).

## Deferred to later chunks (not M6a)

- **Plotly / Cytoscape deps** — added when M6c / M6e wire them (keeps M6a's
  dependency surface minimal; bundle-size/tree-shaking confirmed there).
- **`available_nuclides` over the bridge** (for add-by-name validation) — M6b.
  M6a tests the glob in boot Python directly.
- Any real reactive UI / app-state store — M6b onward. The M6a shell is a boot
  harness, not the app.
- **Boot-level red error banner is unverified.** The gate proves the *bridge*
  surfaces errors loudly (Zz-000 → `EngineError`) and the check table renders, but
  `App.svelte`'s `phase==="error"` banner is never triggered (no boot failure
  injected). **M6h's end-to-end test must assert the boot-error banner actually
  renders** — don't let the UI no-silent-errors path ride to "done" unproven.
- **`npm audit`: 4 high (esbuild GHSA-gv7w-rqvm-qjhr via vite/svelte-plugin).**
  Dev-toolchain only (esbuild dev server / NPM_CONFIG_REGISTRY); the shipped app is
  a static, serverless bundle with no esbuild at runtime → not a deploy risk. The
  remediation is vite@8 (breaking) — deferred; revisit at a toolchain bump.

## Result (verified)

`npm run harness` (dev) and `npm run harness:built` (`vite build` + `vite preview`)
both report `✅ M6a PASS (real browser)`, all 5 self-checks green:

| check | measured |
|---|---|
| Co-60 air-kerma @1m | **0.3056 mGy/h** (vs 0.308, within 3 %), floor 0.01, 25 warnings |
| Co-60 H\*(10)/Kₐ | **1.1394** ∈ (1.05, 1.30) — conversion tables OK |
| Cs-137 secular eq @1d | **0.943990** |
| HP path in WASM (U-238) | hp_recommended=true, 21 nuclides, all finite |
| unknown nuclide | loud `EngineError` |

- **Packaging:** archive = **1299 entries** (13 engine + 1252 emissions + 14 + 11 +
  8 + 1), **49.3 MB → 6.1 MB** zip, **zero backslash arcnames**. The
  `available_nuclides()==1252` canary passes (boot can't succeed otherwise).
- **HP-in-WASM risk CLOSED.** `micropip.install("radioactivedecay")`
  auto-resolves the high-precision deps — the boot package log shows `sympy` and
  `mpmath` loaded — so `rd.InventoryHP` runs under WASM with no extra install.
- Bundle: 41 KB JS / 16 KB gzip — Pyodide + datasets dominate first load, as
  expected (§4).

## Open questions / risks

- **First-load weight is bigger than the archive.** `micropip.install("radioactivedecay")`
  pulls the **full scientific stack** — numpy, scipy, sympy, mpmath, *and* matplotlib,
  pandas, Pillow, networkx (transitive deps the engine never uses). That's the real
  first-load cost (tens of MB of wheels), on top of the 6.1 MB data archive. Candidate
  trim: `micropip.install("radioactivedecay", deps=False)` then install only
  numpy + sympy + mpmath — deferred (risk of an unmet import); revisit if first load
  is unacceptable. The lazy per-nuclide emission fetch (M6-ui.md) is the other lever.
- **Combined-archive staleness in dev** — editing `engine/` or `data/` without
  rebuilding the zip silently runs old code (a self-inflicted silent-error). Mitigated:
  the mtime-aware builder runs on `npm run dev` and in the gate, rebuilding only when a
  source is newer than the zip.
