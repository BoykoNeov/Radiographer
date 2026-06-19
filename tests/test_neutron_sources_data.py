"""Regression suite for the bundled neutron source terms (§6.3, §7, §8; M5).

The datasets are the project (CLAUDE.md), so each lands with its checks. Pillars mirror the
conversion suite, adapted for an *analytically reconstructed* spectrum:

1. **Structural** — schema/source/parent/units invariants, spectrum alignment, Σ frac = 1,
   positive n/decay, valid source-γ lines.
2. **Reconstruction integrity** — re-derive the Cf-252 Maxwellian fractions by an INDEPENDENT
   method (numpy trapezoid, not the build's pure-Python fsum loop) and confirm they match the
   stored fractions. Catches a coding/transcription error in the build.
3. **Physics goldens (cited, NOT from memory)** — Cf-252 n/decay = SF branch × ν̄ ≈ 0.1165,
   which reproduces the canonical 2.30×10¹² n/s/g specific yield; mean energy ≈ 2.13 MeV
   (lit 2.1–2.3); the lethargy spectrum peaks near 1–2 MeV.
4. **Loader behavior** — unknown source raises; ``available()`` lists the shipped sources.

The full spectrum-averaged fluence-to-dose *triangle* (fold × vendored ICRP-74 table →
published h*(10)) lives in tests/test_dose_neutron.py, where the dose engine exists.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from engine import neutron_source as ns

SHIPPED = {"Cf-252", "AmBe"}    # M5 Cf-252 + M7d AmBe (ISO-8529 spectrum sourced from TRS-403)

# AmBe ISO 8529 reference spectrum, transcribed INDEPENDENTLY from IAEA TRS-403 Table 4.V
# (column Am–Be) — a second copy so a build-side transcription error is caught here (§7).
_AMBE_TRS403_EV_VALUE = [
    (1.00e5, 1.66e-2), (1.25e5, 2.21e-2), (1.58e5, 2.87e-2), (1.99e5, 3.67e-2),
    (2.51e5, 4.65e-2), (3.16e5, 5.77e-2), (3.98e5, 7.06e-2), (5.01e5, 8.48e-2),
    (6.30e5, 9.61e-2), (7.94e5, 1.06e-1), (1.00e6, 1.18e-1), (1.25e6, 1.27e-1),
    (1.58e6, 1.81e-1), (1.99e6, 2.43e-1), (2.51e6, 4.21e-1), (3.16e6, 5.71e-1),
    (3.98e6, 6.86e-1), (5.01e6, 6.50e-1), (6.30e6, 5.78e-1), (7.94e6, 1.66e-1),
    (1.00e7, 1.72e-2),
]
N_AVOGADRO = 6.02214076e23
SECONDS_PER_YEAR = 365.25 * 24 * 3600


# --------------------------------------------------------------------------- #
# 0. Presence.
# --------------------------------------------------------------------------- #

def test_shipped_sources_present():
    have = ns.available()
    missing = SHIPPED - have
    assert not missing, f"missing neutron sources {sorted(missing)}; run the build"


# --------------------------------------------------------------------------- #
# 1. Structural / schema.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", sorted(SHIPPED))
def test_structural(key):
    d = ns.load(key)                                  # validates the invariants in-loader
    assert d["parent_nuclide"]
    assert ns.neutrons_per_decay(key) > 0
    lo, hi, frac = ns.spectrum(key)
    assert len(lo) == len(hi) == len(frac) > 0
    assert all(b > a > 0 for a, b in zip(lo, hi)), "bin edges ascending & positive"
    assert math.isclose(math.fsum(frac), 1.0, rel_tol=1e-9, abs_tol=1e-9), "Σ fluence_frac == 1"
    assert hi[-1] <= 20.0 + 1e-9, "spectrum within the 20 MeV neutron H*(10) grid"
    reps = ns.representative_energies(key)
    assert all(a <= r <= b for a, r, b in zip(lo, reps, hi)), "rep energy inside its bin"
    # Bins must NOT overlap (the geometric-midpoint-edge trap: a naïve E_i·r^±½ build can store
    # overlapping bins that still sum to 1 and still fold correctly — a silent data bug, §11).
    assert all(hi[i] <= lo[i + 1] + 1e-12 for i in range(len(lo) - 1)), "bins must not overlap"


def test_loader_rejects_unknown_source():
    with pytest.raises(ns.NeutronSourceError):
        ns.load("NoSuchSource-999")


# --------------------------------------------------------------------------- #
# 2. Reconstruction integrity — independent re-derivation of the Cf-252 Maxwellian.
# --------------------------------------------------------------------------- #

def test_cf252_spectrum_matches_independent_maxwellian():
    """Re-integrate χ(E)=√E·exp(−E/T), T=1.42 MeV, per bin via numpy trapezoid (a DIFFERENT
    implementation than the build's pure-Python loop) and confirm the stored fractions match.
    """
    lo, hi, frac = ns.spectrum("Cf-252")
    T = 1.42
    indep = []
    for a, b in zip(lo, hi):
        e = np.linspace(a, b, 128)
        indep.append(np.trapezoid(np.sqrt(e) * np.exp(-e / T), e))
    indep = np.array(indep)
    indep = indep / indep.sum()
    assert np.allclose(frac, indep, rtol=1e-4, atol=1e-12), "stored Cf-252 fractions drifted from Maxwellian"


# --------------------------------------------------------------------------- #
# 3. Physics goldens — cited constants, NOT from memory.
# --------------------------------------------------------------------------- #

def test_cf252_neutrons_per_decay_and_specific_yield():
    """n/decay = SF branch (3.092%) × ν̄ (3.768) ≈ 0.1165, and this reproduces the canonical
    Cf-252 specific yield 2.30×10¹² n/(s·g) (independent of the build's own self-check).
    """
    npd = ns.neutrons_per_decay("Cf-252")
    assert npd == pytest.approx(0.03092 * 3.7676, rel=1e-3), f"n/decay {npd}"

    half_life_y, atomic_mass = 2.645, 252.0816
    lam = math.log(2.0) / (half_life_y * SECONDS_PER_YEAR)
    specific_yield = lam * N_AVOGADRO / atomic_mass * npd            # n/(s·g)
    assert specific_yield == pytest.approx(2.30e12, rel=0.03), (
        f"Cf-252 specific yield {specific_yield:.3e} n/s/g vs canonical 2.30e12"
    )


def test_cf252_mean_energy_and_lethargy_peak():
    d = ns.load("Cf-252")
    assert d["mean_energy_MeV"] == pytest.approx(2.13, abs=0.1), "Cf-252 mean E ~2.13 MeV (lit 2.1–2.3)"
    lo, hi, frac = ns.spectrum("Cf-252")
    reps = ns.representative_energies("Cf-252")
    e_peak = reps[max(range(len(frac)), key=lambda i: frac[i])]
    assert 1.0 <= e_peak <= 3.0, f"Cf-252 lethargy spectrum peaks at {e_peak:.2f} MeV (expected ~1–2)"


def test_cf252_source_gammas_documented_empty():
    # Prompt-fission γ (continuum) is intentionally not modeled in M5 (honesty register);
    # the field exists and is an empty list, not missing.
    assert ns.source_gammas("Cf-252") == []


# --------------------------------------------------------------------------- #
# 5. AmBe (M7d) — ISO 8529 spectrum (TRS-403), transcription + physics goldens.
# --------------------------------------------------------------------------- #

def test_ambe_spectrum_matches_independent_transcription():
    """Normalize the INDEPENDENTLY transcribed TRS-403 Am–Be per-lethargy values (constant Δu
    on the 10/decade grid ⇒ direct normalization → per-bin fractions) and confirm they match
    the stored fractions. Catches a transcription/normalization error in the build."""
    _, _, frac = ns.spectrum("AmBe")
    raw = np.array([v for _, v in _AMBE_TRS403_EV_VALUE])
    indep = raw / raw.sum()
    assert len(frac) == len(indep), "AmBe bin count drifted from the TRS-403 table"
    assert np.allclose(frac, indep, rtol=1e-9, atol=1e-12), "stored AmBe fractions drifted from TRS-403"


def test_ambe_neutrons_per_decay_canonical_yield():
    """n/decay = canonical AmBe specific emission 2.2×10⁶ n/s per Ci of Am-241 ÷ 3.7×10¹⁰ Bq/Ci.
    Construction-dependent (≈±15%) — a representative value, not an intrinsic constant."""
    npd = ns.neutrons_per_decay("AmBe")
    assert npd == pytest.approx(2.2e6 / 3.7e10, rel=1e-3), f"AmBe n/decay {npd}"


def test_ambe_mean_energy_and_lethargy_peak():
    d = ns.load("AmBe")
    # Fluence-weighted mean over the ISO 0.1–10 MeV bins ≈ 3.5 MeV (internal regression). NB the
    # often-quoted ~4.2 MeV (Kluge–Weise) is the un-truncated mean incl. the >10 MeV tail —
    # documented difference, not an error.
    assert d["mean_energy_MeV"] == pytest.approx(3.5, abs=0.2), "AmBe mean E ~3.5 MeV (ISO, truncated)"
    lo, hi, frac = ns.spectrum("AmBe")
    reps = ns.representative_energies("AmBe")
    e_peak = reps[max(range(len(frac)), key=lambda i: frac[i])]
    assert 3.0 <= e_peak <= 5.0, f"AmBe spectrum peaks at {e_peak:.2f} MeV (expected ~4)"


def test_ambe_source_gamma_4438_line():
    """The clean discrete 4.438 MeV reaction γ at the recommended γ/n ratio R=0.575
    (Liu et al.) — contrast Cf-252's unmodeled prompt-fission continuum."""
    gammas = ns.source_gammas("AmBe")
    assert len(gammas) == 1
    g = gammas[0]
    assert g["E_MeV"] == pytest.approx(4.438)
    npd = ns.neutrons_per_decay("AmBe")
    assert g["yield_per_decay"] == pytest.approx(npd * 0.575, rel=1e-6)
