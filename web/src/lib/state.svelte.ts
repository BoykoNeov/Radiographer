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
  type DoseOk,
  type EvaluateOk,
  type Handle,
  type SolveEntry,
  type SolveOk,
} from "./bridge";
import { interpAt, trapzWindow, type TrapzResult } from "./dosemath";
import { ColorRegistry } from "./palette";
import {
  deserializeState,
  downloadStateFile,
  readStateFile,
  serializeState,
  PersistError,
  type PersistableState,
} from "./persist";
import {
  ATOMS_UNIT,
  DEFAULT_GEOMETRY,
  DEFAULT_UNIT,
  type Axis,
  type DoseQuantity,
  type InventoryEntry,
  type Precision,
} from "./types";

export type SolveStatus = "idle" | "solving" | "solved" | "error";

/** Let a "solving…" state paint before a (synchronous, main-thread) solve blocks. */
const yieldToPaint = () => new Promise<void>((r) => setTimeout(r, 0));

/**
 * `n` log-spaced times over `[lo, hi]` (both > 0) — the per-inventory overlay grid
 * (§9 auto-range). The slider scrubs a cursor over THIS grid in M6d; M6c omits the
 * t=0 offset (an evaluation offset that lands with the time control, M6d).
 */
function logGrid(lo: number, hi: number, n: number): number[] {
  if (!(lo > 0) || !(hi > lo) || n < 2) return [lo, hi].filter((x) => x > 0);
  const a = Math.log10(lo);
  const b = Math.log10(hi);
  const out = new Array<number>(n);
  for (let i = 0; i < n; i++) out[i] = 10 ** (a + ((b - a) * i) / (n - 1));
  return out;
}

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

  // -- overlay-curve display state (M6c, §9) --------------------------------
  // The quantity axis + its secondary unit are DISPLAY state: changing them
  // re-evaluates the already-solved inventory (cheap), it NEVER re-solves (#1).
  // It is deliberately NOT persisted in v1 (the M6b serializer covers the
  // inventory slice; axis is a view preference — see docs/plans/M6c-curves.md).
  axis = $state<Axis>("activity");
  activityUnit = $state<string>("Bq");
  massUnit = $state<string>("g");
  /** Log y-axis (default, §9) vs linear; a pure render flag — no re-evaluate. */
  logY = $state<boolean>(true);
  /** The one evaluate() feeding the overlay; null when empty/stale/failed. */
  curve = $state<EvaluateOk | null>(null);
  /**
   * The DISPLAY-time grid the curves are plotted against (seconds since the
   * reference origin / source-age, §9). The overlay is evaluated at the ABSOLUTE
   * decay times `referenceTimeS + curveX` (M6d offset; see `recomputeCurves`), but
   * plotted against `curveX` so the x-axis, cursor, and half-life ticks all live
   * in one coordinate and are identical to M6c when `referenceTimeS === 0`.
   */
  curveX = $state<number[]>([]);
  /** Loud curve-path error (#3) — surfaced, never a silent blank chart. */
  curveError = $state<string>("");

  // -- time control (M6d, §9) -----------------------------------------------
  // The slider/cursor scrubs a position over the already-drawn curves; it is a
  // pure client-side cursor — moving it NEVER re-evaluates and NEVER re-solves
  // (#1). `cursorOffsetS` is DISPLAY time (seconds since the reference origin);
  // the absolute decay time fed to evaluate/dose/chain is `currentTimeS` below.
  cursorOffsetS = $state<number>(0);
  /**
   * True while the time control is sweeping the cursor (the §9 animate). Owned
   * here so it is observable and, crucially, **cancellable on any inventory
   * change**: `solve()` clears it, so a running sweep can never keep evaluating
   * against a released handle (advisor: an orphaned loop is a silent-error vector).
   * The frame loop itself lives in `TimeControl.svelte` and bails when this is false.
   */
  animating = $state<boolean>(false);

  // -- dose calculator (M6f, §9) --------------------------------------------
  // The dose is "solve once, evaluate many" exactly like the curves (#1): the store
  // evaluates a γ + β dose-RATE SERIES over the SAME `curveX` display grid, once per
  // (inventory × distance × quantity × geometry); the cursor then INDEXES that series
  // and the accumulated dose INTEGRATES it (see the getters below) — so scrub/animate
  // make ZERO bridge calls. Recompute triggers mirror the curves' (solve, source-age)
  // plus the dose inputs. This path NEVER routes through solve() (gate: registry==1).
  // See docs/plans/M6f-dose.md.
  //
  // γ (and neutron, M7) are Sv (H*(10)/effective); β is a DIFFERENT quantity — Gy at
  // 7 mg/cm² (Hp(0.07), w_R=1) — kept in its own series and NEVER summed into the Sv
  // total (invariant #5; §6.2 LOCKED). Inputs are TRANSIENT in M6f-1: their
  // persistence + round-trip lands in M6h with the cursor (NOT a silent drop, §11).
  doseDistanceM = $state<number>(1.0);
  doseQuantity = $state<DoseQuantity>("ambient_H10");
  /** ICRP-116 geometry; used only when `doseQuantity === "effective"` (§13 #3 → AP). */
  doseGeometry = $state<string>(DEFAULT_GEOMETRY);
  /** Exposure window length (seconds) for the accumulated-dose integral. */
  exposureS = $state<number>(3600);
  /** γ dose-rate series (Sv/s) over `curveX`; null when empty/stale/failed. */
  gammaDoseSeries = $state<DoseOk | null>(null);
  /** β skin-dose-rate series (Gy/s, Hp(0.07)) over `curveX` — a separate quantity. */
  betaDoseSeries = $state<DoseOk | null>(null);
  /** Loud dose-path error (#3) — surfaced, never a silent blank breakdown. */
  doseError = $state<string>("");

  /** Overlay grid density (log-spaced). HP is sympy-per-point → keep it responsive. */
  private readonly CURVE_POINTS = 300;
  private readonly CURVE_POINTS_HP = 60;

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
  /** The engine `unit` for the current axis (the secondary-unit selection, §12). */
  get curveUnit(): string {
    if (this.axis === "activity") return this.activityUnit;
    if (this.axis === "mass") return this.massUnit;
    return ATOMS_UNIT;
  }
  /**
   * The DISPLAY-time slider envelope `[lo, hi]` (seconds since the reference
   * origin) = the solve's auto-range; null when every nuclide is stable (no
   * evolution to scrub). The slider/ticks live in this coordinate.
   */
  get cursorRange(): [number, number] | null {
    const r = this.solveMeta?.time_range_s;
    return r ? [r[0], r[1]] : null;
  }
  /**
   * The ABSOLUTE decay time (seconds since the solve origin) at the cursor — the
   * single value M6e (DAG) and M6f (dose) consume: `referenceTimeS` (source-age)
   * + `cursorOffsetS` (slider position). This is the offset wired at evaluate time
   * (the M6b deferral; §8/§9 "forward decay is free"). At t₀=0 it equals the cursor.
   */
  get currentTimeS(): number {
    return this.referenceTimeS + this.cursorOffsetS;
  }

  // -- dose at the cursor (pure client-side index into the rate series, #1/§3) --
  // These read the precomputed dose-rate series at the cursor; moving the cursor or
  // changing the exposure re-derives them with NO bridge call (the §3 payoff). The
  // rate series is indexed by `curveX` (display time), so the cursor's display
  // position `cursorOffsetS` is the query — the same coordinate as the curves.

  /** γ dose-RATE (Sv/s) at the cursor; null when no γ series. */
  get gammaRateAtCursor(): number | null {
    const s = this.gammaDoseSeries;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }
  /** β skin dose-RATE (Gy/s, Hp(0.07)) at the cursor; null when no β series. */
  get betaRateAtCursor(): number | null {
    const s = this.betaDoseSeries;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }
  /** γ ACCUMULATED dose (Sv) over [cursor, cursor+exposure] — ∫rate dt, not rate×t
   *  (#2, §11). `truncated` flags an exposure window past the modeled range. */
  get gammaAccumulated(): TrapzResult | null {
    const s = this.gammaDoseSeries;
    if (!s) return null;
    return trapzWindow(this.curveX, s.rate_si, this.cursorOffsetS, this.cursorOffsetS + this.exposureS);
  }
  /** β ACCUMULATED skin dose (Gy) over the same window. */
  get betaAccumulated(): TrapzResult | null {
    const s = this.betaDoseSeries;
    if (!s) return null;
    return trapzWindow(this.curveX, s.rate_si, this.cursorOffsetS, this.cursorOffsetS + this.exposureS);
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

  /**
   * Reference time / source-age (t₀), seconds, clamped ≥ 0. NOT a re-solve (#1):
   * §8/§9 treat source-age as an evaluation offset (forward decay is free), so
   * this RE-EVALUATES the already-solved inventory at the shifted absolute times
   * (`referenceTimeS + curveX`). This is the M6d wiring of the M6b-stored offset.
   * The cursor's display position (`cursorOffsetS`) is unchanged — only the
   * absolute `currentTimeS` shifts.
   */
  setReferenceTimeS(t: number): void {
    const next = Number.isFinite(t) ? Math.max(0, t) : 0;
    if (next === this.referenceTimeS) return;
    this.referenceTimeS = next;
    this.recomputeCurves(); // evaluate at the shifted times — never a re-solve (#1)
    this.recomputeDose(); // and the dose series at the shifted times (same offset, #1)
  }

  /**
   * Move the time cursor to `t` seconds (display time, since the reference
   * origin), clamped to the slider envelope. A pure cursor move: it changes
   * `currentTimeS` (what the DAG/dose read) but NEVER re-evaluates or re-solves
   * (#1) — the curves already span the whole range; the cursor is just a marker.
   */
  setCursorOffsetS(t: number): void {
    if (!Number.isFinite(t)) return;
    const r = this.cursorRange;
    this.cursorOffsetS = r ? Math.min(Math.max(t, r[0]), r[1]) : Math.max(0, t);
  }

  // -- curve display controls (each RE-EVALUATES, never re-solves; #1) -------

  setAxis(a: Axis): void {
    if (a === this.axis) return;
    this.axis = a;
    this.recomputeCurves();
  }

  setActivityUnit(u: string): void {
    if (u === this.activityUnit) return;
    this.activityUnit = u;
    if (this.axis === "activity") this.recomputeCurves();
  }

  setMassUnit(u: string): void {
    if (u === this.massUnit) return;
    this.massUnit = u;
    if (this.axis === "mass") this.recomputeCurves();
  }

  /** Log vs linear y-axis. Pure render flag — flooring happens in the renderer; no evaluate. */
  setLogY(v: boolean): void {
    this.logY = v;
  }

  // -- dose inputs (each RE-EVALUATES the rate series, never re-solves; #1) ---
  // distance / quantity / geometry change the per-decay coefficients → recompute the
  // dose-rate series (a cheap evaluate off the live handle). exposure & the cursor do
  // NOT — they only move the integration window / index, re-derived by the getters.

  /** Source–target distance (m). Must be > 0 (the point-source γ field is singular at
   *  0); a non-positive value is ignored so the input can't drive a loud engine error. */
  setDoseDistanceM(d: number): void {
    if (!Number.isFinite(d) || d <= 0 || d === this.doseDistanceM) return;
    this.doseDistanceM = d;
    this.recomputeDose();
  }

  setDoseQuantity(q: DoseQuantity): void {
    if (q === this.doseQuantity) return;
    this.doseQuantity = q;
    this.recomputeDose(); // H*(10) ↔ effective is a wholly different conversion table
  }

  setDoseGeometry(g: string): void {
    if (g === this.doseGeometry) return;
    this.doseGeometry = g;
    if (this.doseQuantity === "effective") this.recomputeDose(); // geometry only bites E
  }

  /** Exposure window length (s) for the accumulated integral. NO recompute — the
   *  accumulated getters re-integrate the existing rate series over the new window. */
  setExposureS(s: number): void {
    if (!Number.isFinite(s) || s < 0) return;
    this.exposureS = s;
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
    this.animating = false; // cancel any running sweep — the handle is about to change (#2)
    const old = this.handle;

    if (this.entries.length === 0) {
      this.releaseHandle(old);
      this.handle = null;
      this.solveMeta = null;
      this.colors = {};
      this.curve = null;
      this.curveX = [];
      this.cursorOffsetS = 0;
      this.curveError = "";
      this.clearDose();
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
      this.curve = null;
      this.curveX = [];
      this.cursorOffsetS = 0;
      this.curveError = "";
      this.clearDose();
      this.status = "error";
      this.errorMsg = `${res.error.type}: ${res.error.message}`;
      return;
    }

    this.handle = res.handle;
    this.solveMeta = res;
    this.colors = this.registry.assignAll(res.nuclides); // fresh reference → reactive (#4)
    this.status = "solved";
    this.resetCursor(); // the range changed → home the cursor before evaluating (#2 advisor)
    this.recomputeCurves(); // one evaluate over the auto-range grid (§9; "evaluate many", #1)
    this.recomputeDose(); // and the dose-rate series over the same grid (M6f; pure evaluate)
  }

  /**
   * Home the time cursor whenever the inventory (hence the auto-range) changes —
   * a stale cursor from a previous inventory would point off-range (advisor blind
   * spot). Default to the geometric midpoint of the log envelope (a representative
   * mid-evolution point); 0 when there is no range (all-stable, slider disabled).
   */
  private resetCursor(): void {
    const r = this.cursorRange;
    this.cursorOffsetS = r ? Math.sqrt(r[0] * r[1]) : 0;
  }

  private releaseHandle(h: Handle | null): void {
    if (h && this.client) this.client.release(h);
  }

  // -- the evaluate primitive (the "evaluate many" half of #1) --------------

  /**
   * Evaluate the already-solved inventory over a log-spaced grid spanning the
   * auto time-range, in the current axis + unit, and store it for the overlay.
   * Pure re-evaluation — it reuses the live handle and NEVER re-solves (#1).
   * Loud on failure: clears the curve and sets `curveError` (#3), never a blank.
   */
  private recomputeCurves(): void {
    this.curveError = "";
    const meta = this.solveMeta;
    if (!this.client || !this.handle || !meta) {
      this.curve = null;
      this.curveX = [];
      return;
    }
    const range = meta.time_range_s;
    if (!range) {
      // Every nuclide is stable → no decay to evolve (auto_time_range is null).
      this.curve = null;
      this.curveX = [];
      return;
    }
    const n = this.precision === "hp" ? this.CURVE_POINTS_HP : this.CURVE_POINTS;
    // The DISPLAY grid (plotted x); the evaluate happens at the ABSOLUTE decay
    // times `referenceTimeS + grid` (the M6d source-age offset; "forward decay is
    // free", §8/§9). At t₀=0 these coincide → identical to M6c.
    const grid = logGrid(range[0], range[1], n);
    const t0 = this.referenceTimeS;
    const res = this.client.evaluate(this.handle, {
      times_s: t0 > 0 ? grid.map((x) => x + t0) : grid,
      axis: this.axis,
      unit: this.curveUnit,
    });
    if (!res.ok) {
      this.curve = null;
      this.curveX = [];
      this.curveError = `${res.error.type}: ${res.error.message}`;
      return;
    }
    this.curve = res;
    this.curveX = grid;
  }

  /**
   * Evaluate the γ + β dose-RATE series over the curve grid for the current distance /
   * quantity / geometry, and store them for the breakdown. Pure evaluate (reuses the
   * live handle), NEVER a re-solve (#1) — the gate asserts the registry stays at 1
   * across a distance change. Loud on failure (#3): clears both series + sets
   * `doseError`, never a silent blank breakdown.
   *
   * γ → Sv (H*(10)/effective); β → Gy (Hp(0.07)). They are kept in SEPARATE series and
   * are never summed (invariant #5; §6.2). The series share `curveX`'s display-time
   * coordinate (evaluated at the absolute times `referenceTimeS + curveX`), so the
   * cursor getters index them 1:1 with the curves.
   */
  private recomputeDose(): void {
    this.doseError = "";
    const meta = this.solveMeta;
    if (!this.client || !this.handle || !meta || this.curveX.length === 0) {
      this.gammaDoseSeries = null;
      this.betaDoseSeries = null;
      return;
    }
    const t0 = this.referenceTimeS;
    const times = t0 > 0 ? this.curveX.map((x) => x + t0) : this.curveX.slice();
    const geometry = this.doseQuantity === "effective" ? this.doseGeometry : null;

    const g = this.client.dose(this.handle, {
      times_s: times,
      quantity: this.doseQuantity,
      distance_m: this.doseDistanceM,
      geometry,
    });
    if (!g.ok) {
      this.gammaDoseSeries = null;
      this.betaDoseSeries = null;
      this.doseError = `${g.error.type}: ${g.error.message}`;
      return;
    }
    // β skin dose Hp(0.07): the same distance; no shield in M6f-1 (→ no bremsstrahlung),
    // no ICRP geometry (skin dose is depth-defined, not body-orientation-defined).
    const b = this.client.beta_dose(this.handle, {
      times_s: times,
      distance_m: this.doseDistanceM,
    });
    if (!b.ok) {
      this.gammaDoseSeries = null;
      this.betaDoseSeries = null;
      this.doseError = `${b.error.type}: ${b.error.message}`;
      return;
    }
    this.gammaDoseSeries = g;
    this.betaDoseSeries = b;
  }

  /** Clear the dose breakdown (empty / failed solve). */
  private clearDose(): void {
    this.gammaDoseSeries = null;
    this.betaDoseSeries = null;
    this.doseError = "";
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
