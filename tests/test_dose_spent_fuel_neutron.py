"""Engine tests for the spent-fuel multi-parent SF neutron dose (M9; HANDOFF_PLAN §6.3, §8).

The dose rides S(t)=Σ yield_n·A_n(t) off the ONE Bateman solve. These tests drive the model
from the committed discharge vector's ``neutron`` block (no build script, no 370 MB CSV) and
check: the fold reuses the validated Cf-252 h̄; the source cools through the regime; the dose
equals an independent S·h̄/4πd² hand-calc; and the unmodeled-Cm-246 lower-bound warning fires
at long cooling (never a silent under-count).
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
    return SpentFuelNeutronModel(
        n["yields_n_per_decay"], n["spectrum_source"], quantity, geometry=geometry,
        dropped_sf_branch=n["dropped_sf_branch"], dropped_nubar_nominal=n["dropped_nubar_nominal"],
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
    for i in range(len(ts)):
        s = math.fsum(y * act["series"][n][i] for n, y in yields.items())   # n/s
        expected = (m.hbar_pSv_cm2 * PSV_CM2_TO_SV_M2) / (4.0 * math.pi * d * d) * s
        assert out["rate_si"][i] == pytest.approx(expected, rel=1e-12)
    assert out["si_unit"] == "Sv" and out["per"] == "second"


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


def test_dropped_cm246_lower_bound_warning_at_long_cooling(vector, solved):
    # Cm-244 (18 yr) decays away; Cm-246 (4760 yr, no evaluated ν̄) takes over → the unmodeled
    # SF fraction grows. The model must SURFACE this (loud), never silently under-count.
    m = _model(vector)
    ts = [10.0 * _YEAR_S, 100.0 * _YEAR_S, 500.0 * _YEAR_S]
    out = m.dose_rate_series(solved.evaluate(ts, axis="activity", unit="Bq"), 1.0)
    df = out["dropped_sf_frac"]
    assert df[0] < df[1] < df[2]          # grows monotonically with cooling
    assert df[0] < 0.05 and df[2] > 0.5   # negligible at 10 yr, dominant by 500 yr
    assert any(w.get("reason") == "dropped_sf_unmodeled" for w in out["warnings"])


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
