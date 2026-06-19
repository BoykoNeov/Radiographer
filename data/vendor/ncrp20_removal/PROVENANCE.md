# NCRP-20 fast-neutron mass removal cross-sections — provenance

**Used for:** M10 neutron shielding (HANDOFF_PLAN.md §6.3 / §9). The fast-neutron
**effective removal cross-section** Σ_R (cm⁻¹) gives the dose attenuation of a hydrogenous
shield directly: `T = exp(−Σ_R·x)`. No buildup factor (Σ_R is already dose-calibrated against
fission-spectrum measurements); single energy-independent scalar per material (valid 2–12 MeV,
fission spectrum). See `docs/plans/M10-neutron-shielding.md`.

## Primary source

**NCRP Report No. 20 (1957)** — *Protection against Neutron Radiation up to 30 Million
Electron Volts*, National Bureau of Standards Handbook 63, US Dept. of Commerce — is the
compiled source of the elemental **mass removal cross-sections** Σ_R/ρ (cm²/g). These are
*measured* values; the Wood (1982) semi-empirical Z-fit is **NOT** used here because it badly
under-counts hydrogen (it gives H ≈ 0.190 cm²/g vs the measured 0.602), and hydrogen dominates
fast-neutron removal in hydrogenous shields.

## Transcription secondary (machine-readable values taken from here)

NCRP-20 itself was not obtained as a clean digital table within the session; the three light-
element values needed for the pure hydrogenous shield set were transcribed from a peer-reviewed
secondary that quotes NCRP-20 verbatim and is reproducible:

> Akyıldırım, H. (2019). *Calculation of Fast Neutron Shielding Parameters for Some Essential
> Carbohydrates.* Erzincan University Journal of Science and Technology **12**(2), 1141–1148.
> DOI 10.18185/erzifbed.587514. p.1144: "The mass removal cross sections of constituent
> elements have been compiled from NCRP report (NCRP No. 20, 1957), which are **0.051 cm²/g for
> Carbon, 0.602 cm²/g for Hydrogen and 0.041 cm²/g for Oxygen**." Mixture rule (its Eq. 3):
> `Σ_R = Σ_i ρ_i·(Σ_R/ρ)_i`, `ρ_i = ρ·w_i`.

| Element | Z | Σ_R/ρ (cm²/g) |
|---------|---|---------------|
| H       | 1 | 0.602         |
| C       | 6 | 0.051         |
| O       | 8 | 0.041         |

## Mixture rule

For a compound of bulk density ρ and element weight fractions w_i:

    Σ_R/ρ (compound) = Σ_i w_i · (Σ_R/ρ)_i        [cm²/g]
    Σ_R (compound)   = ρ · Σ_R/ρ (compound)        [cm⁻¹]

## Validation (two independent sources agree — see tests/test_neutron_removal.py)

- **Glucose** C₆H₁₂O₆, ρ=1.562 g/cm³ → Σ_R = 0.129 cm⁻¹, reproducing Akyıldırım (2019)
  Table 2 **exactly** (confirms the mixture-rule implementation against its own worked example).
- **Water** H₂O → Σ_R = 0.1038 cm⁻¹, matching the **independently measured** value
  Σ_R = 0.1023 cm⁻¹ from El Abd, Mesbah, Mohammed & Ellithi (2017), *A simple Method for
  Determining the Effective Removal Cross Section for Fast Neutrons*, J. Rad. Nucl. Appl.
  **2**(2), 53–58, DOI 10.18576/jrna/020203, Table 1 — to ~1.5%.

## Shipped material set

Only the **pure hydrogenous** shields whose composition is H/C/O are shipped (the §6.3
"hydrogenous, not lead" set): **water, polyethylene (CH₂)ₙ, PMMA (C₅H₈O₂)**. Bulk densities
are taken from the existing `data/attenuation/<material>.json` (single density source, γ↔n
consistency).

**Concrete, paraffin, borated poly are deferred:** concrete needs Si/Ca/Al/Fe Σ_R/ρ not sourced
here; mixing the NCRP-20 measured light-element values with a Wood-formula heavy-element fit
would be an inconsistent dataset (no-fabrication discipline — cf. the AmBe-spectrum deferral).

## Honesty register (→ HANDOFF_PLAN §11, M10)

- **Hydrogenous shields only.** Non-hydrogenous / γ-oriented materials (lead, iron, concrete)
  are neutron-transparent here (Σ_R = 0) + a loud warning — never a silently-low neutron dose.
  The removal-cross-section method is only valid with hydrogen present (removed neutrons must
  thermalize/capture in the medium).
- **Fission-spectrum / energy-lumped.** Σ_R is one number per material, calibrated for the
  ~2–12 MeV fission range; harder spectra (AmBe to ~11 MeV) are less accurate. No spectrum
  hardening is modeled (the shield scales the dose but not h̄).
- **Deep-penetration under-count.** Removal underestimates dose for very thick shields
  (intermediate-neutron buildup) — the dangerous direction; order-of-magnitude grade.
- **Composite-order not modeled.** "Enough hydrogen behind a heavy layer" is assumed, not
  checked (parallels the M8 γ layer-order limit).
