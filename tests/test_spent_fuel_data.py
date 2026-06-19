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
_CS137_LAMBDA = math.log(2.0) / (30.08 * _YEAR_S)            # s⁻¹
_CS137_YIELD = 0.0620                                        # cumulative thermal fission yield
_J_PER_FISSION = 200.0 * 1.602176634e-13
_CS137_BQ_PER_THM_PER_GWD = _CS137_LAMBDA * _CS137_YIELD * (1.0e9 * 86400) / _J_PER_FISSION


def _load(point_id: str) -> dict:
    return json.loads((_SF_DIR / f"{point_id}.json").read_text(encoding="utf-8"))


def _solve(record: dict) -> SolvedInventory:
    spec = [{"name": e["name"], "quantity": e["mass_g_per_tHM"], "unit": "g"} for e in record["entries"]]
    return SolvedInventory.from_entries(spec, precision="double")


POINTS = ["pwr-uox-45gwd-4pct", "pwr-uox-20gwd-4pct"]


@pytest.fixture(scope="module")
def points() -> dict[str, dict]:
    return {pid: _load(pid) for pid in POINTS}


def test_all_grid_points_present():
    found = {p.stem for p in _SF_DIR.glob("*.json")}
    assert set(POINTS) <= found, f"missing spent-fuel vectors: {set(POINTS) - found}"


@pytest.mark.parametrize("point_id", POINTS)
def test_structural(points, point_id):
    d = points[point_id]
    assert d["schema_version"] == 2  # v2: + SF neutron-yield block (M9)
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
    hi, lo = points["pwr-uox-45gwd-4pct"], points["pwr-uox-20gwd-4pct"]
    cs_hi = _solve(hi).evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
    cs_lo = _solve(lo).evaluate([0.0], axis="activity", unit="Bq")["series"]["Cs-137"][0]
    # Cs-137 (long-lived FP) tracks total fissions ≈ burnup; ratio ≈ 45/20 within ~15%.
    assert cs_hi / cs_lo == pytest.approx(45.0 / 20.0, rel=0.15)


@pytest.mark.parametrize("point_id,lo_kw,hi_kw", [
    ("pwr-uox-45gwd-4pct", 1.0, 2.5),
    ("pwr-uox-20gwd-4pct", 0.4, 1.2),
])
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
    w = DecayHeatModel(inv.names).heat_series(inv.evaluate(ts, axis="activity", unit="Bq"))["total_W"]
    assert all(w[i] > w[i + 1] for i in range(len(w) - 1)), w


# --- M9: SF neutron-yield block ------------------------------------------------------------
# yield_per_decay(n) = (_SF/_A from Serpent2)·ν̄(IAEA); the neutron source is S(t)=Σ yield·A_n(t).
# Cm-244 is the dominant SF emitter. NOTE the cross-check below validates the SF BRANCHING RATIO
# (Serpent2 _SF/_A vs IAEA's implied T_tot/T_SF) — ν̄ cancels in n_yield/SA, so it does NOT
# independently validate ν̄ or the absolute yield; those rest on the cited IAEA/Holden ν̄.
_CM244_IAEA_N_YIELD_N_S_G = 1.100e7   # IAEA NDS SF_n-Yield Table 1


@pytest.mark.parametrize("point_id", POINTS)
def test_neutron_block_structural(points, point_id):
    n = points[point_id]["neutron"]
    assert n["spectrum_source"] == "Cf-252"
    assert n["yields_n_per_decay"] and "Cm-244" in n["yields_n_per_decay"]
    assert all(v > 0.0 for v in n["yields_n_per_decay"].values())
    # SF-only is a documented LOWER BOUND ((α,n) absent from the dataset) — must say so.
    assert "lower bound" in n["model"].lower()
    # Discharge drop (emitters without an evaluated ν̄) must be negligible at t=0.
    assert n["dropped_sf_frac_at_discharge"] < 0.01
    # Cm-246 — which dominates the SF source at long cooling — is the tracked drop the engine warns on.
    assert "Cm-246" in n["dropped_sf_branch"]


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
    sa = lam * 6.02214076e23 / float(sd.atomic_masses[nd["Cm-244"]])   # Bq/g
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
    assert s0 > s10 > s100 > 0.0                       # cools down through the regime
    cm242_0 = yields.get("Cm-242", 0.0) * act["Cm-242"][0]
    cm244_10 = yields["Cm-244"] * act["Cm-244"][1]
    assert cm242_0 / s0 > 0.10                         # Cm-242 a real share at discharge
    assert cm244_10 / s10 > 0.85                       # Cm-244 dominant by 10 yr (more so at high BU)
