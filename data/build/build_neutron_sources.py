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
DATA_DIR = Path(__file__).resolve().parents[1]              # .../data
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
    sf_branch = 0.03092          # ²⁵²Cf spontaneous-fission branching fraction (NNDC: SF 3.092%)
    nubar = 3.7676               # mean prompt neutrons per ²⁵²Cf SF (evaluated standard, Holden)
    n_per_decay = sf_branch * nubar

    # Self-check: reproduce the canonical specific yield 2.30×10¹² n/(s·g).
    half_life_y = 2.645          # ²⁵²Cf half-life (NNDC)
    atomic_mass = 252.0816       # g/mol
    lam = math.log(2.0) / (half_life_y * SECONDS_PER_YEAR)         # s⁻¹
    activity_per_g = lam * N_AVOGADRO / atomic_mass               # Bq/g
    specific_yield = activity_per_g * n_per_decay                  # n/(s·g)
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


def build() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for record in (build_cf252(),):
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
