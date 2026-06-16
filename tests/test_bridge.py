"""JSON bridge tests — the contract that crosses the Pyodide boundary.

Pure JSON in / JSON out, stateful via a branded string handle (solve-once stays
in Python; JS holds the handle and asks for a whole time grid at once).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from engine import bridge


def test_solve_returns_handle_and_metadata():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Cs-137": 1.0}, "unit": "Bq"})))
    assert res["ok"] is True
    assert res["handle"].startswith("inv_")
    assert "Cs-137" in res["nuclides"]
    assert res["hp_recommended"] is False
    assert res["time_range_s"][0] < res["time_range_s"][1]
    bridge.release(res["handle"])


def test_full_round_trip_solve_evaluate_chain_release():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Mo-99": 1.0}, "unit": "Bq"})))
    handle = res["handle"]

    ev = json.loads(
        bridge.evaluate(
            handle, json.dumps({"times_s": [0.0, 86400.0], "axis": "activity", "unit": "Bq"})
        )
    )
    assert ev["ok"] is True
    assert ev["axis"] == "activity" and ev["unit"] == "Bq"
    assert len(ev["series"]["Mo-99"]) == 2
    assert ev["series"]["Mo-99"][0] == 1.0  # 1 Bq at t=0

    ch = json.loads(bridge.chain(handle))
    assert ch["ok"] is True
    assert any(n["id"] == "Tc-99m" for n in ch["nodes"])

    rel = json.loads(bridge.release(handle))
    assert rel["ok"] is True
    # using a released handle is a loud error, not a silent no-op
    after = json.loads(bridge.evaluate(handle, json.dumps({"times_s": [0.0]})))
    assert after["ok"] is False
    assert "handle" in after["error"]["message"].lower()


def test_dose_round_trip_co60_air_kerma():
    # Solve once, then ask for a gamma dose-rate time series over the same handle.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.dose(
                handle,
                json.dumps({"times_s": [0.0], "quantity": "air_kerma", "distance_m": 1.0}),
            )
        )
        assert out["ok"] is True
        assert out["quantity"] == "air_kerma" and out["si_unit"] == "Gy"
        # 1 GBq Co-60 at 1 m ≈ 0.308 mGy·m²·GBq⁻¹·h⁻¹ → ~8.5e-8 Gy/s.
        mgy_h = out["rate_si"][0] * 1000.0 * 3600.0
        assert mgy_h == pytest.approx(0.308, rel=0.03)
        assert out["scoring_floor_MeV"] == 0.010
        assert out["warnings"]  # sub-10-keV X-rays logged as skips, not errors
    finally:
        bridge.release(handle)


def test_dose_no_buildup_shield_is_structured_error_not_traceback():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.dose(
                handle,
                json.dumps(
                    {
                        "times_s": [0.0],
                        "quantity": "air_kerma",
                        "distance_m": 1.0,
                        "shield": ["pmma", 1.0],
                    }
                ),
            )
        )
        assert out["ok"] is False
        assert out["error"]["type"] == "BuildupError"
        assert out["error"]["traceback"] is None  # expected domain error, no traceback
    finally:
        bridge.release(handle)


def test_beta_dose_round_trip_with_bremsstrahlung():
    # Solve once, ask for the beta SKIN dose series, plus the secondary bremsstrahlung
    # photon dose when a lead shield stops the beta (§6.2 "more lead = more dose").
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Y-90": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.beta_dose(
                handle,
                json.dumps(
                    {
                        "times_s": [0.0],
                        "distance_m": 1.0,
                        "shield": ["lead", 1.0],
                        "brems_quantity": "air_kerma",
                    }
                ),
            )
        )
        assert out["ok"] is True
        assert out["quantity"] == "beta_skin" and out["si_unit"] == "Gy"
        assert out["scoring_depth_mg_cm2"] == 7.0
        assert out["bremsstrahlung"] is not None  # lead shield → secondary photon dose present
        assert out["bremsstrahlung"]["rate_si"][0] > 0.0
    finally:
        bridge.release(handle)


def test_beta_dose_tritium_zero_with_warning():
    # H-3 betas can't reach the basal layer → zero skin dose, recorded loudly (not silent).
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"H-3": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.beta_dose(handle, json.dumps({"times_s": [0.0], "distance_m": 0.0}))
        )
        assert out["ok"] is True
        assert out["rate_si"][0] == 0.0
        assert any(w.get("nuclide") == "H-3" for w in out["warnings"])
    finally:
        bridge.release(handle)


def test_hp_recommended_flag_surfaces_for_stiff_chain():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"U-238": 1.0}, "unit": "Bq"})))
    assert res["hp_recommended"] is True
    bridge.release(res["handle"])


def test_solve_error_is_structured_not_fabricated():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Zz-000": 1.0}, "unit": "Bq"})))
    assert res["ok"] is False
    assert res["error"]["type"] == "EngineError"
    assert "unknown nuclide" in res["error"]["message"]


def test_evaluate_on_unknown_handle_errors():
    res = json.loads(bridge.evaluate("inv_deadbeef", json.dumps({"times_s": [0.0]})))
    assert res["ok"] is False


def test_bridge_output_is_json_serialisable_text():
    out = bridge.solve(json.dumps({"nuclides": {"Cs-137": 1.0}, "unit": "Bq"}))
    assert isinstance(out, str)
    json.loads(out)  # must parse


# A spread of radionuclides: natural-series heads, medical, industrial, and
# notoriously stiff chains — the cases the per-row noise guard must survive.
_SWEEP_ISOTOPES = [
    "H-3",
    "C-14",
    "Na-22",
    "K-40",
    "Co-60",
    "Sr-90",
    "Tc-99m",
    "Mo-99",
    "I-131",
    "Cs-137",
    "Ba-133",
    "Eu-152",
    "Lu-177",
    "Ir-192",
    "Po-210",
    "Pb-210",
    "Bi-210",
    "Rn-222",
    "Ra-226",
    "Ra-228",
    "Th-228",
    "Th-232",
    "Pa-231",
    "Ac-227",
    "U-235",
    "U-238",
    "Np-237",
    "Pu-239",
    "Pu-241",
    "Am-241",
    "Cm-244",
    "Cf-252",
]


@pytest.mark.parametrize("iso", _SWEEP_ISOTOPES)
def test_no_false_raise_across_isotopes_and_times(iso):
    """The ``N < -noise`` honesty guard must never false-fire on a *valid* solve.

    A false fire would turn a legitimate inventory into a bridge ``ok:false`` — so
    sweep each isotope over a wide log-time grid (its auto-range, extended) on all
    three axes and assert the bridge stays ``ok:true`` with no negative leakage."""
    solved = json.loads(bridge.solve(json.dumps({"nuclides": {iso: 1.0}, "unit": "Bq"})))
    assert solved["ok"] is True, f"{iso} failed to solve: {solved.get('error')}"
    handle = solved["handle"]
    try:
        lo, hi = solved["time_range_s"]
        # Extend the envelope a couple of decades each way to stress the guard.
        grid = [0.0] + list(np.logspace(math.log10(lo) - 2, math.log10(hi) + 2, 120))
        for axis, unit in (("activity", "Bq"), ("atoms", None), ("mass", "g")):
            req = {"times_s": grid, "axis": axis}
            if unit:
                req["unit"] = unit
            ev = json.loads(bridge.evaluate(handle, json.dumps(req)))
            assert ev["ok"] is True, f"{iso}/{axis} raised on valid input: {ev.get('error')}"
            assert all(v >= 0.0 for col in ev["series"].values() for v in col), (
                f"{iso}/{axis} leaked a negative value"
            )
    finally:
        bridge.release(handle)
