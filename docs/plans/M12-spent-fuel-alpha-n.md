# M12 — Spent-fuel (α,n)-on-oxygen neutron source

**Status:** done ✅ (gate green dev + built)
**Milestone:** post-v1 extension — close the M9 "spontaneous-fission only → LOWER BOUND" gap
(HANDOFF_PLAN §6.3, §11 spent-fuel neutron note). User-chosen next batch after M11.

## Goal

Add the **(α,n)-on-oxygen** neutron term to the spent-fuel source so the neutron dose is a
**best estimate**, not a lower bound. For clean oxide fuel, SF + (α,n)-on-O is essentially the
complete intrinsic neutron source (fission products are heavy; oxygen is the only significant
light-element (α,n) target in UO₂). "Done" = the neutron card's dose includes (α,n), the
SF-vs-(α,n) split is visible, the honesty note is reframed from "lower bound" to "best estimate
+ residual caveats", and it's validated end-to-end (dev + built gates).

## The data (the sourcing-gated piece) — DONE

Vendored `data/vendor/panda_alpha_n/` — **PANDA / NUREG-CR-5550** (Reilly/Ensslin/Smith, LANL
1991) Ch.11 "The Origin of Neutron Radiation", Tables 13 & 14 (via the 2007 Addendum reprint).

- **Table 13 "(α,n) Neutron Yields"** → `oxide_an_yield[*].oxide_n_s_g` (the **Oxide (n/s-g)**
  column) for 18 actinides (covers the dominant spent-fuel (α,n) emitters: Cm-242, Cm-244,
  Am-241, Pu-238/240).
- **Table 14 "Thick-Target Yields"** oxygen row → `thick_target_O_yield` (0.059 n / 10⁶ α at
  5.2 MeV = **5.9e-8 n/α**) — used ONLY to bound the (α,n) of inventory α-emitters absent from
  Table 13 (the dropped-(α,n) warning).

**Two read-time integrity checks (the §12 trap), in PROVENANCE.md:** (1) `pdftotext -layout`
scrambled the table — values were read from the **rendered image** and every Total-Half-Life
cross-checked to the known half-life to confirm row pairing; (2) the "Yield (α/s-g)" column =
the isotope **specific activity** (Pu-238 6.4e11 ≈ SA), proving the oxide column is **per gram
of ISOTOPE** → the per-decay denominator is λ_total·N_A/M.

## The model

Mirror M9 exactly, as a parallel term:

    yield_an_per_decay[X] = oxide_n_s_g[X] / specific_activity_Bq_per_g(X)     (n/decay)
    S_an(t) = Σ_X yield_an_per_decay[X] · A_X(t)                               (n/s)
    rate(t) = (h̄ · T_n / 4π d²) · (S_sf(t) + S_an(t))                          (Sv/s)

Same representative Cf-252 SF spectrum (h̄ flat over 0.5–6 MeV — the (α,n) spectrum is softer,
~1–5 MeV, so this is a real but defensible approximation, surfaced), same shield T_n. Total
specific activity on both sides → self-consistent even for Pu-241 (mostly β; PANDA's oxide value
already embeds the tiny α branch).

## What's validated (be precise — the M9 standard)

- **Independently validated: the per-gram-of-isotope BASIS.** PANDA's "Yield (α/s·g)" column vs
  the *independent* ICRP-107 α-branch × rd specific activity agree ≤4.1 % across the 18 isotopes
  → the per-gram columns are per gram of ISOTOPE, so ÷λN_A/M is the right conversion. A ÷
  oxide-mass slip (~270 vs ~238) is +13.4 % → caught (gated at 8 % in `build_alpha_n_block`).
  This is the real safeguard, and it is non-tautological (two independent data sources). A
  `yield = oxide/SA` → `yield·SA ≈ oxide` round-trip would only echo the build's own arithmetic.
- **NOT independently validated: the (α,n) MAGNITUDE** — it rests on PANDA. The Pu-238 oxide total
  (dataset-SF + PANDA-(α,n) ≈ 1.60e4 n/s·g) is only a cross-pipeline **SF** sanity gate: the
  canonical value ≈ PANDA's own column sum and the (α,n) term echoes PANDA regardless of basis, so
  it exercises the dataset-SF ↔ PANDA-SF agreement (already M9-validated), nothing more. No second
  (α,n) source is fabricated — PANDA is the standard ref (parallel to M9's ν̄-rests-on-IAEA/Holden).

## Coverage / honesty (surfaced, never silent)

(α,n) modeled for Table-13 isotopes present. α-emitters absent from Table 13 (Am-243,
Cm-243/245/246/…) → `dropped_alpha_branch` (α/decay from emissions), bounded by `5.9e-8 n/α`,
reported as the **dropped-(α,n) fraction** at the evaluated cooling. Reframe: **best estimate**,
residual caveats kept = thick-target ±factor; UO₂≈PuO₂ transfer; soft (α,n) spectrum on the SF h̄.

## Files

- **Data** — `data/vendor/panda_alpha_n/{alpha_n_oxide.json, PROVENANCE.md}`;
  `data/build/build_spent_fuel.py` (`build_alpha_n` in the neutron block, Pu-238 cross-check,
  dropped-(α,n)); schema **v2 → v3**. Rebuild `data/spent_fuel/*.json`.
- **Engine** — `engine/spent_fuel_neutron.py` (`alpha_n_yields` + `dropped_alpha_branch` →
  `rate_si` total + `rate_si_sf`/`rate_si_alpha_n` split + `dropped_frac` combined).
  `engine/bridge.py` passes the new block keys.
- **Web** — `bridge.ts` (split + dropped_frac fields), `state.svelte.ts`
  (`neutronDroppedFrac` → combined), `Dose.svelte` (reframe note + SF/(α,n) split readout),
  `Honesty.svelte` register item. No serializer bump (only the loaded source id persists).
- **Tests** — `tests/test_spent_fuel_data.py` (+α,n block, Pu-238 anchor), `tests/
  test_dose_spent_fuel_neutron.py` (+(α,n) in the source, split, dropped-(α,n)),
  `web/drive_browser.mjs` (M12 lit path, dev + built). `HANDOFF_PLAN.md` §11 reframe.

## Open / future

- Cm-246/Am-243 etc. (α,n) via Table-14 O-yield + per-isotope α energy would remove the
  dropped-(α,n) set (a method mix; deferred — the residual is small since Cm-246's (α,n) ≪ its SF).
