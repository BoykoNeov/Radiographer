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

## Cross-check (what it actually validates — the SF branching ratio, NOT ν̄)

The build compares `yield_per_decay = (_SF/_A)·ν_p` against the IAEA's own
`n_yield_n_s_g / specific_activity` for Cm-244 (both ≈3.7e-6 n/decay, ≈1.1e7 n/s/g). **The same
ν_p appears on both sides and cancels** (`n_yield/SA = ν_p·λ_SF / λ_tot = ν_p·T_tot/T_SF`), so
the ~2% agreement validates the **SF branching ratio** (Serpent2 `_SF/_A` = 1.38e-6 vs IAEA's
implied `T_tot/T_SF` = 1.351e-6; textbook 1.37e-6) and catches a `_SF` units/mapping slip — it is
**not** an independent check on ν_p or on the absolute neutron yield, which rest on the cited
IAEA/Holden ν_p.

## Scope (no fabrication, no silent drop)

This IAEA evaluation covers the **18 safeguards isotopes only** (`src: "IAEA-T1"` in
`sf_nubar.json`). The discharge vectors also contain minor SF emitters absent from it — chiefly
**Cm-246** (t½ 4760 yr), which dominates the SF source once Cm-244 (t½ 18 yr) decays away at
multi-century cooling, plus **Cm-248** and a long tail (Cm-250, Cf-250, …).

**Cm-246/248 ν̄ are now vendored** (closing the original deferral) — NOT typed from memory, but
**derived (ν̄ = Σₖ k·P(k)) from the Holden & Zucker BNL-36467 SF multiplicity distributions**
tabulated in `../llnl_sf_multiplicity/` (`src: "HZ-BNL36467"`). This is the same Holden & Zucker
1985 evaluation the IAEA report itself cites for the curium nu-bars (its ref [16]). The derivation
is validated against this very table: the same Σₖ k·P(k) over the source's Cm-242/Cm-244
distributions reproduces the IAEA Cm-242/244 ν̄ (2.540 / 2.720) **exactly**. With Cm-246/248
modeled, the **dropped SF-rate fraction stays < 0.1 % out to 1 Myr** for the shipped vectors (it
was capped at ~1 century cooling before), so the valid cooling regime now spans the whole
meaningful range. The engine still surfaces the residual dropped fraction at the evaluated cooling
time as a loud warning (the dangerous direction is under-, not over-count). See
`../llnl_sf_multiplicity/PROVENANCE.md`.

## Drift guard

SHA-256 of the vendored PDF:

```
3bdf93e338101f41ee269a898a3020c15b1ccb4e8b3554127ee25057dcf63713  SF_n-Yield_20150313.pdf
```

## Licence

IAEA Nuclear Data Section publication, distributed for scientific use with attribution
(carried in the `source_ref` of the built vectors). Only the small transcribed `sf_nubar.json`
and this provenance live in git; the PDF is vendored for auditability.
