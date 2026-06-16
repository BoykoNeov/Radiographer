r"""Loader for the bundled fluence-to-dose conversion coefficients (§6.4, §7).

Canonical files live in ``data/conversion/`` and are produced by
``data/build/build_conversion.py`` from vendored OpenMC dose tables (see
``data/vendor/openmc_dose/PROVENANCE.md`` and ``docs/plans/M2-conversion.md``). This
module is the single read path the physics core (and tests) use to reach them.

Two **photon** quantities, each a dose per unit fluence in ``pSv·cm²``:

- ``ambient_H10`` — **ambient dose equivalent H\*(10)** (ICRP-74/ICRU-57). Operational
  quantity on the ICRU sphere; **no geometry** (``geometry=None``). Grid 0.01–10 MeV.
  The §6.4 **default/primary** dose quantity (what a survey meter reads).
- ``effective`` — **effective dose E** (ICRP-116). Tabulated **per irradiation geometry**
  ``AP/PA/LLAT/RLAT/ROT/ISO``; selecting E forces a body-orientation choice (§6.4). Grid
  0.01 MeV–10 GeV.

The two are **different quantities computed differently** — never compare directly (§6.4,
honesty register §11).

The dose chain (M3): form a per-line fluence ``Φ_i = y_i · A / (4π d²)``, then
``H*(10) = Σ_i Φ_i · h*(10)/Φ(E_i)`` or ``E = Σ_i Φ_i · e/Φ(E_i, geometry)``.

No silent errors (CLAUDE.md): a missing/malformed file, an unknown quantity, or a
geometry/quantity mismatch (a geometry for H\*(10), or none for effective) raises
``ConversionError`` rather than guessing.

**Interpolation is deliberately NOT done here** (mirrors ``engine.attenuation`` /
``engine.buildup``). These coefficients are smooth in energy (no absorption edges), so a
code that needs a value between grid energies interpolates the *coefficient* in log–log —
the M3 dose engine's job, together with the documented off-grid contract:

- a **10 keV (0.01 MeV) scoring floor** for *both* quantities (higher than the 1 keV
  attenuation floor): photon lines below it have no conversion coefficient and are skipped
  **explicitly and logged**, never silently;
- **H\*(10) above 10 MeV** (grid end) and effective above 10 GeV are off-grid — handled
  explicitly + logged, never extrapolated (mirrors the buildup 15 MeV contract).

This module only loads, validates, and exposes the raw grid + coefficients.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

#: Irradiation geometries for effective dose (ICRP-116 §3.2 idealised fields).
GEOMETRIES: tuple[str, ...] = ("AP", "PA", "LLAT", "RLAT", "ROT", "ISO")
#: Supported dose quantities.
QUANTITIES: tuple[str, ...] = ("ambient_H10", "effective")

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "conversion"
_data_root = _DEFAULT_ROOT


class ConversionError(Exception):
    """A missing/malformed conversion dataset or a bad quantity/geometry. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different conversion directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load.cache_clear()


def data_root() -> Path:
    return _data_root


def _filename(quantity: str, geometry: str | None) -> str:
    """Canonical filename for a (quantity, geometry) pair, validating the combination."""
    if quantity == "ambient_H10":
        if geometry is not None:
            raise ConversionError(
                "ambient_H10 (H*(10)) is an operational quantity with no geometry; "
                f"got geometry={geometry!r}. Geometry applies only to effective dose."
            )
        return "hstar10.json"
    if quantity == "effective":
        if geometry not in GEOMETRIES:
            raise ConversionError(
                f"effective dose requires a geometry in {GEOMETRIES}; got {geometry!r}"
            )
        return f"effective_{geometry}.json"
    raise ConversionError(f"unknown dose quantity {quantity!r} (expected one of {QUANTITIES})")


def available() -> set[str]:
    """Set of canonical file stems present (e.g. ``{'hstar10', 'effective_AP', …}``)."""
    return {p.stem for p in _data_root.glob("*.json")}


def has(quantity: str, geometry: str | None = None) -> bool:
    return (_data_root / _filename(quantity, geometry)).is_file()


@lru_cache(maxsize=None)
def load(quantity: str, geometry: str | None = None) -> dict:
    """Load and validate one canonical conversion record."""
    name = _filename(quantity, geometry)
    path = _data_root / name
    if not path.is_file():
        raise ConversionError(
            f"no conversion data for quantity={quantity!r} geometry={geometry!r} "
            f"(expected {path}); run `python data/build/build_conversion.py`"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConversionError(
            f"{name}: conversion schema_version {data.get('schema_version')!r} "
            f"!= {SCHEMA_VERSION}"
        )
    if data.get("quantity") != quantity:
        raise ConversionError(
            f"{name}: embedded quantity {data.get('quantity')!r} != {quantity!r}"
        )
    if data.get("geometry") != geometry:
        raise ConversionError(
            f"{name}: embedded geometry {data.get('geometry')!r} != {geometry!r}"
        )
    if data.get("particle") != "photon":
        raise ConversionError(f"{name}: unexpected particle {data.get('particle')!r}")
    if data.get("units") != "pSv_cm2":
        raise ConversionError(f"{name}: unexpected units {data.get('units')!r}")
    e = data.get("E_MeV")
    c = data.get("coeff_pSv_cm2")
    if not e or not c or len(e) != len(c):
        raise ConversionError(
            f"{name}: ragged/empty arrays (E={len(e or [])}, coeff={len(c or [])})"
        )
    return data


def energies(quantity: str, geometry: str | None = None) -> list[float]:
    """Photon energy grid (MeV), ascending, for this quantity/geometry."""
    return load(quantity, geometry)["E_MeV"]


def coefficients_pSv_cm2(quantity: str, geometry: str | None = None) -> list[float]:
    """Dose-per-fluence coefficients (pSv·cm²), aligned to :func:`energies`."""
    return load(quantity, geometry)["coeff_pSv_cm2"]


def ambient_h10() -> tuple[list[float], list[float]]:
    r"""``(E_MeV, h*(10)/Φ)`` for ambient dose equivalent H\*(10) (ICRP-74/ICRU-57)."""
    d = load("ambient_H10")
    return d["E_MeV"], d["coeff_pSv_cm2"]


def effective(geometry: str) -> tuple[list[float], list[float]]:
    """``(E_MeV, e/Φ)`` for effective dose E in the given geometry (ICRP-116)."""
    d = load("effective", geometry)
    return d["E_MeV"], d["coeff_pSv_cm2"]
