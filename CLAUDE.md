# Working in this repo

**Read `HANDOFF_PLAN.md` first — it is the design contract.** Decisions marked
**LOCKED** there are settled: build to them, don't relitigate. Items marked
**OPEN** still need a decision. This file is *how to work here*; the plan is
*what we're building*. The plan is authoritative on design — if a design fact
in this file ever drifts from the plan, the plan is right and this file should
be fixed to **point**, not restate.

## What this is

Radiation & Decay Simulator — a fully client-side (browser) decay-chain
visualizer + external-dose calculator. Python physics core via **Pyodide
(WASM)** + a **JavaScript** rendering layer (Plotly curves, Cytoscape DAG).
No server; all computation on-device.

## The two rules that override convenience (pointers, not restatements)

- **Solve once, evaluate many** — never re-run the Bateman solve on a slider
  tick. See `HANDOFF_PLAN.md` §3.
- **The datasets are the project** — most effort and nearly all silent-error
  risk live in the bundled physics data. Build the data layer and its
  validation *before* the UI. See §7, §10.

## How we work

- **Build order is M0 → M7** (§10). De-risk foundation and data before UI; M0
  is a Pyodide smoke test that's allowed to kill the project early.
- **Validation-first / TDD.** Write the check before (or alongside) the code,
  confirm it fails, then implement until it passes. Every physics dataset gets
  a regression test the moment it lands (§7, §10). Don't edit a test to make
  code pass.
- **No silent errors.** Never swallow an exception or quietly substitute a
  fallback in the physics path — surface dataset / interpolation / units
  failures loudly. This is the engineering side of the **honesty register**
  (§11): wrong-but-quiet is the worst outcome for a tool people may trust.
- **Be obsessive about units & quantities** (§12): Gy vs Sv vs effective Sv,
  Bq vs Ci, air kerma vs exposure. Store internally in SI.
- **Type safety.** Python: type hints on the engine/dose APIs that cross the
  Pyodide bridge. JS: prefer typed/branded IDs over bare strings.
- **Don't auto-format inside hooks** (token bloat). Run formatters manually
  between sessions — `ruff`/`black` for Python, `prettier` for JS.
- **Search with ripgrep / Glob / Grep**, not a RAG or index layer.
- **Keep one main thread.** Spawn a subagent only for a genuinely separable,
  well-scoped task, and merge its result yourself.

## Commits

- **`git add` / `git commit` / `git push` are pre-authorized** — no need to
  ask each time. Routine work commits directly to `main` and pushes to
  `origin`; branch first only for large or risky changes.
- **Conventional Commits** subject: `feat:`, `fix:`, `data:`, `test:`,
  `docs:`, `chore:`. Each commit should compile and pass its tests; tie commits
  to M-milestone checkpoints.
- Subject and body describe the change on its own terms — don't narrate the
  assistant. Authorship is recorded only via the trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## End of a work batch

Before wrapping up a batch of work, **always**: (1) update memory and the
relevant `docs/`, (2) commit with a Conventional Commits message, (3) push to
`origin`. This is the default close-out — no need to be asked.

## Context hygiene & task tracking

- Prefer `/clear` between unrelated tasks over letting context balloon into
  auto-compaction. For a multi-step milestone, capture decisions in a
  `docs/plans/` dev-doc so a fresh session can resume — see `docs/README.md`.
- **Two systems, kept distinct:** durable milestone design notes live in
  `docs/plans/`; ephemeral in-session checklists use the harness Task tools.
  If it matters next session, it's a dev-doc; if it's just today's list, it's a
  Task.
