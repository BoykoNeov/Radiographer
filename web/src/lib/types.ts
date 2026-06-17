// Shared UI-layer types for the inventory model (M6b). Kept separate from both the
// bridge contract (bridge.ts) and the store so persist.ts and the components can
// import them without pulling in Svelte runes or the live store singleton.

export type Precision = "double" | "hp";

/** One user-loaded isotope line: name + quantity in a chosen input unit. */
export interface InventoryEntry {
  /** A nuclide ID the engine can solve, e.g. "Co-60" (validated against bridge.nuclides()). */
  name: string;
  /** The amount, in `unit`. Always a number (the serializer must preserve this — not a string). */
  quantity: number;
  /** Input unit for `quantity` — an rd input unit value (see UNIT_OPTIONS). */
  unit: string;
}

/** Unit choices for the add row, grouped by quantity kind (§9 atoms/mass/activity). */
export const UNIT_OPTIONS: ReadonlyArray<{ value: string; label: string; kind: string }> = [
  { value: "Bq", label: "Bq", kind: "activity" },
  { value: "Ci", label: "Ci", kind: "activity" },
  { value: "g", label: "g", kind: "mass" },
  { value: "kg", label: "kg", kind: "mass" },
  { value: "mg", label: "mg", kind: "mass" },
  { value: "ug", label: "µg", kind: "mass" },
  { value: "atoms", label: "atoms", kind: "count" },
];

export const DEFAULT_UNIT = "Bq";

// --- curve axis (M6c, §9 "Atoms · Mass · Activity" toggle) -------------------

/** The quantity axis for the overlay curves (and the dose breakdown later). */
export type Axis = "atoms" | "mass" | "activity";

/** Segmented-toggle options, in display order; default is Activity (§9). */
export const AXIS_OPTIONS: ReadonlyArray<{ value: Axis; label: string }> = [
  { value: "atoms", label: "Atoms" },
  { value: "mass", label: "Mass" },
  { value: "activity", label: "Activity" },
];

/** Secondary unit choices per axis (the `unit` arg to engine `evaluate`). */
export const ACTIVITY_UNITS = ["Bq", "Ci"] as const;
export const MASS_UNITS = ["g", "kg", "mg"] as const;
/** Atoms has a single unit; kept as a constant so labels stay obsessive (§12). */
export const ATOMS_UNIT = "atoms";

// --- time units (M6d, §9 time control) ---------------------------------------
// The engine speaks SI seconds everywhere (solve metadata `time_range_s`,
// `half_lives_s`, `evaluate(times_s)`); these are the human-facing units for the
// numeric time entry, the source-age input, and the half-life tick labels.

export interface TimeUnit {
  value: string;
  label: string;
  /** SI seconds per one of this unit. */
  seconds: number;
}

/** Year = Julian year (365.25 d = 31_557_600 s) — radioactivedecay's convention. */
export const TIME_UNITS: ReadonlyArray<TimeUnit> = [
  { value: "s", label: "s", seconds: 1 },
  { value: "min", label: "min", seconds: 60 },
  { value: "h", label: "h", seconds: 3600 },
  { value: "d", label: "d", seconds: 86400 },
  { value: "y", label: "yr", seconds: 31_557_600 },
];

export const DEFAULT_TIME_UNIT = "s";

/** Convert `(value, unit)` to SI seconds. Loud on an unknown unit (no silent 0). */
export function toSeconds(value: number, unit: string): number {
  const u = TIME_UNITS.find((t) => t.value === unit);
  if (!u) throw new Error(`unknown time unit ${JSON.stringify(unit)}`);
  return value * u.seconds;
}

// --- dose calculator (M6f, §9 dose calculator) -------------------------------
// Two SELECTABLE dose quantities, both in Sv but NOT inter-comparable (§6.4): the
// operational H*(10) (no geometry) and effective dose E (per ICRP-116 geometry).
// Beta is a THIRD quantity entirely — Hp(0.07) skin dose in Gy — handled on the
// engine side (`beta_dose`) and labelled separately; it is never one of these and
// is never summed into an H*(10)/effective total (§6.2 LOCKED; see M6f-dose.md #1).

/** The γ/n dose quantity (the bridge `quantity` string). Both render in Sv. */
export type DoseQuantity = "ambient_H10" | "effective";

export const DOSE_QUANTITY_OPTIONS: ReadonlyArray<{ value: DoseQuantity; label: string }> = [
  { value: "ambient_H10", label: "H*(10)" },
  { value: "effective", label: "Effective" },
];

/** The six ICRP-116 irradiation geometries (shown only when quantity = effective). */
export const GEOMETRY_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "AP", label: "AP (front)" },
  { value: "PA", label: "PA (back)" },
  { value: "ISO", label: "ISO (isotropic)" },
  { value: "LLAT", label: "LLAT (left side)" },
  { value: "RLAT", label: "RLAT (right side)" },
  { value: "ROT", label: "ROT (rotational)" },
];

/** §13 #3 RESOLVED → AP: a point source at distance ⇒ a person facing it (and the
 *  conservative, highest-E ICRP-116 geometry). See HANDOFF_PLAN §13, M6f-dose.md #4. */
export const DEFAULT_GEOMETRY = "AP";

/** Human label for the γ/n quantity (for axis/readout labels, §12). γ/n render in
 *  Sv; β skin dose is a separate Gy / Hp(0.07) quantity (never one of these). */
export function doseQuantityLabel(quantity: DoseQuantity, geometry: string): string {
  return quantity === "effective" ? `effective dose, ${geometry}` : "H*(10)";
}

/** Per-MODALITY colors for the γ/β/n breakdown bar (M6f-dose.md #5 — NOT the
 *  per-species palette, which lives in the per-line gamma table, M6f-2). */
export const MODALITY_COLORS = {
  gamma: "#4e79a7", // blue
  beta: "#f28e2b", // orange
  neutron: "#59a14f", // green (grayed out for user inventories until M7)
} as const;

/**
 * Per-modality EPISTEMIC uncertainty registers (HANDOFF_PLAN §9/§11), made visible as
 * fill bands on the dose-vs-distance curve and error whiskers on the grouped-log bar
 * (M6f-2). These are NOT computed error propagation — they are the documented accuracy
 * limits of each model: γ ≈ ±10–15 % in the buildup regime, β ≈ ±20–30 % (and published
 * skin-dose values themselves disagree ~50 %), neutron source terms ≈ order-of-magnitude
 * (tabulated). The whisker uses the CONSERVATIVE upper bound (`hi`) — understating
 * uncertainty is the wrong direction for a safety-adjacent tool — while the caption shows
 * the full range. "The tight-γ-vs-fat-n contrast is the point" (§9); n lands with the
 * prebuilt sources (M7). */
export const MODALITY_UNCERTAINTY: Record<"gamma" | "beta" | "neutron", { lo: number; hi: number; label: string }> = {
  gamma: { lo: 0.1, hi: 0.15, label: "±10–15%" },
  beta: { lo: 0.2, hi: 0.3, label: "±20–30%" },
  neutron: { lo: 2.0, hi: 2.0, label: "order-of-magnitude" }, // ×/÷ a few — M7
};

/**
 * Format SI seconds as a short human string, auto-picking the largest unit whose
 * value is ≥ 1 (e.g. 86400 → "1 d", 153 → "2.55 min"). For tick/readout labels;
 * not round-trip-exact (display only). 0/negative render as "0 s".
 */
export function humanTime(seconds: number): string {
  if (!(seconds > 0)) return "0 s";
  for (let i = TIME_UNITS.length - 1; i >= 0; i--) {
    const u = TIME_UNITS[i];
    if (seconds >= u.seconds) {
      const v = seconds / u.seconds;
      const s = v >= 100 ? v.toPrecision(3) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
      return `${s} ${u.label}`;
    }
  }
  return `${seconds.toExponential(2)} s`;
}
