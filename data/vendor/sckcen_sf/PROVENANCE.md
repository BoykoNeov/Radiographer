# Vendored upstream — SCK-CEN PWR spent-fuel Serpent2 library

This directory holds the **raw upstream** PWR spent-fuel discharge library used to build the
bundled discharge vectors in `../../spent_fuel/` (HANDOFF_PLAN §8, §13 #4; M7c).

The CSV itself is **gitignored** (`SCKCEN_UOX_PWR.csv`, ~370 MB) — only the compact, validated
per-(burnup, enrichment) JSON vectors land in git. This file documents how to re-fetch it so the
build (`../../build/build_spent_fuel.py`) is reproducible.

## Source chain

| Layer | Detail |
|---|---|
| Primary data | **SCK-CEN**, *"Dataset of observables for UOX and MOX spent fuel extracted from Serpent2 fuel depletion calculations for Pressurized Water Reactors"*, Mendeley Data, **DOI `10.17632/shv89y2zzd`**. Serpent2 v2.2.0, 3D pin-cell model, state-of-the-art nuclear-data libraries. Companion: *Data in Brief* (PMC10371779). |
| File used | `SCKCEN_UOX_PWR.csv` — the **UOX** file (the MOX file is 6.8 GB and unused). Read from dataset **version 4** (the published DOI is `.5`, but v5's public-API file listing returns empty; v4 is `available: True`, published 2023-05-08, and is the same physics). |
| This repo | `../../spent_fuel/<id>.json` — curated discharge vectors at chosen grid points, extracted + validated by `build_spent_fuel.py`. |

## Licence

**CC BY 4.0** (`http://creativecommons.org/licenses/by/4.0`) — *redistributable* with attribution,
unlike the non-commercial ICRP-107 emission data (`../LICENSE.ICRP-07`). The extracted vectors in
`../../spent_fuel/` carry the `source_ref` attribution string per file.

## CSV format (upstream, as-is)

Header row then 63,531 data rows on a (BU × IE) grid: `BU` (achieved burnup, MWd/kgHM = GWd/tHM),
`IE` (initial enrichment %), then **150 nuclides × 7 columns** — bare name = **mass density g/cm³**,
then `_A` (activity Bq), `_H` (decay heat W), `_SF`, `_GSRC`, `_ING_TOX`, `_INH_TOX`. Discharge
(zero cooling); `BU` is the *achieved* depletion burnup (e.g. 45.016, not exactly 45.0).

**Basis note (why the build uses mass density, not `_A`):** the `_A`/`_H` activity columns carry a
fixed geometry/smearing factor `_A/(λ·ρ/M·N_A) ≈ 0.535` (constant across nuclides) that the
mass-density column does **not** — i.e. they are on different volume bases. The build therefore
derives activity as `λN` from the mass-density (atom-inventory) columns via the engine's own decay
constants, normalized to 1 tonne initial HM. Validated independently: the resulting Cs-137 discharge
activity matches a from-scratch fission-yield estimate to ~5%. The `_H/_A` ratio (basis-independent)
is used as an ICRP-107-vs-Serpent2/JEFF decay-energy cross-check on the dominant heat contributors.

## Drift guard

SHA-256 of the vendored UOX CSV (version 4):

```
5522f9284e5367963d4ed503db73c3514cf830c6f9652a873877382ddd759a81  SCKCEN_UOX_PWR.csv
```

## Re-fetching (the file is gitignored)

```sh
# UOX file, dataset version 4 (≈370 MB):
curl -L -o data/vendor/sckcen_sf/SCKCEN_UOX_PWR.csv \
  "https://data.mendeley.com/public-files/datasets/shv89y2zzd/files/8d071817-1b33-4fdf-b4c7-f1d49e277584/file_downloaded"
sha256sum data/vendor/sckcen_sf/SCKCEN_UOX_PWR.csv   # must match the hash above
python data/build/build_spent_fuel.py               # re-extracts + revalidates the vectors
```
