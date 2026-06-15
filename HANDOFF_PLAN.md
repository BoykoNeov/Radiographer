# Radiation & Decay Simulator — Handoff Plan

**Status:** Design locked, ready to build.
**Target dev environment:** Claude Code.
**One-line description:** A professional-grade, fully client-side (browser) tool for radioactive decay chain visualization and external dose calculation.

---

## 0. How to use this document

This is the design contract. Decisions marked **LOCKED** are settled — build to them, don't relitigate. Items marked **OPEN** need a decision before or during the relevant milestone. The **honesty register** (§11) lists accuracy limits that must be surfaced in the UI, not hidden.

The single most important framing: **the engine code is easy; the bundled physics datasets are the project.** Most of the real effort and almost all of the silent-error risk lives in §7. Sequence the work so the data layer and its validation come *before* the UI (see §10).

---

## 1. Purpose & audience

An educational and reference tool at **professional health-physics level**. Users load one or more isotopes (with quantities) or a prebuilt source, visualize each isotope's decay chain with half-lives / decay modes / radiation energies, scrub time to watch inventories evolve, overlay multiple species on one graph, and compute the **external** dose a person accumulates near the source over time — including the effect of interposed shielding materials of chosen thickness, shown numerically and graphically.

Accuracy goal: **near-quantitative to a reasonable, documented precision.** Not a replacement for validated codes (MCNP, ORIGEN, VARSKIN) or a qualified health physicist. This must be stated in-app.

---

## 2. Scope & non-goals — LOCKED

**In scope (v1):**
- Decay chain modelling for arbitrary loaded inventories and prebuilt sources.
- Chain visualization as a **directed graph (DAG)** — chains branch and re-converge; this is not a line.
- Time evolution of inventory with a (log-scale) time control and a **definable reference time / source age** (a t=0 offset; spent-fuel cooling time in §8 is its named instance); multi-species overlay graphs.
- **External** dose from a **point source** — gamma, beta, and neutron, from the onset.
- Two selectable dose quantities: **ambient dose equivalent H\*(10)** and **effective dose E**.
- Shielding: arbitrary stack of materials × thicknesses, with dose-vs-thickness output.
- Save / load of full app state as JSON.

**Explicitly out of scope (v1), expandable later:**
- Internal / committed dose (ICRP dose coefficients in Sv/Bq). *Future.*
- Non-point source geometries (line, slab, volumetric, self-absorbing). *Future — see §11.*
- Neutron source-term *computation* (SF / (α,n)). v1 uses **tabulated** source terms per prebuilt source only. *Future.*
- On-device depletion/burnup. Spent fuel uses **precomputed discharge vectors** (see §8).
- Any server-side computation. **All computation runs on the user's device.** — LOCKED

---

## 3. Architecture — LOCKED

```
┌─────────────────────────────────────────────────────────┐
│  Browser (no server, no backend)                         │
│                                                          │
│  ┌────────────────────┐        ┌──────────────────────┐ │
│  │  UI layer (JS/HTML) │  bridge │  Physics core (Py)  │ │
│  │  - controls/sliders │ <────> │  via Pyodide (WASM)  │ │
│  │  - Plotly / uPlot   │  arrays │  - radioactivedecay  │ │
│  │  - Cytoscape / d3   │  & JSON │  - dose engine       │ │
│  │  - save/load JSON   │        │  - static datasets   │ │
│  └────────────────────┘        └──────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Division of labour:**
- **Python (Pyodide):** all physics — inventory solving via `radioactivedecay`, the dose engine, dataset loading and interpolation. Exposes functions that return plain arrays / JSON across the bridge.
- **JavaScript:** all rendering and interaction. Draw curves with Plotly or uPlot; draw the decay DAG with Cytoscape or d3. **Do not render matplotlib inside Pyodide** — it bloats the download and yields static images.

**Critical performance rule — "solve once, evaluate many":** never re-run the Bateman solve on a slider tick. Solve the inventory once (the matrix/eigendecomposition method gives a closed form), then evaluate it at the slider's chosen time on each move. This is what makes a multi-decade log time slider feel smooth in WASM.

---

## 4. Tech stack

Verify current versions at build time.

- **Pyodide** — Python in the browser (WASM). Confirmed to ship prebuilt numpy, scipy, sympy, pandas, matplotlib, networkx.
- **radioactivedecay** (PyPI, pure-Python wheel) — install via `micropip.install("radioactivedecay")`; micropip resolves numpy/scipy/sympy to the Pyodide builds. Uses ICRP-107 decay data (1252 nuclides), solves the decay ODEs analytically (Amaku matrix method), with an arbitrary-precision SymPy mode (`InventoryHP`) for stiff chains.
- **Plotly.js** — interactive log-log curves. **Chosen over uPlot (§13):** Pyodide dominates first-load weight, so Plotly's basic bundle (~280 KB gzip) is ~1% of payload; its native log-log axes, legend toggling, hover, and PNG/SVG export outweigh uPlot's redraw speed — which the "solve once, evaluate many" rule makes moot (curves are static; the slider only moves a cursor).
- **Cytoscape.js** — decay-chain DAG rendering. **Chosen over d3 (§13):** chains are true DAGs that re-converge (e.g. U-238: Bi-214 branches β⁻/α, both paths merge back at Pb-210), needing a layered/Sugiyama layout — Cytoscape + dagre gives this out of the box, whereas d3 would need d3-dag plus all rendering hand-built.
- Plain HTML/CSS or a light framework for the shell. No build-time backend.

**First-load reality (UX cost of client-side):** Pyodide core + numpy + scipy + sympy is tens of MB; scipy dominates and is unavoidable (radioactivedecay needs it). Expect several seconds to tens of seconds cold start. Mitigate: loading state/progress, service-worker caching, and lazy-load sympy only when high-precision is actually requested.

---

## 5. Decay / inventory engine

- Use `radioactivedecay`'s `Inventory` (double precision) by default. Invoke `InventoryHP` (SymPy arbitrary precision) **only on demand**, with a visible "computing…" state, for chains whose half-lives span many orders of magnitude (the case where double precision suffers catastrophic cancellation in the closed-form solution).
- **Chain is a DAG.** Render nodes (nuclide: half-life, decay modes) and edges (mode: α, β⁻, β⁺, EC, IT, SF; branching %). Natural series both branch and re-converge. `radioactivedecay` exposes progeny and branching fractions; pass the edge list to the JS graph lib.
- **Selectable quantity axis:** number of atoms, mass, and **activity (Bq / Ci)** produce very different-looking curves. Default to **activity** on **log-log** axes — radiation hazard tracks activity (A = λN), and a tiny atom-count of a short-lived daughter can dominate activity.
- **Teaching cases that fall out of correct math** (use as built-in demos / validation): secular equilibrium (Cs-137 → Ba-137m), transient equilibrium (Mo-99 → Tc-99m generator).
- **Optional output:** decay heat (W) — falls straight out of the decay energies; cheap and HP-relevant for spent fuel.

---

## 6. Dose engine (external, point source)

General point-source form for photons:

```
dose_rate(d) = Σ_lines [ E_i · y_i · (μ_en/ρ)_air,tissue(E_i) ] · A / (4π d²)   × shielding
shielding(E, materials) = Π_layers [ B(E, μx) · exp(−μ(E)·x) ]
```

### 6.1 Gamma — the quantitatively defensible core
- Sum over discrete emission lines (energy × yield per decay) folded with mass energy-absorption coefficients; inverse-square in distance; attenuation + **buildup** through shields.
- Realistic accuracy: a few percent for bare point sources. This is genuine professional grade and should be the first dose type implemented and validated.

### 6.2 Beta — skin dose, with honest limits
- External beta is a **skin-dose** problem (dose at 7 mg/cm², the 0.07 mm basal layer). Use a point-kernel (Loevinger or Cross–Berger) folded with the beta spectrum/endpoint.
- Realistic accuracy: **±20–30%**, not percent-level. State this.
- **Bremsstrahlung gotcha — must model:** shielding beta with high-Z material (lead) generates X-rays, so "more lead" can *increase* dose. Recommend low-Z first (acrylic, aluminium), then catch secondary photons. Make the shield material list radiation-type-aware so the UI teaches this.

### 6.3 Neutron — tabulated source terms only (v1)
- **Do not attempt to compute** neutron output from a loaded inventory (SF + (α,n), matrix-dependent — ORIGEN/SOURCES territory). v1 ships tabulated source strength + spectrum per prebuilt source (Cf-252, AmBe, spent-fuel vectors). Gray out neutron output for user-defined inventories.
- Fluence-to-dose conversion via ICRP-74 / ICRU coefficients (trivial once you have fluence).
- Shielding is **hydrogenous** (water, polyethylene), not lead — reinforce via the material-type-aware list.

### 6.4 Dose quantities — both selectable, LOCKED
- **H\*(10) (ambient dose equivalent):** operational quantity, what a survey meter reads. Build from fluence via ICRP-74 / ICRU-57 conversion coefficients. **No geometry choice needed.** Default/primary.
- **Effective dose E:** ICRP-116 external conversion coefficients are given **per irradiation geometry** (AP, PA, LAT, ROT, ISO). Even for a point source, selecting E forces a body-orientation assumption — **expose it as a dropdown** (default ISO or AP), don't bury it.
- The two are **not directly comparable**; the geometry asymmetry should be visible in the UI. Be obsessive about unit/quantity labels everywhere (see §12).

### 6.5 Shielding details — do these right
- Attenuation with **buildup**: `I = I₀ · B(E, μx) · exp(−μx)`. The buildup factor B matters a lot for thick shields (scattered photons); omitting it badly underestimates dose.
- Use **Geometric-Progression (G-P) buildup coefficients** (ANS-6.4.3 / Harima tabulation), interpolated in energy × mean-free-path.
- **Layered-shield buildup has no clean theory** (whose B for a Pb-then-water stack?). Pick a documented approximation (last-layer, or Harima–Kitazume) and **state which** in the UI/tooltips rather than hiding it. — OPEN: choose the approximation.
- **Point-source self-absorption:** a real dense source attenuates its own radiation; the point-source assumption breaks for large/dense sources. Pin a reference geometry and say so. (Relevant to §11 future work.)

---

## 7. Data layer — THE CRITICAL PATH

Because computation is wholly client-side, **no C-extension data libraries** (e.g. `xraylib`) are available. Every physics dataset must be a **bundled static file** loaded and interpolated in pure Python/numpy. Treat this as a feature: a versioned, auditable dataset beats a black-box C library for a professional tool — but it is the bulk of the work and the main error risk.

Build a **validation suite alongside the data** (see §10) so each table is checked the moment it lands.

### Datasets to assemble, with sources

| Dataset | Source | Used for |
|---|---|---|
| Emission spectra (photon lines + yields; beta endpoints/means) | ICRP-107 RAD files, or ENSDF | Gamma & beta source terms |
| μ and μ_en/ρ vs energy, per material | NIST XCOM (pre-extract to static tables) | Gamma attenuation & dose |
| G-P buildup coefficients, per material | ANS-6.4.3 / Harima | Gamma shielding (buildup) |
| H\*(10) fluence-to-dose coefficients | ICRP-74 / ICRU-57 | Operational dose quantity |
| External effective-dose coefficients, per geometry | ICRP-116 | Effective dose quantity |
| Neutron source terms + spectra, per prebuilt source | Published values (tabulated) | Neutron source (v1) |
| Neutron fluence-to-dose coefficients | ICRP-74 / ICRU | Neutron dose |
| Spent-fuel discharge inventory vectors, per (enrichment, burnup) | Published ORIGEN/SCALE tables | Prebuilt spent fuel (§8) |

### Suggested JSON schema sketches (firm these up in milestone M2)

```jsonc
// emissions/<nuclide>.json
{
  "nuclide": "Co-60",
  "photons": [ { "E_MeV": 1.1732, "yield": 0.9985 },
               { "E_MeV": 1.3325, "yield": 0.9998 } ],
  "betas":   [ { "E_endpoint_MeV": 0.318, "E_mean_MeV": 0.0958, "yield": 0.999 } ]
}

// attenuation/<material>.json   (interpolate in log-log)
{
  "material": "lead", "rho_g_cm3": 11.35,
  "E_MeV":        [0.01, 0.1, 1.0, 10.0],
  "mu_rho_cm2_g": [ ... ],          // mass attenuation
  "muen_rho_cm2_g": [ ... ]         // mass energy-absorption
}

// buildup/<material>.json   (G-P coefficients per energy)
{
  "material": "lead",
  "E_MeV": [ ... ],
  "gp": [ { "b": ..., "c": ..., "a": ..., "Xk": ..., "d": ... }, ... ]
}

// conversion/hstar10.json  and  conversion/effective_<geometry>.json
{ "E_MeV": [ ... ], "coeff_pSv_cm2": [ ... ] }
```

---

## 8. Prebuilt source catalog

Each source = a named inventory (or parameterized inventory) + optional tabulated neutron term + a one-line "what it teaches." Pick canonical definitions; ambiguous ones are flagged.

- **Co-60 medical/industrial source** — strong dual-gamma; the gamma-dose reference case.
- **Cs-137 source** — Cs-137 → Ba-137m secular equilibrium; classic 0.662 MeV line.
- **Spent reactor fuel — PARAMETERIZED (LOCKED).** Inputs: enrichment + burnup (GWd/tU) → pick/interpolate a precomputed **discharge vector**; **cooling time = the definable reference time (§9)** — the same t=0 / source-age control, here pre-labelled "cooling time" (just forward decay — free). Show how gamma/decay-heat change by orders of magnitude over cooling. — OPEN: choose the (enrichment, burnup) grid points to ship.
- **Fresh/unspent reactor fuel** — mostly U-238/U-235 α, weak gamma; surprisingly benign externally (good teaching contrast).
- **Nuclear-weapon fragment** — AMBIGUOUS, must disambiguate: (a) Pu/U **pit** (α emitter, low external dose, deadly if inhaled) vs (b) **fresh fission-product fallout** (the 7:10 decay rule). Recommend shipping **both** as separate, clearly-labelled sources. — OPEN.
- **Am-241 smoke detector** — α + 59.5 keV gamma; everyday source.
- **K-40 "banana"** — scale anchor / banana-equivalent-dose teaching.
- **Mo-99 / Tc-99m generator** — transient equilibrium demo.
- **Radium dial** — introduces gaseous Rn-222 daughter (in-growth complication).
- **Cf-252** — neutron source (tabulated SF spectrum).
- **AmBe** — neutron source (tabulated (α,n) spectrum).

**Chart-of-nuclides view — folded into the chain view (no longer a separate stretch).** The decay-chain DAG and the chart of nuclides are the same layout problem: position each node by (N, Z) and α decays become consistent down-left diagonals, β⁻ a horizontal step, with re-convergence falling out for free (a shared daughter is one coordinate, so both edges land on it). Ship two layouts in the same Cytoscape component: **dagre** (compact, for arbitrary loaded inventories) and a **(N, Z) preset** (physically meaningful, for teaching / nuclear-literate users).

---

## 9. UI / UX spec

**Inventory panel:** add isotopes by name + quantity (selectable unit: atoms / mass / activity); or load a prebuilt source; spent-fuel shows enrichment + burnup inputs. Save/Load full state as JSON (file download/upload as the portable format; localStorage as autosave convenience).

**Chain view:** DAG per loaded isotope (Cytoscape). Node tooltip: half-life, decay modes, decay energies. Edge label: mode + branching %. **Live, not static:** node encoding (size/color) is driven by the current slider-time activity, so scrubbing time shows the parent fade and the daughter grow in — secular/transient equilibrium becomes visible *on the diagram*. Two switchable layouts: **dagre** and the **(N, Z) chart-of-nuclides preset** (§8). **One color per species, shared** across the DAG, the overlay curves, and the dose breakdown.

**Time evolution:** a single **log-scale** time slider over an absolute envelope of ns → >10¹⁹ yr, but **auto-ranged per inventory** to ~`[0.01 × shortest relevant t½, 10 × longest relevant t½]` and recomputed when isotopes change (a blanket 28-decade slider is useless for a 6-hour generator). **Half-life tick marks** on the track — one per loaded species — turn the control into a teaching scale. A **numeric time entry + unit dropdown** handles precise jumps (no coarse/fine dual slider needed). A **definable t=0 / source-age** sets the reference origin (e.g. "spent fuel 5 yr after discharge"); this is the general control of which spent-fuel cooling time (§8) is the named instance. A **play/animate button** sweeps time in equal **log**-time steps so the live DAG (§ chain view) and curves evolve fast→slow; per the locked **"solve once, evaluate many"** rule (§3), each frame is a fresh *evaluation* of the already-solved inventory, **not** a re-solve. Multi-species overlay on one log-log graph (Plotly). **Prominent axis toggle:** a 3-way segmented control (Atoms · Mass · Activity) docked on the plot, always visible, default **Activity**, with a secondary unit choice (Bq/Ci, g/kg). The toggle is itself a teaching device — switching atoms↔activity reshapes the curves (a short-lived daughter dominates activity yet is negligible by atom count) — so annotate it. The y-axis label updates obsessively per §12. **Log-axis flooring:** clip the display at `max(visible series) / 10^D` (D ≈ 12–15 decades); values below the floor simply don't draw (an honest gap = "negligible") rather than diving toward −∞. A stable end-product has **zero activity** (omitted on the Activity axis) but a meaningful, *growing* atom/mass curve, so flooring is per axis-mode; offer a **linear-axis** option for the single-half-life zoomed view, default log-log.

**Dose calculator:** inputs = source (from inventory), distance, exposure time → accumulated dose. Selectable **H\*(10)** vs **effective dose** (+ geometry dropdown when effective). Per-radiation-type breakdown (γ / β / n), with neutron grayed out for user-defined inventories. **Breakdown form:** a **linear stacked bar** (γ + β + n = total) by default — at 1 m through a shield, gamma can sit orders of magnitude above beta, and the invisible sliver *is* the honest message ("beta is irrelevant here"); a **toggle to grouped log bars** reveals the small contributors (logs don't stack, hence the separate view). The breakdown is **live** — recomputes with the distance / shield / time controls. The gamma slice expands to a per-line table. **Uncertainty, made visible (§11):** each modality carries a different epistemic register — γ ≈ ±10–15% in the buildup regime, β ≈ ±20–30%, neutron source terms ≈ order-of-magnitude (tabulated). Render these as shaded **fill bands on the dose-vs-distance / dose-vs-thickness curves**, and as **error whiskers on the grouped log-bar view**; **not** on the stacked bar, where cumulative segment positions make per-segment whiskers ambiguous. The tight-γ-vs-fat-n contrast is the point.

**Shield builder:** ordered stack of (material, thickness) layers; material list **radiation-type-aware** (warn on high-Z for beta → bremsstrahlung; steer neutron to hydrogenous). Outputs: numeric dose with/without shield + attenuation factor; **dose-vs-thickness graph** and **dose-vs-time graph**.

---

## 10. Build order / milestones

De-risk foundation and data before UI.

- **M0 — Smoke test (½ day).** In Pyodide, in target browsers: `micropip.install("radioactivedecay")`, solve a known chain (e.g. Cs-137), confirm it works and time it. Kills the project early if the foundation doesn't hold.
- **M1 — Engine wrapper.** Python module exposing inventory solve (double + on-demand HP), chain DAG edge list, and time evaluation, returning JSON/arrays. Bridge to a trivial JS harness.
- **M2 — Data pipeline + validation suite (the big one).** Assemble §7 datasets with finalized schemas; build the loaders/interpolators; write regression tests as each table lands.
- **M3 — Gamma dose core.** Point-kernel + inverse-square + attenuation + G-P buildup. Validate against benchmarks (§ below) before moving on.
- **M4 — Beta dose** (skin dose + bremsstrahlung-in-shield), then **M5 — Neutron** (tabulated terms + fluence-to-dose).
- **M6 — UI.** Build on the proven core: chain view, time slider, overlay graphs, dose calculator, shield builder, save/load.
- **M7 — Prebuilt sources + teaching demos + chart-of-nuclides (stretch).**

### Validation benchmarks (gives "near-quantitative" its teeth) — verify exact published values during M3
- Co-60 air-kerma rate constant (~0.3 mGy·m²/(GBq·h) range) and the "1 Ci Co-60 at 1 m ≈ 1.3 R/h" rule of thumb.
- Cs-137 dose-rate constant.
- Published HVL / TVL tables for Pb, concrete, water at standard energies.
- Secular equilibrium (Cs-137 → Ba-137m) and transient equilibrium (Mo-99 → Tc-99m) inventory curves.

---

## 11. Honesty register — surface these in-app

- **Not for real radiation-safety decisions.** Educational/reference only; real work needs validated codes + a qualified health physicist.
- **Point source only (v1).** Self-absorption and finite-source geometry are not modelled; results degrade for large/dense sources.
- **Beta dose ≈ ±20–30%.**
- **Neutron source terms are tabulated**, not derived; only available for prebuilt sources in v1.
- **Layered-shield buildup uses an approximation** — name which one in tooltips.
- **H\*(10) and effective dose are different quantities** computed differently; don't compare directly.
- **First load is heavy** (WASM scientific stack) — expected, not a bug.

---

## 12. Units & conventions — be obsessive

- Distinguish and label everywhere: **absorbed dose (Gy)** vs **equivalent / H\*(10) (Sv)** vs **effective dose (Sv)**; **air kerma** vs **exposure (R)**; **activity Bq vs Ci**.
- Offer both SI and conventional units; store internally in SI.
- Radiation weighting reminder (for context/teaching): α w_R = 20 — near-zero *external* dose but extremely dangerous internally (a Pu pit reads almost nothing on a survey meter yet is deadly if inhaled). Reinforce that external ≠ internal hazard.

---

## 13. Open decisions to resolve

1. ~~uPlot vs Plotly / Cytoscape vs d3.~~ **RESOLVED:** **Plotly.js** (curves) + **Cytoscape.js** (DAG). Reasoning in §4. Also locked (all in §9): live (time-driven) DAG with switchable dagre + (N, Z) layouts; chart-of-nuclides folded into the chain view; one shared color per species across all views; prominent on-plot axis toggle (Atoms · Mass · Activity, default Activity); **time control** = single log slider, auto-ranged per inventory with half-life tick marks, numeric entry, **definable t=0 / source-age** (unified with spent-fuel cooling time), and an animate button that sweeps log-time via successive *evaluations* (not re-solves); **dose breakdown** = linear stacked bar default + grouped-log-bar toggle, live; **uncertainty** shown as fill bands on curves and whiskers on the grouped view (per-modality registers γ/β/n); **log-axis flooring** at ~12–15 decades below peak, per axis-mode, with a linear-axis option.
2. **Layered-shield buildup approximation** (last-layer vs Harima–Kitazume).
3. **Effective-dose default geometry** (ISO vs AP).
4. **Spent-fuel (enrichment, burnup) grid** to ship.
5. **"Bomb fragment" definitions** — confirm shipping both pit and fallout variants.
6. ~~**Verify** `radioactivedecay` and Pyodide package versions and the exact spectral-data access path (ICRP-107 RAD vs ENSDF) at M0/M2.~~ **RESOLVED at M0** (see `docs/plans/M0-smoke-test.md`): **Pyodide 314.0.0** (bundles CPython 3.14; new version scheme replacing 0.29.x — fallback Pyodide 0.29.4), **radioactivedecay 0.6.1** via micropip (all deps prebuilt in the 314 lock: numpy 2.4.3 / scipy 1.17.1 / sympy 1.14.0 / networkx 3.6.1). **Spectral-data path:** radioactivedecay (dataset `icrp107_ame2020_nubase2020`) exposes **decay topology only — no emission spectra**, so M2 must bundle ICRP-107 RAD / ENSDF photon-line tables separately (as §7 already plans). **Spectral source RESOLVED at M2** (see `docs/plans/M2-emissions.md`): **ICRP-107 RAD** (consistency with the engine's decay data), obtained via `OpenGATE/icrp107-database` 0.0.3 and validated — 1252 nuclides bundled with a four-pillar regression suite.
