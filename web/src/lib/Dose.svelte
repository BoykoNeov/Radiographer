<script lang="ts">
  // Dose calculator + breakdown (M6-ui M6f, §9). A PURE renderer: it reads the
  // store's precomputed γ/β dose-rate series (one evaluate per distance/quantity/
  // geometry, §3) and indexes it at the time cursor — moving the cursor or changing
  // the exposure makes NO bridge call (the M6d smooth-slider payoff). It only ever
  // calls store SETTERS, never the BridgeClient, and never `solve()`.
  //
  // The load-bearing honesty rule (M6f-dose.md #1; §6.2 LOCKED): γ (and neutron, M7)
  // are Sv (H*(10)/effective); β is a DIFFERENT quantity — Gy at 7 mg/cm² (Hp(0.07),
  // w_R=1). They render against SEPARATE y-axes and are NEVER summed into one total.
  // Accumulated dose INTEGRATES the rate over the exposure window (the store getters),
  // never rate×time (#2; §11). Neutron is grayed for user inventories (§6.3 gate).
  import Plotly from "plotly.js-basic-dist-min";
  import { onDestroy } from "svelte";
  import { appState } from "./state.svelte";
  import { formatDose, formatDoseRate } from "./dosemath";
  import {
    DOSE_QUANTITY_OPTIONS,
    GEOMETRY_OPTIONS,
    MODALITY_COLORS,
    TIME_UNITS,
    type DoseQuantity,
    doseQuantityLabel,
    humanTime,
    toSeconds,
  } from "./types";

  // -- two named breakdown modes (§9): "stacked (linear)" vs "grouped (log)" -----
  // The spec bundles bar-mode + axis-scale into one choice. Stacked-linear is the
  // default; grouped-log reveals small contributors (logs don't stack). Real stacking
  // (γ + n in Sv) appears once a prebuilt neutron source lands (M7); for a user
  // inventory the Sv axis carries γ only, so the toggle mostly switches the scale.
  let mode = $state<"stacked" | "grouped">("stacked");
  const isLog = $derived(mode === "grouped");

  let plotEl = $state<HTMLDivElement | null>(null);

  // -- local input bindings (commit to the store on change) ----------------------
  let distanceStr = $state<string>("1");
  let expVal = $state<number | null>(1);
  let expUnit = $state<string>("h");

  // Inputs snap BACK to the model on invalid entry — never leave the field showing a
  // value the dose isn't actually using (a UI-layer wrong-but-quiet; §11). The setters
  // reject ≤0 / NaN (γ is singular at distance 0), so we re-display the live value.
  function onDistance() {
    const d = parseFloat(distanceStr);
    if (Number.isFinite(d) && d > 0) appState.setDoseDistanceM(d);
    else distanceStr = String(appState.doseDistanceM);
  }
  function onExposure() {
    if (expVal !== null && Number.isFinite(expVal) && expVal >= 0) {
      appState.setExposureS(toSeconds(expVal, expUnit));
    } else {
      expVal = appState.exposureS / toSeconds(1, expUnit); // snap back to truth
    }
  }

  // -- derived dose readouts (cursor-indexed; reactive on cursor/exposure) --------
  const gRate = $derived(appState.gammaRateAtCursor); // Sv/s, null when no series
  const bRate = $derived(appState.betaRateAtCursor); // Gy/s
  const gAcc = $derived(appState.gammaAccumulated); // {value Sv, truncated}
  const bAcc = $derived(appState.betaAccumulated); // {value Gy, truncated}
  const qLabel = $derived(doseQuantityLabel(appState.doseQuantity, appState.doseGeometry));
  const qShort = $derived(appState.doseQuantity === "effective" ? "E" : "H*(10)");

  // The dose breakdown needs the rate series (a stable inventory has none).
  const hasDose = $derived(appState.gammaDoseSeries !== null && appState.curveX.length > 0);
  // Below-floor X-ray skips etc. are recorded at build time on the γ series (#3).
  const gammaWarnings = $derived(appState.gammaDoseSeries?.warnings ?? []);
  const truncated = $derived((gAcc?.truncated ?? false) || (bAcc?.truncated ?? false));

  // -- Plotly bar (dual y-axis: Sv left for γ, Gy right for β) --------------------
  // Heights are the dose-RATE at the cursor (per hour). The two axes make the
  // "different quantities" explicit — γ reads against Sv·h⁻¹, β against Gy·h⁻¹.
  function perHour(v: number | null): number | null {
    return v == null ? null : v * 3600;
  }

  function barTraces(): Partial<Plotly.PlotData>[] {
    return [
      {
        type: "bar",
        name: `γ (${qShort}, Sv)`,
        x: ["γ"],
        y: [perHour(gRate)],
        yaxis: "y",
        marker: { color: MODALITY_COLORS.gamma },
        hovertemplate: "γ %{y:.3e} Sv/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
      {
        type: "bar",
        name: "β skin Hp(0.07), Gy",
        x: ["β"],
        y: [perHour(bRate)],
        yaxis: "y2",
        marker: { color: MODALITY_COLORS.beta },
        hovertemplate: "β %{y:.3e} Gy/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function barLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 70, r: 70, t: 10, b: 30 },
      barmode: mode === "stacked" ? "stack" : "group",
      showlegend: true,
      legend: { orientation: "h", y: -0.15 },
      yaxis: {
        type: isLog ? "log" : "linear",
        title: { text: "γ / n dose rate (Sv·h⁻¹)" },
        automargin: true,
        rangemode: "tozero",
      },
      yaxis2: {
        type: isLog ? "log" : "linear",
        title: { text: "β skin dose rate (Gy·h⁻¹)" },
        overlaying: "y",
        side: "right",
        automargin: true,
        rangemode: "tozero",
      },
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  // Imperative sync: re-react on any change to the rates (cursor/exposure-driven),
  // mode, or the quantity label. A 2-bar react is cheap enough to ride the cursor.
  $effect(() => {
    void gRate;
    void bRate;
    void mode;
    void qShort;
    const el = plotEl;
    if (!el) return;
    if (!hasDose) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, barTraces(), barLayout(), { responsive: true, displaylogo: false });
  });

  onDestroy(() => {
    if (plotEl) Plotly.purge(plotEl);
  });
</script>

{#if appState.solveMeta}
  <section class="dose" data-testid="dose">
    <header>
      <h2>Dose</h2>
      <span class="readout muted">
        external · point source in air · at <strong>{humanTime(appState.currentTimeS)}</strong>
      </span>
    </header>

    {#if appState.doseError}
      <p class="note error" role="alert">⚠ dose failed — {appState.doseError}</p>
    {:else if !hasDose}
      <p class="note muted">
        All loaded nuclides are stable — no activity, so no external dose.
      </p>
    {:else}
      <!-- Inputs: distance, quantity (+ geometry when effective), exposure -->
      <div class="inputs">
        <label>
          Distance
          <input
            type="number"
            min="0.001"
            step="any"
            data-testid="dose-distance"
            bind:value={distanceStr}
            onchange={onDistance}
            onkeydown={(e) => e.key === "Enter" && onDistance()}
          />
          m
        </label>

        <div class="q-toggle" role="group" aria-label="Dose quantity" data-testid="dose-quantity">
          {#each DOSE_QUANTITY_OPTIONS as opt (opt.value)}
            <button
              class:selected={appState.doseQuantity === opt.value}
              aria-pressed={appState.doseQuantity === opt.value}
              data-testid="dose-quantity-{opt.value}"
              onclick={() => appState.setDoseQuantity(opt.value as DoseQuantity)}
            >
              {opt.label}
            </button>
          {/each}
        </div>

        {#if appState.doseQuantity === "effective"}
          <label title="ICRP-116 irradiation geometry (§13 #3 default AP).">
            Geometry
            <select
              data-testid="dose-geometry"
              value={appState.doseGeometry}
              onchange={(e) => appState.setDoseGeometry((e.target as HTMLSelectElement).value)}
            >
              {#each GEOMETRY_OPTIONS as g (g.value)}
                <option value={g.value}>{g.label}</option>
              {/each}
            </select>
          </label>
        {/if}

        <label>
          Exposure
          <input
            type="number"
            min="0"
            step="any"
            data-testid="dose-exposure"
            bind:value={expVal}
            onchange={onExposure}
            onkeydown={(e) => e.key === "Enter" && onExposure()}
          />
          <select data-testid="dose-exposure-unit" bind:value={expUnit} onchange={onExposure}>
            {#each TIME_UNITS as u (u.value)}
              <option value={u.value}>{u.label}</option>
            {/each}
          </select>
        </label>
      </div>

      <!-- Numeric readouts: γ (Sv) and β (Gy) kept distinct; n grayed (§6.3). -->
      <div class="cards">
        <div class="card gamma" data-testid="dose-gamma" data-rate-si={gRate ?? ""}>
          <div class="card-h">
            <span class="swatch" style="background:{MODALITY_COLORS.gamma}"></span>
            γ — {qLabel} <span class="unit">(Sv)</span>
          </div>
          <div class="big">{gRate == null ? "—" : formatDoseRate(gRate, "Sv")}</div>
          <div class="sub muted">
            accumulated over {humanTime(appState.exposureS)}:
            <strong>{gAcc == null ? "—" : formatDose(gAcc.value, "Sv")}</strong>
          </div>
        </div>

        <div class="card beta" data-testid="dose-beta" data-rate-si={bRate ?? ""}>
          <div class="card-h">
            <span class="swatch" style="background:{MODALITY_COLORS.beta}"></span>
            β — skin Hp(0.07) <span class="unit">(Gy, w<sub>R</sub>=1)</span>
          </div>
          <div class="big">{bRate == null ? "—" : formatDoseRate(bRate, "Gy")}</div>
          <div class="sub muted">
            accumulated: <strong>{bAcc == null ? "—" : formatDose(bAcc.value, "Gy")}</strong>
            — a different quantity, not added to γ
          </div>
        </div>

        <div class="card neutron grayed" data-testid="dose-neutron">
          <div class="card-h">
            <span class="swatch" style="background:{MODALITY_COLORS.neutron}"></span>
            n — neutron
          </div>
          <div class="big">N/A</div>
          <div class="sub muted">prebuilt neutron sources only (Cf-252…); arrives in M7</div>
        </div>
      </div>

      <!-- Breakdown bar: dual-axis (γ→Sv, β→Gy); never one summed scale (#1). -->
      <div class="bar-head">
        <span class="muted">Breakdown (dose rate at cursor)</span>
        <div class="mode-toggle" role="group" aria-label="Breakdown scale" data-testid="dose-mode">
          <button class:selected={mode === "stacked"} onclick={() => (mode = "stacked")}>
            Stacked (linear)
          </button>
          <button class:selected={mode === "grouped"} onclick={() => (mode = "grouped")}>
            Grouped (log)
          </button>
        </div>
      </div>
      <div class="plot" data-testid="dose-plot" bind:this={plotEl}></div>

      {#if truncated}
        <p class="note warn" data-testid="dose-truncated">
          ⚠ the exposure window extends past the modeled time range — accumulated dose
          is the in-range part only (not silently extrapolated, §11).
        </p>
      {/if}

      {#if gammaWarnings.length > 0}
        <details class="warnings" data-testid="dose-warnings">
          <summary>{gammaWarnings.length} γ scoring note(s) — below-floor lines skipped</summary>
          <ul>
            {#each gammaWarnings as w, i (i)}
              <li class="mono">{w.nuclide ?? "?"}: {w.message ?? w.reason ?? "skipped"}</li>
            {/each}
          </ul>
        </details>
      {/if}

      <p class="hint muted">
        Point-source external dose in air, evaluated at the time cursor; one solve,
        evaluated many (§3) — distance/quantity/geometry recompute the rate series,
        the cursor &amp; exposure just index/integrate it. <strong>γ/n (Sv) and β
        (Gy, Hp(0.07)) are different quantities on separate axes — never summed, and
        their bar heights are NOT comparable across quantities</strong> (§6.2); the
        cards above carry the true magnitudes. γ ≈ ±10–15%, β ≈ ±20–30% (uncertainty
        bands land in M6f-2). <strong>Not for safety decisions</strong> (§11).
      </p>
    {/if}
  </section>
{/if}

<style>
  .dose {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  header {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
    margin-right: auto;
  }
  .readout {
    font-size: 0.9rem;
  }
  .inputs {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 0.75rem;
  }
  .inputs label {
    display: inline-flex;
    gap: 0.35rem;
    align-items: center;
  }
  input,
  select,
  button {
    font: inherit;
    padding: 0.3rem 0.5rem;
  }
  .inputs input[type="number"] {
    width: 6rem;
  }
  .q-toggle,
  .mode-toggle {
    display: inline-flex;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .q-toggle button,
  .mode-toggle button {
    border: none;
    background: transparent;
    cursor: pointer;
    border-left: 1px solid #8886;
  }
  .q-toggle button:first-child,
  .mode-toggle button:first-child {
    border-left: none;
  }
  .q-toggle button.selected,
  .mode-toggle button.selected {
    background: #4e79a7;
    color: #fff;
    font-weight: 600;
  }
  .cards {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-top: 1rem;
  }
  .card {
    flex: 1 1 12rem;
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 0.6rem 0.8rem;
  }
  .card.grayed {
    opacity: 0.55;
  }
  .card-h {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .swatch {
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 2px;
    display: inline-block;
  }
  .unit {
    font-weight: 400;
    opacity: 0.75;
  }
  .big {
    font-size: 1.3rem;
    font-weight: 700;
    margin: 0.25rem 0;
    font-variant-numeric: tabular-nums;
  }
  .sub {
    font-size: 0.82rem;
  }
  .bar-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-top: 1rem;
    flex-wrap: wrap;
  }
  .plot {
    width: 100%;
    height: 260px;
    margin-top: 0.4rem;
  }
  .note {
    margin: 0.75rem 0 0;
    font-weight: 600;
  }
  .note.error {
    color: #b3261e;
  }
  .note.warn {
    color: #8a6d00;
    font-weight: 500;
  }
  .warnings {
    margin-top: 0.6rem;
    font-size: 0.85rem;
  }
  .warnings ul {
    margin: 0.3rem 0 0;
    padding-left: 1.2rem;
  }
  .mono {
    font-family: ui-monospace, monospace;
    font-size: 0.78rem;
  }
  .muted {
    opacity: 0.7;
    font-weight: 400;
  }
  .hint {
    margin: 0.7rem 0 0;
    font-size: 0.85rem;
  }
</style>
