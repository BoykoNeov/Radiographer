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

// The Pass-1 set: ONLY the terms the Curves, Chain, and Dose panels actually surface,
// and only those where a novice genuinely won't know the word AND there is a correctness
// distinction worth an advanced aside (the quantity family, plus the core decay terms).
// App mechanics (display floor, decades, the Bateman solve, the N–Z chart) are left to
// prose / <LearnMore> — they are not glossary Terms. Extend per pass, never pre-populate.
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
} as const satisfies Record<string, GlossaryEntry>;

/** A valid glossary key — a branded-ish string so <Term term="…"> is checked, not free. */
export type GlossaryKey = keyof typeof GLOSSARY;
