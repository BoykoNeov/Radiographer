<script lang="ts">
  // The prebuilt source catalog picker (M7 / §8): SELECT a named source from a compact
  // list, review its exact composition (incl. a summed TOTAL — how much of it "Load"
  // would bring in, e.g. "962,112 g (962 kg)" for a spent-fuel vector), optionally
  // scale it, then commit with "Load". "Load" REPLACES the whole inventory (mirrors
  // loadFromText, not an append — the button says so) — its source-age, and (for
  // neutron sources) its tabulated neutron term populate, then every view evolves
  // live off the one Bateman solve.
  //
  // Two-step (select → Load) rather than one-click-loads, on purpose: a click on the
  // list is free to browse (nothing changes until "Load"), and it's where the scale
  // control and the total-amount preview live (§9 ask: "what amount is actually
  // added?" was previously invisible — the per-isotope table alone doesn't answer it
  // for a many-nuclide source like spent fuel).
  import { appState } from "./state.svelte";
  import { sourcesByCategory, type PrebuiltSource } from "./sources";
  import { DISPLAY_DIGITS_OPTIONS, UNIT_OPTIONS } from "./types";
  import { fmtQuantity } from "./format";
  import Term from "./Term.svelte";
  import LearnMore from "./LearnMore.svelte";

  // Static manifest sources + the runtime spent-fuel catalog (inventory from validated
  // data/spent_fuel, fetched after boot). Each spent-fuel vector is its own category group,
  // appended after the static ones so the picker shows them once the engine is ready.
  const groups = $derived.by(() => {
    const g = sourcesByCategory();
    // Runtime catalogs (inventory from validated data/): spent fuel (M7c) + fallout (M7d).
    for (const s of [...appState.spentFuelSources, ...appState.falloutSources]) {
      let grp = g.find((x) => x.category === s.category);
      if (!grp) {
        grp = { category: s.category, sources: [] };
        g.push(grp);
      }
      grp.sources.push(s);
    }
    return g;
  });

  let selectedId = $state<string | null>(null);
  let scale = $state(1);
  let loadingId = $state<string | null>(null);
  let loadError = $state("");

  const selected = $derived.by(() => {
    for (const g of groups) {
      const s = g.sources.find((x) => x.id === selectedId);
      if (s) return s;
    }
    return null;
  });

  function onSelect(s: PrebuiltSource) {
    selectedId = s.id;
    scale = 1;
    loadError = "";
  }

  async function onLoadClick() {
    const s = selected;
    if (!s) return;
    const sc = Number.isFinite(scale) && scale > 0 ? scale : 1;
    loadError = "";
    loadingId = s.id;
    const err = await appState.loadSource(s, sc);
    loadingId = null;
    if (err) loadError = `${s.label}: ${err}`;
  }

  function unitLabel(unit: string): string {
    return UNIT_OPTIONS.find((u) => u.value === unit)?.label ?? unit;
  }

  // Thousands-grouped fixed-decimal formatting for the "big and ordinary" range, with
  // scientific notation at the extremes (spent-fuel trace nuclides span many decades of
  // mass) — display only, never round-trip-exact. The number of digits after the decimal
  // point is the user's `displayDigits` setting (default 3, chosen for grams). The rule
  // itself lives in `format.ts`, shared with the Inventory quantity cells.
  function fmtQty(v: number): string {
    return fmtQuantity(v, appState.displayDigits);
  }

  // Sum entries by unit (the amount actually added, at the current scale) — the "how
  // much is this?" answer the flat per-isotope table alone doesn't give for a
  // many-nuclide source. Every shipped manifest uses one unit per source, but this
  // groups rather than assumes, so a future mixed-unit source degrades gracefully.
  function totalsByUnit(entries: PrebuiltSource["entries"], sc: number): { unit: string; total: number }[] {
    const totals = new Map<string, number>();
    for (const e of entries) {
      totals.set(e.unit, (totals.get(e.unit) ?? 0) + e.quantity * sc);
    }
    return [...totals.entries()].map(([unit, total]) => ({ unit, total }));
  }

  function totalLine(t: { unit: string; total: number }): string {
    let s = `${fmtQty(t.total)} ${unitLabel(t.unit)}`;
    if (t.unit === "g" && t.total >= 1000) s += ` (${fmtQty(t.total / 1000)} kg)`;
    else if (t.unit === "mg" && t.total >= 1000) s += ` (${fmtQty(t.total / 1000)} g)`;
    else if (t.unit === "Bq" && t.total >= 3.7e10) s += ` (${fmtQty(t.total / 3.7e10)} Ci)`;
    return s;
  }
</script>

<section class="sources">
  <h2>Prebuilt sources</h2>
  <p class="muted intro">
    Select a curated source to review its composition, adjust how much of it to load, then
    commit with "Load". <strong>Loading REPLACES the current inventory</strong> (the
    <Term term="source-age">source-age</Term>, and for neutron sources the tabulated neutron
    term, populate too), then every view evolves live. <strong>Educational/reference only</strong>,
    not for safety decisions (§11).
  </p>

  <LearnMore summary="What makes a source emit neutrons? (the “n” badge)">
    Most of these sources emit gamma and beta radiation; a few also emit neutrons — those carry
    a green <strong>n</strong> badge in the list. There are two ways a source makes neutrons:
    <Term term="spontaneous-fission">spontaneous fission</Term> and the
    <Term term="alpha-n">(α,n) reaction</Term>. A californium-252 check source, an
    americium-beryllium source, and cooled spent fuel all light up the neutron view for these
    reasons; an ordinary gamma source such as Co-60 or Cs-137 does not.
    {#snippet advanced()}
      Neutron output is shown only for prebuilt sources whose neutron term is tabulated (not
      derived), so a user-typed inventory shows the neutron card grayed (§6.3). For spent fuel
      the two terms are summed off the one decay solve, and the (α,n) share is displayed because
      it grows over decades as Am-241 ingrows — see the honesty register.
    {/snippet}
  </LearnMore>

  {#if !appState.ready}
    <p class="muted">Waiting for the engine to finish booting…</p>
  {/if}

  <div class="layout">
    <div class="list">
      {#each groups as g (g.category)}
        <div class="group">
          <h3>{g.category}</h3>
          {#each g.sources as s (s.id)}
            <button
              class="row"
              class:selected={selectedId === s.id}
              class:neutron={!!s.neutronSource}
              data-testid="source-{s.id}"
              onclick={() => onSelect(s)}
              disabled={!appState.ready || loadingId !== null}
              aria-pressed={selectedId === s.id}
              title={s.label}
            >
              <span class="label">{s.label}</span>
              {#if s.neutronSource}<span class="badge">n</span>{/if}
            </button>
          {/each}
        </div>
      {/each}
    </div>

    <div class="detail">
      {#if selected}
        {@const totals = totalsByUnit(selected.entries, scale)}
        <h3>{selected.label}</h3>
        <p class="blurb">{selected.blurb}</p>
        {#if selected.caveat}<p class="caveat">⚠ {selected.caveat}</p>{/if}

        <!-- The headline answer to "how much am I adding?" — right up top, ahead of the
             (possibly long, e.g. 67-nuclide spent fuel) per-isotope breakdown below. -->
        <p class="total">
          {#each totals as t, i (t.unit)}{i > 0 ? " + " : ""}Total: {totalLine(t)}{/each}
        </p>

        <!-- Display-only digit count. It rounds what is SHOWN here and in the table below;
             the loaded quantities keep their full accuracy (see fmtQty). -->
        <div class="digits">
          <label>
            Decimals shown:
            <select
              aria-label="Digits shown after the decimal point"
              value={appState.displayDigits}
              onchange={(ev) => appState.setDisplayDigits(Number((ev.target as HTMLSelectElement).value))}
            >
              {#each DISPLAY_DIGITS_OPTIONS as d (d)}
                <option value={d}>{d}</option>
              {/each}
            </select>
          </label>
          <span class="muted">display only — loaded amounts keep full accuracy</span>
        </div>

        <div class="entries-scroll">
          <table class="entries">
            <thead>
              <tr><th>Nuclide</th><th>Amount added</th></tr>
            </thead>
            <tbody>
              {#each selected.entries as e (e.name)}
                <tr>
                  <td>{e.name}</td>
                  <td>{fmtQty(e.quantity * scale)} {unitLabel(e.unit)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>

        <div class="addrow">
          <label>
            Scale:
            <input
              type="number"
              min="0"
              step="any"
              aria-label="Scale factor — how much of this source to load"
              bind:value={scale}
              disabled={loadingId !== null}
            />
            <span class="muted">× the amounts above</span>
          </label>
          <button
            data-testid="source-add"
            onclick={onLoadClick}
            disabled={!appState.ready || loadingId !== null}
            title="Replaces the current inventory with this source"
          >
            {loadingId === selected.id ? "Loading…" : "Load (replaces inventory)"}
          </button>
        </div>
      {:else}
        <p class="muted">Select a source on the left to see its composition before loading it.</p>
      {/if}

      {#if loadError}
        <p class="inline-error" role="alert">⚠ {loadError}</p>
      {/if}
    </div>
  </div>
</section>

<style>
  .sources {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  h2 {
    margin-top: 0;
  }
  h3 {
    font-size: 0.9rem;
    margin: 0 0 0.4rem;
  }
  .intro {
    margin-top: 0.25rem;
  }
  .muted {
    opacity: 0.7;
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(12rem, 16rem) 1fr;
    gap: 1rem;
    align-items: start;
  }
  .list .group h3 {
    margin-top: 0.7rem;
    font-size: 0.8rem;
    opacity: 0.85;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .list .group:first-child h3 {
    margin-top: 0;
  }
  .row {
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
    text-align: left;
    font: inherit;
    padding: 0.3rem 0.5rem;
    border: 1px solid transparent;
    border-radius: 0.3rem;
    background: transparent;
    cursor: pointer;
  }
  .row:hover:not(:disabled) {
    background: #4e79a722;
  }
  .row.selected {
    background: #4e79a733;
    border-color: #4e79a7;
    font-weight: 600;
  }
  .row.neutron.selected {
    border-color: #59a14f;
  }
  .row:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .badge {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    color: #fff;
    background: #59a14f;
    border-radius: 0.25rem;
    padding: 0 0.3rem;
    flex: none;
  }
  .detail {
    border: 1px solid #8884;
    border-radius: 0.45rem;
    padding: 0.7rem 0.9rem;
    min-height: 6rem;
  }
  .detail .blurb {
    font-size: 0.9rem;
    opacity: 0.85;
    margin: 0.2rem 0 0.5rem;
  }
  .caveat {
    font-size: 0.85rem;
    color: #8a6d00;
    margin: 0 0 0.5rem;
  }
  .entries-scroll {
    max-height: 14rem;
    overflow-y: auto;
    border: 1px solid #8884;
  }
  table.entries {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.85rem;
  }
  table.entries th {
    position: sticky;
    top: 0;
    background: canvas;
  }
  table.entries th,
  table.entries td {
    border: 1px solid #8884;
    padding: 0.2rem 0.5rem;
    text-align: left;
  }
  .total {
    font-weight: 600;
    margin: 0.5rem 0;
  }
  .digits {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    margin: 0 0 0.5rem;
    font-size: 0.9rem;
  }
  .digits label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
  .digits select {
    font: inherit;
  }
  .addrow {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
  }
  .addrow label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
  .addrow input {
    width: 6rem;
    font: inherit;
    padding: 0.3rem 0.5rem;
  }
  .addrow button {
    font: inherit;
    padding: 0.35rem 0.9rem;
  }
  .inline-error {
    color: #b3261e;
    margin: 0.6rem 0 0;
    font-size: 0.9rem;
  }
</style>
