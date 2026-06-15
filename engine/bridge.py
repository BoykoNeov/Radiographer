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

from engine.chain import build_dag
from engine.inventory import EngineError, SolvedInventory

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
                # full traceback only for unexpected (non-EngineError) failures
                "traceback": None if isinstance(exc, EngineError) else traceback.format_exc(),
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


def release(handle: str) -> str:
    """Free a solved inventory. Idempotent; reports whether it existed."""
    try:
        existed = _REGISTRY.pop(handle, None) is not None
        return _ok({"handle": handle, "existed": existed})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
