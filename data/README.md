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
| `vendor/icrp107/` | Raw upstream ICRP-107 JSON, vendored verbatim. See `vendor/PROVENANCE.md`. |
| `vendor/nist_xraymac/` | Raw upstream NIST H&S pages, vendored verbatim. See `vendor/nist_xraymac/PROVENANCE.md`. |
| `vendor/MANIFEST.sha256`, `vendor/nist_xraymac/MANIFEST.sha256` | Per-file hashes of each vendored source (drift guard). |
| `build/build_emissions.py`, `build/build_attenuation.py` | Transforms: `vendor/…` → `emissions/` / `attenuation/`. Dev-time only. |
| `build/fetch_nist_xraymac.py` | One-time acquisition of the NIST pages (verbatim). Dev-time only. |
| `LICENSE.ICRP-07` | The license governing the emission data (see below). |

Datasets still to land in M2 (§7): G-P buildup (ANS-6.4.3/Harima), H\*(10) &
effective-dose conversion coefficients, neutron source terms + fluence-to-dose,
spent-fuel discharge vectors. (Emissions ✅, attenuation ✅.)

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

## Rebuilding & validating

```sh
python data/build/build_emissions.py        # vendor → emissions (idempotent)
python data/build/build_attenuation.py      # vendor → attenuation (idempotent)
python -m pytest tests/test_emissions_data.py tests/test_attenuation_data.py
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
