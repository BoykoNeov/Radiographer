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
import re
import secrets
import traceback

import radioactivedecay as rd

from engine import attenuation, buildup
from engine.attenuation import AttenuationError
from engine.beta_dose import BetaDoseError, BetaSkinDoseModel
from engine.buildup import BuildupError
from engine.chain import build_dag
from engine.conversion import ConversionError
from engine.decay_heat import DecayHeatError, DecayHeatModel
from engine.dose import SCORING_FLOOR_MEV, DoseError, GammaDoseModel
from engine.emissions import EmissionsError
from engine.inventory import EngineError, SolvedInventory
from engine.neutron_dose import NeutronDoseError, NeutronDoseModel
from engine.neutron_source import NeutronSourceError
from engine.photon_interp import OffGridError

#: Expected, structured domain errors — surfaced loudly but without a traceback (the
#: message is the contract). An *un*expected exception still carries its traceback.
_EXPECTED_ERRORS = (
    EngineError,
    DoseError,
    DecayHeatError,
    BetaDoseError,
    NeutronDoseError,
    NeutronSourceError,
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


_NUCLIDE_RE = re.compile(r"^([A-Za-z]+)-(\d+)([a-z]*)$")


def _nuclide_sort_key(name: str) -> tuple:
    """Natural (element, mass, isomeric-state) order so the picker lists Co-58
    before Co-60 before Cs-137 — not naive string order (where 'Co-60' < 'Co-58').
    Names that don't parse fall back to lexical order, kept (never dropped)."""
    m = _NUCLIDE_RE.match(name)
    if not m:
        return (1, name, 0, "")
    element, mass, state = m.groups()
    return (0, element, int(mass), state)


def nuclides() -> str:
    """``-> {ok, nuclides: [...]}`` — every nuclide the engine can solve (rd's full
    dataset), the add-by-name source for the M6b inventory panel. Names only, sorted
    and de-duplicated; emission availability is a *dose*-time concern (M6f), not here,
    so an emission-less but solvable nuclide is intentionally listed."""
    try:
        names = sorted({str(n) for n in rd.DEFAULTDATA.nuclides}, key=_nuclide_sort_key)
        return _ok({"nuclides": names})
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def materials() -> str:
    """``-> {ok, materials: [{id, has_buildup, density_g_cm3}]}`` — the M6g shield-builder
    material list, the no-drift source for the §9 picker. Every material with a bundled
    attenuation file, tagged with ``has_buildup`` (an ANS-6.4.3 G-P buildup file exists).

    ``has_buildup`` is the **γ-shield gate**: ``GammaDoseModel`` *raises* for a shield
    material with no buildup (dose.py — a shield without scatter buildup is a data hole,
    not a transparent medium), so the UI filters the γ picker to ``has_buildup`` rather
    than letting a selection error out the whole γ panel (§11). Low-Z hydrogenous materials
    (PMMA, polyethylene) are listed with ``has_buildup=false`` — surfaced, not hidden — and
    become selectable for β/neutron once those consumers land (M7)."""
    try:
        out = [
            {
                "id": m,
                "has_buildup": buildup.has_material(m),
                "density_g_cm3": attenuation.density(m),
            }
            for m in sorted(attenuation.available_materials())
        ]
        return _ok({"materials": out})
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def _get(handle: str) -> SolvedInventory:
    solved = _REGISTRY.get(handle)
    if solved is None:
        raise EngineError(f"unknown or released handle {handle!r}")
    return solved


def solve(spec_json: str) -> str:
    """Two accepted forms (dispatched on the presence of ``entries``):

    * single-unit: ``{"nuclides": {name: value}, "unit": "Bq", "precision": "double"}``
    * per-entry units (the §9 inventory panel): ``{"entries": [{"name","quantity","unit"}],
      "precision": "double"}`` — each entry may use a different unit, summed in atoms.

    -> ``{ok, handle, nuclides, half_lives_s, time_range_s, hp_recommended, ...}``."""
    try:
        spec = json.loads(spec_json)
        precision = spec.get("precision", "double")
        if "entries" in spec:
            solved = SolvedInventory.from_entries(spec["entries"], precision)
        else:
            solved = _solve_obj(spec["nuclides"], spec.get("unit", "Bq"), precision)
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


def dose_lines(handle: str, request_json: str) -> str:
    """``{"quantity":"ambient_H10", "geometry":null, "shield":["lead",2.0]|null,
        "medium":"air"}`` -> ``{ok, quantity, si_unit, lines:[{nuclide, E_MeV, yield,
        origin, coeff_si}], warnings, scoring_floor_MeV}``.

    The §9 per-line γ breakdown ("the gamma slice expands to a per-line table"). DISTANCE-
    and TIME-FREE on purpose: it returns only the per-line per-decay coefficients ``coeff_si``
    (Sv·m²/decay for H*(10)/effective; J·m²/kg for air_kerma). The client applies the
    geometric factor ``1/4πd²`` and the parent's activity ``A_n(t)`` at the cursor, so the
    table is live on scrub/distance with no re-fetch — the §3 "solve once, evaluate many"
    discipline the dose series already follows. ``coeff_si`` is the same per-line quantity
    that sums to ``dose()``'s ``C_n``, so ``Σ(coeff_si·A_n)/4πd²`` reconciles EXACTLY with
    the ``dose()`` total (one coefficient-assembly path, no second code branch to drift)."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        shield = req.get("shield")
        model = GammaDoseModel(
            solved.names,
            req.get("quantity", "ambient_H10"),
            medium=req.get("medium", "air"),
            shield=tuple(shield) if shield else None,
            geometry=req.get("geometry"),
        )
        return _ok(
            {
                "quantity": model.quantity,
                "si_unit": model.si_unit,
                "lines": model.per_line_rows(),
                "warnings": list(model.warnings),
                "scoring_floor_MeV": SCORING_FLOOR_MEV,
            }
        )
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def dose_thickness(handle: str, request_json: str) -> str:
    """``{"material":"lead", "thicknesses_cm":[0,0.5,1,...], "quantity":"ambient_H10",
        "geometry":null, "medium":"air"}`` -> ``{ok, quantity, si_unit, material,
        thicknesses_cm, coeff_by_nuclide:{nuclide:[C_n(x0), C_n(x1), ...]}, warnings,
        scoring_floor_MeV}``.

    The §9 **dose-vs-thickness** sweep, Design-A (M6f-2 #10): DISTANCE- and TIME-free
    per-nuclide γ dose coefficients ``C_n(x)`` for a thickness grid through one ``material``.
    The shield transmission ``B(E,μx)·exp(−μx)`` is nonlinear and per-line, so — unlike the
    γ dose-vs-*distance* band (exact inverse-square, reconstructed client-side) — it MUST be
    evaluated by the engine. The client folds ``1/4πd²`` and the parent activity ``A_n(t)``
    at the cursor, so the curve is live on scrub/distance with no re-fetch (the §3 discipline
    the dose series already follows).

    ``x == 0`` is evaluated with ``shield=None`` so the curve's zero point is the EXACT
    unshielded baseline. Each ``C_n(x)`` is the same per-nuclide coefficient ``dose()`` folds
    for ``shield=(material, x)`` (one ``GammaDoseModel`` assembly path), so at any grid
    thickness ``Σ C_n(x)·A_n / 4πd²`` reconciles EXACTLY with the breakdown bar — no second
    code branch to drift. Below-floor lines are logged in ``warnings`` (thickness-independent,
    captured once); a material without ANS-6.4.3 buildup raises loudly (§11)."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        material = str(req["material"])
        quantity = req.get("quantity", "ambient_H10")
        geometry = req.get("geometry")
        medium = req.get("medium", "air")
        thicknesses = [float(x) for x in req["thicknesses_cm"]]

        coeff_by_nuclide: dict[str, list[float]] = {n: [] for n in solved.names}
        warnings: list[dict] = []
        si_unit = None
        for i, x in enumerate(thicknesses):
            if x < 0.0:
                raise DoseError(f"shield thickness must be >= 0 cm; got {x}")
            model = GammaDoseModel(
                solved.names,
                quantity,
                medium=medium,
                shield=(material, x) if x > 0.0 else None,
                geometry=geometry,
            )
            si_unit = model.si_unit
            for n in solved.names:
                coeff_by_nuclide[n].append(model.coeff_si[n])
            # Below-floor skips are set by the line *energies* / quantity, not the shield, so
            # they are identical at every thickness — capture them once (the x=0 model).
            if i == 0:
                warnings = list(model.warnings)
        return _ok(
            {
                "quantity": quantity,
                "si_unit": si_unit,
                "material": material,
                "thicknesses_cm": thicknesses,
                "coeff_by_nuclide": coeff_by_nuclide,
                "warnings": warnings,
                "scoring_floor_MeV": SCORING_FLOOR_MEV,
            }
        )
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


def neutron_dose(handle: str, request_json: str) -> str:
    """``{"times_s":[...], "source":"Cf-252", "quantity":"ambient_H10", "distance_m":1.0,
        "geometry":null, "include_source_gamma":true}`` ->
    ``{ok, quantity, si_unit:"Sv", per, times_s, distance_m, source, parent,
       neutrons_per_decay, spectrum_avg_coeff_pSv_cm2, rate_si, warnings,
       source_gamma:{γ-dose series}|null}``.

    The §6.3 external **neutron dose** for a **prebuilt source** over a time grid, the §3
    "solve once, evaluate many" way: one Bateman solve (the handle), one ``NeutronDoseModel``
    (the fixed per-decay coefficient ``neutrons_per_decay·h̄``), one matvec against the
    parent's activity series. The ``"source"`` key is the §6.3 **gray-out gate** — the UI
    only calls this for a prebuilt neutron source, never for a user-defined inventory; the
    source's parent nuclide must be present in the handle's inventory (a missing parent is a
    loud error, never a silent zero).

    When the source carries reaction-correlated γ (e.g. AmBe 4.438 MeV — NOT in the ICRP-107
    decay lines), it is scored through the γ engine via ``photon_override`` in the **same
    quantity/geometry** and returned alongside, so the breakdown can show the photon
    contribution. (Cf-252 prompt-fission γ is unmodeled in v1 — §11 — so this is null there.)
    """
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        activities = solved.evaluate(req["times_s"], axis="activity", unit="Bq")
        quantity = req.get("quantity", "ambient_H10")
        geometry = req.get("geometry")
        model = NeutronDoseModel(req["source"], quantity, geometry=geometry)
        distance_m = float(req["distance_m"])
        out = model.dose_rate_series(activities, distance_m)
        out["source_gamma"] = None
        if req.get("include_source_gamma", True):
            override = model.source_gamma_override()
            if any(override.values()):
                # Source-correlated γ scored in the SAME quantity/geometry as the neutron
                # dose, so the two are directly comparable in the breakdown.
                gm = GammaDoseModel(
                    [model.parent], quantity, geometry=geometry, photon_override=override
                )
                out["source_gamma"] = gm.dose_rate_series(activities, distance_m)
        return _ok(out)
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def decay_heat(handle: str, request_json: str) -> str:
    """``{"times_s": [...]}`` -> ``{ok, quantity:"decay_heat", si_unit:"W", times_s,
        total_W, by_nuclide_W, coeff_W_per_Bq, E_rec_MeV, channels_MeV, definition}``.

    The §5 **decay heat** (thermal power, W) over a time grid, the §3 "solve once,
    evaluate many" way: one Bateman solve (the handle), one ``DecayHeatModel`` (the fixed
    per-nuclide recoverable-energy coefficient W/Bq, assembled once from the same bundled
    ICRP-107 emission spectra the γ/β engines read — no new dataset), one matvec against
    the activity series. DISTANCE- and quantity-free (heat is total locally-deposited power,
    not a point-field quantity). ``total_W`` is Σ over nuclides; ``by_nuclide_W`` is the
    §5/§9 dominant-contributor breakdown. ``definition`` carries the honesty-register
    statement of exactly what is summed (bulk recoverable energy, antineutrino-excluded)."""
    try:
        req = json.loads(request_json)
        solved = _get(handle)
        activities = solved.evaluate(req["times_s"], axis="activity", unit="Bq")
        model = DecayHeatModel(solved.names)
        return _ok(model.heat_series(activities))
    except Exception as exc:  # noqa: BLE001 - surfaced loudly as structured error
        return _err(exc)


def registry_size() -> str:
    """``-> {ok, size}`` — number of live solved inventories. The handle-leak canary
    for invariant #2 (solve-once / release-old): the UI keeps at most one live handle,
    so this stays at 1 across re-solves and 0 when the inventory is cleared."""
    try:
        return _ok({"size": len(_REGISTRY)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def release(handle: str) -> str:
    """Free a solved inventory. Idempotent; reports whether it existed."""
    try:
        existed = _REGISTRY.pop(handle, None) is not None
        return _ok({"handle": handle, "existed": existed})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
