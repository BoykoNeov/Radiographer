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
  type ChainOk,
  type DecayHeatOk,
  type DoseLinesOk,
  type DoseOk,
  type DoseThicknessOk,
  type EvaluateOk,
  type Handle,
  type InternalDoseOk,
  type MaterialInfo,
  type ShieldSpec,
  type SolveEntry,
  type SolveOk,
} from "./bridge";
import { SvelteSet } from "svelte/reactivity";
import { geometricFactor, interpAt, trapzWindow, type TrapzResult } from "./dosemath";
import { ColorRegistry } from "./palette";
import type { PrebuiltSource } from "./sources";
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
  DEFAULT_SHIELD_THICKNESS_CM,
  DEFAULT_UNIT,
  type Axis,
  type DoseQuantity,
  type InternalPopulation,
  type InternalRoute,
  type InventoryEntry,
  type Precision,
  type ShieldLayer,
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
  /**
   * Prebuilt NEUTRON source key (M7 / §6.3) — set when a catalog neutron source (Cf-252…)
   * is loaded; null for every user-style inventory. Its presence is the §6.3 GRAY-OUT GATE
   * that lights the neutron dose path (M7b). It is dropped the moment the user HAND-EDITS
   * the inventory (add/remove/update) — a prebuilt source's identity is broken once edited,
   * and dropping it here is the no-silent-error guard against an ORPHANED key calling
   * `neutron_dose` for a parent that is no longer in the inventory (advisor). Set only by
   * `loadSource` and the load path; persisted in v3 (M7b).
   */
  neutronSource = $state<string | null>(null);

  /**
   * Loaded spent-fuel SF neutron source id (M9 / §6.3) — set when a spent-fuel vector with a
   * `neutron` block is loaded. The MULTI-parent neutron path (S(t)=Σ yield_n·A_n(t) off the one
   * solve), distinct from `neutronSource` (a single tabulated key) and MUTUALLY EXCLUSIVE with
   * it. Same gray-out/orphan-guard discipline: dropped on a hand-edit (add/remove) that breaks
   * the prebuilt identity. Persisted in v5.
   */
  spentFuelNeutronId = $state<string | null>(null);

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

  // -- per-species visibility (view-only; shared by the curves + the DAG) ----
  // The set of nuclide ids the user has HIDDEN by clicking a decay-chain node (or
  // "Hide all"). DISPLAY-ONLY: it drops a species' trace from the time-evolution
  // overlay and greys its DAG node — it NEVER reaches a physics path. Dose, chain
  // activity, decay heat, and internal dose are all computed over the FULL closure
  // regardless of what is hidden, so hiding a species changes no number (advisor #2).
  // EPHEMERAL like `axis` (NOT serialized): a fresh inventory starts fully visible.
  // Pruned to the closure on each solve so a hide intent survives a quantity edit but
  // a stale id cannot linger. A SvelteSet so `.has` / `.size` are reactive in views.
  hiddenNuclides = new SvelteSet<string>();

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
  /**
   * Per-line γ decomposition (M6f-2, §9 "the gamma slice expands to a per-line table").
   * DISTANCE- and TIME-free per-decay coefficients fetched once per (quantity, geometry,
   * shield) — the cursor getter `gammaLinesAtCursor` folds in `1/4πd²` and the parent's
   * activity at the cursor, so the table is live on scrub/distance with ZERO bridge calls
   * (Design A; §3). Its rows sum EXACTLY to `gammaRateAtCursor` (one engine assembly path).
   */
  gammaLines = $state<DoseLinesOk | null>(null);
  /** Loud dose-path error (#3) — surfaced, never a silent blank breakdown. */
  doseError = $state<string>("");

  // -- neutron dose (M7b, §6.3) ---------------------------------------------
  // Only computed when `neutronSource != null` (a prebuilt neutron source is loaded —
  // the §6.3 gray-out gate). Same solve-once / cursor-index pattern as γ: one
  // `neutron_dose` evaluate per (source × distance × quantity × geometry) over `curveX`,
  // the cursor indexes it. γ and n are the SAME quantity (both Sv, H*(10)/effective) so
  // they DO sum in the breakdown total (unlike β's Gy) — invariant #5 is γ-vs-β only.
  // M10: the neutron dose responds to the SHARED shield stack via the fast-neutron removal
  // cross-section (T_n = exp(−Σ_R·x), folded into coeff_si — h̄ untouched, no spectrum
  // hardening). A hydrogenous layer (water) attenuates; a γ-oriented layer (lead) is
  // neutron-transparent and the response carries a `no_hydrogenous_layer` warning rather than
  // a silently-low number (§6.3 "steer to hydrogenous"). A neutron failure sets its OWN error
  // and nulls only its series — it never blanks the γ/β breakdown (advisor: orphan guard).
  // `source_gamma` (reaction γ) is null for Cf-252 (prompt-fission γ unmodeled, §11); it lands
  // with AmBe (M7d), folded into the γ total then, and is now shielded by the same stack.
  /** Neutron dose-rate series (Sv/s) over `curveX`; null when no neutron source / stale. */
  neutronDoseSeries = $state<DoseOk | null>(null);
  /** Loud neutron-path error (#3) — its own field so a neutron failure can't blank γ/β. */
  neutronDoseError = $state<string>("");

  // -- neutron dose-vs-thickness explorer (M11, §9) -------------------------
  // A STANDALONE "what if I put X cm of a hydrogenous shield between source and detector"
  // widget for the neutron dose. Independent of the applied γ shield stack (which is γ-oriented
  // / high-Z and neutron-transparent anyway). T_n(x) = exp(−Σ_R·x) is a closed-form scalar, so
  // — like inverse-square distance — the curve is reconstructed CLIENT-SIDE from the cursor's
  // BARE neutron rate and the material's Σ_R (carried on `availableMaterials`, the engine's
  // single source); no bridge sweep, live on scrub. EPHEMERAL (not serialized): a what-if tool.
  /** Selected explorer material id; null ⇒ default (water, then first removal material). */
  neutronSweepMaterial = $state<string | null>(null);
  /** Selected explorer thickness (cm) — drives the readout + the marker line. */
  neutronSweepThicknessCm = $state<number>(10);

  // -- shield builder (M6g + M8 multi-layer, §9, §13 #2) --------------------
  // A shield is an ORDERED STACK of layers (source-side → detector-side; the LAST layer is
  // detector-adjacent). A shield change is a pure EVALUATE off the live handle (re-fold the
  // per-decay coefficients through the stack transmission) — NEVER a re-solve (#1). When a
  // shield is active the whole γ dose path (series, dose_lines) is recomputed THROUGH the
  // full stack, plus an UNSHIELDED γ baseline (the at-cursor attenuation factor, M6g #5),
  // the dose-vs-thickness grid (M6g #4, sweeping the detector-side layer), and — for ≥2
  // distinct-material layers — a REVERSED-order γ series whose spread quantifies the
  // last-layer-buildup approximation's order sensitivity (M8 honesty, §11). β is a contact
  // hazard stopped in the SOURCE-SIDE layer, so β/bremsstrahlung use the first layer only.
  // Thickness is CENTIMETRES (§12). See docs/plans/M8-multilayer-shields.md, M6g-shield.md.
  /** The shield stack, ordered source-side → detector-side. Empty ⇒ no shield. */
  shieldLayers = $state<ShieldLayer[]>([]);
  /** The shield material list for the picker (id, has_buildup, density); fetched once. */
  availableMaterials = $state<MaterialInfo[]>([]);
  /** UNSHIELDED γ dose-rate series (Sv/s) — the baseline for the at-cursor attenuation
   *  factor; null when no shield is active (factor is then 1). */
  gammaDoseSeriesBare = $state<DoseOk | null>(null);
  /** γ dose-rate series (Sv/s) through the shield with the layer order REVERSED — only
   *  computed for ≥2 distinct-material layers; the normal-vs-reversed spread is the M8
   *  order-sensitivity band of the last-layer buildup approximation (§11). Null otherwise. */
  gammaDoseSeriesReversed = $state<DoseOk | null>(null);
  /** Secondary β-bremsstrahlung γ-dose series (the "more lead → more dose" effect); null
   *  when no shield, no finite distance, or no β converting to photons. A γ (Sv) quantity. */
  bremsSeries = $state<DoseOk | null>(null);
  /** Dose-vs-thickness γ coefficient grid (Design-A, M6g #4): distance/time-free per-nuclide
   *  C_n(x) over a thickness sweep; the cursor getter folds 1/4πd² + activity (zero re-fetch). */
  gammaThicknessCoeffs = $state<DoseThicknessOk | null>(null);

  // -- chain view (M6e, §8/§9) ----------------------------------------------
  // The decay-chain DAG. Topology (`chainDag`: nodes+edges) is TIME-INDEPENDENT —
  // it changes only with the inventory, so it is fetched once per solve (never on a
  // source-age / cursor change). The LIVE node encoding is driven by ACTIVITY at the
  // cursor: a dedicated `chainActivity` rate-series (axis=activity, Bq) over the SAME
  // `curveX` display grid (evaluated at `referenceTimeS + curveX`, the M6d offset), so
  // the cursor INDEXES it 1:1 with the curves/dose (zero bridge calls on scrub, §3).
  // It is its OWN series — NOT the display `curve`, which the Atoms/Mass toggle would
  // otherwise break: the DAG always wants activity regardless of the curve axis (§5).
  // Recompute triggers = solve + source-age only (NOT setAxis); see docs/plans/M6e-chain.md.
  chainDag = $state<ChainOk | null>(null);
  /** Activity (Bq) rate-series over `curveX` driving the live node encoding. */
  chainActivity = $state<EvaluateOk | null>(null);
  /** Loud chain-path error (#3) — surfaced, never a silently blank graph. */
  chainError = $state<string>("");

  /** Overlay grid density (log-spaced). HP is sympy-per-point → keep it responsive. */
  private readonly CURVE_POINTS = 300;
  private readonly CURVE_POINTS_HP = 60;

  // -- decay heat (M7c, §5) -------------------------------------------------
  // Thermal power W(t) = Σ A_n(t)·Ē_rec,n, folded from the SAME bundled ICRP-107 emission
  // spectra as γ/β (no new dataset). DISTANCE- and quantity-free (heat is total locally-
  // deposited power, not a point-field quantity), so it recomputes on solve + source-age
  // ONLY — not on distance/quantity/shield. Same solve-once/cursor-index pattern as dose:
  // one evaluate over `curveX`, the cursor getter indexes it. Most meaningful for spent
  // fuel (cooling drops it orders of magnitude), but defined for any inventory.
  /** Decay-heat (W) series over `curveX`; null when empty/stale/failed. */
  decayHeatSeries = $state<DecayHeatOk | null>(null);
  /** Loud decay-heat-path error (#3) — surfaced, never a silent blank readout. */
  decayHeatError = $state<string>("");

  // -- internal / committed dose (M13 §M13) ---------------------------------
  // The INTAKE pathway: committed E(50) = Σ e_n[Sv/Bq]·A_n(t), the §3 solve-once/evaluate-many
  // way (one matvec of the fixed per-nuclide coefficients against the activity series). DISTANCE-,
  // geometry-, and shield-FREE (committed dose folds biokinetics, not a point field), so it
  // recomputes on solve + source-age + route + population ONLY — like decay heat, plus the two
  // route/population selectors. The result is a committed SCALAR Sv at each intake-time (NOT a
  // rate), so the cursor INDEXES `committed_si` and there is NO integrate (per is null). Effective
  // Sv but NEVER summed with external H*(10)/air-kerma (§6.4, §11). route/population are EPHEMERAL
  // view state (not serialized) — a cheap re-pick, no serializer bump; the panel labels the active
  // scenario. See docs/plans/M13-internal-dose.md.
  /** Intake route — ingestion (default) | inhalation. A re-fold, never a re-solve (#1). */
  internalRoute = $state<InternalRoute>("ingestion");
  /** Reference population — public-adult (ICRP-72, 1 µm, default) | worker (ICRP-68, 5 µm). */
  internalPopulation = $state<InternalPopulation>("public_adult");
  /** Committed E(50) series (Sv) over `curveX`; null when empty/stale/failed/all-stable. */
  internalDoseSeries = $state<InternalDoseOk | null>(null);
  /** Loud internal-dose-path error (#3) — surfaced, never a silent blank readout. */
  internalDoseError = $state<string>("");

  // -- spent-fuel catalog (fetched once after boot, M7c §8) -----------------
  // Prebuilt spent-fuel sources whose inventory comes from validated `data/spent_fuel`
  // discharge vectors (not the static `sources.ts` manifest). Merged into the picker.
  spentFuelSources = $state<PrebuiltSource[]>([]);

  // -- fallout catalog (fetched once after boot, M7d §13 #5) ----------------
  // Prebuilt fission-product fallout source(s) whose inventory comes from the validated
  // `data/fallout` vector (ENDF/B-VIII.0 U-235 cumulative yields). Merged into the picker.
  falloutSources = $state<PrebuiltSource[]>([]);

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

  // -- neutron at the cursor (M7b; same Sv quantity as γ — these DO sum) -----
  /** n dose-RATE (Sv/s) at the cursor; null when no neutron source/series. */
  get neutronRateAtCursor(): number | null {
    const s = this.neutronDoseSeries;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }
  /** n ACCUMULATED dose (Sv) over [cursor, cursor+exposure] — ∫rate dt (#2, §11). */
  get neutronAccumulated(): TrapzResult | null {
    const s = this.neutronDoseSeries;
    if (!s) return null;
    return trapzWindow(this.curveX, s.rate_si, this.cursorOffsetS, this.cursorOffsetS + this.exposureS);
  }
  /** M9/M12: fraction of the spent-fuel neutron source UNMODELED at the cursor — minor SF
   *  emitters without an evaluated ν̄ (chiefly Cm-246 at long cooling) PLUS α-emitters absent
   *  from the PANDA (α,n) table. The honest residual (under-count) gap. null unless a spent-fuel
   *  multi-parent source is active (single tabulated sources carry no dropped fraction). */
  get neutronDroppedFracAtCursor(): number | null {
    const s = this.neutronDoseSeries;
    const frac = s?.dropped_frac ?? s?.dropped_sf_frac;
    if (!s || !frac) return null;
    return interpAt(this.curveX, frac, this.cursorOffsetS);
  }
  /** M12: the (α,n)-on-oxygen SHARE of the modeled spent-fuel neutron dose at the cursor (0..1):
   *  rate_si_alpha_n / rate_si. null unless the split is present (spent-fuel source). Lets the
   *  UI show that the source is SF + (α,n), and how the (α,n) share grows as Am-241 ingrows. */
  get neutronAlphaNFracAtCursor(): number | null {
    const s = this.neutronDoseSeries;
    if (!s || !s.rate_si_alpha_n) return null;
    const tot = interpAt(this.curveX, s.rate_si, this.cursorOffsetS);
    const an = interpAt(this.curveX, s.rate_si_alpha_n, this.cursorOffsetS);
    return tot && tot > 0 && an != null ? an / tot : null;
  }

  /** M10: the fast-neutron shield transmission T_n = exp(−Σ_R·x) applied to the neutron dose;
   *  null when no neutron series. 1.0 means the shield did NOT attenuate neutrons (no shield,
   *  or a γ-oriented stack with no hydrogenous layer — see {@link neutronShieldTransparent}). */
  get neutronTransmission(): number | null {
    const t = this.neutronDoseSeries?.neutron_transmission;
    return typeof t === "number" ? t : null;
  }
  /** M10: a shield is active but contains NO hydrogenous layer, so it does not attenuate the
   *  neutron dose (T_n=1) — the §6.3 "steer neutron to a hydrogenous shield" teaching point.
   *  Driven off the engine warning, never inferred client-side. */
  get neutronShieldTransparent(): boolean {
    return (this.neutronDoseSeries?.warnings ?? []).some((w) => w.reason === "no_hydrogenous_layer");
  }
  /** M10: a mixed hydrogenous + γ-oriented stack — removal theory does not model layer order
   *  (a heavy layer placed last may over-state the true neutron attenuation). §11 caveat. */
  get neutronShieldCompositeOrder(): boolean {
    return (this.neutronDoseSeries?.warnings ?? []).some((w) => w.reason === "composite_order_unmodeled");
  }

  // -- neutron dose-vs-thickness explorer (M11, §9) -------------------------
  /** Hydrogenous neutron-shield materials for the explorer picker: every material with a removal
   *  cross-section Σ_R. DISTINCT from the γ shield picker (`has_buildup`) — fast neutrons are
   *  removed by hydrogen (water, paraffin, polyethylene, concrete), not by high-Z γ shields. */
  get neutronSweepMaterials(): MaterialInfo[] {
    return this.availableMaterials.filter((m) => m.has_removal && m.sigma_r_cm1 != null);
  }
  /** The effective explorer material id — the explicit choice, else water, else first removal. */
  get neutronSweepMaterialId(): string | null {
    const mats = this.neutronSweepMaterials;
    if (this.neutronSweepMaterial && mats.some((m) => m.id === this.neutronSweepMaterial)) {
      return this.neutronSweepMaterial;
    }
    return mats.find((m) => m.id === "water")?.id ?? mats[0]?.id ?? null;
  }
  /** Σ_R (cm⁻¹) of the selected explorer material (the engine's value, not recomputed). */
  get neutronSweepSigmaR(): number | null {
    const id = this.neutronSweepMaterialId;
    return this.neutronSweepMaterials.find((m) => m.id === id)?.sigma_r_cm1 ?? null;
  }
  /** Neutron dose RATE (Sv/s) at the cursor with NO neutron shield — the explorer's x=0 baseline.
   *  Divides out any shared-stack T_n so the curve shows the STANDALONE effect of the explorer's
   *  own material, not stacked on the applied γ shield. null when no neutron series. */
  get neutronBareRateAtCursor(): number | null {
    const r = this.neutronRateAtCursor;
    if (r == null) return null;
    const t = this.neutronTransmission;
    return t != null && t > 0 ? r / t : r;
  }
  /** Neutron dose-vs-thickness curve (Sv/s) for the selected material, computed CLIENT-SIDE from
   *  the closed-form T_n(x) = exp(−Σ_R·x): bareRate·exp(−Σ_R·x) over 0…5 relaxation lengths.
   *  null when no neutron series or the chosen material has no Σ_R. */
  get neutronThicknessCurve():
    | { material: string; sigma_r_cm1: number; thicknesses_cm: number[]; rate_si: number[] }
    | null {
    const sigma = this.neutronSweepSigmaR;
    const id = this.neutronSweepMaterialId;
    const bare = this.neutronBareRateAtCursor;
    if (sigma == null || id == null || bare == null) return null;
    const xMax = 5.0 / sigma; // 5 relaxation lengths → T_n ≈ 0.0067 (covers the useful range)
    const N = 60;
    const thicknesses_cm: number[] = [];
    const rate_si: number[] = [];
    for (let i = 0; i <= N; i++) {
      const x = (xMax * i) / N;
      thicknesses_cm.push(x);
      rate_si.push(bare * Math.exp(-sigma * x));
    }
    return { material: id, sigma_r_cm1: sigma, thicknesses_cm, rate_si };
  }
  /** Neutron dose RATE (Sv/s) at the explorer's selected thickness — the readout value. */
  get neutronRateAtSweepThickness(): number | null {
    const sigma = this.neutronSweepSigmaR;
    const bare = this.neutronBareRateAtCursor;
    if (sigma == null || bare == null) return null;
    return bare * Math.exp(-sigma * this.neutronSweepThicknessCm);
  }
  /** Setters for the explorer controls (pure UI state; no solve, no fetch). */
  setNeutronSweepMaterial(id: string): void {
    this.neutronSweepMaterial = id;
  }
  setNeutronSweepThicknessCm(x: number): void {
    if (Number.isFinite(x) && x >= 0) this.neutronSweepThicknessCm = x;
  }

  // -- source-correlated reaction γ (M7d; e.g. AmBe 4.438 MeV) ---------------
  // A neutron source can carry a reaction γ (NOT in the ICRP-107 decay lines) — scored through
  // the γ engine in the SAME Sv quantity/geometry and returned on `neutronDoseSeries.source_gamma`
  // (null for Cf-252, §11). It is a γ contribution that DOES sum into the Sv total, but is kept
  // DISTINCT from the inventory's decay-γ (`gammaDoseSeries`) so the per-line decay table's
  // Σ==card invariant holds; in the breakdown it stacks as its own labeled segment.
  /** Reaction-γ dose-RATE (Sv/s) at the cursor; null when no source / no modeled reaction γ. */
  get sourceGammaRateAtCursor(): number | null {
    const sg = this.neutronDoseSeries?.source_gamma;
    return sg ? interpAt(this.curveX, sg.rate_si, this.cursorOffsetS) : null;
  }
  /** Reaction-γ ACCUMULATED dose (Sv) over [cursor, cursor+exposure] — ∫rate dt (#2, §11). */
  get sourceGammaAccumulated(): TrapzResult | null {
    const sg = this.neutronDoseSeries?.source_gamma;
    if (!sg) return null;
    return trapzWindow(this.curveX, sg.rate_si, this.cursorOffsetS, this.cursorOffsetS + this.exposureS);
  }

  // -- shield (M6g single-layer + M8 multi-layer) ---------------------------

  /** The ACTIVE layers (material set AND thickness > 0), source-side → detector-side. */
  get activeShieldLayers(): ShieldLayer[] {
    return this.shieldLayers.filter((l) => l.material && l.thicknessCm > 0);
  }
  /** The active shield as the engine's ordered layer list `[[material, cm], …]`, or null
   *  when no layer is active (then the γ dose path runs unshielded). */
  get shield(): ShieldSpec | null {
    const layers = this.activeShieldLayers.map((l) => [l.material, l.thicknessCm] as [string, number]);
    return layers.length ? layers : null;
  }
  /** The shield as the β engine sees it: the SOURCE-SIDE (first) active layer only. Betas
   *  stop in the first absorber they hit; bremsstrahlung is generated there (additional γ
   *  layers behind it don't change the skin β dose). Single `[material, cm]` tuple | null. */
  get betaShield(): [string, number] | null {
    const first = this.activeShieldLayers[0];
    return first ? [first.material, first.thicknessCm] : null;
  }
  /** True while a shield is actually attenuating (≥1 active layer). */
  get shieldActive(): boolean {
    return this.shield !== null;
  }
  /** Human label for the active stack, source-side → detector-side (e.g. "Lead 2 cm →
   *  Water 5 cm"). Empty string when no shield is active. */
  get shieldStackLabel(): string {
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
    return this.activeShieldLayers.map((l) => `${cap(l.material)} ${l.thicknessCm} cm`).join(" → ");
  }

  // -- single-layer COMPATIBILITY shims (M6g API kept for the driver + simple flows) ------
  // The store now models a stack; these expose the first layer as the old scalar pair so
  // existing single-layer callers (the M6g/M6h driver checks, a one-click shield) keep
  // working unchanged. The DETECTOR-side thickness drives the dose-vs-thickness sweep.

  /** First layer's material id, or null when the stack is empty (legacy `shieldMaterial`). */
  get shieldMaterial(): string | null {
    return this.shieldLayers[0]?.material ?? null;
  }
  /** The DETECTOR-side (last) active layer's thickness in cm — the layer the dose-vs-
   *  thickness band sweeps. 0 when no shield is active. (Legacy `shieldThicknessCm`.) */
  get shieldThicknessCm(): number {
    const active = this.activeShieldLayers;
    return active.length ? active[active.length - 1].thicknessCm : (this.shieldLayers[0]?.thicknessCm ?? 0);
  }

  /** UNSHIELDED γ dose-RATE (Sv/s) at the cursor — the attenuation-factor baseline. Falls
   *  back to the (then-unshielded) main γ series when no shield is active. */
  get gammaRateBareAtCursor(): number | null {
    const s = this.gammaDoseSeriesBare ?? this.gammaDoseSeries;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }
  /** γ transmission factor (shielded / unshielded) AT THE CURSOR — a spectrum- and
   *  time-dependent ratio, NOT a constant μx (M6g #5). 1 when no shield; null when the
   *  rates are unavailable. */
  get attenuationFactorAtCursor(): number | null {
    if (!this.shieldActive) return 1;
    const sh = this.gammaRateAtCursor;
    const bare = this.gammaRateBareAtCursor;
    if (sh == null || bare == null || !(bare > 0)) return null;
    return sh / bare;
  }
  /** Secondary β-bremsstrahlung γ dose-RATE (Sv/s) at the cursor; null when no brems series. */
  get bremsRateAtCursor(): number | null {
    const s = this.bremsSeries;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }

  /** γ dose-RATE (Sv/s) at the cursor with the layer order REVERSED; null unless a reversed
   *  series exists (≥2 distinct-material layers). The honest twin of `gammaRateAtCursor`. */
  get gammaRateReversedAtCursor(): number | null {
    const s = this.gammaDoseSeriesReversed;
    return s ? interpAt(this.curveX, s.rate_si, this.cursorOffsetS) : null;
  }
  /** **Layer-order sensitivity** of the last-layer buildup approximation (M8, §11): the
   *  fractional spread between the chosen order and its reverse at the cursor,
   *  `|γ − γ_reversed| / γ`. Same Σμx, different buildup material → this IS the built-in
   *  uncertainty of layered buildup (the approximation errs both ways; §6.4). Null unless a
   *  reversed series exists (needs ≥2 distinct-material layers). */
  get orderSensitivityAtCursor(): number | null {
    const g = this.gammaRateAtCursor;
    const gr = this.gammaRateReversedAtCursor;
    if (g == null || gr == null || !(g > 0)) return null;
    return Math.abs(g - gr) / g;
  }

  /**
   * The §9 dose-vs-thickness curve at the cursor: γ dose RATE (Sv/s) vs shield thickness,
   * `rate(x) = 1/4πd² · Σ_n C_n(x) · A_n(cursor)` — the engine's distance/time-free
   * per-thickness coefficients (`gammaThicknessCoeffs`) folded with the activity at the
   * cursor (`activityAtCursor`) and the current distance, all client-side (Design A; zero
   * bridge calls on scrub/distance, M6g #4). The selected thickness is a grid point, so the
   * curve's value there equals `gammaRateAtCursor` exactly (one engine assembly path).
   *
   * Null when there is no coefficient grid OR the per-nuclide activity is unavailable — the
   * renderer shows a note, never a fabricated/blank curve (the §11 activity-coupling guard,
   * shared with the per-line table).
   */
  get gammaThicknessCurve(): { thicknesses_cm: number[]; rate_si: number[] } | null {
    const tc = this.gammaThicknessCoeffs;
    if (!tc) return null;
    const act = this.activityAtCursor;
    if (!act) return null;
    const geom = geometricFactor(this.doseDistanceM);
    const rate_si = tc.thicknesses_cm.map((_x, i) => {
      let sum = 0;
      for (const n of Object.keys(tc.coeff_by_nuclide)) {
        sum += tc.coeff_by_nuclide[n][i] * (act[n] ?? 0);
      }
      return geom * sum;
    });
    return { thicknesses_cm: tc.thicknesses_cm, rate_si };
  }

  /**
   * The §9 per-line γ table at the cursor: each scored line's dose RATE (Sv/s) =
   * `1/4πd² · coeff_si · A_n(cursor)` — the engine's distance-free per-decay coefficient
   * (`gammaLines`) folded with the parent's activity at the cursor (`activityAtCursor`) and
   * the current distance, all client-side (Design A; zero bridge calls on scrub/distance).
   * Rows are sorted by descending contribution with `frac` of the γ total; `Σ rate_si`
   * equals `gammaRateAtCursor` exactly (one engine assembly path, linear interp commutes).
   *
   * Returns null when there is no decomposition (`gammaLines` null) OR the per-nuclide
   * activity is unavailable (`activityAtCursor` null) — the renderer shows a note rather
   * than a blank or fabricated table (the activity coupling is an honest §11 guard, not a
   * silent empty). The SF pseudo-sink / missing keys read as zero activity (no crash).
   */
  get gammaLinesAtCursor(): {
    rows: { nuclide: string; E_MeV: number; yield: number; origin: string | null; rate_si: number; frac: number }[];
    total: number;
  } | null {
    const dl = this.gammaLines;
    if (!dl) return null;
    const act = this.activityAtCursor;
    if (!act) return null; // activity unavailable — caller shows a note, never a blank table
    const geom = geometricFactor(this.doseDistanceM);
    const rows = dl.lines.map((ln) => ({
      nuclide: ln.nuclide,
      E_MeV: ln.E_MeV,
      yield: ln.yield,
      origin: ln.origin,
      rate_si: geom * ln.coeff_si * (act[ln.nuclide] ?? 0),
      frac: 0,
    }));
    const total = rows.reduce((s, r) => s + r.rate_si, 0);
    if (total > 0) for (const r of rows) r.frac = r.rate_si / total;
    rows.sort((a, b) => b.rate_si - a.rate_si);
    return { rows, total };
  }

  // -- decay heat at the cursor (M7c; pure client-side index, #1/§3) ---------
  /** Total decay heat (W) at the cursor; null when no series. */
  get decayHeatAtCursor(): number | null {
    const s = this.decayHeatSeries;
    return s ? interpAt(this.curveX, s.total_W, this.cursorOffsetS) : null;
  }
  /** Top per-nuclide decay-heat contributors at the cursor (W, descending) — the §5/§9
   *  "dominant contributor" view. Reads the per-nuclide series at the cursor, no bridge call. */
  get decayHeatTopAtCursor(): { nuclide: string; W: number; frac: number }[] | null {
    const s = this.decayHeatSeries;
    if (!s) return null;
    const total = this.decayHeatAtCursor ?? 0;
    const rows = Object.keys(s.by_nuclide_W).map((n) => ({
      nuclide: n,
      W: interpAt(this.curveX, s.by_nuclide_W[n], this.cursorOffsetS) ?? 0,
      frac: 0,
    }));
    if (total > 0) for (const r of rows) r.frac = r.W / total;
    rows.sort((a, b) => b.W - a.W);
    return rows.filter((r) => r.W > 0);
  }

  // -- per-node activity at the cursor (drives the live DAG encoding, M6e) -----
  /**
   * `{nuclide: activity_Bq}` at the cursor — the `chainActivity` series indexed at
   * `cursorOffsetS` (display time) via `interpAt`, the same 1:1 cursor read the dose
   * getters use. Null when there is no activity series (empty/failed/all-stable).
   * Nuclides absent from the series (the SF sink) are simply omitted → the renderer
   * treats a missing key as zero activity (fade, never crash; advisor #4).
   */
  get activityAtCursor(): Record<string, number> | null {
    const s = this.chainActivity;
    if (!s) return null;
    const out: Record<string, number> = {};
    for (const n of s.nuclides) {
      const v = interpAt(this.curveX, s.series[n] ?? [], this.cursorOffsetS);
      out[n] = v ?? 0;
    }
    return out;
  }

  // -- internal / committed dose at the cursor (M13; pure client-side, #1/§3) ----
  // The headline reads the AUTHORITATIVE `committed_si` series at the cursor (survives a null
  // activity series); the breakdown folds `per_nuclide_coeff·A_n(cursor)`. interp commutes with
  // the linear matvec (the series IS that matvec over the same activity grid), so the breakdown
  // total reconciles with the headline to float — exactly like gammaLinesAtCursor ↔ gammaRateAtCursor.

  /** Committed E(50) (Sv, a SCALAR — not a rate) at the cursor; null when no series. */
  get internalCommittedAtCursor(): number | null {
    const s = this.internalDoseSeries;
    return s ? interpAt(this.curveX, s.committed_si, this.cursorOffsetS) : null;
  }

  /**
   * Per-nuclide committed-dose breakdown at the cursor (M13): each contributing nuclide's
   * committed Sv = `e_n·A_n(cursor)`, folded client-side off `per_nuclide_coeff` and the
   * activity at the cursor (zero re-fetch on scrub, §3). Rows carry the folded absorption
   * type/form + f1 provenance (from `types_used`/`forms_used`/`f1_used`) so the panel shows
   * WHICH coefficient was used. Sorted by descending contribution; `Σ committed_si` reconciles
   * with `internalCommittedAtCursor`. Null when there is no series OR the per-nuclide activity
   * is unavailable — the panel shows a note, never a fabricated/blank table (§11).
   */
  get internalBreakdownAtCursor(): {
    rows: { nuclide: string; coeff: number; activity: number; committed_si: number; type: string | null; form: string | null; f1: number | null; frac: number }[];
    total: number;
  } | null {
    const s = this.internalDoseSeries;
    if (!s) return null;
    const act = this.activityAtCursor;
    if (!act) return null; // activity unavailable — caller shows a note, never a blank table
    const rows = Object.entries(s.per_nuclide_coeff).map(([nuclide, coeff]) => {
      const activity = act[nuclide] ?? 0;
      return {
        nuclide,
        coeff,
        activity,
        committed_si: coeff * activity,
        type: s.types_used[nuclide] ?? null, // inhalation F/M/S or vapour form
        form: s.forms_used[nuclide] ?? null, // ingestion chemical form (H-3 HTO/OBT)
        f1: s.f1_used[nuclide] ?? null, // ingestion gut-transfer fraction
        frac: 0,
      };
    });
    const total = rows.reduce((sum, r) => sum + r.committed_si, 0);
    if (total > 0) for (const r of rows) r.frac = r.committed_si / total;
    rows.sort((a, b) => b.committed_si - a.committed_si);
    return { rows, total };
  }

  /**
   * The uncovered nuclides that ACTUALLY CARRY ACTIVITY at the cursor, with their activity share
   * (0..1) of the tracked inventory — the genuine curated-set gap that makes E(50) a lower bound.
   *
   * The engine's `series.lower_bound` flags EVERY uncovered closure nuclide, including STABLE
   * end-products (Pb-206 at the end of the Po-210 chain, Ba-137 after Cs-137, …): a stable nuclide
   * has zero activity ⇒ zero possible committed dose ⇒ it is NOT a real gap, just chain topology.
   * The plan's `uncovered` is explicitly "tracked nuclides with NONZERO activity but no
   * coefficient" (docs/plans/M13-internal-dose.md, Engine §) — the activity filter lives here,
   * where the activity series exists. Without it the lower-bound banner would fire for essentially
   * every chain (all end in a stable nuclide) and become meaningless noise.
   *
   * Null when there is no series, no uncovered nuclides, activity is unavailable, OR every
   * uncovered nuclide is zero-activity (then the committed value is complete for this intake time).
   */
  get internalActiveUncoveredAtCursor(): { nuclides: string[]; share: number } | null {
    const s = this.internalDoseSeries;
    if (!s || s.uncovered.length === 0) return null;
    const act = this.activityAtCursor;
    if (!act) return null;
    let total = 0;
    for (const a of Object.values(act)) total += a;
    const active = s.uncovered
      .map((n) => ({ n, a: act[n] ?? 0 }))
      .filter((x) => x.a > 0)
      .sort((x, y) => y.a - x.a);
    if (active.length === 0) return null; // all uncovered nuclides are stable / zero-activity
    const uncoveredA = active.reduce((sum, x) => sum + x.a, 0);
    return { nuclides: active.map((x) => x.n), share: total > 0 ? uncoveredA / total : 0 };
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
    // The M6g shield material list (id, has_buildup, density). One fetch, cached here.
    const mats = client.materials();
    if (mats.ok) {
      this.availableMaterials = mats.materials;
    } else {
      this.errorMsg = `could not load material list: ${mats.error.type}: ${mats.error.message}`;
    }
    // The §8 spent-fuel catalog (inventory from validated data/spent_fuel). Don't hard-fail
    // boot if it's absent — the rest of the app still works; surface the gap (#3).
    const sf = client.spent_fuel_catalog();
    if (sf.ok) {
      this.spentFuelSources = sf.sources.map((s) => ({
        id: s.id,
        label: s.label,
        category: s.category,
        blurb: s.blurb,
        entries: s.entries.map((e) => ({ name: e.name, quantity: e.quantity, unit: e.unit })),
        referenceTimeS: s.referenceTimeS,
        // M9: a spent-fuel vector carries an intrinsic multi-parent SF neutron source.
        spentFuelNeutronId: s.hasNeutron ? s.id : undefined,
        caveat: s.caveat ?? undefined,
      }));
    } else {
      this.errorMsg = `could not load spent-fuel catalog: ${sf.error.type}: ${sf.error.message}`;
    }
    // The §13 #5 fallout catalog (inventory from validated data/fallout). Same soft-fail policy.
    const fo = client.fallout_catalog();
    if (fo.ok) {
      this.falloutSources = fo.sources.map((s) => ({
        id: s.id,
        label: s.label,
        category: s.category,
        blurb: s.blurb,
        entries: s.entries.map((e) => ({ name: e.name, quantity: e.quantity, unit: e.unit })),
        referenceTimeS: s.referenceTimeS,
        caveat: s.caveat ?? undefined,
      }));
    } else {
      this.errorMsg = `could not load fallout catalog: ${fo.error.type}: ${fo.error.message}`;
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
    this.neutronSource = null; // a hand-edited inventory is no longer a prebuilt source (orphan guard)
    this.spentFuelNeutronId = null; // M9: same guard for the spent-fuel multi-parent source
    await this.solve();
    return null;
  }

  async removeEntry(index: number): Promise<void> {
    if (index < 0 || index >= this.entries.length) return;
    this.entries = this.entries.filter((_, i) => i !== index);
    this.neutronSource = null; // hand-edit drops the prebuilt-source identity (orphan guard, M7)
    this.spentFuelNeutronId = null; // M9: same guard for the spent-fuel multi-parent source
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
    // NOTE: a quantity/unit edit does NOT drop `neutronSource` (unlike add/remove). `updateEntry`
    // cannot change a nuclide's NAME, so the source's parent stays in the inventory — and the
    // neutron dose RIDES that parent's activity (S(t)=n_per_decay·A_parent(t), M5/§6.3), so a
    // strength change must RESCALE neutron, not kill it (advisor). The add/remove guards still
    // cover the only edits that can orphan the parent; the loud `neutronDoseError` is the backstop.
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
    this.recomputeChainActivity(); // and the DAG activity series (topology unchanged, #1)
    this.recomputeDecayHeat(); // and the decay-heat series at the shifted times (#1)
    this.recomputeInternalDose(); // and the committed-dose series at the shifted intake-times (#1)
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

  // -- per-species visibility (view-only; #2 display-only, never a physics path) ----
  // No recompute/re-evaluate: hiding only filters the rendered curves traces and greys
  // the DAG node; the curves/DAG effects re-run off `hiddenNuclides` reactively.

  /** Toggle a species' visibility (curves trace + DAG node). A toggle so a greyed node
   *  un-hides on a second click — the "Hide all, then click the few I want" flow. */
  toggleHidden(nuclide: string): void {
    if (this.hiddenNuclides.has(nuclide)) this.hiddenNuclides.delete(nuclide);
    else this.hiddenNuclides.add(nuclide);
  }

  /** Hide every species in the current closure (the "Hide all" button). */
  hideAll(): void {
    for (const n of this.closure) this.hiddenNuclides.add(n);
  }

  /** Show every species (the "Show all" button). */
  showAll(): void {
    this.hiddenNuclides.clear();
  }

  /** Keep only hidden ids that still exist in `closure` — drops stale ids after a
   *  re-solve while preserving a hide intent across a quantity edit (#2 display-only). */
  private pruneHidden(closure: string[]): void {
    if (this.hiddenNuclides.size === 0) return;
    const keep = new Set(closure);
    for (const id of [...this.hiddenNuclides]) if (!keep.has(id)) this.hiddenNuclides.delete(id);
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

  // -- internal-dose inputs (each RE-FOLDS the committed series, never re-solves; #1) ----
  // Route/population change which fixed per-nuclide e_n vector is folded — a pure re-evaluate
  // off the live handle (the gate asserts the registry stays 1 across a toggle), never a re-solve.

  setInternalRoute(r: InternalRoute): void {
    if (r === this.internalRoute) return;
    this.internalRoute = r;
    this.recomputeInternalDose();
  }

  setInternalPopulation(p: InternalPopulation): void {
    if (p === this.internalPopulation) return;
    this.internalPopulation = p;
    this.recomputeInternalDose();
  }

  // -- shield inputs (each RE-EVALUATES the dose path through the shield; #1) -------
  // A shield is a re-fold of the per-decay coefficients through the transmission factor —
  // a pure evaluate off the live handle, NEVER a re-solve (gate: registry stays 1).

  // -- multi-layer stack API (M8) -------------------------------------------
  // Every mutation is a pure re-evaluate of the dose path through the new stack (#1).
  // Each layer's material must be a `has_buildup` id (the picker enforces it; the engine
  // fails loud as the backstop). Order is load-bearing — the LAST layer is detector-side.

  /** Append a layer (defaults: the first buildup material, the default thickness). */
  addShieldLayer(material?: string): void {
    const id = material ?? this.availableMaterials.find((m) => m.has_buildup && m.id !== "air")?.id ?? null;
    if (!id) return; // no buildup materials loaded yet — nothing to add
    this.shieldLayers = [...this.shieldLayers, { material: id, thicknessCm: DEFAULT_SHIELD_THICKNESS_CM }];
    this.recomputeDose();
  }

  /** Set layer `i`'s material (a `has_buildup` id). No-op on an out-of-range index. */
  setShieldLayerMaterial(i: number, material: string): void {
    if (i < 0 || i >= this.shieldLayers.length || this.shieldLayers[i].material === material) return;
    this.shieldLayers = this.shieldLayers.map((l, j) => (j === i ? { ...l, thicknessCm: l.thicknessCm, material } : l));
    this.recomputeDose();
  }

  /** Set layer `i`'s thickness (cm, clamped ≥ 0; 0 ⇒ that layer does not attenuate). */
  setShieldLayerThicknessCm(i: number, x: number): void {
    if (i < 0 || i >= this.shieldLayers.length || !Number.isFinite(x) || x < 0 || x === this.shieldLayers[i].thicknessCm) return;
    this.shieldLayers = this.shieldLayers.map((l, j) => (j === i ? { ...l, thicknessCm: x } : l));
    this.recomputeDose();
  }

  /** Remove layer `i`. No-op on an out-of-range index. */
  removeShieldLayer(i: number): void {
    if (i < 0 || i >= this.shieldLayers.length) return;
    this.shieldLayers = this.shieldLayers.filter((_l, j) => j !== i);
    this.recomputeDose();
  }

  /** Move layer `i` toward the source (dir −1) or the detector (dir +1) — order matters for
   *  buildup, so this is a real physics control, not cosmetics (M8, §6.4). */
  moveShieldLayer(i: number, dir: -1 | 1): void {
    const j = i + dir;
    if (i < 0 || i >= this.shieldLayers.length || j < 0 || j >= this.shieldLayers.length) return;
    const next = [...this.shieldLayers];
    [next[i], next[j]] = [next[j], next[i]];
    this.shieldLayers = next;
    this.recomputeDose();
  }

  // -- single-layer COMPATIBILITY setters (M6g API over the stack) ----------

  /** Replace the whole stack with a single layer of `material` (null clears the shield) —
   *  the legacy one-material flow. Keeps the existing thickness when one is present. */
  setShieldMaterial(material: string | null): void {
    if (material === null) {
      this.clearShield();
      return;
    }
    if (this.shieldLayers.length === 1 && this.shieldLayers[0].material === material) return;
    const thicknessCm = this.shieldLayers[0]?.thicknessCm ?? DEFAULT_SHIELD_THICKNESS_CM;
    this.shieldLayers = [{ material, thicknessCm }];
    this.recomputeDose();
  }

  /** Set the (single/first) layer's thickness (cm). Legacy single-layer convenience. */
  setShieldThicknessCm(x: number): void {
    if (!Number.isFinite(x) || x < 0 || this.shieldLayers.length === 0 || x === this.shieldLayers[0].thicknessCm) return;
    this.shieldLayers = this.shieldLayers.map((l, j) => (j === 0 ? { ...l, thicknessCm: x } : l));
    this.recomputeDose();
  }

  /** Remove the whole shield (stack → empty); re-evaluates the dose path unshielded. */
  clearShield(): void {
    if (this.shieldLayers.length === 0) return;
    this.shieldLayers = [];
    this.recomputeDose();
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
      this.neutronSource = null; // no inventory ⇒ no prebuilt source
      this.spentFuelNeutronId = null; // M9: same — empty inventory carries no SF neutron source
      this.hiddenNuclides.clear(); // empty inventory ⇒ nothing to hide (view-only)
      this.clearDose();
      this.clearChain();
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
      this.hiddenNuclides.clear(); // a failed solve has no closure → reset visibility (view-only)
      this.clearDose();
      this.clearChain();
      this.status = "error";
      this.errorMsg = `${res.error.type}: ${res.error.message}`;
      return;
    }

    this.handle = res.handle;
    this.solveMeta = res;
    this.colors = this.registry.assignAll(res.nuclides); // fresh reference → reactive (#4)
    this.pruneHidden(res.nuclides); // drop hidden ids no longer in the closure (view-only)
    this.status = "solved";
    this.resetCursor(); // the range changed → home the cursor before evaluating (#2 advisor)
    this.recomputeCurves(); // one evaluate over the auto-range grid (§9; "evaluate many", #1)
    this.recomputeDose(); // and the dose-rate series over the same grid (M6f; pure evaluate)
    this.fetchChain(); // the DAG topology (time-independent → only here, M6e)
    this.recomputeChainActivity(); // and its activity series over `curveX` (after recomputeCurves)
    this.recomputeDecayHeat(); // and the decay-heat series over `curveX` (M7c; after recomputeCurves)
    this.recomputeInternalDose(); // and the committed-dose series over `curveX` (M13; after recomputeCurves)
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
  /**
   * Recompute the dose breakdown off the live handle (pure evaluate, never a re-solve, §3).
   * The γ/β path and the neutron path are computed INDEPENDENTLY so neither can blank the other
   * (SYMMETRIC orphan guard, §11): a γ failure — e.g. the G-P buildup overflow for a low-energy
   * line through very thick high-Z lead, a pre-existing γ-engine edge — sets `doseError` and
   * clears only the γ/β series, while the neutron card still renders (M10: lead → T_n=1 +
   * steer-to-hydrogenous). A neutron failure sets `neutronDoseError` and never touches γ/β.
   */
  private recomputeDose(): void {
    const meta = this.solveMeta;
    if (!this.client || !this.handle || !meta || this.curveX.length === 0) {
      this.clearDoseSeries();
      this.doseError = "";
      return;
    }
    const t0 = this.referenceTimeS;
    const times = t0 > 0 ? this.curveX.map((x) => x + t0) : this.curveX.slice();
    const geometry = this.doseQuantity === "effective" ? this.doseGeometry : null;
    this.recomputeGammaBeta(times, geometry);
    this.recomputeNeutron(times, geometry);
  }

  /**
   * γ + β (+ shield extras) dose series. Isolated from the neutron path: on failure it clears
   * ONLY the γ/β-family series and sets `doseError`, never the neutron series (§11).
   */
  private recomputeGammaBeta(times: number[], geometry: string | null): void {
    this.doseError = "";
    if (!this.client || !this.handle) return;
    const shield = this.shield; // ordered layer list [[material, cm], …] | null (M8)
    const betaShield = this.betaShield; // β stops in the source-side layer only (M8)

    const fail = (e: { type: string; message: string }): void => {
      this.clearGammaBetaSeries();
      this.doseError = `${e.type}: ${e.message}`;
    };

    // γ dose-rate series THROUGH the whole shield stack (M8; null when unshielded).
    const g = this.client.dose(this.handle, {
      times_s: times,
      quantity: this.doseQuantity,
      distance_m: this.doseDistanceM,
      geometry,
      shield,
    });
    if (!g.ok) return fail(g.error);

    // The per-line γ decomposition (M6f-2): same quantity/geometry AND SHIELD STACK as the γ
    // series so the table reconciles with the γ card, but distance/time-free (the cursor getter
    // folds in 1/4πd² + activity). One fetch per recomputeDose; the cursor never re-fetches (§3).
    const lines = this.client.dose_lines(this.handle, { quantity: this.doseQuantity, geometry, shield });
    if (!lines.ok) return fail(lines.error);

    // β skin dose Hp(0.07) through the SOURCE-SIDE layer only (M8): betas stop in the first
    // absorber, where the secondary bremsstrahlung is generated ("more lead → more dose"),
    // scored in the γ quantity so it is comparable with the γ card. No ICRP geometry on the
    // skin dose itself (depth-defined).
    const b = this.client.beta_dose(this.handle, {
      times_s: times,
      distance_m: this.doseDistanceM,
      shield: betaShield,
      brems_quantity: this.doseQuantity,
      geometry,
    });
    if (!b.ok) return fail(b.error);

    // Shield extras — only when a shield is actually attenuating:
    //  · an UNSHIELDED γ baseline for the at-cursor attenuation factor (M6g #5),
    //  · the dose-vs-thickness coefficient grid (Design-A, M6g #4) sweeping the DETECTOR-side
    //    layer with the rest of the stack held, and
    //  · for ≥2 distinct-material layers, a REVERSED-order γ series — the spread is the M8
    //    order-sensitivity band of the last-layer buildup approximation (§11).
    // All are pure evaluates off the same handle; the cursor folds them with zero re-fetch.
    let bare: DoseOk | null = null;
    let thickness: DoseThicknessOk | null = null;
    let reversed: DoseOk | null = null;
    if (shield) {
      const gb = this.client.dose(this.handle, {
        times_s: times,
        quantity: this.doseQuantity,
        distance_m: this.doseDistanceM,
        geometry,
      });
      if (!gb.ok) return fail(gb.error);
      bare = gb;

      const sweepIndex = shield.length - 1; // the detector-side (last) active layer
      const dt = this.client.dose_thickness(this.handle, {
        layers: shield,
        sweep_index: sweepIndex,
        thicknesses_cm: this.thicknessGrid(shield[sweepIndex][1]),
        quantity: this.doseQuantity,
        geometry,
      });
      if (!dt.ok) return fail(dt.error);
      thickness = dt;

      const distinctMaterials = new Set(shield.map((l) => l[0])).size;
      if (shield.length >= 2 && distinctMaterials >= 2) {
        const rev = this.client.dose(this.handle, {
          times_s: times,
          quantity: this.doseQuantity,
          distance_m: this.doseDistanceM,
          geometry,
          shield: [...shield].reverse(),
        });
        if (!rev.ok) return fail(rev.error);
        reversed = rev;
      }
    }

    this.gammaDoseSeries = g;
    this.betaDoseSeries = b;
    this.gammaLines = lines;
    this.gammaDoseSeriesBare = bare;
    this.gammaDoseSeriesReversed = reversed;
    this.bremsSeries = b.bremsstrahlung ?? null;
    this.gammaThicknessCoeffs = thickness;
  }

  /**
   * Neutron dose series (M7b/M9, §6.3) — only for a prebuilt neutron source / spent-fuel SF
   * source (the gray-out gate). Isolated from the γ/β path (SYMMETRIC orphan guard): runs
   * regardless of γ's outcome, and a neutron failure sets only `neutronDoseError`. M10: the
   * neutron dose now responds to the SHARED shield stack via the fast-neutron removal cross-
   * section (T_n = exp(−Σ_R·x)): a hydrogenous layer (water) attenuates; a γ-oriented layer
   * (lead) is neutron-transparent and the response carries a `no_hydrogenous_layer` /
   * `neutron_transparent` warning instead of a silently-low number. Same quantity/geometry as
   * γ so the two are comparable/summable (both Sv).
   */
  private recomputeNeutron(times: number[], geometry: string | null): void {
    this.neutronDoseError = "";
    if (!this.client || !this.handle) {
      this.neutronDoseSeries = null;
      return;
    }
    const shield = this.shield; // the SAME stack the γ path uses; only hydrogenous layers remove n
    if (this.neutronSource) {
      const nq = this.client.neutron_dose(this.handle, {
        times_s: times,
        source: this.neutronSource,
        quantity: this.doseQuantity,
        distance_m: this.doseDistanceM,
        geometry,
        shield,
      });
      if (nq.ok) {
        this.neutronDoseSeries = nq;
      } else {
        this.neutronDoseSeries = null;
        this.neutronDoseError = `${nq.error.type}: ${nq.error.message}`;
      }
    } else if (this.spentFuelNeutronId) {
      // M9 spent-fuel SF neutrons — the MULTI-parent path. Same DoseOk shape as `neutron_dose`,
      // so `neutronDoseSeries` and all its cursor/stacked-bar consumers are reused unchanged.
      const nq = this.client.spent_fuel_neutron_dose(this.handle, {
        times_s: times,
        source_id: this.spentFuelNeutronId,
        quantity: this.doseQuantity,
        distance_m: this.doseDistanceM,
        geometry,
        shield,
      });
      if (nq.ok) {
        this.neutronDoseSeries = nq;
      } else {
        this.neutronDoseSeries = null;
        this.neutronDoseError = `${nq.error.type}: ${nq.error.message}`;
      }
    } else {
      this.neutronDoseSeries = null;
    }
  }

  /**
   * Linear thickness grid (cm) from 0 (the unshielded baseline) to 4× the selected
   * thickness for the dose-vs-thickness sweep (M6g #4). With N=33 points the selected
   * thickness lands exactly on grid index 8 (powers-of-two arithmetic is float-exact), so
   * the swept curve reconciles with the breakdown bar at that thickness; a defensive dedup
   * guarantees membership even if `tmax` ever changes.
   */
  private thicknessGrid(selected: number): number[] {
    const tmax = Math.max(selected * 4, 0.001);
    const N = 33;
    const xs: number[] = [];
    for (let i = 0; i < N; i++) xs.push((tmax * i) / (N - 1));
    if (!xs.some((x) => Math.abs(x - selected) < 1e-12)) {
      xs.push(selected);
      xs.sort((a, b) => a - b);
    }
    return xs;
  }

  /** Null only the γ/β-family series (M6f + M6g). Used by the γ/β failure branch so a γ error
   *  (e.g. the thick-lead buildup overflow) cannot blank the independent neutron card (§11). */
  private clearGammaBetaSeries(): void {
    this.gammaDoseSeries = null;
    this.betaDoseSeries = null;
    this.gammaLines = null;
    this.gammaDoseSeriesBare = null;
    this.gammaDoseSeriesReversed = null;
    this.bremsSeries = null;
    this.gammaThicknessCoeffs = null;
  }

  /** Null every dose-path series (γ/β AND neutron). For an empty/failed solve via clearDose. */
  private clearDoseSeries(): void {
    this.clearGammaBetaSeries();
    this.neutronDoseSeries = null;
    this.neutronDoseError = "";
  }

  /** Clear the dose breakdown (empty / failed solve). */
  private clearDose(): void {
    this.clearDoseSeries();
    this.doseError = "";
  }

  // -- the chain DAG (M6e) --------------------------------------------------

  /**
   * Fetch the decay-chain DAG topology (nodes + edges) for the live handle. Pure
   * topology — TIME-INDEPENDENT, so this runs ONLY on solve (never on a source-age
   * or cursor change). Loud on failure (#3): clears the graph + sets `chainError`,
   * never a silently blank diagram. The node set is the solve closure verbatim
   * (engine/chain.py), so the DAG and inventory can't drift.
   */
  private fetchChain(): void {
    this.chainError = "";
    if (!this.client || !this.handle) {
      this.chainDag = null;
      return;
    }
    const res = this.client.chain(this.handle);
    if (!res.ok) {
      this.chainDag = null;
      this.chainError = `${res.error.type}: ${res.error.message}`;
      return;
    }
    this.chainDag = res;
  }

  /**
   * Evaluate the ACTIVITY (Bq) series over the curve grid for the live node
   * encoding. Its OWN series (axis=activity, unit=Bq) — independent of the curve's
   * display axis (the DAG always wants activity, §5) — over the SAME `curveX`
   * (evaluated at `referenceTimeS + curveX`, the M6d offset), so the cursor indexes
   * it 1:1 with the curves/dose. Must run AFTER `recomputeCurves` (depends on
   * `curveX`). Pure evaluate, NEVER a re-solve (#1). Loud on failure (#3).
   */
  private recomputeChainActivity(): void {
    // Topology absent (failed/empty solve): nothing to encode, and a `fetchChain`
    // error (a closure-drift bug — §11) must stay loud — bail WITHOUT touching
    // `chainError`. When topology IS present, any prior `chainError` was an activity
    // error, so clear it here for parity with `recomputeDose` (advisor: a recovering
    // source-age must not leave a stale banner).
    if (!this.chainDag) {
      this.chainActivity = null;
      return;
    }
    this.chainError = "";
    const meta = this.solveMeta;
    if (!this.client || !this.handle || !meta || this.curveX.length === 0) {
      this.chainActivity = null;
      return;
    }
    const t0 = this.referenceTimeS;
    const times = t0 > 0 ? this.curveX.map((x) => x + t0) : this.curveX.slice();
    const res = this.client.evaluate(this.handle, { times_s: times, axis: "activity", unit: "Bq" });
    if (!res.ok) {
      this.chainActivity = null;
      this.chainError = `${res.error.type}: ${res.error.message}`;
      return;
    }
    this.chainActivity = res;
  }

  /** Clear the chain DAG (empty / failed solve). */
  private clearChain(): void {
    this.chainDag = null;
    this.chainActivity = null;
    this.chainError = "";
    // Decay heat is a derived per-time series like chainActivity; cleared on the same
    // empty/failed-solve paths (clearChain is called in both) so a stale readout can't linger.
    this.decayHeatSeries = null;
    this.decayHeatError = "";
    // Internal/committed dose (M13) is the same shape — cleared here so a stale committed-Sv
    // readout can't survive a Clear or a failed re-solve (both call clearChain).
    this.internalDoseSeries = null;
    this.internalDoseError = "";
  }

  // -- decay heat (M7c §5) --------------------------------------------------

  /**
   * Evaluate the decay-heat (W) series over the curve grid. Its OWN bridge call (one
   * `decay_heat` per solve / source-age over `curveX`, evaluated at the absolute times
   * `referenceTimeS + curveX`), so the cursor getter indexes it 1:1 with the curves/dose.
   * DISTANCE- and quantity-free — heat is total locally-deposited power, so it does NOT
   * recompute on the dose inputs (distance/quantity/shield), only on inventory + source-age.
   * Pure evaluate, NEVER a re-solve (#1). Loud on failure (#3): nulls the series + sets
   * `decayHeatError`, never a silently blank readout.
   */
  private recomputeDecayHeat(): void {
    this.decayHeatError = "";
    if (!this.client || !this.handle || this.curveX.length === 0) {
      this.decayHeatSeries = null;
      return;
    }
    const t0 = this.referenceTimeS;
    const times = t0 > 0 ? this.curveX.map((x) => x + t0) : this.curveX.slice();
    const res = this.client.decay_heat(this.handle, { times_s: times });
    if (!res.ok) {
      this.decayHeatSeries = null;
      this.decayHeatError = `${res.error.type}: ${res.error.message}`;
      return;
    }
    this.decayHeatSeries = res;
  }

  // -- internal / committed dose (M13 §M13) ---------------------------------

  /**
   * Evaluate the committed E(50) series (Sv) over the curve grid for the current route +
   * population — `Σ e_n·A_n(t)`, one matvec of the fixed per-nuclide coefficients against the
   * inventory's activity. DISTANCE-, geometry-, and shield-FREE, so it recomputes on inventory +
   * source-age + route + population only (NOT the external-dose inputs). The bridge builds the
   * activity series internally from the same handle; we feed the IDENTICAL absolute-time grid the
   * other recomputes use (`referenceTimeS + curveX`) so the cursor read reconciles 1:1 with the
   * `chainActivity`-folded breakdown. Pure evaluate, NEVER a re-solve (#1; the gate asserts the
   * registry stays at 1 across a route/population toggle). Loud on failure (#3): nulls the series
   * + sets `internalDoseError`, never a silently blank readout.
   */
  private recomputeInternalDose(): void {
    this.internalDoseError = "";
    if (!this.client || !this.handle || this.curveX.length === 0) {
      this.internalDoseSeries = null;
      return;
    }
    const t0 = this.referenceTimeS;
    const times = t0 > 0 ? this.curveX.map((x) => x + t0) : this.curveX.slice();
    const res = this.client.internal_dose(this.handle, {
      times_s: times,
      route: this.internalRoute,
      population: this.internalPopulation,
    });
    if (!res.ok) {
      this.internalDoseSeries = null;
      this.internalDoseError = `${res.error.type}: ${res.error.message}`;
      return;
    }
    this.internalDoseSeries = res;
  }

  // -- persistence (M6b: inventory slice; later chunks extend the envelope) --

  private toPersistable(): PersistableState {
    return {
      entries: this.entries.map((e) => ({ ...e })),
      precision: this.precision,
      referenceTimeS: this.referenceTimeS,
      neutronSource: this.neutronSource, // prebuilt source key (M7b v3)
      spentFuelNeutronId: this.spentFuelNeutronId, // spent-fuel SF neutron source (M9 v5)
      // view (M6h)
      axis: this.axis,
      activityUnit: this.activityUnit,
      massUnit: this.massUnit,
      logY: this.logY,
      // dose (M6h)
      doseDistanceM: this.doseDistanceM,
      doseQuantity: this.doseQuantity,
      doseGeometry: this.doseGeometry,
      exposureS: this.exposureS,
      // shield stack (M8; serializer v4)
      shieldLayers: this.shieldLayers.map((l) => ({ ...l })),
      // time cursor (M6h) — restored AFTER solve (the ordering trap, see loadFromText)
      cursorOffsetS: this.cursorOffsetS,
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
    // Restore every RECOMPUTE-AFFECTING field by direct assignment BEFORE solve(), so
    // solve()'s internal recomputeCurves/recomputeDose pick up the loaded values in one
    // pass (M6h #3). This bypasses the setters' guards on purpose — the deserializer has
    // already validated ranges/enums loudly (M6h #2), so there is nothing left to clamp.
    this.entries = parsed.entries.map((e) => ({ ...e }));
    this.precision = parsed.precision;
    this.referenceTimeS = parsed.referenceTimeS;
    this.neutronSource = parsed.neutronSource; // restore the prebuilt-source key (M7b v3)
    this.spentFuelNeutronId = parsed.spentFuelNeutronId; // restore the spent-fuel SF source (M9 v5)
    this.axis = parsed.axis;
    this.activityUnit = parsed.activityUnit;
    this.massUnit = parsed.massUnit;
    this.logY = parsed.logY;
    this.doseDistanceM = parsed.doseDistanceM;
    this.doseQuantity = parsed.doseQuantity;
    this.doseGeometry = parsed.doseGeometry;
    this.exposureS = parsed.exposureS;
    this.shieldLayers = parsed.shieldLayers.map((l) => ({ ...l }));

    await this.solve();

    // The cursor is restored AFTER solve(): solve() → resetCursor() homes it to the new
    // range's midpoint, so a value set before would be clobbered (the M6d ordering trap,
    // M6h #3). setCursorOffsetS clamps to the now-current cursorRange. A null offset (a v1
    // file, or one without a cursor) leaves resetCursor's default home in place.
    if (parsed.cursorOffsetS !== null) this.setCursorOffsetS(parsed.cursorOffsetS);
    return null;
  }

  async loadFile(file: File): Promise<string | null> {
    return this.loadFromText(await readStateFile(file));
  }

  /**
   * Load a prebuilt catalog source (M7 / §8): replace the inventory with the source's
   * named entries + its reference time (source-age) + its optional neutron-source key,
   * then re-solve. Mirrors `loadFromText`'s direct-assign-before-`solve()` order (one
   * recompute pass), but the manifest is trusted so there is nothing to validate/clamp —
   * the engine validates the entries loudly on solve as the backstop (#3). The cursor is
   * left at `solve()`'s midpoint home, which lands mid-evolution so the §5 equilibrium
   * demos (Cs-137 secular, Mo-99/Tc-99m transient) are visible immediately on load.
   * Returns the error message on a failed solve, else null.
   */
  async loadSource(source: PrebuiltSource): Promise<string | null> {
    this.entries = source.entries.map((e) => ({ ...e }));
    this.referenceTimeS = source.referenceTimeS ?? 0;
    // Set AFTER nothing can null these (a load is not a hand-edit). Mutually exclusive: a source
    // is either a single tabulated neutron key OR a spent-fuel multi-parent vector, never both.
    this.neutronSource = source.neutronSource ?? null;
    this.spentFuelNeutronId = source.spentFuelNeutronId ?? null;
    await this.solve();
    return this.status === "error" ? this.errorMsg : null;
  }

  /** Clear the inventory (releases the handle). */
  async clear(): Promise<void> {
    this.entries = [];
    await this.solve();
  }
}

/** The app-wide singleton every component imports. */
export const appState = new AppState();
