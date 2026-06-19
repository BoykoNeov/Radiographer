// The prebuilt source catalog (M7 / HANDOFF_PLAN §8) — a curated list of named
// sources a user loads with one click. Each is a *named inventory* (name+quantity+unit)
// + a one-line "what it teaches" blurb + an optional tabulated neutron source key.
//
// THIS IS A UI MANIFEST, NOT A PHYSICS DATASET. The inventory quantities below are
// representative teaching defaults (editable after load), cited in comments but NOT
// regression-grade; the real physics data (emission spectra, neutron terms, and — when
// they land — spent-fuel discharge vectors) lives in validated `data/` files under §7.
// So nothing here fabricates physics: a preset only *selects* nuclides + amounts the
// engine already solves from its bundled ICRP-107 data.
//
// Sequenced by sourcing risk (M7-sources.md "risk split"): the entries here are all
// trivial inventories (no new data). The sourcing-GATED sources — spent fuel (§13 #4),
// bomb fallout (§13 #5), AmBe — are intentionally ABSENT until citable data is in hand;
// they are NOT reconstructed from memory (the §11 AmBe / Cross-Berger discipline).

import type { InventoryEntry } from "./types";

export interface PrebuiltSource {
  /** Stable key (used as the picker option value + the persist round-trip id). */
  id: string;
  /** Display name in the picker. */
  label: string;
  /** Grouping header in the picker. */
  category: string;
  /** The §8 "what it teaches" one-liner — the teaching hook. */
  blurb: string;
  /** The named inventory: each entry is a nuclide the engine solves + amount + unit. */
  entries: InventoryEntry[];
  /** Default reference time / source-age (s) — 0 (fresh) for every v1 preset; the
   *  spent-fuel cooling time (a non-zero default) lands with M7c. */
  referenceTimeS?: number;
  /** Prebuilt neutron source key (`data/neutron_sources/<key>.json`) — present ONLY for
   *  neutron sources; its presence is the §6.3 gray-out gate that lights the neutron
   *  dose path (M7b). Absent ⇒ neutron stays grayed (a user-style inventory). */
  neutronSource?: string;
  /** Spent-fuel SF neutron source id (`data/spent_fuel/<id>.json`) — present ONLY for spent-fuel
   *  vectors that carry a `neutron` block (M9). The MULTI-parent neutron path: unlike
   *  `neutronSource` (one tabulated key), the source strength is intrinsic to the loaded
   *  inventory (S(t)=Σ yield_n·A_n(t)). Mutually exclusive with `neutronSource`. */
  spentFuelNeutronId?: string;
  /** Optional extra teaching caveat surfaced beside the blurb (honesty, §11). */
  caveat?: string;
}

// Activity unit note (§12): the engine input units are Bq / Ci / g / kg / mg / ug /
// atoms (see UNIT_OPTIONS). Quantities below pick whichever reads most naturally for
// the source; all are converted to atoms internally by the solve.

export const PREBUILT_SOURCES: PrebuiltSource[] = [
  // --- Reference / calibration γ -------------------------------------------
  {
    id: "co60-source",
    label: "Co-60 source",
    category: "Reference / calibration",
    blurb:
      "Strong dual γ (1.173 + 1.333 MeV) — the gamma-dose reference case. " +
      "Benchmark: ~1 Ci at 1 m ≈ 1.3 R/h.",
    // 1 Ci (37 GBq) — a legible teaching anchor tied to the dose-rate rule of thumb.
    entries: [{ name: "Co-60", quantity: 1, unit: "Ci" }],
  },
  {
    id: "cs137-source",
    label: "Cs-137 source",
    category: "Reference / calibration",
    blurb:
      "Cs-137 → Ba-137m SECULAR equilibrium; the classic 0.662 MeV line. " +
      "Scrub time to watch the daughter track the parent.",
    // 1 Ci (37 GBq). Ba-137m (t½ 2.55 min) reaches secular equilibrium with Cs-137 (30 y).
    entries: [{ name: "Cs-137", quantity: 1, unit: "Ci" }],
  },

  // --- Generators / teaching demos -----------------------------------------
  {
    id: "mo99-tc99m-generator",
    label: "Mo-99 / Tc-99m generator",
    category: "Generators / teaching",
    blurb:
      "Mo-99 → Tc-99m TRANSIENT equilibrium (the medical 'moly cow'). " +
      "Tc-99m grows in, peaks, then follows the 66 h parent.",
    // 1 Ci (37 GBq) Mo-99 — a clinical generator scale; Tc-99m (6 h) is the in-grown daughter.
    entries: [{ name: "Mo-99", quantity: 1, unit: "Ci" }],
  },

  // --- Everyday sources -----------------------------------------------------
  {
    id: "k40-banana",
    label: "K-40 banana",
    category: "Everyday",
    blurb:
      "The 'banana equivalent dose' scale anchor — one banana ≈ 15 Bq of K-40. " +
      "Negligible EXTERNAL dose; a unit for intuition, not a hazard.",
    // ~15 Bq K-40 per banana (0.45 g K × 0.0117 % K-40 × λ). The teaching point is the
    // tiny external dose — exactly what the dose panel should show.
    entries: [{ name: "K-40", quantity: 15, unit: "Bq" }],
  },
  {
    id: "am241-smoke-detector",
    label: "Am-241 smoke detector",
    category: "Everyday",
    blurb:
      "α + 59.5 keV γ — the everyday α source. α reads ~nothing on a survey meter " +
      "(external) yet is dangerous if inhaled (external ≠ internal hazard, §12).",
    // ~0.3 µg Am-241 (≈ 37 kBq / 1 µCi) — a household ionization-detector source.
    entries: [{ name: "Am-241", quantity: 0.3, unit: "ug" }],
  },
  {
    id: "radium-dial",
    label: "Radium dial",
    category: "Everyday",
    blurb:
      "Ra-226 luminous paint — introduces the gaseous Rn-222 daughter and its in-growing " +
      "chain. Watch the lower U-series build in after loading.",
    // ~1 µg Ra-226 (≈ 1 µCi) — an old luminous watch/instrument dial.
    entries: [{ name: "Ra-226", quantity: 1, unit: "ug" }],
    caveat:
      "Models a CLOSED system: Rn-222 is retained. Real dials leak radon, so the in-grown " +
      "daughters (and their dose) are an upper bound.",
  },

  // --- Reactor fuel ---------------------------------------------------------
  {
    id: "fresh-fuel",
    label: "Fresh reactor fuel (LEU)",
    category: "Reactor fuel",
    blurb:
      "Unirradiated ~4 % enriched UO₂ — mostly U-238/U-235 α with weak γ; surprisingly " +
      "benign externally. The teaching contrast to (future) spent fuel.",
    // 1 kg U at 4 % enrichment: 40 g U-235 + 960 g U-238 (a fuel-pellet-scale basis).
    entries: [
      { name: "U-235", quantity: 40, unit: "g" },
      { name: "U-238", quantity: 960, unit: "g" },
    ],
  },

  // --- Weapons material -----------------------------------------------------
  {
    id: "pu-pit",
    label: "Weapons-grade Pu pit",
    category: "Weapons material",
    blurb:
      "Weapons-grade plutonium — an α emitter that reads almost NOTHING on an external " +
      "survey meter yet is deadly if inhaled (external ≠ internal, §12). Scrub time " +
      "forward to watch the Am-241 (59.5 keV γ) daughter grow in from Pu-241 decay.",
    // ~4 kg weapons-grade Pu (one pit-scale mass), illustrative teaching composition:
    // ~93.5 % Pu-239 / 6 % Pu-240 / 0.5 % Pu-241 by mass (IAEA "weapons-grade" = <7 %
    // Pu-240). Trace Pu-238/Pu-242 (<0.05 %) omitted — negligible to the external field.
    // These are representative quantities (editable after load), NOT regression-grade data.
    entries: [
      { name: "Pu-239", quantity: 3740, unit: "g" },
      { name: "Pu-240", quantity: 240, unit: "g" },
      { name: "Pu-241", quantity: 20, unit: "g" },
    ],
    // Freshly cast/separated pit (t=0): no Am-241 yet, so its in-growth is visible on the
    // timeline. Am-241 (t½ 432 y, in-grows from Pu-241 t½ 14.3 y) is the real external-γ story.
    referenceTimeS: 0,
    caveat:
      "External dose shown is α + γ (incl. in-growing Am-241). A real Pu pit ALSO emits " +
      "~1000 n/s/g of Pu-240 spontaneous-fission neutrons — that neutron dose is NOT modeled " +
      "here (v1), so the external total is an UNDERESTIMATE for this source (§11).",
  },

  // --- Neutron sources ------------------------------------------------------
  {
    id: "cf252-source",
    label: "Cf-252 neutron source",
    category: "Neutron",
    blurb:
      "Spontaneous-fission neutron source (+ its own decay γ). The neutron dose path " +
      "lights up here; ~1 µg ≈ 2.3×10⁶ n/s ≈ 2.5 mrem/h at 1 m.",
    // 1 µg Cf-252 (≈ 0.54 µCi; 2.3×10⁶ n/s). The neutron term + spectrum are the VALIDATED
    // data/neutron_sources/Cf-252.json (M5); `neutronSource` lights the §6.3 neutron path.
    entries: [{ name: "Cf-252", quantity: 1, unit: "ug" }],
    neutronSource: "Cf-252",
  },
  {
    id: "ambe-source",
    label: "Am-241/Be neutron source",
    category: "Neutron",
    blurb:
      "The standard lab (α,n) calibration source: Am-241 α on ⁹Be → neutrons (0.1–10 MeV) " +
      "PLUS a clean 4.438 MeV reaction γ. ~1 Ci ≈ 2.2×10⁶ n/s; watch the γ-source segment " +
      "stack into the Sv total alongside the neutrons.",
    // 1 Ci (37 GBq) Am-241 ≈ 2.2×10⁶ n/s (the canonical AmBe specific emission). The neutron
    // spectrum (ISO 8529 / IAEA TRS-403) + the 4.438 MeV γ are the VALIDATED data/neutron_sources/
    // AmBe.json; `neutronSource` lights the §6.3 neutron path (h̄ = 393.6 pSv·cm² ≈ ISO 391).
    entries: [{ name: "Am-241", quantity: 1, unit: "Ci" }],
    neutronSource: "AmBe",
    caveat:
      "Neutron YIELD is source-construction-dependent (Am:Be ratio, encapsulation) and varies " +
      "≈±15% — a representative value; the spectrum shape and dose coefficient are the " +
      "construction-independent ISO-standard part (§11).",
  },
];

/** Picker grouping: category → its sources, in manifest order. */
export function sourcesByCategory(): { category: string; sources: PrebuiltSource[] }[] {
  const groups: { category: string; sources: PrebuiltSource[] }[] = [];
  for (const s of PREBUILT_SOURCES) {
    let g = groups.find((x) => x.category === s.category);
    if (!g) {
      g = { category: s.category, sources: [] };
      groups.push(g);
    }
    g.sources.push(s);
  }
  return groups;
}

/** Look up a source by id (for the persist round-trip / programmatic load). */
export function findSource(id: string): PrebuiltSource | undefined {
  return PREBUILT_SOURCES.find((s) => s.id === id);
}
