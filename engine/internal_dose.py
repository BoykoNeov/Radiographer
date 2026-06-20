r"""Internal (committed) dose engine — intake of a solved inventory (HANDOFF_PLAN §2/§11).

The committed effective dose **E(50)** from **intaking** the whole inventory (by ingestion or
inhalation) at reference time ``t`` is, per §3 ("solve once, evaluate many"):

    E50(t) = Σ_nuclides  e_n[Sv/Bq] · A_n(t)            (Sv — a committed SCALAR per intake-time)

``e_n`` is the per-nuclide committed-effective-dose coefficient for the chosen **route**
(ingestion / inhalation) and **population** (``public_adult`` ICRP-72 / ``worker`` ICRP-68),
loaded from ``data/internal_dose/<population>.json`` (built by
``data/build/build_internal_dose.py`` from ICRP-119; see ``docs/plans/M13-internal-dose.md``).
It depends on neither distance, time, nor activity — so the time grid is a single matvec of the
fixed ``e_n`` against the activity series from ``inventory.SolvedInventory.evaluate`` (exactly
like :class:`engine.dose.GammaDoseModel`), with **no distance, no 1/4πd², no geometry**.

**Progeny convention (LOCKED, §M13):** the ICRP base coefficients are *parent-only with in-vivo
ingrowth* — summing them over the FULL tracked inventory is correct and does NOT double-count
(in-can progeny is a distinct atom population from in-body-ingrown progeny). This module assumes
the bundled data are the base per-nuclide coefficients, never the "+"-bundled equilibrium ones.

**Quantity/time semantics differ from the external panels (§M13):** this is a committed scalar
in **Sv (E(50))**, *not a rate* — the series reads "committed dose if intaken at time t" (Sv, not
Sv/s). There is no rate to integrate over an exposure duration, so an accumulate/integrate
feature must be disabled. E(50) is effective Sv but **not comparable** to external H\*(10) (Sv) or
air-kerma (Gy) — the same never-summed discipline (§6.4, §11).

**No silent errors (CLAUDE.md), three explicit coverage states:** every tracked nuclide is
classified as
  * **covered** — has a coefficient for this route/population; contributes;
  * **noble-gas N/A** (He/Ne/Ar/Kr/Xe/Rn) — physically has no Sv/Bq *intake* coefficient (ICRP-119
    Annex C gives submersion dose *rates*, a different quantity); excluded WITHOUT making the
    result a lower bound;
  * **uncovered** — a tracked nuclide simply absent from the curated set; excluded AND flags the
    result as a **lower bound** (a missing coefficient *underestimates* committed dose — the
    dangerous direction), surfaced loudly, mirroring the spent-fuel lower-bound pattern.
A malformed/missing dataset, or an unknown route/population/absorption-type, raises loudly.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

SCHEMA_VERSION = 1
UNITS = "Sv_per_Bq"

#: Supported intake routes.
ROUTES: tuple[str, ...] = ("ingestion", "inhalation")
#: Supported exposed populations (both shipped, user-selectable — §M13).
POPULATIONS: tuple[str, ...] = ("public_adult", "worker")
#: Inhalation lung-absorption types (ICRP-66/68 HRTM): Fast / Moderate / Slow.
ABSORPTION_TYPES: tuple[str, ...] = ("F", "M", "S")

#: Elements with NO Sv/Bq intake coefficient — noble gases. A nuclide of one of these is the
#: distinct "N/A — no intake pathway" state (NOT "uncovered"); folding it would falsely imply a
#: missing intake dose that physically does not exist (advisor, §M13).
NOBLE_GAS_ELEMENTS: frozenset[str] = frozenset({"He", "Ne", "Ar", "Kr", "Xe", "Rn"})

#: The committed quantity this engine produces. A scalar Sv, never a rate (no ``per`` second).
QUANTITY = "committed_effective_E50"
SI_UNIT = "Sv"

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "internal_dose"
_data_root = _DEFAULT_ROOT


class InternalDoseError(Exception):
    """Loud failure in the internal-dose path — never swallowed, never a fallback number."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different internal-dose directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load.cache_clear()


def data_root() -> Path:
    return _data_root


def _element(nuclide: str) -> str:
    """``"Cs-137" -> "Cs"`` (the element symbol before the mass number)."""
    base = nuclide.split("-", 1)[0]
    if not base or not base[0].isalpha():
        raise InternalDoseError(f"unparseable nuclide id {nuclide!r}")
    return base


def has(population: str) -> bool:
    return (_data_root / f"{population}.json").is_file()


@lru_cache(maxsize=None)
def load(population: str) -> dict:
    """Load and validate one population's committed-dose-coefficient record."""
    if population not in POPULATIONS:
        raise InternalDoseError(
            f"unknown population {population!r} (expected one of {POPULATIONS})"
        )
    path = _data_root / f"{population}.json"
    if not path.is_file():
        raise InternalDoseError(
            f"no internal-dose data for population={population!r} (expected {path}); "
            "run `python data/build/build_internal_dose.py`"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise InternalDoseError(
            f"{path.name}: schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    if data.get("population") != population:
        raise InternalDoseError(
            f"{path.name}: embedded population {data.get('population')!r} != {population!r}"
        )
    if data.get("units") != UNITS:
        raise InternalDoseError(f"{path.name}: unexpected units {data.get('units')!r}")
    if data.get("progeny_convention") != "parent_only_in_vivo_ingrowth":
        # A "+"-bundled dataset would double-count against separately tracked progeny (§M13).
        raise InternalDoseError(
            f"{path.name}: progeny_convention {data.get('progeny_convention')!r} is not the "
            "required parent-only (in-vivo-ingrowth) convention — refusing to risk double-count"
        )
    coeffs = data.get("coefficients")
    if not isinstance(coeffs, dict) or not coeffs:
        raise InternalDoseError(f"{path.name}: missing/empty coefficients")
    return data


def coefficient(
    nuclide: str,
    route: str,
    population: str,
    *,
    absorption_type: Optional[str] = None,
) -> float:
    """Committed effective dose coefficient ``e(50)`` (Sv/Bq) for one nuclide/route/population.

    For ``inhalation`` the value is the ``absorption_type`` requested, else the dataset's
    ``default_type`` (the ICRP-recommended type for unspecified chemical form). Raises if the
    nuclide, route, or requested type is absent — the caller (model) decides coverage policy;
    this low-level accessor never substitutes a silent zero.
    """
    if route not in ROUTES:
        raise InternalDoseError(f"unknown route {route!r} (expected one of {ROUTES})")
    rec = load(population)["coefficients"].get(nuclide)
    if rec is None or route not in rec:
        raise InternalDoseError(
            f"no {route} coefficient for {nuclide!r} (population={population!r})"
        )
    sub = rec[route]
    if route == "ingestion":
        return float(sub["e_Sv_Bq"])
    # inhalation
    types = sub["types"]
    atype = absorption_type or sub["default_type"]
    if atype not in ABSORPTION_TYPES:
        raise InternalDoseError(f"unknown absorption type {atype!r} (expected {ABSORPTION_TYPES})")
    if atype not in types:
        raise InternalDoseError(
            f"{nuclide!r} has no Type-{atype} inhalation coefficient "
            f"(tabulated: {sorted(types)}); default_type={sub['default_type']!r}"
        )
    return float(types[atype])


class InternalDoseModel:
    """Solve-once committed-dose coefficients for a fixed (route, population, absorption type).

    Build once from the nuclides in a solved inventory; then :meth:`committed_dose_series` is a
    single matvec of the fixed ``e_n`` against the activity grid (no per-tick re-summation).
    Coverage is classified at build time into covered / noble-gas-N/A / uncovered.
    """

    def __init__(
        self,
        nuclides: Sequence[str],
        route: str,
        population: str,
        *,
        absorption_type: Optional[str] = None,
    ):
        if route not in ROUTES:
            raise InternalDoseError(f"unknown route {route!r} (expected one of {ROUTES})")
        if population not in POPULATIONS:
            raise InternalDoseError(
                f"unknown population {population!r} (expected one of {POPULATIONS})"
            )
        if absorption_type is not None and absorption_type not in ABSORPTION_TYPES:
            raise InternalDoseError(
                f"unknown absorption type {absorption_type!r} (expected {ABSORPTION_TYPES})"
            )
        self.route = route
        self.population = population
        self.absorption_type = absorption_type  # None ⇒ each nuclide's default_type

        data = load(population)
        self.amad_um = data.get("amad_um")
        self.icrp_publication = data.get("icrp_publication")
        coeffs: dict[str, float] = {}
        types_used: dict[str, str] = {}
        f1_used: dict[str, float] = {}
        covered: list[str] = []
        noble_gas_na: list[str] = []
        uncovered: list[str] = []
        for n in nuclides:
            rec = data["coefficients"].get(n)
            if rec is not None and route in rec:
                coeffs[n] = coefficient(n, route, population, absorption_type=absorption_type)
                if route == "inhalation":
                    types_used[n] = absorption_type or rec["inhalation"]["default_type"]
                else:  # ingestion — capture the f1 (gut transfer factor) provenance
                    f1 = rec["ingestion"].get("f1")
                    if f1 is not None:
                        f1_used[n] = float(f1)
                covered.append(n)
            elif _element(n) in NOBLE_GAS_ELEMENTS:
                noble_gas_na.append(n)
            else:
                uncovered.append(n)
        self.coeff = coeffs
        self.types_used = types_used
        self.f1_used = f1_used
        self.covered = covered
        self.noble_gas_na = noble_gas_na
        self.uncovered = uncovered

    # -- accessors ---------------------------------------------------------
    def per_nuclide_coeff(self) -> dict[str, float]:
        """``{nuclide: e_Sv_Bq}`` for the covered nuclides (the live per-nuclide breakdown
        source — the caller folds against ``A_n(t)`` at a cursor, no re-fold; §3)."""
        return dict(self.coeff)

    # -- evaluation (evaluate many) ---------------------------------------
    def committed_dose_series(self, evaluate_result: dict) -> dict:
        """Committed E(50) series (Sv) from a ``SolvedInventory.evaluate`` activity result.

        The §3 "evaluate many" path: one matvec ``Σ e_n · A_n(t)`` over the activity grid. The
        result is a committed **scalar Sv at each intake-time t** — NOT a rate (``per`` is null;
        there is no integrate). ``lower_bound`` is True iff any tracked nuclide is *uncovered*
        (noble-gas N/A does NOT set it).
        """
        if evaluate_result.get("axis") != "activity" or evaluate_result.get("unit") != "Bq":
            raise InternalDoseError(
                "committed_dose_series needs an activity-in-Bq evaluate() result "
                f"(got axis={evaluate_result.get('axis')!r}, unit={evaluate_result.get('unit')!r})"
            )
        series: dict[str, list[float]] = evaluate_result["series"]
        times = evaluate_result["times_s"]
        committed = [0.0] * len(times)
        for nuclide, e_n in self.coeff.items():
            if e_n == 0.0:
                continue
            if nuclide not in series:
                raise InternalDoseError(
                    f"no activity series for contributing nuclide {nuclide!r}"
                )
            col = series[nuclide]
            for j, a in enumerate(col):
                committed[j] += e_n * float(a)

        warnings: list[dict] = []
        if self.uncovered:
            warnings.append({
                "reason": "uncovered_nuclides",
                "nuclides": list(self.uncovered),
                "message": (
                    f"{len(self.uncovered)} tracked nuclide(s) have no {self.route} coefficient "
                    f"in the curated {self.population} set ({', '.join(self.uncovered)}); their "
                    "committed dose is omitted, so this E(50) is a LOWER BOUND (§11)."
                ),
            })
        if self.noble_gas_na:
            warnings.append({
                "reason": "noble_gas_no_intake_pathway",
                "nuclides": list(self.noble_gas_na),
                "message": (
                    f"{len(self.noble_gas_na)} noble-gas nuclide(s) ({', '.join(self.noble_gas_na)}) "
                    "have no intake committed-dose coefficient (submersion is a different quantity, "
                    "ICRP-119 Annex C); excluded, and they do NOT make the result a lower bound."
                ),
            })

        return {
            "quantity": QUANTITY,
            "si_unit": SI_UNIT,
            "per": None,            # committed scalar, NOT a rate — integrate is disabled (§M13)
            "route": self.route,
            "population": self.population,
            "icrp_publication": self.icrp_publication,
            "amad_um": self.amad_um,
            "times_s": list(times),
            "committed_si": committed,
            "covered": list(self.covered),
            "noble_gas_na": list(self.noble_gas_na),
            "uncovered": list(self.uncovered),
            "types_used": dict(self.types_used),
            "f1_used": dict(self.f1_used),
            # Per-nuclide e_n (Sv/Bq) for the cursor breakdown — the client folds A_n(t) at the
            # cursor (mirrors dose_lines' coeff_si), so the table is live on scrub with no re-fetch.
            "per_nuclide_coeff": self.per_nuclide_coeff(),
            "lower_bound": bool(self.uncovered),
            "warnings": warnings,
        }
