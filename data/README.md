# `data/` — bundled physics datasets

> **The datasets are the project.** (`../CLAUDE.md`, `HANDOFF_PLAN.md` §7.) These
> are versioned, auditable static tables loaded and interpolated in pure
> Python/numpy — no C-extension data libraries exist client-side. Each table ships
> with a regression suite that runs the moment it lands.

## Layout

| Path | What |
|---|---|
| `emissions/<Nuclide>.json` | **Canonical** per-nuclide emission spectra (this project's schema). Generated; committed. |
| `attenuation/<material>.json` | **Canonical** per-material μ/ρ & μ_en/ρ vs energy (this project's schema). Generated; committed. |
| `buildup/<material>.json` | **Canonical** per-material G-P (exposure) buildup coefficients (this project's schema). Generated; committed. |
| `conversion/{hstar10,effective_<geom>}{,_neutron}.json` | **Canonical** fluence-to-dose coefficients — H\*(10) + effective dose per geometry, for **photon** (M2) and **neutron** (M5). Generated; committed. |
| `neutron_sources/<source>.json` | **Canonical** tabulated neutron source terms — neutrons/decay + normalized spectrum + source-γ (this project's schema; M5). Generated; committed. |
| `internal_dose/{worker,public_adult}.json` | **Canonical** committed-effective-dose coefficients e(50) (Sv/Bq), per nuclide, for ingestion + inhalation (ICRP-68 worker / ICRP-72 public-adult; M13). Generated; committed. |
| `vendor/icrp107/` | Raw upstream ICRP-107 JSON, vendored verbatim. See `vendor/PROVENANCE.md`. |
| `vendor/nist_xraymac/` | Raw upstream NIST H&S pages, vendored verbatim. See `vendor/nist_xraymac/PROVENANCE.md`. |
| `vendor/ans643/` | NUREG/CR-5740 PDF (public-domain ANS-6.4.3 buildup source) + hand-keyed transcription + B-value spot-checks. See `vendor/ans643/PROVENANCE.md`. |
| `vendor/openmc_dose/` | OpenMC dose tables: ICRP-116 effective dose (photon+neutron, verbatim) + ICRP-74 H\*(10) (photon+neutron, unmerged PR). See `vendor/openmc_dose/PROVENANCE.md`. |
| `vendor/icrp119/` | ICRP-119 PDF (free) — source of the internal-dose e(50) coefficients (ICRP-68/72), visually transcribed. See `vendor/icrp119/PROVENANCE.md`. |
| `vendor/MANIFEST.sha256`, `vendor/nist_xraymac/MANIFEST.sha256`, `vendor/openmc_dose/MANIFEST.sha256` | Per-file hashes of each vendored source (drift guard). |
| `build/build_emissions.py`, `build/build_attenuation.py`, `build/build_buildup.py`, `build/build_conversion.py`, `build/build_neutron_sources.py`, `build/build_internal_dose.py` | Transforms: `vendor/…` (or analytic reconstruction) → `emissions/` / `attenuation/` / `buildup/` / `conversion/` / `neutron_sources/` / `internal_dose/`. Dev-time only. |
| `build/fetch_nist_xraymac.py` | One-time acquisition of the NIST pages (verbatim). Dev-time only. |
| `LICENSE.ICRP-07` | The license governing the emission data (see below). |

**All §7 datasets have landed**, plus the post-v1 extension data. Coverage: emissions ✅,
attenuation ✅, G-P buildup ✅, H\*(10) & effective-dose conversion ✅ [photon + neutron],
neutron sources ✅ [Cf-252 + **AmBe**, sourced at M7d from IAEA TRS-403], spent-fuel
discharge vectors ✅ (M7c), bomb fallout ✅ (M7d), neutron removal ✅ (M10/M11), internal-dose
coefficients ✅ (M13).

## Emissions — canonical schema (`schema_version: 1`)

```jsonc
{
  "schema_version": 1,
  "nuclide": "Co-60",
  "source": "ICRP-107 (Endo & Eckerman 2008 …); reformatted via OpenGATE/icrp107-database 0.0.3",
  "photons":  [ { "E_MeV": 1.17323, "yield": 0.9985, "origin": "gamma" } ],  // gamma ∪ X ∪ annihilation, ASCENDING in E
  "betas":    [ { "E_mean_MeV": 0.0958654, "yield": 0.9988, "kind": "beta-" } ],  // ICRP energy is the MEAN
  "alphas":   [ { "E_MeV": 5.234, "yield": 0.71 } ],
  "electrons":[ { "E_MeV": 1.16493, "yield": 0.00015, "origin": "IE" } ],     // auger + internal-conversion
  "neutrons": [ { "E_MeV": 2.306, "yield": 0.116 } ],
  "beta_spectra": [ { "E_MeV": 0.0, "intensity": 6.626 } ],                    // continuous dN/dE
  "extra": { "alpha recoil": [[E,v],…], "fission": […], "betaD": […] }         // verbatim; semantics deferred
}
```

Design choices (M2 review — `docs/plans/M2-emissions.md`):

- **Photons are aggregated** (gamma ∪ X-ray ∪ annihilation) because the dose
  engine sums them identically; `origin` preserves provenance and lets the
  chain/teaching views filter to gamma-only. Annihilation yields are **per
  photon** (verified on Na-22: 0.511 MeV ≈ 1.80 ≈ 2× the β⁺ branch).
- **No line is dropped.** Negligible sub-keV X-rays are kept; thresholding is a
  *documented* parameter of the M3 dose engine, never a silent data reduction.
- **Half-life is NOT stored here** — `radioactivedecay` is the single source of
  truth. The build only uses the upstream half-life as a parse canary.
- `beta_spectra` (`b-spectra`) is a spectrum **summed over decay branches** — M4
  beta dosimetry must account for that (Co-60's 1.49 MeV tail is the rare 0.12 %
  branch, not the main 0.318 MeV endpoint).

### ⚠️ For M3 (gamma dose)
ICRP includes photon lines down to ~14 eV — **below where the NIST attenuation
tables start (1 keV)**. The dose engine must skip below-table photons
**explicitly and logged**, never silently. Keep the lines in the data.

## Attenuation — canonical schema (`schema_version: 1`)

```jsonc
{
  "schema_version": 1,
  "material": "lead",            // this project's stable slug / file stem
  "name": "Lead",               // NIST display name ("Concrete, Ordinary", "Tissue, Soft (ICRU-44)", …)
  "kind": "element",            // element | compound
  "Z": 82,                       // elements only
  "rho_g_cm3": 11.35,            // density, from the NIST tab1/tab2 index (never hardcoded)
  "source": "NIST X-Ray Mass Attenuation Coefficients (Hubbell & Seltzer, NIST SRD 126 …)",
  "E_MeV":          [ … ],       // ASCENDING; DUPLICATED at absorption edges
  "mu_rho_cm2_g":   [ … ],       // mass attenuation μ/ρ  → shielding I = I₀·e^(−μx)
  "muen_rho_cm2_g": [ … ],       // mass energy-absorption μ_en/ρ → dose line-sum E·y·(μ_en/ρ)
  "edges": [ { "label": "K", "E_MeV": 0.0880045 }, … ]   // [] for low-Z compounds
}
```

Materials: dose media `air`, `water`, `tissue_soft`; shields `lead`, `tungsten`,
`iron`, `copper`, `aluminium`, `concrete`, `pmma`, `polyethylene`. Source is the
**Hubbell & Seltzer** tables (SRD 126), *not* XCOM proper — XCOM lacks μ_en/ρ; H&S
gives both. See `vendor/nist_xraymac/PROVENANCE.md` and `docs/plans/M2-attenuation.md`.

Design choices (M2 review):

- **Energy range is 1 keV – 20 MeV** (the NIST tabulation). The M3 dose engine skips
  photon lines below 1 keV **explicitly and logged** — the other half of the sub-keV
  contract above.
- **Absorption edges are preserved as duplicate-energy rows** (μ/ρ steps up across an
  edge). `np.interp` is ill-defined *at* a duplicated energy, so **edge-aware log–log
  interpolation belongs to M3**; this dataset ships none.
- **`μ_en/ρ ≤ μ/ρ` always holds** (you cannot absorb more than you attenuate) and is
  asserted per row — the cheapest catch for a swapped-column parse.
- **Density comes from the vendored index pages** (`tab1`/`tab2`), failing loud if
  absent — never a hardcoded substitute (§11).

### ⚠️ Trust boundary (honesty)
XCOM and Hubbell & Seltzer share the **Berger/Hubbell** cross-section lineage, so the
attenuation goldens catch transcription/unit/column/edge errors — **not** an
independent re-evaluation of the underlying physics (none exists; H&S is the field
standard). HVL goldens here are **narrow-beam** (ln2/μ); published *broad-beam*
HVL/TVL include buildup and are validated in M3.

## Buildup — canonical schema (`schema_version: 1`)

```jsonc
{
  "schema_version": 1,
  "material": "lead",
  "name": "Lead",
  "response": "exposure",            // air-kerma; point-isotropic source, infinite medium
  "source": "ANSI/ANS-6.4.3-1991 via NUREG/CR-5740 (Trubey 1991), G-P exposure buildup",
  "E_MeV": [ 0.03, …, 15.0 ],        // ASCENDING; per-material grid (high-Z OMIT 0.015/0.020)
  "gp": [ { "b": …, "c": …, "a": …, "Xk": …, "d": … }, … ]   // Harima G-P, aligned to E_MeV
}
```

The buildup factor `B(E, x)` (x = depth in mean free paths) corrects the point-kernel for
scattered photons: `I = I₀·B·e^(−μx)` (§6.5). Reconstructed from the five G-P coefficients
(see `engine/buildup.py`); `B(0)=1`, `B(1 mfp)=b`. Materials: shields `lead, tungsten,
iron, copper, aluminium, concrete` + media `water, air`. **PMMA, polyethylene, soft tissue
have NO ANS-6.4.3 buildup** — their absence is the honest contract; the M3 dose engine
handles it loudly, never with a silent surrogate.

Design choices (M2 review — `docs/plans/M2-buildup.md`):

- **Degraded provenance.** No clean machine-readable ANS-6.4.3 source exists, so the
  values are **hand-keyed (double-entered)** from the public-domain NUREG/CR-5740 scan; the
  verbatim re-parse integrity model (NIST/ICRP) does not apply here. See
  `vendor/ans643/PROVENANCE.md` for the trust boundary.
- **Exposure response only** (v1); the report's energy-absorption table is not transcribed.
- **Per-material energy grid.** High-Z (lead) starts at 0.03 MeV; the build stores each
  material's own grid. **No energy interpolation in the loader** — that (and the 15 keV /
  15 MeV bound handling) is the **M3** dose engine's job, like the attenuation interpolator.

### ⚠️ Trust boundary (honesty)
Faithfulness is enforced by reconstruction: the coefficients reproduce the report's *own*
Table 3 exposure B-values to **≤ 2.6% for all 8 materials** (37 anchors). **Iron** is
additionally matched against an independent open-access tabulation (EPJ 2016, CC-BY) at 5
energies. Beyond the anchored (E, mfp) points, the rest of each table is trusted to the
double-entered transcription (mirrors the emissions golden-nuclide boundary).

## Conversion — canonical schema (`schema_version: 1`)

```jsonc
// conversion/hstar10.json   — ambient dose equivalent H*(10), ICRP-74/ICRU-57
// conversion/effective_<GEOM>.json — effective dose E, ICRP-116 (GEOM ∈ AP PA LLAT RLAT ROT ISO)
{
  "schema_version": 1,
  "quantity": "ambient_H10",     // ambient_H10 | effective
  "particle": "photon",
  "geometry": null,              // null for H*(10); one of the 6 for effective
  "units": "pSv_cm2",            // dose per fluence (pSv · cm²)
  "source": "ICRP-74 (1996)/ICRU-57 …; via OpenMC (MIT)",
  "E_MeV": [ 0.01, …, 10.0 ],    // ASCENDING; H*(10) 0.01–10 MeV, effective 0.01 MeV–10 GeV
  "coeff_pSv_cm2": [ … ]         // aligned to E_MeV
}
```

Photon **fluence-to-dose** coefficients closing the §6 dose chain: `H*(10) = Σ Φ_i ·
h*(10)/Φ(E_i)` (operational, §6.4 default) or `E = Σ Φ_i · e/Φ(E_i, geometry)` (effective,
per body orientation). The two are **different quantities, computed differently — never
compare directly** (§6.4, §11). Source is **OpenMC**'s machine-readable ICRP tables (the
coefficients are ICRP/ICRU facts; see `vendor/openmc_dose/PROVENANCE.md` and
`docs/plans/M2-conversion.md`).

Design choices (M2 review):

- **Photon + neutron** (M2 photon, M5 neutron). The `particle` field selects the table;
  neutron files carry a `_neutron` suffix and a wider grid (thermal 1e-9 MeV → 20 MeV for
  H\*(10), 10 GeV for effective). Electrons/positrons are out — external beta is *skin
  dose* (M4). The loader takes `particle` (default `photon`, so M2 call sites are unchanged).
- **Two vintages, both §6.4-LOCKED.** H\*(10) = **ICRP-74/ICRU-57** (operational, ICRU
  sphere, no geometry); E = **ICRP-116** (per geometry). A 2026 "H\*(10)" search surfaces
  the **ICRU-95/2020** revision — *different* values; we pin the ICRP-74 vintage (its
  sphere signature: H\*(10)/Ka peak ≈ 1.77 @ 60 keV).
- **Per-quantity grid (no shared grid).** ICRP-74 photons stop at **10 MeV**; ICRP-116 runs
  to **10 GeV**. **No interpolation in the loader** — log-E interpolation, the **10 keV
  scoring floor** (higher than the 1 keV attenuation floor), and the off-grid >10 MeV /
  >10 GeV handling are the **M3** dose engine's job, explicit + logged.

### ⚠️ For M3 (gamma dose)
A **new scoring-side 10 keV (0.01 MeV) floor** applies to *both* conversion quantities —
photon lines below it have no coefficient and must be skipped **explicitly and logged**
(extend the sub-keV contract). **H\*(10) above 10 MeV is off-grid** (grid end); never
extrapolate.

### ⚠️ Trust boundary (honesty)
**Effective** is verbatim from OpenMC (incl. ICRP-116 **corrigendum** — small diffs vs other
reproductions at corrected energies are expected, *not* errors), cross-checked against an
*independent* ICRP-116 piecewise-poly fit (PMC6074822, ≤3 %; vendored AP matches ≤1.2 %).
**H\*(10)** is transcribed from an **unmerged** OpenMC PR; faithfulness is
enforced by an independent-quantity cross-check (H\*(10)/Φ ÷ OpenMC's independent ICRP-74
Ka/Φ reproduces the ICRU-57 sphere response, anchored to the **IAEA** slab table where
sphere == slab). The 50–200 keV interior and >3 MeV tail rest on the transcription; decay
gammas (≤ ~2.6 MeV) sit inside the three-way-validated range.

## Neutron sources — canonical schema (`schema_version: 1`)

```jsonc
// neutron_sources/Cf-252.json
{
  "schema_version": 1,
  "source": "Cf-252",
  "parent_nuclide": "Cf-252",          // inventory nuclide whose decay drives emission
  "neutrons_per_decay": 0.1165,        // time-invariant; S(t) = n/decay · A_parent(t)
  "spectrum_model": "ISO 8529-1 Maxwellian, T=1.42 MeV",
  "mean_energy_MeV": 2.13,
  "spectrum": { "E_lo_MeV": [ … ], "E_hi_MeV": [ … ], "fluence_frac": [ … ] },  // Σ frac = 1
  "source_gammas": [ /* {E_MeV, yield_per_decay} */ ]   // reaction γ (photon_override); [] for Cf-252
}
```

Tabulated neutron source terms (§6.3 — v1 does NOT derive neutron output from a loaded
inventory). Strength = `neutrons_per_decay · A_parent(t)` (so the neutron view rides the same
solved inventory as gamma); the dose engine folds the normalized spectrum against the
**neutron** fluence-to-dose coefficients. See `docs/plans/M5-neutron.md`.

Design choices (M5 review):

- **Per-bin fluence fractions that sum to 1** — NOT per-lethargy. Neutron spectra are usually
  tabulated per unit lethargy (φ_E·E); the build converts to per-bin fractions and asserts
  Σ = 1 at the one place it's checkable (the §12 normalization trap).
- **Cf-252 spectrum is reconstructed** from the ISO 8529-1 Maxwellian (T=1.42 MeV) — analytic,
  citable, no transcription; `neutrons_per_decay` (SF branch × ν̄) is **self-validated** to
  reproduce the canonical 2.30×10¹² n/s/g specific yield. Capped at 20 MeV (neutron H\*(10)
  grid end); the dropped tail is ~1e-6.
- **Source-correlated γ** (AmBe 4.438 MeV, …) are reaction γ — NOT in the ICRP-107 decay
  lines — scored through the M3 gamma engine via `photon_override`. Cf-252 prompt-fission γ
  (a continuum) is unmodeled in v1 (§11), so its `source_gammas` is `[]`.
- **AmBe shipped at M7d** — sourced from **IAEA TRS-403 (2001) Table 4.V** (open access): the
  ISO 8529 spectrum (folds to H\*(10) ≈ 393.6 pSv·cm², matching the published 391 to <1%), a
  construction-dependent yield (±15%), and the 4.438 MeV reaction γ via `photon_override`. See
  `docs/plans/M7-sources.md` and HANDOFF_PLAN §11.

### ⚠️ Trust boundary (honesty)
The neutron **effective** table is verbatim from OpenMC mainline (clean, blob-SHA == tree);
the neutron **H\*(10)** table is the unmerged PR #3256 transcription (degraded). Faithfulness
of H\*(10) is cross-checked by the **validation triangle**: the reconstructed Cf-252 spectrum
folded against it gives 383 pSv·cm², matching an independently **read** published value —
373 pSv·cm² (ICRP-74, JANP-4-005 Table 1) to +2.7 % (the Maxwellian-vs-tabulated-spectrum gap)
and the commonly-cited ISO 8529-2 ~385 to <1 % (`tests/test_dose_neutron.py`).

## Rebuilding & validating

```sh
python data/build/build_emissions.py        # vendor → emissions (idempotent)
python data/build/build_attenuation.py      # vendor → attenuation (idempotent)
python data/build/build_buildup.py          # vendor → buildup (idempotent)
python data/build/build_conversion.py       # vendor → conversion, photon+neutron (idempotent)
python data/build/build_neutron_sources.py  # analytic/vendor → neutron_sources (idempotent)
python -m pytest tests/test_emissions_data.py tests/test_attenuation_data.py \
                 tests/test_buildup_data.py tests/test_conversion_data.py \
                 tests/test_neutron_sources_data.py tests/test_dose_neutron.py
```

The build fails loudly on any structural surprise (unknown category, bad row,
name/filename mismatch, vendored-byte drift). The suite checks four independent
pillars: schema sanity, transform integrity (canonical == upstream, re-derived
independently), coverage (every radioactive nuclide rd knows has a file — no
silent dose holes), the half-life parse canary, and physics goldens asserted
against independent NNDC/ENSDF intensities.

**Trust boundary (honesty):** transform integrity proves *canonical == upstream*;
it cannot prove *upstream == true ICRP-107*. Faithfulness to the underlying
publication is independently verified only for the **golden nuclides** (Co-60,
Ba-137m, Am-241, Na-22, I-131, Tc-99m); for the other ~1246 nuclides we trust the
`OpenGATE/icrp107-database` reformat. This is unavoidable (1252 nuclides can't be
hand-re-derived) — a future cheap strengthener is a coarse per-nuclide invariant
(Σ photon yield finite, dominant-line energy plausible).

## License — read before redistributing

> The repo-level licensing is settled: **code is MIT (`/LICENSE`), bundled data
> keeps its upstream terms (`/NOTICE`).** The per-dataset terms below are the detail
> behind that NOTICE.

The emission data derives from **ICRP Publication 107** and is governed by
`LICENSE.ICRP-07` (© 2008 A. Endo & K.F. Eckerman). It permits use, copying, and
distribution **for educational, research, and not-for-profit purposes** provided
the license text travels with it — it **does not grant commercial use**. This
constrains the project's *eventual* repo license (currently deferred): the repo
cannot grant commercial rights over this bundled data.

The **attenuation** data (`attenuation/`, `vendor/nist_xraymac/`) derives from **NIST
SRD 126** — a U.S.-Government work, **public domain** (17 U.S.C. §105), NIST requests
citation. It carries **no** non-commercial restriction; the repo-license constraint
above comes solely from the ICRP-107 emission data.

The **conversion** data (`conversion/`, `vendor/openmc_dose/`) is vendored from **OpenMC**
(**MIT**, `vendor/openmc_dose/LICENSE.OpenMC`); the underlying H\*(10)/effective-dose
coefficients (photon + neutron) are **ICRP-74/ICRU-57 and ICRP-116 facts** (not
copyrightable). MIT carries **no** non-commercial restriction — again, only the ICRP-107
emission data constrains the repo license.

The **neutron source** data (`neutron_sources/`) is **reconstructed from public physics
facts** — the ISO 8529-1 Cf-252 Maxwellian parameter and NNDC/Holden SF-branch, ν̄,
half-life, and atomic-mass constants — not transcribed from a copyrightable table. No new
license restriction. (The AmBe spectrum is from **IAEA TRS-403**, open-access and cited.)

The **internal-dose coefficients** (`internal_dose/`, `vendor/icrp119/`) derive from **ICRP
Publication 119** (consolidating the ICRP-68 worker and ICRP-72 public values). Like
ICRP-107, ICRP content is reproduced here for **non-commercial, educational / reference use
only** — it carries the **same non-commercial constraint** and does not worsen the position
ICRP-107 already sets.

The **spent-fuel discharge vectors** (`spent_fuel/`, `vendor/sckcen_sf/`) are from the
**SCK-CEN Serpent2 library** (Mendeley DOI 10.17632/shv89y2zzd), released **CC-BY-4.0** —
redistributable with attribution, **no** non-commercial restriction.

The **fallout** data (`fallout/`, `vendor/endf_nfy/`) uses **ENDF/B-VIII.0** U-235 thermal
fission yields from the NNDC — public, no non-commercial restriction.

The **neutron-removal** data (`neutron_removal/`, `vendor/ncrp20_removal/`, with the SF ν̄
tables in `vendor/iaea_sf_nu/` and `vendor/llnl_sf_multiplicity/`, and the (α,n) yields in
`vendor/panda_alpha_n/`) is reconstructed from **published measured values** (NCRP-20 removal
cross-sections, IAEA/Holden ν̄, PANDA/NUREG-CR-5550 oxide yields) — physics facts, not
copyrightable tables. No new license restriction.

**Net:** the only non-commercial constraint on the bundle comes from the **ICRP** data
(ICRP-107 emission spectra and ICRP-68/72/74/116/119 dose coefficients). Everything else is
public-domain, CC-BY, MIT, or reconstructed physics facts. See `/NOTICE`.
