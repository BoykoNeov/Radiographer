<script lang="ts">
  // Collapsible "Learn more" block (pedagogy layer, docs/plans/pedagogy-layer.md). A thin
  // wrapper over the native <details> element — the exact pattern Honesty.svelte and the
  // dose per-line table already use — so it inherits keyboard/AT behaviour and the browser
  // disclosure marker for free (no manual ▸: adding one would double the native triangle,
  // and the repo's existing <details> summaries rely on the native marker).
  //
  // Collapsed by default (novice content is optional depth, not in the reading path). The
  // body is `children`; an optional `advanced` snippet renders as a secondary, labelled
  // block for the deeper note (equations / standards refs), mirroring <Term>'s split.
  import type { Snippet } from "svelte";

  let {
    summary = "Learn more",
    children,
    advanced,
  }: { summary?: string; children: Snippet; advanced?: Snippet } = $props();
</script>

<details class="learn-more">
  <summary>{summary}</summary>
  <div class="lm-body">
    {@render children()}
    {#if advanced}
      <div class="lm-adv">
        <span class="lm-adv-label">Advanced</span>
        {@render advanced()}
      </div>
    {/if}
  </div>
</details>

<style>
  .learn-more {
    margin: 0.6rem 0 0;
    font-size: 0.85rem;
  }
  .learn-more summary {
    cursor: pointer;
    font-weight: 600;
  }
  .lm-body {
    margin-top: 0.4rem;
    opacity: 0.85;
    line-height: 1.5;
  }
  .lm-adv {
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid #8884;
  }
  .lm-adv-label {
    display: inline-block;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.7;
    margin-right: 0.35rem;
  }
</style>
