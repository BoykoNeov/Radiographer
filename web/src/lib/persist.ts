// Versioned save/load of app state (HANDOFF_PLAN §9; M6-ui M6b).
//
// M6b serializes the INVENTORY slice only (entries + precision + t=0). Later chunks
// (M6d/f/g) add their own sections — distance, shield, geometry, time cursor — and
// BUMP `STATE_VERSION`; each adds its section additively and teaches the loader to
// read it. The full-state round-trip test lands in M6h.
//
// No-silent-error contract (CLAUDE.md, §11) made concrete here: loading never
// "best-efforts" a bad file. A wrong schema, a NEWER version than this build
// understands (where unknown fields would otherwise be dropped silently), or a
// malformed inventory all throw a loud `PersistError` the UI surfaces — we refuse
// rather than load a partial, misleading state.

import type { InventoryEntry, Precision } from "./types";

/** The inventory slice that M6b persists. Later chunks add sibling sections. */
export interface PersistableState {
  entries: InventoryEntry[];
  precision: Precision;
  referenceTimeS: number;
}

export const STATE_SCHEMA = "radiographer.app-state";
export const STATE_VERSION = 1;

export class PersistError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PersistError";
  }
}

interface Envelope {
  schema: string;
  version: number;
  inventory: {
    entries: InventoryEntry[];
    precision: Precision;
    reference_time_s: number;
  };
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
    },
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

/**
 * Parse + validate a state file into `PersistableState`. Throws `PersistError`
 * loudly on anything wrong — never returns a partial/fabricated state.
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

  const inv = obj.inventory;
  if (!isObject(inv)) throw new PersistError("missing inventory section");

  const entriesRaw = inv.entries;
  if (!Array.isArray(entriesRaw)) throw new PersistError("inventory.entries must be an array");
  const entries = entriesRaw.map(parseEntry);

  const precision = inv.precision;
  if (precision !== "double" && precision !== "hp") {
    throw new PersistError(`inventory.precision must be "double" or "hp" (got ${JSON.stringify(precision)})`);
  }

  // t=0 is optional for forward/backward tolerance, but a present value must be a number.
  let referenceTimeS = 0;
  if (inv.reference_time_s !== undefined) {
    if (typeof inv.reference_time_s !== "number" || !Number.isFinite(inv.reference_time_s)) {
      throw new PersistError("inventory.reference_time_s must be a finite number");
    }
    referenceTimeS = inv.reference_time_s;
  }

  return { entries, precision, referenceTimeS };
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

// NOTE: localStorage autosave (the §9 "autosave convenience") is DEFERRED. The
// portable file save/load above is the source-of-truth path and is gate-tested;
// autosave needs boot-restore wiring + write-on-change and interacts with the M6h
// full-state round-trip, so it lands with that, not as half-wired dead code here.
