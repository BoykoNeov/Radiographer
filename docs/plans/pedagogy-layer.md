# Pedagogy / explanations layer (dev-doc)

Status: **Pass 1 + Pass 2 SHIPPED (2026-07-09).** Components + glossary built
and wired into Curves/Chain/Dose (Pass 1) and Shield/Sources (Pass 2);
svelte-check clean, gate green dev + built after each pass. **Pass 3 (Internal
dose, Honesty) is NOT started** — review with the user before starting it. The
original scope/resume contract is preserved below; see the Pass-2 checklist
near the end.

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

## Pass 1 checklist — DONE (2026-07-09)

- [x] `Term.svelte` — Svelte 5 snippet children; **CSS-only** reveal
      (`:hover, :focus-within`), no JS state; hidden = `display:none` (no box to
      eat clicks); trigger is a `<button>` with a **descriptive** `aria-label`
      (`Define …`) + `aria-describedby` → popover; instance-unique id via a
      module counter (activity appears in two panels); theme-aware via
      `Canvas`/`CanvasText` system colors.
- [x] `LearnMore.svelte` — `<details>` wrapper (native marker, no manual ▸, to
      match Honesty/Dose); `children` body + optional `advanced` snippet block.
- [x] `glossary.ts` — 11 entries, ONLY Curves/Chain/Dose terms, each paraphrased
      from `Honesty.svelte` with **no new number/citation** (advisor risk #1/#3).
      `GLOSSARY` is `as const satisfies Record<string, GlossaryEntry>`;
      `GlossaryKey = keyof typeof GLOSSARY` so `<Term term="…">` is type-checked.
      Terms: activity, half-life, secular-equilibrium, branching-ratio,
      decay-mode, absorbed-dose, dose-equivalent (H*(10)), effective-dose,
      hp007, buildup, inverse-square.
- [x] Wired into `Curves` (activity, half-life), `Chain` (activity,
      secular-equilibrium, decay-mode, branching-ratio, + (N,Z) `LearnMore`),
      `Dose` (H*(10), effective, Hp(0.07), absorbed-dose, inverse-square,
      buildup) — all additive, in hint prose only; no `data-testid` element or
      gate-matched control (Atoms/Activity/Mass/H*(10)/Effective) rewrapped.
- [x] `npm run check` clean (0/0); gate green **dev + built**; focused pedagogy
      behaviour check passed (labels, display:none-when-idle, focus reveal,
      Gy≠Sv content, LearnMore toggle).
- [ ] **Review with the user before Pass 2 (Shield, Sources).** ← next

## Pass 2 checklist — DONE (2026-07-09)

- [x] 7 new glossary terms, paraphrased from `Honesty.svelte`, no new
      number/citation: **Shield** — `attenuation`, `half-value-layer` (HVL,
      `HVL = ln2/μ` is a definitional identity, not a fabricated number),
      `bremsstrahlung`, `removal-cross-section` (Σ_R); **Sources** —
      `spontaneous-fission`, `alpha-n`, `source-age` (the one deliberate
      UI-mechanics Term).
- [x] **Advisor-caught correctness fix (blocks, advisor #1/#4):** the
      `spontaneous-fission` novice line must NOT cite the Pu-240 in a Pu pit as
      an SF example — the tool models the pit α/γ-only (Honesty: "~1000 n/s/g
      Pu-240 SF neutrons … v1 does NOT model"). A novice would load the pit and
      see no neutrons = wrong-but-quiet. Fixed to name only tool-modelled SF
      sources: **Cf-252** and **the curium in cooled spent fuel**. The gate
      confirms the consistency (Pu pit → "neutron GRAYED"; Cf-252 → "live card +
      n bar trace"; spent fuel → "MULTI-parent neutron path").
- [x] Wired **additively**, no `data-testid` element rewrapped: Shield — Terms
      in the inactive note + the (existence-only-checked) high-Z warning + a
      novice `<LearnMore>` "How a shield reduces the dose" (uses the `advanced`
      snippet for the first time). Sources — `source-age` Term in the intro + a
      novice `<LearnMore>` "What makes a source emit neutrons? (the 'n' badge)"
      placed ABOVE `.layout`, clear of the gate's `.row`/entries-table text
      assertions.
- [x] `npm run check` clean (0/0); gate green **dev + built**.
- [ ] **Review with the user before Pass 3 (Internal dose, Honesty).** ← next

### Pass-3 notes for the resuming session

- Add Pass-3 terms (committed dose E(50), absorption type / f1, and any
  Honesty-register vocabulary) when wiring `InternalDose.svelte`, same
  discipline (paraphrase Honesty, no new numbers).
- Do NOT refactor `Honesty.svelte` to consume the glossary yet (out of scope,
  advisor #4) — just keep them non-contradictory. Pass 3 is where the
  "make Honesty consume the glossary" future-work could finally land if wanted.
- Reuse the two components as-is; the `advanced` snippet on `LearnMore` now has
  a first real use (Shield/Sources) to copy.

## Related

- Honesty register content: `web/src/lib/Honesty.svelte`, HANDOFF_PLAN §11/§12
- Units discipline: HANDOFF_PLAN §12
