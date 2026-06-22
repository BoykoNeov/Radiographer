# Radiographer

A professional-grade, **fully client-side** (browser) tool for radioactive
**decay-chain visualization** and **external dose calculation**. Load isotopes
or a prebuilt source, watch the decay chain and inventory evolve over time, and
compute the dose a person near the source accumulates — through shielding you
choose. All physics runs **on your device** via Pyodide (Python compiled to
WebAssembly); there is no server and nothing is uploaded.

> **Not a substitute for validated codes** (MCNP, ORIGEN, VARSKIN) or a
> qualified health physicist. It is an educational and reference tool, accurate
> to a documented precision. The app surfaces its own accuracy limits in an
> in-app **Honesty** panel — read it.

---

## Quick start

You need **[Node.js](https://nodejs.org/)** (LTS) installed and a modern
browser. The first launch also needs an **internet connection** (see below).

### Windows — one click

Double-click **`start.cmd`** in this folder. It installs dependencies the first
time, starts the local server, and opens the app in your browser. Leave the
window open while you use the app; close it to stop.

### macOS / Linux — one command

```sh
cd web
npm install      # first time only
npm run dev      # then open the http://localhost:… URL it prints
```

### First load is slow — this is expected, not a bug

On first launch the browser downloads the Pyodide runtime from a CDN and pulls
the scientific Python stack (numpy / scipy / sympy). Expect a loading screen for
**several seconds to tens of seconds**, and note that **the first load requires
internet access**. Subsequent loads are faster (browser-cached).

---

## What you can do

- **Build an inventory** — add nuclides with quantities (Bq, Ci, atoms, or
  mass), or pick a **prebuilt source** (e.g. Cf-252, AmBe, a Pu pit, spent fuel,
  bomb fallout).
- **See the decay chain** as a directed graph that branches and re-converges,
  with half-lives, decay modes, and branching fractions.
- **Scrub time** on a log-scale slider (with a definable source age / reference
  time) and watch activity curves for every species update live.
- **Compute external dose** — gamma, beta, and neutron — as either **ambient
  dose equivalent H\*(10)** or **effective dose E** (with a selectable body
  orientation), shown as a rate, accumulated dose, and dose-vs-distance.
- **Add shielding** — stack materials × thicknesses and see dose-vs-thickness.
  The material list is radiation-type-aware (e.g. it teaches that high-Z
  shielding can *increase* beta dose via bremsstrahlung).
- **Estimate committed internal dose** for a set of nuclides (ICRP dose
  coefficients), with its limits called out.
- **Save / load** the full app state as JSON.

---

## Running a production build

`npm run dev` is the easiest way in. For a production-feel build served as
static files:

```sh
cd web
npm run build     # outputs web/dist/
npm run preview   # serves the built dist/ locally
```

The built `dist/` is a static bundle — host it on any static file server (it
still needs internet on first load for the Pyodide CDN).

---

## Project layout

| Path             | What it is |
| ---------------- | ---------- |
| `web/`           | The browser app — Svelte UI + Vite. Start here. |
| `engine/`        | Python physics core (decay solving + dose engine), runs in Pyodide. |
| `data/`          | The bundled physics datasets and their build scripts. |
| `tests/`         | Regression tests for the engine and datasets. |
| `HANDOFF_PLAN.md`| The design contract — what the project is and why. |
| `docs/`          | Durable design notes per milestone. |

**Data provenance:** emission and dose data are derived from published sources
(ICRP-107 decay data, ICRP-74/116 conversion coefficients, NIST attenuation
data, and others — cited in `data/`). The bundled ICRP-107 emission data is
**non-commercial use only**.

---

## How it works (architecture)

```
Browser (no backend)
  UI layer (Svelte / JS)  ⇄  Physics core (Python via Pyodide / WASM)
  - Plotly  : log-log curves          - radioactivedecay : Bateman solve
  - Cytoscape : decay-chain DAG       - dose engine
  - save/load JSON                    - bundled datasets
```

The inventory is solved **once** (closed-form), then merely *evaluated* at the
slider's chosen time on each move — so a multi-decade time slider stays smooth
in WASM. See `HANDOFF_PLAN.md` for the full design.
