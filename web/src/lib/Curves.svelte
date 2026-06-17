<script lang="ts">
  // Overlay curves (M6-ui M6c, §9): the multi-species time-evolution plot on
  // log-log axes, driven by ONE evaluate() per inventory (the store owns it; this
  // is a PURE renderer — it never touches the BridgeClient). The docked
  // Atoms·Mass·Activity toggle + secondary unit re-evaluate the solved inventory
  // (cheap), never re-solve (#1). Plotly is an imperative library, so a $effect
  // syncs the store's curve into it via Plotly.react().
  import Plotly from "plotly.js-basic-dist-min";
  import { onDestroy, untrack } from "svelte";
  import { appState } from "./state.svelte";
  import { ACTIVITY_UNITS, AXIS_OPTIONS, MASS_UNITS } from "./types";

  // Display floor: clip at peak / 10^D (D decades below the global peak), §9. A
  // SINGLE global floor across ALL series (not per-series) is load-bearing — it is
  // what makes a negligible species read as an honest gap instead of being redrawn
  // at full height. Distinct from the engine's numerical validity floor.
  const FLOOR_DECADES = 13;

  let plotEl = $state<HTMLDivElement | null>(null);

  /** y-axis title tracks axis + resolved unit (§12, obsessive labels). */
  function yTitle(axis: string, unit: string): string {
    if (axis === "activity") return `Activity (${unit})`;
    if (axis === "mass") return `Mass (${unit})`;
    return "Atoms";
  }

  /** Global peak over every series × time (finite, positive). 0 ⇒ nothing to draw. */
  function globalPeak(series: Record<string, number[]>, names: string[]): number {
    let peak = 0;
    for (const n of names) {
      for (const v of series[n] ?? []) {
        if (Number.isFinite(v) && v > peak) peak = v;
      }
    }
    return peak;
  }

  // Build Plotly traces from the store's curve, applying the global log-floor. On a
  // log y-axis, values at/below the floor (or ≤0) become null → Plotly draws a gap
  // ("negligible/absent here"), never a dive toward −∞. On linear, values pass
  // through (0 is plottable; the linear option is the single-half-life zoom, §9).
  function buildTraces(): Partial<Plotly.PlotData>[] {
    const c = appState.curve;
    if (!c) return [];
    // x is the DISPLAY grid (time since the reference origin); the series were
    // evaluated at the absolute times `t₀ + curveX` (the M6d offset, in the store).
    const x = appState.curveX;
    const peak = globalPeak(c.series, c.nuclides);
    const floor = appState.logY ? peak / 10 ** FLOOR_DECADES : 0;
    return c.nuclides.map((name) => {
      const raw = c.series[name] ?? [];
      const y = raw.map((v) =>
        appState.logY ? (v > floor ? v : null) : Number.isFinite(v) ? v : null,
      );
      return {
        type: "scatter",
        mode: "lines",
        name,
        x,
        y,
        line: { color: appState.colors[name] ?? "#888", width: 2 },
        hovertemplate: `${name}: %{y:.3e} @ %{x:.3e} s<extra></extra>`,
      } as Partial<Plotly.PlotData>;
    });
  }

  // The time cursor (M6d): a vertical line at the slider's display-time position,
  // spanning the full plot height (yref:"paper" so it works on log or linear y).
  // Moving it is a cheap Plotly.relayout — never a trace rebuild (see the effects).
  function cursorShapes(): Partial<Plotly.Shape>[] {
    const x = appState.cursorOffsetS;
    if (!appState.curve || !(x > 0)) return [];
    return [
      {
        type: "line",
        xref: "x",
        yref: "paper",
        x0: x,
        x1: x,
        y0: 0,
        y1: 1,
        line: { color: "#e15759", width: 1.5, dash: "dot" },
        layer: "above",
      } as Partial<Plotly.Shape>,
    ];
  }

  function layout(): Partial<Plotly.Layout> {
    const c = appState.curve;
    return {
      margin: { l: 70, r: 20, t: 10, b: 50 },
      xaxis: { type: "log", title: { text: "Time (s)" }, automargin: true },
      yaxis: {
        type: appState.logY ? "log" : "linear",
        title: { text: c ? yTitle(c.axis, c.unit) : "" },
        automargin: true,
      },
      showlegend: true,
      legend: { orientation: "v" },
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  // Imperative sync (traces): rebuild the plot whenever the curve, display grid,
  // colors, or log/linear toggle change. react() both creates (first call) and
  // diff-updates. The cursor is read with untrack() here so a cursor MOVE does NOT
  // re-run this (expensive) trace rebuild — it rides the cheap relayout effect
  // below instead. This split is the "smooth slider" payoff of solve-once (§3).
  $effect(() => {
    const c = appState.curve;
    void appState.logY;
    void appState.colors;
    void appState.curveX;
    const el = plotEl;
    if (!el) return;
    if (!c) {
      Plotly.purge(el);
      return;
    }
    const lay = layout();
    lay.shapes = untrack(() => cursorShapes()); // include the current cursor, untracked
    Plotly.react(el, buildTraces(), lay, { responsive: true, displaylogo: false });
  });

  // Imperative sync (cursor only): a cursor move is a cheap shapes-only relayout,
  // not a trace rebuild. Guarded on the plot already existing (effects may run
  // before the trace effect's first react() on mount — then the cursor is drawn
  // by that react() via the untracked read above).
  $effect(() => {
    const x = appState.cursorOffsetS; // the one tracked dep — re-run on cursor move
    void x;
    const el = plotEl;
    if (!el || !appState.curve) return;
    if (!(el as unknown as { data?: unknown[] }).data) return; // not plotted yet
    Plotly.relayout(el, { shapes: cursorShapes() });
  });

  onDestroy(() => {
    if (plotEl) Plotly.purge(plotEl);
  });

  // Secondary-unit options for the current axis (atoms has a single fixed unit).
  const unitOptions = $derived(
    appState.axis === "activity" ? ACTIVITY_UNITS : appState.axis === "mass" ? MASS_UNITS : [],
  );
  const currentUnit = $derived(appState.axis === "activity" ? appState.activityUnit : appState.massUnit);

  function onUnit(u: string) {
    if (appState.axis === "activity") appState.setActivityUnit(u);
    else if (appState.axis === "mass") appState.setMassUnit(u);
  }

  const hasCurve = $derived(appState.curve !== null);
</script>

<section class="curves">
  <header>
    <h2>Time evolution</h2>

    <!-- Docked Atoms · Mass · Activity segmented toggle (default Activity, §9). -->
    <div class="axis-toggle" role="group" aria-label="Quantity axis" data-testid="axis-toggle">
      {#each AXIS_OPTIONS as opt (opt.value)}
        <button
          class:selected={appState.axis === opt.value}
          aria-pressed={appState.axis === opt.value}
          onclick={() => appState.setAxis(opt.value)}
        >
          {opt.label}
        </button>
      {/each}
    </div>

    <!-- Secondary unit (Bq/Ci, g/kg/mg); hidden for atoms (one unit). -->
    {#if unitOptions.length > 0}
      <select
        class="unit"
        data-testid="curve-unit"
        value={currentUnit}
        onchange={(e) => onUnit((e.target as HTMLSelectElement).value)}
      >
        {#each unitOptions as u (u)}
          <option value={u}>{u}</option>
        {/each}
      </select>
    {/if}

    <label class="logtoggle">
      <input
        type="checkbox"
        checked={appState.logY}
        onchange={(e) => appState.setLogY((e.target as HTMLInputElement).checked)}
      />
      log y-axis
    </label>
  </header>

  {#if appState.curveError}
    <p class="note error" role="alert">⚠ curve failed — {appState.curveError}</p>
  {:else if !appState.solveMeta}
    <p class="note muted">Add an isotope above to plot its decay over time.</p>
  {:else if !hasCurve}
    <p class="note muted">
      All loaded nuclides are stable — there is no time evolution to plot.
    </p>
  {/if}

  <!-- The plot div is always present so the $effect can react()/purge() it. -->
  <div class="plot" data-testid="curves-plot" class:empty={!hasCurve} bind:this={plotEl}></div>

  <p class="hint muted">
    Log-log overlay, one Bateman solve per inventory; the time slider below scrubs a
    cursor over these curves — no re-solve (§3). The Activity axis omits stable
    end-products (zero activity); switch to Atoms/Mass to see them grow in. Curves
    below ~{FLOOR_DECADES} decades under the peak are clipped to an honest gap, not
    drawn toward −∞ (§9).
  </p>
</section>

<style>
  .curves {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
    margin-right: auto;
  }
  .axis-toggle {
    display: inline-flex;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .axis-toggle button {
    font: inherit;
    border: none;
    background: transparent;
    padding: 0.3rem 0.7rem;
    cursor: pointer;
    border-left: 1px solid #8886;
  }
  .axis-toggle button:first-child {
    border-left: none;
  }
  .axis-toggle button.selected {
    background: #4e79a7;
    color: #fff;
    font-weight: 600;
  }
  .unit,
  .logtoggle {
    font: inherit;
  }
  .logtoggle {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .unit {
    padding: 0.3rem 0.4rem;
  }
  .plot {
    width: 100%;
    height: 420px;
    margin-top: 0.75rem;
  }
  .plot.empty {
    height: 0;
    margin: 0;
  }
  .note {
    margin: 0.75rem 0 0;
    font-weight: 600;
  }
  .note.error {
    color: #b3261e;
  }
  .muted {
    opacity: 0.7;
    font-weight: 400;
  }
  .hint {
    margin: 0.6rem 0 0;
    font-size: 0.85rem;
  }
</style>
