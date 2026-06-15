# Vendored upstream — ICRP-107 emission spectra

This directory holds the **raw upstream** ICRP-107 radionuclide spectra, vendored
verbatim so the data build is hermetic and the provenance chain lives entirely
in-repo (the PyPI wheel can vanish; the data must not).

## Source chain

| Layer | Detail |
|---|---|
| Primary data | **ICRP Publication 107** — *Nuclear Decay Data for Dosimetric Calculations*, A. Endo & K.F. Eckerman, Ann. ICRP 38(3), 2008. |
| Reformatter | **`OpenGATE/icrp107-database`**, PyPI `icrp107-database` **0.0.3** (LGPL-3.0 *code* license). Re-expressed the ICRP-07 `.RAD`/`.BET`/… files as per-nuclide JSON. |
| This repo | `icrp107/<Nuclide>.json` copied verbatim from that wheel's `icrp107_database/icrp107/` directory (1252 files). |

We vendor only the **data** (the per-nuclide JSON), not OpenGATE's Python code, so
the binding license here is the **ICRP-07 data license** (`../LICENSE.ICRP-07`),
not LGPL. See `../README.md` for the license implications.

## Format (upstream, as-is)

Each file is a **double-encoded** JSON: a JSON *string* whose contents are JSON
`{"name", "half_life", "time_unit", "emissions": {<category>: [[E_MeV, value], …]}}`.
13 emission categories appear across the set: `gamma, X, annihilation, beta-,
beta+, b-spectra, alpha, alpha recoil, auger, IE, neutron, fission, betaD`.
Energies are MeV; discrete-line values are yield per decay; `b-spectra` values are
a continuous spectrum (dN/dE), not yields.

## Drift guard

`MANIFEST.sha256` lists `<sha256>  <name>` for all 1252 files. The build
(`../build/build_emissions.py`) recomputes a combined hash over the sorted manifest
and **refuses to run** unless it matches the pinned `EXPECTED_MANIFEST_SHA256`:

```
e47776c9f46440a4445ccc275630a4a930a17f710fa527936a2d11786331c14d
```

So the committed canonical files can never be silently rebuilt from changed inputs.

## Re-vendoring (only if upstream is intentionally bumped)

```sh
pip install icrp107-database==<new-version>
cp "$(python -c 'import icrp107_database,os;print(os.path.dirname(icrp107_database.__file__))')/icrp107/"*.json data/vendor/icrp107/
# regenerate MANIFEST.sha256, update EXPECTED_MANIFEST_SHA256 in the build script,
# rebuild, and re-run the full validation suite.
```
