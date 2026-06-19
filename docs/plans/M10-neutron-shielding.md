# M10 — neutron shielding

**Status:** ✅ COMPLETE (engine + bridge + UI shipped; gate green dev+built). See the
"COMPLETION" section at the bottom for what landed, the conscious deferrals, and the one
follow-up surfaced (the pre-existing γ buildup overflow → `docs/plans/gamma-buildup-overflow.md`).

**Status (history):** planning (blocked on data sourcing)
**Milestone (HANDOFF_PLAN.md §6.3 / §9 / honesty register):** close the flagged
"neutron shielding remains unmodeled" gap — the γ shield does not attenuate neutrons.

## Goal
The neutron-dose path (single-source `NeutronDoseModel` **and** multi-parent
`SpentFuelNeutronModel`) must respond to the shield stack the UI already feeds γ/β.
"Done" = a hydrogenous shield attenuates the neutron dose by a citable, validated factor;
a non-hydrogenous (γ-oriented) shield does **not** silently under-count.

Validation anchor (write the test FIRST): a published fission-neutron / Cf-252 dose
TVL or relaxation length in **water** and **polyethylene** — assert the engine's
Cf-252-through-water transmission reproduces it. (Cf-252 is already in the codebase and
is fission-spectrum, the natural benchmark.)

## Plan — method (advisor-confirmed)
Fast-neutron **removal cross-section** Σ_R (cm⁻¹), transmission `T = exp(−Σ_R·x)`. The
standard hand-calc that gives *dose* attenuation directly (no transport solve). Three
structural differences from the γ shield — do NOT clone `dose.py`:

1. **No buildup factor.** Σ_R is already dose-calibrated against fission-spectrum
   measurements; there is no B(E,μx) analog. Do not invent one.
2. **Single energy-independent scalar, not per-line.** A per-bin Σ_R(E) does not exist in
   standard tabulations — building one would be fabrication. The shield is ONE scalar
   `T_n` multiplied into `coeff_si`, not folded per spectral bin.
3. **T_n factors out of the spectrum fold.** `h̄` is unchanged by the shield; `T_n` just
   scales the dose like distance does. Solve-once/evaluate-many trivially preserved. This
   correctly encodes "no spectrum hardening modeled."

### The correctness crux — hydrogen-presence validity gate
Σ_R is only valid when hydrogen is present (removed neutrons thermalize/capture in the
hydrogenous medium). A **non-hydrogenous-only** stack (bare lead/iron) → `exp(−Σ_R·x)`
over-attenuates → **under-counts dose (the dangerous direction)**. So:
- ≥1 hydrogenous layer → apply Σ_R; document the composite-order limit ("enough hydrogen
  behind the heavy layer" not modeled — a §11 line, parallels M8 order-sensitivity).
- non-hydrogenous-only stack → must NOT silently emit a falsely-low number. Loud warning
  (same discipline as the γ "no silent B=1 surrogate"). This IS the §6.3 "steer neutron to
  hydrogenous" teaching feature: the user watches lead do nothing.

### Shared-stack semantics (decision)
Ship Σ_R only for the hydrogenous set (water, polyethylene, concrete, maybe paraffin).
Any material without removal data → **neutron-transparent (Σ_R = 0) + explicit warning**.
Errs *safe* (over-counts), keeps a mixed γ/n stack working, preserves the lead-does-nothing
contrast. Add a `has_removal` flag mirroring `has_buildup` in the materials registry.

## Enumerated touch points
1. `data/neutron_removal/` + PROVENANCE + build script (citable Σ_R). **BLOCKER — see below.**
2. Regression test first: published fission-neutron TVL → Cf-252-through-water assertion.
3. Engine: `neutron_transmission(stack) → T_n` scalar + hydrogen-gate + transparent-with-warning;
   `NeutronDoseModel` and `SpentFuelNeutronModel` accept `shield`, fold `T_n` into `coeff_si`.
4. Bridge: `neutron_dose` and `spent_fuel_neutron_dose` accept/pass `shield`.
5. Materials registry: `has_removal` flag + `materials()` surfaces it; UI radiation-type steering.
6. §11 honesty lines: hydrogenous-only; fission-calibrated/energy-lumped (AmBe harder
   spectrum → less accurate); no spectrum hardening; composite-order not modeled; thick-shield
   deep-penetration under-count direction.
7. UI: neutron dose now responds to shield; dose-vs-thickness drives the neutron series too.

Serializer: shield is already persisted; neutron shield is a derived scalar → likely **no
schema bump**. Verify the round-trip test exercises a neutron-source-plus-shield combo.

## DATA SOURCING — progress + the hydrogen-anomaly finding (2026-06-19)

**Decision (user):** semi-empirical formula route. **Citable source landed:** El Abd, Mesbah,
Mohammed & Ellithi, *"A simple Method for Determining the Effective Removal Cross Section for
Fast Neutrons,"* J. Rad. Nucl. Appl. **2**(2), 53–58 (2017), DOI 10.18576/jrna/020203.
(WebFetch returns binary for these image-PDFs; the **Read tool renders the WebFetch-saved PDF
visually** — that is how the numbers were extracted. Reuse this trick.)

**Wood (1982) semi-empirical elemental mass removal cross-section** (El Abd Eqs 4–5):
- `Σ_R/ρ = 0.190·Z^(−0.743)` cm²/g for **Z ≤ 8**
- `Σ_R/ρ = 0.125·Z^(−0.565)` cm²/g for **Z > 8**
Mixture rule (Eq 1, Kaplan 1989 / Wood 1982): `Σ_R = ρ·Σ_i w_i·(Σ_R/ρ)_i`.

**CRITICAL FINDING — the Wood Z-formula is ~1.8× too low for hydrogen, the dominant
neutron-shielding element.** El Abd Table 1 gives the **measured** water `Σ_R = 0.1023 cm⁻¹`.
Wood-formula water (H₂O, w_H 0.112 / w_O 0.888; H→0.190, O→0.0405) gives only **0.057 cm⁻¹**.
Hydrogen is anomalous (Albert–Welton 1950: its *entire* cross-section is effective for removal,
≈0.6 cm²/g), and the flat Z≤8 branch (0.190) badly under-counts it. Back-solving El Abd's
measured water with the Wood oxygen value requires `(Σ_R/ρ)_H ≈ 0.592 cm²/g`, consistent with
the classic tabulated ~0.602. **⇒ the naive formula route would make hydrogenous shields
under-attenuate ~2× (over-count dose — the safe direction, but wrong).** Validation-first
caught it: **water = 0.1023 cm⁻¹ (El Abd, measured) is the regression anchor** and it rejects
the naive formula.

**RESOLVED — elemental Σ_R/ρ sourced (NCRP-20 via a clean secondary):** Akyıldırım, H.
(2019), *"Calculation of Fast Neutron Shielding Parameters for Some Essential Carbohydrates,"*
Erzincan Univ. J. Sci. Tech. **12**(2), 1141–1148, DOI 10.18185/erzifbed.587514, p.1144 states
the NCRP-20 (1957) measured mass removal cross-sections:
- **H = 0.602 cm²/g, C = 0.051 cm²/g, O = 0.041 cm²/g**
- mixture rule `Σ_R = Σ_i ρ_i·(Σ_R/ρ)_i`, `ρ_i = ρ·w_i` (its Eq. 3).

These are *measured* values; the Wood Z-formula (which gave H=0.190) is NOT used — it fails for
hydrogen, the dominant element. Two-source cross-validation:
- **Glucose** C₆H₁₂O₆ ρ=1.562 → 0.400·0.051 + 0.067·0.602 + 0.533·0.041 = 0.0827 ×1.562 =
  **0.129 cm⁻¹**, reproducing Akyıldırım Table 2 EXACTLY (validates the mixture-rule impl).
- **Water** H₂O → 0.112·0.602 + 0.888·0.041 = 0.1038 ×1.0 = **0.104 cm⁻¹**, matching El Abd's
  *independently measured* 0.1023 cm⁻¹ to ~1.5% (validates the data + light-element handling).

**Material set (shipped):** water (ρ=1.0), polyethylene CH₂ (ρ=0.93), paraffin (~CH₂, ρ=0.93)
— the pure hydrogenous shields, all computable from H/C/O. **Concrete deferred** (needs
Si/Ca/Al/Fe Σ_R/ρ not yet sourced; do not mix NCRP-20 light-element data with a Wood-formula
heavy-element fit — same no-fabrication discipline as the AmBe deferral). `has_removal=true`
only for the shipped hydrogenous set; everything else (lead, the γ buildup materials) is
neutron-transparent + warning.

**Regression anchors (write before code):**
1. Reproduce Akyıldırım glucose Σ_R = 0.129 cm⁻¹ (mixture rule + data, exact).
2. Water Σ_R within a few % of El Abd's measured 0.1023 cm⁻¹ (independent cross-check).
3. Cf-252-through-water end-to-end: T = exp(−Σ_R·x); relaxation length 1/Σ_R ≈ 9.6 cm.
   (Note: removal-theory poly TVL ≈ ln10/0.12 ≈ 19 cm is ~2× the rough "10 cm poly → 10×" rule
   of thumb; removal gives the LESS-attenuating, dose-conservative estimate — document, don't
   tune to the rule of thumb.)

**Measured compound anchors also in El Abd Table 1 (cm⁻¹, at sample density):** H₂O 0.1023,
graphite-C 0.0773, polyethylene grains 0.0789, SiO₂ 0.0588, CaCO₃ 0.0234, Fe 0.1689,
Fe/H₂O 0.155 — useful as cross-checks, but densities (grains/powder/solution) ≠ bulk solid,
so prefer the elemental-table + bulk-density route for the shipped material set.

## Open questions / risks — DATA SOURCING IS THE BLOCKER
- **Canonical Σ_R provenance = NCRP Report No. 20 (1957)** ("Protection against Neutron
  Radiation up to 30 MeV") — the compiled elemental mass removal cross-sections
  Σ_R/ρ (cm²/g); compound Σ_R = ρ·Σ_i w_i·(Σ_R/ρ)_i (the mixture rule, what El-Khayatt
  et al. and the MERCSF-N tool implement). Also tabulated in Chilton/Shultis/Faw
  *Principles of Radiation Shielding* and Shultis & Faw *Radiation Shielding*.
- **Could not extract clean, transcribable numbers within the session:** the El-Khayatt
  Annals-of-Nuclear-Energy compound tables are paywalled/403 (academia.edu, researchgate,
  ScienceDirect, MDPI); the open PDFs are image-based and WebFetch returns binary, not text.
  Per the no-fabrication discipline (cf. the AmBe spectrum, the beta Cross-Berger kernel) the
  Σ_R values are NOT transcribed from memory — sourcing is deferred to a clean citable table.
- **Physics subtlety to resolve WITH the real data, not from memory:** the removal-cross-section
  relaxation length for water/poly (~10 cm order) does NOT obviously match the common
  "10 cm polyethylene → factor-10 dose reduction" rule of thumb (that implies TVL ≈ 10 cm,
  i.e. Σ_R ≈ 0.23 cm⁻¹, ~2× a typical removal value). The validation benchmark must be a
  *properly published* fission/Cf-252 dose TVL so this is reconciled against a source, not a
  guess. Removal underestimates dose for THICK shields (deep-penetration intermediate-neutron
  buildup) → caveat the under-count direction.

## Validation leads (untried / to confirm)
- NCRP-20 (1957) elemental Σ_R/ρ table — the primary; need a clean copy.
- IOP *J. Radiol. Prot.* (2026) "Neutron tenth-value layers in polyethylene…" — paywalled PDF.
- Vega-Carrillo / IAEA shielding tabulations for Cf-252 attenuation.

## COMPLETION (2026-06-19)

**Shipped — the full vertical slice, all touch points 1–7 closed:**
1. **Data** (already landed): `data/neutron_removal/{water,polyethylene,pmma}.json` (NCRP-20
   Σ_R/ρ × mixture rule) + `tests/test_neutron_removal.py`. M10 added `neutron_removal` to the
   web runtime archive (`web/scripts/build-archive.mjs` `DATA_DIRS`) — it was missing, so the
   browser engine couldn't load Σ_R until this fix (caught by the harness, not unit tests).
2. **Engine** `engine/neutron_dose.py`: `neutron_transmission(shield) → (T_n, warnings)` —
   `T_n = exp(−Σ Σ_R·x)` over hydrogenous layers; non-removal layers transparent + warned;
   non-hydrogenous-only stack → `T_n=1` + loud `no_hydrogenous_layer`; mixed → `composite_order`
   caveat. `NeutronDoseModel` **and** `SpentFuelNeutronModel` take `shield=`, fold `T_n` into
   `coeff_si` once (h̄ untouched → no spectrum hardening). `T_n` surfaced in the result dict.
3. **Bridge**: `neutron_dose` + `spent_fuel_neutron_dose` accept/pass `shield`; the source-
   correlated γ (AmBe) is shielded by the SAME stack through the γ engine. `materials()` gains
   `has_removal`. Tests in `test_bridge.py`, `test_dose_neutron.py`, `test_dose_spent_fuel_neutron.py`.
4. **UI**: the shared shield stack now drives the neutron dose (`state.svelte.ts`
   `recomputeNeutron`); the Dose card shows the attenuation factor / the "steer-to-hydrogenous"
   warning; Honesty gains the removal-method §11 item; Shield note updated. Harness check added
   (water attenuates, lead transparent + neutron card survives the γ overflow).

**Symmetric orphan guard (M10-scoped fix, advisor):** `recomputeDose` was split into
`recomputeGammaBeta` + `recomputeNeutron` so a γ failure clears ONLY the γ/β series — the
neutron card renders regardless. This was forced by the discovery below.

**Conscious deferrals (NOT silent gaps):**
- **Neutron dose-vs-thickness band (touch point 7):** the γ Shield panel has a dose-vs-thickness
  sweep; the neutron equivalent (a single `exp(−Σ_R·x)` curve) is NOT added. The neutron dose
  DOES respond to the shield at the cursor (the core deliverable); the thickness *sweep widget*
  for neutrons is deferred — low value (trivial exponential, no per-line structure) vs. UI cost.
- **Picker boundary:** poly/PMMA carry `has_removal=true` but are NOT selectable in the shield
  picker (it filters to `has_buildup`, and they have none). **Water is the only UI-selectable
  hydrogenous shield** (it has both flags). poly/PMMA stay validation-only. This is the intended
  M10 boundary — opening the picker to no-buildup materials would blank the γ panel (the γ engine
  raises without buildup). Revisit if a neutron-only shield UI is wanted later.
- **Concrete / paraffin** removal data still deferred (heavy-element Σ_R/ρ unsourced — no-fab).

**Follow-up surfaced (separate, pre-existing — NOT M10):** the γ G-P buildup **OverflowError**
for a low-energy line through very thick high-Z (e.g. Am-241 59 keV + 5 cm lead, confirmed with a
plain `bridge.dose()`, no neutrons) — the buildup fit is evaluated hundreds of mfp past its
validated ~40 mfp range. M10 only made it routine (lead-on-a-neutron-source) and contained the
blast radius (symmetric isolation). The fix (cap the buildup *argument* at the table's valid mfp,
§11-noted) is its own γ-engine task → `docs/plans/gamma-buildup-overflow.md`.
