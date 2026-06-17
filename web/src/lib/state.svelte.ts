// Central app-state store — the single source of truth (M6-ui M6b; §9).
//
// Every view (curves, DAG, dose, shield — M6c onward) reads from THIS object. It
// owns the inventory model, the live engine handle, the shared per-species color
// map, and save/load. The `.svelte.ts` extension is load-bearing: it is what
// compiles the `$state` runes (a plain `.ts` would silently not be reactive).
//
// Load-bearing invariants (M6-ui "Cross-cutting invariants"):
//  #1 Solve once, evaluate many — a re-solve happens ONLY when the inventory
//     changes (entries / units / quantities / precision). The reference time
//     (t=0) is NOT a re-solve trigger in M6b: §8/§9 treat source-age as an
//     evaluation offset (forward decay is free), so it is stored here and its
//     semantics land in M6d. (M6-ui invariant #1 lists t=0 as a re-solve trigger;
//     that contradicts §8/§9 and is resolved here in favor of "offset, not solve".)
//  #2 Handle lifecycle — on every solve the previous handle is released; a new
//     one is kept only on success, so the Python `_REGISTRY` never leaks and at
//     most one live handle exists.
//  #3 No silent errors — a failed solve is a visible error + status, never a blank.
//  #4 Shared per-species color — assigned here, once per solve, over the full
//     descendant closure; consumed identically by all views.

import {
  BridgeClient,
  type Handle,
  type SolveEntry,
  type SolveOk,
} from "./bridge";
import { ColorRegistry } from "./palette";
import {
  deserializeState,
  downloadStateFile,
  readStateFile,
  serializeState,
  PersistError,
  type PersistableState,
} from "./persist";
import { DEFAULT_UNIT, type InventoryEntry, type Precision } from "./types";

export type SolveStatus = "idle" | "solving" | "solved" | "error";

/** Let a "solving…" state paint before a (synchronous, main-thread) solve blocks. */
const yieldToPaint = () => new Promise<void>((r) => setTimeout(r, 0));

export class AppState {
  // -- the inventory model (source of truth) --------------------------------
  entries = $state<InventoryEntry[]>([]);
  precision = $state<Precision>("double");
  /** Reference time / source-age (t=0), seconds. Stored only in M6b (see invariant #1). */
  referenceTimeS = $state<number>(0);

  // -- engine + derived solve state -----------------------------------------
  /** The live Bateman solve; null when empty or after a failed solve (#2). */
  handle = $state<Handle | null>(null);
  solveMeta = $state<SolveOk | null>(null);
  /** Fresh `{nuclide: color}` per solve (a new reference so `$state` tracks it, #4). */
  colors = $state<Record<string, string>>({});
  status = $state<SolveStatus>("idle");
  errorMsg = $state<string>("");

  // -- add-by-name source (fetched once after boot) -------------------------
  availableNuclides = $state<string[]>([]);
  /** True once the engine client is attached and the nuclide list is loaded. */
  ready = $state<boolean>(false);

  private client: BridgeClient | null = null;
  private availableSet = new Set<string>();
  private readonly registry = new ColorRegistry();

  // -- derived (getters stay reactive when read in components) --------------
  get isEmpty(): boolean {
    return this.entries.length === 0;
  }
  get hpRecommended(): boolean {
    return this.solveMeta?.hp_recommended ?? false;
  }
  /** The full descendant closure of the current solve (parents + daughters). */
  get closure(): string[] {
    return this.solveMeta?.nuclides ?? [];
  }

  // -- wiring ---------------------------------------------------------------

  /** Attach the engine client (after boot) and load the add-by-name nuclide list. */
  setClient(client: BridgeClient): void {
    this.client = client;
    const res = client.nuclides();
    if (res.ok) {
      this.availableNuclides = res.nuclides;
      this.availableSet = new Set(res.nuclides);
    } else {
      // Don't hard-fail boot: solve still validates loudly. But surface the gap.
      this.errorMsg = `could not load nuclide list: ${res.error.type}: ${res.error.message}`;
    }
    this.ready = true;
  }

  // -- validation (inline, near the add row) --------------------------------

  /** Null if `name` is a solvable nuclide; an error string otherwise. */
  validateName(name: string): string | null {
    const n = name.trim();
    if (!n) return "enter a nuclide name";
    // Validate only when the list is loaded; otherwise defer to the bridge's loud error.
    if (this.availableSet.size > 0 && !this.availableSet.has(n)) {
      return `unknown nuclide ${JSON.stringify(n)} — not in the engine dataset`;
    }
    return null;
  }

  validateQuantity(q: number): string | null {
    if (!Number.isFinite(q) || q <= 0) return "quantity must be a positive number";
    return null;
  }

  // -- mutations (each commit re-solves; #1) --------------------------------

  /** Add an isotope. Returns an inline validation error, or null once accepted. */
  async addEntry(name: string, quantity: number, unit: string = DEFAULT_UNIT): Promise<string | null> {
    const trimmed = name.trim();
    const nameErr = this.validateName(trimmed);
    if (nameErr) return nameErr;
    const qErr = this.validateQuantity(quantity);
    if (qErr) return qErr;
    this.entries = [...this.entries, { name: trimmed, quantity, unit }];
    await this.solve();
    return null;
  }

  async removeEntry(index: number): Promise<void> {
    if (index < 0 || index >= this.entries.length) return;
    this.entries = this.entries.filter((_, i) => i !== index);
    await this.solve();
  }

  /** Edit an existing entry's quantity and/or unit (re-solves). */
  async updateEntry(index: number, patch: { quantity?: number; unit?: string }): Promise<string | null> {
    if (index < 0 || index >= this.entries.length) return "no such entry";
    if (patch.quantity !== undefined) {
      const qErr = this.validateQuantity(patch.quantity);
      if (qErr) return qErr;
    }
    this.entries = this.entries.map((e, i) => (i === index ? { ...e, ...patch } : e));
    await this.solve();
    return null;
  }

  /** Precision is inventory-defining → re-solve (#1). */
  async setPrecision(p: Precision): Promise<void> {
    if (p === this.precision) return;
    this.precision = p;
    await this.solve();
  }

  /** Reference time / source-age. NOT a re-solve trigger in M6b (#1). */
  setReferenceTimeS(t: number): void {
    this.referenceTimeS = Number.isFinite(t) ? t : 0;
  }

  // -- the solve primitive --------------------------------------------------

  /**
   * The one re-solve. Releases the previous handle, solves the current inventory,
   * keeps the new handle only on success, and reassigns the shared color map.
   */
  async solve(): Promise<void> {
    if (!this.client) {
      this.status = "error";
      this.errorMsg = "engine not ready";
      return;
    }
    const old = this.handle;

    if (this.entries.length === 0) {
      this.releaseHandle(old);
      this.handle = null;
      this.solveMeta = null;
      this.colors = {};
      this.errorMsg = "";
      this.status = "idle";
      return;
    }

    this.status = "solving";
    this.errorMsg = "";
    await yieldToPaint();

    const spec: { entries: SolveEntry[]; precision: Precision } = {
      entries: this.entries.map((e) => ({ name: e.name, quantity: e.quantity, unit: e.unit })),
      precision: this.precision,
    };
    const res = this.client.solve(spec);

    // Release the previous handle either way — it no longer matches the inventory (#2).
    this.releaseHandle(old);

    if (!res.ok) {
      this.handle = null;
      this.solveMeta = null;
      this.colors = {};
      this.status = "error";
      this.errorMsg = `${res.error.type}: ${res.error.message}`;
      return;
    }

    this.handle = res.handle;
    this.solveMeta = res;
    this.colors = this.registry.assignAll(res.nuclides); // fresh reference → reactive (#4)
    this.status = "solved";
  }

  private releaseHandle(h: Handle | null): void {
    if (h && this.client) this.client.release(h);
  }

  // -- persistence (M6b: inventory slice; later chunks extend the envelope) --

  private toPersistable(): PersistableState {
    return {
      entries: this.entries.map((e) => ({ ...e })),
      precision: this.precision,
      referenceTimeS: this.referenceTimeS,
    };
  }

  /** The versioned JSON text of the current state (pure; no I/O). */
  serialize(): string {
    return serializeState(this.toPersistable());
  }

  /** Save to a downloaded file (the portable §9 save path). */
  download(filename?: string): void {
    downloadStateFile(this.serialize(), filename);
  }

  /** Replace state from a versioned JSON text, then re-solve. Returns an error or null. */
  async loadFromText(text: string): Promise<string | null> {
    let parsed: PersistableState;
    try {
      parsed = deserializeState(text);
    } catch (err) {
      const msg = err instanceof PersistError ? err.message : String(err);
      this.status = "error";
      this.errorMsg = `load failed — ${msg}`;
      return msg;
    }
    this.entries = parsed.entries.map((e) => ({ ...e }));
    this.precision = parsed.precision;
    this.referenceTimeS = parsed.referenceTimeS;
    await this.solve();
    return null;
  }

  async loadFile(file: File): Promise<string | null> {
    return this.loadFromText(await readStateFile(file));
  }

  /** Clear the inventory (releases the handle). */
  async clear(): Promise<void> {
    this.entries = [];
    await this.solve();
  }
}

/** The app-wide singleton every component imports. */
export const appState = new AppState();
