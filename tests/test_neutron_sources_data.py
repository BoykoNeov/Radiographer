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

SHIPPED = {"Cf-252"}            # M5 source set (AmBe added when its ISO-8529 spectrum is sourced)
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
