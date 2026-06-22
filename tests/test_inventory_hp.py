"""Regression tests for the precompute-once arbitrary-precision (HP) path.

Why this file exists (HANDOFF_PLAN §3, advisor guidance): switching precision to
"arbitrary" used to call ``radioactivedecay``'s ``InventoryHP.decay(t)`` once per
grid point. That re-runs a full-dataset sympy matmul (≈0.7 s/call regardless of
chain size) and the ~5 UI panels each evaluate the grid → the synchronous,
main-thread Pyodide call froze the page for minutes. The fix solves the
closure's Bateman coefficients ONCE in high precision and then evaluates a cheap
mpmath matvec, with a 1-deep cache collapsing the panel fan-out to a single solve.

Two distinct claims are asserted:

* **Parity** — the fast HP path reproduces rd's own ``InventoryHP`` (its 320-digit
  default) to the float64 downcast, on single- AND multi-nuclide inventories. This
  is a *parity* check: a faithful reimplementation of rd's matmul restricted to the
  closure, NOT an independent physics validation.
* **It does its job** — on a stiff chain the HP path recovers real sub-floor
  activities that the double path (correctly) floors to honest zero. This proves the
  path is exercised and still earns its keep, not merely that it is fast.
"""

from __future__ import annotations

import numpy as np
import pytest
import radioactivedecay as rd

from engine.inventory import HP_DPS, SolvedInventory

DAY_S = 86400.0
# Peak-normalized agreement: measured ~1e-16; assert well inside that with margin
# for platform float formatting. The shared scale is the per-time peak activity
# (mirrors the engine's own per-row validity-floor philosophy — a deep daughter at
# 1e-250 is physical zero, and its meaningless relative error must not gate parity).
PARITY_NORM_TOL = 1e-9


def _rd_hp_activities(spec, t_d):
    return rd.InventoryHP(spec, "Bq").decay(t_d, "d").activities("Bq")


@pytest.mark.parametrize(
    "spec",
    [
        {"Co-60": 1.0},  # trivial 2-nuclide chain
        {"Sr-90": 1.0},  # short chain
        {"U-238": 1.0},  # long, wide-half-life-span chain (HP recommended)
        {"Cf-252": 1.0},  # has a spontaneous-fission branch
        {"Sr-90": 1.0, "Cs-137": 2.0, "Co-60": 0.5},  # MULTI-nuclide mix
        {"U-238": 1.0, "Th-232": 1.0, "Ra-226": 0.3},  # multi-parent, overlapping closures
    ],
)
@pytest.mark.parametrize("t_d", [1.0, 365.0, 3.65e4, 3.65e6])
def test_fast_hp_matches_rd_hp(spec, t_d):
    """Fast precompute-once HP == rd's InventoryHP, peak-normalized, incl. mixes.

    The decisive case is the multi-nuclide mix: the ``b[k] = Σ C_inv[k,j]·N0_j``
    reconstruction must generalize to overlapping closures / multiple nonzero N0.
    """
    solved = SolvedInventory.from_spec(spec, "Bq", precision="hp")
    out = solved.evaluate([t_d * DAY_S], axis="activity", unit="Bq")
    mine = {n: out["series"][n][0] for n in out["nuclides"]}
    ref = {str(k): float(v) for k, v in _rd_hp_activities(spec, t_d).items()}

    peak = max((abs(v) for v in ref.values()), default=0.0)
    if peak == 0.0:
        pytest.skip("degenerate: all-stable at this time")
    for nuc, ref_a in ref.items():
        got = mine.get(nuc, 0.0)
        assert abs(got - ref_a) / peak < PARITY_NORM_TOL, f"{nuc}: {got} vs {ref_a}"


def test_fast_hp_matches_rd_hp_over_a_whole_grid():
    """Parity holds across an entire log-spaced grid (the real evaluate shape)."""
    spec = {"U-238": 1.0, "Cs-137": 0.5}
    solved = SolvedInventory.from_spec(spec, "Bq", precision="hp")
    times_d = np.logspace(-1, 6, 40)
    out = solved.evaluate((times_d * DAY_S).tolist(), axis="activity", unit="Bq")
    for j, t_d in enumerate(times_d):
        ref = {str(k): float(v) for k, v in _rd_hp_activities(spec, float(t_d)).items()}
        peak = max((abs(v) for v in ref.values()), default=0.0)
        if peak == 0.0:
            continue
        for nuc in out["nuclides"]:
            got = out["series"][nuc][j]
            assert abs(got - ref.get(nuc, 0.0)) / peak < PARITY_NORM_TOL


def test_hp_beats_double_on_a_stiff_chain():
    """The HP path recovers real sub-floor activity the double path floors to zero.

    U-238 @ 1 day: double-precision cancellation buries the deep daughters under the
    validity floor (returned as honest 0.0); HP recovers their true (tiny) values,
    matching rd's InventoryHP. This is the whole reason the HP path exists — proof it
    is genuinely exercised, not just a faster way to get the same double answer."""
    spec = {"U-238": 1.0}
    dbl = SolvedInventory.from_spec(spec, "Bq")
    hp = SolvedInventory.from_spec(spec, "Bq", precision="hp")
    t = [1.0 * DAY_S]
    dbl_series = dbl.evaluate(t, axis="activity", unit="Bq")["series"]
    hp_series = hp.evaluate(t, axis="activity", unit="Bq")["series"]
    ref = {str(k): float(v) for k, v in _rd_hp_activities(spec, 1.0).items()}

    recovered = 0
    for nuc in ("Th-230", "Ra-226", "Pb-210", "Po-210"):
        if ref.get(nuc, 0.0) > 0.0:
            assert dbl_series[nuc][0] == 0.0, f"{nuc} should be double-floored to 0"
            assert hp_series[nuc][0] > 0.0, f"{nuc} should be HP-recovered > 0"
            assert hp_series[nuc][0] == pytest.approx(ref[nuc], rel=1e-6)
            recovered += 1
    assert recovered >= 1  # the contrast actually happened


def test_hp_evaluate_caches_one_solve_per_grid():
    """The 1-deep cache collapses the panel fan-out: an identical grid → no recompute.

    All UI panels (curves, γ/β, neutron, decay-heat, internal) evaluate the SAME
    ``curveX + t₀`` grid; the cache must return the SAME array (identity) on a repeat
    so HP is computed once per user action, not ~5×. A different grid evicts it."""
    solved = SolvedInventory.from_spec({"U-238": 1.0}, "Bq", precision="hp")
    t = np.array([1.0 * DAY_S, 365.0 * DAY_S, 3.65e4 * DAY_S])

    n1 = solved._evaluate_hp_atoms(t)
    n2 = solved._evaluate_hp_atoms(t.copy())  # equal values, different object
    assert n2 is n1  # cache hit → no recompute (the fan-out collapse)

    n3 = solved._evaluate_hp_atoms(t * 2.0)  # different grid → recompute
    assert n3 is not n1
    # 1-deep: the previous grid is evicted, so the original grid recomputes a fresh array
    n4 = solved._evaluate_hp_atoms(t)
    assert n4 is not n1
    np.testing.assert_array_equal(n4, n1)  # ...but identical values


def test_hp_dps_is_sane():
    """HP_DPS must comfortably exceed double precision (≈16 digits) and the worst
    realistic cancellation depth, while staying far below rd's wasteful 320."""
    assert HP_DPS >= 40
    assert HP_DPS < 320
