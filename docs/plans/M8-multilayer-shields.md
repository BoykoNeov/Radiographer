# M8 — Multi-layer shields (§13 #2 / §6.4 OPEN → resolved)

**Status:** DONE ✅ — gate green dev + built (M6g checks + new M8 multi-layer order check;
pytest green incl. order-locking + artifact tests). Closes §13 #2 and the §6.4
layered-buildup decision — **the last OPEN design item in the plan**. Post-v1 in build
order (M0–M7 are v1); extends the proven single-layer shield (M6g), no new dataset.

**Parent:** `docs/plans/M6g-shield.md` (single-layer shield this generalizes).
**Milestone (HANDOFF_PLAN.md §6.5, §13 #2):** "Layered-shield buildup has no clean
theory — pick a documented approximation (last-layer, or Harima–Kitazume) and state which."

## The decision (§6.4 / §13 #2) — LOCKED: last-layer / total-mfp

A stack of `n` layers, ordered **source-side → detector-side** (last element adjacent to
the detector). For a photon of energy E passing through layers `i=1..n` with linear
attenuation `μᵢ` and thickness `xᵢ`:

    transmission(E) = B_L(E, Σᵢ μᵢxᵢ) · exp(−Σᵢ μᵢxᵢ)

where **L = the last (detector-side) layer**. Two parts, two honesty grades:

- **Attenuation `exp(−Σ μᵢxᵢ)` is EXACT** — narrow-beam attenuation is multiplicative
  and order-invariant; the stack just sums mean-free-paths. No approximation.
- **Buildup `B_L(E, Σ mfp)` is the approximation** — the only ambiguous part. We take the
  whole penetration depth's buildup as if it were the detector-side material. Documented,
  plan-named, reduces **exactly** to single-layer for n=1 (then L is the only layer).

**Why last-layer, not Broder / Harima–Kitazume (no fabrication, §11):**
- **Harima–Kitazume** needs a *new* sourcing-gated two-layer correction coefficient set —
  a new dataset to source + validate, same discipline as M7's AmBe/spent-fuel.
- **Broder's method** needs only the single-material B(mfp) data we already have, BUT its
  multi-layer summation formula must be transcribed *exactly* from a citable source;
  reconstructing it from memory is the fabrication trap (cf. the M4 Cross-Berger kernel).
  Not sourced this batch → not shipped.
- **Last-layer** is unambiguous, named in §6.5, needs zero new data, and is conservative
  in the teaching case that matters (the "more lead can increase dose" / order-matters
  lesson is carried by the **attenuation × material order**, which is exact).

A future upgrade to Broder/H-K is a drop-in `_stack_buildup` strategy swap — recorded
here, not a silent omission.

### The last-layer artifact — a FIRST-CLASS honesty item, not a footnote (advisor)

Empirically (the TDD red→green surfaced it): last-layer buildup is **not monotonic** across
a material/order change, and — sharper — it is **order-dependent and errs in BOTH
directions**:
- **lead → water** (high-buildup low-Z layer on the *detector* side): water's large B is
  applied over the whole depth, including the lead portion that never scattered water-like →
  the computed transmission is *higher* than lead alone (a non-physical "add water → more
  dose" increase). **Over-estimates.**
- **water → lead** (high-Z on the *detector* side): lead's low B is applied over the water
  portion too → **under-estimates**, the dangerous direction the honesty register cares about.

So layered buildup is now the **least-reliable element of the γ dose calc**. It must be
documented loudly in §11 (order-dependent, errs both ways, can silently under-count) — and
two tests pin it: the *true* monotonicity invariant (thicken a layer in a fixed stack → T
falls) and an explicit **artifact test** (lead→water > lead-alone) so no future reader
"fixes" the artifact into a fabrication.

**Optional honest turn (UI step):** the spread between the two layer orderings — same
`exp(−Σμx)`, different B — *is* a built-in uncertainty estimate for the layered-buildup
approximation. Surfacing "order sensitivity ≈ X%" through the existing per-modality
uncertainty viz converts the artifact into an honest band rather than a hidden wart.

## The silent-error vector: LAYER ORDER (advisor)

`exp(−Σμx)` is order-invariant and same-material B is order-invariant — so a
reversed-layer-list bug passes the same-material test, the n=1 test, AND monotonicity,
while silently picking the wrong detector-side material for buildup. **Order is THE bug
surface.** The locking test (TDD-first, written before the impl):

- A dissimilar stack (lead + water) in **both orders** must
  (a) give **identical** `exp(−Σμx)` (attenuation order-invariant),
  (b) give **different** total transmission (buildup picks the detector-side material), and
  (c) the order whose detector-side layer is X equals `B_X(Σ mfp)·exp(−Σμx)` **exactly**.

That test pins "last = detector-side" into the engine; the bridge JSON order, the UI
layer order, and the serializer must all match it. The UI must **show** which end faces
the detector — order changes the answer, so it can never be implicit.

## `dose_thickness` under layering (advisor)

Single-layer `dose_thickness` evaluates `x=0` with `shield=None` as "the exact unshielded
baseline." Under a stack that's wrong: sweeping one layer with the others fixed, `x=0` for
that layer is **rest-of-stack**, not unshielded. Resolution: sweep the selected layer with
the others held; the swept curve's zero point is the rest-of-stack transmission (evaluated
with the remaining layers, not `shield=None`); the reconciliation invariant folds the
**full** stack at the selected thickness and still matches the breakdown bar exactly.

## Scope / touch points

1. **`engine/dose.py`** — `_normalize_shield` → ordered layer list (one normalize path;
   bare 2-tuple stays a Python convenience, internally promoted to `[tuple]`).
   `stack_transmission(layers, E)` = `B_last(E, Σ mfp)·exp(−Σ mfp)`; `_shield_factor`
   calls it. Per-layer `has_buildup` + on-grid μ gate (a non-buildup layer **anywhere**
   raises, same as single-layer today).
2. **`engine/bridge.py`** — `dose`, `dose_lines`, `dose_thickness` accept the list form
   (`shield: [[material, cm], …] | null`). `dose_thickness` gains a swept-layer index +
   held layers.
3. **`web/src/lib`** — `bridge.ts` shield type → layer list; `state.svelte.ts` shield state
   → array + add/remove/reorder; `Shield.svelte` stack editor (every slot = the 8 buildup
   materials; detector-side end labelled); serializer version bump (round-trip asserts
   identical *views*, the M6h pattern); honesty register names the last-layer approximation.
4. **`web/drive_browser.mjs`** — a multi-layer gate check (order matters: lead-then-water
   ≠ water-then-lead through the rendered path).

## Tests (TDD-first, red → green)

- **Order-locking** (the one above) — the asymmetric lead+water test. THE anti-bug test.
- 2×same-material (x₁ then x₂) == 1×(x₁+x₂) **exactly** (same B at same total mfp).
- n=1 layer list reduces bit-for-bit to the existing single-tuple path.
- Monotonic: adding a layer / thickening any layer never increases transmission.
- Per-layer non-buildup material (pmma anywhere in the stack) raises loudly.
- Bridge reconciliation: `dose_thickness` swept value at the selected thickness == the
  `dose_lines` γ rate for the full stack (the Σ==card anti-drift analog, M6g #4).
