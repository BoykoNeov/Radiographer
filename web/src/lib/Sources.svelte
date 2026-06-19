<script lang="ts">
  // The prebuilt source catalog picker (M7 / §8): one click loads a named source —
  // its inventory, source-age, and (for neutron sources) its tabulated neutron term —
  // into the central store, which re-solves and lights every view live off the one
  // Bateman solve. Each source shows its "what it teaches" blurb (the teaching hook).
  import { appState } from "./state.svelte";
  import { sourcesByCategory, type PrebuiltSource } from "./sources";

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

  let loadingId = $state<string | null>(null);
  let loadError = $state("");

  async function onLoad(s: PrebuiltSource) {
    loadError = "";
    loadingId = s.id;
    const err = await appState.loadSource(s);
    loadingId = null;
    if (err) loadError = `${s.label}: ${err}`;
  }
</script>

<section class="sources">
  <h2>Prebuilt sources</h2>
  <p class="muted intro">
    Load a curated source with one click — the inventory, source-age, and (for neutron
    sources) the tabulated neutron term populate, then every view evolves live.
    <strong>Educational/reference only</strong>, not for safety decisions (§11).
  </p>

  {#if !appState.ready}
    <p class="muted">Waiting for the engine to finish booting…</p>
  {/if}

  {#each groups as g (g.category)}
    <div class="group">
      <h3>{g.category}</h3>
      <div class="cards">
        {#each g.sources as s (s.id)}
          <button
            class="card"
            class:neutron={!!s.neutronSource}
            data-testid="source-{s.id}"
            onclick={() => onLoad(s)}
            disabled={!appState.ready || loadingId !== null}
            title="Load {s.label}"
          >
            <span class="label">
              {s.label}
              {#if s.neutronSource}<span class="badge">n</span>{/if}
              {#if loadingId === s.id}<span class="muted">— loading…</span>{/if}
            </span>
            <span class="blurb">{s.blurb}</span>
            {#if s.caveat}<span class="caveat">⚠ {s.caveat}</span>{/if}
          </button>
        {/each}
      </div>
    </div>
  {/each}

  {#if loadError}
    <p class="inline-error" role="alert">⚠ {loadError}</p>
  {/if}
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
    margin: 0.9rem 0 0.4rem;
    opacity: 0.85;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .intro {
    margin-top: 0.25rem;
  }
  .muted {
    opacity: 0.7;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: 0.5rem;
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    text-align: left;
    font: inherit;
    padding: 0.55rem 0.7rem;
    border: 1px solid #8886;
    border-radius: 0.45rem;
    background: #8881;
    cursor: pointer;
  }
  .card:hover:not(:disabled) {
    background: #4e79a722;
    border-color: #4e79a7;
  }
  .card:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .card.neutron:hover:not(:disabled) {
    background: #59a14f22;
    border-color: #59a14f;
  }
  .label {
    font-weight: 700;
  }
  .badge {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    color: #fff;
    background: #59a14f;
    border-radius: 0.25rem;
    padding: 0 0.3rem;
    margin-left: 0.25rem;
    vertical-align: middle;
  }
  .blurb {
    font-size: 0.85rem;
    opacity: 0.85;
  }
  .caveat {
    font-size: 0.8rem;
    color: #8a6d00;
  }
  .inline-error {
    color: #b3261e;
    margin: 0.6rem 0 0;
    font-size: 0.9rem;
  }
</style>
