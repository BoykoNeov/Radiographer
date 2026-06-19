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


def test_nuclides_lists_the_solvable_set():
    # The add-by-name source for the M6b inventory panel: every nuclide the engine
    # can solve (rd's full dataset), as JSON, sorted and de-duplicated, names only.
    import radioactivedecay as rd

    res = json.loads(bridge.nuclides())
    assert res["ok"] is True
    names = res["nuclides"]
    assert isinstance(names, list) and all(isinstance(n, str) for n in names)
    # the canary: the whole solvable set is exposed, not a subset
    assert len(names) == len(set(names)) == len(rd.DEFAULTDATA.nuclides)
    for known in ("Co-60", "Cs-137", "U-238", "Tc-99m"):
        assert known in names
    # naturally ordered (element, mass, state): Co-58 before Co-60 before Cs-137,
    # and not naive string order ("Co-60" < "Co-58" lexically would be wrong)
    assert names.index("Co-58") < names.index("Co-60") < names.index("Cs-137")
    # every listed name actually solves (no phantom entries that would fail add-by-name)
    for name in ("Co-60", "U-238"):
        solved = json.loads(bridge.solve(json.dumps({"nuclides": {name: 1.0}, "unit": "Bq"})))
        assert solved["ok"] is True
        bridge.release(solved["handle"])


def _atoms_at_t0(handle: str, nuclide: str) -> float:
    ev = json.loads(bridge.evaluate(handle, json.dumps({"times_s": [0.0], "axis": "atoms"})))
    assert ev["ok"] is True
    return ev["series"][nuclide][0]


def test_solve_entries_form_mixed_units():
    # The M6b inventory panel sends per-entry units; the engine converts each to atoms
    # (via rd) and merges. One Bateman solve over the union — §9 "selectable unit per isotope".
    import radioactivedecay as rd

    spec = {
        "entries": [
            {"name": "Co-60", "quantity": 1.0e9, "unit": "Bq"},
            {"name": "Cs-137", "quantity": 1.0, "unit": "g"},
        ]
    }
    res = json.loads(bridge.solve(json.dumps(spec)))
    assert res["ok"] is True
    handle = res["handle"]
    try:
        assert "Co-60" in res["nuclides"] and "Cs-137" in res["nuclides"]
        # atom counts must match rd's own per-entry conversion (no fabricated math)
        want_co = float(rd.Inventory({"Co-60": 1.0e9}, "Bq").contents["Co-60"])
        want_cs = float(rd.Inventory({"Cs-137": 1.0}, "g").contents["Cs-137"])
        assert _atoms_at_t0(handle, "Co-60") == pytest.approx(want_co, rel=1e-9)
        assert _atoms_at_t0(handle, "Cs-137") == pytest.approx(want_cs, rel=1e-9)
    finally:
        bridge.release(handle)


def test_solve_entries_duplicate_nuclide_sums_atoms():
    # Same nuclide in two units (Bq + Ci) is physically the sum of atoms (intentional).
    import radioactivedecay as rd

    spec = {
        "entries": [
            {"name": "Co-60", "quantity": 1.0e9, "unit": "Bq"},
            {"name": "Co-60", "quantity": 1.0, "unit": "Ci"},
        ]
    }
    res = json.loads(bridge.solve(json.dumps(spec)))
    assert res["ok"] is True
    handle = res["handle"]
    try:
        want = float(rd.Inventory({"Co-60": 1.0e9}, "Bq").contents["Co-60"]) + float(
            rd.Inventory({"Co-60": 1.0}, "Ci").contents["Co-60"]
        )
        assert _atoms_at_t0(handle, "Co-60") == pytest.approx(want, rel=1e-9)
    finally:
        bridge.release(handle)


def test_solve_entries_form_hp_path():
    # HP precision through the entries form must build rd.InventoryHP and evaluate finite.
    spec = {
        "entries": [{"name": "U-238", "quantity": 1.0, "unit": "Bq"}],
        "precision": "hp",
    }
    res = json.loads(bridge.solve(json.dumps(spec)))
    assert res["ok"] is True
    assert res["hp_recommended"] is True and res["precision"] == "hp"
    handle = res["handle"]
    try:
        lo, hi = res["time_range_s"]
        grid = [0.0, lo, (lo * hi) ** 0.5, hi]
        ev = json.loads(bridge.evaluate(handle, json.dumps({"times_s": grid, "axis": "activity"})))
        assert ev["ok"] is True
        assert all(math.isfinite(v) and v >= 0.0 for col in ev["series"].values() for v in col)
    finally:
        bridge.release(handle)


def test_solve_entries_unknown_nuclide_is_loud():
    res = json.loads(
        bridge.solve(json.dumps({"entries": [{"name": "Zz-000", "quantity": 1.0, "unit": "Bq"}]}))
    )
    assert res["ok"] is False
    assert res["error"]["type"] == "EngineError"
    assert "unknown nuclide" in res["error"]["message"].lower()


def test_solve_entries_empty_is_loud():
    res = json.loads(bridge.solve(json.dumps({"entries": []})))
    assert res["ok"] is False
    assert res["error"]["type"] == "EngineError"


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


def test_decay_heat_round_trip_co60():
    # Solve once, then ask for the decay-heat (W) series over the same handle. 1 g Co-60
    # ≈ 4.18e13 Bq with ~2.60 MeV recoverable/decay → ~17.4 W (the §5 specific-power anchor).
    res = json.loads(
        bridge.solve(json.dumps({"entries": [{"name": "Co-60", "quantity": 1.0, "unit": "g"}]}))
    )
    handle = res["handle"]
    try:
        out = json.loads(bridge.decay_heat(handle, json.dumps({"times_s": [0.0]})))
        assert out["ok"] is True
        assert out["quantity"] == "decay_heat" and out["si_unit"] == "W"
        assert out["total_W"][0] == pytest.approx(17.4, rel=0.03)
        # Breakdown sums to the total; the honesty-register definition crosses the bridge.
        assert out["total_W"][0] == pytest.approx(
            sum(col[0] for col in out["by_nuclide_W"].values()), rel=1e-12
        )
        assert "recoverable" in out["definition"].lower()
    finally:
        bridge.release(handle)


def test_spent_fuel_catalog_lists_validated_vectors():
    # The §8 spent-fuel picker source: inventory comes from the validated data/spent_fuel
    # vectors, returned as ready-to-load entries (per-tonne-HM masses, unit="g").
    cat = json.loads(bridge.spent_fuel_catalog())
    assert cat["ok"] is True
    ids = {s["id"] for s in cat["sources"]}
    assert "pwr-uox-45gwd-4pct" in ids
    ref = next(s for s in cat["sources"] if s["id"] == "pwr-uox-45gwd-4pct")
    assert ref["category"].startswith("Reactor fuel")
    assert ref["referenceTimeS"] == 0.0  # a DISCHARGE vector; cooling = the time control
    assert len(ref["entries"]) > 30 and all(e["unit"] == "g" for e in ref["entries"])
    # The catalog entries actually solve + carry decay heat (the full round trip).
    res = json.loads(bridge.solve(json.dumps({"entries": ref["entries"], "precision": "double"})))
    assert res["ok"] is True and "Cs-137" in res["nuclides"]
    try:
        dh = json.loads(bridge.decay_heat(res["handle"], json.dumps({"times_s": [0.0]})))
        assert dh["ok"] is True and dh["total_W"][0] > 0.0
    finally:
        bridge.release(res["handle"])


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


def test_dose_lines_reconciles_with_dose_total():
    # The §9 per-line γ table endpoint (M6f-2): distance/time-free per-decay coefficients
    # whose Σ(coeff_si·A_n)/4πd² must reconstruct the dose() total EXACTLY (one assembly
    # path). The client multiplies these by the cursor activity + 1/4πd² with zero re-fetch.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        lines = json.loads(bridge.dose_lines(handle, json.dumps({"quantity": "ambient_H10"})))
        assert lines["ok"] is True
        assert lines["quantity"] == "ambient_H10" and lines["si_unit"] == "Sv"
        assert lines["scoring_floor_MeV"] == 0.010
        assert lines["warnings"]  # sub-10-keV X-rays logged as skips (absent from rows)
        co = [ln for ln in lines["lines"] if ln["nuclide"] == "Co-60"]
        assert len(co) >= 2 and all(ln["E_MeV"] >= 0.010 for ln in co)

        t, d = 0.0, 1.0
        ev = json.loads(
            bridge.evaluate(handle, json.dumps({"times_s": [t], "axis": "activity", "unit": "Bq"}))
        )
        acts = {n: ev["series"][n][0] for n in ev["nuclides"]}
        geom = 1.0 / (4.0 * math.pi * d * d)
        recon = geom * sum(ln["coeff_si"] * acts[ln["nuclide"]] for ln in lines["lines"])

        total = json.loads(
            bridge.dose(
                handle,
                json.dumps({"times_s": [t], "quantity": "ambient_H10", "distance_m": d}),
            )
        )
        assert total["ok"] is True
        assert recon == pytest.approx(total["rate_si"][0], rel=1e-9)
    finally:
        bridge.release(handle)


def test_dose_lines_effective_requires_geometry_is_loud():
    # effective dose has no meaning without an ICRP-116 geometry — the per-line endpoint
    # must surface that as a structured error, never a silent default geometry.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(bridge.dose_lines(handle, json.dumps({"quantity": "effective"})))
        assert out["ok"] is False
        assert out["error"]["type"] == "DoseError"
        assert out["error"]["traceback"] is None  # expected domain error
    finally:
        bridge.release(handle)


def test_materials_lists_buildup_flag_and_density():
    # The M6g shield-builder material source: every attenuation material, tagged with
    # has_buildup (the γ-shield gate) + density. The UI filters the γ picker to has_buildup.
    res = json.loads(bridge.materials())
    assert res["ok"] is True
    by_id = {m["id"]: m for m in res["materials"]}
    # the 8 buildup materials span low-Z → high-Z (the aluminium↔lead brems contrast set)
    for m in ("aluminium", "concrete", "copper", "iron", "lead", "tungsten", "water", "air"):
        assert by_id[m]["has_buildup"] is True
        assert by_id[m]["density_g_cm3"] > 0.0
    # PMMA / polyethylene / tissue have attenuation but NO buildup → listed, flagged false
    # (surfaced, not hidden) so the γ picker excludes them rather than erroring out (§11).
    for m in ("pmma", "polyethylene", "tissue_soft"):
        assert by_id[m]["has_buildup"] is False
    # M10: has_removal is the NEUTRON-shield gate. The hydrogenous set attenuates neutrons;
    # water has BOTH flags (works in a shared γ+neutron stack), poly/PMMA are neutron-only.
    for m in ("water", "polyethylene", "pmma"):
        assert by_id[m]["has_removal"] is True
    assert by_id["water"]["has_buildup"] is True and by_id["water"]["has_removal"] is True
    # γ-oriented high-Z shields have NO removal data → neutron-transparent (the neutron path
    # warns + does not silently under-count, §6.3).
    for m in ("lead", "iron", "tungsten", "aluminium"):
        assert by_id[m]["has_removal"] is False
    # lead is denser than aluminium (a sanity tag the UI may display)
    assert by_id["lead"]["density_g_cm3"] > by_id["aluminium"]["density_g_cm3"]


def test_dose_thickness_sweep_reconciles_and_attenuates():
    # The §9 dose-vs-thickness sweep (Design-A): per-nuclide, distance/time-free γ
    # coefficients C_n(x). x=0 == the unshielded baseline EXACTLY; the curve is monotone
    # decreasing through a lead layer; and at any grid thickness Σ C_n(x)·A_n/4πd²
    # reconciles EXACTLY with dose(shield=(material,x)) — the one-assembly-path invariant
    # that stops the swept curve and the breakdown bar from drifting (advisor; M6g #4).
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        xs = [0.0, 0.5, 1.0, 2.0, 4.0]
        sweep = json.loads(
            bridge.dose_thickness(
                handle,
                json.dumps({"material": "lead", "thicknesses_cm": xs, "quantity": "ambient_H10"}),
            )
        )
        assert sweep["ok"] is True
        assert sweep["si_unit"] == "Sv" and sweep["material"] == "lead"
        assert sweep["thicknesses_cm"] == xs
        co = sweep["coeff_by_nuclide"]["Co-60"]
        assert len(co) == len(xs)

        # x=0 is the unshielded baseline: equals an unshielded dose_lines coefficient sum.
        bare = json.loads(bridge.dose_lines(handle, json.dumps({"quantity": "ambient_H10"})))
        bare_co = sum(ln["coeff_si"] for ln in bare["lines"] if ln["nuclide"] == "Co-60")
        assert co[0] == pytest.approx(bare_co, rel=1e-12)

        # monotone decreasing: more lead → strictly less penetrating γ.
        assert all(co[i + 1] < co[i] for i in range(len(co) - 1))

        # reconciliation at x=2 cm: the folded curve == dose(shield=("lead", 2)).
        t, d = 0.0, 1.0
        ev = json.loads(
            bridge.evaluate(handle, json.dumps({"times_s": [t], "axis": "activity", "unit": "Bq"}))
        )
        acts = {n: ev["series"][n][0] for n in ev["nuclides"]}
        geom = 1.0 / (4.0 * math.pi * d * d)
        idx = xs.index(2.0)
        recon = geom * sum(sweep["coeff_by_nuclide"][n][idx] * acts.get(n, 0.0) for n in acts)
        total = json.loads(
            bridge.dose(
                handle,
                json.dumps(
                    {
                        "times_s": [t],
                        "quantity": "ambient_H10",
                        "distance_m": d,
                        "shield": ["lead", 2.0],
                    }
                ),
            )
        )
        assert total["ok"] is True
        assert recon == pytest.approx(total["rate_si"][0], rel=1e-9)
    finally:
        bridge.release(handle)


def test_dose_thickness_no_buildup_material_is_loud():
    # PMMA has attenuation but no ANS-6.4.3 buildup → a γ shield through it is a data hole,
    # not a transparent medium. The sweep must raise loudly, never return a silent number.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.dose_thickness(
                handle, json.dumps({"material": "pmma", "thicknesses_cm": [0.0, 1.0]})
            )
        )
        assert out["ok"] is False  # loud failure (the UI never offers pmma for γ anyway)
    finally:
        bridge.release(handle)


def test_dose_multilayer_order_matters_through_bridge():
    # The layer order is THE silent-error vector: lead→water (detector-side water) and
    # water→lead (detector-side lead) share Σμx but differ in buildup material, so the
    # rendered dose must differ — a reversed-stack bug would make them equal. (advisor)
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        def total(layers):
            out = json.loads(bridge.dose(handle, json.dumps({
                "times_s": [0.0], "quantity": "ambient_H10", "distance_m": 1.0,
                "shield": layers,
            })))
            assert out["ok"] is True
            return out["rate_si"][0]

        lead_water = total([["lead", 1.0], ["water", 5.0]])
        water_lead = total([["water", 5.0], ["lead", 1.0]])
        assert lead_water != water_lead
        # The bare ["lead", 2.0] single-tuple form must still route as one layer.
        single = total([["lead", 2.0]])
        assert single > 0.0
    finally:
        bridge.release(handle)


def test_dose_thickness_multilayer_zero_point_is_rest_of_stack():
    # Under layering, x=0 of the swept layer is the REST OF THE STACK, not unshielded
    # (advisor). Sweeping the detector-side water layer of [lead 1cm, water x] at x=0 must
    # equal the lead-only shield — and at the held thickness it reconciles with the full
    # stack's dose(). The single-layer x=0→None baseline is checked separately (M6g).
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        xs = [0.0, 2.0, 5.0]
        sweep = json.loads(bridge.dose_thickness(handle, json.dumps({
            "layers": [["lead", 1.0], ["water", 5.0]], "sweep_index": 1,
            "thicknesses_cm": xs, "quantity": "ambient_H10",
        })))
        assert sweep["ok"] is True and sweep["material"] == "water"
        co = sweep["coeff_by_nuclide"]["Co-60"]

        # x=0 zero point == lead-only stack (rest-of-stack), NOT unshielded.
        lead_only = json.loads(bridge.dose_lines(handle, json.dumps({
            "quantity": "ambient_H10", "shield": [["lead", 1.0]],
        })))
        lead_co = sum(ln["coeff_si"] for ln in lead_only["lines"] if ln["nuclide"] == "Co-60")
        assert co[0] == pytest.approx(lead_co, rel=1e-12)
        bare = json.loads(bridge.dose_lines(handle, json.dumps({"quantity": "ambient_H10"})))
        bare_co = sum(ln["coeff_si"] for ln in bare["lines"] if ln["nuclide"] == "Co-60")
        assert co[0] < bare_co  # the held lead layer means x=0 is NOT the unshielded value

        # reconciliation at the held thickness x=5: folded curve == dose(full stack).
        t, d = 0.0, 1.0
        ev = json.loads(bridge.evaluate(handle, json.dumps(
            {"times_s": [t], "axis": "activity", "unit": "Bq"})))
        acts = {n: ev["series"][n][0] for n in ev["nuclides"]}
        geom = 1.0 / (4.0 * math.pi * d * d)
        idx = xs.index(5.0)
        recon = geom * sum(sweep["coeff_by_nuclide"][n][idx] * acts.get(n, 0.0) for n in acts)
        full = json.loads(bridge.dose(handle, json.dumps({
            "times_s": [t], "quantity": "ambient_H10", "distance_m": d,
            "shield": [["lead", 1.0], ["water", 5.0]],
        })))
        assert recon == pytest.approx(full["rate_si"][0], rel=1e-9)
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


def test_neutron_dose_round_trip_cf252():
    # Solve 1 µg Cf-252, then ask for the neutron H*(10) dose-rate series over the handle.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Cf-252": 1.0}, "unit": "ug"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.neutron_dose(
                handle,
                json.dumps(
                    {
                        "times_s": [0.0],
                        "source": "Cf-252",
                        "quantity": "ambient_H10",
                        "distance_m": 1.0,
                    }
                ),
            )
        )
        assert out["ok"] is True
        assert out["quantity"] == "ambient_H10" and out["si_unit"] == "Sv"
        assert out["source"] == "Cf-252" and out["parent"] == "Cf-252"
        # Spectrum-averaged h*(10) ≈ 373 pSv·cm² (ICRP-74, read from JANP-4-005 Table 1; fold
        # ~383, within the few-% Maxwellian-vs-ISO-spectrum spread); ~2.5 mrem/h per µg at 1 m.
        assert out["spectrum_avg_coeff_pSv_cm2"] == pytest.approx(373.0, rel=0.05)
        assert out["rate_si"][0] * 3.6e8 == pytest.approx(2.5, rel=0.10)  # Sv/s → mrem/h
        assert out["source_gamma"] is None  # Cf-252 prompt-fission γ unmodeled (§11)
        assert out["neutron_transmission"] == 1.0  # unshielded
    finally:
        bridge.release(handle)


def test_neutron_dose_shield_through_bridge():
    # M10: the neutron dose responds to the shared shield stack. Water (hydrogenous) attenuates;
    # lead is neutron-transparent + warned — the §6.3 "steer to hydrogenous" teaching point.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Cf-252": 1.0}, "unit": "ug"})))
    handle = res["handle"]
    try:
        bare = json.loads(
            bridge.neutron_dose(handle, json.dumps(
                {"times_s": [0.0], "source": "Cf-252", "distance_m": 1.0}))
        )
        water = json.loads(
            bridge.neutron_dose(handle, json.dumps(
                {"times_s": [0.0], "source": "Cf-252", "distance_m": 1.0,
                 "shield": [["water", 20.0]]}))
        )
        lead = json.loads(
            bridge.neutron_dose(handle, json.dumps(
                {"times_s": [0.0], "source": "Cf-252", "distance_m": 1.0,
                 "shield": [["lead", 20.0]]}))
        )
        assert bare["ok"] and water["ok"] and lead["ok"]
        # 20 cm water removes ~7× (Σ_R≈0.104 → exp(−2.08)); the dose drops accordingly.
        assert 0.0 < water["neutron_transmission"] < 0.2
        assert water["rate_si"][0] == pytest.approx(bare["rate_si"][0] * water["neutron_transmission"], rel=1e-9)
        # Lead does NOTHING to neutrons — same dose as bare + a loud steer-to-hydrogenous warning.
        assert lead["neutron_transmission"] == 1.0
        assert lead["rate_si"][0] == pytest.approx(bare["rate_si"][0], rel=1e-12)
        assert any(w.get("reason") == "no_hydrogenous_layer" for w in lead["warnings"])
    finally:
        bridge.release(handle)


def test_neutron_dose_ambe_carries_reaction_gamma():
    # AmBe (M7d): the neutron path lights with the ISO 8529 spectrum (h̄ ≈ 391, TRS-403) AND a
    # non-null source_gamma — the 4.438 MeV reaction γ scored through the γ engine in the SAME
    # Sv quantity (the first non-empty source_gamma path; contrast Cf-252's None above).
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Am-241": 1.0}, "unit": "Ci"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.neutron_dose(
                handle,
                json.dumps(
                    {
                        "times_s": [0.0],
                        "source": "AmBe",
                        "quantity": "ambient_H10",
                        "distance_m": 1.0,
                    }
                ),
            )
        )
        assert out["ok"] is True
        assert out["source"] == "AmBe" and out["parent"] == "Am-241"
        assert out["spectrum_avg_coeff_pSv_cm2"] == pytest.approx(391.0, rel=0.03)
        sg = out["source_gamma"]
        assert sg is not None, "AmBe 4.438 MeV reaction γ must be scored, not dropped"
        assert sg["si_unit"] == "Sv"  # same quantity as the neutron H*(10) → they sum
        assert sg["rate_si"][0] > 0.0
    finally:
        bridge.release(handle)


def test_neutron_dose_source_gamma_failure_does_not_blank_neutron(monkeypatch):
    # M10 symmetric orphan guard at the BRIDGE tier: the good neutron result must survive a
    # failure scoring the source-correlated γ (e.g. a future low-energy reaction γ overflowing
    # the G-P buildup through a thick high-Z shield). Inject a raising GammaDoseModel and assert
    # the neutron dose is still returned, with source_gamma=null + a loud source_gamma_failed
    # warning — never a discarded neutron result.
    def _boom(*a, **k):
        raise OverflowError("(34, 'Result too large')")

    monkeypatch.setattr(bridge, "GammaDoseModel", _boom)
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Am-241": 1.0}, "unit": "Ci"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.neutron_dose(
                handle,
                json.dumps({"times_s": [0.0], "source": "AmBe", "quantity": "ambient_H10",
                            "distance_m": 1.0, "shield": [["lead", 30.0]]}),
            )
        )
        assert out["ok"] is True, "a source-γ failure must NOT discard the neutron dose"
        assert out["rate_si"][0] > 0.0 and out["source"] == "AmBe"
        assert out["source_gamma"] is None
        assert any(w.get("reason") == "source_gamma_failed" for w in out["warnings"])
    finally:
        bridge.release(handle)


def test_neutron_dose_grayed_out_when_parent_absent():
    # The §6.3 gray-out: asking for a Cf-252 neutron dose over an inventory that does NOT
    # contain Cf-252 is a loud structured error (never a silent zero) — the engine cannot
    # scale the tabulated term without the parent's activity.
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Co-60": 1.0e9}, "unit": "Bq"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.neutron_dose(
                handle, json.dumps({"times_s": [0.0], "source": "Cf-252", "distance_m": 1.0})
            )
        )
        assert out["ok"] is False
        assert out["error"]["type"] == "NeutronDoseError"
        assert out["error"]["traceback"] is None  # expected domain error, no traceback
        assert "Cf-252" in out["error"]["message"]
    finally:
        bridge.release(handle)


def test_neutron_dose_unknown_source_is_structured_error():
    res = json.loads(bridge.solve(json.dumps({"nuclides": {"Cf-252": 1.0}, "unit": "ug"})))
    handle = res["handle"]
    try:
        out = json.loads(
            bridge.neutron_dose(
                handle, json.dumps({"times_s": [0.0], "source": "NoSuch-999", "distance_m": 1.0})
            )
        )
        assert out["ok"] is False
        assert out["error"]["type"] == "NeutronDoseError"
        assert out["error"]["traceback"] is None
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


def test_registry_size_tracks_live_handles():
    # The handle-leak canary for invariant #2 (solve-once / release the old handle).
    base = json.loads(bridge.registry_size())["size"]
    r = json.loads(bridge.solve(json.dumps({"nuclides": {"Cs-137": 1.0}, "unit": "Bq"})))
    assert json.loads(bridge.registry_size())["size"] == base + 1
    bridge.release(r["handle"])
    assert json.loads(bridge.registry_size())["size"] == base


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
