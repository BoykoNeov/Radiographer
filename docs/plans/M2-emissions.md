# M2 — Data pipeline: emission spectra

**Status:** done ✅ (first of M2's §7 datasets; siblings — attenuation, buildup,
conversion coefficients, neutron terms, spent-fuel vectors — still to land)
**Milestone (HANDOFF_PLAN.md §10):** assemble the §7 datasets with finalized
schemas, build loaders/interpolators, write regression tests as each table lands.

> M2 is "the big one" (§7). It is being built **one dataset at a time**, each with
> its validation suite, rather than as a single drop. This doc covers the
> **emission spectra** (photon lines + yields, beta endpoints/means) — the source
> term everything dose-related needs, and the chosen first dataset.

## Results (done)

- **1252 canonical files** `data/emissions/<Nuclide>.json` (`schema_version: 1`),
  generated from vendored ICRP-107 by `data/build/build_emissions.py`.
- **14 regression tests pass** (`tests/test_emissions_data.py`); full suite 91
  pass, no M1 regression.
- **Coverage is provably complete:** every radioactive nuclide `radioactivedecay`
  knows (1252) has an emission file; the 260 rd-only nuclides are all **stable**
  (no emissions) — asserted both directions, so there are **no silent dose holes**
  (§11).
- **Annihilation convention pinned:** ICRP yields are **per photon** — Na-22
  0.511 MeV ≈ 1.80 ≈ 2× its 0.90 β⁺ branch. Getting this wrong would have made
  every positron-emitter's photon dose 2× low, invisibly.
- **Half-life parse canary:** ICRP `half_life × time_unit` vs rd agrees to
  < 0.003 % across all 1252 (the only spread is the year-length convention) —
  confirms the units/files are parsed correctly. rd remains the half-life source
  of truth; ICRP's half-life is **not** stored in the canonical schema.

## Resolves §13 OPEN #6 (spectral part)

**Spectral data source = ICRP-107 RAD** (user decision), obtained via
`OpenGATE/icrp107-database` 0.0.3 (a verbatim JSON reformat of the ICRP-07 files).
Chosen over ENSDF for **consistency with the decay topology already in the engine**
(radioactivedecay also uses ICRP-107). The §13 #6 spectral item is now closed.

## Accepted approach

**Acquisition → vendor → transform → validate**, all in-repo and hermetic:

1. **Vendor** the upstream per-nuclide JSON verbatim into `data/vendor/icrp107/`
   (+ `MANIFEST.sha256`). Byte-exact provenance; the build pins a combined hash
   and refuses to run on drift. (Don't depend on the PyPI wheel at build/run time;
   read JSON directly — skip upstream `utility.py`, whose Gate-name API mismatches
   the hyphenated on-disk names.)
2. **Transform** (`build_emissions.py`) maps the 13 ICRP categories into typed,
   unit-labelled groups; aggregates gamma ∪ X ∪ annihilation into `photons`
   (origin-tagged, ascending in E); preserves exact floats; raises on any unknown
   category / bad row / name mismatch. Output is deterministic + readable
   (auditable git diffs) and **idempotent**.
3. **Loader** `engine/emissions.py` — the single read path for the physics core;
   raises `EmissionsError` on a missing radioactive nuclide (a hole ≠ zero dose).
4. **Validate** — four independent pillars (see below), TDD: suite written first,
   confirmed failing on the empty dir, then built to green.

### Validation pillars (avoid circular tests)
- **Structural:** schema, types, E>0, yields≥0, photons sorted, valid origins/kinds.
- **Transform integrity:** canonical == upstream re-derived **independently** of
  `transform()` — the full multiset of (category, E, value) triples must survive
  the rebuild. Catches drop/dup/mis-route/double-decode/value-mangle bugs.
- **Coverage:** hard assertion, both directions (above).
- **Physics goldens:** Co-60, Ba-137m, Am-241, Na-22 (β⁺/annihilation), I-131,
  Tc-99m — asserted against **independent NNDC/ENSDF** nominal intensities,
  hardcoded with tolerances, *not* copied from the ICRP files.

## Key files & decisions

- `data/build/build_emissions.py` — transform + drift guard + `BuildError`.
- `data/emissions/*.json` — canonical dataset (committed).
- `data/vendor/icrp107/*.json`, `data/vendor/MANIFEST.sha256`,
  `data/vendor/PROVENANCE.md` — vendored upstream + provenance.
- `data/LICENSE.ICRP-07` — data license (educational/research/**non-commercial**).
- `data/README.md` — schema, choices, license, rebuild/validate instructions.
- `engine/emissions.py` — `EmissionsError`, `load_emissions`, `photons/betas/alphas`,
  `available_nuclides`, `has_emissions`, `set_data_root` (M6/Pyodide repoint).
- `tests/test_emissions_data.py` — the four-pillar suite.
- `.gitignore` — re-include `data/build/` (the generic `build/` ignore swallowed it).

**License constraint (record):** the ICRP-07 data license is **non-commercial**;
it propagates to the whole distributed repo and constrains the *eventual* repo
license (HANDOFF_PLAN.md has no license yet). Isolated under `data/` with the
license file + Endo/Eckerman notice.

## Open questions / risks

- **Beta carry-forward for M4 — no clean per-branch endpoints exist.** ICRP-107
  gives discrete betas only as the *mean* energy (not §7's `E_endpoint_MeV`), and
  `b-spectra` is a continuous spectrum **summed over all branches** (Co-60's
  1.49 MeV tail is the 0.12 % branch, not the main 0.318 MeV endpoint). So M4 has
  **neither per-branch endpoints nor per-branch spectra**. Loevinger/Cross-Berger
  skin-dose kernels are endpoint-parameterized, so the M4 beta model must be
  designed around mean-energy + summed-spectrum inputs (or derive endpoints from
  decay energetics) — it cannot assume the §7 endpoint field. This is inherent to
  ICRP-107; there is no "capture it now" fix.
- **Upstream faithfulness is verified only for the goldens.** Transform integrity
  proves canonical == upstream; for ~1246 of 1252 nuclides we trust the OpenGATE
  reformat == true ICRP-107 (only the 6 goldens are independently anchored). Cheap
  future strengthener: a coarse per-nuclide invariant. Recorded in `data/README.md`.
- **Sub-keV photon lines** sit below the NIST XCOM ~1 keV floor → **M3** dose
  engine must skip below-table photons explicitly **and logged**, never silently.
- **`extra` categories** (`alpha recoil`, `fission`, `betaD`) are preserved
  verbatim; their semantics are validated only structurally until M4/M5 need them.
- **Pyodide path** — the loader defaults to the repo `data/emissions`; M6 must
  mount these into the Pyodide FS and call `set_data_root` (also the bundling
  question flagged in M1 — 1252 files vs a packed form).
- Neutron `neutron`-category entries are single representative lines, not full
  multiplicity/spectra; v1 neutron source terms remain tabulated per-source (M5).
