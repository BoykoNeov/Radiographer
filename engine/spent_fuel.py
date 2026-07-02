"""Loader for the bundled PWR spent-fuel discharge vectors (HANDOFF_PLAN §8; M7c).

Canonical files live in ``data/spent_fuel/<id>.json`` and are produced by
``data/build/build_spent_fuel.py`` from the CC-BY SCK-CEN Serpent2 library. This module
is the read path that turns a discharge vector into a **catalog source** the §8 prebuilt-
source picker can load: an inventory (per-tonne-HM masses, loaded with ``unit="g"``) + a
teaching blurb + the neutron caveat. The cooling time is the §9 reference-time control, so
each source loads at discharge (t=0) and the existing time slider evolves the cooling.

No silent errors (CLAUDE.md): a missing/malformed vector raises ``SpentFuelError`` rather
than yielding an empty inventory — a spent-fuel source with no nuclides is a data hole.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 3  # v3: + (α,n)-on-oxygen neutron term in the neutron block (M12)

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "spent_fuel"
_data_root = _DEFAULT_ROOT


class SpentFuelError(Exception):
    """A missing or malformed spent-fuel discharge vector. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different spent_fuel directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load_vector.cache_clear()


def available_sources() -> list[str]:
    """Sorted ids of the bundled discharge vectors."""
    return sorted(p.stem for p in _data_root.glob("*.json"))


@lru_cache(maxsize=None)
def load_vector(source_id: str) -> dict:
    """Load and validate one discharge vector record."""
    path = _data_root / f"{source_id}.json"
    if not path.is_file():
        raise SpentFuelError(f"no spent-fuel vector {source_id!r} (expected {path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise SpentFuelError(
            f"{source_id}: schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    if data.get("id") != source_id:
        raise SpentFuelError(f"{path.name}: embedded id {data.get('id')!r} != {source_id!r}")
    if not data.get("entries"):
        raise SpentFuelError(f"{source_id}: empty discharge vector (a data hole, not zero source)")
    return data


def _blurb(rec: dict) -> str:
    bu = rec["burnup_GWd_tHM"]
    ie = rec["enrichment_pct"]
    n = rec["n_nuclides"]
    return (
        f"A REAL PWR discharge inventory ({n} radionuclides), {bu:g} GWd/tHM at {ie:g}% "
        "enrichment, per tonne initial heavy metal. Scrub the cooling time to watch γ dose "
        "and decay heat fall orders of magnitude (Cs-137/Sr-90 set the decades-long plateau)."
    )


def catalog() -> list[dict]:
    """The §8 picker records for every bundled vector: a prebuilt-source manifest whose
    inventory comes from validated ``data/`` (not a hand-written manifest). Each entry's
    amount is the per-tonne-HM mass loaded with ``unit="g"`` (the engine's λN gives activity
    and decay heat). Ordered by descending burnup, then ascending enrichment (so the highest-
    burnup case leads; the 45 GWd reference sits inside its enrichment group of the cross)."""
    out: list[dict] = []
    for sid in available_sources():
        rec = load_vector(sid)
        out.append(
            {
                "id": sid,
                "label": rec["label"],
                "category": "Reactor fuel — spent",
                "blurb": _blurb(rec),
                "caveat": rec.get("neutron_caveat"),
                "referenceTimeS": rec.get("cooling_time_s", 0.0),
                "burnup_GWd_tHM": rec["burnup_GWd_tHM"],
                "enrichment_pct": rec["enrichment_pct"],
                # M9: a spontaneous-fission neutron source rides this inventory (multi-parent,
                # not a single tabulated key). The picker uses this to arm the neutron view.
                "hasNeutron": bool(rec.get("neutron", {}).get("yields_n_per_decay")),
                "entries": [
                    {"name": e["name"], "quantity": e["mass_g_per_tHM"], "unit": "g"}
                    for e in rec["entries"]
                ],
            }
        )
    out.sort(key=lambda s: -s["burnup_GWd_tHM"])
    return out
