"""Beam-probe regression tests (``engine.beam``) — shield vs external line / X-ray tube.

Validation strategy (deliberate, see ``docs/plans/beam-probe.md``): this module adds **no new
dataset**, so there is no external table to reproduce. Published HVL tables for diagnostic
beams are *not* asserted here — reconstructing one from memory is the fabrication line that
deferred the AmBe spectrum and the Cross-Berger kernel. What is asserted instead is
**internal consistency against the already-validated γ dose path** plus **physical direction**:

* a one-bin tube spectrum reproduces the mono-line transmission **exactly** (the
  non-tautological check on the whole weighting/normalization fold),
* mono-line transmission is identical for all three dose quantities (transmission multiplies
  fluence) — while the *spectrum-averaged* transmission is not,
* broad beam ≥ narrow beam always (B ≥ 1), and narrow beam == ``exp(−Σμx)`` == the ``ln2/μ``
  HVL algebra exactly,
* the scored band follows the layers' buildup floors (lead 30 keV, others 15 keV) and the
  dropped incident fraction is reported, never silent,
* beam hardening: mean energy out > mean energy in; HVL monotone in kVp and in filtration.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from engine import beam
from engine import buildup as bu
from engine.attenuation import density
from engine.dose import SCORING_FLOOR_MEV, stack_transmission
from engine.photon_interp import interp_mu_rho


# --- scored band ---------------------------------------------------------------------


def test_band_follows_buildup_floors():
    """The band's floor is the max of the 10 keV δ and every layer's buildup floor — lead's
    G-P table starts at 30 keV, so a lead layer *raises* the floor."""
    lo_al, hi_al = beam.scored_band([("aluminium", 1.0)])
    lo_pb, hi_pb = beam.scored_band([("lead", 1.0)])
    assert lo_al == pytest.approx(max(SCORING_FLOOR_MEV, bu.energies("aluminium")[0]))
    assert lo_pb == pytest.approx(bu.energies("lead")[0]) and lo_pb > lo_al
    # 15 MeV buildup end binds below the 20 MeV attenuation end for both.
    assert hi_al == pytest.approx(15.0) and hi_pb == pytest.approx(15.0)
    # A mixed stack takes the tightest floor of the two.
    assert beam.scored_band([("aluminium", 1.0), ("lead", 1.0)])[0] == pytest.approx(lo_pb)


def test_band_intersects_the_conversion_grid():
    """H*(10) ends at 10 MeV, so asking for it tightens the high end below the buildup end."""
    assert beam.scored_band([("iron", 1.0)], quantity="ambient_H10")[1] == pytest.approx(10.0)
    assert beam.scored_band([("iron", 1.0)], quantity="air_kerma")[1] == pytest.approx(15.0)


def test_no_buildup_material_raises_not_transparent():
    with pytest.raises(bu.BuildupError):
        beam.scored_band([("polyethylene", 1.0)])


# --- monoenergetic line probe ---------------------------------------------------------


def test_line_probe_matches_the_dose_path_exactly():
    """The probe must return the SAME factor the γ dose engine folds per line — not a
    re-derivation. Exact equality, one shared transmission core."""
    layers = [("lead", 0.5), ("water", 3.0)]
    for e_mev in (0.0595, 0.1405, 0.6617, 1.3325):
        got = beam.line_probe(layers, e_mev)
        assert got["transmission"] == stack_transmission(layers, e_mev)


def test_line_probe_narrow_broad_and_buildup_algebra():
    layers = [("lead", 1.0), ("iron", 2.0)]
    p = beam.line_probe(layers, 0.6617)
    mfp = sum(interp_mu_rho(m, 0.6617) * density(m) * x for m, x in layers)
    assert p["total_mfp"] == pytest.approx(mfp, rel=1e-12)
    assert p["transmission_narrow"] == pytest.approx(math.exp(-mfp), rel=1e-12)
    assert p["transmission"] >= p["transmission_narrow"]  # B >= 1, always
    assert p["buildup"] == pytest.approx(p["transmission"] / p["transmission_narrow"])
    assert p["buildup"] > 1.0
    # per-layer rows sum to the total depth
    assert sum(r["mfp"] for r in p["layers"]) == pytest.approx(mfp, rel=1e-12)


def test_line_probe_hvl_algebra_exact_and_broad_hvl_is_thicker():
    """Narrow-beam HVL is ln2/μ exactly; the broad-beam HVL (buildup lets scattered photons
    through) must be LARGER — more material is needed to halve the dose than to halve the
    primary beam."""
    p = beam.line_probe([("lead", 1.0)], 0.6617)
    mu = interp_mu_rho("lead", 0.6617) * density("lead")
    assert p["hvl_cm"] == pytest.approx(math.log(2.0) / mu, rel=1e-9)
    assert p["tvl_cm"] == pytest.approx(math.log(10.0) / mu, rel=1e-9)
    assert p["hvl_broad_cm"] > p["hvl_cm"]
    # the HVL is the thickness that halves the narrow beam, by construction
    assert beam.line_probe([("lead", p["hvl_cm"])], 0.6617)["transmission_narrow"] == pytest.approx(
        0.5
    )
    assert beam.line_probe([("lead", p["hvl_broad_cm"])], 0.6617)["transmission"] == pytest.approx(
        0.5, rel=1e-6
    )


def test_line_probe_transmission_is_quantity_independent():
    """A fluence factor: the same stack/energy transmits the same fraction whether the caller
    scores air kerma, H*(10), or effective dose. (`line_probe` takes no quantity at all — this
    pins the *reason* it doesn't.)"""
    layers = [("concrete", 10.0)]
    probes = [
        beam.tube_probe(layers, kvp=150.0, filtration_mm_al=2.5, quantity=q, geometry=g, n_bins=1)
        for q, g in (("air_kerma", None), ("ambient_H10", None), ("effective", "AP"))
    ]
    e_bin = probes[0]["spectrum"]["E_MeV"][0]
    mono = beam.line_probe(layers, e_bin)["transmission"]
    for p in probes:
        assert p["transmission"] == pytest.approx(mono, rel=1e-12)


def test_line_probe_off_band_raises_loudly():
    """A 12 keV line through lead is below lead's 30 keV buildup floor: raise, never B=1."""
    with pytest.raises(beam.BeamError, match="scoreable band"):
        beam.line_probe([("lead", 0.1)], 0.012)
    # ...but it IS scoreable through aluminium (15 keV floor) — the band is per-stack.
    with pytest.raises(beam.BeamError, match="scoreable band"):
        beam.line_probe([("aluminium", 0.1)], 0.012)
    assert beam.line_probe([("aluminium", 0.1)], 0.020)["transmission"] > 0.0


def test_empty_stack_is_unity_transmission():
    p = beam.line_probe([], 0.6617)
    assert p["transmission"] == 1.0 and p["transmission_narrow"] == 1.0
    assert p["total_mfp"] == 0.0 and p["detector_material"] is None


def test_transmission_curve_spans_the_band_and_is_monotone_in_thickness():
    c = beam.transmission_curve([("lead", 1.0)], n_points=41)
    lo, hi = c["band_MeV"]
    assert c["E_MeV"][0] == pytest.approx(lo) and c["E_MeV"][-1] == pytest.approx(hi)
    assert all(b >= n for b, n in zip(c["transmission"], c["transmission_narrow"]))
    thick = beam.transmission_curve([("lead", 3.0)], n_points=41)
    assert all(t3 <= t1 for t3, t1 in zip(thick["transmission"], c["transmission"]))


def test_lead_k_edge_shows_up_as_a_transmission_drop():
    """Physical signature the curve exists to teach: just ABOVE lead's 88 keV K-edge the
    photoelectric cross-section jumps, so transmission *drops* as energy *increases*."""
    below = beam.line_probe([("lead", 0.2)], 0.087)["transmission_narrow"]
    above = beam.line_probe([("lead", 0.2)], 0.090)["transmission_narrow"]
    assert above < below


# --- X-ray tube spectrum -------------------------------------------------------------


def test_one_bin_tube_reproduces_the_mono_line_fold():
    """The load-bearing consistency check (advisor): collapse the spectrum to a single bin and
    the whole weighting/normalization machinery must reduce to the mono-line transmission."""
    layers = [("aluminium", 2.0)]
    t = beam.tube_probe(layers, kvp=100.0, filtration_mm_al=2.5, n_bins=1)
    e_bin = t["spectrum"]["E_MeV"][0]
    assert t["transmission"] == pytest.approx(
        beam.line_probe(layers, e_bin)["transmission"], rel=1e-12
    )
    assert t["transmission_narrow"] == pytest.approx(
        beam.line_probe(layers, e_bin)["transmission_narrow"], rel=1e-12
    )


def test_kramers_shape_endpoint_and_normalization():
    e, phi = beam.kramers_spectrum(100.0, n_bins=200)
    assert e[-1] < 0.1 and e[0] == pytest.approx(beam.GENERATION_FLOOR_MEV, abs=5e-4)
    assert np.all(phi >= 0.0)
    # N(E) ∝ (E_max − E)/E · dE: monotone falling on a uniform grid, zero at the endpoint.
    assert np.all(np.diff(phi) < 0.0)
    assert phi[-1] < phi[0] * 1e-2
    # UNFILTERED, the number spectrum's 1/E divergence makes it soft-photon dominated: the
    # fluence-weighted mean sits near the generation floor, not near the endpoint. That is
    # exactly why filtration is not optional — the filtered mean below is the usable beam.
    assert float(np.sum(phi * e) / np.sum(phi)) < 0.05 * 0.1 + 0.01
    filtered = beam.tube_probe([("aluminium", 0.0)], kvp=100.0, filtration_mm_al=2.5)
    assert 0.35 < filtered["mean_E_in_MeV"] / 0.1 < 0.7


def test_kvp_out_of_range_refused():
    for kv in (1.0, 1000.0):
        with pytest.raises(beam.BeamError, match="tube potential"):
            beam.kramers_spectrum(kv)


def test_unsupported_anode_refused():
    with pytest.raises(beam.BeamError, match="anode"):
        beam.tube_probe([("aluminium", 1.0)], kvp=80.0, anode="molybdenum")


def test_tube_beam_hardening():
    """A stack removes soft photons preferentially, so what gets through is HARDER: higher mean
    energy and a larger HVL than the beam that went in."""
    t = beam.tube_probe([("aluminium", 3.0)], kvp=120.0, filtration_mm_al=2.5)
    assert t["mean_E_out_MeV"] > t["mean_E_in_MeV"]
    assert t["hvl_al_out_mm"] > t["hvl_al_in_mm"]
    assert 0.0 < t["transmission"] < 1.0
    assert t["transmission"] >= t["transmission_narrow"]  # buildup, again


def test_incident_hvl_monotone_in_kvp_and_filtration():
    hvl = [
        beam.tube_probe([("aluminium", 1.0)], kvp=kv, filtration_mm_al=2.5)["hvl_al_in_mm"]
        for kv in (60.0, 80.0, 100.0, 120.0)
    ]
    assert all(b > a for a, b in zip(hvl, hvl[1:])), hvl
    filt = [
        beam.tube_probe([("aluminium", 1.0)], kvp=100.0, filtration_mm_al=f)["hvl_al_in_mm"]
        for f in (1.0, 2.5, 4.0)
    ]
    assert all(b > a for a, b in zip(filt, filt[1:])), filt


def test_more_shield_transmits_less():
    ts = [
        beam.tube_probe([("lead", x)], kvp=150.0, filtration_mm_al=2.5)["transmission"]
        for x in (0.05, 0.1, 0.2, 0.4)
    ]
    assert all(b < a for a, b in zip(ts, ts[1:])), ts


def test_spectrum_averaged_transmission_is_quantity_dependent():
    """The contrast with the mono-line invariance: a *polyenergetic* beam's transmission
    depends on the response you weight it with, because the response is energy-dependent."""
    kw = dict(kvp=120.0, filtration_mm_al=2.5)
    t_k = beam.tube_probe([("aluminium", 2.0)], quantity="air_kerma", **kw)["transmission"]
    t_h = beam.tube_probe([("aluminium", 2.0)], quantity="ambient_H10", **kw)["transmission"]
    assert t_k != pytest.approx(t_h, rel=1e-6)


def test_dropped_incident_fraction_is_reported_and_lead_drops_more():
    """The §11 honesty number: lead's 30 keV buildup floor excludes more of an 80 kVp beam than
    aluminium's 15 keV floor does — reported, never silently folded in as if scored."""
    kw = dict(kvp=80.0, filtration_mm_al=2.5)
    d_al = beam.tube_probe([("aluminium", 1.0)], **kw)["dropped_incident_fraction"]
    d_pb = beam.tube_probe([("lead", 0.1)], **kw)["dropped_incident_fraction"]
    assert 0.0 <= d_al < d_pb < 1.0
    # heavier inherent filtration removes the soft photons before scoring, so less is dropped
    d_al_filtered = beam.tube_probe([("aluminium", 1.0)], kvp=80.0, filtration_mm_al=6.0)[
        "dropped_incident_fraction"
    ]
    assert d_al_filtered < d_al


def test_whole_beam_below_the_band_raises():
    """A 25 kVp beam is entirely below lead's 30 keV buildup floor: nothing is scoreable, so
    nothing is reported (no zero, no B=1)."""
    with pytest.raises(beam.BeamError, match="scored band"):
        beam.tube_probe([("lead", 0.1)], kvp=25.0, filtration_mm_al=0.5)


def test_tube_spectrum_arrays_are_consistent():
    t = beam.tube_probe([("iron", 1.0)], kvp=200.0, filtration_mm_al=2.5, n_bins=64)
    s = t["spectrum"]
    assert len(s["E_MeV"]) == len(s["phi_in"]) == len(s["phi_out"]) == t["n_bins_scored"]
    assert all(o <= i for o, i in zip(s["phi_out"], s["phi_in"]))
    lo, hi = t["band_MeV"]
    assert all(lo <= e <= hi for e in s["E_MeV"])


def test_incident_beam_characterization_is_stack_independent():
    """The two-band split (see the module docstring): the *incident* beam's mean energy and
    HVL in aluminium are properties of the BEAM, so putting lead in front of it must not
    appear to harden it — even though lead's 30 keV buildup floor shrinks the *scored* band
    (which the dropped fraction reports)."""
    kw = dict(kvp=100.0, filtration_mm_al=2.5)
    thin_al = beam.tube_probe([("aluminium", 0.1)], **kw)
    thick_pb = beam.tube_probe([("lead", 0.5)], **kw)
    assert thick_pb["mean_E_in_MeV"] == pytest.approx(thin_al["mean_E_in_MeV"], rel=1e-12)
    assert thick_pb["hvl_al_in_mm"] == pytest.approx(thin_al["hvl_al_in_mm"], rel=1e-12)
    assert thick_pb["beam_band_MeV"] == thin_al["beam_band_MeV"]
    # ...while the SCORED band and the dropped fraction do differ with the stack.
    assert thick_pb["band_MeV"][0] > thin_al["band_MeV"][0]
    assert thick_pb["dropped_incident_fraction"] > thin_al["dropped_incident_fraction"]
    # the scored-band incident mean is the harder, band-restricted twin (kept distinct)
    assert thick_pb["mean_E_in_scored_MeV"] > thick_pb["mean_E_in_MeV"]
