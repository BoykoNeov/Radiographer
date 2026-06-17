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
