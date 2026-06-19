"""Decay-heat (thermal power) regression suite (HANDOFF_PLAN.md §5, §10).

Decay heat "falls straight out of the decay energies" — but two traps decide whether
it is right, and a β-γ anchor catches NEITHER (advisor):

1. **Alpha recoil.** ICRP-107's α energy is the *particle* energy; the locally-deposited
   decay energy is ``Q_α = E_α·A/(A−4)`` (the ~2 % heavy-recoil nucleus stops locally).
   The discriminator is a near-pure-α emitter: **Pu-238** lands 0.4 % from the published
   0.57 W/g *with* recoil and ~2 % low *without* it, so the tight Pu-238 tolerance below
   is what proves the recoil term is present.
2. **β double-count.** ``emissions`` exposes β two ways — discrete ``betas`` (per-branch
   ``E_mean``) and the continuous ``beta_spectra`` (∫E·I dE = MeV/decay). The model uses
   ONLY the discrete path; ``Co-60`` (β-γ) at 0.3 % confirms the channel is counted once.

Published anchors (FETCHED, not reconstructed — en.wikipedia.org, June 2026):
- **Pu-238: ~0.57 W/g**, decay energy Q_α = **5.593 MeV** (= particle + recoil).
- **Po-210: ~140 W/g** (precise refs ~141), Q_α = **5.40745 MeV**, T½ 138.376 d.
- **Co-60: ~17.4 W/g** (β-γ), the no-recoil channel-sum check.

Every anchor is W/g of a 1 g pure load: the engine's own λ (activity = λ·N) folded with
the recoverable energy per decay — exercising the whole solve→activity→heat chain.
"""

from __future__ import annotations

import pytest

from engine.decay_heat import (
    MEV_TO_J,
    DecayHeatError,
    DecayHeatModel,
    recoverable_energy_MeV,
)
from engine.inventory import SolvedInventory


def _specific_power_W_per_g(nuclide: str) -> float:
    """Decay heat of a 1 g pure load at t=0 (W/g), through the full rendered path."""
    inv = SolvedInventory.from_entries([{"name": nuclide, "quantity": 1.0, "unit": "g"}])
    activities = inv.evaluate([0.0], axis="activity", unit="Bq")
    model = DecayHeatModel(inv.names)
    return model.heat_series(activities)["total_W"][0]


# --- the alpha-recoil discriminator (the test a β-γ anchor cannot do) -----------------

def test_pu238_specific_power_requires_alpha_recoil():
    # Published 0.57 W/g (Wikipedia). With recoil the engine lands ~0.568 (0.4 %); WITHOUT
    # recoil it would be ~0.558 (≈2 % low) and fail this tolerance — so passing IS the proof
    # the Q_α = E_α·A/(A−4) recoil term is present.
    w = _specific_power_W_per_g("Pu-238")
    assert w == pytest.approx(0.567, rel=0.015)

    ch = recoverable_energy_MeV("Pu-238")
    # Total recoverable energy reproduces the FETCHED Q_α = 5.593 MeV (particle 5.486 +
    # recoil 0.094 + photon/electron) — the recoil increment must be non-trivial and signed up.
    assert ch["total"] == pytest.approx(5.593, rel=2e-3)
    assert ch["alpha_recoil"] == pytest.approx(ch["alpha"] * 4.0 / (238 - 4), rel=1e-9)
    assert ch["alpha_recoil"] > 0.0


def test_po210_near_pure_alpha():
    w = _specific_power_W_per_g("Po-210")
    # The classic "1 g → 140 W"; first-principles (T½ 138.376 d, Q 5.4075) gives ~144,
    # i.e. the 140 figure is 2-sig-fig rounded — anchor with the wider register accordingly.
    assert w == pytest.approx(142.0, rel=0.04)
    ch = recoverable_energy_MeV("Po-210")
    assert ch["total"] == pytest.approx(5.40745, rel=1e-3)  # FETCHED Q_α


# --- the β-γ anchor (counts the discrete-β channel exactly once) ----------------------

def test_co60_beta_gamma_no_double_count():
    w = _specific_power_W_per_g("Co-60")
    assert w == pytest.approx(17.4, rel=0.03)
    ch = recoverable_energy_MeV("Co-60")
    # Co-60 is β-γ: ~2.50 MeV of photons (two lines) + ~0.097 MeV mean β, no α.
    assert ch["alpha"] == 0.0
    assert ch["photon"] == pytest.approx(2.504, rel=5e-3)
    assert 0.09 < ch["beta"] < 0.10
    # The discrete β mean (~0.0965), counted ONCE — not the continuous-spectrum integral too.
    assert ch["total"] == pytest.approx(ch["beta"] + ch["photon"] + ch["electron"], rel=1e-12)


# --- structure / no-silent-errors -----------------------------------------------------

def test_stable_endproduct_is_zero_heat_not_a_hole():
    # Ni-60 (stable Co-60 daughter) has no emission file: legitimately zero heat, the
    # dose.py convention — NOT a raised data hole (it carries zero activity in any case).
    ch = recoverable_energy_MeV("Ni-60")
    assert ch["total"] == 0.0


def test_coeff_is_energy_times_mev_to_j():
    model = DecayHeatModel(["Co-60"])
    expected = recoverable_energy_MeV("Co-60")["total"] * MEV_TO_J
    assert model.coeff_w_per_bq["Co-60"] == pytest.approx(expected, rel=1e-12)


def test_breakdown_sums_to_total_over_a_chain():
    # Sr-90 → Y-90 (β-β): the per-nuclide breakdown must sum to total_W at every time.
    inv = SolvedInventory.from_entries([{"name": "Sr-90", "quantity": 1.0, "unit": "Ci"}])
    activities = inv.evaluate([0.0, 1.0e7, 1.0e9], axis="activity", unit="Bq")
    out = DecayHeatModel(inv.names).heat_series(activities)
    for j in range(len(out["times_s"])):
        assert out["total_W"][j] == pytest.approx(
            sum(col[j] for col in out["by_nuclide_W"].values()), rel=1e-12
        )
    assert "antineutrino" in out["definition"].lower()


def test_heat_series_rejects_non_activity_result():
    inv = SolvedInventory.from_entries([{"name": "Co-60", "quantity": 1.0, "unit": "Ci"}])
    atoms = inv.evaluate([0.0], axis="atoms")
    with pytest.raises(DecayHeatError):
        DecayHeatModel(inv.names).heat_series(atoms)


def test_missing_activity_series_raises_not_silent_zero():
    model = DecayHeatModel(["Co-60"])
    bogus = {"axis": "activity", "unit": "Bq", "times_s": [0.0], "series": {}}
    with pytest.raises(DecayHeatError):
        model.heat_series(bogus)
