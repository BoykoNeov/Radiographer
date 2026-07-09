<script module lang="ts">
  // Instance-unique id source (see popId below). Module scope so it persists across all
  // <Term> instances on the page.
  let _termSeq = 0;
  function nextTermId(): number {
    return _termSeq++;
  }
</script>

<script lang="ts">
  // Inline glossary term (pedagogy layer, docs/plans/pedagogy-layer.md). Renders the
  // term text with a dotted underline + ⓘ affordance; the definition popover is revealed
  // PURELY BY CSS (:hover / :focus-within) — no reactive state, no effect. That matters
  // for two reasons the plan calls out (advisor risk #2, the cf9c819 DOM-risk class):
  //   1. When closed the popover is `display:none` — it has NO box, so it can never
  //      overlay or intercept a click on the Plotly canvas, a legend entry, or a control
  //      beneath it. It only exists while the term itself is hovered/focused (in prose,
  //      away from those click paths).
  //   2. :focus-within means Tab-focusing the trigger reveals it too — keyboard + tap
  //      (tap = focus) work for free, with no JS state to desync.
  //
  // The trigger is a real <button> with a DESCRIPTIVE aria-label ("Define …"), never the
  // bare quantity word, so the gate's role+name control queries (getByRole("button",
  // { name: "Atoms" }) etc.) can never collide with it (advisor). Snippet children let a
  // call site override the visible text while keeping the same glossary entry.
  import type { Snippet } from "svelte";
  import { GLOSSARY, type GlossaryKey } from "./glossary";

  let { term, children }: { term: GlossaryKey; children?: Snippet } = $props();

  // $derived so svelte-check is satisfied that a (hypothetical) `term` change would flow
  // through — in practice every call site passes a static literal, so it is constant.
  const entry = $derived(GLOSSARY[term]);

  // A unique id per instance so aria-describedby links this trigger to ITS popover — the
  // same term can appear in more than one panel (activity in Curves and Chain), so the id
  // must be instance-unique, not term-unique. The <script> runs once per instance, so a
  // module counter increment gives a stable unique value (no SSR here to desync).
  const popId = `term-pop-${nextTermId()}`;
</script>

<span class="term-wrap">
  <button type="button" class="term" aria-label={`Define ${entry.term}`} aria-describedby={popId}>
    {#if children}{@render children()}{:else}{entry.term}{/if}<span class="info" aria-hidden="true"
      >ⓘ</span
    >
  </button>
  <span class="popover" id={popId} role="tooltip">
    <span class="pop-term">{entry.term}</span>
    <span class="pop-novice">{entry.novice}</span>
    {#if entry.advanced}
      <span class="pop-adv">
        <span class="pop-adv-label">Advanced</span>
        {entry.advanced}
      </span>
    {/if}
  </span>
</span>

<style>
  /* Inline anchor for the absolutely-positioned popover. `inline` (not inline-block) so a
     term still wraps naturally inside a sentence. */
  .term-wrap {
    position: relative;
  }
  /* The trigger: reads as emphasised prose (dotted underline + ⓘ), not a chrome button. */
  .term {
    font: inherit;
    color: inherit;
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    cursor: help;
    border-bottom: 1px dotted currentColor;
    white-space: nowrap;
  }
  .info {
    font-size: 0.82em;
    opacity: 0.6;
    margin-left: 0.1em;
    vertical-align: baseline;
  }
  /* Closed = no box at all → cannot intercept clicks on the plot/legend/canvas below it
     (advisor risk #2). Revealed only while the term is hovered or focus is inside it. */
  .popover {
    display: none;
    position: absolute;
    left: 0;
    top: calc(100% + 0.3rem);
    z-index: 50;
    width: max-content;
    max-width: min(28rem, 92vw);
    /* System colors → theme-aware (respects the app's `color-scheme: light dark`) with no
       hard-coded light/dark palette to get wrong. */
    background: Canvas;
    color: CanvasText;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    box-shadow: 0 4px 16px #0004;
    padding: 0.6rem 0.75rem;
    font-size: 0.85rem;
    font-weight: 400;
    line-height: 1.45;
    text-align: left;
    white-space: normal;
    cursor: auto;
  }
  .term-wrap:hover .popover,
  .term-wrap:focus-within .popover {
    display: block;
  }
  .pop-term {
    display: block;
    font-weight: 600;
    margin-bottom: 0.25rem;
  }
  .pop-novice {
    display: block;
  }
  .pop-adv {
    display: block;
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid #8884;
    opacity: 0.85;
  }
  .pop-adv-label {
    display: inline-block;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.7;
    margin-right: 0.35rem;
  }
</style>
