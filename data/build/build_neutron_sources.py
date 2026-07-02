"""Build canonical neutron source-term files for the prebuilt neutron sources (M5, §6.3/§8).

Output : data/neutron_sources/<source>.json  (Cf-252; AmBe lands when its ISO-8529 spectrum
         is sourced — see docs/plans/M5-neutron.md, the user-chosen fallback is Cf-252-only).

Each record carries (HANDOFF_PLAN §6.3 — tabulated terms, NOT derived from the inventory):

- ``neutrons_per_decay`` — neutrons emitted per decay of ``parent_nuclide`` (time-invariant).
  The neutron strength is then ``S(t) = neutrons_per_decay · A_parent(t)`` (neutrons/s), so
  the neutron view scales with the *same* solved inventory that drives the gamma view (§3
  solve-once / evaluate-many; the parent's decay handles time evolution for free).
- ``spectrum`` — the normalized energy distribution as **per-bin fluence fractions** that
  **sum to 1** (NOT per-lethargy — the lethargy/per-energy ambiguity is resolved here, once,
  at the one place it is checkable; §12). The dose engine folds these against the neutron
  fluence-to-dose coefficients (engine/neutron_dose.py).
- ``source_gammas`` — source-CORRELATED photon lines (reaction γ, not decay γ — they are NOT
  in the ICRP-107 inventory data), scored through the M3 gamma engine via ``photon_override``.

Provenance / honesty (→ HANDOFF_PLAN §11):
- **Cf-252**: spectrum = ISO 8529-1:2001 reference, a Maxwellian χ(E) ∝ √E·exp(−E/T),
  T = 1.42 MeV (the standard's nominal form; ISO actually tabulates a near-Maxwellian
  spectrum — the analytic form is a documented approximation, but H*(10) is nearly flat
  (~400 pSv·cm²) across 0.5–6 MeV so the spectrum-averaged value is insensitive to the
  shape detail). ``neutrons_per_decay`` is DERIVED from the SF branch × ν̄ and validated to
  reproduce the canonical 2.30×10¹² n/s/g specific yield. Prompt-fission γ is a continuum
  (Verbinski) **not modeled** in M5 (honesty register) — only AmBe's clean discrete line is.

Dev-time step only; the browser/Pyodide runtime reads the generated canonical files.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

SCHEMA_VERSION = 1
DATA_DIR = Path(__file__).resolve().parents[1]  # .../data
OUT_DIR = DATA_DIR / "neutron_sources"

#: Stored spectrum binning: log-spaced edges over the neutron H*(10) grid (1 keV–20 MeV).
#: Capping at 20 MeV keeps every bin on-grid for BOTH dose quantities (H*(10) ends at 20 MeV,
#: effective at 10 GeV); the dropped Maxwellian tail above 20 MeV is ~1e-6 (negligible). 100
#: log bins reproduce the trapezoidal spectrum-averaged h*(10) to <0.1%.
SPECTRUM_E_LO_MEV = 1.0e-3
SPECTRUM_E_HI_MEV = 20.0
N_BINS = 100

# Avogadro / seconds-per-year for the Cf-252 specific-yield self-check.
N_AVOGADRO = 6.02214076e23
SECONDS_PER_YEAR = 365.25 * 24 * 3600


class BuildError(Exception):
    """A structural / integrity failure in the neutron-source build. Never swallowed."""


def _log_bins(e_lo: float, e_hi: float, n: int) -> tuple[list[float], list[float]]:
    """``n`` log-spaced bins; returns (lower_edges, upper_edges)."""
    edges = [e_lo * (e_hi / e_lo) ** (i / n) for i in range(n + 1)]
    return edges[:-1], edges[1:]


def _centered_log_edges(energies_MeV: list[float]) -> tuple[list[float], list[float]]:
    """Bin edges for a tabulated spectrum whose values sit at log-grid *points* E_i.

    Each value is the per-lethargy spectrum at E_i (the lethargy-centre of its bin), so the
    bin edges are the geometric midpoints between adjacent points; the ends get a half-step
    using the (asserted constant) grid ratio r. This makes ``geomean(E_lo_i, E_hi_i) == E_i``
    for every bin — the fold point the dose engine uses — with NON-overlapping edges (a
    naïve E_i·r^±½ would overlap when the grid is finer than the half-step, a silent
    data-integrity trap; §11 / "the datasets are the project").

    The constant-ratio assert is load-bearing: direct normalization of per-lethargy values to
    per-bin fluence fractions is only valid because the lethargy width Δu = ln(r) is constant.
    """
    n = len(energies_MeV)
    if n < 2:
        raise BuildError("tabulated spectrum needs ≥2 points")
    # Geometric-mean ratio (robust to the published table rounding its grid points to 3 sig
    # figs). The per-step ratio may wobble ~1% around this from rounding; the 5% tolerance
    # tolerates that while still catching a real grid-density change (3/decade ⇒ r≈2.15 vs
    # 10/decade ⇒ r≈1.26 is a ~70% jump) that would break the constant-Δu normalization.
    r = (energies_MeV[-1] / energies_MeV[0]) ** (1.0 / (n - 1))
    for k in range(n - 1):
        rr = energies_MeV[k + 1] / energies_MeV[k]
        if not math.isclose(rr, r, rel_tol=5e-2):
            raise BuildError(
                f"tabulated spectrum grid is not constant-ratio at index {k}: "
                f"{rr:.5f} != {r:.5f} (direct per-lethargy normalization assumes constant Δu)"
            )
    lo = [energies_MeV[0] / math.sqrt(r)] + [
        math.sqrt(energies_MeV[i - 1] * energies_MeV[i]) for i in range(1, n)
    ]
    hi = [math.sqrt(energies_MeV[i] * energies_MeV[i + 1]) for i in range(n - 1)] + [
        energies_MeV[-1] * math.sqrt(r)
    ]
    return lo, hi


def _maxwellian_bin_fractions(
    lo: list[float], hi: list[float], temperature_MeV: float, subdiv: int = 64
) -> list[float]:
    """Per-bin integral of χ(E) ∝ √E·exp(−E/T), normalized to sum 1.

    Each bin is sub-integrated (trapezoid, ``subdiv`` points) so the fraction is the true
    integral over the bin, not a midpoint sample — this is what makes the stored fractions
    independent of the bin count.
    """

    def chi(e: float) -> float:
        return math.sqrt(e) * math.exp(-e / temperature_MeV)

    fracs: list[float] = []
    for a, b in zip(lo, hi):
        step = (b - a) / subdiv
        acc = 0.0
        prev = chi(a)
        for k in range(1, subdiv + 1):
            cur = chi(a + k * step)
            acc += 0.5 * (prev + cur) * step
            prev = cur
        fracs.append(acc)
    total = math.fsum(fracs)
    return [f / total for f in fracs]


def _mean_energy_MeV(lo: list[float], hi: list[float], frac: list[float]) -> float:
    """Fluence-weighted mean energy using each bin's geometric-mean representative energy."""
    return math.fsum(f * math.sqrt(a * b) for a, b, f in zip(lo, hi, frac))


def _validate_spectrum(tag: str, lo: list[float], hi: list[float], frac: list[float]) -> None:
    if not (len(lo) == len(hi) == len(frac)) or not lo:
        raise BuildError(f"{tag}: ragged/empty spectrum arrays")
    for a, b, f in zip(lo, hi, frac):
        if not (math.isfinite(a) and math.isfinite(b) and a > 0 and b > a):
            raise BuildError(f"{tag}: bad bin edges ({a}, {b})")
        if not (math.isfinite(f) and f >= 0):
            raise BuildError(f"{tag}: bad fluence fraction {f}")
    s = math.fsum(frac)
    if not math.isclose(s, 1.0, rel_tol=1e-9, abs_tol=1e-12):
        raise BuildError(f"{tag}: fluence fractions sum to {s!r}, not 1 (normalization trap)")
    if hi[-1] > 20.0 + 1e-9:
        raise BuildError(f"{tag}: spectrum extends above the 20 MeV neutron H*(10) grid end")


def _write(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_cf252() -> dict:
    """Cf-252 spontaneous-fission source: ISO-8529 Maxwellian spectrum + derived n/decay."""
    # --- neutrons per decay: SF branch × prompt-fission ν̄ (cited constants) ---------------
    sf_branch = 0.03092  # ²⁵²Cf spontaneous-fission branching fraction (NNDC: SF 3.092%)
    nubar = 3.7676  # mean prompt neutrons per ²⁵²Cf SF (evaluated standard, Holden)
    n_per_decay = sf_branch * nubar

    # Self-check: reproduce the canonical specific yield 2.30×10¹² n/(s·g).
    half_life_y = 2.645  # ²⁵²Cf half-life (NNDC)
    atomic_mass = 252.0816  # g/mol
    lam = math.log(2.0) / (half_life_y * SECONDS_PER_YEAR)  # s⁻¹
    activity_per_g = lam * N_AVOGADRO / atomic_mass  # Bq/g
    specific_yield = activity_per_g * n_per_decay  # n/(s·g)
    if not math.isclose(specific_yield, 2.30e12, rel_tol=0.03):
        raise BuildError(
            f"Cf-252 specific yield {specific_yield:.3e} n/s/g disagrees with the canonical "
            f"2.30e12 by >3% — re-check SF branch / ν̄ / half-life"
        )

    lo, hi = _log_bins(SPECTRUM_E_LO_MEV, SPECTRUM_E_HI_MEV, N_BINS)
    frac = _maxwellian_bin_fractions(lo, hi, temperature_MeV=1.42)
    _validate_spectrum("Cf-252", lo, hi, frac)
    e_mean = _mean_energy_MeV(lo, hi, frac)

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Cf-252",
        "parent_nuclide": "Cf-252",
        "neutrons_per_decay": n_per_decay,
        "neutrons_per_decay_note": (
            f"SF branch {sf_branch} × ν̄ {nubar} = {n_per_decay:.5f}; reproduces specific yield "
            f"{specific_yield:.3e} n/s/g (canonical 2.30e12)"
        ),
        "spectrum_model": "ISO 8529-1:2001 reference: Maxwellian χ(E) ∝ √E·exp(−E/T), T = 1.42 MeV",
        "mean_energy_MeV": e_mean,
        "spectrum": {"E_lo_MeV": lo, "E_hi_MeV": hi, "fluence_frac": frac},
        "source_gammas": [],
        "source_gammas_note": (
            "Cf-252 prompt-fission γ (~8 γ/fission, continuum, Verbinski) is NOT modeled in M5 "
            "(would need a citable continuum spectrum); see HANDOFF_PLAN §11."
        ),
        "source_ref": (
            "ISO 8529-1:2001 (Cf-252 reference spectrum, Maxwellian T=1.42 MeV); SF branch/ν̄ "
            "NNDC/Holden; specific yield cross-check 2.30e12 n/s/g (NIST/IAEA)."
        ),
    }


# --- AmBe (²⁴¹Am–⁹Be) ISO 8529 reference source -------------------------------------------
# Spectrum: IAEA Technical Reports Series No. 403, "Compendium of Neutron Spectra and Detector
# Responses for Radiation Protection Purposes" (2001), Table 4.V "ISO Reference Spectra",
# column "Am–Be" — the ISO 8529-2 reference (α,n) spectrum. OPEN ACCESS:
# www-pub.iaea.org/MTCD/publications/PDF/TRS403_scr.pdf. This is a CITED table, NOT a
# reconstruction/figure-digitization (the §11 no-fabrication discipline — earlier sessions
# deferred AmBe because only paywalled/figure sources were found; TRS-403 resolves that).
#
# The 21 nonzero bins (0.1–10 MeV) on a 10/decade log grid; values are the compendium's
# per-lethargy fluence (arbitrary norm). Lethargy width Δu = ln(r) is constant across these
# bins, so direct normalization → per-bin fluence fractions (asserted in _centered_log_edges).
# (E_eV, per-lethargy spectral value)
ISO_AMBE_SPECTRUM_TRS403: list[tuple[float, float]] = [
    (1.00e5, 1.66e-2),
    (1.25e5, 2.21e-2),
    (1.58e5, 2.87e-2),
    (1.99e5, 3.67e-2),
    (2.51e5, 4.65e-2),
    (3.16e5, 5.77e-2),
    (3.98e5, 7.06e-2),
    (5.01e5, 8.48e-2),
    (6.30e5, 9.61e-2),
    (7.94e5, 1.06e-1),
    (1.00e6, 1.18e-1),
    (1.25e6, 1.27e-1),
    (1.58e6, 1.81e-1),
    (1.99e6, 2.43e-1),
    (2.51e6, 4.21e-1),
    (3.16e6, 5.71e-1),
    (3.98e6, 6.86e-1),
    (5.01e6, 6.50e-1),
    (6.30e6, 5.78e-1),
    (7.94e6, 1.66e-1),
    (1.00e7, 1.72e-2),
]


def build_ambe() -> dict:
    """²⁴¹AmBe (α,n) source: ISO 8529 reference spectrum (TRS-403) + 4.438 MeV reaction γ."""
    parent = "Am-241"

    # neutrons_per_decay — the canonical AmBe specific emission 2.2×10⁶ n/s per Ci of ²⁴¹Am
    # (1 Ci = 3.7×10¹⁰ Bq; Am-241 ≈ 1 α/decay). UNLIKE Cf-252's intrinsic SF×ν̄, the AmBe
    # (α,n) yield is SOURCE-CONSTRUCTION-DEPENDENT (Am:Be ratio, encapsulation, geometry) and
    # varies ≈±15% between sources — a representative value, not a fundamental constant (§11).
    AMBE_N_PER_S_PER_CI = 2.2e6
    BQ_PER_CI = 3.7e10
    n_per_decay = AMBE_N_PER_S_PER_CI / BQ_PER_CI  # ≈ 5.95e-5 n / Am-241 decay

    energies_MeV = [e_eV * 1e-6 for e_eV, _ in ISO_AMBE_SPECTRUM_TRS403]
    raw = [v for _, v in ISO_AMBE_SPECTRUM_TRS403]
    lo, hi = _centered_log_edges(energies_MeV)
    total = math.fsum(raw)
    frac = [v / total for v in raw]  # constant Δu ⇒ per-lethargy values ∝ per-bin fluence
    _validate_spectrum("AmBe", lo, hi, frac)
    e_mean = _mean_energy_MeV(lo, hi, frac)

    # 4.438 MeV reaction γ from ⁹Be(α,n)¹²C* (¹²C first-excited-state de-excitation). Yield is
    # the recommended γ/n emission ratio R = 0.575 ± 4.8% (Liu et al., synthetic evaluated
    # value; ⁴·⁴³⁸ MeV-γ-to-neutron ratio for ²⁴¹AmBe). Unlike Cf-252's prompt-fission γ
    # continuum (unmodeled, §11), this is a single clean discrete line — scored through the
    # gamma engine via photon_override (engine/neutron_dose.source_gamma_override).
    GAMMA_PER_NEUTRON = 0.575
    gamma_yield_per_decay = n_per_decay * GAMMA_PER_NEUTRON

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "AmBe",
        "parent_nuclide": parent,
        "neutrons_per_decay": n_per_decay,
        "neutrons_per_decay_note": (
            f"{AMBE_N_PER_S_PER_CI:.2g} n/s per Ci of Am-241 ÷ {BQ_PER_CI:.3g} Bq/Ci = "
            f"{n_per_decay:.3e} n/decay. SOURCE-CONSTRUCTION-DEPENDENT (Am:Be ratio, "
            "encapsulation) — representative, varies ≈±15%; the spectrum SHAPE and h̄ are the "
            "construction-independent ISO-standard part."
        ),
        "spectrum_model": (
            "ISO 8529 reference (α,n) spectrum, tabulated — IAEA TRS-403 (2001) Table 4.V, "
            "column Am–Be (21 bins, 0.1–10 MeV)"
        ),
        "mean_energy_MeV": e_mean,
        "spectrum": {"E_lo_MeV": lo, "E_hi_MeV": hi, "fluence_frac": frac},
        "source_gammas": [
            {
                "E_MeV": 4.438,
                "yield_per_decay": gamma_yield_per_decay,
                "origin": "9Be(a,n)12C* de-excitation",
            }
        ],
        "source_gammas_note": (
            f"4.438 MeV line at γ/n ratio R={GAMMA_PER_NEUTRON} (Liu et al., recommended "
            f"evaluated, ±4.8%) × {n_per_decay:.3e} n/decay = {gamma_yield_per_decay:.3e} γ/decay."
        ),
        "source_ref": (
            "Spectrum: IAEA TRS-403 (2001) Table 4.V (ISO 8529 Am–Be reference), open access. "
            "h̄ anchor: TRS-403 Table 4.IV H*(10)=391 pSv·cm² (Table 4.V 'spectrum-weighted "
            "responses' lists 395 — a ~1% conversion-coefficient-set difference). n yield: "
            "2.2e6 n/s/Ci (canonical AmBe). γ/n ratio R=0.575 (Liu et al.)."
        ),
    }


def build() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for record in (build_cf252(), build_ambe()):
        _write(OUT_DIR / f"{record['source']}.json", record)
        count += 1
    return count


if __name__ == "__main__":
    try:
        n = build()
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical neutron-source files into {OUT_DIR}")
