"""JSON bridge — the contract crossing the Pyodide boundary (HANDOFF_PLAN §3).

Pure JSON text in / JSON text out, stateful via a branded string handle. The
solve-once state lives in Python; JS keeps the handle and asks for a *whole time
grid* at once (the slider then scrubs a cursor over the returned arrays
client-side — no per-tick re-solve, no PyProxy lifetime to manage).

Errors cross as a loud structured ``{"ok": false, "error": {type, message}}`` —
never a swallowed exception, never a fabricated fallback number (CLAUDE.md
no-silent-errors). Success responses carry ``"ok": true``.
"""

from __future__ import annotations

import json
import secrets
import traceback

from engine.attenuation import AttenuationError
from engine.beta_dose import BetaDoseError, BetaSkinDoseModel
from engine.buildup import BuildupError
from engine.chain import build_dag
from engine.conversion import ConversionError
from engine.dose import DoseError, GammaDoseModel
from engine.emissions import EmissionsError
from engine.inventory import EngineError, SolvedInventory
from engine.photon_interp import OffGridError

#: Expected, structured domain errors — surfaced loudly but without a traceback (the
#: message is the contract). An *un*expected exception still carries its traceback.
_EXPECTED_ERRORS = (
    EngineError,
    DoseError,
    BetaDoseError,
    OffGridError,
    AttenuationError,
    BuildupError,
    ConversionError,
    EmissionsError,
)

_REGISTRY: dict[str, SolvedInventory] = {}


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload})


def _err(exc: Exception) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                # full traceback only for unexpected (non-domain) failures
                "traceback": None if isinstance(exc, _EXPECTED_ERRORS) else traceback.format_exc(),
            },
        }
    )


def _solve_obj(nuclides: dict, unit: str = "Bq", precision: str = "double") -> SolvedInventory:
    """Internal: build a SolvedInventory (used by ``solve`` and by tests)."""
    return SolvedInventory.from_spec(nuclides, unit, precision)


def _get(handle: str) -> SolvedInventory:
    solved = _REGISTRY.get(handle)
    if solved is None:
        raise EngineError(f"unknown or released handle {handle!r}")
    return solved


def solve(spec_json: str) -> str:
    """``{"nuclides": {name: value}, "unit": "Bq", "precision": "double"}`` ->
    ``{ok, handle, nuclides, half_lives_s, time_range_s, hp_recommended, ...}``."""
    try:
        spec = json.loads(spec_json)
        solved = _solve_obj(
            spec["nuclides"], spec.get("unit", "Bq"), spec.get("precision", "double")
        )
        handle = "inv_" + secrets.token_hex(8)
        _REGISTRY[handle] = solved
        return _ok({"handle": handle, **solved.metadata()})
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def evaluate(handle: str, request_json: str) -> str:
    """``{"times_s": [...], "axis": "activity", "unit": "Bq"}`` ->
    ``{ok, axis, unit, times_s, nuclides, series, peak_atoms, floor_atoms, ...}``."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        return _ok(solved.evaluate(req["times_s"], req.get("axis", "activity"), req.get("unit")))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def chain(handle: str) -> str:
    """-> ``{ok, nodes, edges}`` (the decay-chain DAG)."""
    try:
        return _ok(build_dag(_get(handle)))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def dose(handle: str, request_json: str) -> str:
    """``{"times_s":[...], "quantity":"ambient_H10", "distance_m":1.0,
        "shield":["lead",2.0] | null, "medium":"air", "geometry":null}`` ->
    ``{ok, quantity, si_unit, per, times_s, distance_m, rate_si, scoring_floor_MeV,
       warnings}``.

    The §6 gamma dose-rate over a whole time grid, the §3 "solve once, evaluate many" way:
    one Bateman solve (the handle), one ``GammaDoseModel`` (the per-nuclide dose coefficients
    ``C_n``), one matvec against the activity series. The slider scrubs the returned array
    client-side — no per-tick re-solve, no per-tick line summation."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        activities = solved.evaluate(req["times_s"], axis="activity", unit="Bq")
        shield = req.get("shield")
        model = GammaDoseModel(
            solved.names,
            req.get("quantity", "ambient_H10"),
            medium=req.get("medium", "air"),
            shield=tuple(shield) if shield else None,
            geometry=req.get("geometry"),
        )
        return _ok(model.dose_rate_series(activities, float(req["distance_m"])))
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def beta_dose(handle: str, request_json: str) -> str:
    """``{"times_s":[...], "distance_m":0.0, "shield":["pmma",1.0] | null,
        "medium":"tissue_soft", "avg_area_cm2":1.0, "include_bremsstrahlung":true,
        "brems_quantity":"ambient_H10", "geometry":null}`` ->
    ``{ok, quantity:"beta_skin", si_unit:"Gy", per, times_s, distance_m,
       scoring_depth_mg_cm2, rate_si, warnings, bremsstrahlung: {γ-dose series} | null}``.

    The §6.2 external **beta skin dose** (Hp(0.07), 7 mg/cm²) over a time grid, the §3
    "solve once, evaluate many" way: one solve, fixed per-nuclide C_n^β(d), one matvec. When
    a shield is present, the secondary **bremsstrahlung** photon dose is scored through the
    γ engine (a *different* quantity — penetrating photons, not skin dose) and returned
    alongside, so the UI can show "more lead can increase dose". Brems needs a finite
    distance (point-source γ is singular at 0)."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        activities = solved.evaluate(req["times_s"], axis="activity", unit="Bq")
        shield = req.get("shield")
        model = BetaSkinDoseModel(
            solved.names,
            medium=req.get("medium", "tissue_soft"),
            shield=tuple(shield) if shield else None,
            avg_area_cm2=float(req.get("avg_area_cm2", 1.0)),
        )
        distance_m = float(req.get("distance_m", 0.0))
        out = model.dose_rate_series(activities, distance_m)
        out["bremsstrahlung"] = None
        if shield and req.get("include_bremsstrahlung", True):
            override = model.bremsstrahlung_override()
            if distance_m > 0.0 and any(override.values()):
                gm = GammaDoseModel(
                    solved.names,
                    req.get("brems_quantity", "ambient_H10"),
                    shield=None,  # beta-stopping shield is photon-thin (documented, §11)
                    geometry=req.get("geometry"),
                    photon_override=override,
                )
                out["bremsstrahlung"] = gm.dose_rate_series(activities, distance_m)
        return _ok(out)
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def release(handle: str) -> str:
    """Free a solved inventory. Idempotent; reports whether it existed."""
    try:
        existed = _REGISTRY.pop(handle, None) is not None
        return _ok({"handle": handle, "existed": existed})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
