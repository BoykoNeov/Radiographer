<script lang="ts">
  // The inventory panel (M6-ui M6b, §9): add-by-name + quantity + unit, edit/remove,
  // precision, reference time, save/load — all reading/writing the central app-state
  // store (the single source of truth). The solved-closure legend shows the shared
  // per-species palette that M6c/M6e/M6f will consume identically.
  import { appState } from "./state.svelte";
  import { UNIT_OPTIONS, DEFAULT_UNIT } from "./types";

  // Local draft for the add row (committed to the store on "Add").
  let draftName = $state("");
  let draftQty = $state<number | null>(null);
  let draftUnit = $state(DEFAULT_UNIT);
  let addError = $state("");

  let fileInput: HTMLInputElement;

  async function onAdd() {
    addError = "";
    const qty = draftQty ?? NaN;
    const err = await appState.addEntry(draftName, qty, draftUnit);
    if (err) {
      addError = err;
      return;
    }
    draftName = "";
    draftQty = null;
    draftUnit = DEFAULT_UNIT;
  }

  function onAddKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") onAdd();
  }

  async function onLoadFile(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) await appState.loadFile(file);
    input.value = ""; // allow re-loading the same file
  }

  // Edit an entry's quantity; if the store rejects it (e.g. cleared → NaN), snap the
  // input back to the stored value so the DOM never silently diverges from the model.
  async function onEditQty(i: number, prev: number, ev: Event) {
    const input = ev.target as HTMLInputElement;
    const err = await appState.updateEntry(i, { quantity: input.valueAsNumber });
    if (err) input.value = String(prev);
  }

  // Half-life formatting for the legend (seconds → readable). Engine gives the
  // canonical readable form via chain() in M6e; this is a light helper for M6b.
  const MIN = 60,
    HOUR = 3600,
    DAY = 86400,
    YEAR = 365.25 * 86400;
  function fmtHalfLife(s: number | null): string {
    if (s === null) return "stable";
    if (!Number.isFinite(s)) return "stable";
    if (s < MIN) return `${s.toPrecision(3)} s`;
    if (s < HOUR) return `${(s / MIN).toPrecision(3)} min`;
    if (s < DAY) return `${(s / HOUR).toPrecision(3)} h`;
    if (s < YEAR) return `${(s / DAY).toPrecision(3)} d`;
    return `${(s / YEAR).toPrecision(3)} yr`;
  }

  const halfLives = $derived(appState.solveMeta?.half_lives_s ?? {});
  const parentSet = $derived(new Set(appState.entries.map((e) => e.name)));
</script>

<section class="inventory">
  <h2>Inventory</h2>

  <!-- Add-by-name row -->
  <div class="addrow">
    <input
      class="name"
      list="nuclide-list"
      placeholder="nuclide (e.g. Co-60)"
      bind:value={draftName}
      onkeydown={onAddKeydown}
      disabled={!appState.ready}
    />
    <datalist id="nuclide-list">
      {#each appState.availableNuclides as n (n)}
        <option value={n}></option>
      {/each}
    </datalist>
    <input
      class="qty"
      type="number"
      min="0"
      step="any"
      placeholder="quantity"
      bind:value={draftQty}
      onkeydown={onAddKeydown}
      disabled={!appState.ready}
    />
    <select class="unit" bind:value={draftUnit} disabled={!appState.ready}>
      {#each UNIT_OPTIONS as u (u.value)}
        <option value={u.value}>{u.label}</option>
      {/each}
    </select>
    <button onclick={onAdd} disabled={!appState.ready}>Add</button>
  </div>
  {#if addError}
    <p class="inline-error" role="alert">{addError}</p>
  {/if}
  {#if !appState.ready}
    <p class="muted">Waiting for the engine to finish booting…</p>
  {/if}

  <!-- Loaded entries -->
  {#if appState.entries.length > 0}
    <table class="entries">
      <thead>
        <tr><th>Nuclide</th><th>Quantity</th><th>Unit</th><th></th></tr>
      </thead>
      <tbody>
        {#each appState.entries as e, i (e.name + ":" + i)}
          <tr>
            <td>
              <span class="swatch" style="background:{appState.colors[e.name] ?? 'transparent'}"></span>
              {e.name}
            </td>
            <td>
              <input
                class="qty"
                type="number"
                min="0"
                step="any"
                value={e.quantity}
                onchange={(ev) => onEditQty(i, e.quantity, ev)}
              />
            </td>
            <td>
              <select
                value={e.unit}
                onchange={(ev) => appState.updateEntry(i, { unit: (ev.target as HTMLSelectElement).value })}
              >
                {#each UNIT_OPTIONS as u (u.value)}
                  <option value={u.value}>{u.label}</option>
                {/each}
              </select>
            </td>
            <td><button class="remove" onclick={() => appState.removeEntry(i)} title="Remove">✕</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="muted">No isotopes loaded. Add one above to solve its decay chain.</p>
  {/if}

  <!-- Controls: precision, reference time -->
  <div class="controls">
    <label>
      Precision:
      <select
        value={appState.precision}
        onchange={(ev) => appState.setPrecision((ev.target as HTMLSelectElement).value as "double" | "hp")}
      >
        <option value="double">double</option>
        <option value="hp">high (arbitrary)</option>
      </select>
    </label>
    {#if appState.hpRecommended && appState.precision === "double"}
      <span class="hint" role="alert"
        >⚠ stiff chain — high precision recommended (double may suffer cancellation)</span
      >
    {/if}
    <!-- Reference time / source-age (t₀) now lives in the time control (M6d). -->
  </div>

  <!-- Save / load -->
  <div class="persist">
    <button onclick={() => appState.download()} disabled={appState.isEmpty}>Save JSON</button>
    <button onclick={() => fileInput.click()}>Load JSON</button>
    <input
      bind:this={fileInput}
      type="file"
      accept="application/json,.json"
      onchange={onLoadFile}
      style="display:none"
    />
  </div>

  <!-- Status -->
  {#if appState.status === "solving"}
    <p class="status solving">Solving…</p>
  {:else if appState.status === "error"}
    <p class="status error" role="alert">⚠ {appState.errorMsg}</p>
  {:else if appState.status === "solved" && appState.solveMeta}
    <p class="status ok">
      Solved: {appState.solveMeta.n_nuclides} nuclide(s) in the decay closure
      (precision: {appState.solveMeta.precision}).
    </p>
  {/if}

  <!-- Shared-palette legend over the full closure -->
  {#if appState.closure.length > 0}
    <div class="legend" data-testid="legend">
      <h3>Decay closure ({appState.closure.length})</h3>
      <ul>
        {#each appState.closure as n (n)}
          <li class:parent={parentSet.has(n)}>
            <span class="swatch" style="background:{appState.colors[n]}"></span>
            <span class="nname">{n}</span>
            <span class="muted hl">{fmtHalfLife(halfLives[n])}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  .inventory {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  h2 {
    margin-top: 0;
  }
  h3 {
    font-size: 0.95rem;
    margin: 0.75rem 0 0.4rem;
  }
  .addrow {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    align-items: center;
  }
  input,
  select,
  button {
    font: inherit;
    padding: 0.3rem 0.5rem;
  }
  .name {
    min-width: 12rem;
  }
  .qty {
    width: 9rem;
  }
  .inline-error,
  .status.error,
  .hint {
    color: #b3261e;
  }
  .inline-error {
    margin: 0.4rem 0 0;
    font-size: 0.9rem;
  }
  .muted {
    opacity: 0.7;
  }
  table.entries {
    border-collapse: collapse;
    width: 100%;
    margin-top: 0.75rem;
  }
  table.entries th,
  table.entries td {
    border: 1px solid #8884;
    padding: 0.3rem 0.5rem;
    text-align: left;
  }
  .remove {
    border: none;
    background: transparent;
    cursor: pointer;
    color: #b3261e;
    font-weight: 700;
  }
  .controls {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 0.75rem;
  }
  .controls label {
    display: inline-flex;
    gap: 0.4rem;
    align-items: center;
  }
  .persist {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
  }
  .status {
    margin: 0.75rem 0 0;
    font-weight: 600;
  }
  .status.ok {
    color: #1b7f3b;
  }
  .status.solving {
    color: #664d03;
  }
  .swatch {
    display: inline-block;
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 0.2rem;
    vertical-align: middle;
    margin-right: 0.35rem;
    border: 1px solid #0003;
  }
  .legend ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem 0.9rem;
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.9rem;
  }
  .legend li.parent .nname {
    font-weight: 700;
  }
  .legend .hl {
    font-size: 0.8rem;
  }
</style>
