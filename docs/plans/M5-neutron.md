# M5 — Neutron (tabulated source terms + fluence-to-dose)

**Status:** in progress
**Milestone (HANDOFF_PLAN.md §10, §6.3):** external **neutron dose** for **prebuilt
sources only** (v1 does not derive neutron output from a loaded inventory — SF + (α,n) is
ORIGEN/SOURCES territory). Ship **tabulated** source strength + spectrum per source, fold
against ICRP-74 / ICRP-116 fluence-to-dose coefficients. Neutron output is **grayed out
for user-defined inventories** (§6.3).

## Goal

"Done" =
- A `NeutronDoseModel` that, for a **prebuilt source key** (Cf-252, AmBe) and a dose
  quantity (+ geometry for effective), computes a neutron dose-rate **time series** from the
  parent nuclide's activity series — obeying §3 "solve once, evaluate many" (the
  spectrum-averaged coefficient h̄ and any shield factor are fixed; distance/time/activity
  are the cheap evaluate-many axes).
- Two new datasets landed with regression tests (validation-first):
  1. **Neutron fluence-to-dose** — extends the M2 conversion pipeline with a `particle`
     axis (clean; the M2 schema was shaped for exactly this).
  2. **Neutron source terms** — strength (neutrons per parent decay) + normalized spectrum
     + source-correlated γ lines, per source.
- The validation triangle (below) closed against named references.

## Scope (LOCKED for M5 — user decisions 2026-06-16)

- **Shielding → DEFERRED to M6.** The milestone is literally "tabulated source terms +
  fluence-to-dose"; bare-source dose (both quantities) is the M5 deliverable. The
  hydrogenous removal-cross-section model (§6.3) needs its own Σ_R dataset + fast-neutron
  HVL validation and lands with the M6 shield builder. (HANDOFF_PLAN §6.3 stays as the
  eventual capability; no §13 number.)
- **Source set = Cf-252 + AmBe.** Cf-252 spontaneous fission (analytic Watt/Maxwellian,
  bulletproof provenance) and AmBe (α,n) (ISO 8529-1 tabulated spectrum). **Fallback:** if
  AmBe cannot be sourced cleanly/citably (the M4/Cross-Berger lesson), ship Cf-252 only and
  say so. Spent-fuel neutron is entangled with the §13-OPEN #4 discharge vectors → **M7**.
- **Both dose quantities** — H\*(10) (default) + effective (per ICRP-116 geometry), to match
  the gamma engine. Fluence-to-dose is "trivial once you have fluence" (§6.3).
- **Source-correlated γ → MODELED** via the existing M3 `photon_override` path (the exact
  channel M4 bremsstrahlung used). AmBe's 4.438 MeV γ is a real dose contributor; Cf-252
  prompt-fission γ likewise. They are NOT in the inventory's ICRP-107 decay lines (they come
  from the (α,n)/fission reaction), so they are carried as synthetic photon lines keyed to
  the parent nuclide and scored through `GammaDoseModel`.

## Plan

### Time-coupling — handle-coupled, NOT standalone (advisor)

§8 defines a prebuilt source as *named inventory + tabulated neutron term*, so the parent
already has a decay handle with an activity series. Cf-252 (t½ = 2.645 y) has a
time-dependent strength, and spent-fuel cooling (§8) will need this too. So:

- Store the source term as **neutrons per decay of the named parent** (time-invariant) +
  a normalized spectrum. `S(t) = n_per_decay · A_parent(t)` (neutrons/s).
- `neutron_dose(handle, req)` with `req["source"]` = the source key: pulls `A_parent(t)`
  from the handle, scales by n/decay → S(t), folds the spectrum → h̄, divides by 4πd².
- The **`source` key is the §6.3 gray-out gate**: no key ⇒ the UI never calls
  `neutron_dose` ⇒ neutron grayed out for user inventories. The parent nuclide must be
  present in the handle's inventory (it is, for a prebuilt source) — a missing parent is a
  loud error, never a silent zero.

This rides "solve once, evaluate many": one Bateman solve, one fixed per-decay coefficient
`C = n_per_decay · h̄_SI`, one matvec `rate(t) = (C/4πd²)·A_parent(t)`.

### Dose chain

```
H*(10)_rate(t,d) = (n_per_decay · A_parent(t) / 4π d²) · h̄        h̄ = Σ_bins φ_i · h(E_i)
```

- `φ_i` = normalized per-bin fluence fraction (Σφ_i = 1) — see normalization trap below.
- `h(E_i)` = neutron fluence-to-dose coefficient (pSv·cm²) at the bin's representative
  energy, log–log interpolated on the vendored grid; → SI (Sv·m²) in one conversion block.
- h̄ is the **spectrum-averaged** coefficient — computed once (solve-once).

### Dataset 1 — neutron fluence-to-dose (extend M2 conversion)

- **Vendor** (same OpenMC commits as the photon tables, parallel files — CONFIRMED to
  exist at these paths, identical column layout):
  - `icrp116/neutrons.txt` — effective dose per fluence, 6 geometries, 1e-9 MeV → 10 GeV.
    **CLEAN** (develop `53d98ce`, verbatim → independent re-parse proves canonical==upstream).
  - `icrp74/neutrons_H10.txt` — H\*(10) per fluence, single column, 1e-9 → **20 MeV**.
    **DEGRADED** (PR #3256 fork `f89d146`, unmerged transcription) — faithfulness leans on
    the ISO-averaged cross-check (validation triangle), exactly as the photon H\*(10) leaned
    on the IAEA slab table.
- **build_conversion.py** — add a neutron build; output `hstar10_neutron.json` +
  `effective_neutron_<GEOM>.json` (6). Pin the two new vendored sha256s.
- **engine/conversion.py** — add a `particle` parameter (default `"photon"` so every
  existing call site is untouched). `_filename(quantity, geometry, particle)`; validate the
  embedded `particle` field. Neutron filenames carry a `_neutron` suffix.
- **engine/photon_interp.py** (`interp_conversion`) — thread `particle` through; the fold is
  log–log on energy (these coeffs are smooth, no edges). The neutron grid spans thermal
  (1e-9 MeV) → GeV; nothing structurally new vs the photon path.
- **Off-grid contract (established):** a spectrum bin **above 20 MeV** for H\*(10) (or 10 GeV
  effective) → loud `ABOVE_GRID` error (dropping a high-E bin underestimates dose). Below
  the 1e-9 MeV floor → logged skip. Both Cf-252 and AmBe fit under 20 MeV; the contract is
  enforced regardless.

### Dataset 2 — neutron source terms (new `data/neutron_sources/<source>.json`)

```jsonc
{
  "schema_version": 1,
  "source": "Cf-252",
  "parent_nuclide": "Cf-252",          // inventory nuclide whose decay drives emission
  "neutrons_per_decay": 0.116,         // time-invariant; S(t)=n_per_decay·A_parent(t)
  "spectrum": {                        // normalized to Σ fluence = 1 over the bins
    "E_lo_MeV": [ ... ], "E_hi_MeV": [ ... ],   // bin edges
    "fluence_frac": [ ... ]                     // per-bin fraction (NOT per-lethargy)
  },
  "source_gammas": [ { "E_MeV": 4.438, "yield_per_decay": ... } ],  // photon_override lines
  "source_ref": "...", "provenance": "..."
}
```

- **Cf-252:** `neutrons_per_decay` = SF branch (3.09 %) × ν̄ (≈3.76) ≈ **0.116** — the build
  derives it and validates it reproduces the published **2.3×10¹² n/s/g** specific yield (a
  checkable anchor, not asserted). Spectrum = Watt/Maxwellian (kT≈1.42 MeV) reconstructed +
  binned, OR the PNNL-19273 / ISO 8529-1 tabulation. Prompt-fission γ as source_gammas.
- **AmBe:** ISO 8529-1 reference spectrum (Kluge–Weise PTB), tabulated. `neutrons_per_decay`
  is **construction-dependent / nominal** (≈70 n per 10⁶ Am-241 α ≈ 7×10⁻⁵) — flag as
  order-of-magnitude in the honesty register. 4.438 MeV γ as source_gamma.
- **Normalization trap (advisor §12):** neutron spectra are usually tabulated as fluence
  **per unit lethargy** (φ_E·E), not per energy. The build converts whatever the source
  gives into **per-bin fractions** and asserts Σ = 1 — sidesteps the lethargy/per-energy
  ambiguity at the one place it can be checked.

### Engine — `engine/neutron_dose.py`

`NeutronDoseModel(source_key, quantity, *, geometry=None)`:
- loads the source term + the neutron conversion grid; computes h̄ once (solve-once);
- `dose_rate_series(activities_result, distance_m)` → one matvec `(C/4πd²)·A_parent(t)`;
- `source_gamma_override()` → `{parent: source_gammas}` for the γ channel.
- `NeutronSourceError` (bad/missing source key or spectrum) + reuse `DoseError` patterns.
- **w_R NOT double-counted** (advisor): the H\*(10)/effective coefficients are already Sv per
  fluence — w_R(E) is baked in. The fold multiplies fluence by Sv/fluence; no extra w_R.

### Bridge — `engine/bridge.py`

`neutron_dose(handle, request_json)`:
`{"times_s":[...], "source":"Cf-252", "quantity":"ambient_H10", "distance_m":1.0,
  "geometry":null, "include_source_gamma":true, "gamma_quantity":"ambient_H10"}` →
`{ok, quantity, si_unit:"Sv", per, times_s, distance_m, source, parent, rate_si, warnings,
  source_gamma:{γ-dose series}|null}`. Add `NeutronSourceError` to `_EXPECTED_ERRORS`.

## Validation triangle (the crux — closes the degraded-trust loop)

Fold (vendored spectrum × vendored neutron H\*(10) table) → spectrum-averaged h̄, and check
it equals the **published** ISO 8529-1 / PNNL-19273 spectrum-averaged h\*(10) for that exact
source. Three independent things meeting (spectrum, conversion table, fold/normalization)
validates the whole chain in one shot — and **is** the independent cross-check for the
unmerged-PR (degraded-trust) neutron H\*(10) table.

- **Cf-252:** published bare h\*(10) ≈ **385 pSv·cm²** (TO VERIFY vs PNNL-19273 / ISO 8529-1
  — not asserted from memory). Back-of-envelope: 2.55 mrem/h per µg at 1 m back-solves to
  h ≈ 385 pSv·cm² — corroborates. Also: 1 µg (2.3×10⁶ n/s) at 1 m → ~2.6 mrem/h H\*(10).
- **AmBe:** published h\*(10) ≈ **391 pSv·cm²** (TO VERIFY).
- **n/decay anchor:** Cf-252 0.116 reproduces 2.3×10¹² n/s/g (build-time check).
- **Guards:** off-grid contract enforced; spectrum Σφ=1; w_R not double-counted; monotone in
  1/d².

## Honesty register additions (→ HANDOFF_PLAN §11 at close)

- Neutron source terms are **tabulated, not derived**; prebuilt sources only (already in §11
  — extend with the specifics below).
- **AmBe neutron yield is construction-dependent / nominal** (order-of-magnitude).
- **Neutron H\*(10) coefficients are from an unmerged OpenMC PR** (degraded trust),
  independently cross-checked via the ISO-averaged coefficient (the triangle).
- **Source-correlated γ (AmBe 4.438 MeV, Cf-252 prompt fission) ARE modeled** via the γ
  engine override — state that they're reaction-correlated, not decay lines.

## Key files

- `data/vendor/openmc_dose/{icrp116_neutrons,icrp74_neutrons_H10}.txt` (+ MANIFEST, PROVENANCE)
- `data/build/build_conversion.py` (neutron build), `data/conversion/{hstar10_neutron,
  effective_neutron_*}.json`
- `data/build/build_neutron_sources.py` (new), `data/neutron_sources/{Cf-252,AmBe}.json`
- `engine/conversion.py` (particle axis), `engine/photon_interp.py` (particle thread)
- `engine/neutron_dose.py` (new), `engine/bridge.py` (`neutron_dose` entry)
- `tests/test_conversion_data.py` (neutron pillars), `tests/test_neutron_sources_data.py`
  (new), `tests/test_dose_neutron.py` (new), bridge neutron tests

## Open questions / risks

- **AmBe sourcing** (gating): ISO 8529-1 spectrum reproduced across open refs (PTB,
  scholars.direct JANP-4-005, arXiv 2111.02774); a clean machine-readable tabulation must be
  obtained at build time. Fallback = Cf-252 only.
- **Exact ISO/PNNL averaged coefficients (385/391)** are TO VERIFY against source, not
  asserted — the validation anchors depend on them.
- **Conversion `particle` refactor** must not regress the 7 photon files / their 12 tests
  (default `particle="photon"` everywhere).
