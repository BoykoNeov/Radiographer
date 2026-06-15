# M2 — Data pipeline: photon attenuation (μ/ρ, μ_en/ρ)

**Status:** done ✅ (second of M2's §7 datasets, after emissions; siblings — G-P
buildup, conversion coefficients, neutron terms, spent-fuel vectors — still to land)
**Milestone (HANDOFF_PLAN.md §10):** assemble the §7 datasets with finalized schemas,
build loaders/interpolators, write regression tests as each table lands.

> M2 is "the big one" (§7), built **one dataset at a time**, each with its validation
> suite. This doc covers the **photon attenuation / energy-absorption coefficients** —
> the material side of the gamma dose engine: μ/ρ drives shielding `I = I₀·e^(−μx)`,
> μ_en/ρ drives the dose line-sum `E·y·(μ_en/ρ)` (§6). This is the direct M3 dependency.

## Results (done)

- **11 canonical files** `data/attenuation/<material>.json` (`schema_version: 1`),
  generated from vendored NIST tables by `data/build/build_attenuation.py`.
- **Materials:** dose media — `air`, `water`, `tissue_soft`; shields — `lead`,
  `tungsten`, `iron`, `copper`, `aluminium`, `concrete`, `pmma`, `polyethylene`.
  (`water` doubles as a medium and a shield.)
- **14 regression tests pass** (`tests/test_attenuation_data.py`); full suite 105 pass,
  no emissions/M1 regression.
- **Goldens verified** against independent published values: water μ/ρ ≈ 0.0632 &
  μ_en/ρ ≈ 0.0297 cm²/g @ 1.25 MeV; water μ/ρ ≈ 0.171 @ 0.1 MeV; air μ_en/ρ ≈ 0.0267 @
  1.25 MeV; Pb **narrow-beam** HVL = 1.039 cm @ 1.25 MeV; Pb ≫ Al at 0.1 MeV; Pb K-edge
  at 0.088 MeV with μ/ρ stepping up across it.

## Resolves §13 OPEN #6 (attenuation part) + corrects §7 source

**Source = NIST Hubbell & Seltzer (SRD 126 / NISTIR 5632), not "XCOM".** §7 wrote
"NIST XCOM", but XCOM (SRD 8) gives **μ/ρ only**; the mass **energy-absorption**
coefficient μ_en/ρ the dose engine needs lives in the **Hubbell & Seltzer** tables — a
superset giving both coefficients for elements and compounds over 1 keV – 20 MeV. Same
NIST cross-section lineage, so the two are *not* independent (trust-boundary note below).
NIST concrete is **"Concrete, Ordinary"** (ρ ≈ 2.30), not §7's "Portland" — pinned and
named; there is no separate Portland entry.

## Accepted approach (mirrors emissions: acquire → vendor → transform → validate)

1. **Acquire** — `data/build/fetch_nist_xraymac.py` pulls the per-material μ/ρ + μ_en/ρ
   pages (`ElemTab/z<Z>.html`, `ComTab/<name>.html`) plus the density index pages
   (`tab1.html` elements, `tab2.html` compounds), writing **verbatim bytes**. NIST gates
   on a User-Agent. One-time step, analogous to `pip install icrp107-database`.
2. **Vendor** — `data/vendor/nist_xraymac/` (+ `MANIFEST.sha256`, `PROVENANCE.md`). The
   build pins a combined hash (`EXPECTED_MANIFEST_SHA256`) and refuses to run on drift.
3. **Transform** (`build_attenuation.py`) — regex-parses each page's data rows
   (`[E, μ/ρ, μ_en/ρ]`, or `[edge, E, μ/ρ, μ_en/ρ]` at absorption edges), looks up
   density from `tab1`/`tab2` (**fails loud** if a material's ρ is absent — no hardcoded
   fallback), preserves exact floats, and raises on any non-positive coefficient,
   `μ_en/ρ > μ/ρ`, non-ascending energy, or out-of-range row. Deterministic + readable.
4. **Loader** `engine/attenuation.py` — single read path; validates schema/name/array
   alignment/ρ; exposes `energies / mu_rho / muen_rho / density / edges`; raises
   `AttenuationError` on a missing/malformed material. **No interpolation here** (below).
5. **Validate** — four independent pillars, TDD (suite written first, confirmed failing
   on the empty dir, then built to green).

### Validation pillars (avoid circular tests)
- **Structural:** schema, array alignment, ascending E in [1 keV, 20 MeV], positive
  finite coefficients, and the free invariant **μ_en/ρ ≤ μ/ρ on every row** (cheapest
  catch for a swapped-column parse); edges are duplicated energies with a label.
- **Transform integrity:** canonical == vendored, re-parsed from the raw HTML by an
  **independent method** (stdlib `HTMLParser`, not the build's regex); the full multiset
  of `(E, μ/ρ, μ_en/ρ)` rows must survive, and density is re-derived independently from
  `tab1`/`tab2`. Catches drop/dup/mis-row/value-mangle/wrong-density.
- **Coverage:** every required dose medium and shield has a file; both directions (no
  stray files). Plus **grid completeness** — every material carries the full 36-point
  NIST base energy grid (anchored externally via edge-free `water`), since the integrity
  pillar is parser-vs-parser and cannot see a row both row-filters would drop (the
  "silent dose hole" class). Six densities are anchored to external handbook values.
- **Physics goldens:** μ/ρ, μ_en/ρ and a **narrow-beam** HVL vs independent
  textbook-rounded values, hardcoded with windows; plus the Pb K-edge.

## Key decisions / risks

- **Narrow-beam vs broad-beam HVL.** μ/ρ alone gives *narrow-beam* HVL = ln2/μ.
  Published HVL/TVL tables and the §10 rules of thumb are usually **broad-beam** (they
  include buildup, ~10–15 % larger). Goldens here assert **narrow-beam** μ; broad-beam
  HVL/TVL validation is deferred to **M3**, where the G-P buildup factor exists.
- **Absorption edges preserved, interpolation deferred to M3.** Both sides of each edge
  (Pb K/L/M; constituent K-edges in concrete/air/tissue) are kept as duplicate-energy
  rows, so the μ/ρ discontinuity is in the data. `np.interp` is ill-defined *at* a
  duplicated x, so **edge-aware log–log interpolation is M3's job**, together with the
  "skip photon lines below the 1 keV table floor, explicitly and logged" rule
  (`data/README.md`). This loader deliberately ships no interpolator.
- **Trust boundary (honesty).** Transform integrity proves *canonical == vendored*; it
  cannot prove *vendored == true NIST physics*. XCOM and H&S share the Berger/Hubbell
  cross-section library, so the goldens catch transcription/unit/column/edge errors, not
  an independent re-evaluation (none exists; H&S is the field standard).
- **License is friendlier than emissions.** NIST SRD is US-Government public domain (17
  U.S.C. §105) — **no non-commercial restriction**, unlike ICRP-107. The repo-license
  constraint still comes from the emission data.
- **Edge labels are metadata.** Element edges are bare shells (`K`, `L1`); compound
  edges are `"<Z> <shell>"` (e.g. `"18 K"` = argon K-edge in air). Whitespace is
  normalised; the numeric coefficients are never altered.

## Carry-forward for M3 (gamma dose)
- Build the **edge-aware log–log interpolator** over (E, μ/ρ) and (E, μ_en/ρ); handle
  duplicate-E edges by bracketing within a segment, never across.
- Enforce the **1 keV floor**: photon lines below the table (ICRP keeps sub-keV lines)
  are skipped explicitly **and logged**, never silently (closes the contract opened in
  the emissions dev-doc / `data/README.md`).
- Dose uses the **μ_en/ρ ratio** between the scoring medium (air for H\*(10), tissue for
  approximate E) and applies μ/ρ·ρ·x attenuation per shield layer with buildup (M3).
