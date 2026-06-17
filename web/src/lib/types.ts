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
