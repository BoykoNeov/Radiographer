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
# M13 fission/activation-product batch (default-type-only inhalation).
FISSION_PRODUCTS = ("Co-60", "Se-79", "Sr-90", "Tc-99", "Ru-106", "Cs-134", "Cs-137", "Ce-144")
# M13 actinide-expansion batch (all cross-checkable tabulated types; 300-DPI crop-verified).
# Grows by element. Np ships M only (worker tabulates M); Pu ships M & S (worker has no F).
ACTINIDE_EXPANSION = ("U-234", "U-235", "U-236",
                      "Np-237", "Pu-238", "Pu-240", "Pu-241", "Pu-242",
                      "Am-243", "Cm-242", "Cm-243", "Cm-244", "Cm-245", "Cm-246")
# M13 non-actinide expansion (default-type only, like the fission products). The shipped worker
# 5 µm value was 300-DPI crop-read twice (the one column the build never cross-checks).
NON_ACTINIDE = ("Pb-210", "Sb-125", "Sn-126", "Pm-147", "Eu-154", "Eu-155")
CURATED = MICRO_SLICE + FISSION_PRODUCTS + ACTINIDE_EXPANSION + NON_ACTINIDE

# ICRP default absorption type per element (ICRP-119 Annex E "unspecified compounds" catch-all)
# — what the engine folds, so the anchor below is this type's value. NOT chosen by value/memory.
DEFAULT_TYPE = {
    # Po-210 = F: Annex E Table E.1 Polonium "Unspecified compounds" is Type F (f1 0.1). The
    # original micro-slice shipped M ("commonly-cited"); the M13 non-actinide re-verify caught the
    # rule violation and corrected it to F (folds 7.1E-07 worker / 6.0E-07 public). See PROVENANCE.
    "Po-210": "F", "Ra-226": "M", "U-238": "M", "Pu-239": "M", "Am-241": "M",
    "Co-60": "M", "Se-79": "F", "Sr-90": "F", "Tc-99": "F",
    "Ru-106": "F", "Cs-134": "F", "Cs-137": "F", "Ce-144": "M",
    "U-234": "M", "U-235": "M", "U-236": "M",  # uranium catch-all = Type M (same element as U-238)
    "Np-237": "M", "Pu-238": "M", "Pu-240": "M", "Pu-241": "M", "Pu-242": "M",
    "Am-243": "M", "Cm-242": "M", "Cm-243": "M", "Cm-244": "M", "Cm-245": "M", "Cm-246": "M",
    # Non-actinides (Annex E: Pb F, Sb F, Sn F, Pm M, Eu M):
    "Pb-210": "F", "Sb-125": "F", "Sn-126": "F", "Pm-147": "M", "Eu-154": "M", "Eu-155": "M",
}

# Validated ICRP-119 anchors (Sv/Bq). ingestion = e; inhalation = DEFAULT-type e.
# worker = ICRP-68 Annex A (5 µm); public_adult = ICRP-72 Annexes F/G (1 µm, Adult).
ANCHORS = {
    "worker": {
        "Po-210": {"ingestion": 2.4e-07, "inhalation": 7.1e-07},  # F (corrected from M; Annex E)
        "Ra-226": {"ingestion": 2.8e-07, "inhalation": 2.2e-06},  # M
        "U-238":  {"ingestion": 4.4e-08, "inhalation": 1.6e-06},  # M (5 µm)
        "Pu-239": {"ingestion": 2.5e-07, "inhalation": 3.2e-05},  # M
        "Am-241": {"ingestion": 2.0e-07, "inhalation": 2.7e-05},  # M
        "Co-60":  {"ingestion": 3.4e-09, "inhalation": 7.1e-09},  # M
        "Se-79":  {"ingestion": 2.9e-09, "inhalation": 1.6e-09},  # F
        "Sr-90":  {"ingestion": 2.8e-08, "inhalation": 3.0e-08},  # F
        "Tc-99":  {"ingestion": 7.8e-10, "inhalation": 4.0e-10},  # F
        "Ru-106": {"ingestion": 7.0e-09, "inhalation": 9.8e-09},  # F
        "Cs-134": {"ingestion": 1.9e-08, "inhalation": 9.6e-09},  # F
        "Cs-137": {"ingestion": 1.3e-08, "inhalation": 6.7e-09},  # F
        "Ce-144": {"ingestion": 5.2e-09, "inhalation": 2.3e-08},  # M
        "U-234":  {"ingestion": 4.9e-08, "inhalation": 2.1e-06},  # M (5 µm)
        "U-235":  {"ingestion": 4.6e-08, "inhalation": 1.8e-06},  # M (5 µm)
        "U-236":  {"ingestion": 4.6e-08, "inhalation": 1.9e-06},  # M (5 µm)
        "Np-237": {"ingestion": 1.1e-07, "inhalation": 1.5e-05},  # M (5 µm)
        "Pu-238": {"ingestion": 2.3e-07, "inhalation": 3.0e-05},  # M (5 µm)
        "Pu-240": {"ingestion": 2.5e-07, "inhalation": 3.2e-05},  # M (5 µm)
        "Pu-241": {"ingestion": 4.7e-09, "inhalation": 5.8e-07},  # M (5 µm)
        "Pu-242": {"ingestion": 2.4e-07, "inhalation": 3.1e-05},  # M (5 µm)
        "Am-243": {"ingestion": 2.0e-07, "inhalation": 2.7e-05},  # M (5 µm)
        "Cm-242": {"ingestion": 1.2e-08, "inhalation": 3.7e-06},  # M (5 µm)
        "Cm-243": {"ingestion": 1.5e-07, "inhalation": 2.0e-05},  # M (5 µm)
        "Cm-244": {"ingestion": 1.2e-07, "inhalation": 1.7e-05},  # M (5 µm)
        "Cm-245": {"ingestion": 2.1e-07, "inhalation": 2.7e-05},  # M (5 µm)
        "Cm-246": {"ingestion": 2.1e-07, "inhalation": 2.7e-05},  # M (5 µm)
        # Non-actinide expansion (default type, worker 5 µm):
        "Pb-210": {"ingestion": 6.8e-07, "inhalation": 1.1e-06},  # F
        "Sb-125": {"ingestion": 1.1e-09, "inhalation": 1.7e-09},  # F
        "Sn-126": {"ingestion": 4.7e-09, "inhalation": 1.4e-08},  # F
        "Pm-147": {"ingestion": 2.6e-10, "inhalation": 3.5e-09},  # M
        "Eu-154": {"ingestion": 2.0e-09, "inhalation": 3.5e-08},  # M
        "Eu-155": {"ingestion": 3.2e-10, "inhalation": 4.7e-09},  # M
    },
    "public_adult": {
        "Po-210": {"ingestion": 1.2e-06, "inhalation": 6.0e-07},  # F (corrected from M; Annex E)
        "Ra-226": {"ingestion": 2.8e-07, "inhalation": 3.5e-06},  # M
        "U-238":  {"ingestion": 4.5e-08, "inhalation": 2.9e-06},  # M
        "Pu-239": {"ingestion": 2.5e-07, "inhalation": 5.0e-05},  # M
        "Am-241": {"ingestion": 2.0e-07, "inhalation": 4.2e-05},  # M
        "Co-60":  {"ingestion": 3.4e-09, "inhalation": 1.0e-08},  # M
        "Se-79":  {"ingestion": 2.9e-09, "inhalation": 1.1e-09},  # F
        "Sr-90":  {"ingestion": 2.8e-08, "inhalation": 2.4e-08},  # F
        "Tc-99":  {"ingestion": 6.4e-10, "inhalation": 2.9e-10},  # F (differing-f1 ingestion)
        "Ru-106": {"ingestion": 7.0e-09, "inhalation": 7.9e-09},  # F
        "Cs-134": {"ingestion": 1.9e-08, "inhalation": 6.6e-09},  # F
        "Cs-137": {"ingestion": 1.3e-08, "inhalation": 4.6e-09},  # F
        "Ce-144": {"ingestion": 5.2e-09, "inhalation": 3.6e-08},  # M
        "U-234":  {"ingestion": 4.9e-08, "inhalation": 3.5e-06},  # M (1 µm adult)
        "U-235":  {"ingestion": 4.7e-08, "inhalation": 3.1e-06},  # M (1 µm adult)
        "U-236":  {"ingestion": 4.6e-08, "inhalation": 3.2e-06},  # M (1 µm adult)
        "Np-237": {"ingestion": 1.1e-07, "inhalation": 2.3e-05},  # M (1 µm adult)
        "Pu-238": {"ingestion": 2.3e-07, "inhalation": 4.6e-05},  # M (1 µm adult)
        "Pu-240": {"ingestion": 2.5e-07, "inhalation": 5.0e-05},  # M (1 µm adult)
        "Pu-241": {"ingestion": 4.8e-09, "inhalation": 9.0e-07},  # M (1 µm adult)
        "Pu-242": {"ingestion": 2.4e-07, "inhalation": 4.8e-05},  # M (1 µm adult)
        "Am-243": {"ingestion": 2.0e-07, "inhalation": 4.1e-05},  # M (1 µm adult)
        "Cm-242": {"ingestion": 1.2e-08, "inhalation": 5.2e-06},  # M (1 µm adult)
        "Cm-243": {"ingestion": 1.5e-07, "inhalation": 3.1e-05},  # M (1 µm adult)
        "Cm-244": {"ingestion": 1.2e-07, "inhalation": 2.7e-05},  # M (1 µm adult)
        "Cm-245": {"ingestion": 2.1e-07, "inhalation": 4.2e-05},  # M (1 µm adult)
        "Cm-246": {"ingestion": 2.1e-07, "inhalation": 4.2e-05},  # M (1 µm adult)
        # Non-actinide expansion (default type, public 1 µm adult):
        "Pb-210": {"ingestion": 6.9e-07, "inhalation": 9.0e-07},  # F
        "Sb-125": {"ingestion": 1.1e-09, "inhalation": 1.4e-09},  # F
        "Sn-126": {"ingestion": 4.7e-09, "inhalation": 1.1e-08},  # F
        "Pm-147": {"ingestion": 2.6e-10, "inhalation": 5.0e-09},  # M
        "Eu-154": {"ingestion": 2.0e-09, "inhalation": 5.3e-08},  # M
        "Eu-155": {"ingestion": 3.2e-10, "inhalation": 6.9e-09},  # M
    },
}

# Nuclides whose worker/public ingestion f1 differ (the equal-f1 check cannot apply); kept in
# lockstep with the build's DIFFERING_F1_INGESTION (see build_internal_dose.py for the physics).
DIFFERING_F1_INGESTION = {"Po-210", "Tc-99"}


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
    assert set(a["coefficients"]) == set(CURATED)


# -- Pillar 2: anchor goldens ----------------------------------------------

@pytest.mark.parametrize("population", idose.POPULATIONS)
@pytest.mark.parametrize("nuclide", CURATED)
def test_anchor_values(population, nuclide):
    for route in ("ingestion", "inhalation"):
        got = idose.coefficient(nuclide, route, population)
        want = ANCHORS[population][nuclide][route]
        assert got == want, f"{population}/{nuclide}/{route}: {got} != {want}"


def test_default_type_matches_annex_e_catchall():
    # default_type = ICRP-119 Annex E "unspecified compounds" catch-all per element (NOT a
    # value/memory pick) — it is what the engine folds, so the shipped default-type inhalation
    # value must equal that type's tabulated value.
    for population in idose.POPULATIONS:
        d = _load_raw(population)
        for nuc in CURATED:
            inh = d["coefficients"][nuc]["inhalation"]
            assert inh["default_type"] == DEFAULT_TYPE[nuc], f"{nuc}: default_type drift"
            assert idose.coefficient(nuc, "inhalation", population) == inh["types"][DEFAULT_TYPE[nuc]]


# -- Pillar 3: cross-table consistency (transcription fidelity) -------------

def test_ingestion_equal_f1_implies_equal_e():
    # The assumption-free transcription check: where worker and public-adult ingestion f1 are
    # EQUAL, the same biokinetics give an identical coefficient → e_worker == e_public (≤10% for
    # 2-sig-fig rounding). Holds for every curated nuclide except the differing-f1 exceptions.
    w = _load_raw("worker")["coefficients"]
    p = _load_raw("public_adult")["coefficients"]
    checked = 0
    for nuc in CURATED:
        wf, pf = w[nuc]["ingestion"]["f1"], p[nuc]["ingestion"]["f1"]
        if wf != pf:
            assert nuc in DIFFERING_F1_INGESTION, f"{nuc}: undocumented differing f1"
            continue
        we, pe = w[nuc]["ingestion"]["e_Sv_Bq"], p[nuc]["ingestion"]["e_Sv_Bq"]
        assert pe == pytest.approx(we, rel=0.10), f"{nuc}: equal-f1 but e differs ({pe} vs {we})"
        checked += 1
    assert checked >= len(CURATED) - len(DIFFERING_F1_INGESTION)


def test_tc99_differing_f1_is_a_documented_exception():
    # Tc-99 ingestion f1 differs (worker 0.8, public 0.5); the naive e∝f1 ratio is physically
    # invalid (β-emitter, large f1-independent colon transit dose). It must be a documented
    # exception, and the two-population affine solve e=G+f1·(S−G) must give G>=0, S>0.
    assert "Tc-99" in DIFFERING_F1_INGESTION
    we, wf = 7.8e-10, 0.8
    pe, pf = 6.4e-10, 0.5
    assert idose.coefficient("Tc-99", "ingestion", "worker") == we
    assert idose.coefficient("Tc-99", "ingestion", "public_adult") == pe
    slope = (pe - we) / (pf - wf)
    g = we - wf * slope
    assert g >= 0 and g + slope > 0  # G≈4.1e-10 (GI transit) , S≈8.7e-10 both physical


def test_every_public_inhalation_type_has_a_worker_analog():
    # No public-adult inhalation type ships without a worker counterpart to cross-validate it
    # (the build enforces public 1µm ≈ worker 1µm per type; this guards the shipped invariant
    # that public types ⊆ worker types — uncross-checkable types were dropped, §M13/advisor).
    w = _load_raw("worker")["coefficients"]
    p = _load_raw("public_adult")["coefficients"]
    for nuc in CURATED:
        wt = set(w[nuc]["inhalation"]["types"])
        pt = set(p[nuc]["inhalation"]["types"])
        assert pt <= wt, f"{nuc}: public inhalation types {pt} not all in worker {wt}"


def test_po210_population_difference_is_the_f1_ratio():
    # The teaching point that motivates shipping both populations: Po-210 ingestion differs by
    # exactly the f1 ratio (public dietary f1 0.5 vs worker f1 0.1 → 5×). This is exact because
    # Po-210 is systemic-dominated (α, retained) → the affine intercept G≈0 (see Tc-99 contrast).
    w = idose.coefficient("Po-210", "ingestion", "worker")
    p = idose.coefficient("Po-210", "ingestion", "public_adult")
    assert p / w == pytest.approx(5.0, rel=1e-6)


# -- Pillar 4: engine semantics --------------------------------------------

def _evaluate_stub(series: dict[str, list[float]], times=(0.0, 1.0)) -> dict:
    return {"axis": "activity", "unit": "Bq", "times_s": list(times), "series": series}


def test_three_coverage_states():
    # covered (actinides) + noble-gas N/A (Kr-85) + uncovered (I-131, not in the curated set —
    # iodine is deferred to the gas/vapour batch, so it is a genuine coverage gap here).
    model = idose.InternalDoseModel(
        ["Pu-239", "Am-241", "Kr-85", "I-131"], "inhalation", "worker"
    )
    assert set(model.covered) == {"Pu-239", "Am-241"}
    assert model.noble_gas_na == ["Kr-85"]
    assert model.uncovered == ["I-131"]


def test_lower_bound_only_from_uncovered_not_noble_gas():
    series = _evaluate_stub({"Pu-239": [1e6, 1e6], "Kr-85": [1e9, 1e9]})
    out = idose.InternalDoseModel(["Pu-239", "Kr-85"], "inhalation", "worker") \
        .committed_dose_series(series)
    # Kr-85 is N/A, not uncovered → NOT a lower bound.
    assert out["lower_bound"] is False
    assert out["noble_gas_na"] == ["Kr-85"]
    assert any(w["reason"] == "noble_gas_no_intake_pathway" for w in out["warnings"])

    series2 = _evaluate_stub({"Pu-239": [1e6, 1e6], "I-131": [1e9, 1e9]})
    out2 = idose.InternalDoseModel(["Pu-239", "I-131"], "inhalation", "worker") \
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
    # NOTE: the S golden was 6.3E-06 — a transcription error (U-236's 5µm S value pulled into the
    # adjacent U-238 row). Corrected to 5.7E-06 against a 300-DPI crop of ICRP-119 Annex A printed
    # p.54 (U-238 5µm S = 5.7E-06, 1µm S = 7.3E-06) in the M13 actinide-expansion batch. The
    # error escaped the build's inhalation check (which validates the 1µm column, not the shipped
    # worker 5µm) and the v1 fold (S is a non-default type, never folded). See PROVENANCE.md.
    s = idose.coefficient("U-238", "inhalation", "worker", absorption_type="S")
    m = idose.coefficient("U-238", "inhalation", "worker")
    assert s == 5.7e-06 and m == 1.6e-06


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
