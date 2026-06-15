"""Regression tests for the solve-once / evaluate-many inventory engine.

The central correctness claim (HANDOFF_PLAN §3): our restricted-dense
factorization reproduces ``radioactivedecay``'s own ``.decay()`` while making
evaluate-many cheap. Tolerances are **tiered on purpose** (advisor guidance):

* *meaningful* nuclides (activity well above the double-precision floor) must
  match ``rd`` — and the arbitrary-precision ``InventoryHP`` truth — to ~1e-12;
* *deep-chain* daughters below the floor are **known double-precision noise**;
  we assert they are floored to honest zero, and a separate HP test recovers
  their real (tiny) values. We never loosen the meaningful-nuclide tolerance to
  absorb that noise — doing so would hide the very failure we surface.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import radioactivedecay as rd

from engine.inventory import (
    HP_HALFLIFE_SPAN,
    VALIDITY_FLOOR_REL,
    EngineError,
    SolvedInventory,
    _apply_validity_floor,
)

DAY_S = 86400.0
MEANINGFUL_REL_TOL = 1e-12


def _rd_activities(spec, t_d):
    return rd.Inventory(spec, "Bq").decay(t_d, "d").activities("Bq")


@pytest.mark.parametrize("spec", [{"Cs-137": 1.0}, {"Mo-99": 1.0}, {"Co-60": 1.0}])
@pytest.mark.parametrize("t_d", [1.0, 365.0, 3.65e5])
def test_solve_once_machine_precision_well_conditioned(spec, t_d):
    """For well-conditioned (non-stiff) chains, solve-once == rd.decay() to ~1e-12.

    These chains don't suffer catastrophic cancellation, so the restricted-dense
    factorization reproduces rd's full-sparse solve to machine precision on every
    nuclide the engine resolves (non-clipped)."""
    solved = SolvedInventory.from_spec(spec, "Bq")
    assert solved.hp_recommended() is False  # guard: these specs really are non-stiff
    out = solved.evaluate([t_d * DAY_S], axis="activity", unit="Bq")
    mine = {n: out["series"][n][0] for n in out["nuclides"]}
    ref = _rd_activities(spec, t_d)
    peak = max(abs(v) for v in ref.values())

    checked = 0
    for nuc, ref_a in ref.items():
        if mine.get(nuc, 0.0) == 0.0:
            continue  # engine clipped as exact-zero / unresolvable
        checked += 1
        assert mine[nuc] == pytest.approx(ref_a, rel=MEANINGFUL_REL_TOL, abs=peak * 1e-13)
    assert checked > 0, "test exercised no resolved nuclide"


@pytest.mark.parametrize("spec", [{"U-238": 1.0}, {"Th-232": 2.0, "Co-60": 1.0}])
@pytest.mark.parametrize("t_d", [1.0, 365.0, 3.65e5])
def test_solve_once_tracks_rd_on_stiff_chains(spec, t_d):
    """For stiff chains, every *clearly meaningful* nuclide must be resolved (not
    wrongly clipped — this is the Po-212 regression guard) and track rd.

    Two double implementations of an ill-conditioned chain only agree to the
    conditioning limit, so the tolerance is honestly looser than the non-stiff
    case. The deep sub-noise band is covered by the HP test, not here."""
    solved = SolvedInventory.from_spec(spec, "Bq")
    out = solved.evaluate([t_d * DAY_S], axis="activity", unit="Bq")
    mine = {n: out["series"][n][0] for n in out["nuclides"]}
    ref = _rd_activities(spec, t_d)
    peak = max(abs(v) for v in ref.values())

    for nuc, ref_a in ref.items():
        if abs(ref_a) <= peak * 1e-6:
            continue  # marginal/noise band — double is unreliable, see HP test
        # A short-lived daughter (e.g. Po-212, 300 ns) has a tiny atom count but a
        # large activity: it must NOT be floored away.
        assert mine.get(nuc, 0.0) != 0.0, f"{nuc} (rd={ref_a:.3e} Bq) was wrongly clipped"
        assert mine[nuc] == pytest.approx(ref_a, rel=1e-5, abs=peak * 1e-9)


@pytest.mark.parametrize(
    "spec_atoms",
    [
        {"Mo-99": 5.0e5, "Tc-99m": 3.0e5},  # parent + its own daughter (generator)
        {"U-238": 2.0e17, "U-234": 7.0e9},  # parent + a deep daughter (aged source)
    ],
)
def test_overlapping_multispecies_load_is_exact_at_t0(spec_atoms):
    """Loading overlapping supports (parent + its daughter) must place each input
    exactly. At t=0, C·(C⁻¹·n0) = n0 is an exact identity — any closure/indexing
    slip in the union-closure shows immediately; non-loaded progeny start at 0."""
    solved = SolvedInventory.from_spec(spec_atoms, "atoms")
    out = solved.evaluate([0.0], axis="atoms")["series"]
    for nuc in solved.names:
        expected = spec_atoms.get(nuc, 0.0)
        assert out[nuc][0] == pytest.approx(expected, rel=1e-12, abs=1e-3)


def test_overlapping_multispecies_matches_rd_at_nonzero_time():
    """Overlapping load tracks rd at a non-trivial time (generator in-growth)."""
    spec = {"Mo-99": 5.0e5, "Tc-99m": 3.0e5}
    solved = SolvedInventory.from_spec(spec, "atoms")
    t_s = 6.0 * 3600.0  # 6 h — Tc-99m (6 h) and Mo-99 (66 h) both evolving
    mine = solved.evaluate([t_s], axis="activity", unit="Bq")["series"]
    ref = rd.Inventory(spec, "num").decay(t_s, "s").activities("Bq")
    for nuc in solved.names:
        if mine[nuc][0] == 0.0:
            continue
        assert mine[nuc][0] == pytest.approx(ref.get(nuc, 0.0), rel=1e-10, abs=1e-9)


def test_deep_chain_doubles_are_floored_not_garbage():
    """U-238 @ 1 day: rd's own doubles emit negatives/garbage below the floor.

    The engine must return honest zeros there (clipped), NOT the garbage and NOT
    a raised error — the garbage is below the validity floor.
    """
    solved = SolvedInventory.from_spec({"U-238": 1.0}, "Bq")
    out = solved.evaluate([1.0 * DAY_S], axis="activity", unit="Bq")
    series = out["series"]
    # Deep daughters are floored to exactly 0.0 (no negative activities leak out).
    for nuc in ("Bi-214", "Po-214", "Po-210", "Pb-210"):
        assert series[nuc][0] == 0.0
    assert out["clipped_count"] > 0
    # No negative values anywhere in the (double) result.
    assert all(v >= 0.0 for col in series.values() for v in col)


def test_hp_recovers_deep_chain_truth():
    """The on-demand HP path computes the real (tiny) deep-chain activities."""
    spec = {"U-238": 1.0}
    hp = SolvedInventory.from_spec(spec, "Bq", precision="hp")
    out = hp.evaluate([1.0 * DAY_S], axis="activity", unit="Bq")
    ref = rd.InventoryHP(spec, "Bq").decay(1.0, "d").activities("Bq")
    series = out["series"]
    # Th-230 truth ~9.2e-19 Bq — far below the double floor, recovered by HP.
    assert series["Th-230"][0] == pytest.approx(float(ref["Th-230"]), rel=1e-9)
    assert series["Th-230"][0] > 0.0


def test_evaluate_many_is_one_solve_for_a_whole_grid():
    """Evaluating a time grid matches per-time rd.decay() across the grid."""
    spec = {"Mo-99": 1.0}
    solved = SolvedInventory.from_spec(spec, "Bq")
    times_d = np.logspace(-2, 2, 50)
    out = solved.evaluate((times_d * DAY_S).tolist(), axis="activity", unit="Bq")
    for j, t_d in enumerate(times_d):
        ref = _rd_activities(spec, float(t_d))
        for nuc in out["nuclides"]:
            assert out["series"][nuc][j] == pytest.approx(
                ref.get(nuc, 0.0), rel=MEANINGFUL_REL_TOL, abs=1e-25
            )


def test_secular_equilibrium_cs137():
    """A(Ba-137m)/A(Cs-137) -> the Cs-137 branching fraction (0.944) at equilibrium."""
    solved = SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq")
    out = solved.evaluate([1.0 * DAY_S], axis="activity", unit="Bq")
    ratio = out["series"]["Ba-137m"][0] / out["series"]["Cs-137"][0]
    bf = rd.Nuclide("Cs-137").branching_fractions()[rd.Nuclide("Cs-137").progeny().index("Ba-137m")]
    assert ratio == pytest.approx(bf, rel=1e-3)


def test_axis_atoms_and_mass_and_activity_consistent():
    """activity = λ·N and mass = N·M/N_A must agree with rd's conversions."""
    spec = {"Co-60": 5.0}
    solved = SolvedInventory.from_spec(spec, "Bq")
    t = [10.0 * 365.0 * DAY_S]
    atoms = solved.evaluate(t, axis="atoms")["series"]
    act = solved.evaluate(t, axis="activity", unit="Bq")["series"]
    mass = solved.evaluate(t, axis="mass", unit="g")["series"]
    ref = rd.Inventory(spec, "Bq").decay(10.0 * 365.0, "d")
    ref_act = ref.activities("Bq")
    ref_mass = ref.masses("g")
    for nuc in solved.names:
        assert act[nuc][0] == pytest.approx(ref_act.get(nuc, 0.0), rel=1e-10, abs=1e-15)
        # mass of a stable end-product is meaningful even when activity is 0
        assert mass[nuc][0] == pytest.approx(ref_mass.get(nuc, 0.0), rel=1e-10, abs=1e-30)
    # Co-60 activity = λ·N internal consistency
    lam = math.log(2) / rd.Nuclide("Co-60").half_life("s")
    assert act["Co-60"][0] == pytest.approx(lam * atoms["Co-60"][0], rel=1e-12)


def test_ci_unit_conversion():
    solved = SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq")
    bq = solved.evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
    ci = solved.evaluate([0.0], axis="activity", unit="Ci")["series"]["Cs-137"][0]
    assert ci == pytest.approx(bq / 3.7e10, rel=1e-12)


def test_input_unit_atoms_and_activity():
    """A 1 Bq Cs-137 source has N0 = 1/λ atoms; check input-unit handling."""
    lam = math.log(2) / rd.Nuclide("Cs-137").half_life("s")
    from_bq = SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq")
    n0 = from_bq.evaluate([0.0], axis="atoms")["series"]["Cs-137"][0]
    assert n0 == pytest.approx(1.0 / lam, rel=1e-12)
    from_atoms = SolvedInventory.from_spec({"Cs-137": 1.0 / lam}, "atoms")
    a0 = from_atoms.evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
    assert a0 == pytest.approx(1.0, rel=1e-12)


# --- metadata (§9) -------------------------------------------------------


def test_auto_time_range_brackets_halflives():
    solved = SolvedInventory.from_spec({"Mo-99": 1.0}, "Bq")
    lo, hi = solved.auto_time_range_s()
    hls = [
        rd.Nuclide(n).half_life("s")
        for n in solved.names
        if math.isfinite(rd.Nuclide(n).half_life("s"))
    ]
    assert lo == pytest.approx(0.01 * min(hls), rel=1e-9)
    assert hi == pytest.approx(10.0 * max(hls), rel=1e-9)


def test_hp_recommended_flags_stiff_chains_only():
    assert SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq").hp_recommended() is False
    assert SolvedInventory.from_spec({"U-238": 1.0}, "Bq").hp_recommended() is True


def test_metadata_shape():
    meta = SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq").metadata()
    assert meta["nuclides"][0] == "Cs-137"
    assert meta["half_lives_s"]["Ba-137"] is None  # stable -> null
    assert meta["validity_floor_rel"] == VALIDITY_FLOOR_REL
    assert meta["time_range_s"] is not None


# --- the honesty guard: validity floor (advisor) -------------------------


def test_validity_floor_clips_subnoise_to_zero():
    # Per-nuclide noise: small values within their own noise -> honest zero;
    # large values are kept even if another column's noise is large.
    N = np.array([[1.0e9, 5.0e-7, -3.0e-7, 2.0e8]])
    noise = np.array([[1.0, 1.0e-6, 1.0e-6, 1.0]])
    clipped, info = _apply_validity_floor(N, noise)
    assert clipped[0, 1] == 0.0  # +5e-7 < its noise 1e-6 -> 0
    assert clipped[0, 2] == 0.0  # -3e-7 within -noise -> 0 (noise, not a bug)
    assert clipped[0, 0] == 1.0e9
    assert clipped[0, 3] == 2.0e8
    assert info["clipped_count"] == 2


def test_validity_floor_raises_on_negative_beyond_noise():
    # A negative whose magnitude exceeds its noise bound is NOT noise — loud.
    N = np.array([[1.0e9, -50.0]])
    noise = np.array([[1.0, 1.0]])  # -50 < -1 -> raise
    with pytest.raises(EngineError, match="negative"):
        _apply_validity_floor(N, noise, names=["Big", "Bad"], times_s=[0.0])


def test_unknown_nuclide_raises():
    with pytest.raises(EngineError, match="unknown nuclide"):
        SolvedInventory.from_spec({"Xx-999": 1.0}, "Bq")


def test_negative_time_raises():
    solved = SolvedInventory.from_spec({"Cs-137": 1.0}, "Bq")
    with pytest.raises(EngineError, match="time"):
        solved.evaluate([-1.0], axis="activity")


def test_hp_span_constant_is_sane():
    assert HP_HALFLIFE_SPAN >= 1e9
