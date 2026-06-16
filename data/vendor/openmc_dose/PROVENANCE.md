# Vendored upstream — fluence-to-dose conversion coefficients (OpenMC dose tables)

Source material for the **conversion** dataset: fluence-to-dose conversion coefficients for
**ambient dose equivalent H\*(10)** (operational, §6.4 default) and **effective dose E** per
irradiation geometry, for both **photons** (M2) and **neutrons** (M5). See
`docs/plans/M2-conversion.md`, `docs/plans/M5-neutron.md`, and `../../README.md`.

> **Two trust levels in one directory.** The effective-dose table is vendored **verbatim**
> from OpenMC mainline (its git-blob-SHA matches OpenMC's tree, so the build can prove
> canonical == upstream by independent re-parse — the NIST/ICRP-107 clean model). The
> H\*(10) table is vendored from an **unmerged pull request** (a transcription); it uses
> the **degraded** model (cf. the ANS-6.4.3 buildup data) — faithfulness is enforced by an
> independent-quantity cross-check, not by re-parse alone. See the trust boundary below.

## Source chain

| File | Upstream quantity | Vendored from | Trust |
|---|---|---|---|
| `icrp116_photons.txt` | **ICRP-116 (2010) Table A.1** — effective dose per fluence (pSv·cm²), monoenergetic photons, geometries AP/PA/LLAT/RLAT/ROT/ISO, **incl. corrigendum** | `openmc-dev/openmc` **develop** commit `53d98ce71acddd028a8361bf966aa8d6be204cfd`, path `openmc/data/dose/icrp116/photons.txt` (git blob `e2591d85fc062c74cad76c888d5e165bdc7a10e8`) | **CLEAN** (verbatim; blob-SHA == OpenMC tree) |
| `icrp116_neutrons.txt` | **ICRP-116 (2010) Table A.5** — effective dose per fluence (pSv·cm²), monoenergetic **neutrons**, geometries AP/PA/LLAT/RLAT/ROT/ISO, 1e-9 MeV–10 GeV | same develop commit `53d98ce…`, path `openmc/data/dose/icrp116/neutrons.txt` (git blob `724180ec82adf17c8497a20c3900ba134a8ecf15`) | **CLEAN** (verbatim; blob-SHA == OpenMC tree — confirmed via the contents API at this ref) |
| `icrp74_photons_H10.txt` | **ICRP-74 (1996) / ICRU-57** — ambient dose equivalent H\*(10) per fluence (pSv·cm²), monoenergetic photons | OpenMC **PR #3256** (`MatteoZammataro/openmc`) commit `f89d146ad1fe86adfa999c463aedb7128c207b54`, path `openmc/data/effective_dose/icrp74/photons_H10.txt` (git blob `66031b2f0e99033969528ce9c759730bf40602b9`) | **DEGRADED** (transcription in an unmerged PR) |
| `icrp74_neutrons_H10.txt` | **ICRP-74 (1996)** — ambient dose equivalent H\*(10) per fluence (pSv·cm²), monoenergetic **neutrons**, 1e-9 MeV–20 MeV | same OpenMC **PR #3256** fork commit `f89d146…`, path `openmc/data/effective_dose/icrp74/neutrons_H10.txt` (git blob `fe0036cbc9c8c5994f053785a0554cc233806c77`) | **DEGRADED** (transcription in an unmerged PR; cross-checked via the M5 ISO-8529 validation triangle) |
| `LICENSE.OpenMC` | OpenMC MIT license | same develop commit, `LICENSE` | — |

OpenMC issue **#3216** requests H\*(10) factors; PR **#3256** ("Add ambient dose
coefficients (H\*(10)) from ICRP74") supplies them but **was not merged** as of
2026-06-16 (mainline `develop` has no `*_H10.txt` — verified via the GitHub tree API).
If/when it merges, re-vendor `icrp74_photons_H10.txt` from mainline for strictly cleaner
provenance and update the pin below.

## Why OpenMC as the conduit

ICRP-74 and ICRP-116 are **paywalled** publications; the numerical conversion coefficients
themselves are **facts** (not copyrightable). OpenMC is an MIT-licensed Monte-Carlo code
whose `openmc/data/dose/` tables reproduce them machine-readably — the same "vendor a
faithful open reproduction, then re-parse independently" model used for NIST attenuation.

- **ICRP-116** effective dose: OpenMC's `photons.txt` is the report's Table A.1 verbatim
  (incl. corrigendum — see below), 55 energies 0.01 MeV–10 GeV × 6 geometries; `neutrons.txt`
  is the matching neutron table (Table A.5), 1e-9 MeV–10 GeV × 6 geometries.
- **ICRP-74** H\*(10): the PR's `photons_H10.txt` is the ICRU-57/ICRP-74 monoenergetic
  photon H\*(10)/Φ table, 25 energies 0.01–10 MeV (single column — operational, no geometry);
  `neutrons_H10.txt` is the matching neutron table, 1e-9 MeV–20 MeV (single column).

## Corrigendum (do NOT "fix")

OpenMC ships the **ICRP-116 corrigendum** values, not the original report (their own test
asserts `90.4 # updated in corrigendum` at 10 GeV AP). Cross-checks against other
reproductions (PMC piecewise-poly paper; CERN-OPEN-2023-009) may differ slightly at the
corrected energies — that is the corrigendum, **not** a transcription error.

## Drift guard

`MANIFEST.sha256` lists the sha256 of each vendored file. The build
(`../../build/build_conversion.py`) pins all four data tables — `icrp116_photons.txt`,
`icrp116_neutrons.txt`, `icrp74_photons_H10.txt`, `icrp74_neutrons_H10.txt`
(`EXPECTED_SHA256`) — and **refuses to run** unless they match: the committed canonical
files can never be silently rebuilt from a changed input.

## Trust boundary (honesty)

- **Effective (clean):** transform integrity proves *canonical == vendored*; the vendored
  bytes are OpenMC's tree blob. Faithfulness to true ICRP-116 is cross-checked against an
  **independent** piecewise-poly fit of ICRP-116 (Veinot et al., PMC6074822, ≤3 %) — a
  separate group's transcription, which the vendored AP coefficients match to ≤1.2 % across
  0.03–6 MeV; the rest is trusted to OpenMC's verbatim (corrigendum-inclusive) table.
- **H\*(10) (degraded):** the re-parse only proves *canonical == the PR file*. Faithfulness
  to true ICRP-74/ICRU-57 is enforced by an **independent-quantity cross-check**: dividing
  H\*(10)/Φ by OpenMC's *independently sourced* ICRP-74 Table A.1 (Ka/Φ, from
  `generate_photon_effective_dose.py`) on the shared grid reproduces the canonical ICRU-57
  **sphere** response (peak ≈ 1.77 @ 60 keV), matched against the **IAEA** slab Hp(10,0°)/Ka
  table at the energies where sphere == slab (≤ 40 keV and ≥ 1 MeV). The 50–200 keV interior
  and the > 3 MeV tail rest on the transcription. (Decay gammas ≤ ~2.6 MeV, inside the
  three-way-validated range.) See `tests/test_conversion_data.py`.
- **Neutron H\*(10) (degraded):** same model — the re-parse proves *canonical == the PR
  file*; faithfulness to true ICRP-74 is enforced by the **M5 validation triangle** (fold the
  vendored ISO-8529 source spectrum against this table → spectrum-averaged h\*(10), check it
  equals the *published* ISO-8529/PNNL-19273 value for Cf-252 / AmBe — three mutually
  independent things meeting). The neutron *effective* table is **clean** (blob-SHA == tree).
  See `tests/test_dose_neutron.py`.

## License

OpenMC is **MIT-licensed** (`LICENSE.OpenMC`) — no non-commercial restriction. The
coefficients are ICRP/ICRU facts. The repo-license constraint comes solely from the
ICRP-107 emission data, not from this dataset.

## Re-vendoring (only to deliberately bump the source)

```sh
# effective (ICRP-116) photon + neutron, from OpenMC mainline:
curl -sL https://raw.githubusercontent.com/openmc-dev/openmc/<commit>/openmc/data/dose/icrp116/photons.txt \
  -o data/vendor/openmc_dose/icrp116_photons.txt
curl -sL https://raw.githubusercontent.com/openmc-dev/openmc/<commit>/openmc/data/dose/icrp116/neutrons.txt \
  -o data/vendor/openmc_dose/icrp116_neutrons.txt
# ambient H*(10) (ICRP-74) photon + neutron: prefer mainline once PR #3256 merges; else the
# pinned fork commit (.../openmc/data/effective_dose/icrp74/{photons,neutrons}_H10.txt).
# Then regenerate MANIFEST.sha256, update EXPECTED_SHA256 in build_conversion.py, rebuild,
# and re-run tests/test_conversion_data.py + tests/test_dose_neutron.py.
```
