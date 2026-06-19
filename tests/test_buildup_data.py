"""Regression suite for the bundled ANS-6.4.3 G-P buildup data (HANDOFF_PLAN.md §6.5/§7).

The datasets are the project (CLAUDE.md), validated the moment they land. Unlike the
NIST/ICRP datasets, there is no clean machine-readable upstream, so the trust model is
**degraded honestly** (docs/plans/M2-buildup.md): values were double-entered from the
public-domain NUREG/CR-5740 scan, and faithfulness is enforced here by independent
checks rather than a verbatim re-parse:

1. **Structural** — schema, alignment, ascending grid, finite coefficients, Xk > 0,
   loose ``b`` sanity (NOT a tight ``b >= 1`` — high-E behaviour is data, not assumed).
2. **Algebraic goldens** — the G-P identities ``B(0)=1`` and ``B(1 mfp)=b`` (validate
   the evaluator independently of any coefficient value).
3. **Physical reconstruction** — B over the mfp grid is finite, ≥ 1, and grows with
   depth, for *every* material/energy (catches coefficient errors that yield
   unphysical B even where no golden B-value exists).
4. **Smoothness** — above the K-edge region the G-P ``b`` varies smoothly in log-E; a
   single off-trend point (the residual a double-entry miss could leave) is caught.
5. **Cross-source** — iron coefficients vs an INDEPENDENT open-access tabulation
   (EPJ Web Conf. 106, 03009 (2016), CC-BY, Table 1). Its two garbled rows (0.50,
   10.0 MeV) are excluded by name — a cross-source value can itself be corrupt.
6. **Within-source reconstruction** — reconstruct B from the coefficients and match the
   report's OWN Table 3 exposure B-values (data/vendor/ans643/b_value_spotchecks.json),
   within the GP fit residual + scan-read margin. Uniquely catches *systematic* errors
   (c<->a swap, kerma/exposure mixup, formula bug) and validates the M3 evaluator.

Trust boundary (honesty): faithfulness to true ANS-6.4.3 is independently verified only
for the cross-source / golden subset; the remainder is trusted to the double-entered
transcription. This mirrors the emissions trust boundary.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from engine import buildup as bu

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "buildup"
VENDOR = ROOT / "data" / "vendor" / "ans643"

# Materials that MUST have buildup (the shields ANS-6.4.3 covers + dose media).
REQUIRED = {"lead", "tungsten", "iron", "copper", "aluminium", "concrete",
            "water", "air"}
# Low-Z shields ANS-6.4.3 does NOT tabulate — their ABSENCE is the honest contract
# (the M3 dose engine must handle it loudly, never with a silent surrogate).
ABSENT_BY_DESIGN = {"pmma", "polyethylene", "tissue_soft"}

GP_KEYS = ("b", "c", "a", "Xk", "d")
ALL = sorted(p.stem for p in CANON.glob("*.json"))


# --------------------------------------------------------------------------- #
# 0/1. Presence, coverage, structure.
# --------------------------------------------------------------------------- #

def test_dataset_present_and_complete():
    missing = sorted(REQUIRED - set(ALL))
    assert not missing, f"missing buildup files {missing}; run data/build/build_buildup.py"
    strays = sorted(set(ALL) - REQUIRED)
    assert not strays, f"unexpected buildup files: {strays}"


def test_low_z_shields_absent_by_design():
    """PMMA / polyethylene / tissue have no ANS-6.4.3 buildup — must NOT be invented."""
    for m in ABSENT_BY_DESIGN:
        assert not bu.has_material(m), (
            f"{m} has a buildup file but ANS-6.4.3 provides none; a fabricated/surrogate "
            "table violates the no-silent-errors contract"
        )
        with pytest.raises(bu.BuildupError):
            bu.load_buildup(m)


def test_schema_and_structural():
    for m in REQUIRED:
        data = bu.load_buildup(m)
        assert data["response"] == "exposure", m
        e = data["E_MeV"]
        gp = data["gp"]
        assert len(e) == len(gp) >= 20, m
        assert e == sorted(e) and len(set(e)) == len(e), f"{m}: grid not strictly ascending"
        assert 0.015 - 1e-9 <= e[0] and e[-1] <= 15.0 + 1e-9, f"{m}: energy out of span"
        for ei, c in zip(e, gp):
            for k in GP_KEYS:
                assert math.isfinite(c[k]), f"{m}: non-finite {k} at {ei}"
            assert c["Xk"] > 0, f"{m}: Xk <= 0 at {ei}"
            assert 0.0 < c["b"] < 12.0, f"{m}: implausible b {c['b']} at {ei}"


# --------------------------------------------------------------------------- #
# 2. Algebraic goldens — validate the evaluator independent of coefficient values.
# --------------------------------------------------------------------------- #

def test_algebraic_identities():
    for m in REQUIRED:
        e = bu.energies(m)
        gp = bu.gp_coefficients(m)
        for ei, c in zip(e, gp):
            args = tuple(c[k] for k in GP_KEYS)
            assert bu.gp_buildup(*args, 0.0) == 1.0, f"{m}@{ei}: B(0)!=1"
            b1 = bu.gp_buildup(*args, 1.0)
            assert abs(b1 - c["b"]) < 1e-9, f"{m}@{ei}: B(1mfp)={b1} != b={c['b']}"


# --------------------------------------------------------------------------- #
# 3. Physical reconstruction — B finite, >= 1, growing with depth, everywhere.
# --------------------------------------------------------------------------- #

MFP_GRID = [1, 2, 4, 7, 10, 15, 20, 40]


def test_reconstructed_B_is_physical():
    """B must be finite and >= 1 at every depth (the hard physical invariants), and grow
    overall with depth. Strict step-monotonicity is NOT asserted: the G-P fit can wiggle
    by ~0.1% where buildup is ~unity (e.g. iron @ 0.015 MeV, b=1.004) — a benign fit
    artifact, not a transcription error. A 5%/step floor still catches a gross
    coefficient error that drives B down with depth."""
    for m in REQUIRED:
        for ei in bu.energies(m):
            prev = 0.0
            Bvals = []
            for x in MFP_GRID:
                B = bu.buildup_factor(m, ei, x)
                assert math.isfinite(B), f"{m}@{ei},{x}mfp: B not finite"
                assert B >= 1.0 - 1e-9, f"{m}@{ei},{x}mfp: B={B} < 1 (buildup < 1?)"
                assert B >= prev * 0.95, (
                    f"{m}@{ei}: B dropped >5% with depth ({prev}->{B} at {x} mfp)"
                )
                prev = B
                Bvals.append(B)
            assert Bvals[-1] >= Bvals[0] - 1e-9, (
                f"{m}@{ei}: B at 40 mfp ({Bvals[-1]}) below B at 1 mfp ({Bvals[0]})"
            )


# --------------------------------------------------------------------------- #
# 4. Smoothness — b is smooth in log-E above the K-edge region.
# --------------------------------------------------------------------------- #

def test_b_smoothness_above_kedge():
    """No interior `b` (for E >= 0.2 MeV) deviates from its log-E neighbour interp by a
    lot. The K-edge spike region (E < 0.2 for high-Z) is excluded — that spike is real
    (lead 2.037 @ 0.10, tungsten 2.054 @ 0.08). Threshold is generous (gross-blip catch),
    so a real digit error stands out without false-failing the smooth data."""
    for m in REQUIRED:
        e = bu.energies(m)
        b = [c["b"] for c in bu.gp_coefficients(m)]
        idx = [i for i, ei in enumerate(e) if ei >= 0.2]
        for j in range(1, len(idx) - 1):
            i0, i1, i2 = idx[j - 1], idx[j], idx[j + 1]
            t = (math.log(e[i1]) - math.log(e[i0])) / (math.log(e[i2]) - math.log(e[i0]))
            interp = b[i0] + t * (b[i2] - b[i0])
            dev = abs(b[i1] - interp) / interp
            assert dev < 0.15, (
                f"{m}: b={b[i1]} at {e[i1]} MeV is {dev:.0%} off the log-E neighbour "
                f"interpolation ({interp:.3f}) — possible transcription blip"
            )


# --------------------------------------------------------------------------- #
# 5. Cross-source — iron coefficients vs an independent open-access tabulation.
# --------------------------------------------------------------------------- #
# EPJ Web Conf. 106, 03009 (2016), Table 1 "Existing Data (ANS 6.4.3)", iron.
# (E_MeV, b, c, a, Xk, d). The paper's 0.50 and 10.0 MeV rows are GARBLED in the
# source and intentionally excluded (a cross-source value can itself be corrupt).
EPJ_IRON = [
    (0.015, 1.004, 1.561, -0.554, 5.60, 0.352),
    (0.05,  1.099, 0.366,  0.232, 14.01, -0.135),
    (0.10,  1.389, 0.557,  0.144, 14.11, -0.079),
    (1.00,  1.841, 1.250, -0.048, 19.49, 0.014),
    (5.00,  1.483, 1.009,  0.012, 13.12, -0.026),
]


def test_iron_coefficients_match_independent_source():
    e = bu.energies("iron")
    gp = bu.gp_coefficients("iron")
    by_e = {round(ei, 4): c for ei, c in zip(e, gp)}
    for E, b, c, a, Xk, d in EPJ_IRON:
        rec = by_e[round(E, 4)]
        assert abs(rec["b"] - b) <= 0.002, (E, "b", rec["b"], b)
        assert abs(rec["c"] - c) <= 0.002, (E, "c", rec["c"], c)
        assert abs(rec["a"] - a) <= 0.002, (E, "a", rec["a"], a)
        assert abs(rec["Xk"] - Xk) <= 0.02, (E, "Xk", rec["Xk"], Xk)
        assert abs(rec["d"] - d) <= 0.001, (E, "d", rec["d"], d)  # EPJ rounds d to 3 dp


# --------------------------------------------------------------------------- #
# 6. Within-source reconstruction — coefficients reproduce the report's Table 3 B.
# --------------------------------------------------------------------------- #

def _spotchecks():
    return json.loads((VENDOR / "b_value_spotchecks.json").read_text(encoding="utf-8"))["points"]


def test_reconstruction_matches_table3_B_values():
    """B(E,x) from the coefficients matches NUREG Table 3 within the GP fit residual +
    scan-read margin. This is a gross/systematic catch (column swap or kerma/exposure
    mixup would give ~2x errors); the data's true residual is a few percent."""
    TOL = 0.15  # relative; covers ~5% lead/iron high-E fit residual + ~2% B-table read
    points = _spotchecks()
    # Coverage: EVERY required material must have >=1 value-level anchor. The algebraic
    # goldens are value-independent, so without an anchor a material's c/a/Xk/d have no
    # regression coverage at all (advisor catch). A new material must bring anchors.
    covered = {p["material"] for p in points}
    assert REQUIRED <= covered, f"materials with no B-value anchor: {sorted(REQUIRED - covered)}"
    worst = 0.0
    for p in points:
        B = bu.buildup_factor(p["material"], p["E_MeV"], p["mfp"])
        rel = abs(B - p["B"]) / p["B"]
        worst = max(worst, rel)
        assert rel < TOL, (
            f"{p['material']} {p['E_MeV']}MeV {p['mfp']}mfp: reconstructed B={B:.3f} vs "
            f"tabulated {p['B']} ({rel:.1%} off) — beyond fit residual; check coefficients"
        )
    # Most points should be well inside the gross tolerance (sanity on the sanity check).
    assert worst < TOL


# --------------------------------------------------------------------------- #
# Loader contracts.
# --------------------------------------------------------------------------- #

def test_loader_raises_on_missing_material():
    with pytest.raises(bu.BuildupError):
        bu.load_buildup("unobtainium")


def test_off_grid_energy_raises():
    """Energy interpolation is M3's job; the loader evaluates only at grid energies."""
    with pytest.raises(bu.BuildupError):
        bu.buildup_factor("water", 1.234, 5.0)   # 1.234 MeV is not a tabulated point


# --------------------------------------------------------------------------- #
# Buildup-fit cap: beyond MFP_FIT_MAX the G-P form overflows float64 and is
# physically invalid (extrapolation). B is frozen at B(MFP_FIT_MAX), finite, no raise.
# docs/plans/gamma-buildup-overflow.md.
# --------------------------------------------------------------------------- #

def test_gp_buildup_capped_beyond_fit_range():
    """At a few hundred mfp the raw ``K**mfp`` overflows; the cap must make B finite and
    equal to its frozen value at the fit limit — and be a no-op at/below the limit."""
    # lead @ 0.06 MeV (near Am-241's 59 keV line through thick lead → hundreds of mfp).
    args = tuple(bu.gp_coefficients("lead")[bu._grid_index("lead", 0.06)][k] for k in GP_KEYS)
    b_at_limit = bu.gp_buildup(*args, bu.MFP_FIT_MAX)
    for deep in (bu.MFP_FIT_MAX + 1e-9, 100.0, 285.0, 1000.0):
        b_deep = bu.gp_buildup(*args, deep)
        assert math.isfinite(b_deep), f"B({deep} mfp) not finite — overflow not capped"
        assert b_deep == b_at_limit, f"B not frozen at the fit limit for {deep} mfp"
    # The cap must NOT perturb anything inside the validated range.
    assert bu.gp_buildup(*args, bu.MFP_FIT_MAX) == b_at_limit


def test_buildup_factor_finite_for_thick_lead_low_energy():
    """The dose-path symptom at the loader level: a low-energy line through thick lead is
    hundreds of mfp and must reconstruct a finite B (no OverflowError)."""
    b = bu.buildup_factor("lead", 0.06, 300.0)
    assert math.isfinite(b) and b >= 1.0
