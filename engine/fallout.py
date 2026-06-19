"""Loader for the bundled fission-product fallout vector (HANDOFF_PLAN §8 / §13 #5; M7d).

Canonical file: ``data/fallout/u235_fission_fallout.json`` (produced by
``data/build/build_fallout.py`` from ENDF/B-VIII.0 U-235 cumulative fission yields). This
module turns it into a **catalog source** the §8 picker loads — exactly like a spent-fuel
vector: an inventory (per-fission cumulative yields × a reference fission count, loaded with
``unit="atoms"``) + a teaching blurb + the modelling caveats. The post-detonation reference
(t=0 ≈ H+1 h) is the §9 time control, so the existing slider plays the Way–Wigner 7:10 decay.

No silent errors (CLAUDE.md): a missing/malformed vector raises ``FalloutError`` rather than
yielding an empty inventory — a fallout source with no nuclides is a data hole.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

#: Fissions per kiloton TNT-equivalent (≈ 1 kt / ~180 MeV recoverable per fission). The default
#: device size that scales the per-fission yields into an absolute atom inventory; the absolute
#: scale is a teaching default (editable after load) — the SHAPE / 7:10 decay is the physics.
FISSIONS_PER_KT = 1.45e23
DEFAULT_DEVICE_KT = 1.0

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "fallout"
_data_root = _DEFAULT_ROOT


class FalloutError(Exception):
    """A missing or malformed fallout vector. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different fallout directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load_vector.cache_clear()


def available_sources() -> list[str]:
    """Sorted ids of the bundled fallout vectors."""
    return sorted(p.stem for p in _data_root.glob("*.json"))


@lru_cache(maxsize=None)
def load_vector(source_id: str) -> dict:
    """Load and validate one fallout vector record."""
    path = _data_root / f"{source_id}.json"
    if not path.is_file():
        raise FalloutError(f"no fallout vector {source_id!r} (expected {path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise FalloutError(f"{source_id}: schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}")
    if data.get("id") != source_id:
        raise FalloutError(f"{path.name}: embedded id {data.get('id')!r} != {source_id!r}")
    if not data.get("entries"):
        raise FalloutError(f"{source_id}: empty fallout vector (a data hole, not zero source)")
    return data


def _blurb(rec: dict) -> str:
    n = rec["n_nuclides"]
    return (
        f"A fresh fission-product mix ({n} radionuclides, ENDF/B-VIII.0 U-235 cumulative "
        "yields) at ≈ H+1 h. Scrub the time forward to watch the gross γ dose fall along the "
        "Way–Wigner 7:10 rule (≈ t⁻¹·²) — the classic fallout decay law."
    )


def _caveat(rec: dict) -> str:
    return (
        "Illustrative representative mix: cumulative-yield seeding (≈ H+1 h chain-fed inventory) "
        "double-counts within chains — a documented shape-preserving approximation, so the 7:10 "
        "DECAY is meaningful but the absolute level is approximate; t < H+1 h is unreliable. A "
        f"real weapon is FAST U/Pu fission, not thermal U-235. Scaled to {DEFAULT_DEVICE_KT:g} kt "
        f"(~{FISSIONS_PER_KT:.2g} fissions/kt); edit quantities to rescale. §11."
    )


def catalog() -> list[dict]:
    """The §8 picker records for every bundled fallout vector — inventory from validated
    ``data/fallout`` (not a hand-written manifest). Each entry's amount is
    ``yield_per_fission × DEFAULT_DEVICE_KT × FISSIONS_PER_KT`` atoms; the engine's decay gives
    the activity / γ-dose evolution. Loaded at t=0 ≈ H+1 h (cumulative-yield reference)."""
    scale = DEFAULT_DEVICE_KT * FISSIONS_PER_KT
    out: list[dict] = []
    for sid in available_sources():
        rec = load_vector(sid)
        out.append(
            {
                "id": sid,
                "label": rec["label"],
                "category": "Weapons material",
                "blurb": _blurb(rec),
                "caveat": _caveat(rec),
                "referenceTimeS": 0.0,
                "entries": [
                    {"name": e["name"], "quantity": e["yield_per_fission"] * scale, "unit": "atoms"}
                    for e in rec["entries"]
                ],
            }
        )
    return out
