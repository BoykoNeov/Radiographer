"""M5 neutron dose-core benchmarks (HANDOFF_PLAN.md §6.3, §10).

The crux is the **validation triangle**: fold the *independently reconstructed* Cf-252
spectrum against the *independently vendored* ICRP-74 neutron H*(10) table → a
spectrum-averaged h̄, and require it to equal the **published** ISO-8529/ICRP-74 value.
Three mutually independent things meeting (spectrum, conversion table, fold+normalization
+geometry) validate the whole chain in one shot — and this agreement IS the independent
cross-check for the DEGRADED (unmerged-PR) neutron H*(10) table (cf. the photon IAEA check).

- **Cf-252 spectrum-averaged h*(10) = 373 pSv·cm²** (ICRP-74) — read from Table 1 of the
  open-access JANP-4-005 (Sabharwal et al., scholars.direct; a SEPARATE group's
  spectrum-averaged calculation). The fold gives ~383 (+3 %, the Maxwellian vs the tabulated
  ISO spectrum), also consistent with the commonly-cited ISO 8529-2 ~385. This is the read
  anchor (not a self-consistent hardcode) — a unit slip or wrong column misses by far more.
- **Dose-rate constant ≈ 2.5 mrem/h per µg at 1 m** — the well-known field magnitude, here a
  DERIVED consequence of two sourced numbers (specific yield 2.3×10⁶ n/s/µg × h̄) that also
  exercises the n/decay × activity × 1/4πd² geometry end to end.
- w_R is NOT double-counted (the coefficients are already Sv/fluence); both quantities Sv;
  effective < H*(10) for Cf-252 (geometry asymmetry); solve-once/evaluate-many; gray-out gate.

Internally everything is SI (Sv/s); we convert to mrem/h / µSv/h at the boundary.
"""

from __future__ import annotations

import pytest

from engine import neutron_source as nsrc
from engine.inventory import SolvedInventory
from engine.neutron_dose import NeutronDoseError, NeutronDoseModel
from engine.photon_interp import ABOVE_GRID

SV_S_TO_MREM_H = 3.6e8        # Sv/s → mrem/h  (×3600 s/h × 1e5 mrem/Sv)
SV_S_TO_USV_H = 3.6e9         # Sv/s → µSv/h


# --- the validation triangle ---------------------------------------------------------

def test_cf252_spectrum_averaged_h10_matches_published():
    # Fold (reconstructed Maxwellian × vendored ICRP-74 neutron table) vs an EXTERNALLY READ
    # value: bare Cf-252 H*(10) = 373 pSv·cm² (ICRP-74), Table 1 of the open-access JANP-4-005
    # (a separate group's spectrum-averaged calc). The fold ~383 sits +2.7 % above it (the
    # Maxwellian vs the tabulated ISO spectrum) and ≈ the commonly-cited ISO 8529-2 ~385 —
    # inside the few-% inter-method spread. A unit slip / wrong column misses by far more.
    m = NeutronDoseModel("Cf-252", "ambient_H10")
    assert m.hbar_pSv_cm2 == pytest.approx(373.0, rel=0.05)


def test_ambe_spectrum_averaged_h10_matches_iso():
    # AmBe validation triangle: fold the ISO 8529 Am–Be reference spectrum (IAEA TRS-403
    # Table 4.V) against the vendored ICRP-74 neutron H*(10) table → 393.6 pSv·cm². This
    # agrees with TRS-403 Table 4.IV's PUBLISHED ISO H*(10) = 391 to +0.66% (well inside the
    # inter-method spread; Table 4.V's own "spectrum-weighted responses" lists 395 — a ~1%
    # conversion-coefficient-set difference). Two anchors:
    m = NeutronDoseModel("AmBe", "ambient_H10")
    # (a) physics: matches the externally published ISO value (a unit slip misses by far more)
    assert m.hbar_pSv_cm2 == pytest.approx(391.0, rel=0.03)
    # (b) tight regression pin on the built data + fold — a 1% drift must FAIL, not pass silently
    assert m.hbar_pSv_cm2 == pytest.approx(393.56, rel=0.005)


def test_ambe_source_gamma_override_has_4438_line():
    # AmBe's clean discrete 4.438 MeV reaction γ flows through the override (contrast Cf-252's
    # empty continuum). yield = n/decay (5.95e-5) × γ/n ratio R=0.575 (Liu et al., recommended).
    m = NeutronDoseModel("AmBe", "ambient_H10")
    ov = m.source_gamma_override()
    assert set(ov) == {"Am-241"}
    (line,) = ov["Am-241"]
    assert line["E_MeV"] == pytest.approx(4.438)
    assert line["yield"] == pytest.approx(5.9459e-5 * 0.575, rel=1e-3)


def test_cf252_dose_rate_constant_per_microgram_at_1m():
    # 1 µg Cf-252 at 1 m, bare → H*(10) ≈ 2.5 mrem/h — the well-known field magnitude, here a
    # DERIVED consequence of two sourced numbers (specific yield 2.3e6 n/s/µg × h̄ ≈ 379) not a
    # separate citation. Exercises n/decay × activity (λN from a real solve) × 1/4πd² end to end.
    inv = SolvedInventory.from_spec({"Cf-252": 1.0}, "ug")
    res = inv.evaluate([0.0], axis="activity", unit="Bq")
    acts = {n: res["series"][n][0] for n in res["nuclides"]}

    m = NeutronDoseModel("Cf-252", "ambient_H10")
    rate = m.dose_rate(acts, 1.0)  # Sv/s
    assert rate * SV_S_TO_MREM_H == pytest.approx(2.5, rel=0.10)
    # Sanity: the source strength S = n/decay · A is ~2.3e6 n/s per µg (canonical).
    s = m.neutrons_per_decay * acts["Cf-252"]
    assert s == pytest.approx(2.30e6, rel=0.05)


# --- quantities: both Sv, w_R not double-counted, geometry asymmetry ------------------

def test_both_quantities_are_sv_and_effective_below_h10():
    h10 = NeutronDoseModel("Cf-252", "ambient_H10")
    eff_iso = NeutronDoseModel("Cf-252", "effective", geometry="ISO")
    eff_ap = NeutronDoseModel("Cf-252", "effective", geometry="AP")
    assert h10.si_unit == eff_iso.si_unit == "Sv"
    # For fast neutrons effective dose (whole-body) is below H*(10); ISO < AP (orientation).
    assert eff_iso.hbar_pSv_cm2 < h10.hbar_pSv_cm2
    assert eff_iso.hbar_pSv_cm2 < eff_ap.hbar_pSv_cm2
    # Effective AP for the Cf-252 spectrum ~350 pSv·cm² — an INTERNAL regression guard on the
    # ICRP-116 fold (that table is clean/verbatim + transform-validated in
    # test_conversion_data). NOT anchored to JANP-4-005's eAP=309: that is ICRP-74 effective
    # dose (ICRP-60 weights), a DIFFERENT vintage than our ICRP-116 (§6.4) — not comparable.
    assert eff_ap.hbar_pSv_cm2 == pytest.approx(350.0, rel=0.10)


def test_quantity_geometry_guards():
    with pytest.raises(NeutronDoseError):
        NeutronDoseModel("Cf-252", "effective")              # effective needs a geometry
    with pytest.raises(NeutronDoseError):
        NeutronDoseModel("Cf-252", "ambient_H10", geometry="AP")  # H*(10) takes none
    with pytest.raises(NeutronDoseError):
        NeutronDoseModel("Cf-252", "equivalent")             # unknown quantity


# --- gray-out gate / missing-data loudness -------------------------------------------

def test_unknown_source_raises_loudly():
    with pytest.raises(NeutronDoseError):
        NeutronDoseModel("NoSuchSource-999", "ambient_H10")


def test_missing_parent_activity_raises():
    m = NeutronDoseModel("Cf-252", "ambient_H10")
    with pytest.raises(NeutronDoseError):
        m.dose_rate({"Co-60": 1.0e9}, 1.0)                   # parent Cf-252 absent
    with pytest.raises(NeutronDoseError):
        m.dose_rate({"Cf-252": 1.0e9}, 0.0)                  # singular at d=0


# --- solve-once / evaluate-many: the per-decay coeff matvec over a time grid ----------

def test_dose_rate_series_tracks_parent_activity_over_grid():
    inv = SolvedInventory.from_spec({"Cf-252": 1.0}, "ug")
    yr = 365.25 * 24 * 3600.0
    grid = [0.0, 2.645 * yr, 2 * 2.645 * yr]   # 0, 1, 2 Cf-252 half-lives
    res = inv.evaluate(grid, axis="activity", unit="Bq")
    m = NeutronDoseModel("Cf-252", "ambient_H10")
    out = m.dose_rate_series(res, 1.0)

    assert out["si_unit"] == "Sv" and out["source"] == "Cf-252" and out["parent"] == "Cf-252"
    a = res["series"]["Cf-252"]
    for j in range(len(grid)):
        assert out["rate_si"][j] / out["rate_si"][0] == pytest.approx(a[j] / a[0], rel=1e-12)
    # ~half the rate after one Cf-252 half-life (parent activity halves).
    assert out["rate_si"][1] / out["rate_si"][0] == pytest.approx(0.5, rel=1e-3)


def test_dose_rate_series_rejects_non_activity_result():
    inv = SolvedInventory.from_spec({"Cf-252": 1.0}, "ug")
    res_atoms = inv.evaluate([0.0], axis="atoms")
    m = NeutronDoseModel("Cf-252", "ambient_H10")
    with pytest.raises(NeutronDoseError):
        m.dose_rate_series(res_atoms, 1.0)


# --- source-correlated gamma override -------------------------------------------------

def test_cf252_source_gamma_override_empty():
    # Cf-252 prompt-fission γ is a continuum, not modeled in M5 (honesty register); the
    # override is empty (AmBe's discrete 4.438 MeV line would populate it).
    m = NeutronDoseModel("Cf-252", "ambient_H10")
    assert m.source_gamma_override() == {}


# --- off-grid: above the 20 MeV neutron H*(10) grid is a loud error -------------------

def test_above_grid_spectrum_bin_raises(monkeypatch):
    # Dropping flux above the grid UNDERESTIMATES dose — the dangerous direction. Inject a
    # 25 MeV bin (above the 20 MeV H*(10) end): construction must raise loudly.
    real_spec = nsrc.spectrum("Cf-252")
    real_reps = nsrc.representative_energies("Cf-252")

    monkeypatch.setattr(nsrc, "spectrum", lambda k: ([24.0], [26.0], [1.0]))
    monkeypatch.setattr(nsrc, "representative_energies", lambda k: [25.0])
    with pytest.raises(NeutronDoseError):
        NeutronDoseModel("Cf-252", "ambient_H10")
    # sanity: the real data is unaffected (monkeypatch is scoped to the test)
    assert real_spec[2] and real_reps
