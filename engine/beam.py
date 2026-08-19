"""Beam probe — test a shield stack against an *external* beam (§6.5, §9 shield builder).

The rest of the dose engine answers "what dose does this **inventory** deliver through this
shield?". This module answers the orthogonal question a shield designer actually asks:

    "How much of a **60 keV line** / of a **100 kVp X-ray tube beam** gets through this stack?"

It is a pure function of the layer stack — **no inventory, no solve, no handle, no time, no
distance**. It reuses the already-validated point-kernel transmission
(:func:`engine.dose.stack_transmission`) verbatim, so the number it reports is the same
physics the γ dose path folds per line; nothing new is fitted or fabricated.

**Transmission only — never an absolute dose rate.** For a radionuclide the activity sets the
source strength; for an X-ray tube the output is mGy/mAs at 1 m, a tube-and-geometry-specific
calibration that is **not** in ``data/`` and would be fabricated if invented. So every number
here is a *ratio* (dimensionless transmission), a *thickness* (HVL/TVL), a *mean energy*, or a
relative spectrum shape. A caller that wants an absolute rate must supply its own measured
unshielded rate and scale — that number then comes from the user, not from this engine. This
keeps the feature inside §2's locked "shielding: arbitrary stack × thickness" scope: it probes
the stack, it does **not** add a source to §8's catalog.

The scored band (§11, and the design constraint that shapes everything here)
------------------------------------------------------------------------------
``B`` (ANS-6.4.3 G-P buildup) is tabulated from **15 keV** for most materials but only from
**30 keV for lead**, up to 15 MeV — and :func:`engine.photon_interp.interp_buildup` *raises*
below that floor rather than substituting ``B = 1`` (which would under-count dose: the silent
surrogate §6.5 forbids). A diagnostic X-ray spectrum extends well below both floors, so this
module defines **one scored band per stack**:

    E_lo = max(10 keV scoring floor δ, every layer's buildup floor, every layer's μ/ρ floor)
    E_hi = min(every layer's buildup end, every layer's μ/ρ end)

Bins outside the band are dropped from **both** the transmitted sum and the incident
normalization, and the incident weight that was dropped is reported as
``dropped_incident_fraction`` (the same "never silent" idiom as the dropped SF-rate and
dropped-(α,n) fractions, §11). Dropping treats those photons as **fully absorbed** — very
nearly exact for any real shield (15 keV through 1 mm of aluminium transmits ~12 %; 30 keV
through 0.5 mm of lead ~1e-7).

**Direction of that bias:** the dropped photons are the *softest* in the beam, i.e. the ones
the stack removes hardest, so excluding them from both sides of the ratio makes the reported
transmission an **upper bound** on the whole beam's transmission (it over-states what gets
through — the conservative direction for a shield). It is a *ratio over the scored band*, not
over the whole beam, and ``dropped_incident_fraction`` is how much of the beam that excludes:
a probe reporting 40 % dropped is answering a narrower question than the user may think, which
is why the number is a headline readout, not a footnote.

**Two bands, deliberately.** The *incident beam's* own characterization (mean energy, HVL in
aluminium) is a property of the beam, not of whatever shield is in front of it, so it is quoted
over a stack-independent **beam band** ``[δ, endpoint]`` (narrow-beam μ/ρ only — no buildup
floor involved). Only the stack's transmission and the *transmitted* beam's characterization
use the stack-dependent scored band. Without this split, adding a lead layer would silently
"harden" the incident beam it is being tested against.

X-ray tube spectrum — an idealized analytic continuum (§11)
-----------------------------------------------------------
The tube spectrum is **Kramers' thick-target law** (Kramers 1923 — the same model
``engine.beta_dose`` already uses for in-shield bremsstrahlung): photon *number* spectrum
``N(E) ∝ (E_max − E)/E`` for ``E < E_max = e·kVp``, shaped by the user's **inherent
filtration in mm of aluminium equivalent** (how tubes are actually specced, and the stand-in
for anode self-absorption, which Kramers' law does not contain). It is **not a measured
spectrum**: it carries no anode-angle/self-absorption detail and — stated in the UI — **no
tungsten K characteristic lines** (which appear above roughly 70 kVp; their energies and
yields are not in ``data/`` and are not reconstructed from memory, per the no-fabrication
discipline that deferred AmBe and the Cross-Berger kernel). Consequence: the *shape* of
transmission-vs-energy and the beam-hardening *trend* are trustworthy; an absolute HVL in mm
Al is indicative, **not** a QA/compliance number. Only a **tungsten** anode is offered —
Mo/Rh mammography beams are characteristic-line dominated, so a continuum-only model would be
qualitatively wrong there, not merely imprecise.

No silent errors (CLAUDE.md): an off-band probe energy, an unknown material, or a layer
without buildup data raises (:class:`BeamError`, or the loaders' own errors) — never a
quietly substituted coefficient.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from engine import attenuation as _att
from engine import buildup as _bu
from engine import conversion as _conv
from engine import photon_interp as _pi
from engine.dose import (  # `_`-prefixed: dose.py is the single owner of the shield-spec
    CM2_PER_G_TO_M2_PER_KG,  # shape and of the transmission core — reused verbatim (same
    MEV_TO_J,  # convention as engine.neutron_dose), never re-derived here, so a probe number
    QUANTITIES,  # is bit-for-bit the factor the γ dose path applies to a line at that energy.
    SCORING_FLOOR_MEV,
    _normalize_shield,
    _stack_transmission,
)

#: Supported anodes. Tungsten only, deliberately (see module docstring).
ANODES: tuple[str, ...] = ("tungsten",)

#: Generation floor of the Kramers grid (MeV) — the μ/ρ table floor. Bins between this and the
#: scored band's ``E_lo`` are *generated* (so the dropped fraction is honest) but not scored.
GENERATION_FLOOR_MEV = 0.001

#: Default number of spectrum bins (linear in energy, the natural grid for a continuum).
TUBE_BINS = 240

#: Default number of points on the transmission-vs-energy curve (log-spaced).
CURVE_POINTS = 121

#: Tube potentials outside this range are refused rather than silently clamped: below 5 kV
#: essentially nothing escapes any filtration, and above 450 kV the "X-ray tube" framing
#: (and the Kramers thick-target form) stops being the right model.
KVP_MIN, KVP_MAX = 5.0, 450.0


class BeamError(Exception):
    """Loud failure in the beam-probe path — never swallowed, never a fallback number."""


# --------------------------------------------------------------------------------------
# scored band
# --------------------------------------------------------------------------------------


def scored_band(
    layers: Sequence[tuple[str, float]] | None,
    *,
    quantity: Optional[str] = None,
    geometry: Optional[str] = None,
    medium: str = "air",
) -> tuple[float, float]:
    """The ``(E_lo, E_hi)`` MeV window in which this stack's transmission is *scoreable*.

    Intersection of the 10 keV dose-scoring floor δ, every layer's μ/ρ grid, every layer's
    ANS-6.4.3 buildup grid, the ``medium``'s μ/ρ grid, and — when ``quantity`` is given — the
    fluence-to-dose conversion grid for it. Raises if the intersection is empty (a stack whose
    materials share no scoreable energies is a data hole, not a transparent shield).
    """
    lo, hi = SCORING_FLOOR_MEV, math.inf

    def clip(e_grid: Sequence[float]) -> None:
        nonlocal lo, hi
        lo = max(lo, e_grid[0])
        hi = min(hi, e_grid[-1])

    clip(_att.energies(medium))
    for material, _thickness in _normalize_shield(list(layers or [])) or []:
        clip(_att.energies(material))
        clip(_bu.energies(material))  # BuildupError if the layer has no buildup data (§6.5)
    if quantity is not None:
        if quantity not in QUANTITIES:
            raise BeamError(f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}")
        if quantity != "air_kerma":
            clip(_conv.energies(quantity, geometry, "photon"))
    if not (hi > lo):
        raise BeamError(
            f"empty scored band for this stack: E_lo={lo:g} MeV >= E_hi={hi:g} MeV "
            "(the layers' buildup/attenuation grids do not overlap)"
        )
    return lo, hi


def _material_band(material: str) -> tuple[float, float]:
    """One material's scoreable window — what the UI needs to constrain its energy input."""
    return scored_band([(material, 0.0)])


# --------------------------------------------------------------------------------------
# monoenergetic line probe
# --------------------------------------------------------------------------------------


def _layer_rows(layers: Sequence[tuple[str, float]], E_MeV: float) -> list[dict]:
    rows = []
    for material, thickness_cm in layers:
        mu_rho = _pi.interp_mu_rho(material, E_MeV)
        mu_lin = mu_rho * _att.density(material)
        rows.append(
            {
                "material": material,
                "thickness_cm": thickness_cm,
                "mu_rho_cm2_g": mu_rho,
                "mu_cm1": mu_lin,
                "mfp": mu_lin * thickness_cm,
            }
        )
    return rows


def _solve_thickness_for(
    material: str, E_MeV: float, target: float, *, broad: bool
) -> Optional[float]:
    """Thickness (cm) of a *single* ``material`` slab whose transmission equals ``target``.

    Narrow beam is closed form (``ln(1/target)/μ``); broad beam bisects
    ``B(E, μx)·exp(−μx)``. Returns ``None`` when the target is unreachable within the
    buildup fit range (:data:`engine.buildup.MFP_FIT_MAX`) — never an extrapolated number.
    """
    mu_lin = _pi.interp_mu_rho(material, E_MeV) * _att.density(material)
    if not (mu_lin > 0.0):
        raise BeamError(f"non-physical μ={mu_lin:g} cm⁻¹ for {material} at {E_MeV:g} MeV")
    if not broad:
        return math.log(1.0 / target) / mu_lin

    x_hi = _bu.MFP_FIT_MAX / mu_lin  # beyond the fit B is frozen; exp(−μx) still falls
    t = lambda x: _stack_transmission([(material, x)], E_MeV)[0]  # noqa: E731
    if t(x_hi) > target:
        return None
    x_lo = 0.0
    for _ in range(80):
        mid = 0.5 * (x_lo + x_hi)
        if t(mid) > target:
            x_lo = mid
        else:
            x_hi = mid
    return 0.5 * (x_lo + x_hi)


def line_probe(layers, E_MeV: float) -> dict:
    """Probe a layer stack with a single photon energy (the "specific line" mode).

    Returns broad-beam transmission ``B·exp(−Σμx)`` (what the γ dose path applies per line),
    the narrow-beam ``exp(−Σμx)``, the buildup factor that separates them, the total depth in
    mean free paths, a per-layer μ/ρ · μ · mfp breakdown, and the HVL/TVL of the
    **detector-side** material at this energy (narrow-beam closed form + broad-beam solved).

    Transmission multiplies photon *fluence*, so it is **identical for all three dose
    quantities** — no quantity argument, deliberately (that invariance is a regression test
    and a teaching point; the *spectrum-averaged* transmission of a beam is not
    quantity-independent, which is the contrast the tube mode shows).
    """
    stack = _normalize_shield(list(layers or [])) or []
    lo, hi = scored_band(stack)
    E_MeV = float(E_MeV)
    if not (E_MeV > 0.0):
        raise BeamError(f"probe energy must be > 0 MeV; got {E_MeV!r}")
    if E_MeV < lo or E_MeV > hi:
        raise BeamError(
            f"probe energy {E_MeV * 1e3:g} keV is outside this stack's scoreable band "
            f"{lo * 1e3:g}–{hi * 1e3:g} keV (buildup data for "
            f"{', '.join(m for m, _ in stack) or 'the medium'} does not reach it; never "
            "extrapolated, and never B=1 — that would under-count dose, §6.5/§11)"
        )

    broad, total_mfp = _stack_transmission(stack, E_MeV) if stack else (1.0, 0.0)
    narrow = math.exp(-total_mfp)
    detector = stack[-1][0] if stack else None
    return {
        "E_MeV": E_MeV,
        "band_MeV": [lo, hi],
        "transmission": broad,
        "transmission_narrow": narrow,
        "buildup": broad / narrow if narrow > 0 else None,
        "total_mfp": total_mfp,
        "mfp_fit_max": _bu.MFP_FIT_MAX,
        "buildup_capped": total_mfp > _bu.MFP_FIT_MAX,
        "layers": _layer_rows(stack, E_MeV),
        "detector_material": detector,
        "hvl_cm": _solve_thickness_for(detector, E_MeV, 0.5, broad=False) if detector else None,
        "tvl_cm": _solve_thickness_for(detector, E_MeV, 0.1, broad=False) if detector else None,
        "hvl_broad_cm": _solve_thickness_for(detector, E_MeV, 0.5, broad=True)
        if detector
        else None,
    }


def transmission_curve(layers, *, n_points: int = CURVE_POINTS) -> dict:
    """Broad- and narrow-beam transmission of the stack across its whole scored band.

    The teaching plot behind both modes: where the stack is opaque, where it is transparent,
    and where an absorption edge (lead's K-edge at 88 keV) makes transmission jump the
    "wrong" way. Log-spaced in energy; quantity-independent (transmission is a fluence factor).
    """
    stack = _normalize_shield(list(layers or [])) or []
    lo, hi = scored_band(stack)
    grid = np.geomspace(lo, hi, int(n_points))
    broad, narrow = [], []
    for e in grid:
        b, mfp = _stack_transmission(stack, float(e)) if stack else (1.0, 0.0)
        broad.append(b)
        narrow.append(math.exp(-mfp))
    return {
        "E_MeV": [float(e) for e in grid],
        "transmission": broad,
        "transmission_narrow": narrow,
        "band_MeV": [lo, hi],
    }


# --------------------------------------------------------------------------------------
# X-ray tube spectrum
# --------------------------------------------------------------------------------------


def kramers_spectrum(kvp: float, *, n_bins: int = TUBE_BINS) -> tuple[np.ndarray, np.ndarray]:
    """Unfiltered Kramers thick-target photon **number** spectrum of a tungsten tube.

    Returns ``(E_MeV bin centres, photons per bin)`` in **arbitrary units** (only ratios and
    shape are used — absolute output is not modelled, see the module docstring). Intensity
    ``I(E) ∝ (E_max − E)`` (Kramers 1923) ⇒ number ``N(E) = I(E)/E``; ``E_max = e·kVp``, i.e.
    the numerical kV *is* the endpoint in keV. Bins run from :data:`GENERATION_FLOOR_MEV` so
    the soft part that later falls outside the scored band is *counted* as dropped, not hidden.
    """
    kvp = float(kvp)
    if not (KVP_MIN <= kvp <= KVP_MAX):
        raise BeamError(
            f"tube potential {kvp:g} kV outside the modelled {KVP_MIN:g}–{KVP_MAX:g} kV range "
            "(refused rather than silently clamped)"
        )
    e_max = kvp * 1e-3  # kV → MeV endpoint (Duane–Hunt)
    if e_max <= GENERATION_FLOOR_MEV:
        raise BeamError(
            f"tube endpoint {e_max:g} MeV is at/below the {GENERATION_FLOOR_MEV:g} MeV table floor"
        )
    edges = np.linspace(GENERATION_FLOOR_MEV, e_max, int(n_bins) + 1)
    e = 0.5 * (edges[:-1] + edges[1:])
    de = np.diff(edges)
    phi = np.where(e < e_max, (e_max - e) / e, 0.0) * de
    return e, phi


def _narrow_transmission_grid(layers: Sequence[tuple[str, float]], e: np.ndarray) -> np.ndarray:
    """Per-bin narrow-beam ``exp(−Σμx)``. Only μ/ρ is needed (no buildup) — this is the
    filtration / good-geometry-HVL path, where scattered photons are excluded by definition."""
    mfp = np.zeros_like(e)
    for material, thickness_cm in layers:
        mu_lin = _att.density(material) * np.array(
            [_pi.interp_mu_rho(material, float(x)) for x in e]
        )
        mfp += mu_lin * thickness_cm
    return np.exp(-mfp)


def _response(quantity: str, geometry: Optional[str], e: np.ndarray, medium: str) -> np.ndarray:
    """Per-unit-fluence dose response at each bin energy, in SI-ish units (scale cancels).

    ``air_kerma`` → ``E·(μ_en/ρ)_medium``; ``ambient_H10`` / ``effective`` → the ICRP
    fluence-to-dose coefficient. This is what turns a photon-number spectrum into the
    weighting appropriate to the selected quantity.
    """
    if quantity == "air_kerma":
        return np.array(
            [
                float(x) * MEV_TO_J * _pi.interp_muen_rho(medium, float(x)) * CM2_PER_G_TO_M2_PER_KG
                for x in e
            ]
        )
    return np.array([_pi.interp_conversion(quantity, float(x), geometry) for x in e])


def _spectrum_hvl_mm(
    e: np.ndarray, weight: np.ndarray, material: str, target: float = 0.5
) -> Optional[float]:
    """Thickness of ``material`` (in **mm**) that reduces the ``weight``-folded beam to
    ``target`` — the polyenergetic HVL/TVL, **narrow beam** (the good-geometry definition).

    Returns ``None`` if the target is not reached within 500 mm (never extrapolated).
    """
    if not np.any(weight > 0):
        return None
    total = float(np.sum(weight))
    mu_lin = _att.density(material) * np.array([_pi.interp_mu_rho(material, float(x)) for x in e])
    frac = lambda x_cm: float(np.sum(weight * np.exp(-mu_lin * x_cm))) / total  # noqa: E731
    x_hi = 50.0  # cm
    if frac(x_hi) > target:
        return None
    x_lo = 0.0
    for _ in range(80):
        mid = 0.5 * (x_lo + x_hi)
        if frac(mid) > target:
            x_lo = mid
        else:
            x_hi = mid
    return 10.0 * 0.5 * (x_lo + x_hi)


def tube_probe(
    layers,
    *,
    kvp: float,
    filtration_mm_al: float = 2.5,
    anode: str = "tungsten",
    quantity: str = "ambient_H10",
    geometry: Optional[str] = None,
    medium: str = "air",
    n_bins: int = TUBE_BINS,
) -> dict:
    """Fold an idealized X-ray tube beam through a shield stack (the "X-ray tube" mode).

    Pipeline: Kramers continuum at ``kvp`` → narrow-beam **inherent filtration**
    (``filtration_mm_al`` mm of aluminium equivalent, the stand-in for anode self-absorption)
    → that is the *incident* beam → the stack's broad-beam ``B·exp(−Σμx)`` per bin → the
    ``quantity``-weighted transmission.

    Everything is quoted over the stack's :func:`scored_band`; ``dropped_incident_fraction``
    is the air-kerma-weighted share of the incident beam that falls **outside** it (air kerma
    is the only response defined below 10 keV, so it is the honest denominator for the drop).
    Dropped bins are treated as fully absorbed — see the module docstring for the bias.
    """
    if anode not in ANODES:
        raise BeamError(
            f"unsupported anode {anode!r}; only {ANODES} is modelled (Mo/Rh beams are "
            "characteristic-line dominated, which a continuum-only model gets qualitatively "
            "wrong — not shipped rather than shipped wrong)"
        )
    if quantity not in QUANTITIES:
        raise BeamError(f"unknown dose quantity {quantity!r}; expected one of {QUANTITIES}")
    filtration_mm_al = float(filtration_mm_al)
    if filtration_mm_al < 0.0:
        raise BeamError(f"inherent filtration must be >= 0 mm Al; got {filtration_mm_al}")

    stack = _normalize_shield(list(layers or [])) or []
    lo, hi = scored_band(stack, quantity=quantity, geometry=geometry, medium=medium)

    # 1) generation + inherent filtration, on the FULL generated grid (so the drop is honest)
    e_all, phi_raw = kramers_spectrum(kvp, n_bins=n_bins)
    filt = [("aluminium", filtration_mm_al * 0.1)] if filtration_mm_al > 0 else []
    phi_in_all = phi_raw * _narrow_transmission_grid(filt, e_all)

    # 2) the INCIDENT BEAM band — stack-independent, [δ, endpoint], narrow-beam μ/ρ only. The
    #    beam's own mean energy and HVL live here so a lead layer cannot appear to harden the
    #    beam it is being tested against. Air-kerma weighted (the HVL definition, and the only
    #    response defined this low).
    beam_lo = max(SCORING_FLOOR_MEV, _att.energies("aluminium")[0], _att.energies(medium)[0])
    beam_band = e_all >= beam_lo
    kerma_all = _response("air_kerma", None, e_all, medium)
    if not np.any(beam_band & (phi_in_all > 0)):
        raise BeamError(
            f"no photons above the {beam_lo * 1e3:g} keV scoring floor at {kvp:g} kVp with "
            f"{filtration_mm_al:g} mm Al inherent filtration — nothing to characterize"
        )
    phi_beam = phi_in_all[beam_band]
    e_beam = e_all[beam_band]
    w_beam = phi_beam * kerma_all[beam_band]

    # 3) the drop bookkeeping: incident air-kerma weight inside the beam band that falls
    #    OUTSIDE the stack's scored band (§11 — reported, never folded in as if scored).
    in_band = (e_all >= lo) & (e_all <= hi)
    w_beam_total = float(np.sum(w_beam))
    dropped = (
        1.0 - float(np.sum(phi_in_all[in_band] * kerma_all[in_band])) / w_beam_total
        if w_beam_total > 0
        else 1.0
    )

    # 4) the scored fold — the stack's transmission, over the scored band
    e = e_all[in_band]
    phi_in = phi_in_all[in_band]
    if e.size == 0 or not np.any(phi_in > 0):
        raise BeamError(
            f"no incident photons inside the scored band {lo * 1e3:g}–{hi * 1e3:g} keV at "
            f"{kvp:g} kVp with {filtration_mm_al:g} mm Al — the whole beam is below this "
            "stack's buildup floor (nothing scoreable, so nothing reported)"
        )
    t_broad = np.array([_stack_transmission(stack, float(x))[0] if stack else 1.0 for x in e])
    t_narrow = _narrow_transmission_grid(stack, e)
    resp = _response(quantity, geometry, e, medium)
    kerma = kerma_all[in_band]

    w_q = phi_in * resp
    w_k = phi_in * kerma
    phi_out = phi_in * t_broad
    t_quantity = float(np.sum(w_q * t_broad) / np.sum(w_q))
    t_kerma = float(np.sum(w_k * t_broad) / np.sum(w_k))
    t_quantity_narrow = float(np.sum(w_q * t_narrow) / np.sum(w_q))

    # Beam hardening: the INCIDENT beam over its own band vs what came through the stack.
    # Comparing the real (soft-inclusive) incident beam with the transmitted one is the honest
    # statement — the soft part really is absorbed by the stack, which is what hardening means.
    mean_in = float(np.sum(phi_beam * e_beam) / np.sum(phi_beam))
    mean_out = float(np.sum(phi_out * e) / np.sum(phi_out)) if np.sum(phi_out) > 0 else None
    mean_in_scored = float(np.sum(phi_in * e) / np.sum(phi_in))

    return {
        "kvp": float(kvp),
        "anode": anode,
        "filtration_mm_al": filtration_mm_al,
        "quantity": quantity,
        "geometry": geometry,
        "band_MeV": [lo, hi],
        "beam_band_MeV": [beam_lo, float(e_beam[-1])],
        "endpoint_MeV": float(kvp) * 1e-3,
        # transmission of the whole beam (dimensionless — never an absolute rate)
        "transmission": t_quantity,
        "transmission_narrow": t_quantity_narrow,
        "transmission_air_kerma": t_kerma,
        "buildup_effective": t_quantity / t_quantity_narrow if t_quantity_narrow > 0 else None,
        # beam hardening
        "mean_E_in_MeV": mean_in,
        "mean_E_in_scored_MeV": mean_in_scored,
        "mean_E_out_MeV": mean_out,
        "hvl_al_in_mm": _spectrum_hvl_mm(e_beam, w_beam, "aluminium", 0.5),
        "hvl_al_out_mm": _spectrum_hvl_mm(e, phi_out * kerma, "aluminium", 0.5),
        # honesty bookkeeping (§11)
        "dropped_incident_fraction": dropped,
        "n_bins_scored": int(e.size),
        "spectrum": {
            "E_MeV": [float(x) for x in e],
            "phi_in": [float(x) for x in phi_in],
            "phi_out": [float(x) for x in phi_out],
        },
    }
