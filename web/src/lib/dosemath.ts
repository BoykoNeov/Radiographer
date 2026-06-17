// Pure dose-math helpers (M6-ui M6f, §3/§11/§12). No Svelte, no bridge — just the
// arithmetic the dose calculator does on the engine's already-returned rate series,
// kept here so it is unit-testable and reusable by M6f-2 (uncertainty) and M6g.
//
// The dose path is "solve once, evaluate many" (§3): the store evaluates a dose-RATE
// SERIES over the curve grid once per (distance, quantity, geometry); the time cursor
// then INDEXES that series (`interpAt`) and the accumulated dose INTEGRATES it
// (`trapzWindow`) — no per-cursor-tick bridge call. Accumulated dose must integrate,
// never rate×time, or it silently overestimates a source that decays during the
// exposure window (§11; e.g. ~30 % high for a 6 h exposure of a 6 h half-life).

/**
 * Linear interpolation of `ys` at `x`, with `xs` strictly ascending and the same
 * length as `ys`. Clamps to the endpoints (the curve grid spans the whole slider
 * range, so the cursor is always inside it — clamping only guards float edges).
 * Returns `null` when there is nothing to interpolate (empty / mismatched arrays).
 */
export function interpAt(xs: number[], ys: number[], x: number): number | null {
  const n = xs.length;
  if (n === 0 || ys.length !== n) return null;
  if (n === 1) return ys[0];
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  // Binary search for the bracketing segment (xs ascending).
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid;
    else hi = mid;
  }
  const x0 = xs[lo];
  const x1 = xs[hi];
  const span = x1 - x0;
  if (!(span > 0)) return ys[lo];
  const f = (x - x0) / span;
  return ys[lo] + f * (ys[hi] - ys[lo]);
}

export interface TrapzResult {
  /** ∫ ys d(xs) over [a, b] (∩ the grid range), trapezoidal. */
  value: number;
  /** True when [a, b] extended beyond the grid — the integral is the in-range part
   *  only (surfaced loudly, never a silent under-count; §11). */
  truncated: boolean;
}

/**
 * Trapezoidal ∫ `ys` d`xs` from `a` to `b`, with `xs` strictly ascending. The window
 * is clamped to the grid range and `truncated` reports whether any of [a, b] fell
 * outside it. Endpoints are interpolated, so the window need not land on grid points.
 */
export function trapzWindow(xs: number[], ys: number[], a: number, b: number): TrapzResult {
  const n = xs.length;
  if (n === 0 || ys.length !== n || !(b > a)) return { value: 0, truncated: false };
  const x0 = xs[0];
  const xN = xs[n - 1];
  const lo = Math.max(a, x0);
  const hi = Math.min(b, xN);
  const truncated = a < x0 || b > xN;
  if (!(hi > lo)) return { value: 0, truncated };

  // Breakpoints: the clamped endpoints plus every interior grid point between them,
  // integrating trapezoids over consecutive breakpoints (interpolated y at each).
  const pts: number[] = [lo];
  for (let i = 0; i < n; i++) {
    if (xs[i] > lo && xs[i] < hi) pts.push(xs[i]);
  }
  pts.push(hi);

  let area = 0;
  let prevX = pts[0];
  let prevY = interpAt(xs, ys, prevX) ?? 0;
  for (let i = 1; i < pts.length; i++) {
    const curX = pts[i];
    const curY = interpAt(xs, ys, curX) ?? 0;
    area += 0.5 * (prevY + curY) * (curX - prevX);
    prevX = curX;
    prevY = curY;
  }
  return { value: area, truncated };
}

/**
 * Point-source geometric factor `1/(4π d²)` (m⁻²) — the exact mirror of the engine's
 * `GammaDoseModel._geometric_factor` (dose.py). The γ per-line table and the dose-vs-
 * distance curve apply it client-side to the engine's distance-free per-decay coefficients,
 * so the cursor/distance are pure derives (§3 "evaluate many", zero bridge calls). The
 * point-source field is singular at 0; callers pass `distance > 0` (the dose input rejects
 * ≤0). Returns 0 for a non-positive distance rather than ∞ (a defensive guard; never hit
 * through the validated input path).
 */
export function geometricFactor(distanceM: number): number {
  if (!(distanceM > 0)) return 0;
  return 1 / (4 * Math.PI * distanceM * distanceM);
}

// --- SI dose formatting (§12: obsessive, prefixed units) ----------------------

const PREFIXES: ReadonlyArray<{ factor: number; symbol: string }> = [
  { factor: 1e-12, symbol: "p" },
  { factor: 1e-9, symbol: "n" },
  { factor: 1e-6, symbol: "µ" },
  { factor: 1e-3, symbol: "m" },
  { factor: 1, symbol: "" },
  { factor: 1e3, symbol: "k" },
];

function sig3(v: number): string {
  if (v >= 100) return v.toPrecision(4).replace(/\.?0+$/, "");
  return v.toPrecision(3).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

/**
 * Format an SI dose `value` (e.g. Sv, Gy) with an auto-picked metric prefix so the
 * mantissa sits in [1, 1000): `1.2e-6 Sv → "1.20 µSv"`. `unit` is the base SI symbol
 * ("Sv" / "Gy"); it is the caller's job to pass the RIGHT quantity (never mix
 * Hp(0.07) Gy with H*(10) Sv — #1). Non-finite or ≤0 renders as `"0 <unit>"`.
 */
export function formatDose(value: number, unit: string): string {
  if (!Number.isFinite(value) || value <= 0) return `0 ${unit}`;
  let chosen = PREFIXES[0];
  for (const p of PREFIXES) {
    if (value >= p.factor) chosen = p;
  }
  return `${sig3(value / chosen.factor)} ${chosen.symbol}${unit}`;
}

/** Format an SI **per-second** dose rate as a per-hour, prefixed quantity. */
export function formatDoseRate(siPerSec: number, unit: string): string {
  return `${formatDose(siPerSec * 3600, unit)}/h`;
}
