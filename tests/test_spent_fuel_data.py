"""Regression suite for the bundled PWR spent-fuel discharge vectors (HANDOFF_PLAN §8, §10).

The datasets are the project (CLAUDE.md), so each lands with its validation. These vectors
are extracted by ``data/build/build_spent_fuel.py`` from the CC-BY SCK-CEN Serpent2 library
(DOI 10.17632/shv89y2zzd) — but this suite tests the **committed JSON** without the 370 MB
CSV, re-deriving every anchor *independently* of the build script:

1. **Structural** — schema, required keys, a discharge (zero-cooling) vector, negligible
   dropped (not-in-rd) activity.
2. **Tractability** — the full vector solves in DOUBLE precision (no HP), the §3 contract.
3. **Absolute basis (independent anchor)** — the engine-solved Cs-137 discharge activity
   matches a from-scratch fission-yield estimate (cumulative yield × fissions-per-burnup ×
   λ), which uses NONE of the dataset's own activity columns — so it validates the
   mass-density→λN→per-tonne basis the build chose (the dataset's _A column carries an
   opaque geometry factor and is deliberately not used).
4. **Burnup scaling** — Cs-137 and decay heat scale ~linearly between the 20 and 45 GWd
   points (fission products track fluence).
5. **Decay heat magnitude** — folded through the M7c decay-heat engine, the W/tHM at 10 yr
   sits in the published PWR band; and cooling monotonically lowers both heat and the
   long-lived activity (forward decay).
6. **Enrichment axis (fixed burnup)** — at 45 GWd, Cs-137 (a fission product) is ~enrichment-
   independent (it tracks burnup), while the intrinsic neutron source rises as enrichment falls
   (lower enrichment reaches the same burnup with more U-238 capture → more Pu/minor-actinide
   buildup). The two axes cross at the reference point (45 GWd, 4.0%).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from engine.decay_heat import DecayHeatModel
from engine.inventory import SolvedInventory

_SF_DIR = Path(__file__).resolve().parents[1] / "data" / "spent_fuel"
_YEAR_S = 365.25 * 86400

# Independent fission-yield estimate of the Cs-137 discharge activity (NOT from the dataset):
#   A(Cs-137)/tHM ≈ λ · Y_cum · (BU·1e9·86400 J/tHM) / (200 MeV/fission · 1.602e-13 J/MeV)
_CS137_LAMBDA = math.log(2.0) / (30.08 * _YEAR_S)  # s⁻¹
_CS137_YIELD = 0.0620  # cumulative thermal fission yield
_J_PER_FISSION = 200.0 * 1.602176634e-13
_CS137_BQ_PER_THM_PER_GWD = _CS137_LAMBDA * _CS137_YIELD * (1.0e9 * 86400) / _J_PER_FISSION


def _load(point_id: str) -> dict:
    return json.loads((_SF_DIR / f"{point_id}.json").read_text(encoding="utf-8"))


def _solve(record: dict) -> SolvedInventory:
    spec = [
        {"name": e["name"], "quantity": e["mass_g_per_tHM"], "unit": "g"} for e in record["entries"]
    ]
    return SolvedInventory.from_entries(spec, precision="double")


# The burnup × enrichment CROSS centered on the reference (45 GWd/tHM, 4.0%): a burnup axis
# (20/45/60 @ 4.0%) and an enrichment axis (3/4/5% @ 45 GWd), sharing that center point.
POINTS = [
    "pwr-uox-60gwd-4pct",
    "pwr-uox-45gwd-4pct",
    "pwr-uox-20gwd-4pct",
    "pwr-uox-45gwd-3pct",
    "pwr-uox-45gwd-5pct",
]
# The enrichment axis, low→high enrichment, at fixed 45 GWd/tHM burnup.
ENRICHMENT_AXIS = ["pwr-uox-45gwd-3pct", "pwr-uox-45gwd-4pct", "pwr-uox-45gwd-5pct"]


@pytest.fixture(scope="module")
def points() -> dict[str, dict]:
    return {pid: _load(pid) for pid in POINTS}


def test_all_grid_points_present():
    found = {p.stem for p in _SF_DIR.glob("*.json")}
    assert set(POINTS) <= found, f"missing spent-fuel vectors: {set(POINTS) - found}"


@pytest.mark.parametrize("point_id", POINTS)
def test_structural(points, point_id):
    d = points[point_id]
    assert d["schema_version"] == 3  # v3: + (α,n)-on-oxygen neutron term (M12)
    assert d["cooling_time_s"] == 0.0  # a DISCHARGE vector; cooling = the §9 time control
    assert d["entries"] and all(e["mass_g_per_tHM"] > 0.0 for e in d["entries"])
    assert "tonne initial heavy metal" in d["basis"]
    # The not-in-rd drop loses activity AND daughter ingrowth — must be negligible (§11).
    assert d["dropped"]["activity_frac"] < 1e-3
    # Honesty hooks that must reach the UI.
    assert "neutron" in d["neutron_caveat"].lower()
    assert "CC BY" in d["source_ref"]


@pytest.mark.parametrize("point_id", POINTS)
def test_solves_in_double_precision(points, point_id):
    # Verify-first #1: a 67-nuclide vector spanning seconds→10⁷ yr must solve in double
    # without tripping the engine's cancellation floor (no HP fallback needed).
    inv = _solve(points[point_id])
    assert inv.precision == "double"
    act = inv.evaluate([0.0], axis="activity", unit="Bq")
    assert act["clipped_count"] >= 0  # raises EngineError instead if too stiff


@pytest.mark.parametrize("point_id", POINTS)
def test_cs137_matches_independent_fission_yield(points, point_id):
    d = points[point_id]
    inv = _solve(d)
    cs137 = inv.evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
    expected = _CS137_BQ_PER_THM_PER_GWD * d["burnup_GWd_tHM"]
    # ~5% low vs the simple estimate (Cs-137 neutron capture + Pu-239 fission yield) — a
    # 20% band is a real cross-check (a basis/units error misses by far more).
    assert cs137 == pytest.approx(expected, rel=0.20)


def test_burnup_scaling(points):
    # Cs-137 (long-lived FP) tracks total fissions ≈ burnup. Across the whole 20→45→60 GWd
    # series the discharge Cs-137 ratio must track the achieved-burnup ratio within ~15%.
    cs = {
        pid: _solve(points[pid]).evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
        for pid in POINTS
    }
    bu = {pid: points[pid]["burnup_GWd_tHM"] for pid in POINTS}
    for hi, lo in (
        ("pwr-uox-45gwd-4pct", "pwr-uox-20gwd-4pct"),
        ("pwr-uox-60gwd-4pct", "pwr-uox-45gwd-4pct"),
    ):
        assert cs[hi] / cs[lo] == pytest.approx(bu[hi] / bu[lo], rel=0.15), (hi, lo)


def test_enrichment_axis_at_fixed_burnup(points):
    # The enrichment axis (3/4/5% @ 45 GWd) is a pure-actinide contrast at FIXED burnup, with two
    # independent signatures — both computed via the engine's λN, NOT the dataset's opaque _A column:
    #  (a) Cs-137, a fission product, tracks total fissions ≈ burnup → ~enrichment-independent.
    #  (b) the intrinsic neutron source (SF + (α,n)) RISES as enrichment falls: lower enrichment
    #      reaches the same burnup with more U-238 capture → more Pu/minor-actinide buildup
    #      (Cm-244 roughly doubles from 5% to 3%), so the source is ~2× larger at 3% than at 5%.
    invs = {pid: _solve(points[pid]) for pid in ENRICHMENT_AXIS}
    act0 = {
        pid: invs[pid].evaluate([0.0], axis="activity", unit="Bq")["series"]
        for pid in ENRICHMENT_AXIS
    }

    # (a) Cs-137 discharge activity is flat across the enrichment axis (within 3%).
    cs = {pid: act0[pid]["Cs-137"][0] for pid in ENRICHMENT_AXIS}
    assert max(cs.values()) / min(cs.values()) < 1.03, cs

    # (b) the discharge neutron source (SF + (α,n) modeled yields) is strictly monotonic in
    #     enrichment, with a material (not marginal) 3%-vs-5% contrast.
    def _source0(pid: str) -> float:
        d = points[pid]
        sf = d["neutron"]["yields_n_per_decay"]
        an = d["neutron"]["alpha_n"]["yields_n_per_decay"]
        s = act0[pid]
        return math.fsum(y * s.get(n, [0.0])[0] for n, y in sf.items()) + math.fsum(
            y * s.get(n, [0.0])[0] for n, y in an.items()
        )

    s3, s4, s5 = (_source0(p) for p in ENRICHMENT_AXIS)  # 3% → 4% → 5%
    assert s3 > s4 > s5 > 0.0, (s3, s4, s5)
    assert s3 / s5 > 1.5, s3 / s5


@pytest.mark.parametrize(
    "point_id,lo_kw,hi_kw",
    [
        # High burnup carries more decay heat at 10 yr (FP ∝ burnup + extra minor-actinide heat);
        # the band is the 45 GWd band scaled ~×(60/45), an independent published-range expectation.
        ("pwr-uox-60gwd-4pct", 1.3, 3.5),
        ("pwr-uox-45gwd-4pct", 1.0, 2.5),
        ("pwr-uox-20gwd-4pct", 0.4, 1.2),
        # The enrichment axis shares the 45 GWd band: 10-yr heat is fission-product-dominated and
        # FP track burnup, not enrichment, so the published range is the SAME regardless of IE. The
        # small actinide tail (slightly higher at low enrichment) stays well inside — reusing the
        # band is itself the cross-check on that enrichment-insensitivity. (Trend → enrichment test.)
        ("pwr-uox-45gwd-3pct", 1.0, 2.5),
        ("pwr-uox-45gwd-5pct", 1.0, 2.5),
    ],
)
def test_decay_heat_10yr_in_published_band(points, point_id, lo_kw, hi_kw):
    inv = _solve(points[point_id])
    act = inv.evaluate([10.0 * _YEAR_S], axis="activity", unit="Bq")
    w = DecayHeatModel(inv.names).heat_series(act)["total_W"][0]
    assert lo_kw * 1e3 < w < hi_kw * 1e3, f"{point_id}: {w / 1e3:.3f} kW/tHM outside band"


@pytest.mark.parametrize("point_id", POINTS)
def test_cooling_lowers_heat_in_the_cooling_regime(points, point_id):
    # Decay heat is NOT strictly monotonic from t=0: daughter ingrowth (and the dataset's
    # omission of sub-hour fission products from the discharge snapshot) can let it rise in
    # the first months. But through the spent-fuel COOLING regime (years+) it falls steadily.
    inv = _solve(points[point_id])
    ts = [1.0 * _YEAR_S, 10.0 * _YEAR_S, 100.0 * _YEAR_S, 1000.0 * _YEAR_S]
    w = DecayHeatModel(inv.names).heat_series(inv.evaluate(ts, axis="activity", unit="Bq"))[
        "total_W"
    ]
    assert all(w[i] > w[i + 1] for i in range(len(w) - 1)), w


# --- M9: SF neutron-yield block ------------------------------------------------------------
# yield_per_decay(n) = (_SF/_A from Serpent2)·ν̄; the neutron source is S(t)=Σ yield·A_n(t).
# ν̄ is from the IAEA safeguards table for the 18 safeguards isotopes, plus Cm-246/248 derived
# (Σ_k k·P(k)) from the Holden & Zucker BNL-36467 distributions (see the derivation test below).
# NOTE the Cm-244 cross-check validates the SF BRANCHING RATIO (Serpent2 _SF/_A vs IAEA's implied
# T_tot/T_SF) — ν̄ cancels in n_yield/SA, so it does NOT independently validate ν̄ or the absolute
# yield; those rest on the cited IAEA/Holden ν̄.
_CM244_IAEA_N_YIELD_N_S_G = 1.100e7  # IAEA NDS SF_n-Yield Table 1

_VENDOR_DIR = Path(__file__).resolve().parents[1] / "data" / "vendor"
_NUBAR_PATH = _VENDOR_DIR / "iaea_sf_nu" / "sf_nubar.json"
_SF_MULT_PATH = _VENDOR_DIR / "llnl_sf_multiplicity" / "sf_multiplicity.json"


@pytest.mark.parametrize("point_id", POINTS)
def test_neutron_block_structural(points, point_id):
    n = points[point_id]["neutron"]
    assert n["spectrum_source"] == "Cf-252"
    assert n["yields_n_per_decay"] and "Cm-244" in n["yields_n_per_decay"]
    assert all(v > 0.0 for v in n["yields_n_per_decay"].values())
    # M12: the source is now SF + (α,n)-on-oxygen — a documented BEST ESTIMATE, not a lower bound.
    assert "best estimate" in n["model"].lower() and "(α,n)" in n["model"]
    # Discharge drop (emitters without an evaluated ν̄) must be negligible at t=0.
    assert n["dropped_sf_frac_at_discharge"] < 0.01
    # Cm-246/248 ν̄ are now SOURCED (Holden & Zucker BNL-36467), so the dominant long-cooling SF
    # emitter Cm-246 is MODELED (in yields), not dropped — this is what extends the valid regime.
    assert "Cm-246" in n["yields_n_per_decay"] and "Cm-248" in n["yields_n_per_decay"]
    assert "Cm-246" not in n["dropped_sf_branch"] and "Cm-248" not in n["dropped_sf_branch"]


# --- M12: (α,n)-on-oxygen neutron term -----------------------------------------------------
# yield_an_per_decay = PANDA Table-13 Oxide(n/s-g) / specific activity (per gram of isotope).
# What is independently validated is the per-gram-of-isotope BASIS (PANDA α/s·g vs ICRP-107
# α-branch×rd-SA — two independent data sources); the (α,n) absolute MAGNITUDE rests on PANDA,
# un-independently-confirmed (parallel to M9's ν̄-rests-on-IAEA/Holden framing). The Pu-238 oxide
# total is only a cross-pipeline SF-sanity gate (the canonical value ≈ PANDA's own column sum).
_PANDA_PATH = _VENDOR_DIR / "panda_alpha_n" / "alpha_n_oxide.json"


@pytest.mark.parametrize("point_id", POINTS)
def test_alpha_n_block_structural(points, point_id):
    an = points[point_id]["neutron"]["alpha_n"]
    y = an["yields_n_per_decay"]
    # The dominant spent-fuel (α,n) emitters must be modeled (all in PANDA Table 13).
    for nuc in ("Cm-242", "Cm-244", "Am-241", "Pu-238", "Pu-240"):
        assert nuc in y and y[nuc] > 0.0, nuc
    assert an["nominal_O_yield_per_alpha"] == pytest.approx(5.9e-8, rel=1e-9)
    # α-emitters absent from Table 13 (e.g. Cm-246, Am-243) are tracked for the residual warning,
    # NOT in the modeled (α,n) yields — the honest, surfaced gap.
    assert "Cm-246" in an["dropped_alpha_branch"] and "Cm-246" not in y


def test_panda_alpha_sg_is_per_gram_of_isotope():
    # The NON-tautological per-gram basis check (the §12 trap): PANDA Table-13's "Yield (α/s·g)"
    # column must equal the isotope α-emission rate from INDEPENDENT nuclear data — ICRP-107 α
    # branch × rd specific activity (λ·N_A/M, per gram of isotope). Agreement proves the PANDA
    # per-gram columns are per gram of ISOTOPE, so dividing the Oxide column by λN_A/M (what the
    # build does) is on a consistent basis. A ÷ oxide-mass (~270 vs ~238) slip is +13.4% → would
    # fail here. NOTE: a `yield = oxide/SA` then `yield·SA ≈ oxide` round-trip would be tautological
    # (it just echoes the build's own arithmetic); this compares two independent data sources.
    import radioactivedecay as rd
    from engine import emissions

    nd = rd.DEFAULTDATA.nuclide_dict
    sd = rd.DEFAULTDATA.scipy_data
    oxide = json.loads(_PANDA_PATH.read_text(encoding="utf-8"))["oxide_an_yield"]
    checked = 0
    for nuc, rec in oxide.items():
        if not emissions.has_emissions(nuc):
            continue
        br = math.fsum(float(a["yield"]) for a in emissions.alphas(nuc))  # α/decay, ICRP-107
        if br <= 0.0:
            continue
        lam = math.log(2.0) / float(rd.Nuclide(nuc).half_life("s"))
        sa = lam * 6.02214076e23 / float(sd.atomic_masses[nd[nuc]])  # Bq/g, per gram isotope
        assert br * sa == pytest.approx(rec["alpha_s_g"], rel=0.08), nuc
        checked += 1
    assert checked >= 12  # the bulk of the table (β-dominated Pu-241 etc. included)


@pytest.mark.parametrize("point_id", POINTS)
def test_pu238_oxide_total_is_a_cross_pipeline_sanity_not_an_alpha_n_validation(points, point_id):
    # The Pu-238 oxide total (dataset-SF + PANDA-(α,n)) lands at the canonical ~1.60e4 n/s·g — but
    # this is a WEAK anchor by construction: the canonical value ≈ PANDA's own SF+(α,n) column sum,
    # and the (α,n) term echoes PANDA regardless of basis. What it genuinely exercises is the
    # dataset-SF ↔ PANDA-SF agreement (Serpent2 ~2604 vs PANDA 2590 n/s·g) — the already-M9-
    # validated SF pipeline. The honest (α,n) checks are the per-gram basis test above + the
    # build's basis_check; the (α,n) absolute magnitude rests on PANDA, un-independently-confirmed.
    chk = points[point_id]["neutron"]["crosscheck_Pu238_oxide_total"]
    assert chk["total_n_s_g"] == pytest.approx(1.60e4, rel=0.12)
    assert "NOT an independent" in chk["note"]
    # The dataset SF for Pu-238 must agree with PANDA's tabulated SF yield (2.59e3) to a few %.
    assert chk["sf_n_s_g"] == pytest.approx(2.59e3, rel=0.05)


@pytest.mark.parametrize("point_id", POINTS)
def test_alpha_n_basis_check_ran_in_build(points, point_id):
    # The build's per-gram-of-isotope basis gate must have actually run over the table and passed
    # well inside tolerance (it is the real safeguard against the §12 basis slip).
    bc = points[point_id]["neutron"]["alpha_n"]["basis_check"]
    assert bc["n_isotopes"] >= 12 and bc["worst_rel"] < bc["tol"]


@pytest.mark.parametrize("point_id", POINTS)
def test_cm244_sf_branching_ratio_matches_iaea(points, point_id):
    # Cross-checks the SF BRANCHING RATIO (NOT ν̄, NOT the absolute yield): the stored
    # (_SF/_A)·ν̄ equals n_yield_IAEA/SA only if Serpent2's SF branch matches IAEA's implied
    # T_tot/T_SF, because the SAME ν̄ appears on both sides and cancels. So a pass means
    # Serpent2's SF half-life agrees with IAEA's to ~2% — it catches a _SF units/mapping slip,
    # but the neutron magnitude still rests on the cited IAEA/Holden ν̄ (not validated here).
    import radioactivedecay as rd

    nd = rd.DEFAULTDATA.nuclide_dict
    sd = rd.DEFAULTDATA.scipy_data
    lam = math.log(2.0) / float(rd.Nuclide("Cm-244").half_life("s"))
    sa = lam * 6.02214076e23 / float(sd.atomic_masses[nd["Cm-244"]])  # Bq/g
    expected = _CM244_IAEA_N_YIELD_N_S_G / sa
    stored = points[point_id]["neutron"]["yields_n_per_decay"]["Cm-244"]
    assert stored == pytest.approx(expected, rel=0.05)


@pytest.mark.parametrize("point_id", POINTS)
def test_sf_neutron_source_cm244_dominates_after_cooling(points, point_id):
    # The whole point of the per-nuclide (multi-parent) model: Cm-242 (163 d) carries a big
    # share at discharge but is gone by 10 yr, leaving Cm-244 (18 yr) dominant; the source then
    # falls with Cm-244. A single-parent model could not show this transition.
    d = points[point_id]
    inv = _solve(d)
    yields = d["neutron"]["yields_n_per_decay"]
    ts = [0.0, 10.0 * _YEAR_S, 100.0 * _YEAR_S]
    act = inv.evaluate(ts, axis="activity", unit="Bq")["series"]

    def s_at(i):  # total SF neutron source at sample i (n/s/tHM)
        return math.fsum(y * act.get(name, [0.0] * 3)[i] for name, y in yields.items())

    s0, s10, s100 = s_at(0), s_at(1), s_at(2)
    assert s0 > s10 > s100 > 0.0  # cools down through the regime
    cm242_0 = yields.get("Cm-242", 0.0) * act["Cm-242"][0]
    cm244_10 = yields["Cm-244"] * act["Cm-244"][1]
    assert cm242_0 / s0 > 0.10  # Cm-242 a real share at discharge
    assert cm244_10 / s10 > 0.85  # Cm-244 dominant by 10 yr (more so at high BU)


def test_cm246_nubar_derived_from_vendored_distribution():
    """The Cm-246/248 ν̄ are DERIVED, not transcribed: ν̄ = Σ_k k·P(k) over the Holden & Zucker
    BNL-36467 SF multiplicity distributions vendored in data/vendor/llnl_sf_multiplicity/. This
    re-runs that computation as a regression check, and — crucially — validates the METHOD by
    reproducing the IAEA-vendored Cm-242/Cm-244 ν̄ (2.540 / 2.720) exactly from the same source's
    distributions before trusting it for the new nuclides. Then it confirms the value the build
    consumes (sf_nubar.json's nu_p) equals the freshly derived one — no hand-typed literal slips
    in between the source and the dose. (No fabrication; §11 / CLAUDE.md.)"""
    mult = json.loads(_SF_MULT_PATH.read_text(encoding="utf-8"))
    nubar = json.loads(_NUBAR_PATH.read_text(encoding="utf-8"))["nuclides"]

    derived: dict[str, float] = {}
    for row in mult["distributions"]:
        nu_bar = math.fsum(k * p for k, p in enumerate(row["P"]))
        assert math.isclose(math.fsum(row["P"]), 1.0, abs_tol=2e-4), row  # a probability dist.
        # Method-validation rows must reproduce the IAEA-known ν̄ exactly (proves Σ_k k·P(k)).
        if row["role"] == "method-validation":
            assert nu_bar == pytest.approx(row["expect_nu_bar"], abs=5e-4)
            assert nu_bar == pytest.approx(nubar[row["nuclide"]]["nu_p"], abs=5e-4)
        elif row["role"] == "vendored-nu_p-source":
            derived[row["nuclide"]] = nu_bar

    # The new nuclides, derived from the BNL-36467 distribution, to 3 decimals.
    assert derived["Cm-246"] == pytest.approx(2.930, abs=5e-4)
    assert derived["Cm-248"] == pytest.approx(3.130, abs=5e-4)
    # …and the build's consumed nu_p must equal the derivation (source → dose, no typo).
    assert nubar["Cm-246"]["nu_p"] == pytest.approx(derived["Cm-246"], abs=5e-4)
    assert nubar["Cm-248"]["nu_p"] == pytest.approx(derived["Cm-248"], abs=5e-4)
    assert nubar["Cm-246"]["src"] == "HZ-BNL36467" and nubar["Cm-248"]["src"] == "HZ-BNL36467"

    # Independent cross-confirm for Cm-248 (Vorobyev 2005, a different measurement).
    vorobyev = next(
        r
        for r in mult["distributions"]
        if r["nuclide"] == "Cm-248" and r["role"] == "cross-confirm"
    )
    assert math.fsum(k * p for k, p in enumerate(vorobyev["P"])) == pytest.approx(3.13, abs=2e-3)


@pytest.mark.parametrize("point_id", POINTS)
def test_sourcing_cm246_248_extends_valid_cooling_regime(points, point_id):
    """With Cm-246/248 now modeled, the unmodeled-ν̄ dropped SF-rate fraction stays negligible
    across the WHOLE cooling range (it was capped at ~1 century before): Cm-246 (4760 yr) carries
    the source after Cm-244 (18 yr) decays, and the residual (chiefly Pu-244, Cm-250) is tiny.
    This is the deliverable — the engine's lower-bound ν̄-gap warning no longer fires for the
    shipped vectors. (The orthogonal (α,n) lower-bound caveat is unaffected.)"""
    d = points[point_id]
    inv = _solve(d)
    yields = d["neutron"]["yields_n_per_decay"]
    dropped = d["neutron"]["dropped_sf_branch"]
    nom = d["neutron"]["dropped_nubar_nominal"]
    ts = [1.0e3 * _YEAR_S, 1.0e4 * _YEAR_S, 1.0e5 * _YEAR_S]  # the multi-century+ regime
    series = inv.evaluate(ts, axis="activity", unit="Bq")["series"]
    for i in range(len(ts)):
        s = math.fsum(y * series.get(n, [0.0] * len(ts))[i] for n, y in yields.items())
        s_drop = nom * math.fsum(
            b * series.get(n, [0.0] * len(ts))[i] for n, b in dropped.items() if n in series
        )
        frac = s_drop / (s + s_drop) if (s + s_drop) > 0 else 0.0
        assert frac < 0.01, f"{point_id}: dropped SF frac {frac:.3%} at t={ts[i] / _YEAR_S:.0f} yr"
    # Cm-246 must be modeled (the sourcing goal). Its WEIGHT in the long-cooling SF source is a
    # CROSS signature — Cm-246 is a high-order capture product, so it leads the 1 kyr source (Cm-244
    # long gone) at high burnup AND at low enrichment. Keyed on physics, verified against the build
    # output (not assumed): it dominates at 60/45 GWd @4% and at 45 GWd @3%; at 45 GWd @5% (less
    # capture) and 20 GWd @4% (too little capture) the lower-order Pu-240 still leads.
    assert "Cm-246" in yields
    s1k = {n: yields[n] * series[n][0] for n in yields if n in series}
    _CM246_DOMINANT = {"pwr-uox-60gwd-4pct", "pwr-uox-45gwd-4pct", "pwr-uox-45gwd-3pct"}
    if point_id in _CM246_DOMINANT:
        assert max(s1k, key=s1k.get) == "Cm-246"
        assert s1k["Cm-246"] / math.fsum(s1k.values()) > 0.4
    else:  # 20 GWd @4%, 45 GWd @5%: the lower-order Pu-240 leads, Cm-246 not yet dominant
        # 45 GWd @5% is DELIBERATELY the near-crossover point (Pu-240 0.45 vs Cm-246 0.36) — the
        # tightest margin in this suite. It is deterministic (fixed by the committed JSON + rd's
        # nuclear data, not flaky), but if a future radioactivedecay data bump (Cm-246/Pu-240/
        # Cm-244 half-lives) trips this, it is a physics-boundary recalibration, NOT a bug — move
        # 45@5% between the sets per the new numbers; do NOT widen 0.4 (that blurs the boundary).
        assert max(s1k, key=s1k.get) == "Pu-240"
        assert s1k["Cm-246"] / math.fsum(s1k.values()) < 0.4
