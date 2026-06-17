// Typed client for engine/bridge.py — the JSON contract crossing the Pyodide
// boundary (HANDOFF_PLAN §3). Pure JSON text in / JSON text out, stateful via a
// branded `Handle`. Every bridge response is the discriminated union
//   { ok: true, ... } | { ok: false, error: BridgeError }
// so callers must narrow on `.ok` before reading a payload — the no-silent-error
// contract (CLAUDE.md, §11) made structural: a failure can't be mistaken for data.

/** Opaque inventory handle minted by `solve`; never construct one by hand. */
export type Handle = string & { readonly __handle: unique symbol };

export interface BridgeError {
  type: string;
  message: string;
  /** Present only for unexpected (non-domain) failures. */
  traceback: string | null;
}

type Fail = { ok: false; error: BridgeError };
type Result<T> = (T & { ok: true }) | Fail;

// --- requests ----------------------------------------------------------------

/** One isotope line for the per-entry-units solve form (§9 inventory panel). */
export interface SolveEntry {
  name: string;
  quantity: number;
  /** An rd input unit: Bq, Ci, atoms, g, kg, mg, ug, ... */
  unit: string;
}

/**
 * Two accepted forms (the bridge dispatches on `entries`):
 *  - single-unit:   `{ nuclides, unit, precision }`
 *  - per-entry units: `{ entries: [{name,quantity,unit}], precision }`
 * The inventory panel always uses the entries form; selfcheck/tests use the older one.
 */
export type SolveSpec =
  | { entries: SolveEntry[]; precision?: "double" | "hp" }
  | {
      nuclides: Record<string, number>;
      /** Bq (default), Ci, atoms, g, kg, ug, ... — see inventory.from_spec. */
      unit?: string;
      precision?: "double" | "hp";
    };

export type DoseAxis = "atoms" | "mass" | "activity";

export interface EvaluateRequest {
  times_s: number[];
  axis?: DoseAxis;
  unit?: string | null;
}

export interface DoseRequest {
  times_s: number[];
  quantity?: string; // "air_kerma" | "ambient_H10" | "effective"
  distance_m: number;
  shield?: [string, number] | null;
  medium?: string;
  geometry?: string | null;
}

// --- responses (only the fields the app reads are typed; the bridge may add more) ---

export interface SolveOk {
  handle: Handle;
  nuclides: string[];
  half_lives_s: Record<string, number>;
  time_range_s: [number, number];
  hp_recommended: boolean;
  precision: string;
  n_nuclides: number;
}

export interface EvaluateOk {
  axis: DoseAxis;
  unit: string;
  times_s: number[];
  nuclides: string[];
  series: Record<string, number[]>;
  peak_atoms: number;
  floor_atoms: number;
}

/** One DAG node = one closure nuclide (or the SF pseudo-sink). Shape mirrors
 *  `engine/chain.build_dag`. `Z/A/N` are null only for the SF sink; `half_life_s`
 *  is null for stable nodes (and the sink). Per-emission energies are NOT here —
 *  they live in the emissions dataset, surfaced in the M6f-2 per-line dose table. */
export interface ChainNode {
  id: string;
  /** Present only on the SF pseudo-sink ("spontaneous fission products"). */
  label?: string;
  Z: number | null;
  A: number | null;
  N: number | null;
  /** Metastable state suffix ("m"/"n") or "" for the ground state. */
  state: string;
  half_life_s: number | null;
  half_life_readable: string;
  stable: boolean;
  decay_modes: string[];
}
export interface ChainEdge {
  source: string;
  target: string;
  /** Decay mode label (α, β⁻, EC, IT, SF, …). */
  mode: string;
  /** Branching fraction in [0, 1]. */
  branching: number;
}
export interface ChainOk {
  nodes: ChainNode[];
  edges: ChainEdge[];
}

export interface DoseWarning {
  reason?: string;
  nuclide?: string;
  [k: string]: unknown;
}

export interface DoseOk {
  quantity: string;
  si_unit: string;
  per: string;
  times_s: number[];
  distance_m: number;
  rate_si: number[];
  scoring_floor_MeV: number;
  warnings: DoseWarning[];
}

/** One scored photon line for the §9 per-line γ table (M6f-2). `coeff_si` is the
 *  DISTANCE- and TIME-free per-decay SI constant (Sv·m²/decay for H*(10)/effective);
 *  the client applies `1/4πd²` and the parent's activity at the cursor. */
export interface DoseLineRow {
  nuclide: string;
  E_MeV: number;
  yield: number;
  origin: string | null;
  coeff_si: number;
}

export interface DoseLinesOk {
  quantity: string;
  si_unit: string;
  lines: DoseLineRow[];
  warnings: DoseWarning[];
  scoring_floor_MeV: number;
}

export interface ReleaseOk {
  handle: string;
  existed: boolean;
}

export interface NuclidesOk {
  /** Every nuclide the engine can solve (rd dataset), natural-sorted, names only. */
  nuclides: string[];
}

export interface RegistrySizeOk {
  /** Number of live solved inventories (handle-leak canary for invariant #2). */
  size: number;
}

export type SolveResponse = Result<SolveOk>;
export type NuclidesResponse = Result<NuclidesOk>;
export type RegistrySizeResponse = Result<RegistrySizeOk>;
export type EvaluateResponse = Result<EvaluateOk>;
export type ChainResponse = Result<ChainOk>;
export type DoseResponse = Result<DoseOk>;
export type DoseLinesResponse = Result<DoseLinesOk>;
export type ReleaseResponse = Result<ReleaseOk>;

// --- the client --------------------------------------------------------------

/** The raw Pyodide module proxy: each member is a `(str, ...) -> str` callable. */
type BridgeModule = Record<string, (...args: string[]) => string>;

export class BridgeClient {
  private readonly mod: BridgeModule;

  constructor(mod: BridgeModule) {
    this.mod = mod;
  }

  private call<T>(fn: string, ...args: string[]): T {
    const raw = this.mod[fn];
    if (typeof raw !== "function") {
      throw new Error(`engine.bridge has no callable ${JSON.stringify(fn)}`);
    }
    const out = raw(...args);
    if (typeof out !== "string") {
      throw new Error(`engine.bridge.${fn} returned ${typeof out}, expected JSON text`);
    }
    return JSON.parse(out) as T;
  }

  /** The add-by-name source for the inventory panel; one fetch, cached by the caller. */
  nuclides(): NuclidesResponse {
    return this.call<NuclidesResponse>("nuclides");
  }

  solve(spec: SolveSpec): SolveResponse {
    return this.call<SolveResponse>("solve", JSON.stringify(spec));
  }

  evaluate(handle: Handle, req: EvaluateRequest): EvaluateResponse {
    return this.call<EvaluateResponse>("evaluate", handle, JSON.stringify(req));
  }

  chain(handle: Handle): ChainResponse {
    return this.call<ChainResponse>("chain", handle);
  }

  dose(handle: Handle, req: DoseRequest): DoseResponse {
    return this.call<DoseResponse>("dose", handle, JSON.stringify(req));
  }

  /** Per-line γ decomposition for the §9 per-line table (M6f-2). Distance/time-free:
   *  the client folds in `1/4πd²` and the cursor activity (no re-fetch on scrub). */
  dose_lines(handle: Handle, req: { quantity?: string; geometry?: string | null; shield?: [string, number] | null; medium?: string }): DoseLinesResponse {
    return this.call<DoseLinesResponse>("dose_lines", handle, JSON.stringify(req));
  }

  beta_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("beta_dose", handle, JSON.stringify(req));
  }

  neutron_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("neutron_dose", handle, JSON.stringify(req));
  }

  release(handle: Handle): ReleaseResponse {
    return this.call<ReleaseResponse>("release", handle);
  }

  /** Live-handle count — the leak canary the gate asserts is 1 across re-solves. */
  registry_size(): RegistrySizeResponse {
    return this.call<RegistrySizeResponse>("registry_size");
  }
}
