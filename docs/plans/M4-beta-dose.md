# M4 — Beta dose (skin dose + bremsstrahlung-in-shield)

**Status:** done ✅
**Milestone (HANDOFF_PLAN.md §10, §6.2):** external **beta skin dose** (7 mg/cm²
basal layer) from a point source via a point-kernel folded with the beta
spectrum/endpoint, ±20–30 %; plus **bremsstrahlung-in-shield** (high-Z shielding
of beta generates X-rays — "more lead can increase dose").

## Results (done)

- **`engine/beta_dose.py`** — `loevinger_nu/c/J` (the arXiv-sourced kernel),
  `BetaSkinDoseModel` (per-branch solve-once `C_n^β(d)`, disk-averaged contact dose ×
  exact solid-angle geometry × air-mass transmission), `bremsstrahlung_lines` /
  `bremsstrahlung_override` (Kramers thick-target, f=3.5e-4·Z·E), `BetaDoseError`.
- **`engine/dose.py`** — `GammaDoseModel` gained `photon_override` so brems lines reuse
  the validated per-line/quantity/scoring-floor machinery (γ-channel coupling).
- **`engine/emissions.py`** — `beta_spectra` / `beta_endpoint_MeV` accessors.
- **`engine/bridge.py`** — `beta_dose(handle, req)` (skin-dose series + optional
  bremsstrahlung γ-dose series); `BetaDoseError` in the structured-error set.
- **Tests:** `tests/test_dose_beta.py` (19) + 2 bridge beta tests. **Full suite 182
  pass**, no M0–M3 regression.
- **Validation:** Co-60 point on skin **39.75 vs VARSKIN 34.5 mGy/µCi/h (+15 %)**;
  distributed disk C-14/Sr-90/P-32/Y-90 land at the **median** of the ~50 %-wide
  published spread; Table 4-2 distance+cover within **~factor-2**; energy conservation
  exact; monotonic in distance; H-3 → 0 (range below basal layer); brems lead ≫ acrylic.

### Decisions resolved here

- **§6.2 Loevinger vs Cross-Berger → Loevinger** (user choice; the monoenergetic kernel
  wasn't citably sourceable). Endpoint-based, IC/Auger excluded — see §11.
- **Air gap is exact geometry, not the kernel.** Loevinger (infinite-medium) cannot model
  a source-in-air half-space; `dose(d) = contact_dose(absorber=ρ_air·d+shield) ×
  f_geom(d)`, `f_geom = 1 − d/√(d²+a²)` (scoring-disk solid angle). Validated ~factor-2 vs
  VARSKIN Table 4-2; monotonic. Original Loevinger (factor `(2−Ē/Ē*)`=1) kept — it lands at
  the published median, so Cross's revised params weren't needed.

## Decision: Loevinger analytic kernel (option A) — sourced, not from memory

The §6.2 fork (Loevinger **vs** Cross-Berger) was decided by **sourcing**, per the
advisor's rule: prefer the monoenergetic Cross-Berger kernel folded over the
spectra *if* the kernel table is cleanly obtainable; else Loevinger-with-revised-
params is a legitimate ±20–30 % fallback. **User chose Loevinger (A).**

A clean, citable, transcribable monoenergetic 2-D electron dose-point-kernel is
**not obtainable** in this environment (Cross 1992 / Berger MIRD-7 paywalled;
VARSKIN's kernels are embedded Monte-Carlo tables; modern work is MC/ML). So we do
**not** fold a monoenergetic kernel; we apply Loevinger's empirical beta point-
source function **once per beta branch**, using the branch mean energy + endpoint.
Honesty consequences (→ §11): **endpoint-based, not a spectrum fold**, and
**discrete IC/Auger electrons are excluded** (Loevinger's domain — Kocher p.7).

### What was sourced cleanly (free, authoritative, vision/text-readable)

- **Loevinger formula + parameters** — Fernández et al., *Dosimetry for radiocolloid
  therapy of cystic craniopharyngiomas*, **arXiv physics/0310150** (open access),
  which reproduces the original Loevinger (1956) point-source function verbatim.
- **Point-kernel framework + energy-conservation normalization** — D. C. Kocher,
  *Calculation of External Dose from Distributed Sources*, ORNL / CONF-8606139-2
  (1986), OSTI 5409085 (free). K(r)=k·Φ(r,E), k=1.6e-13 kg·Gy/MeV;
  4π∫Φr²dr = 1/ρ (energy conservation).
- **Geometry + validation benchmarks** — **VARSKIN 5**, NUREG/CR-6918 Rev. 2
  (Hamby et al., 2014), govinfo GOVPUB-Y3_N88-PURL-gpo51651 (free). Point source,
  7 mg/cm² scoring over 1 cm², air gap (≤5 cm), cover materials; CSDA ranges from
  NIST ESTAR; MC-validated (EGSnrc/MCNP5) skin-dose tables (4-1..4-5).
- **Bremsstrahlung yield** f = 3.5e-4·Z·E (Cember, HP handbook rule).

## The Loevinger kernel (arXiv physics/0310150, Eqs. 2–4)

Dose **per decay** J_β(x) at distance x (cm) in an infinite homogeneous medium:

```
J_β(x) = T1(x) + T2(x)
T1(x)  = [ B·t / x²  −  (B/x)·exp(1 − x/t) ] · Θ(t − x)
T2(x)  =   (B/x)·exp(1 − x/z)
z = (ρ·ν)⁻¹ ,  t = c·z                         # characteristic distances (cm)
B = (1/4π)·ρ·ν²·α·Ē_β ,  α = [3c² − (c²−1)·e]⁻¹  # B fixed by energy conservation
ν = 18.6 / (E_max − 0.036)^1.37   cm²/g          # apparent absorption coefficient
c = 2.0 (E_max<0.5) | 1.5 (0.5–1.5) | 1.0 (1.5–3.0)   dimensionless
```

ρ = medium density (g/cm³), Ē_β = mean β energy/decay (MeV), E_max = endpoint (MeV).
J in MeV/g per decay → **Gy/decay** ×1.602176634e-10. The `(2 − Ē/Ē*)` spectrum-
shape factor in the source is **set to 1** (allowed-spectrum approximation); see
validation — it is not needed within budget.

**Normalization is self-checking:** ∫ J·ρ·4πx² dx = Ē_β exactly (verified to
ratio 1.0000 for Y-90/Sr-90/P-32/Cs-137). NB this checks B/α/structure, **not** ν
(the shape) — that needs the external benchmarks below.

### Per-branch application (the multi-branch trap)

ICRP-107 gives per-branch **mean** energies only (no per-branch endpoints) and a
beta_spectra summed over branches (see `docs/plans/M2-emissions.md`). Loevinger
needs (E_max, Ē) per branch. So:
- **Single/dominant branch → true spectrum endpoint** (it *is* data; e.g. Sr-90,
  Y-90, P-32, C-14). Assign the spectrum endpoint to the highest-mean branch.
- **Minor branches → estimate** E_max,i = Ē_i / R, R ≈ 0.40 (the measured Ē/E_max
  of allowed beta spectra: C-14 0.31, Sr-90 0.36, Y-90 0.41, P-32 0.41), clipped
  to the spectrum endpoint. This is a *documented* approximation confined to minor
  branches; it is **not** tuned to dose (would be circular).
- Sum branches weighted by yield.

Co-60's spectrum endpoint (1.49 MeV) belongs to a **0.12 %** branch; its dominant
99.88 % branch ends at 0.318 MeV. Using the spectrum max for the whole nuclide
would massively over-penetrate — hence per-branch, not single-effective.

### Geometry — contact dosimetry × exact geometry × air transmission

Point source, dose to the **7 mg/cm² basal layer** (0.007 g/cm² → 0.0066 cm in
ρ=1.06 tissue), **averaged over a 1 cm² disk** (10 CFR 20.1201(c); what VARSKIN
reports). **Loevinger is an infinite-medium kernel and cannot model a source-in-air
half-space** — a naive multi-media application made a 0.2 cm air gap *increase* dose
6× (the 1/x far-field falls too slowly; ρ_tissue-gated near-zone). So distance is
**decomposed** (the principled split, advisor):

```
dose(d) = contact_dose(absorber_mass = ρ_air·d + shield_mass) × f_geom(d)
f_geom(d) = 1 − d/√(d² + a²)        # EXACT scoring-disk solid angle, a = √(A/π)
```

- `contact_dose` = disk-averaged homogeneous Loevinger with the absorber added as an
  equivalent tissue depth (validated: Co-60 +15 %; cover-mass attenuation sensible).
- `f_geom` is exact point-source geometry (→1 at contact, →a²/2d² far) — *not* a fudge.
- Absorber mass = air column (ρ_air·d) + shield → range-out transmission.

E_max ≤ 0.036 MeV (ν undefined / range below the basal layer) ⇒ **zero skin dose**
(the correct H-3 / tritium result — no external skin hazard). Monotonic in distance.

### Solve-once / evaluate-many (§3)

Beta C_n is **distance-dependent** (ranging + geometry not separable from 1/d² as
they are for γ). So: precompute per-nuclide branch kernels once; for a fixed distance
compute `C_n^β(d)`, then the time series is one matvec `rate(t) = Σ C_n^β(d)·A_n(t)`.
Distance change re-folds `C_n^β`; time scrub does not.

### Solve-once / evaluate-many (§3)

Beta C_n is **distance-dependent** (ranging is not separable from 1/d² as it is for
γ). So: precompute per-nuclide branch kernels once; for a fixed distance compute
`C_n^β(d)` (the disk-averaged Gy/decay), then the time series is one matvec
`rate(t) = Σ C_n^β(d)·A_n(t)`. Distance change re-folds `C_n^β`; time scrub does not.

## Validation (prototype results — to become `tests/test_dose_beta.py`)

| Nuclide | E_max | model | VARSKIN5 | Kocher-Eck. | Delacroix | Piechowski |
|---|---|---|---|---|---|---|
| C-14  | 0.156 | 11.8 | 11.1 | 12.2 | 10.7 | 12 |
| Sr-90 | 0.546 | 71.8 | 49.7 | 67.6 | 69.9 | 59 |
| P-32  | 1.711 | 84.9 | 58.6 | 88.7 | 91.5 | 70 |
| Y-90  | 2.280 | 84.5 | 59.4 | 88.7 | 91.8 | 75 |

(2-cm distributed disk, 1 µCi/cm², 7 mg/cm², 1 cm², 1 h, mGy.) **Published values
span ~50 %; the model sits at the median**, ±5 % of Kocher-Eckerman/Delacroix
(independent Berger MC kernels). **Co-60 point on skin: model 39.75 vs VARSKIN
34.5 mGy/µCi/h (+15 %)** (Table 4-1), converged under a near-axis-refined radial
grid. → Lock factor=1; the ~50 % inter-code spread **is** the ±20–30 % register.

Pillars: (1) energy-conservation normalization (exact); (2) Co-60 point
(low-E, MC); (3) distributed-disk across 0.16–2.28 MeV (high-E, multi-reference
bracket); (4) monotone fall-off + range cutoff (H-3 → 0); (5) Cs-137 stated
**beta-only** (VARSKIN excludes progeny too — apples-to-apples for IC exclusion).

## Bremsstrahlung-in-shield (done)

f = 3.5e-4·Z·E_max radiated fraction (Cember) per branch → **Kramers thick-target**
spectrum I(k)∝(E_max−k) discretized to synthetic photon lines (`bremsstrahlung_lines`)
→ scored through the **existing γ machinery** via `GammaDoseModel(photon_override=…,
shield=None)` (the beta-stopping shield is **photon-thin** — documented). Compound
shields use an effective Z table. Deliverable met: **lead brems ≫ acrylic** (Z 82 vs
6.6 ⇒ ~12× radiated energy) — the "more lead can increase dose" crossover; order-of-
magnitude. The bridge `beta_dose` returns the brems γ-dose series alongside skin dose.

## Key files

- `engine/beta_dose.py` — Loevinger kernel, `BetaSkinDoseModel`, bremsstrahlung,
  `BetaDoseError`.
- `engine/dose.py` — `GammaDoseModel.photon_override` (brems coupling).
- `engine/emissions.py` — `beta_spectra` / `beta_endpoint_MeV`.
- `engine/bridge.py` — `beta_dose` entry point.
- `tests/test_dose_beta.py` (19) + 2 bridge beta tests (TDD).

## Open questions / risks

- **Air-gap precision:** the geometry×contact decomposition is ~factor-2 vs VARSKIN
  Table 4-2 and monotonic; large air gaps are Monte-Carlo territory (VARSKIN caps at
  5 cm). Adequate for the contact/skin-contamination use case; not a precise
  beta-at-distance code.
- **Original vs Cross-revised params:** original Loevinger (factor `(2−Ē/Ē*)`=1)
  validated at the median; Cross's revised set wasn't sourceable. The factor is in the
  formula if high-E ever needs it.
- **IC/Auger electrons excluded** (Loevinger domain) — a real limitation for e.g.
  Cs-137→Ba-137m's 624 keV K-IC electron. Adding them needs a monoenergetic kernel.
- **β skin dose (Hp(0.07), Gy; w_R=1) ≠ γ H*(10)/effective** — different quantities;
  the §9 γ/β breakdown (M6) must label this, not sum blindly (§12). Brems photons *do*
  join the γ channel.
- **Distributed/surface-contamination sources** (the validation used them via a test
  helper) aren't a first-class engine geometry yet — v1 ships the point source (§9).
- IC/Auger electrons excluded (Loevinger domain) — a real limitation for e.g.
  Cs-137→Ba-137m's ~624 keV K-IC electron; → honesty register.
