# Beam probe — test a shield against an X-ray tube / a specific line

**Status:** done (2026-08-19)
**Milestone (HANDOFF_PLAN.md §10):** post-v1 shield-builder extension. Adds the missing half of
§9's "Shield builder" spec: the stack can now be evaluated as a *shield*, not only as a filter in
front of the loaded inventory.

## Goal

Answer the question a shield designer actually asks — *"how much of a 60 keV line / of a 100 kVp
X-ray tube beam gets through this stack?"* — without loading a radionuclide inventory at all.

"Done" means:

- a **monoenergetic** probe whose transmission is **bit-for-bit** the factor the γ dose path folds
  per line (no re-derivation), with the buildup factor, depth in mean free paths, a per-layer
  μ/ρ · μ · mfp breakdown, and HVL/TVL of the detector-side material;
- an **X-ray tube** probe: an idealized Kramers continuum → inherent filtration → the stack, with
  a quantity-weighted transmission, the beam-hardening pair (mean energy and HVL in aluminium,
  in vs out), and the dropped-incident fraction;
- a transmission-vs-energy curve for the whole stack (the teaching plot: where the stack is
  opaque, and where lead's 88 keV K-edge inverts "higher energy penetrates more");
- validation by internal consistency + physical direction (see below), no new dataset;
- everything **stateless** — no handle, no solve, no cursor — and gated on the registry staying 1.

## Plan (as built)

`engine/beam.py` — new module, no new data:

| function | what it does |
| --- | --- |
| `scored_band(layers, quantity?)` | the `(E_lo, E_hi)` window where transmission is *scoreable* |
| `line_probe(layers, E_MeV)` | the mono-line probe; delegates to `dose._stack_transmission` |
| `transmission_curve(layers)` | broad + narrow transmission across the band |
| `kramers_spectrum(kvp)` | Kramers thick-target photon-number spectrum, arbitrary scale |
| `tube_probe(layers, kvp, filtration_mm_al, quantity, …)` | the polyenergetic fold |

`engine/bridge.py` — `beam_probe(payload_json)`, **stateless** (the `materials()` /
`convert_unit()` pattern), plus `buildup_band_MeV` added to each `materials()` row so the UI can
constrain the probe energy client-side. `BeamError` registered as an expected domain error (loud,
structured, no traceback).

Web: `BeamProbe.svelte` mounted **inside** the Shield panel (it measures the stack, so it belongs
with the stack), ephemeral store state next to `neutronSweep*` (`beamMode` / `beamLineKeV` /
`beamKvp` / `beamFiltrationMmAl` / `beamProbe` / `beamError`), refreshed from `recomputeDose()` and
a no-op while the probe is closed. Glossary gained `beam-hardening`.

## Key decisions

1. **Transmission only — never an absolute dose rate.** A tube's output is mGy/mAs at 1 m: a
   tube-and-geometry calibration that is not in `data/`. Emitting a Sv/h for a tube beam would be
   fabrication, so every number is a ratio, a thickness, a mean energy, or a relative spectrum
   shape, and the panel tells the user to multiply their *own measured* unshielded rate by the
   transmission. This is also what keeps the feature inside §2's locked scope ("shielding:
   arbitrary stack of materials × thicknesses, with dose-vs-thickness output") — it probes the
   stack; it does **not** add a source to the §8 catalog. §2 was not widened.

2. **The design is shaped by the buildup floor, not caveated after the fact.** ANS-6.4.3 G-P
   buildup starts at **15 keV** (**30 keV for lead**) and ends at 15 MeV, and
   `photon_interp.interp_buildup` *raises* below the floor rather than substituting `B = 1` (which
   would under-count dose — the silent surrogate §6.5 forbids). A diagnostic X-ray spectrum lives
   partly below both floors, so:
   - one **scored band** per stack = max(10 keV δ, every layer's buildup floor, every μ/ρ floor)
     … min(buildup ends, μ/ρ ends, conversion-grid end for the chosen quantity);
   - out-of-band bins are dropped from **both** numerator and denominator, and the excluded
     incident air-kerma weight is reported as `dropped_incident_fraction` (the same "never silent"
     idiom as the dropped SF-rate and dropped-(α,n) fractions);
   - the line-mode input is **clamped** to the band in the UI, so an off-band probe is prevented
     rather than discovered as an engine error — while the engine still raises if asked directly.

   **Bias direction:** the dropped photons are the softest, i.e. the ones the stack removes
   hardest, so excluding them from both sides makes the reported transmission an **upper bound**
   on the whole beam's transmission (it over-states what gets through — the conservative direction
   for a shield). It is a ratio *over the scored band*; the dropped fraction is how much of the
   beam that excludes, which is why it is a headline card and not a footnote.

3. **Two bands, deliberately.** The *incident* beam's own characterization (mean energy, HVL in
   aluminium) is a property of the beam, so it is computed over a stack-independent **beam band**
   `[δ, endpoint]` using narrow-beam μ/ρ only. Only the stack transmission and the *transmitted*
   beam use the buildup-limited scored band. Without this split, adding a lead layer would appear
   to harden the beam it is being tested against — a real trap, since lead lifts the floor from 15
   to 30 keV. The gate asserts the incident numbers do not move when lead↔aluminium is swapped.

4. **X-ray tube = Kramers thick-target continuum, tungsten only.** `N(E) ∝ (E_max − E)/E`
   (Kramers 1923 — the same model `engine.beta_dose` already uses for in-shield bremsstrahlung),
   shaped by **inherent filtration in mm Al equivalent**, which is how tubes are specced and which
   stands in for anode self-absorption (absent from Kramers' law). Explicitly **no tungsten K
   characteristic lines** (they appear above roughly 70 kVp): their energies and yields are not in
   `data/` and are not reconstructed from memory — the same no-fabrication line that deferred the
   AmBe spectrum and the Cross-Berger β kernel. Mo/Rh anodes are **not** offered at all, because a
   mammography beam is characteristic-line dominated and a continuum-only model would be
   qualitatively wrong there, not merely imprecise. kVp is refused outside 5–450 kV rather than
   silently clamped.

5. **Line presets come from the loaded inventory's own scored γ lines**, not a hardcoded line
   table — nothing to drift from ICRP-107, nothing to fabricate. They are filtered to the scored
   band so a preset can never be an off-band probe. Picked by per-decay strength but **listed in
   energy order**, deliberately not ranked by dose at the cursor: the user is choosing an energy,
   and a contribution-ranked list would re-order under the time slider as daughters grow in,
   making the dropdown's shown option jump mid-scrub. Energy order also makes the list
   cursor-independent, so scrubbing cannot churn it at all.

## Validation

No new dataset ⇒ no external table to reproduce, and published HVL tables for diagnostic beams are
deliberately **not** asserted (reconstructing one from memory is the fabrication line above). What
`tests/test_beam.py` (23 tests) asserts instead:

- **the mono-line probe equals `dose.stack_transmission` exactly** — one shared transmission core,
  so a probe at a real line energy reconciles with the γ dose card by construction;
- **a one-bin tube spectrum reproduces the mono-line transmission exactly** — the non-tautological
  check on the whole weighting/normalization fold;
- mono-line transmission is **identical across all three dose quantities** (it multiplies fluence),
  while the *spectrum-averaged* transmission is **not** — both directions pinned;
- `T_broad ≥ T_narrow` always; `T_narrow == exp(−Σμx)`; `hvl_cm == ln2/μ` exactly; the broad-beam
  HVL is strictly larger (buildup adds scatter back);
- lead's 88 keV K-edge shows as transmission *falling* with rising energy;
- the band follows the layers' buildup floors, and a sub-floor probe / an entirely sub-floor beam
  raises loudly;
- direction: beam hardening (mean E and HVL both rise), HVL monotone in kVp and in filtration,
  transmission monotone in thickness, dropped fraction larger for lead than aluminium and smaller
  with heavier inherent filtration.

`tests/test_bridge.py` adds the stateless contract (registry unchanged, no handle), the
structured-error shape, and the "no `*_si` / no `rate` key anywhere in the tube payload" assert
that keeps decision 1 honest. `web/drive_browser.mjs` → `runBeamProbe` covers the wiring in a real
browser: the mode buttons, registry == 1 across probes, curve↔card agreement, the UI clamp, the
re-probe on a stack change, the two-band invariance, and that closing the probe stops the call.

## Open questions / risks

- **The absolute HVL in mm Al is indicative, not a QA number.** The Kramers model has no anode
  self-absorption of its own, so the modelled beam is softer than a real one at the same nominal
  filtration and the HVL lands low (~2.6 mm Al for 100 kVp / 2.5 mm Al, against the ~3.7–4 mm a
  real tube would show). The *shape* of transmission-vs-energy and the hardening *trend* are the
  trustworthy outputs. Surfaced in §11 and in the panel's own copy.
- A citable machine-readable tube spectrum (TASMIP-style polynomial coefficients, or SpekPy's
  semi-analytic model) would upgrade the tube mode from "idealized" to "validated against a
  published spectrum". Deferred, not reconstructed from memory — the same rule as AmBe.
- The tube fold is ~240 bins × a per-bin interpolation, so a probe is a visible-but-small Pyodide
  call; it is a no-op while the probe is closed, and it never runs on a cursor scrub (it does not
  depend on time or distance). If it ever needs to get cheaper, the per-bin μ/ρ lookups vectorize
  the same way `beta_dose`'s Loevinger kernel did.
