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

**Mixture-rule (pure H/C/O, measured elemental Σ_R/ρ):** **water, polyethylene (CH₂)ₙ,
PMMA (C₅H₈O₂), paraffin (CₙH₂ₙ₊₂, n=25)**. Paraffin is pure H/C — the SAME measured elemental
values as polyethylene, no new empiricism. Bulk densities come from the existing
`data/attenuation/<material>.json` (single density source, γ↔n consistency); paraffin has no
γ-attenuation file, so its density is declared inline: ρ = 0.93 g/cm³ (NIST/PNNL "Paraffin wax";
grade-dependent 0.87–0.93 — the upper, standard-reference end).

**Published whole-material (concrete):** ordinary concrete's heavy elements (Si/Ca/Al/Fe/Na/K/…)
have **no** measured Σ_R/ρ in the NCRP-20 light-element set above. Reconstructing them from the
Wood (1982) empirical Z-fit is *unanchored* — we have no measured element above Z=8 to validate
that branch, and a trial Wood reconstruction undershot the published whole-material value by
~12%. So per the user's instruction order (*credible source first, empirical only as fallback*),
concrete ships a **directly published** value:

> Ahmed, R., Hassan, G.S., Scott, T. & Bakr, M. (2023). *Assessment of Five Concrete Types as
> Candidate Shielding Materials for a Compact Radiation Source Based on the IECF.* Materials
> **16**(7), 2845. DOI 10.3390/ma16072845. Ordinary concrete **OC-2**: Σ_R = **0.09989 cm⁻¹** at
> ρ = 2.35 g/cm³ (composition Table 1; H 0.56 wt%).

OC-2 is the **lowest-Σ_R / lowest-hydrogen** of the five concretes in that study — chosen
deliberately because it *errs safe* (less attenuation → higher predicted dose). The published
Σ_R is **mass-normalized** to its density-independent form Σ_R/ρ = 0.09989/2.35 = 0.04251 cm²/g,
then **re-densified at the repo's γ-attenuation density** (ρ = 2.3 g/cm³, `data/attenuation/
concrete.json`) → Σ_R = **0.0978 cm⁻¹**, so the SAME physical slab thickness drives both the γ
and the neutron path. The published ordinary-concrete band itself is wide (OC-2 0.0999 →
OC-1 0.1496 cm⁻¹), driven mostly by water/hydrogen content — see the honesty register.

**Still deferred:** borated polyethylene (needs a boron capture term beyond fast-neutron removal).

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
- **Concrete Σ_R is mix-dependent (±~50%).** The shipped concrete value is ONE published
  ordinary-concrete mix (OC-2, low hydrogen). Real concrete Σ_R varies strongly with water
  content, aggregate, and density — the same study spans 0.0999→0.1496 cm⁻¹ for "ordinary"
  concrete, and heavy/serpentine concretes go higher (≈0.37). The shipped low-end value
  under-states attenuation for wetter/denser mixes — the *safe* direction for a dose tool, but a
  real ×1.5 uncertainty. (Surfaced in the UI's neutron dose-vs-thickness widget.)
- **Paraffin density grade.** Σ_R scales with ρ; paraffin wax ρ varies 0.87–0.93 g/cm³ by grade,
  a ~±3% band on the shipped Σ_R.
