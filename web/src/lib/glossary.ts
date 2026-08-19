// Shared glossary — the single source of truth for the pedagogy layer (docs/plans/
// pedagogy-layer.md). Keyed `term → { term, novice, advanced? }`; <Term> renders an
// inline, keyboard-accessible popover from an entry and <LearnMore> may quote them.
//
// CONTENT CORRECTNESS IS PHYSICS CORRECTNESS (§11 "no wrong-but-quiet", §12 units).
// Every `novice` line is a physics claim a novice must be able to trust, and every
// `advanced` aside is checked against the language already in Honesty.svelte and
// HANDOFF_PLAN §11/§12 — NOT reconstructed from memory. The distinctions the app is
// obsessive about MUST survive simplification, in particular:
//   - absorbed dose (Gy) ≠ dose equivalent / effective dose (Sv) — never interchangeable,
//     never summed (§6.2);
//   - H*(10) (no geometry, ICRP-74 vintage) ≠ effective dose (per-geometry, ICRP-116) —
//     both in Sv, but not comparable;
//   - Hp(0.07) β skin dose (Gy, w_R=1) is a THIRD quantity, on its own axis, never added
//     into a γ total.
// No entry introduces a number or citation not already present in Honesty.svelte /
// HANDOFF_PLAN (§11 no-fabrication). Standards named in asides (ICRP-74/116, ANS-6.4.3,
// ICRU-57) are the ones the engine already uses.

/** One glossary entry: a plain-language baseline plus an optional deeper aside. */
export interface GlossaryEntry {
  /** Canonical display name — used as the trigger text when <Term> has no child. */
  term: string;
  /** Plain-language definition everyone can follow (the novice baseline; always shown). */
  novice: string;
  /** Optional deeper note — equations / standards refs — shown as a secondary block. */
  advanced?: string;
}

// Grown per pass (never pre-populated): ONLY the terms the wired panels actually surface,
// and only those where a novice genuinely won't know the word AND there is a correctness
// distinction worth an advanced aside (the quantity family, the core decay terms, the — as
// of Pass 2 — shielding + neutron-source vocabulary of the Shield and Sources panels, and —
// as of Pass 3 — the intake / committed-dose vocabulary of the Internal-dose panel).
// App mechanics (display floor, decades, the Bateman solve, the N–Z chart) are left to
// prose / <LearnMore> — they are not glossary Terms; `source-age` is the one deliberate
// exception, a UI-mechanics word a novice meets head-on in the Sources intro.
export const GLOSSARY = {
  // -- decay basics (Curves + Chain) ------------------------------------------
  activity: {
    term: "activity",
    novice:
      "How much a sample is decaying right now: the number of atomic nuclei that break " +
      "apart each second. It is measured in becquerels (Bq) — 1 Bq is one decay per " +
      "second. The older unit is the curie (Ci); 1 Ci = 3.7×10¹⁰ Bq (originally the " +
      "activity of about one gram of radium). Activity is not the same as dose — a very " +
      "active source can still be harmless behind shielding or at a distance.",
    advanced:
      "Activity A = λN: the decay constant λ = ln 2 / t½ times the number of atoms N " +
      "present. It says nothing on its own about the type or energy of the radiation " +
      "emitted — that is what the dose calculation adds on top.",
  },
  "half-life": {
    term: "half-life",
    novice:
      "The time it takes for half of the atoms of a nuclide to decay. After one half-life " +
      "half remain, after two a quarter, and so on. A short half-life means the sample is " +
      "very active but fades quickly; a long half-life means it lasts but is less active " +
      "gram-for-gram.",
    advanced:
      "Decay is exponential: N(t) = N₀·e^(−λt) with λ = ln 2 / t½. Across the bundled " +
      "dataset half-lives span from fractions of a second to billions of years — which is " +
      "why the time axis here is logarithmic.",
  },
  "secular-equilibrium": {
    term: "secular equilibrium",
    novice:
      "When a long-lived parent feeds a much shorter-lived daughter, the daughter builds " +
      "up until it decays as fast as it is produced. From then on their activities rise " +
      "and fall together and the daughter appears 'locked' to the parent. Cs-137 and its " +
      "daughter Ba-137m are the classic example.",
    advanced:
      "Reached when the parent half-life ≫ the daughter's: the daughter activity settles " +
      "at the parent activity times the branching fraction to that daughter. For " +
      "Cs-137 → Ba-137m that ratio is ≈0.944 (the branch to the metastable state) — the " +
      "value the curves and chain views reproduce, and a physics anchor for the gate.",
  },
  "branching-ratio": {
    term: "branching ratio",
    novice:
      "Many nuclei can decay in more than one way, or to more than one product. The " +
      "branching ratio is the percentage of decays that take each path. The arrows in the " +
      "decay chain are labelled with these percentages.",
    advanced:
      "Branching fractions per decay mode come from the ICRP-107 decay data and sum to " +
      "100% over a parent's modes. They scale each daughter's in-growth — a one-third " +
      "branch feeds its daughter at one-third of the parent's decay rate.",
  },
  "decay-mode": {
    term: "decay mode",
    novice:
      "The kind of transformation a nucleus undergoes: alpha (α) emits a helium nucleus; " +
      "beta-minus (β⁻) converts a neutron into a proton and emits an electron; and others. " +
      "Each mode fixes what radiation comes out and which nuclide is produced next.",
    advanced:
      "Alpha emission lowers Z by 2 and A by 4; β⁻ raises Z by 1 at constant A (a diagonal " +
      "step on the N–Z chart); β⁺ / electron capture lower Z by 1. The chain's (N, Z) " +
      "layout draws each mode as a characteristic step, so two paths re-converging on a " +
      "shared daughter meet at a single coordinate.",
  },
  // -- dose quantities (Dose) — the quantity family, where the split earns its keep ---
  "absorbed-dose": {
    term: "absorbed dose",
    novice:
      "The amount of radiation energy actually deposited in a material or tissue, per " +
      "kilogram. Its unit is the gray (Gy): 1 Gy = 1 joule per kilogram. It measures the " +
      "energy delivered — not yet how biologically harmful that energy is.",
    advanced:
      "The tool reports the β skin dose as absorbed dose in gray (Hp(0.07), w_R=1). " +
      "Absorbed dose is the physical starting point; the sievert quantities weight it for " +
      "biological effect. Gray and sievert are never interchangeable and are never summed.",
  },
  "dose-equivalent": {
    term: "H*(10)",
    novice:
      "A measure of external radiation exposure adjusted for how harmful the radiation is " +
      "to tissue, in sieverts (Sv). H*(10) — 'ambient dose equivalent' — is the quantity a " +
      "survey meter reads: defined at 10 mm depth, with no assumption about which way a " +
      "person is facing. It is what you compare against external-exposure limits.",
    advanced:
      "H*(10) (ICRP-74 / ICRU-57 vintage, no body geometry) is an operational quantity. " +
      "Its photon fluence-to-dose coefficients here are transcribed from an unmerged " +
      "OpenMC pull request and carry degraded trust above ~200 keV — see the honesty " +
      "register. It is not directly comparable to effective dose, even though both are in Sv.",
  },
  "effective-dose": {
    term: "effective dose",
    novice:
      "An estimate of the overall harm to the whole body from a radiation exposure, in " +
      "sieverts (Sv). Unlike H*(10), it depends on which way the body faces the source " +
      "(front, back, side…), so choosing it here asks you to pick a geometry.",
    advanced:
      "Effective dose E (ICRP-116) sums organ equivalent doses weighted by " +
      "tissue-sensitivity factors, for a defined irradiation geometry (default AP — facing " +
      "the source). It and H*(10) are different quantities of different vintage and are not " +
      "interchangeable, even though both are reported in sieverts.",
  },
  "hp007": {
    term: "Hp(0.07) skin dose",
    novice:
      "The radiation dose to the skin, measured at 0.07 mm depth — where the sensitive " +
      "basal skin layer sits. Beta particles stop in a thin surface layer, so this is the " +
      "right quantity for a beta (skin / contact) hazard. It is reported in gray and shown " +
      "on its own axis, never added to the gamma dose.",
    advanced:
      "Hp(0.07) (Gy at 7 mg/cm², w_R=1) comes from the Loevinger beta endpoint kernel — " +
      "not a full spectrum fold — and is a contact / near-contact quantity. It is a " +
      "different quantity from H*(10) / effective dose (different depth, geometry and " +
      "meaning), so it is never summed into a sievert total.",
  },
  // -- dose physics (Dose) ----------------------------------------------------
  buildup: {
    term: "buildup factor",
    novice:
      "When gamma rays pass through a shield, some scatter instead of being absorbed and " +
      "still reach the far side. The buildup factor accounts for this extra scattered " +
      "radiation, so a shield is never quite as effective as simple absorption alone " +
      "would predict.",
    advanced:
      "The dose uses the ANS-6.4.3 Geometric-Progression buildup factor, applying the " +
      "air-kerma buildup to all three quantities (air kerma, H*(10), effective) — a " +
      "documented approximation, since the buildup of dose-equivalent differs from that of " +
      "air kerma. For layered shields the last-layer approximation is the least-reliable " +
      "part of the γ calc (see the honesty register).",
  },
  "inverse-square": {
    term: "inverse-square law",
    novice:
      "For a small (point-like) source, radiation intensity falls off with the square of " +
      "the distance: double the distance and the dose rate drops to a quarter. Stepping " +
      "back is often the simplest way to cut exposure.",
    advanced:
      "The γ (and neutron) dose-vs-distance curves here are exact inverse-square: " +
      "rate(d) = rate(d₀)·(d₀/d)². Version 1 models no intervening-air attenuation, so the " +
      "falloff is purely geometric — good for penetrating photons, an over-estimate for " +
      "soft ones (a 10 keV dose-scoring floor stands in for the missing air path).",
  },
  // -- shielding (Shield; Pass 2) ---------------------------------------------
  attenuation: {
    term: "attenuation",
    novice:
      "As radiation passes through a shield, some of it is absorbed or scattered aside, so " +
      "less comes out the far side than went in. Thicker shields — and denser, higher-" +
      "atomic-number materials — remove more. For gamma rays the fraction getting through " +
      "falls off exponentially with thickness.",
    advanced:
      "Narrow-beam (point-kernel) transmission is exp(−Σ μᵢxᵢ): each layer's linear " +
      "attenuation coefficient μ times its thickness x, summed. It is exact and independent " +
      "of layer order — what depends on order is the buildup correction applied on top, " +
      "which accounts for scattered photons the narrow-beam term leaves out.",
  },
  "half-value-layer": {
    term: "half-value layer (HVL)",
    novice:
      "The thickness of a given material that cuts the radiation dose in half. Two half-" +
      "value layers cut it to a quarter, three to an eighth, and so on. A smaller HVL means " +
      "a more effective shield for that radiation — a handy way to compare materials.",
    advanced:
      "For a single photon energy the dose falls as (½)^(x/HVL), so HVL = ln 2 / μ. For a " +
      "real mixed-energy source it is NOT one constant: the beam 'hardens' as soft lines are " +
      "removed first, and scattered buildup adds dose back — which is why the dose-vs-" +
      "thickness curve here is not a straight line on a log axis. Read it as the actual " +
      "transmission, not a fixed HVL.",
  },
  "beam-hardening": {
    term: "beam hardening",
    novice:
      "A shield does not weaken every part of a mixed-energy beam equally: it removes the " +
      "low-energy photons far more effectively than the high-energy ones. So the radiation " +
      "that makes it through is more penetrating, on average, than the beam that went in — " +
      "the beam has been 'hardened'. A practical consequence: the second half-value layer of " +
      "shielding always removes less than the first one did.",
    advanced:
      "Because μ falls with energy across the diagnostic and gamma range, the transmitted " +
      "spectrum is weighted toward the high end: its mean energy and its half-value layer " +
      "both rise with thickness. That is why an 'attenuation factor' measured at one " +
      "thickness cannot be reused at another, and why the dose-vs-thickness curve here is " +
      "not a straight line on a log axis (buildup, which adds scattered photons back, bends " +
      "it the other way). For a single line there is nothing to harden — the effect exists " +
      "only for a spectrum.",
  },
  bremsstrahlung: {
    term: "bremsstrahlung",
    novice:
      "'Braking radiation': when fast beta electrons are stopped abruptly in matter, some of " +
      "their energy comes back out as penetrating X-rays. Dense, high-atomic-number " +
      "materials like lead produce far more of it — so a heavy shield can turn a stopped " +
      "beta into a new, more penetrating photon hazard. That is why adding lead in front of " +
      "a strong beta emitter can INCREASE the total (photon) dose.",
    advanced:
      "The radiated fraction rises with the absorber's atomic number Z and the beta endpoint " +
      "energy. This tool models the bremsstrahlung as leaving the (β-thin) shield " +
      "unattenuated and reports it as an order-of-magnitude γ (Sv) quantity, shown beside " +
      "the β skin dose (Gy) and never summed into it. It exists to teach the 'more lead can " +
      "increase dose' crossover, not for precise photon dose.",
  },
  "removal-cross-section": {
    term: "removal cross-section (Σ_R)",
    novice:
      "A shortcut for how well a hydrogen-rich shield (water, polyethylene) stops fast " +
      "neutrons. Neutrons are slowed best by light nuclei — above all hydrogen — so heavy " +
      "gamma shields like lead barely touch them. The fraction of fast neutrons getting " +
      "through a hydrogenous shield falls off exponentially with thickness.",
    advanced:
      "Fast-neutron transmission here is T = exp(−Σ_R·x), with Σ_R a single energy-" +
      "independent effective removal cross-section (measured mass values combined by the " +
      "mixture rule). It is only valid where hydrogen is present to thermalize the removed " +
      "neutrons, so only hydrogenous shields carry removal data and a high-Z γ shield is " +
      "treated as neutron-transparent. Calibrated to a fission spectrum; for thick shields " +
      "it under-counts the dose (deep-penetration buildup) — flagged in the honesty register.",
  },
  // -- neutron sources (Sources; Pass 2) --------------------------------------
  "spontaneous-fission": {
    term: "spontaneous fission",
    novice:
      "Some very heavy nuclei — californium-252, and the curium that builds up in cooled " +
      "spent fuel — occasionally split into two fragments entirely on their own, with " +
      "nothing hitting them. Each split throws off several fast neutrons, so these materials " +
      "are neutron sources even sitting alone in the dark.",
    advanced:
      "The neutron yield of a nuclide is its spontaneous-fission rate times the mean prompt " +
      "neutron multiplicity ν̄. Spontaneous fission is one of the two terms summed for a " +
      "spent-fuel or actinide neutron source (the other is the (α,n) reaction); the ν̄ " +
      "values come from evaluated safeguards / nuclear-data tables, cited in the honesty " +
      "register.",
  },
  "alpha-n": {
    term: "(α,n) reaction",
    novice:
      "A second way a source makes neutrons: alpha particles emitted by decaying atoms " +
      "(plutonium, americium, curium) strike light nuclei nearby — the oxygen in oxide fuel, " +
      "or the beryllium in an Am-Be source — and knock a neutron loose. No fission needed; " +
      "the alpha particle does it.",
    advanced:
      "In spent oxide fuel the (α,n)-on-oxygen term is summed with spontaneous fission for " +
      "the total neutron source, and its share grows over decades as Am-241 (a strong α " +
      "emitter with no spontaneous fission) ingrows. Thick-target (α,n) yields carry a " +
      "±factor uncertainty and a softer spectrum than fission — folded on the same dose " +
      "response and flagged in the honesty register.",
  },
  "source-age": {
    term: "source age",
    novice:
      "How old the source is at the moment you load it — the point on the decay timeline " +
      "where the loaded inventory 'starts'. A spent-fuel vector, for example, loads at " +
      "discharge (age zero) and the time slider then moves forward through cooling.",
    advanced:
      "Source age is an offset applied at evaluate time: the displayed activities, dose and " +
      "chain are the one Bateman solve read at (source age + cursor time). It is a display / " +
      "reference offset, not a re-solve — the 'solve once, evaluate many' contract.",
  },
  // -- internal / committed dose (Internal-dose panel; Pass 3) -----------------
  "committed-dose": {
    term: "committed dose E(50)",
    novice:
      "The dose your body would receive over the next 50 years from radioactive material " +
      "taken IN once — breathed in or swallowed — because it lodges inside and keeps " +
      "irradiating tissue long after the intake. It is reported in sieverts (Sv), like an " +
      "external effective dose, but it describes a different situation — a hypothetical " +
      "intake, not an external field — so the two are never added together into one total.",
    advanced:
      "Committed effective dose E(50) = Σ eₙ·Aₙ: each nuclide's intake activity times its " +
      "committed effective-dose coefficient eₙ (Sv/Bq), summed. It is a SCALAR in sieverts " +
      "(not a rate — the 50-year integration is already baked into the coefficient), so " +
      "there is no exposure window to accumulate. Although it is an effective-dose quantity " +
      "it is never summed with the external H*(10) / effective dose, which describe a " +
      "separate exposure scenario.",
  },
  "absorption-type": {
    term: "lung absorption type (F/M/S)",
    novice:
      "For something BREATHED IN, how quickly the compound dissolves out of the lungs into " +
      "the bloodstream: Type F (fast), M (moderate) or S (slow). A slower type keeps the " +
      "material in the lung longer, which usually means a higher dose. The tool folds one " +
      "default type per nuclide; a real intake depends on the exact chemical form.",
    advanced:
      "The absorption type sets the ICRP respiratory-tract clearance rate for an inhaled " +
      "aerosol; the alternative type can be materially higher or lower than the folded " +
      "default (the panel's honesty block lists the cases that bite). It applies to " +
      "inhalation only — ingestion uses the gut-transfer fraction f₁ instead.",
  },
  "gut-transfer": {
    term: "gut transfer factor (f₁)",
    novice:
      "For something SWALLOWED, the fraction of the element that is absorbed from the gut " +
      "into the bloodstream — the rest passes straight through and out. A larger f₁ means " +
      "more of an intake actually reaches the body's tissues. It depends on the element and " +
      "its chemical form.",
    advanced:
      "f₁ is the ICRP gastro-intestinal uptake fraction, used for the ingestion route " +
      "(inhalation uses the lung absorption type F/M/S instead). The panel shows the folded " +
      "f₁ per nuclide as provenance; a different chemical form can carry a different f₁.",
  },
} as const satisfies Record<string, GlossaryEntry>;

/** A valid glossary key — a branded-ish string so <Term term="…"> is checked, not free. */
export type GlossaryKey = keyof typeof GLOSSARY;
