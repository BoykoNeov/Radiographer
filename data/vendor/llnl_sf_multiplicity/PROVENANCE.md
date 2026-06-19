# Vendored upstream — LLNL SF prompt-neutron multiplicity distributions (Cm-246/248 ν̄)

This directory holds the citable source for the **spontaneous-fission prompt neutron
multiplicity ν̄** of **Cm-246 and Cm-248**, which are **absent from the IAEA safeguards table**
(`../iaea_sf_nu/`, 18 isotopes only) yet matter for spent fuel: once Cm-244 (t½ 18 yr) decays,
Cm-246 (t½ 4760 yr) becomes the dominant spontaneous-fission neutron emitter at multi-century
cooling. Vendoring these closes the original M9 deferral and extends the valid cooling regime.

## Why a distribution, not a single number

The cleanest citable form available is the full SF prompt-neutron **multiplicity distribution**
P(ν) — the probability of emitting ν neutrons in one spontaneous fission. ν̄ is then a
deterministic derivation, **not a transcription from memory** (the §11 no-fabrication
discipline — cf. the AmBe spectrum and the β Cross-Berger kernel):

```
ν̄ = Σ_k  k · P(k)
```

`sf_multiplicity.json` is a **verbatim transcription of Table 4** of the report below.

## Source

| Layer | Detail |
|---|---|
| Report | **J.M. Verbeke, C. Hagmann, D. Wright (LLNL)**, *"Simulation of Neutron and Gamma Ray Emission from Fission and Photofission. LLNL Fission Library 2.0.2"*, **UCRL-AR-228518-REV-1**, 2016-10-24. |
| File | `UCRL-AR-228518-REV-1_LLNL_Fission_Library_2.0.2.pdf` — fetched from `https://nuclear.llnl.gov/simulation/fission.pdf`. |
| Table used | **Table 4** — "Neutron number distributions for spontaneous fission, along with their references" (page 6). |
| Cm-246/248 P(ν) provenance | ref **[12] = BNL-36467** = N. Holden & M. Zucker, *"Neutron Multiplicities for the Transuranium Nuclides"*, Brookhaven, 1985 — **the same Holden & Zucker 1985 evaluation the IAEA `SF_n-Yield` report cites (its ref [16]) for the curium nu-bars**. |
| Independent cross-check (Cm-248) | ref **[11]** = A.S. Vorobyev et al., *AIP Conf. Proc.* **769**, 613 (2005). |
| Method-validation rows (Cm-242/244) | ref **[9]** = N.E. Holden & M.S. Zucker, BNL-NCS-35513. |

## Derived ν̄ and validation

| Nuclide | source (ref) | Σₖ k·P(k) | role |
|---|---|---|---|
| Cm-242 | Holden BNL-NCS-35513 [9] | **2.540** | method-validation — matches IAEA Table 1 ν̄ 2.540 |
| Cm-244 | Holden BNL-NCS-35513 [9] | **2.720** | method-validation — matches IAEA Table 1 ν̄ 2.720 |
| **Cm-246** | **Holden & Zucker BNL-36467 [12]** | **2.930** | **vendored ν̄** (→ `../iaea_sf_nu/sf_nubar.json`) |
| **Cm-248** | **Holden & Zucker BNL-36467 [12]** | **3.130** | **vendored ν̄** |
| Cm-248 | Vorobyev 2005 [11] | 3.129 | independent cross-confirm |

The two method-validation rows reproduce the **IAEA-vendored** Cm-242/244 ν̄ *exactly* with the
same Σₖ k·P(k), proving the transcription + derivation before it is applied to the new nuclides.
`tests/test_spent_fuel_data.py` re-runs this computation as a regression check.

**Honest asymmetry (do not smooth over):** Cm-248 is **double-confirmed** (BNL 3.130 vs Vorobyev
3.129). **Cm-246 rests on the single (authoritative) Holden & Zucker source** — no independent
second evaluation is in hand; the smooth Cm trend (2.54 → 2.72 → 2.93 → 3.13, ≈ +0.19 per 2 u)
is corroborating but not an independent measurement.

## Drift guard

SHA-256 of the vendored PDF:

```
177935ece734729027c8474b90f464e2f0d604e320e3360770dfad3f814afc01  UCRL-AR-228518-REV-1_LLNL_Fission_Library_2.0.2.pdf
```

## Licence

The report (UCRL-AR-228518-REV-1) is a **publicly distributed DOE / LLNL technical report** —
vendored here for auditability on the same basis as the IAEA `SF_n-Yield` PDF. (The accompanying
LLNL Fission Library *software* carries a BSD-style licence, UCRL-CODE-224807, © 2006-2016 LLNS,
LLC; that governs the code, not this PDF.) Regardless of the report's distribution terms, the
**numeric multiplicity distributions used here are uncopyrightable facts**, transcribed into
`sf_multiplicity.json`; attribution is carried there, in the build `nubar_source`, and in the
shipped vectors' provenance. The binding repo data-licence constraint remains the non-commercial
ICRP-107 emission data — this addition neither loosens nor tightens it.
