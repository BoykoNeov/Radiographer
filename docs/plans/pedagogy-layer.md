# Pedagogy / explanations layer (dev-doc)

Status: **PLANNED — not started.** Scope agreed with the user; a session pause
was called right after the advisor review, before any code. This doc is the
resume contract for a fresh session.

## Goal (user request)

> "I want richer pedagogy and explanations throughout the software — including
> if not to layman level, but at least to a novice one. More explanations for
> advanced users are also welcomed if relevant."

## Decisions (locked with the user via AskUserQuestion)

- **Delivery mechanisms — all three (NOT a dedicated onboarding/concepts page):**
  1. Term tooltips + a shared glossary
  2. Collapsible "Learn more" blocks
  3. Inline prose hints
- **Depth: novice baseline + advanced asides.** Plain-language everyone can
  follow, with an optional deeper note (equations / standards refs) marked as
  advanced. Novice sentence first; advanced aside is optional and secondary.
- **Surface order: core physics panels first**, review after each pass:
  - **Pass 1 — Curves, Chain/DAG, Dose** (also builds + proves the shared components)
  - **Pass 2 — Shield, Sources**
  - **Pass 3 — Internal dose, Honesty**
- **Two new components approved** by the user (`Term.svelte`, `LearnMore.svelte`)
  plus a `glossary.ts` data module.

## Architecture

- **`web/src/lib/glossary.ts`** — single source of truth. Keyed table
  `term → { term, novice: string, advanced?: string }`. Every unit/quantity
  definition lives here once (half-life, activity/Bq/Ci, Gy vs Sv vs effective
  Sv, air kerma vs exposure, H*(10) vs effective, secular equilibrium, buildup
  factor, removal cross-section Σ_R, committed dose E(50), etc.).
- **`web/src/lib/Term.svelte`** — inline term with a dotted underline + ⓘ
  affordance; hover/focus/tap reveals the glossary entry (novice always shown;
  `advanced` note as a secondary "Advanced" block). Keyboard-accessible.
- **`web/src/lib/LearnMore.svelte`** — thin wrapper over `<details>` (the
  pattern `Honesty.svelte` already uses), collapsed by default, consistent
  "▸ Learn more" summary; body is novice prose, optional nested advanced block.
- Inline hints: extend the existing `.hint muted` lines (Curves/Dose already
  have them) with one or two plain-language "what am I looking at" sentences.

### Implementation notes discovered this session

- **Svelte 5** (`^5.0.0`), Vite 6, **no SvelteKit**. The codebase currently
  uses **no snippets and no `<slot>`** (grep found zero). The two components
  will be the first to take children — use Svelte 5 runes + snippets:
  `let { children } = $props()` and `{@render children()}`.
- **Style conventions to match** (from Curves/Dose/Honesty):
  - panel card: `border: 1px solid #8884; border-radius: 0.5rem; padding: 1rem`
  - `.muted { opacity: 0.7 }`; `.hint { font-size: 0.85rem; margin: ~0.6rem 0 0 }`
  - `<details>` summary: `cursor: pointer; font-weight: 600`
  - dividers/subtle borders use `#8883`/`#8886`; accent blue `#4e79a7`
  - `[title]` attributes are already used for short hover help (Dose geometry,
    graph-unit selectors) — reuse where a rich popover isn't warranted.

## Advisor guidance (2026-07-08) — where the risk actually is

The plumbing is easy and will work first try. Spend the care on these:

1. **Content correctness IS physics correctness — this blocks.** Every glossary
   entry and advanced aside is a physics claim; this repo's cardinal rule is
   "no wrong-but-quiet" (§11). A flattened simplification is exactly that
   failure — worse in a tool people may trust. Forbidden flattenings:
   "half-life = when it's gone"; conflating absorbed dose (Gy) with dose
   equivalent (Sv); implying H*(10) and effective dose are interchangeable;
   blurring air kerma vs exposure; summing external and internal dose. These
   distinctions the app is obsessive about (§12) must SURVIVE simplification.
   **Check every entry against the language already in `Honesty.svelte` and
   HANDOFF_PLAN §11/§12 before writing it.**
2. **Gate/DOM risk — same class as the cf9c819 modebar-over-legend bug.** ⓘ
   triggers/popovers can (a) overlay and intercept clicks on existing
   interactive elements and (b) collide with the Plotly canvas via
   z-index/overflow. Keep affordances **additive** and out of the click paths
   the gate drives (legend entries, axis toggles, sliders, DAG canvas). **Do
   not wrap or reposition any element carrying a `data-testid`.** A `<Term>`
   popover near a plot must not eat plot clicks (hidden state = `display:none`,
   no box). **Verify gate green dev AND built before committing Pass 1.**
3. **Advanced asides: cite, don't reconstruct** (§11 no-fabrication, the rule
   that kept Broder/Harima out). If an aside states a standard, equation, or
   number, it must be verifiable — omit it rather than reconstruct a citation
   from memory. An unsourced "advanced" number is worse than no aside.
4. **Don't let glossary.ts and Honesty.svelte drift.** Honesty already carries
   much of this content. Do NOT refactor Honesty to consume the glossary now
   (out of scope) — just ensure they don't contradict where a term appears in
   both. Future work: make Honesty consume the glossary.
5. **Scope Pass 1 tightly:** build the two components + seed the glossary with
   ONLY the terms Curves/Chain/Dose actually use + wire those three, then
   gate-green, commit, hand back before Pass 2. Do NOT pre-populate the whole
   glossary. Reserve the `<Term>` popover for terms where the novice+advanced
   split earns its keep; lean on `<LearnMore>`/plain prose (and native
   `[title]`) elsewhere — don't put a popover on every noun.

## Pass 1 checklist (next session)

- [ ] `Term.svelte` (Svelte 5 snippet children; keyboard-accessible; hidden =
      `display:none`; never over a `data-testid` click path)
- [ ] `LearnMore.svelte` (`<details>` wrapper, consistent summary, optional
      advanced block)
- [ ] `glossary.ts` seeded with ONLY the Curves/Chain/Dose terms, each checked
      against `Honesty.svelte` + §11/§12
- [ ] Wire into `Curves.svelte`, `Chain.svelte`, `Dose.svelte`
- [ ] `npm run check` clean; gate green **dev + built**
- [ ] Commit (Conventional Commits), push; update memory + this doc
- [ ] Review with user before Pass 2 (Shield, Sources)

## Related

- Honesty register content: `web/src/lib/Honesty.svelte`, HANDOFF_PLAN §11/§12
- Units discipline: HANDOFF_PLAN §12
