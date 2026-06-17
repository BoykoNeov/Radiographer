// Shared per-species color palette (HANDOFF_PLAN §9 LOCKED, M6-ui invariant #4).
//
// "One color per species, shared" across the DAG, the overlay curves, and the
// dose breakdown. The single owner of that mapping is the app-state store, which
// holds ONE registry instance and re-derives a fresh `Record<nuclide,color>` on
// every solve (a fresh object reference so Svelte 5 `$state` tracks it — mutating
// a Map in place would not re-render — see the store).
//
// Stability contract: a nuclide that persists across re-solves keeps its color.
// The registry caches each assignment and only mints a new color for an unseen
// nuclide, so adding/removing isotopes never reshuffles the colors already on
// screen. Colors are assigned over the *full descendant closure* (parents AND
// daughters), because every consumer renders daughters too.

/**
 * Tableau 20 — 20 perceptually distinct categorical colors (paired hue/tint).
 * Covers the common closure sizes (U-238 ≈ 21 nuclides) before any overflow.
 */
const BASE_PALETTE: readonly string[] = [
  "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1",
  "#76b7b2", "#edc948", "#ff9da7", "#9c755f", "#bab0ac",
  "#a0cbe8", "#ffbe7d", "#8cd17d", "#ff9d9a", "#d4a6c8",
  "#86bcb6", "#b6992d", "#fabfd2", "#d7b5a6", "#79706e",
];

const GOLDEN_ANGLE_DEG = 137.508;

/** Deterministic overflow color for assignment `i` once the base palette is spent. */
function overflowColor(i: number): string {
  // Golden-angle hue rotation gives maximally-spread, repeatable hues; fixed
  // saturation/lightness keeps them legible on light and dark backgrounds.
  const hue = (i * GOLDEN_ANGLE_DEG) % 360;
  return `hsl(${hue.toFixed(1)}, 62%, 50%)`;
}

export class ColorRegistry {
  private readonly cache = new Map<string, string>();
  private next = 0;

  /** The stable color for one nuclide, minting (and caching) it on first sight. */
  colorFor(nuclide: string): string {
    const existing = this.cache.get(nuclide);
    if (existing !== undefined) return existing;
    const i = this.next++;
    const color = i < BASE_PALETTE.length ? BASE_PALETTE[i] : overflowColor(i);
    this.cache.set(nuclide, color);
    return color;
  }

  /**
   * A fresh `{nuclide: color}` for the given closure — reuses cached colors,
   * mints new ones in array order. Returns a NEW object every call so a Svelte
   * `$state` assignment is tracked (advisor: in-place Map mutation is not).
   */
  assignAll(nuclides: readonly string[]): Record<string, string> {
    const out: Record<string, string> = {};
    for (const n of nuclides) out[n] = this.colorFor(n);
    return out;
  }

  /** Test/debug hook: how many distinct colors have been minted this session. */
  get size(): number {
    return this.cache.size;
  }
}
