<script lang="ts">
  // Honesty register (M6-ui M6h; HANDOFF_PLAN §11, §0 "the register must be visible").
  //
  // A CONSOLIDATED, in-app surfacing of the §11 accuracy limits. Per-number caveats already
  // live inline next to the values they qualify (Dose.svelte / Shield.svelte / Curves.svelte
  // — the spec's "next to the numbers, not buried"); this panel COMPLEMENTS them, carrying
  // the global limits and — its real job (M6h #6) — the items with NO inline home, chiefly
  // the DATA-PROVENANCE / trust levels (the photon H*(10) table is transcribed from an
  // UNMERGED OpenMC PR; see docs/plans/M2-conversion.md). A pure static renderer — no store
  // reads, no physics. The headline disclaimer is always visible; the detail is collapsible.

  interface Item {
    title: string;
    body: string;
  }
  interface Group {
    heading: string;
    items: Item[];
  }

  const GROUPS: Group[] = [
    {
      heading: "Scope of the model",
      items: [
        {
          title: "Point source in air only (v1)",
          body:
            "Dose is computed for an idealised point source. Self-absorption and finite/dense " +
            "source geometry are NOT modelled — results degrade for large or dense sources. " +
            "There is also no intervening-air attenuation between source and detector: exact " +
            "for penetrating gammas (662 keV transmits ~99% through 1 m of air), but soft " +
            "photons are not removed by the air path. A 10 keV dose-scoring floor stands in for " +
            "this (sub-10 keV lines are dropped from the dose sum — logged, never silent).",
        },
        {
          title: "External dose only — external ≠ internal hazard",
          body:
            "Only external dose is computed. An α emitter reads almost nothing on an external " +
            "survey meter (w_R=20 applies internally) yet can be deadly if inhaled — a Pu pit is " +
            "the classic case. Internal / committed dose is out of scope for v1.",
        },
      ],
    },
    {
      heading: "Per-modality accuracy registers",
      items: [
        {
          title: "Gamma ≈ ±10–15% (the quantitative core)",
          body:
            "Point-kernel sum over emission lines × mass energy-absorption coefficients, " +
            "inverse-square, with ANS-6.4.3 Geometric-Progression buildup. Buildup uses the " +
            "air-kerma (exposure) factor B for ALL THREE quantities (air kerma, H*(10), " +
            "effective) — a documented approximation: the buildup of dose-equivalent ≠ that of " +
            "air kerma.",
        },
        {
          title: "Beta ≈ ±20–30% — a skin-dose quantity, never summed with gamma",
          body:
            "Beta skin dose Hp(0.07) (Gy at 7 mg/cm², w_R=1) via the Loevinger endpoint kernel — " +
            "NOT a spectrum fold; discrete IC/Auger electrons are excluded (e.g. Cs-137's 624 keV " +
            "K-IC electron is not counted). Published skin-dose values themselves disagree ~50% " +
            "(VARSKIN vs Kocher-Eckerman vs Delacroix); this model lands at their median. Beta is " +
            "a contact / near-contact hazard validated within ~factor-2 through air gaps. Hp(0.07) " +
            "is a DIFFERENT quantity from gamma H*(10)/effective — different depth, geometry, and " +
            "meaning — and is shown on its own axis, never added into a gamma total.",
        },
        {
          title: "Bremsstrahlung-in-shield — order-of-magnitude",
          body:
            "Radiated fraction f = 3.5e-4·Z·E_max over a thick-target spectrum; the brems is " +
            "treated as exiting the (β-thin) shield unattenuated. It exists to TEACH the " +
            "“more lead can increase dose” crossover (a high-Z shield emits penetrating " +
            "X-rays a low-Z one does not), not for precise photon dose.",
        },
        {
          title: "Neutron — tabulated, prebuilt sources only",
          body:
            "Neutron source terms are tabulated per prebuilt source (not derived), so neutron " +
            "output is grayed out for user-defined inventories. The dose folds a spectrum against " +
            "ICRP-74 (H*(10)) / ICRP-116 (effective) coefficients; source spectra are good to " +
            "±factor, the dose is order-of-magnitude grade.",
        },
        {
          title: "Spent-fuel neutrons — spontaneous fission only (a LOWER BOUND)",
          body:
            "Spent fuel DOES light the neutron view: a multi-parent spontaneous-fission source " +
            "S(t)=Σ yield_n·A_n(t) off the one decay solve, with per-nuclide yields = (SF rate " +
            "from the SCK-CEN library)·(prompt ν̄). The ν̄ come from the IAEA safeguards table for " +
            "the dominant emitters (Cm-242 short cooling, Cm-244 through ~1 century), plus Cm-246/248 " +
            "for multi-century-and-beyond cooling (derived from the Holden & Zucker BNL-36467 " +
            "distributions); folded against the validated Cf-252 SF spectrum. BUT (α,n) on the fuel's " +
            "oxygen is NOT in the dataset and is unmodeled (typically tens-of-% of the source), so " +
            "the neutron dose is a lower bound — it UNDER-counts, the dangerous direction. Any " +
            "residual SF rate from minor emitters still lacking an evaluated ν̄ (<0.1% out to 1 Myr " +
            "for the shipped vectors) is shown on the neutron card, never silently.",
        },
        {
          title: "Neutron shielding — hydrogenous removal cross-section (energy-lumped)",
          body:
            "The shield now attenuates the neutron dose: T = exp(−Σ_R·x), the fast-neutron " +
            "effective REMOVAL cross-section Σ_R (NCRP-20 measured H/C/O mass values via the " +
            "mixture rule). It is a single energy-independent scalar, not per-line — there is no " +
            "buildup factor (Σ_R is already dose-calibrated against fission-spectrum measurements) " +
            "and NO spectrum hardening is modeled (h̄ is unchanged by the shield). Σ_R is only valid " +
            "where HYDROGEN is present to thermalize the removed neutrons, so only hydrogenous " +
            "shields (water, polyethylene, PMMA) carry removal data; a γ-oriented high-Z shield " +
            "(lead, iron) is neutron-transparent and the neutron card says so — never a silently-low " +
            "number (the safe, over-count direction; the §6.3 “steer neutrons to hydrogen” point). " +
            "It is calibrated to a FISSION spectrum, so a harder source (AmBe) is less accurate; the " +
            "layer order in a mixed stack is not modeled; and for THICK shields removal UNDER-counts " +
            "the dose (deep-penetration intermediate-neutron buildup) — the dangerous direction, " +
            "opposite to the lead case.",
        },
      ],
    },
    {
      heading: "Data provenance & trust levels",
      items: [
        {
          title: "Emission spectra — ICRP-107 (clean, validated)",
          body:
            "Photon lines + yields and beta endpoints/means are bundled from ICRP-107 RAD data " +
            "(1252 nuclides), validated by a four-pillar regression suite. This is also the " +
            "dataset behind the decay topology, so chain and source terms stay consistent.",
        },
        {
          title: "H*(10) coefficients — DEGRADED TRUST (transcribed from an unmerged PR)",
          body:
            "The photon H*(10) fluence-to-dose table (ICRP-74 / ICRU-57 vintage) is transcribed " +
            "from an UNMERGED OpenMC pull request (#3256) — OpenMC mainline has no H*(10) table " +
            "yet. Its faithfulness is cross-checked independently (the derived H*(10)/Ka " +
            "reproduces the ICRU-57 sphere response and matches an IAEA slab table at low- and " +
            "MeV-energies), but the 50–200 keV interior and the >3 MeV tail rest on that " +
            "transcription. Decay gammas essentially never exceed ~2.6 MeV, inside the validated " +
            "range. Flagged, not silently shipped as exact.",
        },
        {
          title: "Effective-dose coefficients — ICRP-116 (clean, verbatim)",
          body:
            "The effective-dose table (ICRP-116, incl. corrigendum) re-parses byte-identically " +
            "from OpenMC mainline and matches a separate group's independent piecewise-poly fit " +
            "to ≤1.2%. Clean provenance — distinct from the degraded H*(10) above.",
        },
      ],
    },
    {
      heading: "Spent fuel & decay heat (M7c)",
      items: [
        {
          title: "Spent-fuel discharge vectors — SCK-CEN Serpent2 (CC-BY), per tonne HM",
          body:
            "The prebuilt spent-fuel sources are real PWR discharge inventories from the SCK-CEN " +
            "Serpent2 library (Mendeley DOI 10.17632/shv89y2zzd, CC BY 4.0), shipped at chosen " +
            "burnup/enrichment grid points (45 and 20 GWd/tHM at 4.0%), normalised to one tonne " +
            "initial heavy metal. Activity is derived as λN from the dataset's mass-density " +
            "(atom-inventory) columns — validated independently: the Cs-137 discharge activity " +
            "matches a first-principles fission-yield estimate to ~5%, and the inferred fuel HM " +
            "density (8.88 g/cm³) matches U-in-UO₂. Loaded at discharge (t=0); the time control " +
            "IS the cooling-time axis (forward decay).",
        },
        {
          title: "Decay heat = recoverable energy (neutrino-excluded)",
          body:
            "Decay heat W(t) = Σ A_n·Ē_rec,n is folded from the SAME ICRP-107 emission spectra as " +
            "the γ/β dose (no separate dataset): mean β kinetic energy (antineutrino energy " +
            "excluded — why decay heat ≠ Q-value), all photons, IC/Auger electrons, and α particle " +
            "+ recoil-nucleus energy (Q_α = E_α·A/(A−4)). Spontaneous-fission/fragment energy is " +
            "not included (negligible except SF sources, which are α-dominated anyway).",
        },
        {
          title: "Short-cooling underestimate — valid for months+ of cooling",
          body:
            "The discharge vector tracks ~150 nuclides and OMITS sub-hour fission products, so " +
            "spent-fuel decay heat and γ dose UNDERESTIMATE the first ~day after discharge (the " +
            "prompt, very-short-lived component is missing). The model is intended for the cooling " +
            "regime — months to millennia — where Cs-137/Sr-90 (+ daughters) set the plateau; the " +
            "shipped grid points are validated against published decay heat at 10 and 100 years.",
        },
      ],
    },
    {
      heading: "Prebuilt source catalog (M7)",
      items: [
        {
          title: "Weapons-grade Pu pit — α/γ only; SF neutrons NOT modelled",
          body:
            "The pit is an illustrative weapons-grade Pu inventory (~93.5% Pu-239 / 6% Pu-240 / " +
            "0.5% Pu-241; quantities representative, editable). Its real external field also " +
            "includes ~1000 n/s/g of Pu-240 SPONTANEOUS-FISSION neutrons, which v1 does NOT model " +
            "— so the shown external dose is an UNDERESTIMATE for this source. The in-growing " +
            "Am-241 (59.5 keV γ) from Pu-241 decay IS modelled (the real external-γ story). The " +
            "teaching point stands: α reads ~nothing externally yet is deadly if inhaled.",
        },
        {
          title: "Am-241/Be — ISO 8529 spectrum (cited); yield is construction-dependent",
          body:
            "The AmBe neutron spectrum is the ISO 8529 reference, taken from IAEA TRS-403 (2001) " +
            "Table 4.V — a cited open-access table, not a reconstruction. Folded against ICRP-74 " +
            "it gives H*(10) = 393.6 pSv·cm², matching the standard's published 391 to <1%. The " +
            "4.438 MeV reaction γ (⁹Be(α,n)¹²C*) is modelled at the recommended γ/n ratio R=0.575 " +
            "and stacks into the Sv total. The absolute neutron YIELD (2.2×10⁶ n/s per Ci) is " +
            "source-construction-dependent (Am:Be ratio, encapsulation) and varies ≈±15% — a " +
            "representative value; the spectrum shape and dose coefficient are construction-independent.",
        },
        {
          title: "Bomb fallout (7:10 rule) — ENDF yields, illustrative mix",
          body:
            "The fresh fission-product fallout source is built from ENDF/B-VIII.0 U-235 thermal " +
            "CUMULATIVE fission yields (a cited table, not a memory reconstruction); decayed " +
            "forward it reproduces the Way–Wigner t⁻¹·² (7:10) gross-γ decay law (regression-" +
            "tested). Caveats: (1) cumulative-yield seeding ≈ the H+1 h chain-fed inventory and " +
            "double-counts within decay chains — a shape-preserving approximation, so the DECAY " +
            "is meaningful but the absolute level AND the relative composition (per-line/DAG — " +
            "equilibrium daughters such as La-140/Y-90 are over-weighted) are approximate, and " +
            "t < H+1 h is unreliable; " +
            "(2) it uses thermal U-235 yields, whereas a real weapon is FAST U/Pu fission — the " +
            "dominant γ emitters and the 7:10 law are broadly common, so this is a representative " +
            "illustrative mix, not a weapon-specific vector; (3) scaled to a default 1 kt " +
            "(~1.45×10²³ fissions), editable.",
        },
      ],
    },
    {
      heading: "Quantities are not interchangeable",
      items: [
        {
          title: "H*(10) vs effective dose — different quantities AND vintages",
          body:
            "H*(10) (ambient dose equivalent, the survey-meter reading, ICRP-74/ICRU-57, no " +
            "geometry) and effective dose E (ICRP-116, per body orientation AP/PA/…) are computed " +
            "differently and are NOT directly comparable. Selecting effective dose forces a " +
            "geometry assumption (default AP — a person facing the source). The neutron tables " +
            "mirror this split (H*(10) = ICRP-74, effective = ICRP-116), also non-comparable.",
        },
        {
          title: "Multi-layer shields — last-layer buildup, the least-reliable element",
          body:
            "A layer stack's attenuation exp(−Σμᵢxᵢ) is EXACT and order-independent, but its " +
            "buildup has no clean theory. We use the LAST-LAYER approximation: the buildup of the " +
            "detector-side material over the whole penetration depth (§6.4). It is order-dependent " +
            "and errs BOTH ways — a high-buildup low-Z layer on the detector side over-estimates; " +
            "a high-Z layer there under-counts (the dangerous direction). This is the least-reliable " +
            "part of the γ dose calc; the “layer-order sensitivity” readout quantifies it for a " +
            "mixed stack. Broder / Harima–Kitazume (order-aware) are a future upgrade — not " +
            "reconstructed from memory (no-fabrication, §11). Single-layer is exact for buildup.",
        },
      ],
    },
  ];
</script>

<section class="honesty" data-testid="honesty-register">
  <p class="disclaimer" data-testid="honesty-disclaimer" role="note">
    ⚠ <strong>Educational / reference tool — not for real radiation-safety decisions.</strong>
    Accuracy is near-quantitative to a documented precision (see below); real work needs
    validated codes (MCNP, ORIGEN, VARSKIN) and a qualified health physicist. The first load
    is heavy (the WASM scientific stack) — that is expected, not a bug.
  </p>

  <details class="register">
    <summary>Accuracy &amp; limitations — the honesty register (HANDOFF_PLAN §11)</summary>
    <p class="lead muted">
      What this tool does well, and where it is approximate. Per-number caveats also appear
      inline next to the values they qualify; this is the consolidated view.
    </p>
    {#each GROUPS as g (g.heading)}
      <h3>{g.heading}</h3>
      <dl>
        {#each g.items as item (item.title)}
          <dt>{item.title}</dt>
          <dd>{item.body}</dd>
        {/each}
      </dl>
    {/each}
  </details>
</section>

<style>
  .honesty {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  .disclaimer {
    margin: 0;
    padding: 0.6rem 0.8rem;
    background: #fff3cd;
    color: #664d03;
    border-radius: 0.4rem;
    font-size: 0.92rem;
    line-height: 1.5;
  }
  .register {
    margin-top: 0.75rem;
    font-size: 0.88rem;
  }
  .register summary {
    cursor: pointer;
    font-weight: 600;
    font-size: 1rem;
  }
  .lead {
    margin: 0.6rem 0 0.2rem;
  }
  h3 {
    font-size: 0.95rem;
    margin: 1rem 0 0.3rem;
  }
  dl {
    margin: 0;
  }
  dt {
    font-weight: 600;
    margin-top: 0.6rem;
  }
  dd {
    margin: 0.15rem 0 0;
    opacity: 0.85;
    line-height: 1.5;
  }
  .muted {
    opacity: 0.7;
  }
</style>
