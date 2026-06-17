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

export interface SolveSpec {
  nuclides: Record<string, number>;
  /** Bq (default), Ci, atoms, g, kg, ug, ... — see inventory.from_spec. */
  unit?: string;
  precision?: "double" | "hp";
}

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

export interface ChainNode {
  id: string;
  [k: string]: unknown;
}
export interface ChainEdge {
  source: string;
  target: string;
  [k: string]: unknown;
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

export interface ReleaseOk {
  handle: string;
  existed: boolean;
}

export type SolveResponse = Result<SolveOk>;
export type EvaluateResponse = Result<EvaluateOk>;
export type ChainResponse = Result<ChainOk>;
export type DoseResponse = Result<DoseOk>;
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

  beta_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("beta_dose", handle, JSON.stringify(req));
  }

  neutron_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("neutron_dose", handle, JSON.stringify(req));
  }

  release(handle: Handle): ReleaseResponse {
    return this.call<ReleaseResponse>("release", handle);
  }
}
