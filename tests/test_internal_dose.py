"""Regression suite for the bundled internal (committed) dose coefficients (§M13, §11).

The datasets are the project (CLAUDE.md) — this lands with the data. Pillars:

1. **Structural** — schema/units/population/progeny invariants; every e(50) positive & in a
   physical Sv/Bq range; inhalation ``default_type`` is among the tabulated types.
2. **Anchor goldens (transcription fidelity)** — the validated micro-slice values, read from
   ICRP-119 (the §12 trap is transcription, so the goldens ARE the check). Five actinides ×
   both populations × both routes.
3. **Cross-table consistency** — the same check the build enforces, re-asserted on shipped
   data: worker↔public ingestion reconciles by the f1 ratio (Po-210: public f1 0.5 / worker
   f1 0.1 → exactly 5×; matched-f1 actinides → 1×). This is the independent-typesetting
   transcription check.
4. **Engine semantics** — parent-only progeny convention enforced (a "+"-bundled file is
   rejected); three coverage states (covered / noble-gas N/A / uncovered) with the lower-bound
   flag set ONLY by uncovered; the fold ``Σ e_n·A_n(t)`` reconciles exactly and yields a
   committed scalar Sv (``per is None``); no silent errors (unknown route/population/type and
   missing activity series all raise).

Trust boundary (honesty): the anchors prove transcription fidelity, NOT methodology — ICRP-119
is the sole methodology source (advisor, §M13). The cross-table check exploits that ICRP-119
typesets the worker (Annex A) and public (Annexes F/G) numbers independently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import internal_dose as idose

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "internal_dose"

MICRO_SLICE = ("Po-210", "Ra-226", "U-238", "Pu-239", "Am-241")

# Validated ICRP-119 anchors (Sv/Bq). ingestion = e; inhalation = DEFAULT-type e.
# worker = ICRP-68 Annex A (5 µm); public_adult = ICRP-72 Annexes F/G (1 µm, Adult).
ANCHORS = {
    "worker": {
        "Po-210": {"ingestion": 2.4e-07, "inhalation": 2.2e-06},  # M
        "Ra-226": {"ingestion": 2.8e-07, "inhalation": 2.2e-06},  # M
        "U-238":  {"ingestion": 4.4e-08, "inhalation": 1.6e-06},  # M (5 µm)
        "Pu-239": {"ingestion": 2.5e-07, "inhalation": 3.2e-05},  # M
        "Am-241": {"ingestion": 2.0e-07, "inhalation": 2.7e-05},  # M
    },
    "public_adult": {
        "Po-210": {"ingestion": 1.2e-06, "inhalation": 3.3e-06},  # M
        "Ra-226": {"ingestion": 2.8e-07, "inhalation": 3.5e-06},  # M
        "U-238":  {"ingestion": 4.5e-08, "inhalation": 2.9e-06},  # M
        "Pu-239": {"ingestion": 2.5e-07, "inhalation": 5.0e-05},  # M
        "Am-241": {"ingestion": 2.0e-07, "inhalation": 4.2e-05},  # M
    },
}


def _load_raw(population: str) -> dict:
    return json.loads((CANON / f"{population}.json").read_text(encoding="utf-8"))


# -- Pillar 1: structural ---------------------------------------------------

@pytest.mark.parametrize("population", idose.POPULATIONS)
def test_structural_invariants(population):
    d = _load_raw(population)
    assert d["schema_version"] == idose.SCHEMA_VERSION
    assert d["population"] == population
    assert d["units"] == "Sv_per_Bq"
    assert d["progeny_convention"] == "parent_only_in_vivo_ingrowth"
    for nuc, rec in d["coefficients"].items():
        for route in ("ingestion", "inhalation"):
            if route not in rec:
                continue
            vals = ([rec[route]["e_Sv_Bq"]] if route == "ingestion"
                    else list(rec[route]["types"].values()))
            for v in vals:
                assert 1e-13 < v < 1e-3, f"{population}/{nuc}/{route}: {v} out of range"
        if "inhalation" in rec:
            inh = rec["inhalation"]
            assert inh["default_type"] in inh["types"], f"{nuc}: default_type not tabulated"
            assert all(t in idose.ABSORPTION_TYPES for t in inh["types"])


@pytest.mark.parametrize("population", idose.POPULATIONS)
def test_loader_validates_and_caches(population):
    a = idose.load(population)
    b = idose.load(population)
    assert a is b  # lru_cache
    assert set(a["coefficients"]) == set(MICRO_SLICE)


# -- Pillar 2: anchor goldens ----------------------------------------------

@pytest.mark.parametrize("population", idose.POPULATIONS)
@pytest.mark.parametrize("nuclide", MICRO_SLICE)
def test_anchor_values(population, nuclide):
    for route in ("ingestion", "inhalation"):
        got = idose.coefficient(nuclide, route, population)
        want = ANCHORS[population][nuclide][route]
        assert got == want, f"{population}/{nuclide}/{route}: {got} != {want}"


def test_default_type_is_M_for_actinides():
    # ICRP-recommended default for unspecified actinide chemical form is Type M; the shipped
    # default-type inhalation value must equal the Type-M value.
    for population in idose.POPULATIONS:
        d = _load_raw(population)
        for nuc in MICRO_SLICE:
            inh = d["coefficients"][nuc]["inhalation"]
            assert inh["default_type"] == "M"
            assert idose.coefficient(nuc, "inhalation", population) == inh["types"]["M"]


# -- Pillar 3: cross-table consistency (transcription fidelity) -------------

def test_ingestion_f1_ratio_worker_vs_public():
    w = _load_raw("worker")["coefficients"]
    p = _load_raw("public_adult")["coefficients"]
    for nuc in MICRO_SLICE:
        we, wf = w[nuc]["ingestion"]["e_Sv_Bq"], w[nuc]["ingestion"]["f1"]
        pe, pf = p[nuc]["ingestion"]["e_Sv_Bq"], p[nuc]["ingestion"]["f1"]
        assert pe / we == pytest.approx(pf / wf, rel=0.10), f"{nuc}: f1-ratio mismatch"


def test_every_public_inhalation_type_has_a_worker_analog():
    # No public-adult inhalation type ships without a worker counterpart to cross-validate it
    # (the build enforces public 1µm ≈ worker 1µm per type; this guards the shipped invariant
    # that public types ⊆ worker types — uncross-checkable types were dropped, §M13/advisor).
    w = _load_raw("worker")["coefficients"]
    p = _load_raw("public_adult")["coefficients"]
    for nuc in MICRO_SLICE:
        wt = set(w[nuc]["inhalation"]["types"])
        pt = set(p[nuc]["inhalation"]["types"])
        assert pt <= wt, f"{nuc}: public inhalation types {pt} not all in worker {wt}"


def test_po210_population_difference_is_the_f1_ratio():
    # The teaching point that motivates shipping both populations: Po-210 ingestion differs by
    # exactly the f1 ratio (public dietary f1 0.5 vs worker f1 0.1 → 5×).
    w = idose.coefficient("Po-210", "ingestion", "worker")
    p = idose.coefficient("Po-210", "ingestion", "public_adult")
    assert p / w == pytest.approx(5.0, rel=1e-6)


# -- Pillar 4: engine semantics --------------------------------------------

def _evaluate_stub(series: dict[str, list[float]], times=(0.0, 1.0)) -> dict:
    return {"axis": "activity", "unit": "Bq", "times_s": list(times), "series": series}


def test_three_coverage_states():
    # covered (actinides) + noble-gas N/A (Kr-85) + uncovered (Cs-137, not in the curated set).
    model = idose.InternalDoseModel(
        ["Pu-239", "Am-241", "Kr-85", "Cs-137"], "inhalation", "worker"
    )
    assert set(model.covered) == {"Pu-239", "Am-241"}
    assert model.noble_gas_na == ["Kr-85"]
    assert model.uncovered == ["Cs-137"]


def test_lower_bound_only_from_uncovered_not_noble_gas():
    series = _evaluate_stub({"Pu-239": [1e6, 1e6], "Kr-85": [1e9, 1e9]})
    out = idose.InternalDoseModel(["Pu-239", "Kr-85"], "inhalation", "worker") \
        .committed_dose_series(series)
    # Kr-85 is N/A, not uncovered → NOT a lower bound.
    assert out["lower_bound"] is False
    assert out["noble_gas_na"] == ["Kr-85"]
    assert any(w["reason"] == "noble_gas_no_intake_pathway" for w in out["warnings"])

    series2 = _evaluate_stub({"Pu-239": [1e6, 1e6], "Cs-137": [1e9, 1e9]})
    out2 = idose.InternalDoseModel(["Pu-239", "Cs-137"], "inhalation", "worker") \
        .committed_dose_series(series2)
    assert out2["lower_bound"] is True
    assert any(w["reason"] == "uncovered_nuclides" for w in out2["warnings"])


def test_fold_reconciles_and_is_a_committed_scalar():
    # Σ e_n·A_n(t). Pu-239 1e6 Bq + Am-241 5e5 Bq, worker inhalation (Type M).
    series = _evaluate_stub({"Pu-239": [1e6, 2e6], "Am-241": [5e5, 5e5]})
    model = idose.InternalDoseModel(["Pu-239", "Am-241"], "inhalation", "worker")
    out = model.committed_dose_series(series)
    e_pu, e_am = 3.2e-05, 2.7e-05
    assert out["committed_si"][0] == pytest.approx(e_pu * 1e6 + e_am * 5e5)
    assert out["committed_si"][1] == pytest.approx(e_pu * 2e6 + e_am * 5e5)
    # committed scalar Sv, NOT a rate:
    assert out["quantity"] == "committed_effective_E50"
    assert out["si_unit"] == "Sv"
    assert out["per"] is None
    assert out["lower_bound"] is False


def test_ingestion_vs_inhalation_differ():
    # Pu-239 inhalation ≫ ingestion (gut barrier f1 0.0005) — sanity that route is wired.
    inh = idose.coefficient("Pu-239", "inhalation", "worker")
    ing = idose.coefficient("Pu-239", "ingestion", "worker")
    assert inh / ing > 100


def test_absorption_type_override():
    # U-238 has F/M/S; an explicit type overrides the default (M).
    s = idose.coefficient("U-238", "inhalation", "worker", absorption_type="S")
    m = idose.coefficient("U-238", "inhalation", "worker")
    assert s == 6.3e-06 and m == 1.6e-06


# -- no silent errors -------------------------------------------------------

def test_unknown_route_population_type_raise():
    with pytest.raises(idose.InternalDoseError):
        idose.coefficient("Pu-239", "dermal", "worker")
    with pytest.raises(idose.InternalDoseError):
        idose.load("astronaut")
    with pytest.raises(idose.InternalDoseError):
        idose.coefficient("Ra-226", "inhalation", "worker", absorption_type="F")  # Ra is M-only


def test_missing_activity_series_raises():
    series = _evaluate_stub({"Pu-239": [1e6, 1e6]})  # Am-241 series missing
    model = idose.InternalDoseModel(["Pu-239", "Am-241"], "inhalation", "worker")
    with pytest.raises(idose.InternalDoseError):
        model.committed_dose_series(series)


def test_non_activity_evaluate_rejected():
    bad = {"axis": "mass", "unit": "g", "times_s": [0.0], "series": {"Pu-239": [1.0]}}
    model = idose.InternalDoseModel(["Pu-239"], "inhalation", "worker")
    with pytest.raises(idose.InternalDoseError):
        model.committed_dose_series(bad)


def test_parent_only_convention_enforced(tmp_path):
    # A "+"-bundled file (equilibrium progeny) would double-count → loader must reject it.
    bad = _load_raw("worker")
    bad["progeny_convention"] = "equilibrium_plus_bundled"
    (tmp_path / "worker.json").write_text(json.dumps(bad), encoding="utf-8")
    idose.set_data_root(tmp_path)
    try:
        with pytest.raises(idose.InternalDoseError, match="parent-only"):
            idose.load("worker")
    finally:
        idose.set_data_root(idose._DEFAULT_ROOT)
