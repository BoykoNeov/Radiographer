# ENDF/B-VIII.0 neutron fission yields — vendored source

## File
- `nfy-092_U_235.endf` — ENDF/B-VIII.0 neutron-induced fission-yield (NFY)
  evaluation for ²³⁵U.
- SHA-256: `9e1320293a544fc03f33f804a15a9e3ccc3be026552ee6dbc03b8d3e24615e41`
- Size: 382 052 bytes.

## Origin
- Downloaded from the NNDC ENDF/B-VIII.0 NFY sublibrary:
  `https://www.nndc.bnl.gov/endf-b8.0/zips/ENDF-B-VIII.0_nfy.zip`
  (file `ENDF-B-VIII.0_nfy/nfy-092_U_235.endf` within the archive).
- Library: ENDF/B-VIII.0 (Brookhaven National Laboratory, 2018).

## License / use
ENDF/B evaluated nuclear data are released into the public domain by the
US Cross Section Evaluation Working Group (CSEWG) / BNL and are freely
redistributable. No usage restriction beyond citing the library.

## What we use
`build_fallout.py` parses **MF=8, MT=459** (cumulative fission-product
yields) at the **thermal** incident energy (0.0253 eV) — the first energy
block. Cumulative (not independent) yields are used because they capture
the chain-fed population of each nuclide once its short-lived precursors
(many absent from the ICRP-107 emission set) have decayed in; seeding
independent yields would drop ~69 % of the fragments and badly underfeed
the longer-lived γ emitters. See `data/build/build_fallout.py` and
`docs/plans/M7-sources.md`.

## Validation anchor
The shipped vector, decayed forward through the Bateman engine, reproduces
the Way–Wigner **t⁻¹·² (7:10)** gross-γ decay law over H+1 h … ~30 d
(regression test `tests/test_fallout_data.py`).
