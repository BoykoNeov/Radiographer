"""Energy-axis interpolation for the M3 gamma-dose engine (HANDOFF_PLAN.md §6, §7).

The M2 loaders (``engine.attenuation`` / ``buildup`` / ``conversion``) ship the raw grids
and deliberately do **no** interpolation — the energy axis is M3's contract, and it has
three sharp edges this module owns:

1. **Edge-aware log–log μ/ρ, μ_en/ρ.** ``data/attenuation`` duplicates the energy at an
   absorption edge (Pb K-edge 0.0880045: μ/ρ steps 1.91 → 7.683 across one energy). A
   naive ``np.interp`` would average the two branches. :func:`interp_mu_rho` selects the
   bracketing segment with *distinct* endpoints and interpolates log–log inside it; a query
   exactly at a duplicated edge energy returns the **post-edge** (higher) value, which is
   the physical response for a photon at the edge (it can ionise the inner shell).

2. **Buildup interpolated in B-space, not coefficient-space.** The G-P coefficients (Xk in
   particular) are not smooth in energy, so :func:`interp_buildup` evaluates ``B`` at the
   two bracketing grid energies via :func:`engine.buildup.buildup_factor` and interpolates
   ``ln B`` vs ``ln E``.

3. **Pure off-grid signalling — severity is the dose engine's call.** Below a grid floor or
   above a grid end raises :class:`OffGridError` carrying a ``reason`` (:data:`BELOW_FLOOR`
   vs :data:`ABOVE_GRID`). This module does **not** decide skip-vs-error: the dose engine
   knows the line *and* the quantity (grid ends are quantity-specific) and maps BELOW_FLOOR
   → logged skip, ABOVE_GRID → loud error (dropping a high-E line underestimates dose). No
   silent fallback (CLAUDE.md): off-grid is always surfaced, never extrapolated.
"""

from __future__ import annotations

import math

from engine import attenuation as _att
from engine import buildup as _bu
from engine import conversion as _conv

#: Query energy is below the table's low-energy floor (e.g. < 1 keV attenuation, < 10 keV
#: conversion, < 15–30 keV buildup). The dose engine treats this as a logged skip.
BELOW_FLOOR = "BELOW_FLOOR"
#: Query energy is above the table's high-energy end (e.g. > 20 MeV attenuation, > 10 MeV
#: H*(10), > 15 MeV buildup). The dose engine treats this as a loud error.
ABOVE_GRID = "ABOVE_GRID"

_REL_TOL = 1e-9


class OffGridError(Exception):
    """Query energy is outside a table's grid. Carries ``reason`` (:data:`BELOW_FLOOR` /
    :data:`ABOVE_GRID`); raised pure, never swallowed — the dose engine decides severity."""

    def __init__(self, reason: str, message: str, *, E_MeV: float, bound: float):
        super().__init__(message)
        self.reason = reason
        self.E_MeV = E_MeV
        self.bound = bound


def _check_bounds(table: str, E_MeV: float, e_lo: float, e_hi: float) -> None:
    """Raise :class:`OffGridError` with the right reason if ``E_MeV`` is off-grid."""
    if E_MeV < e_lo and not math.isclose(E_MeV, e_lo, rel_tol=_REL_TOL):
        raise OffGridError(
            BELOW_FLOOR,
            f"{table}: energy {E_MeV:g} MeV is below the grid floor {e_lo:g} MeV",
            E_MeV=E_MeV,
            bound=e_lo,
        )
    if E_MeV > e_hi and not math.isclose(E_MeV, e_hi, rel_tol=_REL_TOL):
        raise OffGridError(
            ABOVE_GRID,
            f"{table}: energy {E_MeV:g} MeV is above the grid end {e_hi:g} MeV "
            "(never extrapolated — that would underestimate dose)",
            E_MeV=E_MeV,
            bound=e_hi,
        )


def _loglog_on_grid(E_grid: list[float], y_grid: list[float], E_MeV: float) -> float:
    """Edge-aware log–log interpolation on an ascending grid that may carry duplicate
    energies at absorption edges. Assumes ``E_grid[0] <= E_MeV <= E_grid[-1]`` (bounds are
    checked by the caller). At a duplicated energy the post-edge (higher) value is returned.
    """
    n = len(E_grid)
    # Find the first index whose energy is >= the query (ties resolve to the lower index).
    hi = 0
    while hi < n and E_grid[hi] < E_MeV and not math.isclose(E_grid[hi], E_MeV, rel_tol=_REL_TOL):
        hi += 1

    if hi >= n:  # equals the last grid point within tolerance
        return float(y_grid[-1])

    if math.isclose(E_grid[hi], E_MeV, rel_tol=_REL_TOL):
        # Exact grid hit. If it is the low side of a duplicated edge energy, step to the
        # post-edge value (physical for a line AT the edge).
        while hi + 1 < n and math.isclose(E_grid[hi + 1], E_grid[hi], rel_tol=_REL_TOL):
            hi += 1
        return float(y_grid[hi])

    # Strictly inside the segment [hi-1, hi]; these endpoints are distinct (an equal pair
    # would have been caught as an exact hit), so the interpolation never straddles an edge.
    lo = hi - 1
    e_lo, e_hi = E_grid[lo], E_grid[hi]
    y_lo, y_hi = y_grid[lo], y_grid[hi]
    f = (math.log(E_MeV) - math.log(e_lo)) / (math.log(e_hi) - math.log(e_lo))
    return math.exp(math.log(y_lo) + f * (math.log(y_hi) - math.log(y_lo)))


def _interp_attenuation(material: str, coeffs: list[float], E_MeV: float) -> float:
    e_grid = _att.energies(material)
    _check_bounds(f"attenuation/{material}", E_MeV, e_grid[0], e_grid[-1])
    return _loglog_on_grid(e_grid, coeffs, E_MeV)


def interp_mu_rho(material: str, E_MeV: float) -> float:
    """Mass attenuation coefficient μ/ρ (cm²/g) at ``E_MeV``, edge-aware log–log."""
    return _interp_attenuation(material, _att.mu_rho(material), E_MeV)


def interp_muen_rho(material: str, E_MeV: float) -> float:
    """Mass energy-absorption coefficient μ_en/ρ (cm²/g) at ``E_MeV``, edge-aware log–log."""
    return _interp_attenuation(material, _att.muen_rho(material), E_MeV)


def interp_conversion(quantity: str, E_MeV: float, geometry: str | None = None) -> float:
    """Fluence-to-dose coefficient (pSv·cm²) at ``E_MeV``, log–log.

    ``quantity`` is ``ambient_H10`` or ``effective`` (the latter needs a ``geometry``).
    These coefficients are smooth in energy (no edges), but the floors/ends differ by
    quantity — H*(10) ends at 10 MeV, effective runs to 10 GeV.
    """
    e_grid = _conv.energies(quantity, geometry)
    coeffs = _conv.coefficients_pSv_cm2(quantity, geometry)
    label = quantity if geometry is None else f"{quantity}/{geometry}"
    _check_bounds(f"conversion/{label}", E_MeV, e_grid[0], e_grid[-1])
    return _loglog_on_grid(e_grid, coeffs, E_MeV)


def interp_buildup(material: str, E_MeV: float, mfp: float) -> float:
    """Exposure buildup factor ``B`` at ``E_MeV`` and depth ``mfp`` (mean free paths).

    Interpolated in **B-space** (``ln B`` vs ``ln E``), not coefficient-space — the G-P
    coefficients are not smooth in energy. ``mfp == 0`` returns 1 exactly. A material with
    no ANS-6.4.3 buildup (PMMA, polyethylene, soft tissue) raises ``BuildupError`` from the
    loader — never a silent B=1 surrogate (§6.5).
    """
    e_grid = _bu.energies(material)  # BuildupError if the material has no buildup data
    _check_bounds(f"buildup/{material}", E_MeV, e_grid[0], e_grid[-1])
    if mfp == 0.0:
        return 1.0

    # Locate the bracketing grid energies (the buildup grid has no duplicate energies).
    n = len(e_grid)
    hi = 0
    while hi < n and e_grid[hi] < E_MeV and not math.isclose(e_grid[hi], E_MeV, rel_tol=_REL_TOL):
        hi += 1

    if hi >= n or math.isclose(e_grid[hi], E_MeV, rel_tol=_REL_TOL):
        idx = min(hi, n - 1)
        return _bu.buildup_factor(material, e_grid[idx], mfp)

    lo = hi - 1
    e_lo, e_hi = e_grid[lo], e_grid[hi]
    b_lo = _bu.buildup_factor(material, e_lo, mfp)
    b_hi = _bu.buildup_factor(material, e_hi, mfp)
    f = (math.log(E_MeV) - math.log(e_lo)) / (math.log(e_hi) - math.log(e_lo))
    return math.exp(math.log(b_lo) + f * (math.log(b_hi) - math.log(b_lo)))
