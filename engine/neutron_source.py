"""Loader for the bundled neutron source terms (HANDOFF_PLAN §6.3, §7, §8).

Canonical files live in ``data/neutron_sources/`` and are produced by
``data/build/build_neutron_sources.py``. This module is the single read path the physics
core (and tests) use to reach them.

A neutron source is **tabulated, not derived** (§6.3): v1 does not compute neutron output
from a loaded inventory (SF + (α,n) is ORIGEN/SOURCES territory). Each record carries

- ``neutrons_per_decay`` — neutrons per decay of ``parent_nuclide`` (time-invariant). The
  neutron strength is ``S(t) = neutrons_per_decay · A_parent(t)``, so the neutron view rides
  the *same* solved inventory as the gamma view (§3 solve-once / evaluate-many).
- ``spectrum`` — normalized **per-bin fluence fractions** that sum to 1 (NOT per-lethargy —
  the ambiguity is resolved in the build; §12). The dose engine folds these against the
  neutron fluence-to-dose coefficients.
- ``source_gammas`` — source-CORRELATED photon lines (reaction γ, not the ICRP-107 decay
  lines), scored through the M3 gamma engine via ``photon_override``.

No silent errors (CLAUDE.md): a missing/malformed file, an unknown source key, a spectrum
that does not sum to 1, or a non-positive yield raises :class:`NeutronSourceError` rather
than guessing. Interpolation/folding is the dose engine's job (mirrors the conversion
loader); this module only loads, validates, and exposes the raw record.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "neutron_sources"
_data_root = _DEFAULT_ROOT


class NeutronSourceError(Exception):
    """A missing/malformed neutron source term or an unknown source key. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load.cache_clear()


def data_root() -> Path:
    return _data_root


def available() -> set[str]:
    """Set of source keys present (file stems, e.g. ``{'Cf-252'}``)."""
    return {p.stem for p in _data_root.glob("*.json")}


def has(source_key: str) -> bool:
    return (_data_root / f"{source_key}.json").is_file()


@lru_cache(maxsize=None)
def load(source_key: str) -> dict:
    """Load and validate one canonical neutron-source record."""
    path = _data_root / f"{source_key}.json"
    if not path.is_file():
        raise NeutronSourceError(
            f"no neutron source {source_key!r} (expected {path}); "
            f"available: {sorted(available())}; run `python data/build/build_neutron_sources.py`"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise NeutronSourceError(
            f"{source_key}: schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    if data.get("source") != source_key:
        raise NeutronSourceError(
            f"{source_key}: embedded source {data.get('source')!r} != filename"
        )
    parent = data.get("parent_nuclide")
    if not isinstance(parent, str) or not parent:
        raise NeutronSourceError(f"{source_key}: missing/empty parent_nuclide")
    npd = data.get("neutrons_per_decay")
    if not isinstance(npd, (int, float)) or not (math.isfinite(npd) and npd > 0):
        raise NeutronSourceError(f"{source_key}: neutrons_per_decay must be a positive number, got {npd!r}")

    spec = data.get("spectrum") or {}
    lo, hi, frac = spec.get("E_lo_MeV"), spec.get("E_hi_MeV"), spec.get("fluence_frac")
    if not lo or not hi or not frac or not (len(lo) == len(hi) == len(frac)):
        raise NeutronSourceError(f"{source_key}: ragged/empty spectrum arrays")
    for a, b, f in zip(lo, hi, frac):
        if not (math.isfinite(a) and math.isfinite(b) and a > 0 and b > a):
            raise NeutronSourceError(f"{source_key}: bad spectrum bin edges ({a}, {b})")
        if not (math.isfinite(f) and f >= 0):
            raise NeutronSourceError(f"{source_key}: negative/non-finite fluence fraction {f}")
    s = math.fsum(frac)
    if not math.isclose(s, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise NeutronSourceError(
            f"{source_key}: fluence fractions sum to {s!r}, not 1 (normalization invariant)"
        )

    for g in data.get("source_gammas", []):
        e, y = g.get("E_MeV"), g.get("yield_per_decay")
        if not (isinstance(e, (int, float)) and math.isfinite(e) and e > 0):
            raise NeutronSourceError(f"{source_key}: bad source γ energy {e!r}")
        if not (isinstance(y, (int, float)) and math.isfinite(y) and y >= 0):
            raise NeutronSourceError(f"{source_key}: bad source γ yield {y!r}")
    return data


def parent_nuclide(source_key: str) -> str:
    """The inventory nuclide whose decay drives this source's emission."""
    return load(source_key)["parent_nuclide"]


def neutrons_per_decay(source_key: str) -> float:
    """Neutrons emitted per decay of :func:`parent_nuclide` (time-invariant)."""
    return float(load(source_key)["neutrons_per_decay"])


def spectrum(source_key: str) -> tuple[list[float], list[float], list[float]]:
    """``(E_lo_MeV, E_hi_MeV, fluence_frac)`` — normalized per-bin spectrum (Σ frac = 1)."""
    s = load(source_key)["spectrum"]
    return s["E_lo_MeV"], s["E_hi_MeV"], s["fluence_frac"]


def representative_energies(source_key: str) -> list[float]:
    """Per-bin geometric-mean energy (MeV) — the fold point for log-interpolated coefficients."""
    lo, hi, _ = spectrum(source_key)
    return [math.sqrt(a * b) for a, b in zip(lo, hi)]


def source_gammas(source_key: str) -> list[dict]:
    """Source-correlated γ lines as ``[{E_MeV, yield_per_decay, ...}]`` (reaction γ, not decay)."""
    return list(load(source_key).get("source_gammas", []))
