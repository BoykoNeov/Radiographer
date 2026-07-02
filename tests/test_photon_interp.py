"""Contract tests for the M3 energy-axis interpolators (HANDOFF_PLAN.md §6, §7).

The M2 loaders (``engine.attenuation`` / ``buildup`` / ``conversion``) deliberately ship
*no* interpolation — the energy axis is M3's job, with three sharp contracts these tests
pin down:

1. **Log–log correctness** — interpolation is linear in (ln E, ln y); an exact grid hit
   returns the tabulated value unchanged.
2. **Edge-aware bracket selection** — ``data/attenuation`` duplicates the energy at an
   absorption edge (Pb K-edge 0.0880045: μ/ρ 1.91 below, 7.683 above). A query must land
   in the segment with *distinct* endpoints on the correct side of the edge; a naive
   ``np.interp`` would blend the two branches and return nonsense.
3. **Two-floor / two-end off-grid signalling** — below a grid floor or above a grid end
   raises ``OffGridError`` with a ``reason`` (BELOW_FLOOR vs ABOVE_GRID). The interpolator
   stays *pure*: it signals, it does not decide skip-vs-error (that policy is the dose
   engine's, which knows the line and the quantity). Buildup interpolates **B**, not the
   non-smooth G-P coefficients.
"""

from __future__ import annotations

import math

import pytest

from engine import photon_interp as pi
from engine.buildup import BuildupError


# --- log–log correctness -------------------------------------------------------------


def _loglog(e_lo, y_lo, e_hi, y_hi, e):
    f = (math.log(e) - math.log(e_lo)) / (math.log(e_hi) - math.log(e_lo))
    return math.exp(math.log(y_lo) + f * (math.log(y_hi) - math.log(y_lo)))


def test_mu_rho_exact_grid_point_is_unchanged():
    # 1.0 MeV is a tabulated air energy; interpolation must not perturb a grid value.
    from engine import attenuation as att

    e_grid = att.energies("air")
    mu_grid = att.mu_rho("air")
    i = next(k for k, e in enumerate(e_grid) if abs(e - 1.0) < 1e-12)
    assert pi.interp_mu_rho("air", 1.0) == pytest.approx(mu_grid[i], rel=1e-12)


def test_mu_rho_loglog_midpoint_matches_hand_calc():
    # A segment well clear of any edge (air, low-Z, has none): 0.6→0.8 MeV.
    from engine import attenuation as att

    e_grid = att.energies("air")
    mu_grid = att.mu_rho("air")
    lo = next(k for k, e in enumerate(e_grid) if abs(e - 0.6) < 1e-12)
    hi = next(k for k, e in enumerate(e_grid) if abs(e - 0.8) < 1e-12)
    e_mid = math.sqrt(0.6 * 0.8)  # geometric midpoint
    expected = _loglog(e_grid[lo], mu_grid[lo], e_grid[hi], mu_grid[hi], e_mid)
    assert pi.interp_mu_rho("air", e_mid) == pytest.approx(expected, rel=1e-12)


def test_muen_rho_interpolates_too():
    from engine import attenuation as att

    e_grid = att.energies("water")
    muen_grid = att.muen_rho("water")
    lo = next(k for k, e in enumerate(e_grid) if abs(e - 1.0) < 1e-12)
    hi = next(k for k, e in enumerate(e_grid) if abs(e - 1.25) < 1e-12)
    e_mid = math.sqrt(1.0 * 1.25)
    expected = _loglog(e_grid[lo], muen_grid[lo], e_grid[hi], muen_grid[hi], e_mid)
    assert pi.interp_muen_rho("water", e_mid) == pytest.approx(expected, rel=1e-12)


# --- edge-aware bracket selection (the one that bites) --------------------------------


def test_mu_rho_below_pb_k_edge_uses_pre_edge_branch():
    # 0.085 MeV is between 0.08 (μ/ρ 2.419) and the K-edge 0.0880045 (pre-edge 1.91).
    # Edge-aware interp stays on the LOW branch: result in (1.91, 2.419), nowhere near
    # the post-edge 7.683.
    val = pi.interp_mu_rho("lead", 0.085)
    assert 1.9 < val < 2.42


def test_mu_rho_above_pb_k_edge_uses_post_edge_branch():
    # 0.09 MeV is between the K-edge (post-edge 7.683) and 0.1 (μ/ρ 5.549).
    # Edge-aware interp jumps to the HIGH branch: result in (5.549, 7.683).
    val = pi.interp_mu_rho("lead", 0.09)
    assert 5.5 < val < 7.7


def test_pb_k_edge_query_straddle_is_not_a_naive_blend():
    # The discriminator: a naive np.interp across the duplicated edge energy would return
    # an intermediate value for both queries. Edge-aware selection keeps them on opposite
    # branches — so the just-above value is far larger than the just-below value.
    assert pi.interp_mu_rho("lead", 0.09) > 3.0 * pi.interp_mu_rho("lead", 0.085)


def test_exact_edge_energy_returns_post_edge_value():
    # A photon line AT the K-edge can K-ionise → the higher (post-edge) μ/ρ is physical.
    assert pi.interp_mu_rho("lead", 0.0880045) == pytest.approx(7.683, rel=1e-9)


# --- off-grid signalling (pure: reason, no policy) ------------------------------------


def test_attenuation_below_floor_raises_below_floor():
    # Air grid floor is 1 keV (0.001 MeV); 0.5 keV is below it.
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_mu_rho("air", 0.0005)
    assert exc.value.reason == pi.BELOW_FLOOR


def test_attenuation_above_end_raises_above_grid():
    # Air grid ends at 20 MeV.
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_muen_rho("air", 25.0)
    assert exc.value.reason == pi.ABOVE_GRID


def test_conversion_below_10kev_floor_raises_below_floor():
    # H*(10) scoring floor is 10 keV (0.01 MeV), higher than the 1 keV attenuation floor.
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_conversion("ambient_H10", 0.005)
    assert exc.value.reason == pi.BELOW_FLOOR


def test_conversion_hstar10_above_10mev_raises_above_grid():
    # ICRP-74 H*(10) grid ends at 10 MeV; never extrapolate (underestimates dose).
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_conversion("ambient_H10", 12.0)
    assert exc.value.reason == pi.ABOVE_GRID


def test_conversion_effective_reaches_higher_energies():
    # ICRP-116 effective runs to 10 GeV, so a decay-gamma energy is well in range.
    val = pi.interp_conversion("effective", 1.0, geometry="AP")
    assert val > 0.0


# --- buildup: interpolate B, not the coefficients -------------------------------------


def test_buildup_mfp_zero_is_unity():
    assert pi.interp_buildup("lead", 0.662, 0.0) == pytest.approx(1.0, abs=1e-12)


def test_buildup_exact_grid_energy_matches_loader():
    from engine import buildup as bu

    # 1.0 MeV is on the lead buildup grid; interp must equal the direct G-P evaluation.
    assert pi.interp_buildup("lead", 1.0, 2.0) == pytest.approx(
        bu.buildup_factor("lead", 1.0, 2.0), rel=1e-12
    )


def test_buildup_interpolated_energy_lies_between_neighbours():
    from engine import buildup as bu

    # 0.662 MeV (Cs-137 line) is between grid points 0.6 and 0.8 in lead.
    b_lo = bu.buildup_factor("lead", 0.6, 3.0)
    b_hi = bu.buildup_factor("lead", 0.8, 3.0)
    b = pi.interp_buildup("lead", 0.662, 3.0)
    assert min(b_lo, b_hi) <= b <= max(b_lo, b_hi)
    # and it is the log–log (ln B vs ln E) interpolant, not a coefficient blend
    expected = _loglog(0.6, b_lo, 0.8, b_hi, 0.662)
    assert b == pytest.approx(expected, rel=1e-9)


def test_buildup_below_grid_floor_raises_below_floor():
    # Lead buildup grid starts at 0.03 MeV (high-Z omits 15/20 keV).
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_buildup("lead", 0.02, 1.0)
    assert exc.value.reason == pi.BELOW_FLOOR


def test_buildup_above_grid_end_raises_above_grid():
    # ANS-6.4.3 buildup grid ends at 15 MeV.
    with pytest.raises(pi.OffGridError) as exc:
        pi.interp_buildup("lead", 18.0, 1.0)
    assert exc.value.reason == pi.ABOVE_GRID


def test_buildup_no_data_material_raises_loudly():
    # PMMA has NO ANS-6.4.3 buildup — the honest contract is a loud loader error,
    # never a silent B=1 surrogate. The interpolator must not swallow it.
    with pytest.raises(BuildupError):
        pi.interp_buildup("pmma", 1.0, 1.0)
