# PANDA (alpha,n)-in-oxide neutron yields — provenance

`alpha_n_oxide.json` carries the thick-target **(α,n) neutron yields in oxide** used by the
spent-fuel **(α,n)-on-oxygen** neutron source (milestone **M12**), which closes the M9
"spontaneous-fission only → lower bound" gap. For clean oxide fuel, SF + (α,n)-on-O is
essentially the complete intrinsic neutron source (fission products are heavy; oxygen is the
only significant light-element (α,n) target in UO₂), so adding this term turns the spent-fuel
neutron dose from a **lower bound** into a **best estimate** (caveated, see below).

## Primary source

> D. Reilly, N. Ensslin, H. Smith Jr. (eds.), *Passive Nondestructive Assay of Nuclear
> Materials* (PANDA), **NUREG/CR-5550, LA-UR-90-732**, Los Alamos National Laboratory, 1991.
> Chapter 11, "The Origin of Neutron Radiation" (N. Ensslin).

The numerical tables used here are the "Useful Nuclear Data" tables as reproduced in the
**2007 PANDA Addendum** (T. Douglas Reilly), the publicly downloadable LANL reprint:

- **Table 13. "(α,n) Neutron Yields"** (addendum p. 11-16) — the **"(α,n) Yield in Oxide
  (n/s-g)"** column is transcribed into `oxide_an_yield[*].oxide_n_s_g`; the **"Yield (α/s-g)"**
  and **"Mean Energy (MeV)"** columns are kept for provenance / the basis check.
- **Table 14. "Thick-Target Yields from (α,n) Reactions"** (addendum p. 11-17) — the **oxygen**
  row (0.059 ± 0.002 n per 10⁶ α at 5.2 MeV; 0.040 ± 0.001 at 4.7 MeV) → `thick_target_O_yield`.

Source URL (2007 addendum, full 335-page reprint, T.D. Reilly): the LANL CDN
(`cdn.lanl.gov/files/panda-2007-addendum_00d29.pdf`) and the FAS mirror of the original Ch.11
(`sgp.fas.org/othergov/doe/lanl/lib-www/la-pubs/00326406.pdf`). PANDA is a U.S. government
report (NUREG/CR), not export-controlled, freely redistributable.

## How the numbers were read — and why it mattered

`pdftotext -layout` **scrambled the table's row/column alignment** (a known failure on
multi-column scientific PDFs): it mispaired e.g. Pu-238 oxide as `8.3e-5` and floated the real
oxide values (2.69e3, 3.76e6, 7.73e4 …) to the bottom of the block, detached from their
isotopes. Transcribing from that text would have been silently wrong. The values here were read
from the **rendered table image** instead, and every row was double-checked two ways:

1. **Row pairing** — each isotope's "Total Half-Life" was checked against the known half-life
   (Pu-238 87.74 y, Cm-244 18.1 y, Am-241 433.6 y, …). All match → the (isotope ↔ oxide-value)
   pairing in the image is correct.
2. **Per-gram basis (the §12 units trap)** — the "Yield (α/s-g)" column equals each isotope's
   **specific activity** (Pu-238 6.4e11 ≈ SA 6.34e11; Cm-244 3.0e12; Am-241 1.3e11), proving the
   oxide column is **per gram of the ISOTOPE**, not per gram of the oxide compound. So the
   per-decay conversion divides by the isotope specific activity λN_A/M (consistent), not by a
   per-oxide mass.

## Conversion (in `data/build/build_spent_fuel.py`)

    yield_an_per_decay[X] = oxide_n_s_g[X] / specific_activity_Bq_per_g(X)        (n / decay)
    S_an(t) = Σ_X yield_an_per_decay[X] · A_X(t)        (n/s, total decays/s from the Bateman solve)

`specific_activity_Bq_per_g` is **λ_total·N_A/M** (all decay modes) — consistent with `A_X(t)`
being total activity and with PANDA's oxide value already embedding the actual α branch (so an
emitter like Pu-241, mostly β, gets the right tiny (α,n) per decay automatically).

## What is — and isn't — validated

Be precise here (the M9 standard: state what a check proves, not what you wish it proved).

**Independently validated — the per-gram-of-isotope BASIS.** PANDA's "Yield (α/s·g)" column is
compared against the isotope α-emission rate computed from *independent* nuclear data — ICRP-107
α branch × rd specific activity (λ·N_A/M). Across the 18 isotopes these agree to **≤4.1 %** (PANDA
is 2 sig figs), proving the per-gram columns are per gram of **isotope**, so dividing the Oxide
column by λN_A/M is the right basis. A ÷ oxide-molar-mass slip (~270 vs ~238) is +13.4 % and would
fail this check (gated at 8 % in `build_alpha_n_block`). This is non-tautological: a
`yield = oxide/SA` → `yield·SA ≈ oxide` round-trip would only echo the build's own arithmetic.

**NOT independently validated — the (α,n) absolute MAGNITUDE.** It rests entirely on PANDA. The
Pu-238 oxide total (dataset-SF + PANDA-(α,n) = 2.6e3 + 1.34e4 ≈ **1.60e4 n/s·g**, the canonical
PuO₂ value) is only a **cross-pipeline sanity** gate: the canonical figure ≈ PANDA's *own* SF+(α,n)
column sum, and the (α,n) term echoes PANDA regardless of basis, so what it actually exercises is
the dataset-SF ↔ PANDA-SF agreement (Serpent2 ~2604 vs PANDA 2590 n/s·g — the already-M9-validated
SF pipeline). No second (α,n) source is fabricated; PANDA is the standard reference (exactly
parallel to M9's "neutron magnitude rests on the cited IAEA/Holden ν̄").

## Coverage & residual (honesty, surfaced never silent)

Table 13 covers the **dominant** spent-fuel (α,n) emitters: **Cm-242** (short cooling),
**Cm-244**, **Am-241** (grows in from Pu-241), **Pu-238/240**. Inventory α-emitters **absent**
from Table 13 (Am-243, Cm-243/245/246/247/248, …) are **not** in the modeled (α,n) dose; their
(α,n) is **bounded** with the Table-14 oxygen yield (`alpha_branch · 5.9e-8 n/α`) and surfaced as
the **dropped (α,n) fraction** at the evaluated cooling time — the same mechanism as the dropped
SF set. (Cm-246, which dominates SF at >1 kyr, has a negligible (α,n) ~6 n/s·g vs its ~10⁷ SF, so
the residual stays small across the cooling range.)

## Grade

Order-of-magnitude / factor-grade, like the rest of the neutron path. The thick-target (α,n)
yield itself carries ±factor uncertainty; the UO₂≈PuO₂ transfer is justified (≈11.8 % O by mass
in both, near-identical actinide α-stopping); the (α,n) spectrum (softer than SF, ~1–5 MeV) is
folded against the same representative Cf-252 SF spectrum — defensible because H*(10) is flat
over 0.5–6 MeV (the M5/M9 justification), but a real approximation, surfaced as such.
