<script lang="ts">
  // Internal / committed dose panel (M13 §M13). The INTAKE pathway: committed effective dose
  // E(50) = Σ e_n[Sv/Bq]·A_n(t) — the committed dose that WOULD result from intaking the whole
  // inventory (by ingestion or inhalation) at the cursor time. A PURE renderer: it reads the
  // store's precomputed committed-Sv series (one fold per route/population, §3) and indexes it at
  // the cursor — moving the cursor or toggling route/population makes at most ONE re-fold, never a
  // re-solve (the gate asserts registry==1 across a toggle).
  //
  // The load-bearing quantity discipline (docs/plans/M13-internal-dose.md, §6.4/§11):
  //  · committed E(50) is a SCALAR in Sv (NOT a rate, NOT Sv/s) — so it is shown with formatDose,
  //    never formatDoseRate (the ×3600 trap), and there is NO accumulate/integrate control.
  //  · it is effective Sv but NEVER summed with external H*(10)/air-kerma — a different quantity,
  //    a different scenario (a hypothetical intake vs an external field).
  //  · the engine folds ONE default absorption type / chemical form / f1 per nuclide; the honesty
  //    block surfaces the ones where the alternative is materially higher (the wrong-but-quiet §11
  //    hazard), and the breakdown shows the folded type/form/f1 per nuclide (provenance, not buried).
  import Plotly from "plotly.js-basic-dist-min";
  import { onDestroy } from "svelte";
  import { appState } from "./state.svelte";
  import { formatDose } from "./dosemath";
  import {
    INTERNAL_POPULATION_OPTIONS,
    INTERNAL_ROUTE_OPTIONS,
    humanTime,
    internalRouteVerb,
    type InternalPopulation,
    type InternalRoute,
  } from "./types";

  // Cap the breakdown rows (a big chain has many contributors); the tail rolls into one honest
  // "+ N more" line — never silently dropped (§11). Mirrors the per-line γ table.
  const MAX_ROWS = 15;

  let plotEl = $state<HTMLDivElement | null>(null);

  const series = $derived(appState.internalDoseSeries);
  const committed = $derived(appState.internalCommittedAtCursor); // Sv scalar at cursor
  const breakdown = $derived(appState.internalBreakdownAtCursor);
  // The uncovered nuclides that actually CARRY ACTIVITY at the cursor (a stable end-product like
  // Pb-206 is uncovered in the engine's flag but contributes zero dose — not a real gap). This,
  // not the raw `series.lower_bound`, drives the loud banner — see internalActiveUncoveredAtCursor.
  const activeUncovered = $derived(appState.internalActiveUncoveredAtCursor); // {nuclides, share} | null
  const verb = $derived(internalRouteVerb(appState.internalRoute));

  // The per-nuclide breakdown needs the activity series (the cursor fold); distinguish "activity
  // unavailable" (show a note) from "no decomposition" so the table is never a silent blank (§11).
  const breakdownUnavailable = $derived(series !== null && appState.activityAtCursor === null);

  // -- the three "committed ≈ 0 is not nothing" cases, driven off the FLAGS not the number (§11) --
  // (a) an uncovered nuclide WITH ACTIVITY ⇒ a real curated-set gap ⇒ LOWER BOUND (loud); (b)
  // noble-gas-only ⇒ no intake coefficient physically exists (submersion ≠ intake); (c) genuinely
  // no contributors. A stable-only uncovered set (Pb-206) is none of these — it contributes zero.
  const lowerBound = $derived(activeUncovered !== null);
  const nobleGasNA = $derived(series?.noble_gas_na ?? []);
  const hasContribution = $derived((breakdown?.total ?? 0) > 0);

  // Population/route provenance for the active scenario (route/population are ephemeral — label
  // them so a loaded state is never silently a different scenario than when it was saved).
  const pubLabel = $derived(
    INTERNAL_POPULATION_OPTIONS.find((p) => p.value === appState.internalPopulation)?.label ?? "",
  );

  /** Prettify the folded absorption type / chemical-form token for the breakdown table. */
  function fmtType(tok: string | null): string {
    if (!tok) return "—";
    if (tok === "F" || tok === "M" || tok === "S") return `Type ${tok}`;
    if (tok === "vapour_elemental") return "elemental vapour";
    if (tok === "vapour_methyl") return "methyl vapour";
    return tok; // HTO / OBT
  }

  /** The folded provenance cell: inhalation → absorption type/form; ingestion → f1 (+ H-3 form). */
  function provenance(r: { type: string | null; form: string | null; f1: number | null }): string {
    if (appState.internalRoute === "inhalation") return fmtType(r.type);
    const f1 = r.f1 != null ? `f₁ ${r.f1.toPrecision(2)}` : "—";
    return r.form ? `${f1} (${r.form})` : f1;
  }

  // -- committed-dose-vs-intake-time curve (Sv, NOT Sv/s) ---------------------------
  // One plain trace of `committed_si` over `curveX`: "the committed E(50) if the inventory were
  // intaken at time t". No uncertainty band — there is no quantified internal-dose register, and a
  // fabricated band is worse than none (the honesty block carries uncertainty qualitatively).
  const INT_COLOR = "#6a51a3"; // purple — distinct from the external γ/β/n modality colors

  function curveTraces(): Partial<Plotly.PlotData>[] {
    if (!series) return [];
    return [
      {
        x: appState.curveX,
        y: series.committed_si,
        mode: "lines",
        line: { color: INT_COLOR, width: 2 },
        name: "committed E(50)",
        hovertemplate: "intake at %{x:.3g} s → %{y:.3e} Sv<extra></extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function curveLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 72, r: 20, t: 10, b: 42 },
      showlegend: false,
      xaxis: { type: "log", title: { text: "intake time (s)" }, automargin: true },
      yaxis: { type: "log", title: { text: "committed E(50) (Sv)" }, automargin: true },
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

  $effect(() => {
    void series;
    void appState.cursorOffsetS;
    const el = plotEl;
    if (!el) return;
    if (!series || !hasContribution) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, curveTraces(), curveLayout(), { responsive: true, displaylogo: false });
  });

  onDestroy(() => {
    if (plotEl) Plotly.purge(plotEl);
  });
</script>

{#if appState.solveMeta}
  <section class="internal" data-testid="internal-dose">
    <header>
      <h2>Committed dose <span class="muted">— internal / intake (§M13)</span></h2>
      <span class="readout muted">
        if the whole inventory were <strong>{verb}</strong> at
        <strong>{humanTime(appState.currentTimeS)}</strong>
      </span>
    </header>

    <!-- Route + population selectors (ingestion/inhalation × public-adult/worker). -->
    <div class="inputs">
      <div class="seg" role="group" aria-label="Intake route" data-testid="internal-route">
        {#each INTERNAL_ROUTE_OPTIONS as opt (opt.value)}
          <button
            class:selected={appState.internalRoute === opt.value}
            aria-pressed={appState.internalRoute === opt.value}
            data-testid="internal-route-{opt.value}"
            onclick={() => appState.setInternalRoute(opt.value as InternalRoute)}
          >
            {opt.label}
          </button>
        {/each}
      </div>
      <div class="seg" role="group" aria-label="Reference population" data-testid="internal-population">
        {#each INTERNAL_POPULATION_OPTIONS as opt (opt.value)}
          <button
            class:selected={appState.internalPopulation === opt.value}
            aria-pressed={appState.internalPopulation === opt.value}
            data-testid="internal-population-{opt.value}"
            onclick={() => appState.setInternalPopulation(opt.value as InternalPopulation)}
          >
            {opt.label}
          </button>
        {/each}
      </div>
    </div>

    {#if appState.internalDoseError}
      <p class="note error" role="alert">⚠ committed dose failed — {appState.internalDoseError}</p>
    {:else if !series}
      <p class="note muted">
        All loaded nuclides are stable — no activity to intake, so no committed dose.
      </p>
    {:else}
      <!-- Headline: committed E(50) SCALAR in Sv (formatDose, never a /h rate). -->
      <div class="card" data-testid="internal-card" data-committed-si={committed ?? ""}>
        <div class="card-h">
          committed effective dose E(50) <span class="unit">(Sv)</span>
        </div>
        <div class="big">{committed == null ? "—" : formatDose(committed, "Sv")}</div>
        <div class="sub muted" data-testid="internal-provenance">
          {INTERNAL_ROUTE_OPTIONS.find((r) => r.value === appState.internalRoute)?.label}
          · {pubLabel}, {series.icrp_publication}
          {#if appState.internalRoute === "inhalation"}· {series.amad_um} µm AMAD{/if}
          · 50-yr committed, baked into the coefficient
        </div>
      </div>

      <!-- Lower bound (uncovered nuclides WITH ACTIVITY) — the dangerous (under-count) direction
           → LOUD (§11). Stable uncovered daughters (zero activity, zero dose) are NOT flagged.
           The activity-share is reported but explicitly NOT presented as the dose shortfall: for a
           short-lived equilibrium daughter (Ba-137m, 2.6 min) the activity share is large yet the
           omitted committed intake dose is negligible — the inverse honesty hazard, so the caveat
           is mandatory, not optional (the metric overstates the gap for short-lived progeny). -->
      {#if lowerBound && activeUncovered}
        <p class="note warn" data-testid="internal-lowerbound">
          ⚠ this E(50) is a <strong>LOWER BOUND</strong>: {activeUncovered.nuclides.length}
          still-active tracked nuclide(s) have no {appState.internalRoute} coefficient in the
          curated set ({activeUncovered.nuclides.join(", ")}) — their committed dose is omitted,
          not estimated.
        </p>
        <p class="note muted small" data-testid="internal-lowerbound-note">
          They carry ~{(activeUncovered.share * 100).toFixed(1)}% of the inventory's
          <em>activity</em> here — but activity share is not dose share: a short-lived equilibrium
          daughter (e.g. Ba-137m, 2.6 min) contributes a negligible committed intake dose despite a
          large activity share, whereas a longer-lived omission (e.g. Y-90, Nb-95) genuinely matters.
        </p>
      {/if}

      <!-- Noble gases: no intake coefficient EXISTS (submersion is a different quantity) — does NOT
           make the result a lower bound (it would falsely imply a missing intake dose). -->
      {#if nobleGasNA.length > 0}
        <p class="note muted" data-testid="internal-noblegas">
          {nobleGasNA.join(", ")}: noble gas — no intake committed-dose coefficient exists
          (submersion is a different quantity, ICRP-119 Annex C); excluded, and it does NOT make
          this a lower bound.
        </p>
      {/if}

      {#if !hasContribution && !lowerBound && nobleGasNA.length === 0}
        <p class="note muted">No covered nuclide carries committed dose for this intake.</p>
      {/if}

      <!-- Per-nuclide breakdown at the cursor: e_n·A_n(cursor), with the FOLDED type/form/f1. -->
      {#if hasContribution}
        <details class="lines" data-testid="internal-breakdown" open>
          <summary>
            Per-nuclide breakdown — {breakdown ? breakdown.rows.filter((r) => r.committed_si > 0).length : 0}
            contributor(s)
            <span class="muted">(committed Sv · at {humanTime(appState.currentTimeS)})</span>
          </summary>
          {#if breakdownUnavailable}
            <p class="note muted" data-testid="internal-breakdown-unavailable">
              per-nuclide activity is unavailable at the cursor — table hidden rather than shown
              as a (misleading) zero (§11).
            </p>
          {:else if breakdown}
            <table class="tab">
              <thead>
                <tr>
                  <th>nuclide</th>
                  <th class="num">e(50)</th>
                  <th>{appState.internalRoute === "inhalation" ? "absorption" : "gut transfer"}</th>
                  <th class="num">committed</th>
                  <th class="num">% of E(50)</th>
                </tr>
              </thead>
              <tbody>
                {#each breakdown.rows.filter((r) => r.committed_si > 0).slice(0, MAX_ROWS) as r (r.nuclide)}
                  <tr data-nuclide={r.nuclide} data-committed-si={r.committed_si}>
                    <td>
                      <span class="swatch" style="background:{appState.colors[r.nuclide] ?? '#888'}"></span>
                      {r.nuclide}
                    </td>
                    <td class="num">{r.coeff.toExponential(2)} Sv/Bq</td>
                    <td class="prov">{provenance(r)}</td>
                    <td class="num">{formatDose(r.committed_si, "Sv")}</td>
                    <td class="num">{(r.frac * 100).toFixed(1)}%</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if breakdown.rows.filter((r) => r.committed_si > 0).length > MAX_ROWS}
              <p class="note muted small">
                + {breakdown.rows.filter((r) => r.committed_si > 0).length - MAX_ROWS} more
                lower-contribution nuclide(s) — not shown, not dropped.
              </p>
            {/if}
          {/if}
        </details>

        <!-- Committed E(50) vs intake-time (Sv, not Sv/s). -->
        <div class="bar-head">
          <span class="muted">Committed E(50) vs intake time — the curve is in Sv, not Sv/s</span>
        </div>
        <div class="plot" data-testid="internal-plot" bind:this={plotEl}></div>
      {/if}

      <!-- Honesty block (§11): the default-choice caveats the engine folds SILENTLY (one type/
           form/f1 per nuclide) — mandatory per docs/plans/M13-internal-dose.md step 8. -->
      <details class="honesty" data-testid="internal-honesty">
        <summary>What this number is — and is not</summary>
        <ul>
          <li>
            A <strong>hypothetical scenario</strong>: the committed effective dose a
            <strong>reference adult</strong> would receive over <strong>50 years</strong> if they
            intaked this entire inventory at the cursor time. It is NOT a measured field and NOT a
            received dose.
          </li>
          <li>
            <strong>Never comparable to / summed with</strong> the external H*(10) (Sv) or air-kerma
            (Gy) in the Dose panel — a different quantity and a different exposure scenario (§6.4).
          </li>
          <li>
            One <strong>default absorption type / chemical form / f₁</strong> is folded per nuclide
            (shown in the breakdown). Real intakes vary by compound, particle size, and individual.
            Where the alternative is materially higher:
            <ul class="caveats">
              <li><strong>Po-210</strong> uses the default Type F; <strong>Type M is ~3× higher</strong>
                and is the value many regulatory tables cite — the default is the UNDER-estimate direction.</li>
              <li><strong>H-3</strong> ingestion uses HTO; <strong>organically-bound tritium (OBT) is
                ~2.3× higher</strong>.</li>
              <li><strong>Co-60</strong> inhalation uses Type M; the <strong>oxide (Type S) is ~2–3× higher</strong>.</li>
              <li><strong>Iodine</strong> inhalation uses elemental vapour; methyl is ~25% lower, and
                <strong>particulate iodine is not modeled</strong> (vapour-only scope) — a particulate
                textbook value (e.g. I-131 Type F adult ≈ 7.4e-9, ~2.7× below elemental) is a different case.</li>
            </ul>
          </li>
          <li>
            Coverage is a <strong>curated nuclide set</strong> — an uncovered tracked nuclide makes the
            result a <strong>lower bound</strong> (flagged above when it bites).
          </li>
          <li><strong>Not for safety decisions</strong> (§11).</li>
        </ul>
      </details>
    {/if}
  </section>
{/if}

<style>
  .internal {
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
  .seg {
    display: inline-flex;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .seg button {
    border: none;
    background: transparent;
    cursor: pointer;
    border-left: 1px solid #8886;
    font: inherit;
    padding: 0.3rem 0.7rem;
  }
  .seg button:first-child {
    border-left: none;
  }
  .seg button.selected {
    background: #6a51a3;
    color: #fff;
    font-weight: 600;
  }
  .card {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 0.6rem 0.8rem;
    margin-top: 1rem;
    max-width: 32rem;
  }
  .card-h {
    font-weight: 600;
    font-size: 0.9rem;
  }
  .unit {
    font-weight: 400;
    opacity: 0.75;
  }
  .big {
    font-size: 1.4rem;
    font-weight: 700;
    margin: 0.25rem 0;
    font-variant-numeric: tabular-nums;
  }
  .sub {
    font-size: 0.82rem;
  }
  .bar-head {
    margin-top: 1rem;
  }
  .plot {
    width: 100%;
    height: 240px;
    margin-top: 0.4rem;
  }
  .lines {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .lines summary,
  .honesty summary {
    cursor: pointer;
    font-weight: 600;
  }
  .tab {
    border-collapse: collapse;
    width: 100%;
    margin-top: 0.5rem;
    font-variant-numeric: tabular-nums;
  }
  .tab th,
  .tab td {
    border-bottom: 1px solid #8883;
    padding: 0.25rem 0.5rem;
    text-align: left;
  }
  .tab th.num,
  .tab td.num {
    text-align: right;
  }
  .tab td.prov {
    opacity: 0.85;
  }
  .swatch {
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 2px;
    display: inline-block;
  }
  .honesty {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .honesty ul {
    margin: 0.4rem 0 0;
    padding-left: 1.2rem;
  }
  .honesty .caveats {
    margin-top: 0.3rem;
  }
  .note {
    margin: 0.75rem 0 0;
    font-weight: 600;
  }
  .note.small {
    font-weight: 400;
    font-size: 0.8rem;
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
</style>
