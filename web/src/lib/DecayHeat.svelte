<script lang="ts">
  // Decay-heat (thermal power) readout (M7c / §5). Total W(t) = Σ A_n·Ē_rec,n folded from
  // the SAME bundled ICRP-107 emission spectra as γ/β dose — no new dataset. Live at the
  // cursor (pure index into the precomputed series; zero bridge calls on scrub, §3). Most
  // meaningful for spent fuel: scrub the cooling time to watch it fall orders of magnitude.
  import { appState } from "./state.svelte";
  import { formatDose } from "./dosemath";
  import { humanTime as fmtTime } from "./types";

  const total = $derived(appState.decayHeatAtCursor);
  const top = $derived(appState.decayHeatTopAtCursor);
  const def = $derived(appState.decayHeatSeries?.definition ?? "");
  // A spent-fuel vector is per tonne initial HM (the basis is in its data record); any other
  // inventory's heat is just "for the loaded inventory" at the loaded quantities.
  const perTonne = $derived(appState.entries.some((e) => e.unit === "g") && appState.entries.length > 20);
</script>

<section class="decayheat">
  <h2>Decay heat <span class="muted">— thermal power (§5)</span></h2>

  {#if appState.decayHeatError}
    <p class="inline-error" role="alert">⚠ {appState.decayHeatError}</p>
  {:else if total == null}
    <p class="muted">Load an inventory to see its decay heat. (Stable-only inventories emit none.)</p>
  {:else}
    <p class="readout">
      <span class="value">{formatDose(total, "W")}</span>
      <span class="muted">at cooling time {fmtTime(appState.cursorOffsetS)}</span>
      {#if perTonne}<span class="basis muted">— per tonne initial heavy metal</span>{/if}
    </p>

    {#if top && top.length}
      <table>
        <thead>
          <tr><th>nuclide</th><th>power</th><th>share</th></tr>
        </thead>
        <tbody>
          {#each top.slice(0, 8) as r (r.nuclide)}
            <tr>
              <td class="mono">{r.nuclide}</td>
              <td class="mono">{formatDose(r.W, "W")}</td>
              <td class="mono">{(r.frac * 100).toFixed(1)}%</td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if top.length > 8}<p class="muted small">+{top.length - 8} more contributors</p>{/if}
    {/if}

    <p class="muted small def">{def}</p>
  {/if}
</section>

<style>
  .decayheat {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  h2 {
    margin-top: 0;
    font-size: 1.05rem;
  }
  .muted {
    opacity: 0.7;
  }
  .small {
    font-size: 0.8rem;
  }
  .readout {
    margin: 0.4rem 0 0.8rem;
  }
  .value {
    font-size: 1.4rem;
    font-weight: 700;
    margin-right: 0.5rem;
  }
  .basis {
    font-size: 0.85rem;
  }
  table {
    border-collapse: collapse;
    width: auto;
    min-width: 18rem;
  }
  th,
  td {
    border: 1px solid #8884;
    padding: 0.25rem 0.7rem;
    text-align: left;
  }
  th {
    font-weight: 600;
    opacity: 0.8;
  }
  .mono {
    font-family: ui-monospace, monospace;
  }
  .def {
    margin-top: 0.7rem;
    max-width: 48rem;
  }
  .inline-error {
    color: #b3261e;
    font-size: 0.9rem;
  }
</style>
