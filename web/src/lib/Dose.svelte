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
    MODALITY_UNCERTAINTY,
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

  // Cap the rendered per-line rows: a big chain (e.g. U-238) has 100+ scored lines, almost
  // all negligible, and the table re-renders every animate frame. Show the top contributors
  // (already sorted desc) and roll the tail into one honest "+ N more" line — never silently
  // dropped (§11). Co-60's 6 lines fall well under the cap.
  const MAX_LINE_ROWS = 15;

  let plotEl = $state<HTMLDivElement | null>(null);
  let distEl = $state<HTMLDivElement | null>(null);

  // -- local input bindings (commit to the store on change) ----------------------
  // `mode` (above) and `expUnit` are EPHEMERAL by design (M6h #4) — cosmetic / display-unit
  // state, not persisted. `distanceStr`/`expVal` mirror the store inputs.
  let distanceStr = $state<string>("1");
  let expVal = $state<number | null>(1);
  let expUnit = $state<string>("h");

  // Keep the entry fields in sync when the store changes them elsewhere — chiefly an M6h
  // state LOAD. Without this, after a load that changes distance/exposure the input boxes
  // show their stale initial value while the dose uses the loaded one — a §11 wrong-but-quiet
  // display mismatch (mirrors Shield.svelte's thickStr sync). No feedback loop: the setters'
  // no-op guards absorb a same-value write, and a Svelte effect does not fire change events.
  $effect(() => {
    distanceStr = String(appState.doseDistanceM);
    expVal = appState.exposureS / toSeconds(1, expUnit);
  });

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

  // Per-line γ table at the cursor (M6f-2, §9). `gLines` is null when the per-nuclide
  // activity is unavailable; we distinguish that (show a note) from "no decomposition at
  // all" so the table is never a silent blank (advisor; §11 activity-coupling guard).
  const gLines = $derived(appState.gammaLinesAtCursor);
  const gLinesUnavailable = $derived(appState.gammaLines !== null && appState.gammaLinesAtCursor === null);

  // -- Plotly bar (dual y-axis: Sv left for γ, Gy right for β) --------------------
  // Heights are the dose-RATE at the cursor (per hour). The two axes make the
  // "different quantities" explicit — γ reads against Sv·h⁻¹, β against Gy·h⁻¹.
  function perHour(v: number | null): number | null {
    return v == null ? null : v * 3600;
  }

  // Error whiskers (§9/§11): the per-modality epistemic register, shown ONLY on the
  // grouped (log) view — NOT the stacked bar, where cumulative segment positions make
  // per-segment whiskers ambiguous (§9). The whisker uses the CONSERVATIVE upper bound
  // (γ 15%, β 30%); the caption shows the full ±10–15% / ±20–30% range. On a log axis
  // ±15% stays well clear of zero (×0.85 / ×1.15), so the bars render sensibly.
  function whisker(modality: "gamma" | "beta"): Partial<Plotly.ErrorBar> {
    if (!isLog) return { visible: false };
    return {
      type: "percent",
      value: MODALITY_UNCERTAINTY[modality].hi * 100,
      visible: true,
      thickness: 1.5,
      width: 8,
    };
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
        error_y: whisker("gamma"),
        hovertemplate: "γ %{y:.3e} Sv/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
      {
        type: "bar",
        name: "β skin Hp(0.07), Gy",
        x: ["β"],
        y: [perHour(bRate)],
        yaxis: "y2",
        marker: { color: MODALITY_COLORS.beta },
        error_y: whisker("beta"),
        hovertemplate: "β %{y:.3e} Gy/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  // -- dose-vs-distance curve with the γ uncertainty fill band (M6f-2, §9) -------------
  // γ's distance dependence is EXACT inverse-square here (the per-decay coefficient is
  // distance-independent; v1 models no air attenuation, §11), so the whole curve is
  // reconstructed client-side from the cursor rate `rate(d)=rate(d₀)·(d₀/d)²` — zero
  // engine calls. The shaded ±band is the γ register (±15% conservative); the curve is a
  // slope-−2 line, so the BAND is the information. β is contact-dominated (non-inverse-
  // square distance model) and not shown here; neutron (order-of-mag) arrives with the
  // prebuilt sources (M7) — that is where the "tight γ vs fat n" contrast lands (§9).
  const DIST_RGBA = "rgba(78,121,167,0.18)"; // MODALITY_COLORS.gamma at low alpha (band fill)

  function distanceTraces(): Partial<Plotly.PlotData>[] {
    const rate0 = gRate; // Sv/s at the current distance
    const d0 = appState.doseDistanceM;
    if (rate0 == null || !(d0 > 0)) return [];
    const u = MODALITY_UNCERTAINTY.gamma;
    const lo = Math.max(d0 / 10, 0.01);
    const hi = d0 * 10;
    const N = 48;
    const xs: number[] = [];
    const yc: number[] = [];
    const yUp: number[] = [];
    const yLo: number[] = [];
    const la = Math.log10(lo);
    const lb = Math.log10(hi);
    for (let i = 0; i < N; i++) {
      const d = 10 ** (la + ((lb - la) * i) / (N - 1));
      const r = rate0 * (d0 / d) ** 2 * 3600; // Sv/h
      xs.push(d);
      yc.push(r);
      yUp.push(r * (1 + u.hi));
      yLo.push(r * (1 - u.hi));
    }
    return [
      // lower edge (invisible line) then upper edge filling down to it = the shaded band.
      { x: xs, y: yLo, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: yUp,
        mode: "lines",
        line: { width: 0 },
        fill: "tonexty",
        fillcolor: DIST_RGBA,
        hoverinfo: "skip",
        showlegend: false,
      } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: yc,
        mode: "lines",
        line: { color: MODALITY_COLORS.gamma, width: 2 },
        name: `γ ${qShort}`,
        hovertemplate: "%{x:.3g} m → %{y:.3e} Sv/h<extra></extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function distanceLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 72, r: 20, t: 10, b: 42 },
      showlegend: false,
      xaxis: { type: "log", title: { text: "distance (m)" }, automargin: true },
      yaxis: { type: "log", title: { text: `γ ${qShort} dose rate (Sv·h⁻¹)` }, automargin: true },
      shapes: [
        {
          type: "line",
          x0: appState.doseDistanceM,
          x1: appState.doseDistanceM,
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

  // Dose-vs-distance curve: re-react on the cursor rate, the distance (marker + range),
  // and the quantity label. Pure client-side reconstruction — no bridge call (§3).
  $effect(() => {
    void gRate;
    void appState.doseDistanceM;
    void qShort;
    const el = distEl;
    if (!el) return;
    if (!hasDose || gRate == null) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, distanceTraces(), distanceLayout(), { responsive: true, displaylogo: false });
  });

  onDestroy(() => {
    if (plotEl) Plotly.purge(plotEl);
    if (distEl) Plotly.purge(distEl);
  });
</script>

{#if appState.solveMeta}
  <section class="dose" data-testid="dose">
    <header>
      <h2>Dose</h2>
      <span class="readout muted">
        external · point source in air · at <strong>{humanTime(appState.currentTimeS)}</strong>
        {#if appState.shieldActive}
          · <strong class="shielded" data-testid="dose-shield-tag"
            >through {appState.shieldMaterial} {appState.shieldThicknessCm} cm</strong
          >
        {/if}
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

      <!-- Breakdown bar: dual-axis (γ→Sv, β→Gy); never one summed scale (#1). The
           grouped (log) view carries the per-modality uncertainty whiskers (§9/§11). -->
      <div class="bar-head">
        <span class="muted">
          Breakdown (dose rate at cursor){#if isLog}
            · whiskers = γ {MODALITY_UNCERTAINTY.gamma.label}, β {MODALITY_UNCERTAINTY.beta.label}{/if}
        </span>
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

      <!-- Dose vs distance with the γ uncertainty fill band (§9/§11). γ-only (exact
           inverse-square); β is contact-dominated, n arrives with prebuilt sources (M7). -->
      <div class="bar-head">
        <span class="muted">
          Dose vs distance — γ ({qShort}), shaded ±band = {MODALITY_UNCERTAINTY.gamma.label} register
        </span>
      </div>
      <div class="plot dist" data-testid="dose-distance-plot" bind:this={distEl}></div>
      <p class="hint muted">
        γ falls as 1/distance² (exact here — v1 models no air attenuation, §11); the band is
        the model's accuracy register, not statistical error. β is a contact/near-contact
        skin hazard (not inverse-square) and is shown only in the breakdown bar; neutron
        (order-of-magnitude) lands with the prebuilt sources (M7), where the tight-γ-vs-fat-n
        contrast becomes the point.
      </p>

      <!-- Per-line γ table (§9): "the gamma slice expands to a per-line table", colored by
           parent species (#4). Live at the cursor: rate = 1/4πd²·coeff·A_n(cursor), all
           client-side off the distance/time-free coefficients (Design A; zero bridge calls). -->
      {#if appState.gammaLines}
        <details class="lines" data-testid="dose-lines" open>
          <summary>
            Per-line γ breakdown — {gLines ? gLines.rows.length : 0} scored line(s)
            <span class="muted">({qLabel}, Sv · at {humanTime(appState.currentTimeS)})</span>
          </summary>
          {#if gLinesUnavailable}
            <p class="note muted" data-testid="dose-lines-unavailable">
              per-line activity is unavailable at the cursor — table hidden rather than shown
              as a (misleading) zero (§11).
            </p>
          {:else if gLines}
            <table class="linetab">
              <thead>
                <tr>
                  <th>nuclide</th><th class="num">energy</th><th>origin</th>
                  <th class="num">yield</th><th class="num">dose rate</th><th class="num">% of γ</th>
                </tr>
              </thead>
              <tbody>
                {#each gLines.rows.slice(0, MAX_LINE_ROWS) as r (r.nuclide + ":" + r.E_MeV)}
                  <tr data-nuclide={r.nuclide} data-rate-si={r.rate_si}>
                    <td>
                      <span class="swatch" style="background:{appState.colors[r.nuclide] ?? '#888'}"></span>
                      {r.nuclide}
                    </td>
                    <td class="num">{(r.E_MeV * 1000).toFixed(1)} keV</td>
                    <td class="origin">{r.origin ?? "—"}</td>
                    <td class="num">{r.yield.toPrecision(3)}</td>
                    <td class="num">{formatDoseRate(r.rate_si, "Sv")}</td>
                    <td class="num">{(r.frac * 100).toFixed(1)}%</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if gLines.rows.length > MAX_LINE_ROWS}
              <p class="note muted small">
                + {gLines.rows.length - MAX_LINE_ROWS} more lower-contribution line(s)
                ({(
                  gLines.rows.slice(MAX_LINE_ROWS).reduce((s, r) => s + r.frac, 0) * 100
                ).toFixed(1)}% of γ) — not shown, not dropped.
              </p>
            {/if}
            {#if gammaWarnings.length > 0}
              <p class="note muted small">
                + {gammaWarnings.length} sub-{(
                  (appState.gammaLines.scoring_floor_MeV ?? 0.01) * 1000
                ).toFixed(0)} keV line(s) below the dose-scoring floor δ — excluded as negligible
                at distance (§11; listed under the scoring notes below).
              </p>
            {/if}
          {/if}
        </details>
      {/if}

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
        cards above carry the true magnitudes. Uncertainty is shown as whiskers on the
        grouped bar and a ±band on the distance curve — γ ≈ {MODALITY_UNCERTAINTY.gamma.label},
        β ≈ {MODALITY_UNCERTAINTY.beta.label} (model accuracy registers, not statistical
        error). <strong>Not for safety decisions</strong> (§11).
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
  .readout .shielded {
    color: #4e79a7;
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
  .plot.dist {
    height: 240px;
  }
  .lines {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .lines summary {
    cursor: pointer;
    font-weight: 600;
  }
  .linetab {
    border-collapse: collapse;
    width: 100%;
    margin-top: 0.5rem;
    font-variant-numeric: tabular-nums;
  }
  .linetab th,
  .linetab td {
    border-bottom: 1px solid #8883;
    padding: 0.25rem 0.5rem;
    text-align: left;
  }
  .linetab th.num,
  .linetab td.num {
    text-align: right;
  }
  .linetab td.origin {
    opacity: 0.75;
  }
  .note.small {
    font-weight: 400;
    font-size: 0.8rem;
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
