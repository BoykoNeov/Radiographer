# Vendored upstream — IAEA spontaneous-fission prompt ν̄ (SF neutron multiplicity)

This directory holds the citable source for the **spontaneous-fission prompt neutron
multiplicity ν̄ (ν_p)** used to turn the SCK-CEN spent-fuel SF *fission* rate (`_SF`) into a
**neutron source** (HANDOFF_PLAN §8; M9 spent-fuel neutron output).

## Why this is needed

The SCK-CEN Serpent2 discharge library (`../sckcen_sf/`) carries a per-nuclide `_SF` column
which is the **spontaneous-fission rate (fissions/s)**, NOT neutrons/s — verified because
`_SF/_A` reproduces the textbook SF *branching ratios* (Cm-244 1.38e-6, Cm-242 6.1e-8,
Pu-240 5.7e-8, U-238 5.46e-7). To get the neutron emission rate each nuclide's fission rate
must be multiplied by its SF prompt multiplicity ν̄:

```
yield_per_decay(n) = (_SF_n / _A_n) · ν̄_n          # neutrons per decay of nuclide n
S(t) = Σ_n yield_per_decay(n) · A_n(t)              # total SF neutron source (n/s)
```

The ratio `_SF/_A` is basis-independent (the SCK-CEN `_A` geometry factor ≈0.535 cancels,
exactly as `_H/_A` does), so the yields are clean regardless of the activity-column basis.

## Source

| Layer | Detail |
|---|---|
| Report | **S. Simakov, M. Verpelli, N. Otsuka (IAEA Nuclear Data Section)**, *"Update of the nuclear data for the neutron emissions for actinides of interest in safeguards"*, IAEA NDS, 2015-03-13. |
| File | `SF_n-Yield_20150313.pdf` — fetched from `https://nds.iaea.org/sgnucdat/SF_n-Yield_20150313.pdf`. |
| Table used | **Table 1** — "Updated Half-Lives, SF Half-Lives, SF prompt nu-bars ν_p and calculated SF neutron Yields" for 18 trans-actinides (Th-232 … Cf-252). |
| ν_p provenance (per the report) | JEFF-3.1 evaluation (Nichols & James 1981) except ²⁴²Cm/²⁴⁴Cm/²⁴⁹Bk from Holden (1985); SF half-lives from IAEA-CRP / DDEP. |

`sf_nubar.json` is a **verbatim transcription of Table 1** (ν_p, the IAEA-calculated specific
neutron yield n/s/g, total + SF half-lives), used by `../../build/build_spent_fuel.py`.

## Cross-validation (apples-to-apples, SF only)

The build cross-checks each isotope two independent ways that must agree:
`yield_per_decay = (_SF/_A)·ν_p` (Serpent2 fission rate × IAEA ν̄) vs the IAEA's own
`n_yield_n_s_g / specific_activity`. For Cm-244 both give ≈3.7e-6 n/decay (≈1.1e7 n/s/g),
the dominant SF emitter — agreement to ~2%.

## Scope / deferral (no fabrication, no silent drop)

This evaluation covers the **18 safeguards isotopes only**. The discharge vectors also contain
minor SF emitters absent from it — chiefly **Cm-246** (and Cm-248, Cf-250, …). These are
**< 0.34 % of the SF rate at discharge through ~1 century cooling**, but Cm-246 (t½ 4760 yr)
eventually dominates once Cm-244 (t½ 18 yr) decays away. Rather than insert a ν̄ from memory
(the §11 no-fabrication discipline — cf. the AmBe spectrum and the β Cross-Berger kernel), the
build **drops** these nuclides and the engine **surfaces the dropped SF-rate fraction at the
evaluated cooling time** as a loud warning (the dangerous direction is under-, not over-count).
A future upgrade is to vendor Cm-246/248 ν̄ from PANDA Table 11-1 / ENDF.

## Drift guard

SHA-256 of the vendored PDF:

```
3bdf93e338101f41ee269a898a3020c15b1ccb4e8b3554127ee25057dcf63713  SF_n-Yield_20150313.pdf
```

## Licence

IAEA Nuclear Data Section publication, distributed for scientific use with attribution
(carried in the `source_ref` of the built vectors). Only the small transcribed `sf_nubar.json`
and this provenance live in git; the PDF is vendored for auditability.
