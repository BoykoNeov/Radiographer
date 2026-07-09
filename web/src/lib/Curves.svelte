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
  import { ACTIVITY_UNITS, AXIS_OPTIONS, MASS_UNITS, TIME_UNITS } from "./types";

  // Diagnostic only (gate-js-heap-runaway, HANDOFF_PLAN §13 #8): log the render
  // counter INLINE at the call site, wall-clock-throttled, rather than relying only
  // on App.svelte's rAF sampler. If the runaway is a microtask-flush storm (the
  // leading hypothesis), rAF never gets a turn (it runs after microtasks drain), so
  // it would go dark exactly when this signal is needed most; a console.log made
  // from inside the effect still queues its CDP event on the IO thread and has a
  // real chance to flush mid-storm.
  let lastCurvesLog = 0;
  function logCurvesReact(): void {
    if (!window.__PERF__) return;
    const now = performance.now();
    if (now - lastCurvesLog < 200) return;
    lastCurvesLog = now;
    console.log(`[__PERF__] curvesReact=${window.__PERF__.renders.curvesReact}`);
  }

  // Display floor: clip at peak / 10^D (D decades below the global peak), §9. A
  // SINGLE global floor across ALL series (not per-series) is load-bearing — it is
  // what makes a negligible species read as an honest gap instead of being redrawn
  // at full height. Distinct from the engine's numerical validity floor.
  const FLOOR_DECADES = 13;

  let plotEl = $state<HTMLDivElement | null>(null);

  // x-axis display time unit (§9 "switch from seconds to years"). DISPLAY-ONLY: the
  // store/grid stay in SI seconds (§12) — this only rescales the plotted x array, the
  // cursor line, the axis title, and the hover label. Default "s" so the existing
  // seconds-based behaviour (and gate) is unchanged. Local to this plot, not the slider.
  let timeUnit = $state<string>("s");
  const timeUnitDef = $derived(TIME_UNITS.find((u) => u.value === timeUnit) ?? TIME_UNITS[0]);

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
    // Keep EVERY species as a trace, even hidden ones — hidden traces get
    // visible:"legendonly" (line hidden, legend entry stays and stays clickable) rather
    // than being dropped from the array entirely. Dropping them removes their legend
    // entry too, which strands the user with no way to re-show a species once every
    // trace is hidden (there'd be nothing left to click) — see the hide-all/legend fix.
    const hidden = appState.hiddenNuclides;
    // x is the DISPLAY grid (time since the reference origin), rescaled to the chosen
    // display unit; the store/grid stay SI seconds (§12). The series were evaluated at
    // the absolute times `t₀ + curveX` (the M6d offset, in the store).
    const f = timeUnitDef.seconds;
    const x = appState.curveX.map((v) => v / f);
    const ulabel = timeUnitDef.label;
    // Floor over ALL series (not just visible), so the y-axis floor stays stable as
    // species are hidden/shown — a floor keyed to `visible` would make the axis jump
    // on every toggle, which reads as a layout bug on top of the actual resize one.
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
        visible: hidden.has(name) ? "legendonly" : true,
        line: { color: appState.colors[name] ?? "#888", width: 2 },
        hovertemplate: `${name}: %{y:.3e} @ %{x:.3e} ${ulabel}<extra></extra>`,
      } as Partial<Plotly.PlotData>;
    });
  }

  // Plotly's own legend click/dbl-click default to toggling *its* internal per-trace
  // visibility — which would diverge from appState.hiddenNuclides (and desync the
  // chain DAG's dot coloring, which reads that same set). Intercept both: route a
  // single click through the shared toggle and suppress Plotly's default; suppress
  // double-click's "isolate this trace" outright (no equivalent in the shared state).
  function attachLegendHandlers(el: HTMLDivElement) {
    const gd = el as unknown as {
      removeAllListeners?: (evt: string) => void;
      on: (evt: string, cb: (ev: unknown) => boolean | void) => void;
    };
    gd.removeAllListeners?.("plotly_legendclick");
    gd.removeAllListeners?.("plotly_legenddoubleclick");
    gd.on("plotly_legendclick", (ev) => {
      // `curveNumber` is the clicked trace's index. buildTraces() maps `curve.nuclides`
      // 1:1 in order (trace i ⇒ nuclides[i]), so resolve the name off the store rather
      // than the event payload — Plotly's legendclick `ev.data` IS the traces array, so
      // the old `ev.data.data[…]` was a level too deep (undefined → threw → no toggle).
      const curveNumber = (ev as { curveNumber: number }).curveNumber;
      const name = appState.curve?.nuclides[curveNumber];
      if (name) appState.toggleHidden(name);
      return false; // suppress Plotly's own legendonly toggle — appState drives it
    });
    gd.on("plotly_legenddoubleclick", () => false); // suppress "isolate this trace"
  }

  // The time cursor (M6d): a vertical line at the slider's display-time position,
  // spanning the full plot height (yref:"paper" so it works on log or linear y).
  // Moving it is a cheap Plotly.relayout — never a trace rebuild (see the effects).
  function cursorShapes(): Partial<Plotly.Shape>[] {
    const x = appState.cursorOffsetS / timeUnitDef.seconds; // same display unit as the x array
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
      xaxis: { type: "log", title: { text: `Time (${timeUnitDef.label})` }, automargin: true },
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
    void appState.hiddenNuclides.size; // rebuild traces on hide/show (advisor #3)
    void timeUnit; // and on an x-axis unit switch (rescales x + relabels the axis)
    const el = plotEl;
    if (!el) return;
    if (!c) {
      Plotly.purge(el);
      return;
    }
    const lay = layout();
    lay.shapes = untrack(() => cursorShapes()); // include the current cursor, untracked
    if (window.__PERF__) window.__PERF__.renders.curvesReact++; // gate-js-heap-runaway diagnostic
    logCurvesReact();
    Plotly.react(el, buildTraces(), lay, { responsive: true, displaylogo: false });
    attachLegendHandlers(el);
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
  /** Every species hidden — the plot is intentionally empty; tell the user how to restore. */
  const allHidden = $derived(
    appState.curve !== null && appState.curve.nuclides.every((n) => appState.hiddenNuclides.has(n)),
  );
</script>

<section class="curves">
  <header>
    <h2>Time evolution</h2>

    <!-- Hide/show-all (moved from the decay chain, §9 follow-up: this is the panel the
         buttons actually affect — the chain only reflects hidden state via dot color). -->
    <div class="visibility" role="group" aria-label="Species visibility" data-testid="chain-visibility">
      <button data-testid="chain-hide-all" onclick={() => appState.hideAll()}>Hide all</button>
      <button data-testid="chain-show-all" onclick={() => appState.showAll()}>Show all</button>
    </div>

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
        aria-label="Curve unit"
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

    <!-- x-axis time unit (§9 "switch from seconds to years"); rescales the plotted x. -->
    <label class="timeunit">
      x-axis
      <select
        aria-label="Time axis unit"
        data-testid="curve-time-unit"
        value={timeUnit}
        onchange={(e) => (timeUnit = (e.target as HTMLSelectElement).value)}
      >
        {#each TIME_UNITS as u (u.value)}
          <option value={u.value}>{u.label}</option>
        {/each}
      </select>
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

  <!-- The plot div is always present so the $effect can react()/purge() it. The
       all-hidden note is an ABSOLUTE overlay INSIDE the (always-420px, whenever hasCurve)
       plot area, not another block in the note chain above. As a block it pushed the plot
       up/down every time the last species was hidden/shown — that resize moved the scroll
       (the shift the user reported, in both directions). As an overlay it never changes
       layout. pointer-events:none so clicks fall through to the legend beneath it (the
       restore path) instead of being swallowed by the centered note. -->
  <div class="plot-wrap">
    <div class="plot" data-testid="curves-plot" class:empty={!hasCurve} bind:this={plotEl}></div>
    {#if allHidden}
      <div class="overlay">
        <p class="note muted" data-testid="curves-all-hidden">
          All species hidden — click a node in the decay chain, or use “Show all”, to restore them.
        </p>
      </div>
    {/if}
  </div>

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
  .logtoggle,
  .timeunit {
    font: inherit;
  }
  .logtoggle,
  .timeunit {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .unit,
  .timeunit select {
    padding: 0.3rem 0.4rem;
  }
  .plot-wrap {
    position: relative;
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
  /* All-species-hidden note, centered over the (fixed-height) plot. Absolute so
     toggling it never resizes the panel; pointer-events:none so it never blocks a
     legend click. Sits over the empty axes Plotly still draws when every trace is off. */
  .overlay {
    position: absolute;
    inset: 0.75rem 0 0; /* match .plot's top margin so it covers the plot box, not the gap */
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    text-align: center;
    pointer-events: none;
  }
  .overlay .note {
    margin: 0;
    max-width: 30rem;
  }
  /* Move Plotly's (hover-only) modebar to the TOP-LEFT. Its default is the top-RIGHT,
     directly over our vertical legend — where it silently intercepts clicks on the top
     legend entries, so those species could not be hidden/shown by clicking the legend
     (the first/parent nuclide is the top entry, so this hit the species users care about
     most). :global because Plotly injects this DOM itself and re-creates it on every
     react(); a CSS rule persists across re-renders where an inline style would be wiped.
     Left overrides the container's right-anchored default. !important because Plotly
     injects its own `.modebar { right: 2px }` rule at runtime at equal specificity — a
     plain rule loses the cascade tie, so the bar stays put (verified: without !important
     the top entry is still intercepted). */
  .plot :global(.modebar) {
    left: 0 !important;
    right: auto !important;
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
