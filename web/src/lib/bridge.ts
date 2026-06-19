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

/** A shield as the engine's ordered layer list (source-side → detector-side; the last
 *  layer is detector-adjacent). A single layer is `[["lead", 2.0]]`. Always the list
 *  form on the wire — the Python `_normalize_shield` reduces n=1 to the legacy path. */
export type ShieldSpec = [string, number][];

export interface DoseRequest {
  times_s: number[];
  quantity?: string; // "air_kerma" | "ambient_H10" | "effective"
  distance_m: number;
  shield?: ShieldSpec | null;
  medium?: string;
  geometry?: string | null;
}

/** Distance/time-free per-nuclide γ coefficients over a thickness grid (M6g dose-vs-
 *  thickness, Design-A). Two forms (M8): single-layer `{material}` (legacy; `x=0` is the
 *  exact unshielded baseline) or multi-layer `{layers, sweep_index}` — sweep that layer's
 *  thickness with the OTHERS held (then `x=0` is the rest-of-stack, not unshielded). The
 *  client folds `1/4πd²` and the cursor activity at every grid point (zero re-fetch). */
export interface DoseThicknessRequest {
  material?: string;
  layers?: ShieldSpec;
  sweep_index?: number;
  thicknesses_cm: number[];
  quantity?: string;
  geometry?: string | null;
  medium?: string;
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
  /** β skin-dose responses only (M6g): the secondary bremsstrahlung γ-dose series scored
   *  when a shield stops the β ("more lead → more photon dose"). null when no shield. A
   *  γ (Sv/air-kerma) quantity — shown beside, NEVER summed into, the β skin (Gy) number. */
  bremsstrahlung?: DoseOk | null;
  /** neutron_dose responses only (M7d): the SOURCE-correlated reaction γ-dose series (e.g.
   *  AmBe 4.438 MeV, scored through the γ engine in the SAME Sv quantity) — null for Cf-252
   *  (prompt-fission γ continuum unmodeled, §11). A γ contribution that DOES stack into the
   *  Sv total, but is kept distinct from the inventory's decay-γ lines (it is a reaction γ,
   *  not a decay line). */
  source_gamma?: DoseOk | null;
  /** spent_fuel_neutron_dose responses only (M9): per-time fraction of the SF neutron source
   *  from emitters without an evaluated ν̄ (chiefly Cm-246 at long cooling) — NOT in the dose.
   *  The honest lower-bound gap, surfaced for the UI to show (the dangerous under-count). */
  dropped_sf_frac?: number[];
}

/** One shield material for the M6g picker. `has_buildup` is the γ-shield gate (a material
 *  without ANS-6.4.3 buildup raises in the γ engine; the UI filters the γ picker to it). */
export interface MaterialInfo {
  id: string;
  has_buildup: boolean;
  density_g_cm3: number;
}

export interface MaterialsOk {
  materials: MaterialInfo[];
}

/** The §9 dose-vs-thickness sweep (M6g, Design-A): distance/time-free per-nuclide γ
 *  coefficients `C_n(x)` over `thicknesses_cm`. `x=0` is the exact unshielded baseline.
 *  The client folds `1/4πd²` and the parent activity at the cursor (zero re-fetch). */
export interface DoseThicknessOk {
  quantity: string;
  si_unit: string;
  material: string;
  thicknesses_cm: number[];
  coeff_by_nuclide: Record<string, number[]>;
  warnings: DoseWarning[];
  scoring_floor_MeV: number;
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

/** One §8 spent-fuel catalog source — inventory sourced from validated `data/spent_fuel`. */
export interface SpentFuelSource {
  id: string;
  label: string;
  category: string;
  blurb: string;
  caveat: string | null;
  referenceTimeS: number;
  burnup_GWd_tHM: number;
  enrichment_pct: number;
  /** M9: this vector carries an intrinsic multi-parent SF neutron source (arms the neutron view). */
  hasNeutron: boolean;
  entries: SolveEntry[];
}
export interface SpentFuelCatalogOk {
  sources: SpentFuelSource[];
}

/** One §8 / §13 #5 fallout catalog source — inventory from validated `data/fallout` (ENDF
 *  U-235 cumulative fission yields). Loaded with `unit="atoms"` at t=0 ≈ H+1 h. */
export interface FalloutSource {
  id: string;
  label: string;
  category: string;
  blurb: string;
  caveat: string | null;
  referenceTimeS: number;
  entries: SolveEntry[];
}
export interface FalloutCatalogOk {
  sources: FalloutSource[];
}

/** Decay-heat (thermal power, W) series over a time grid (M7c §5). */
export interface DecayHeatOk {
  quantity: "decay_heat";
  si_unit: "W";
  times_s: number[];
  total_W: number[];
  by_nuclide_W: Record<string, number[]>;
  coeff_W_per_Bq: Record<string, number>;
  E_rec_MeV: Record<string, number>;
  definition: string;
}

export type SolveResponse = Result<SolveOk>;
export type NuclidesResponse = Result<NuclidesOk>;
export type MaterialsResponse = Result<MaterialsOk>;
export type DoseThicknessResponse = Result<DoseThicknessOk>;
export type RegistrySizeResponse = Result<RegistrySizeOk>;
export type EvaluateResponse = Result<EvaluateOk>;
export type ChainResponse = Result<ChainOk>;
export type DoseResponse = Result<DoseOk>;
export type DoseLinesResponse = Result<DoseLinesOk>;
export type ReleaseResponse = Result<ReleaseOk>;
export type SpentFuelCatalogResponse = Result<SpentFuelCatalogOk>;
export type FalloutCatalogResponse = Result<FalloutCatalogOk>;
export type DecayHeatResponse = Result<DecayHeatOk>;

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

  /** The M6g shield-builder material list (id, has_buildup, density); one fetch, cached. */
  materials(): MaterialsResponse {
    return this.call<MaterialsResponse>("materials");
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
  dose_lines(handle: Handle, req: { quantity?: string; geometry?: string | null; shield?: ShieldSpec | null; medium?: string }): DoseLinesResponse {
    return this.call<DoseLinesResponse>("dose_lines", handle, JSON.stringify(req));
  }

  /** The §9 dose-vs-thickness sweep (M6g): per-nuclide γ coefficients over a thickness grid.
   *  Distance/time-free — the client folds `1/4πd²` + cursor activity (no re-fetch on scrub). */
  dose_thickness(handle: Handle, req: DoseThicknessRequest): DoseThicknessResponse {
    return this.call<DoseThicknessResponse>("dose_thickness", handle, JSON.stringify(req));
  }

  beta_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("beta_dose", handle, JSON.stringify(req));
  }

  neutron_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("neutron_dose", handle, JSON.stringify(req));
  }

  /** The §6.3 spent-fuel SF neutron dose (M9) — multi-parent (S(t)=Σ yield_n·A_n(t)); same
   *  DoseOk shape as `neutron_dose`. `req`: {times_s, source_id, quantity, distance_m, geometry}. */
  spent_fuel_neutron_dose(handle: Handle, req: Record<string, unknown>): DoseResponse {
    return this.call<DoseResponse>("spent_fuel_neutron_dose", handle, JSON.stringify(req));
  }

  /** The §8 spent-fuel catalog (inventory from validated `data/spent_fuel`); one fetch,
   *  merged into the source picker by the store. */
  spent_fuel_catalog(): SpentFuelCatalogResponse {
    return this.call<SpentFuelCatalogResponse>("spent_fuel_catalog");
  }

  /** The §8 / §13 #5 fallout catalog (inventory from validated `data/fallout`); one fetch,
   *  merged into the source picker by the store. */
  fallout_catalog(): FalloutCatalogResponse {
    return this.call<FalloutCatalogResponse>("fallout_catalog");
  }

  /** Decay-heat (W) series over a time grid (M7c §5). One evaluate per (inventory ×
   *  source-age); distance/quantity-free (heat is total locally-deposited power). */
  decay_heat(handle: Handle, req: { times_s: number[] }): DecayHeatResponse {
    return this.call<DecayHeatResponse>("decay_heat", handle, JSON.stringify(req));
  }

  release(handle: Handle): ReleaseResponse {
    return this.call<ReleaseResponse>("release", handle);
  }

  /** Live-handle count — the leak canary the gate asserts is 1 across re-solves. */
  registry_size(): RegistrySizeResponse {
    return this.call<RegistrySizeResponse>("registry_size");
  }
}
