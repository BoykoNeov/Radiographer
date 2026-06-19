# M9 — Spent-fuel spontaneous-fission neutron output

**Status:** done ✅ (gate green dev + built)
**Milestone (HANDOFF_PLAN.md §8, §6.3):** post-v1 extension — wire the spent-fuel neutron
output the M7c notes deferred. Closes the M7c "future hook".

## Goal

A loaded spent-fuel vector lights the neutron view (it was grayed in M7c). "Done" = the
neutron card shows a live, validated spontaneous-fission dose that cools with the inventory,
honestly flagged as a lower bound, end-to-end through the rendered path (dev + built gates).

## The decisive data finding

The SCK-CEN CSV carries **150 nuclides × 7 columns**: bare (mass density), `_A`, `_H`, `_SF`,
`_GSRC`, `_ING_TOX`, `_INH_TOX`. There is **no `_AN`** — the M7c notes ("dataset carries
`_SF`/`_AN`") were wrong (doc bug fixed in §11). So:

- **`_SF` is the spontaneous-fission RATE (fissions/s)**, not neutrons/s — proven because
  `_SF/_A` reproduces textbook SF branching ratios (Cm-244 1.38e-6, Cm-242 6.1e-8, Pu-240
  5.7e-8, U-238 5.46e-7). The ratio is basis-independent (the ≈0.535 `_A` geometry factor
  cancels, like `_H/_A`).
- Neutron emission needs the prompt multiplicity ν̄: **`yield_n = (_SF/_A)·ν̄`**, and the source
  is the **multi-parent** `S(t)=Σ yield_n·A_n(t)` off the one Bateman solve (§3). Cm-242 (163 d)
  carries ~35 % at discharge but is gone by 10 yr → Cm-244 (18 yr) dominates → genuinely needs
  per-nuclide time evolution, not a single parent.
- **(α,n) is absent** from the dataset → unmodeled → the result is a **lower bound** (the
  dangerous under-count). Loud caveat, not silent.

## ν̄ sourcing (the one sourcing-gated piece)

Vendored `data/vendor/iaea_sf_nu/` — **IAEA NDS** Simakov/Verpelli/Otsuka, *"Update of the
nuclear data for the neutron emissions for actinides of interest in safeguards"*, Table 1 (SF
prompt ν_p + calculated n-yields; JEFF-3.1 / Holden 1985). PDF + SHA + a verbatim
`sf_nubar.json` transcription (18 trans-actinides). Per the §11 no-fabrication discipline,
**Cm-246/248 ν̄ were NOT typed from memory.**

**Post-M9 extension (DONE): Cm-246/248 ν̄ vendored to extend the valid cooling regime.** The IAEA
table covers only the 18 safeguards isotopes, so Cm-246 (t½ 4760 yr) — which dominates the SF
source once Cm-244 (18 yr) decays at multi-century cooling — was originally a surfaced, bounded
drop. Now sourced (no fabrication): the **Holden & Zucker BNL-36467 (1985)** SF prompt-neutron
*multiplicity distributions* P(ν) are vendored in `data/vendor/llnl_sf_multiplicity/` (transcribed
from LLNL **UCRL-AR-228518-REV-1** Table 4, BSD-licensed), and ν̄ = Σₖ k·P(k) is **derived**:
Cm-246 = 2.930, Cm-248 = 3.130 (Cm-248 double-confirmed by Vorobyev 2005; Cm-246 single
authoritative source). BNL-36467 is the same Holden & Zucker evaluation the IAEA report itself
cites for the curium nu-bars. The derivation is **validated by reproducing the IAEA Cm-242/Cm-244
ν̄ (2.540/2.720) exactly** from the same source's distributions (regression test
`test_cm246_nubar_derived_from_vendored_distribution`). With these modeled, the unmodeled-ν̄
dropped SF-rate fraction stays **< 0.1 % out to 1 Myr** (was capped at ~1 century), and Cm-246 is
the dominant SF emitter at 1 kyr for the 45 GWd vector (51 %; at low burnup Pu-240 leads — Cm-246
is a high-order capture product). The remaining drop (chiefly Cm-250/Pu-244) is negligible and
still surfaced. The orthogonal **(α,n) lower-bound caveat is unchanged.**

## Validation — what the cross-check actually proves (and what it doesn't)

The Cm-244 cross-check compares `(_SF/_A)·ν̄ = 1.38e-6·2.72 = 3.75e-6 n/decay` vs the IAEA's
`n-yield/SA = 1.100e7 / 2.99e12 = 3.68e-6`. **ν̄ is common to both and cancels**
(`n_yield/SA = ν̄·T_tot/T_SF`), so the ~2% agreement validates the **SF branching ratio**
(Serpent2 1.38e-6 vs IAEA 1.351e-6 vs textbook 1.37e-6) — it catches a `_SF` units/mapping slip
but does NOT independently validate ν̄ or the absolute yield (those rest on the cited IAEA/Holden
ν̄, a properly evaluated quantity). Magnitude sense (rebuilt `selfcheck`, with Cm-246/248 now
modeled): SF-only source 45 GWd/tHM = 1.36e9 (t0) → 6.12e8 (10 yr) → 2.87e7 (100 yr) n/s/tHM; the
10 yr figure is ~Cm-244 alone (78.6 g/tHM × 1.1e7 n/s/g × 0.68 decay), confirming the
Cm-242→Cm-244 transition, and the 100 yr figure now includes the in-grown Cm-246 (the ~20% rise
over the pre-extension 2.39e7 is exactly Cm-246 starting to carry the source). (An independent
ν̄-inclusive magnitude anchor would need a specific-yield value from a lineage other than the
IAEA/Holden ν̄, cleanly cited — a future add, not fabricated from memory.)

## Key files & decisions

- **Data** — `data/build/build_spent_fuel.py` (`build_neutron_block`): per-nuclide yields,
  `dropped_sf_branch` (emitters w/o ν̄, for the warning only), Cm-244 cross-check; schema → **v2**.
  `data/vendor/iaea_sf_nu/{SF_n-Yield_20150313.pdf, sf_nubar.json, PROVENANCE.md}`.
- **Engine** — `engine/spent_fuel_neutron.py` (`SpentFuelNeutronModel`): folds h̄ via the shared
  `engine.neutron_dose.fold_spectrum` (refactored out), `S(t)=Σ yield·A` solve-once, returns the
  same `DoseOk` shape + a per-time `dropped_sf_frac` and a lower-bound warning past 5 %.
  `engine/spent_fuel.py` schema → **v2**, catalog gains `hasNeutron`.
- **Bridge** — `engine/bridge.py:spent_fuel_neutron_dose(handle, req)` looks up the loaded
  vector's `neutron` block by `source_id`.
- **State/UI** — `state.svelte.ts` `spentFuelNeutronId` (load sets, hand-edit drops, mutually
  exclusive with `neutronSource`); `recomputeDose` branch writes the SAME `neutronDoseSeries`
  (all cursor/stacked-bar consumers reused). `Dose.svelte` un-grays + SF-only lower-bound
  caveat + dropped-fraction readout. `persist.ts` **serializer v5** (`spent_fuel_neutron_id`,
  rejects co-set with `neutron_source`). Honesty.svelte register item rewritten.
- **Tests** — `tests/test_spent_fuel_data.py` (+5 neutron-block tests), new
  `tests/test_dose_spent_fuel_neutron.py` (7 engine tests), `drive_browser.mjs` (M9 lit-path +
  v5 round-trip + orphan-guard, dev + built).

## Open / future
- ~~Vendor Cm-246/248 SF ν̄ to extend the valid cooling regime past ~1 century.~~ **DONE** — see
  the ν̄-sourcing section above (Holden & Zucker BNL-36467 via LLNL UCRL-AR-228518 Table 4;
  ν̄=Σₖ k·P(k); dropped fraction now < 0.1 % out to 1 Myr).
- Cf-250 SF ν̄ stays dropped (tracked for the warning, not in the dose): t½ 13 yr, so it decays
  away fast and is negligible at the long cooling where its high SF branch would matter — not
  worth sourcing.
- (α,n) source term (would need ORIGEN/SOURCES-grade matrix data) to make it a total, not a
  lower bound. With the SF-ν̄ residual now < 0.1 %, (α,n) is the dominant remaining reason the
  neutron dose is a lower bound.
