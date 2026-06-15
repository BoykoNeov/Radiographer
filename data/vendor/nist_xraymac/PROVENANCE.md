# Vendored upstream — NIST X-Ray Mass Attenuation Coefficients

Raw upstream pages for the **attenuation** dataset (μ/ρ and μ_en/ρ vs energy per
material; `HANDOFF_PLAN.md` §7), vendored verbatim so the data build is hermetic and
the provenance chain lives entirely in-repo.

## Source chain

| Layer | Detail |
|---|---|
| Primary data | **NIST Standard Reference Database 126** — *Tables of X-Ray Mass Attenuation Coefficients and Mass Energy-Absorption Coefficients*, J.H. Hubbell & S.M. Seltzer (orig. NISTIR 5632, 1995; v1.4, 2004). |
| Host | `https://physics.nist.gov/PhysRefData/XrayMassCoef/` |
| This repo | `elem/z<Z>.html`, `comp/<name>.html` (per-material μ/ρ + μ_en/ρ tables) and `tab1.html` / `tab2.html` (the density index for elements / compounds), copied **byte-for-byte** as served. |

### "NIST XCOM" vs what this actually is (correcting §7)

`HANDOFF_PLAN.md` §7 lists the source as "NIST XCOM". **XCOM** (SRD 8) tabulates
**μ/ρ only** — it does *not* provide the mass **energy-absorption** coefficient
μ_en/ρ, which the dose engine needs (the `E·y·(μ_en/ρ)` line-sum, §6). μ_en/ρ lives
in the **Hubbell & Seltzer** tables (SRD 126), a superset that gives both
coefficients for the 92 elements and ~48 compounds/mixtures over **1 keV – 20 MeV**.
We therefore source from H&S, not XCOM proper. Same NIST cross-section lineage
(Berger/Hubbell), so the two are not independent evaluations — see the trust-boundary
note in `../../README.md`.

## Materials vendored

- **Elements** (`elem/z<Z>.html`): lead (82), tungsten (74), iron (26), copper (29),
  aluminium (13). Densities from `tab1.html` (keyed by Z).
- **Compounds** (`comp/<name>.html`): Water, Liquid · Air, Dry (near sea level) ·
  Tissue, Soft (ICRU-44) · Concrete, Ordinary · Polymethyl Methacrylate (PMMA/Lucite)
  · Polyethylene. Densities + exact material names from `tab2.html` (keyed by name).

> The NIST concrete is **"Concrete, Ordinary"** (ρ ≈ 2.30 g/cm³), not the §7
> "Portland" wording — there is no separate Portland entry; ordinary structural
> concrete is the standard shielding reference. Pinned and named explicitly.

## Page format (upstream, as-is)

Each per-material page is an HTML table. Data rows are `<TR>` with **3 cells**
`[E_MeV, μ/ρ, μ_en/ρ]` or **4 cells** `[edge_label, E_MeV, μ/ρ, μ_en/ρ]`. At an
absorption edge there are **two rows at the same energy**: the blank-label row is the
value *below* the edge, the labelled row (`K`, `L1`, `L2`, `L3`, `M1`…`M5`) is the
value *above* it (μ/ρ steps up). Energies are MeV; coefficients are cm²/g. `tab1`/
`tab2` carry Z/A, mean excitation energy I, and **density** (g/cm³) per material.

## Drift guard

`MANIFEST.sha256` lists `<sha256>  <relpath>` for all 13 files. The build
(`../../build/build_attenuation.py`) recomputes a combined hash over the sorted
manifest and **refuses to run** unless it matches the pinned `EXPECTED_MANIFEST_SHA256`:

```
ebb10026976a004110bafd7a7766598e7e0b3926b933b34253c5a11e29a8fd8a
```

So the committed canonical files can never be silently rebuilt from changed inputs.

## License

NIST Standard Reference Data produced by U.S. Government employees as part of their
official duties — **public domain** in the United States (17 U.S.C. §105); NIST
requests citation. Unlike the ICRP-107 emission data, this dataset carries **no
non-commercial restriction**.

## Re-vendoring (only to deliberately bump upstream)

```sh
python data/build/fetch_nist_xraymac.py     # re-pull the pages (verbatim bytes)
# regenerate MANIFEST.sha256, update EXPECTED_MANIFEST_SHA256 in build_attenuation.py,
# rebuild, and re-run the full validation suite.
```
