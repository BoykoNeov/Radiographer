// Versioned save/load of app state (HANDOFF_PLAN §9; M6-ui M6b → M6h).
//
// M6b shipped v1: the INVENTORY slice only (entries + precision + t=0). M6h bumps to v2
// and adds the rest of the output/view-affecting state as ADDITIVE sibling sections —
// `view` (axis + units + log y), `dose` (distance, quantity, geometry, exposure),
// `shield` (material, thickness), and the `cursor_offset_s` time cursor. A v1 file still
// loads: the new sections are optional and fall back to the type defaults.
//
// What is and is NOT persisted is a CONSCIOUS decision (M6-ui M6h #4; §11 no-silent-drop):
// purely cosmetic / write-only entry state is EPHEMERAL by design — the dose breakdown
// `mode` (stacked↔grouped), the exposure-entry display unit, and the time control's "go
// to"/"set" entry fields. Those are documented as ephemeral, not silently lost.
//
// No-silent-error contract (CLAUDE.md, §11) made concrete here: loading never
// "best-efforts" a bad file. A wrong schema, a NEWER version than this build understands
// (where unknown fields would otherwise be dropped silently), or ANY malformed/out-of-range
// field throws a loud `PersistError` the UI surfaces — we refuse rather than load a
// partial, misleading state. ALL field validation lives HERE because the store's
// `loadFromText` restores by direct assignment (bypassing the setters' guards, M6h #2).

import {
  ACTIVITY_UNITS,
  AXIS_OPTIONS,
  DEFAULT_GEOMETRY,
  DOSE_QUANTITY_OPTIONS,
  GEOMETRY_OPTIONS,
  MASS_UNITS,
  type Axis,
  type DoseQuantity,
  type InventoryEntry,
  type Precision,
  type ShieldLayer,
} from "./types";

/** The full app-state slice that M6h persists. Defaults below fill any absent section. */
export interface PersistableState {
  // inventory (v1)
  entries: InventoryEntry[];
  precision: Precision;
  referenceTimeS: number;
  // prebuilt neutron source key (v3); null for a user-style inventory (§6.3 gate, M7b)
  neutronSource: string | null;
  // view (v2)
  axis: Axis;
  activityUnit: string;
  massUnit: string;
  logY: boolean;
  // dose (v2)
  doseDistanceM: number;
  doseQuantity: DoseQuantity;
  doseGeometry: string;
  exposureS: number;
  // shield stack (v4 — ordered source-side → detector-side; v2/v3 single-layer files load
  // by promoting their `material`/`thickness_cm` to a one-element stack)
  shieldLayers: ShieldLayer[];
  // time cursor (v2). null ⇒ the file did not specify one → keep the solve's default home
  // (the geometric midpoint), rather than forcing the cursor to the range start (M6h #3).
  cursorOffsetS: number | null;
}

/** The defaults for any section a (v1 or partial) file omits — mirror the store's initial
 *  values so an omitted section round-trips to the same view as a fresh app. */
export const PERSIST_DEFAULTS: Omit<
  PersistableState,
  "entries" | "precision" | "referenceTimeS" | "neutronSource"
> = {
  axis: "activity",
  activityUnit: "Bq",
  massUnit: "g",
  logY: true,
  doseDistanceM: 1.0,
  doseQuantity: "ambient_H10",
  doseGeometry: DEFAULT_GEOMETRY,
  exposureS: 3600,
  shieldLayers: [],
  cursorOffsetS: null,
};

export const STATE_SCHEMA = "radiographer.app-state";
export const STATE_VERSION = 4;

export class PersistError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PersistError";
  }
}

// Enum membership sets (the deserializer's allow-lists; #2). Derived from the single
// source of truth in types.ts so they can't drift from the UI options.
const AXIS_VALUES = new Set<string>(AXIS_OPTIONS.map((o) => o.value));
const QUANTITY_VALUES = new Set<string>(DOSE_QUANTITY_OPTIONS.map((o) => o.value));
const GEOMETRY_VALUES = new Set<string>(GEOMETRY_OPTIONS.map((o) => o.value));
const ACTIVITY_UNIT_VALUES = new Set<string>(ACTIVITY_UNITS);
const MASS_UNIT_VALUES = new Set<string>(MASS_UNITS);

interface Envelope {
  schema: string;
  version: number;
  inventory: {
    entries: InventoryEntry[];
    precision: Precision;
    reference_time_s: number;
    neutron_source: string | null;
  };
  view: {
    axis: Axis;
    activity_unit: string;
    mass_unit: string;
    log_y: boolean;
  };
  dose: {
    distance_m: number;
    quantity: DoseQuantity;
    geometry: string;
    exposure_s: number;
  };
  shield: {
    // v4: the ordered stack. v2/v3 single-layer fields are still READ on load (below).
    layers: { material: string; thickness_cm: number }[];
  };
  cursor_offset_s: number | null;
}

/** Serialize app state into the versioned envelope (pretty JSON text). */
export function serializeState(state: PersistableState): string {
  const env: Envelope = {
    schema: STATE_SCHEMA,
    version: STATE_VERSION,
    inventory: {
      entries: state.entries.map((e) => ({
        name: e.name,
        quantity: e.quantity,
        unit: e.unit,
      })),
      precision: state.precision,
      reference_time_s: state.referenceTimeS,
      neutron_source: state.neutronSource,
    },
    view: {
      axis: state.axis,
      activity_unit: state.activityUnit,
      mass_unit: state.massUnit,
      log_y: state.logY,
    },
    dose: {
      distance_m: state.doseDistanceM,
      quantity: state.doseQuantity,
      geometry: state.doseGeometry,
      exposure_s: state.exposureS,
    },
    shield: {
      layers: state.shieldLayers.map((l) => ({ material: l.material, thickness_cm: l.thicknessCm })),
    },
    cursor_offset_s: state.cursorOffsetS,
  };
  return JSON.stringify(env, null, 2);
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseEntry(raw: unknown, i: number): InventoryEntry {
  if (!isObject(raw)) throw new PersistError(`inventory.entries[${i}] is not an object`);
  const { name, quantity, unit } = raw;
  if (typeof name !== "string" || name.length === 0) {
    throw new PersistError(`inventory.entries[${i}].name must be a non-empty string`);
  }
  // quantity must be a real number, not a stringified one — the round-trip contract.
  if (typeof quantity !== "number" || !Number.isFinite(quantity)) {
    throw new PersistError(`inventory.entries[${i}].quantity must be a finite number`);
  }
  if (typeof unit !== "string" || unit.length === 0) {
    throw new PersistError(`inventory.entries[${i}].unit must be a non-empty string`);
  }
  return { name, quantity, unit };
}

/** A finite number ≥ `min` at `path`, or `fallback` when the key is absent. Loud otherwise
 *  (no silent clamp on load — the load path bypasses the setters' guards, M6h #2). */
function reqNumber(obj: Record<string, unknown>, key: string, path: string, min: number, fallback: number): number {
  if (obj[key] === undefined) return fallback;
  const v = obj[key];
  if (typeof v !== "number" || !Number.isFinite(v)) {
    throw new PersistError(`${path} must be a finite number (got ${JSON.stringify(v)})`);
  }
  if (v < min) throw new PersistError(`${path} must be ≥ ${min} (got ${v})`);
  return v;
}

/** A value from `allowed` at `path`, or `fallback` when absent. Loud on an off-enum value. */
function reqEnum<T extends string>(
  obj: Record<string, unknown>,
  key: string,
  path: string,
  allowed: Set<string>,
  fallback: T,
): T {
  if (obj[key] === undefined) return fallback;
  const v = obj[key];
  if (typeof v !== "string" || !allowed.has(v)) {
    throw new PersistError(`${path} must be one of [${[...allowed].join(", ")}] (got ${JSON.stringify(v)})`);
  }
  return v as T;
}

/**
 * Parse + validate a state file into `PersistableState`. Throws `PersistError`
 * loudly on anything wrong — never returns a partial/fabricated state. Absent
 * sections fall back to `PERSIST_DEFAULTS` (forward/backward tolerance, e.g. v1 files).
 */
export function deserializeState(text: string): PersistableState {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch (err) {
    throw new PersistError(`not valid JSON: ${(err as Error).message}`);
  }
  if (!isObject(obj)) throw new PersistError("top level is not an object");
  if (obj.schema !== STATE_SCHEMA) {
    throw new PersistError(
      `not a Radiographer state file (schema=${JSON.stringify(obj.schema)}, ` +
        `expected ${JSON.stringify(STATE_SCHEMA)})`,
    );
  }
  if (typeof obj.version !== "number" || !Number.isInteger(obj.version)) {
    throw new PersistError(`missing or non-integer version (${JSON.stringify(obj.version)})`);
  }
  if (obj.version > STATE_VERSION) {
    // Refuse rather than silently drop the newer fields we don't understand (§11).
    throw new PersistError(
      `saved by a newer version of Radiographer (v${obj.version}); this build supports ` +
        `up to v${STATE_VERSION}. Update the app to load this file.`,
    );
  }

  // -- inventory (required; the v1 slice) --
  const inv = obj.inventory;
  if (!isObject(inv)) throw new PersistError("missing inventory section");

  const entriesRaw = inv.entries;
  if (!Array.isArray(entriesRaw)) throw new PersistError("inventory.entries must be an array");
  const entries = entriesRaw.map(parseEntry);

  const precision = inv.precision;
  if (precision !== "double" && precision !== "hp") {
    throw new PersistError(`inventory.precision must be "double" or "hp" (got ${JSON.stringify(precision)})`);
  }

  // t=0 is optional for forward/backward tolerance, but a present value must be a number ≥ 0.
  const referenceTimeS = reqNumber(inv, "reference_time_s", "inventory.reference_time_s", 0, 0);

  // prebuilt neutron source (v3; optional → null). A present value must be a non-empty
  // string (the engine fails loud on an unknown source key as the backstop, §6.3).
  let neutronSource: string | null = null;
  if (inv.neutron_source !== undefined && inv.neutron_source !== null) {
    if (typeof inv.neutron_source !== "string" || inv.neutron_source.length === 0) {
      throw new PersistError(
        `inventory.neutron_source must be null or a non-empty string (got ${JSON.stringify(inv.neutron_source)})`,
      );
    }
    neutronSource = inv.neutron_source;
  }

  // -- view (v2; optional → defaults) --
  const view = obj.view === undefined ? {} : obj.view;
  if (!isObject(view)) throw new PersistError("view section must be an object");
  const axis = reqEnum<Axis>(view, "axis", "view.axis", AXIS_VALUES, PERSIST_DEFAULTS.axis);
  const activityUnit = reqEnum(view, "activity_unit", "view.activity_unit", ACTIVITY_UNIT_VALUES, PERSIST_DEFAULTS.activityUnit);
  const massUnit = reqEnum(view, "mass_unit", "view.mass_unit", MASS_UNIT_VALUES, PERSIST_DEFAULTS.massUnit);
  let logY = PERSIST_DEFAULTS.logY;
  if (view.log_y !== undefined) {
    if (typeof view.log_y !== "boolean") throw new PersistError(`view.log_y must be a boolean (got ${JSON.stringify(view.log_y)})`);
    logY = view.log_y;
  }

  // -- dose (v2; optional → defaults). distance > 0 (γ field singular at 0); exposure ≥ 0. --
  const dose = obj.dose === undefined ? {} : obj.dose;
  if (!isObject(dose)) throw new PersistError("dose section must be an object");
  const doseDistanceM = reqNumberPositive(dose, "distance_m", "dose.distance_m", PERSIST_DEFAULTS.doseDistanceM);
  const doseQuantity = reqEnum<DoseQuantity>(dose, "quantity", "dose.quantity", QUANTITY_VALUES, PERSIST_DEFAULTS.doseQuantity);
  const doseGeometry = reqEnum(dose, "geometry", "dose.geometry", GEOMETRY_VALUES, PERSIST_DEFAULTS.doseGeometry);
  const exposureS = reqNumber(dose, "exposure_s", "dose.exposure_s", 0, PERSIST_DEFAULTS.exposureS);

  // -- shield (v4 stack; optional → []). A v4 file carries `layers`; a v2/v3 file carries the
  //    single `material`/`thickness_cm`, promoted here to a one-element stack (backward compat).
  //    Each layer's material is a non-empty string (the picker + engine fail-loud are the
  //    backstop for an unknown/no-buildup id, M6g #3); thickness ≥ 0. --
  const shield = obj.shield === undefined ? {} : obj.shield;
  if (!isObject(shield)) throw new PersistError("shield section must be an object");
  const shieldLayers = parseShieldLayers(shield);

  // -- time cursor (v2; optional → null = keep the solve's default home, M6h #3) --
  let cursorOffsetS: number | null = PERSIST_DEFAULTS.cursorOffsetS;
  if (obj.cursor_offset_s !== undefined && obj.cursor_offset_s !== null) {
    if (typeof obj.cursor_offset_s !== "number" || !Number.isFinite(obj.cursor_offset_s)) {
      throw new PersistError(`cursor_offset_s must be a finite number or null (got ${JSON.stringify(obj.cursor_offset_s)})`);
    }
    cursorOffsetS = obj.cursor_offset_s;
  }

  return {
    entries,
    precision,
    referenceTimeS,
    neutronSource,
    axis,
    activityUnit,
    massUnit,
    logY,
    doseDistanceM,
    doseQuantity,
    doseGeometry,
    exposureS,
    shieldLayers,
    cursorOffsetS,
  };
}

/** Parse the shield section into an ordered layer stack. Reads v4 `layers` if present, else
 *  promotes a v2/v3 single `material`/`thickness_cm` to a one-element stack; absent → []. A
 *  present layer must have a non-empty material id and a finite thickness ≥ 0 (loud, M6h #2). */
function parseShieldLayers(shield: Record<string, unknown>): ShieldLayer[] {
  if (shield.layers !== undefined) {
    if (!Array.isArray(shield.layers)) throw new PersistError("shield.layers must be an array");
    return shield.layers.map((raw, i) => {
      if (!isObject(raw)) throw new PersistError(`shield.layers[${i}] is not an object`);
      const { material, thickness_cm } = raw;
      if (typeof material !== "string" || material.length === 0) {
        throw new PersistError(`shield.layers[${i}].material must be a non-empty string`);
      }
      if (typeof thickness_cm !== "number" || !Number.isFinite(thickness_cm) || thickness_cm < 0) {
        throw new PersistError(`shield.layers[${i}].thickness_cm must be a finite number ≥ 0 (got ${JSON.stringify(thickness_cm)})`);
      }
      return { material, thicknessCm: thickness_cm };
    });
  }
  // Legacy v2/v3 single-layer form.
  if (shield.material === undefined || shield.material === null) return [];
  if (typeof shield.material !== "string" || shield.material.length === 0) {
    throw new PersistError(`shield.material must be null or a non-empty string (got ${JSON.stringify(shield.material)})`);
  }
  const thicknessCm = reqNumber(shield, "thickness_cm", "shield.thickness_cm", 0, DEFAULT_SHIELD_THICKNESS_CM_FALLBACK);
  return [{ material: shield.material, thicknessCm }];
}

// The thickness a legacy file gets if it somehow carried a material but no thickness_cm.
const DEFAULT_SHIELD_THICKNESS_CM_FALLBACK = 1.0;

/** A finite number strictly > 0 at `path`, or `fallback` when absent (distance's contract). */
function reqNumberPositive(obj: Record<string, unknown>, key: string, path: string, fallback: number): number {
  if (obj[key] === undefined) return fallback;
  const v = obj[key];
  if (typeof v !== "number" || !Number.isFinite(v)) {
    throw new PersistError(`${path} must be a finite number (got ${JSON.stringify(v)})`);
  }
  if (!(v > 0)) throw new PersistError(`${path} must be > 0 (got ${v})`);
  return v;
}

// --- browser I/O (thin, side-effecting wrappers; the store calls these) -------

/** Trigger a download of `text` as `filename` (portable save). */
export function downloadStateFile(text: string, filename = "radiographer-state.json"): void {
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Read an uploaded file's text (load). */
export function readStateFile(file: File): Promise<string> {
  return file.text();
}

// NOTE: localStorage autosave (the §9 "autosave convenience") stays DEFERRED past v1 — a
// CONSCIOUS M6h decision (see docs/plans/M6h-honesty-persist-polish.md #7), not a
// fall-through: the portable file save/load above is the source-of-truth path and IS
// gate-tested (the full-state round-trip), whereas autosave needs boot-restore wiring that
// interacts with the heavy Pyodide boot, and first-load service-worker caching is itself a
// documented stretch. It is post-v1 polish, recorded loudly rather than half-wired here.
