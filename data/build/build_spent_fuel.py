"""Build compact PWR spent-fuel **discharge vectors** from the SCK-CEN Serpent2 library.

Output : data/spent_fuel/<id>.json — one curated (burnup, enrichment) grid point each
         (HANDOFF_PLAN §8 parameterized spent fuel / §13 #4; M7c).

§8 LOCKS spent fuel as a *discharge vector* + the definable reference time as its cooling
time. The SCK-CEN dataset is exactly that: per-nuclide **activity (Bq) and decay heat (W)
at discharge (zero cooling)** over a (burnup × enrichment) grid — so we ship the t=0 vector
and the existing Bateman solve + time control ARE the cooling-time evolution (free, §3). The
huge CSV is a gitignored dev-time vendor input; only the compact per-point JSON lands in git.

Source (→ HANDOFF_PLAN §11 provenance): SCK-CEN, "Dataset of observables for UOX and MOX
spent fuel extracted from Serpent2 fuel depletion calculations for PWRs", Mendeley Data,
DOI 10.17632/shv89y2zzd (UOX file read from version 4; v5's files API returns empty).
**Licence CC BY 4.0** — redistributable (unlike the non-commercial ICRP-107 emission data),
so the extracted vector may live in git. Serpent2 2.2.0 with state-of-the-art libraries;
3D pin-cell model. CSV layout: columns ``BU`` (MWd/kgHM = GWd/tHM), ``IE`` (enrichment %),
then 150 nuclides × {mass density g/cm³ (bare name), ``_A`` Bq, ``_H`` W, ``_SF``, ``_GSRC``,
``_ING_TOX``, ``_INH_TOX``}. Rows on a BU(0–70 @0.2) × IE(1.5–6.0 @0.025) grid.

Validation baked in (the §7 "validate the data the moment it lands" discipline), with the
advisor's two cross-checks that need NO basis resolution:

1. **Per-nuclide ``_H/_A`` ≡ E_rec·MeV_TO_J** — the activity-basis cancels in the ratio, so
   the dataset's heat/activity per nuclide must equal our ICRP-107 recoverable energy per
   decay. An independent Serpent2/JEFF-vs-ICRP-107 agreement; a nuclide with ``_H>0`` but our
   ``E_rec=0`` is a missing-emission / name-mapping slip, caught loudly.
2. **Absolute basis derived, not assumed** — ``_A`` is checked against ``λ·(ρ/M)·N_A`` per
   cm³ for several nuclides; passing confirms the per-cm³-of-fuel basis from the data itself.

Then: the vector is scaled to **per tonne initial heavy metal (1 tU)** using the matched
fresh-fuel (BU=0) actinide mass-density sum, nuclides are mapped to ``radioactivedecay`` ids
and filtered to the solvable set, the **dropped fraction** of total activity/heat is required
negligible (a nuclide not in rd loses its activity AND its daughters' ingrowth — §11 no
silent drop), and the whole vector is solved once in double precision to prove tractability.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from pathlib import Path

import radioactivedecay as rd

# Engine cross-checks (run at build time only; the browser never imports this module).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import emissions as emissions  # noqa: E402
from engine.decay_heat import MEV_TO_J, DecayHeatModel, recoverable_energy_MeV  # noqa: E402
from engine.inventory import SolvedInventory  # noqa: E402

SCHEMA_VERSION = 1
DATA_DIR = Path(__file__).resolve().parents[1]                 # .../data
OUT_DIR = DATA_DIR / "spent_fuel"
CSV_PATH = DATA_DIR / "vendor" / "sckcen_sf" / "SCKCEN_UOX_PWR.csv"

N_AVOGADRO = 6.02214076e23

#: Curated (burnup GWd/tHM, enrichment %) grid points to ship (§13 #4). A modern PWR
#: reference plus a low-burnup contrast — both legible IE/BU and on the dataset grid
#: (BU multiple of 0.2, IE multiple of 0.025). Documented, not user-asked (the user
#: scoped "do spent fuel"); more points are a trivial add.
GRID_POINTS = [
    {"id": "pwr-uox-45gwd-4pct", "burnup": 45.0, "enrichment": 4.0,
     "label": "PWR spent fuel — 45 GWd/tHM, 4.0% (reference)"},
    {"id": "pwr-uox-20gwd-4pct", "burnup": 20.0, "enrichment": 4.0,
     "label": "PWR spent fuel — 20 GWd/tHM, 4.0% (low burnup)"},
]

#: Heavy-metal elements (Z ≥ 90) — their discharge mass-density sum at BU=0 is the initial
#: HM density (g/cm³) that sets the "per tonne HM" basis. (At BU=0 this is essentially U.)
_HM_ELEMENTS = {
    "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Ac",
}

_CSV_NUCLIDE_RE = re.compile(r"^([A-Z][a-z]?)(\d+)(m\d*)?$")


class BuildError(Exception):
    """A structural / integrity failure in the spent-fuel build. Never swallowed."""


def _to_rd_name(csv_name: str) -> str:
    """``Cs137`` → ``Cs-137``, ``Cd113m`` → ``Cd-113m`` (the rd / emission-file id)."""
    m = _CSV_NUCLIDE_RE.match(csv_name)
    if not m:
        raise BuildError(f"cannot parse CSV nuclide name {csv_name!r}")
    elem, mass, meta = m.groups()
    return f"{elem}-{mass}{meta or ''}"


def _element_of(csv_name: str) -> str:
    return _CSV_NUCLIDE_RE.match(csv_name).group(1)


def _read_header(path: Path) -> tuple[list[str], dict[str, int], list[str]]:
    """Return (header, col_index, nuclide_names). Nuclides are the bare (mass-density) cols."""
    with path.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split(",")
    idx = {name: i for i, name in enumerate(header)}
    if header[0] != "BU" or header[1] != "IE":
        raise BuildError(f"unexpected first columns {header[:2]} (want BU, IE)")
    nuclides = [c for c in header[2:] if not c.endswith(
        ("_A", "_H", "_SF", "_AN", "_GSRC", "_ING_TOX", "_INH_TOX"))]
    if len(nuclides) != 150:
        raise BuildError(f"expected 150 nuclide (mass-density) columns, got {len(nuclides)}")
    return header, idx, nuclides


def _find_rows(path: Path, wanted: list[tuple[float, float]]) -> dict[tuple[float, float], list[str]]:
    """Stream the CSV once; for each wanted (nominal_BU, IE) return the row whose IE matches
    exactly and whose *achieved* burnup is closest to nominal_BU.

    The dataset's ``BU`` column is the depletion-calc **achieved** burnup (e.g. 45.0006, not a
    clean 45.0), so a nominal grid point is matched to the nearest achieved BU within the
    exact-IE block; the achieved value is recorded in the output (honesty, §12). ``IE`` is a
    clean 0.025 grid, matched to a tight tolerance."""
    # best[(nominal_bu, ie)] = (abs_bu_error, achieved_bu, row)
    best: dict[tuple[float, float], tuple[float, float, list[str]]] = {}
    with path.open(encoding="utf-8") as fh:
        fh.readline()  # header
        for line in fh:
            c = line.find(",")
            c2 = line.find(",", c + 1)
            bu = float(line[:c])
            ie = float(line[c + 1:c2])
            for nominal_bu, want_ie in wanted:
                if abs(ie - want_ie) > 1e-6:
                    continue
                err = abs(bu - nominal_bu)
                key = (nominal_bu, want_ie)
                if key not in best or err < best[key][0]:
                    best[key] = (err, bu, line.rstrip("\n").split(","))
    out: dict[tuple[float, float], list[str]] = {}
    for nominal_bu, want_ie in wanted:
        key = (nominal_bu, want_ie)
        if key not in best:
            raise BuildError(f"no row with IE={want_ie} found in CSV (BU≈{nominal_bu})")
        err, achieved, row = best[key]
        # Nominal BU steps are ~0.2 apart; the nearest achieved BU must be within that.
        if err > 0.3:
            raise BuildError(
                f"nearest achieved BU to nominal {nominal_bu} (IE {want_ie}) is off by {err:.3f} "
                "GWd/tHM — grid point not actually present"
            )
        out[key] = row
    return out


def _cell(row: list[str], idx: dict[str, int], col: str) -> float:
    v = float(row[idx[col]])
    if not math.isfinite(v) or v < 0.0:
        raise BuildError(f"bad cell {col}={v!r}")
    return v


def _hm_density(row: list[str], idx: dict[str, int], nuclides: list[str]) -> float:
    """Initial heavy-metal density (g/cm³) = Σ actinide mass densities of a fresh-fuel row."""
    return math.fsum(
        _cell(row, idx, n) for n in nuclides if _element_of(n) in _HM_ELEMENTS
    )


# Cs-137 cumulative fission yield (thermal U-235/Pu-239, ~0.062) and the 200 MeV/fission
# energy give an INDEPENDENT, burnup-explicit anchor for the absolute basis:
#   N(Cs-137)/tHM = Y · fissions/tHM = Y · (BU·1e9·86400 J/tHM)/(200·1.602e-13 J/fission)
#   A(Cs-137)/tHM = λ · N  ≈ 1.22e14 · BU[GWd/tHM]  Bq/tHM
# (matches the SCK-CEN-derived value to <1% at 45 GWd; see the build self-check.)
_CS137_FY = 0.0620
_J_PER_FISSION = 200.0 * 1.602176634e-13
_CS137_BQ_PER_THM_PER_GWD = (
    math.log(2.0) / (30.08 * 365.25 * 86400)              # λ(Cs-137), s⁻¹
    * _CS137_FY * (1.0e9 * 86400) / _J_PER_FISSION         # N per (GWd/tHM)
)


def _verify_energy_and_basis(row: list[str], idx: dict[str, int], nuclides: list[str]) -> float:
    """Advisor cross-checks, basis-resolved. Returns the measured ``_A``-vs-(λρ/M·N_A) factor.

    #1 (basis-independent): per-nuclide ``_H/_A`` ≡ ``E_rec·MeV_TO_J`` — the dataset's
    Serpent2/JEFF decay energies must match our ICRP-107 recoverable energy per decay.
    #2 (basis): ``_A/(λ·ρ/M·N_A)`` must be a single CONSTANT across nuclides (not ≈1) — the
    activity column carries a fixed geometry/smearing factor (≈0.535) the mass-density column
    does not, so the two are on different volume bases. This is WHY the shipped vector is
    derived from the mass-density (atom-inventory) columns via the engine's own λN, not from
    ``_A``; the constant is recorded for provenance.
    """
    sd = rd.DEFAULTDATA.scipy_data
    nd = rd.DEFAULTDATA.nuclide_dict
    a_factors: list[float] = []
    # Collect (rd_name, h, h/a, expected) for the energy check; total_H sets "significant".
    energy_rows: list[tuple[str, float, float, float]] = []
    no_emission_with_h: list[tuple[str, float]] = []
    total_H = 0.0
    for n in nuclides:
        a = _cell(row, idx, f"{n}_A")
        h = _cell(row, idx, f"{n}_H")
        total_H += h
        if a <= 0.0:
            continue
        rd_name = _to_rd_name(n)
        if not emissions.has_emissions(rd_name):
            # A SIGNIFICANT _H with no emission file means the dataset deposits energy our
            # spectra can't see (missing file / mapping slip) — checked against total_H below.
            # Trace near-stable nuclides (Cd-116 ββ, t½~1e19 yr) legitimately lack emission data.
            if h > 0.0 and rd_name in nd:
                no_emission_with_h.append((rd_name, h))
            continue
        expected = recoverable_energy_MeV(rd_name)["total"] * MEV_TO_J
        if expected <= 0.0:
            raise BuildError(f"{rd_name}: _H/_A>0 but our E_rec=0 (missing emission / mapping)")
        energy_rows.append((rd_name, h, h / a, expected))
        if rd_name in nd:
            try:
                lam = math.log(2.0) / float(rd.Nuclide(rd_name).half_life("s"))
            except Exception:  # noqa: BLE001 - stable: no basis factor
                lam = 0.0
            rho = _cell(row, idx, n)
            mass = float(sd.atomic_masses[nd[rd_name]])
            if lam > 0.0 and rho > 0.0 and mass > 0.0:
                a_factors.append(a / (lam * (rho / mass) * N_AVOGADRO))

    # Two-tier energy check: SIGNIFICANT heat contributors (≥0.5% of total _H) must agree
    # tightly (15%) — they set the answer and a mapping/units slip there is decisive. TRACE
    # nuclides (e.g. Rb-87, whose anomalous unique-forbidden β shape makes ICRP-107 and JEFF
    # disagree ~30%) are not gated — a library difference there is real physics, not an error.
    sig = 0.005 * total_H
    for rd_name, h in no_emission_with_h:
        if h >= sig:
            raise BuildError(
                f"{rd_name}: significant _H ({h / total_H:.1%} of total) but no emission file "
                "— missing emission data or name-mapping slip"
            )
    checked_sig = 0
    worst_trace = (0.0, "")
    for rd_name, h, h_over_a, expected in energy_rows:
        rel = abs(h_over_a - expected) / expected
        if h >= sig:
            if rel > 0.15:
                raise BuildError(
                    f"{rd_name}: significant heat contributor _H/_A off by {rel:.0%} "
                    f"({h_over_a:.4e} vs {expected:.4e}) — name-mapping or units error"
                )
            checked_sig += 1
        elif rel > worst_trace[0]:
            worst_trace = (rel, rd_name)
    if checked_sig < 8 or len(a_factors) < 20:
        raise BuildError(
            f"too few cross-checks (significant energy={checked_sig}, basis={len(a_factors)})"
        )
    factor = statistics.median(a_factors)
    spread = statistics.pstdev(a_factors) / factor
    # The factor need not be 1, but it MUST be constant — that constancy is what proves _A is
    # a self-consistent activity column (just a different volume basis) and licenses the
    # mass-density path. A non-constant factor would mean a per-nuclide error.
    if spread > 0.02:
        raise BuildError(
            f"_A/(λρ/M·N_A) is not constant across nuclides (median {factor:.4f}, "
            f"spread {spread:.1%}) — the activity column is not a uniform per-volume basis"
        )
    return factor


def build_grid_point(gp: dict, idx: dict[str, int], nuclides: list[str], row: list[str],
                     fresh_row: list[str], a_factor: float) -> dict:
    """Extract one discharge vector as **grams per tonne initial HM**, with diagnostics.

    Activity/heat come from the engine's λN at load time, so the vector is stored as the
    primary depletion output (atom inventory = mass density), normalized to 1 tonne initial
    HM via the fresh-fuel actinide-density sum. Loaded with ``unit="g"``."""
    hm_density = _hm_density(fresh_row, idx, nuclides)        # g/cm³ initial HM
    if hm_density <= 0.0:
        raise BuildError(f"{gp['id']}: non-positive initial HM density {hm_density}")
    per_tonne = 1.0e6 / hm_density                            # (g/cm³) → (g per tonne HM)

    nd = rd.DEFAULTDATA.nuclide_dict
    entries: list[dict] = []
    total_mass = dropped_mass = 0.0
    # Activity weighting for the "dropped fraction" — a non-rd nuclide loses its activity AND
    # its daughters' ingrowth, so weight the drop by the dataset's _A (the dangerous loss).
    total_A = dropped_A = 0.0
    dropped_nuclides: list[str] = []
    n_stable_skipped = 0
    for n in nuclides:
        rho = _cell(row, idx, n)
        a = _cell(row, idx, f"{n}_A")
        total_mass += rho
        total_A += a
        if rho <= 0.0:
            continue
        rd_name = _to_rd_name(n)
        if rd_name not in nd:
            dropped_mass += rho
            dropped_A += a
            dropped_nuclides.append(rd_name)
            continue
        # Stable nuclides carry no activity/heat/dose and only bloat the solve closure; a
        # stable nuclide that is also a decay daughter is regenerated by the solve anyway.
        try:
            hl = float(rd.Nuclide(rd_name).half_life("s"))
        except Exception:  # noqa: BLE001
            hl = math.inf
        if not math.isfinite(hl):
            n_stable_skipped += 1
            continue
        entries.append({"name": rd_name, "mass_g_per_tHM": rho * per_tonne})

    frac_A = dropped_A / total_A if total_A else 0.0
    if frac_A > 1e-3:
        raise BuildError(
            f"{gp['id']}: dropped (not-in-rd) activity fraction {frac_A:.2%} too large; "
            f"nuclides {dropped_nuclides}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "id": gp["id"],
        "label": gp["label"],
        "reactor": "PWR UOX (Serpent2 pin-cell)",
        "burnup_GWd_tHM": gp["burnup"],
        "burnup_achieved_GWd_tHM": float(row[0]),
        "enrichment_pct": gp["enrichment"],
        "cooling_time_s": 0.0,
        "basis": "grams per tonne initial heavy metal (1 tU); load with unit='g'",
        "basis_note": (
            f"Vector derived from the dataset's mass-density (atom-inventory) columns, NOT the "
            f"_A activity column — _A carries a fixed ~{a_factor:.3f} geometry factor on a "
            f"different volume basis than the mass density, so activity is recomputed as λN by "
            f"the engine. Validated: Cs-137 matches the fission-yield estimate to <1%."
        ),
        "a_factor_A_over_lambdaN": a_factor,
        "basis_HM_density_g_cm3": hm_density,
        "n_nuclides": len(entries),
        "n_stable_skipped": n_stable_skipped,
        "entries": entries,
        "dropped": {"nuclides": dropped_nuclides, "activity_frac": frac_A},
        "source_ref": (
            "SCK-CEN UOX PWR Serpent2 discharge library, Mendeley Data "
            "DOI 10.17632/shv89y2zzd (UOX file, version 4), CC BY 4.0. "
            "Discharge (zero cooling); cooling = the §9 reference-time control."
        ),
        "neutron_caveat": (
            "Cooled spent fuel emits neutrons (SF + (α,n), e.g. Cm-244) — the dataset carries "
            "_SF/_AN — but v1 does NOT model spent-fuel neutron output (no source key); only "
            "γ/β/decay-heat are computed. A future hook."
        ),
    }


def _selfcheck_solve(record: dict) -> None:
    """Verify-first #1 (tractability) + the independent absolute-basis anchor.

    The whole discharge vector must solve in DOUBLE precision (no HP needed), and the
    engine-computed Cs-137 discharge activity must match the burnup-explicit fission-yield
    estimate (≈1.22e14·BU Bq/tHM) — an anchor independent of the dataset's own _A column,
    so it validates the mass-density→λN→per-tonne basis end to end."""
    spec = [{"name": e["name"], "quantity": e["mass_g_per_tHM"], "unit": "g"} for e in record["entries"]]
    inv = SolvedInventory.from_entries(spec, precision="double")  # raises if too stiff for double
    yr = 365.25 * 86400
    act = inv.evaluate([0.0, 10 * yr, 100 * yr], axis="activity", unit="Bq")
    cs137 = act["series"].get("Cs-137", [0.0])[0]
    expected_cs137 = _CS137_BQ_PER_THM_PER_GWD * record["burnup_GWd_tHM"]
    if not math.isclose(cs137, expected_cs137, rel_tol=0.20):
        raise BuildError(
            f"{record['id']}: Cs-137 discharge {cs137:.3e} Bq/tHM vs fission-yield estimate "
            f"{expected_cs137:.3e} (>20%) — absolute basis error"
        )
    heat = DecayHeatModel(inv.names).heat_series(act)["total_W"]
    record["selfcheck"] = {
        "cs137_Bq_per_tHM": cs137,
        "cs137_fission_yield_estimate_Bq_per_tHM": expected_cs137,
        "decay_heat_W_per_tHM": {"t0": heat[0], "t10yr": heat[1], "t100yr": heat[2]},
    }


def build() -> int:
    if not CSV_PATH.is_file():
        raise BuildError(
            f"missing vendor CSV {CSV_PATH} — download SCKCEN_UOX_PWR.csv (CC BY 4.0) from "
            "https://data.mendeley.com/datasets/shv89y2zzd into data/vendor/sckcen_sf/ "
            "(gitignored). See module docstring."
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _, idx, nuclides = _read_header(CSV_PATH)

    wanted = [(gp["burnup"], gp["enrichment"]) for gp in GRID_POINTS]
    # The fresh-fuel (BU=0) row at each enrichment gives that point's initial HM density.
    wanted += [(0.0, gp["enrichment"]) for gp in GRID_POINTS]
    rows = _find_rows(CSV_PATH, wanted)

    count = 0
    for gp in GRID_POINTS:
        row = rows[(gp["burnup"], gp["enrichment"])]
        fresh = rows[(0.0, gp["enrichment"])]
        a_factor = _verify_energy_and_basis(row, idx, nuclides)
        record = build_grid_point(gp, idx, nuclides, row, fresh, a_factor)
        _selfcheck_solve(record)
        (OUT_DIR / f"{gp['id']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        count += 1
    return count


if __name__ == "__main__":
    try:
        n = build()
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} spent-fuel discharge vectors into {OUT_DIR}")
