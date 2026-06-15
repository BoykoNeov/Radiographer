# docs/

Durable design notes that outlive a single session. The design **contract** is
`../HANDOFF_PLAN.md`; this folder holds the **working notes** that accumulate as
each milestone is built.

## What goes where

- **`../HANDOFF_PLAN.md` (repo root)** — the contract: what we're building, all
  LOCKED / OPEN decisions. Authoritative for design.
- **`docs/plans/`** — one dev-doc per milestone (M0–M7), created *when that
  milestone starts*. Captures the accepted approach, key files/decisions, and
  whatever a fresh session needs to resume. This is the durable record.
- **Harness Task tools** (`TaskCreate` / `TaskUpdate`) — the *in-session*
  checklist for the milestone you're actively working. Ephemeral; not a
  substitute for a dev-doc.

Rule of thumb: **if it matters next session, it goes in a dev-doc; if it's just
today's checklist, it's a Task.** Don't run two durable task systems.

## Convention

- Name dev-docs `docs/plans/M<n>-<slug>.md` (e.g. `M0-smoke-test.md`).
- Start from the template below. A single file is usually enough; only split a
  separate context/tasks file out if the milestone genuinely outgrows one doc.
- **Don't pre-create docs for milestones that haven't started** — empty
  scaffolds rot. Create `M0-…` when M0 begins.
- When a milestone resolves a `HANDOFF_PLAN.md` §13 OPEN item, record it in the
  dev-doc **and** update §13 in the plan.

## Template

```markdown
# M<n> — <title>

**Status:** planning | in progress | done
**Milestone (HANDOFF_PLAN.md §10):** <one line>

## Goal
What "done" means here, and the validation that proves it.

## Plan
The accepted approach. Keep this a living document during implementation.

## Key files & decisions
Paths touched, datasets assembled, decisions made (flag any §13 OPEN item this
resolves).

## Open questions / risks
```
