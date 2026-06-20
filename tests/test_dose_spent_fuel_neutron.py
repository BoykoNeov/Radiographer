"""Engine tests for the spent-fuel multi-parent SF neutron dose (M9; HANDOFF_PLAN §6.3, §8).

The dose rides S(t)=Σ yield_n·A_n(t) off the ONE Bateman solve. These tests drive the model
from the committed discharge vector's ``neutron`` block (no build script, no 370 MB CSV) and
check: the fold reuses the validated Cf-252 h̄; the source cools through the regime; the dose
equals an independent S·h̄/4πd² hand-calc; with Cm-246/248 ν̄ now sourced the dominant
long-cooling SF emitter is modeled so the unmodeled-ν̄ lower-bound warning no longer fires for
the shipped vector; and the warning MECHANISM still surfaces a large unmodeled branch (never a
silent under-count).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from engine.inventory import SolvedInventory
from engine.neutron_dose import NeutronDoseError, PSV_CM2_TO_SV_M2, fold_spectrum
from engine.spent_fuel_neutron import SpentFuelNeutronModel

_SF_DIR = Path(__file__).resolve().parents[1] / "data" / "spent_fuel"
_YEAR_S = 365.25 * 86400
_POINT = "pwr-uox-45gwd-4pct"


@pytest.fixture(scope="module")
def vector() -> dict:
    return json.loads((_SF_DIR / f"{_POINT}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def solved(vector) -> SolvedInventory:
    spec = [{"name": e["name"], "quantity": e["mass_g_per_tHM"], "unit": "g"} for e in vector["entries"]]
    return SolvedInventory.from_entries(spec, precision="double")


def _model(vector, quantity="ambient_H10", geometry=None) -> SpentFuelNeutronModel:
    n = vector["neutron"]
    an = n.get("alpha_n") or {}
    return SpentFuelNeutronModel(
        n["yields_n_per_decay"], n["spectrum_source"], quantity, geometry=geometry,
        dropped_sf_branch=n["dropped_sf_branch"], dropped_nubar_nominal=n["dropped_nubar_nominal"],
        alpha_n_yields=an.get("yields_n_per_decay"),
        dropped_alpha_branch=an.get("dropped_alpha_branch"),
        nominal_O_yield_per_alpha=an.get("nominal_O_yield_per_alpha", 5.9e-8),
    )


def test_hbar_reuses_validated_cf252_fold(vector):
    # The representative SF spectrum IS Cf-252's, so h̄ must equal the M5-validated Cf-252 fold
    # (~383 pSv·cm² for H*(10)).
    m = _model(vector)
    hbar_cf252, _ = fold_spectrum("Cf-252", "ambient_H10", None)
    assert m.hbar_pSv_cm2 == pytest.approx(hbar_cf252)
    assert 370.0 < m.hbar_pSv_cm2 < 400.0
    assert m.coeff_si == pytest.approx(m.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2)


def test_dose_equals_independent_hand_calc(vector, solved):
    m = _model(vector)
    d = 1.0
    ts = [0.0, 10.0 * _YEAR_S]
    act = solved.evaluate(ts, axis="activity", unit="Bq")
    out = m.dose_rate_series(act, d)
    yields = vector["neutron"]["yields_n_per_decay"]
    an_yields = vector["neutron"]["alpha_n"]["yields_n_per_decay"]
    for i in range(len(ts)):
        s_sf = math.fsum(y * act["series"][n][i] for n, y in yields.items())          # n/s
        s_an = math.fsum(y * act["series"][n][i] for n, y in an_yields.items())        # n/s
        k = (m.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2) / (4.0 * math.pi * d * d)
        assert out["rate_si"][i] == pytest.approx(k * (s_sf + s_an), rel=1e-12)
        # The reported SF/(α,n) split must add back to the total and match each term.
        assert out["rate_si_sf"][i] == pytest.approx(k * s_sf, rel=1e-12)
        assert out["rate_si_alpha_n"][i] == pytest.approx(k * s_an, rel=1e-12)
        assert out["rate_si"][i] == pytest.approx(out["rate_si_sf"][i] + out["rate_si_alpha_n"][i], rel=1e-12)
    assert out["si_unit"] == "Sv" and out["per"] == "second"


def test_alpha_n_strictly_adds_and_grows_at_century(vector, solved):
    # M12: (α,n) is a strictly positive addition to the SF source (best estimate > SF-only lower
    # bound), and its SHARE grows from ~10 yr to ~100 yr as Am-241 (no SF, strong (α,n)) ingrows
    # from Pu-241 — the physical signature that makes (α,n) worth modeling at decade+ cooling.
    n = vector["neutron"]
    sf_only = SpentFuelNeutronModel(n["yields_n_per_decay"], n["spectrum_source"], "ambient_H10")
    full = _model(vector)
    ts = [10.0 * _YEAR_S, 100.0 * _YEAR_S]
    act = solved.evaluate(ts, axis="activity", unit="Bq")
    o_sf = sf_only.dose_rate_series(act, 1.0)
    o = full.dose_rate_series(act, 1.0)
    for i in range(len(ts)):
        assert o["rate_si"][i] > o_sf["rate_si"][i]      # (α,n) strictly adds to the dose
        assert o["rate_si_alpha_n"][i] > 0.0
    frac10 = o["rate_si_alpha_n"][0] / o["rate_si"][0]
    frac100 = o["rate_si_alpha_n"][1] / o["rate_si"][1]
    assert frac100 > frac10                              # Am-241 ingrowth raises the (α,n) share
    assert frac100 > 0.1                                 # ~20% at a century — a real correction


def test_source_cools_through_the_regime(vector, solved):
    m = _model(vector)
    ts = [0.0, 10.0 * _YEAR_S, 100.0 * _YEAR_S]
    out = m.dose_rate_series(solved.evaluate(ts, axis="activity", unit="Bq"), 1.0)
    r = out["rate_si"]
    assert r[0] > r[1] > r[2] > 0.0


def test_distance_is_inverse_square(vector, solved):
    m = _model(vector)
    act = solved.evaluate([10.0 * _YEAR_S], axis="activity", unit="Bq")
    r1 = m.dose_rate_series(act, 1.0)["rate_si"][0]
    r2 = m.dose_rate_series(act, 2.0)["rate_si"][0]
    assert r1 / r2 == pytest.approx(4.0, rel=1e-9)


def test_cm246_now_modeled_so_no_lower_bound_warning_at_long_cooling(vector, solved):
    # Cm-246/248 ν̄ are now SOURCED (Holden & Zucker BNL-36467), so once Cm-244 (18 yr) decays the
    # dominant long-cooling emitter Cm-246 (4760 yr) is in the dose — NOT dropped. The unmodeled-ν̄
    # SF fraction therefore stays negligible across the cooling range and the lower-bound ν̄-gap
    # warning no longer fires for the shipped vector. (This is the deliverable; the orthogonal
    # (α,n) lower-bound caveat in the vector's neutron_caveat is unaffected.)
    m = _model(vector)
    ts = [100.0 * _YEAR_S, 500.0 * _YEAR_S, 1.0e4 * _YEAR_S, 1.0e5 * _YEAR_S]
    out = m.dose_rate_series(solved.evaluate(ts, axis="activity", unit="Bq"), 1.0)
    assert max(out["dropped_sf_frac"]) < 0.01     # was >0.5 by 500 yr before Cm-246 was modeled
    assert not any(w.get("reason") == "dropped_sf_unmodeled" for w in out["warnings"])


def test_dropped_sf_warning_mechanism_still_fires_for_a_large_unmodeled_branch(vector, solved):
    # Coverage for the §11 surfacing PATH itself: if a (future) dataset carried a genuinely large
    # SF emitter with no evaluated ν̄, the model must still loudly flag the under-count. Inject a
    # synthetic dropped branch on Cm-244 (present in the series) large enough to dominate, and
    # confirm the dropped fraction and the loud warning both appear.
    n = vector["neutron"]
    m = SpentFuelNeutronModel(
        n["yields_n_per_decay"], n["spectrum_source"], "ambient_H10",
        dropped_sf_branch={"Cm-244": 1.0e-3}, dropped_nubar_nominal=3.3,
    )
    out = m.dose_rate_series(solved.evaluate([10.0 * _YEAR_S], axis="activity", unit="Bq"), 1.0)
    assert out["dropped_sf_frac"][0] > 0.05
    assert out["dropped_frac"][0] > 0.05
    assert any(w.get("reason") == "dropped_unmodeled_neutron" for w in out["warnings"])


def test_effective_requires_geometry(vector):
    with pytest.raises(NeutronDoseError):
        _model(vector, quantity="effective", geometry=None)
    # AP effective folds fine and differs from H*(10).
    m = _model(vector, quantity="effective", geometry="AP")
    assert m.hbar_pSv_cm2 > 0.0


def test_missing_emitter_is_loud(vector, solved):
    # A yield nuclide absent from the activity series must raise, not silently zero out.
    m = _model(vector)
    act = solved.evaluate([0.0], axis="activity", unit="Bq")
    act["series"].pop("Cm-244")
    with pytest.raises(NeutronDoseError):
        m.dose_rate_series(act, 1.0)


# --- M10 neutron shielding: the SAME removal-cross-section gate as the single-source path ----

def test_water_shield_attenuates_spent_fuel_neutron_dose(vector, solved):
    # A hydrogenous shield attenuates the SF neutron dose by the removal scalar T_n; h̄ is
    # unchanged (no spectrum hardening), so the whole series scales by exactly exp(−Σ_R·x).
    from engine import neutron_removal as nr

    n = vector["neutron"]
    act = solved.evaluate([10.0 * _YEAR_S], axis="activity", unit="Bq")
    bare = _model(vector).dose_rate_series(act, 1.0)["rate_si"][0]
    an = n["alpha_n"]
    shielded_model = SpentFuelNeutronModel(
        n["yields_n_per_decay"], n["spectrum_source"], "ambient_H10",
        dropped_sf_branch=n["dropped_sf_branch"], dropped_nubar_nominal=n["dropped_nubar_nominal"],
        alpha_n_yields=an["yields_n_per_decay"], dropped_alpha_branch=an["dropped_alpha_branch"],
        nominal_O_yield_per_alpha=an["nominal_O_yield_per_alpha"],
        shield=[("water", 20.0)],
    )
    out = shielded_model.dose_rate_series(act, 1.0)
    T = math.exp(-nr.sigma_r_cm1("water") * 20.0)
    assert shielded_model.T_n == pytest.approx(T, rel=1e-12)
    assert out["neutron_transmission"] == pytest.approx(T, rel=1e-12)
    assert out["rate_si"][0] == pytest.approx(bare * T, rel=1e-12)


def test_lead_shield_does_not_attenuate_spent_fuel_and_warns(vector):
    # γ-oriented stack → T_n=1 + loud "steer to hydrogenous" warning (never a silent under-count).
    n = vector["neutron"]
    m = SpentFuelNeutronModel(
        n["yields_n_per_decay"], n["spectrum_source"], "ambient_H10", shield=[("lead", 15.0)],
    )
    assert m.T_n == 1.0
    assert any(w.get("reason") == "no_hydrogenous_layer" for w in m.warnings)
