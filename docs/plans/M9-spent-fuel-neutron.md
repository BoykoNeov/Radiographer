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
**Cm-246/248/Cf-250 ν̄ are NOT typed from memory** — they are absent from this evaluation, so
those minor SF emitters are a surfaced, bounded drop (Cm-246 matters only at multi-century
cooling, where the engine warns). Cloudflare blocked the PANDA Table 11-1 mirror; a future
upgrade is to vendor Cm-246/248 ν̄ from there / ENDF.

## Validation (apples-to-apples, SF only)

Published spent-fuel neutron source usually INCLUDES (α,n), so the anchor is the **Cm-244
specific SF yield**: `(_SF/_A)·ν̄ = 1.38e-6·2.72 = 3.75e-6 n/decay` vs the IAEA's own
`n-yield/specific-activity = 1.100e7 / 2.99e12 = 3.68e-6` — two independent routes agree to
~2 % (build cross-check + a `tests/test_spent_fuel_data.py` regression). SF-only source:
45 GWd/tHM = 1.36e9 (t0) → 6.07e8 (10 yr) → 2.39e7 (100 yr) n/s/tHM; the 10 yr figure equals
Cm-244 alone (78.6 g/tHM × 1.1e7 × 0.68 decay), confirming the Cm-242→Cm-244 transition.

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
- Vendor Cm-246/248/Cf-250 SF ν̄ (PANDA Table 11-1 / ENDF) to extend the valid cooling regime
  past ~1 century.
- (α,n) source term (would need ORIGEN/SOURCES-grade matrix data) to make it a total, not a
  lower bound.
