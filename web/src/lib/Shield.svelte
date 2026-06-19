<script lang="ts">
  // Shield builder (M6-ui M6g, §9). A PURE renderer over the store's shielded dose path:
  // it reads the precomputed γ series (shielded + unshielded baseline), the β-bremsstrahlung
  // series, and the Design-A dose-vs-thickness coefficient grid — all folded at the cursor
  // with ZERO bridge calls on scrub (the §3 payoff). It only calls store SETTERS, never the
  // BridgeClient, and never `solve()` — a shield is a pure evaluate (the gate asserts the
  // registry stays at 1 across a shield change).
  //
  // v1 is SINGLE-LAYER (§13 #2). The γ picker is restricted to the buildup materials
  // (`has_buildup`) because the γ engine raises for a shield without ANS-6.4.3 buildup
  // (M6g #2) — that flag is the no-drift gate that keeps a fail-loud material out of the
  // picker. High-Z materials stop β but convert it to penetrating bremsstrahlung photons:
  // "more lead can INCREASE dose" — surfaced as a warning + the brems readout (#6).
  import Plotly from "plotly.js-basic-dist-min";
  import { onDestroy } from "svelte";
  import { appState } from "./state.svelte";
  import { formatDoseRate } from "./dosemath";
  import { MATERIAL_GUIDANCE, MODALITY_COLORS, MODALITY_UNCERTAINTY, doseQuantityLabel, humanTime } from "./types";

  let thickEl = $state<HTMLDivElement | null>(null);
  let timeEl = $state<HTMLDivElement | null>(null);

  // -- local thickness binding (commit to the store on change) -------------------
  let thickStr = $state<string>(String(appState.shieldThicknessCm));
  $effect(() => {
    // keep the field in sync if the store thickness changes elsewhere (e.g. M6h load)
    thickStr = String(appState.shieldThicknessCm);
  });
  function onThickness() {
    const x = parseFloat(thickStr);
    if (Number.isFinite(x) && x >= 0) appState.setShieldThicknessCm(x);
    else thickStr = String(appState.shieldThicknessCm); // snap back to truth (§11)
  }
  function onMaterial(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    appState.setShieldMaterial(v === "" ? null : v);
  }

  // -- derived shield/dose readouts (cursor-indexed; reactive) -------------------
  // Buildup materials only (the γ-shield gate, M6g #2); `air` is excluded — a 1 cm air
  // "shield" is physically meaningless (air is the transport medium, not a shield layer).
  const buildupMaterials = $derived(
    appState.availableMaterials.filter((m) => m.has_buildup && m.id !== "air"),
  );
  const hasDose = $derived(appState.gammaDoseSeries !== null && appState.curveX.length > 0);
  const active = $derived(appState.shieldActive);
  const gShielded = $derived(appState.gammaRateAtCursor); // Sv/s through the shield
  const gBare = $derived(appState.gammaRateBareAtCursor); // Sv/s unshielded baseline
  const atten = $derived(appState.attenuationFactorAtCursor); // shielded/unshielded at cursor
  const bRate = $derived(appState.betaRateAtCursor); // Gy/s skin (is there a β emitter?)
  const brems = $derived(appState.bremsRateAtCursor); // Sv/s secondary γ from stopped β
  const tCurve = $derived(appState.gammaThicknessCurve); // {thicknesses_cm, rate_si} | null
  const qShort = $derived(appState.doseQuantity === "effective" ? "E" : "H*(10)");
  const qLabel = $derived(doseQuantityLabel(appState.doseQuantity, appState.doseGeometry));

  // High-Z + a β emitter present ⇒ the bremsstrahlung crossover is physically relevant.
  const highZ = $derived(appState.shieldMaterial !== null && (MATERIAL_GUIDANCE[appState.shieldMaterial]?.highZ ?? false));
  const bremsRelevant = $derived(active && highZ && bRate != null && bRate > 0);

  const matLabel = (id: string) => id.charAt(0).toUpperCase() + id.slice(1);

  // -- dose-vs-thickness curve with the γ uncertainty band (M6g #4, §9) ----------------
  // Unlike dose-vs-distance (exact inverse-square, reconstructed client-side), thickness
  // transmission B(E,μx)·exp(−μx) is nonlinear/per-line, so the curve comes from the engine's
  // distance/time-free coefficient grid, folded with the cursor activity client-side (Design A
  // → live on scrub, zero re-fetch). The selected thickness is a grid point, so the curve there
  // equals the breakdown bar's γ rate exactly. The shaded ±band is the γ register (#8).
  const THICK_RGBA = "rgba(78,121,167,0.18)"; // MODALITY_COLORS.gamma at low alpha (band fill)

  function thicknessTraces(): Partial<Plotly.PlotData>[] {
    if (!tCurve) return [];
    const u = MODALITY_UNCERTAINTY.gamma;
    const xs = tCurve.thicknesses_cm;
    const yc = tCurve.rate_si.map((r) => r * 3600); // Sv/h
    const yUp = yc.map((r) => r * (1 + u.hi));
    const yLo = yc.map((r) => r * (1 - u.hi));
    return [
      { x: xs, y: yLo, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: yUp,
        mode: "lines",
        line: { width: 0 },
        fill: "tonexty",
        fillcolor: THICK_RGBA,
        hoverinfo: "skip",
        showlegend: false,
      } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: yc,
        mode: "lines",
        line: { color: MODALITY_COLORS.gamma, width: 2 },
        name: `γ ${qShort}`,
        hovertemplate: "%{x:.3g} cm → %{y:.3e} Sv/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function thicknessLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 72, r: 20, t: 10, b: 42 },
      showlegend: false,
      xaxis: { title: { text: `${matLabel(appState.shieldMaterial ?? "")} thickness (cm)` }, automargin: true },
      yaxis: { type: "log", title: { text: `γ ${qShort} dose rate (Sv·h⁻¹)` }, automargin: true },
      shapes: [
        {
          type: "line",
          x0: appState.shieldThicknessCm,
          x1: appState.shieldThicknessCm,
          yref: "paper",
          y0: 0,
          y1: 1,
          line: { color: "#888", width: 1, dash: "dash" },
        },
      ],
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  // -- dose-vs-time: γ rate with vs without the shield, across the decay (M6g, §9) -----
  // Shown only when a shield is active (the unshielded line is the baseline; the gap IS the
  // shield's effect over time). Plotted against the display-time grid `curveX`, like the
  // overlay curves. Both are existing series — no extra bridge call.
  function timeTraces(): Partial<Plotly.PlotData>[] {
    const xs = appState.curveX;
    const sh = appState.gammaDoseSeries;
    const bare = appState.gammaDoseSeriesBare;
    if (!sh || !bare || xs.length === 0) return [];
    return [
      {
        x: xs,
        y: bare.rate_si.map((r) => r * 3600),
        mode: "lines",
        line: { color: "#888", width: 1.5, dash: "dot" },
        name: "no shield",
        hovertemplate: "%{x:.3g} s → %{y:.3e} Sv/h<extra>no shield</extra>",
      } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: sh.rate_si.map((r) => r * 3600),
        mode: "lines",
        line: { color: MODALITY_COLORS.gamma, width: 2 },
        name: `${matLabel(appState.shieldMaterial ?? "")} ${appState.shieldThicknessCm} cm`,
        hovertemplate: "%{x:.3g} s → %{y:.3e} Sv/h<extra>shielded</extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function timeLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 72, r: 20, t: 10, b: 42 },
      showlegend: true,
      legend: { orientation: "h", y: -0.2 },
      xaxis: { type: "log", title: { text: "time (s, since source age)" }, automargin: true },
      yaxis: { type: "log", title: { text: `γ ${qShort} dose rate (Sv·h⁻¹)` }, automargin: true },
      shapes: [
        {
          type: "line",
          x0: appState.cursorOffsetS,
          x1: appState.cursorOffsetS,
          yref: "paper",
          y0: 0,
          y1: 1,
          line: { color: "#888", width: 1, dash: "dash" },
        },
      ],
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  // Imperative Plotly sync. The thickness curve re-reacts on the folded curve (cursor/
  // distance), the selected thickness (marker), and the quantity label.
  $effect(() => {
    void tCurve;
    void appState.shieldThicknessCm;
    void qShort;
    const el = thickEl;
    if (!el) return;
    if (!active || !tCurve) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, thicknessTraces(), thicknessLayout(), { responsive: true, displaylogo: false });
  });

  $effect(() => {
    void appState.gammaDoseSeries;
    void appState.gammaDoseSeriesBare;
    void appState.cursorOffsetS;
    void qShort;
    const el = timeEl;
    if (!el) return;
    if (!active) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, timeTraces(), timeLayout(), { responsive: true, displaylogo: false });
  });

  onDestroy(() => {
    if (thickEl) Plotly.purge(thickEl);
    if (timeEl) Plotly.purge(timeEl);
  });
</script>

{#if appState.solveMeta && hasDose}
  <section class="shield" data-testid="shield">
    <header>
      <h2>Shield</h2>
      <span class="readout muted">
        single layer · point source in air · at <strong>{humanTime(appState.currentTimeS)}</strong>
      </span>
    </header>

    {#if appState.doseError}
      <p class="note error" role="alert">⚠ shielded dose failed — {appState.doseError}</p>
    {:else}
      <div class="inputs">
        <label>
          Material
          <select data-testid="shield-material" value={appState.shieldMaterial ?? ""} onchange={onMaterial}>
            <option value="">None (no shield)</option>
            {#each buildupMaterials as m (m.id)}
              <option value={m.id}>{matLabel(m.id)} ({m.density_g_cm3} g/cm³)</option>
            {/each}
          </select>
        </label>

        <label class:disabled={!appState.shieldMaterial}>
          Thickness
          <input
            type="number"
            min="0"
            step="any"
            data-testid="shield-thickness"
            disabled={!appState.shieldMaterial}
            bind:value={thickStr}
            onchange={onThickness}
            onkeydown={(e) => e.key === "Enter" && onThickness()}
          />
          cm
        </label>

        {#if active}
          <button class="clear" data-testid="shield-clear" onclick={() => appState.clearShield()}>
            Remove shield
          </button>
        {/if}
      </div>

      {#if !active}
        <p class="note muted">
          Pick a material to attenuate the γ dose. Only materials with ANS-6.4.3 buildup data
          are offered (a shield without scatter buildup is a data hole, not a transparent
          medium — §11); PMMA / polyethylene and neutron-hydrogenous steering arrive with the
          neutron sources (M7).
        </p>
      {:else}
        <!-- With / without + attenuation factor (γ, at the cursor) -->
        <div class="cards">
          <div class="card" data-testid="shield-gamma" data-shielded-si={gShielded ?? ""} data-bare-si={gBare ?? ""}>
            <div class="card-h">
              <span class="swatch" style="background:{MODALITY_COLORS.gamma}"></span>
              γ — {qLabel} <span class="unit">(Sv)</span>
            </div>
            <div class="row">
              <span class="muted">without shield</span>
              <strong>{gBare == null ? "—" : formatDoseRate(gBare, "Sv")}</strong>
            </div>
            <div class="row">
              <span class="muted">with {matLabel(appState.shieldMaterial ?? "")} {appState.shieldThicknessCm} cm</span>
              <strong>{gShielded == null ? "—" : formatDoseRate(gShielded, "Sv")}</strong>
            </div>
            <div class="row big">
              <span class="muted">attenuation factor</span>
              <strong data-testid="shield-atten"
                >{atten == null ? "—" : atten < 1e-3 ? atten.toExponential(2) : atten.toFixed(3)}×</strong
              >
            </div>
          </div>

          <div class="card brems" class:grayed={!bremsRelevant} data-testid="shield-brems" data-brems-si={brems ?? ""}>
            <div class="card-h">
              <span class="swatch" style="background:{MODALITY_COLORS.gamma}"></span>
              β → bremsstrahlung γ <span class="unit">(Sv)</span>
            </div>
            <div class="big">{brems == null || brems === 0 ? "—" : formatDoseRate(brems, "Sv")}</div>
            <div class="sub muted">
              secondary photons from β stopped in the shield — a γ (Sv) quantity, shown beside
              the skin β (Gy), never summed into it.
            </div>
          </div>
        </div>

        {#if bremsRelevant}
          <p class="note warn" data-testid="shield-highz-warn">
            ⚠ {matLabel(appState.shieldMaterial ?? "")} is high-Z: it stops the β but converts it
            into penetrating bremsstrahlung photons — <strong>more shield can increase the total
            (photon) dose</strong>. For a β emitter, a low-Z shield (aluminium, water) first, then
            high-Z for the γ, is the standard order.
          </p>
        {/if}

        <!-- Dose vs thickness with the γ uncertainty band (§9/§11). -->
        <div class="bar-head">
          <span class="muted">
            Dose vs thickness — γ ({qShort}), shaded ±band = {MODALITY_UNCERTAINTY.gamma.label} register
          </span>
        </div>
        {#if tCurve}
          <div class="plot" data-testid="shield-thickness-plot" bind:this={thickEl}></div>
        {:else}
          <p class="note muted" data-testid="shield-thickness-unavailable">
            per-nuclide activity is unavailable at the cursor — thickness curve hidden rather
            than shown as a (misleading) zero (§11).
          </p>
        {/if}

        <!-- Dose vs time: shielded vs unshielded across the decay (§9). -->
        <div class="bar-head">
          <span class="muted">Dose vs time — γ ({qShort}), shielded vs unshielded (cursor dashed)</span>
        </div>
        <div class="plot" data-testid="shield-time-plot" bind:this={timeEl}></div>

        <p class="hint muted">
          Single-layer point-kernel shield: narrow-beam attenuation corrected by the ANS-6.4.3
          exposure buildup factor (applied to all quantities — a documented approximation, §11).
          The attenuation factor is the γ transmission <em>at the cursor</em> (spectrum- and
          time-dependent, not a constant μx). One solve, evaluated many (§3) — the shield
          re-folds the coefficients; the cursor just indexes. <strong>Not for safety
          decisions</strong> (§11).
        </p>
      {/if}
    {/if}
  </section>
{/if}

<style>
  .shield {
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
  .inputs label.disabled {
    opacity: 0.5;
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
  button.clear {
    cursor: pointer;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    background: transparent;
  }
  .cards {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-top: 1rem;
  }
  .card {
    flex: 1 1 14rem;
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
    margin-bottom: 0.35rem;
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
  .row {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    font-variant-numeric: tabular-nums;
    padding: 0.1rem 0;
  }
  .row.big {
    font-size: 1.1rem;
    border-top: 1px solid #8883;
    margin-top: 0.3rem;
    padding-top: 0.35rem;
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
    height: 240px;
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
  .muted {
    opacity: 0.7;
    font-weight: 400;
  }
  .hint {
    margin: 0.7rem 0 0;
    font-size: 0.85rem;
  }
</style>
