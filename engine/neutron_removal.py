"""Loader for the bundled NCRP-20 fast-neutron removal cross-sections (M10, §6.3).

Canonical files live in ``data/neutron_removal/<material>.json`` and are produced by
``data/build/build_neutron_removal.py`` from the NCRP-20 (1957) elemental mass removal
cross-sections (see ``data/vendor/ncrp20_removal/PROVENANCE.md``). This module is the single
read path the neutron-dose engine (and tests) use to reach them.

Each record carries the fast-neutron **effective removal cross-section** Σ_R (cm⁻¹) — the
hydrogenous-shield dose-attenuation coefficient, ``T = exp(−Σ_R·x)`` — plus the bulk density,
the compound mass removal Σ_R/ρ, and the **hydrogen weight fraction** that the dose engine's
hydrogen-presence validity gate reads (the removal method is only valid with H present; §11).

No silent errors (CLAUDE.md): a missing/malformed material raises ``RemovalError``. A material
with no file is **not** loaded as "transparent" here — the *transparent-with-warning* decision
for γ-oriented materials belongs to the dose engine (engine.neutron_dose), which owns that
contract; this loader only loads materials that genuinely have removal data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "neutron_removal"
_data_root = _DEFAULT_ROOT


class RemovalError(Exception):
    """A missing or malformed removal-cross-section dataset. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different directory (e.g. the Pyodide virtual FS)."""
    global _data_root
    _data_root = Path(root)
    load_removal.cache_clear()


def data_root() -> Path:
    return _data_root


def available_materials() -> set[str]:
    """Set of material IDs that have a bundled removal-cross-section file."""
    return {p.stem for p in _data_root.glob("*.json")}


def has_material(material: str) -> bool:
    return (_data_root / f"{material}.json").is_file()


@lru_cache(maxsize=None)
def load_removal(material: str) -> dict:
    """Load and validate one material's canonical removal-cross-section record."""
    path = _data_root / f"{material}.json"
    if not path.is_file():
        raise RemovalError(f"no removal-cross-section data for {material!r} (expected {path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RemovalError(f"{material}: removal schema_version {version!r} != {SCHEMA_VERSION}")
    if data.get("material") != material:
        raise RemovalError(
            f"{path.name}: embedded material {data.get('material')!r} != {material!r}"
        )
    sigma = data.get("sigma_r_cm1")
    if not (isinstance(sigma, (int, float)) and sigma > 0):
        raise RemovalError(f"{material}: missing/invalid Σ_R {sigma!r} (must be > 0 cm⁻¹)")
    rho = data.get("rho_g_cm3")
    if not (isinstance(rho, (int, float)) and rho > 0):
        raise RemovalError(f"{material}: missing/invalid density {rho!r}")
    wh = data.get("hydrogen_weight_fraction")
    if not isinstance(wh, (int, float)) or wh < 0:
        raise RemovalError(f"{material}: missing/invalid hydrogen_weight_fraction {wh!r}")
    return data


def sigma_r_cm1(material: str) -> float:
    """Macroscopic fast-neutron removal cross-section Σ_R (cm⁻¹)."""
    return load_removal(material)["sigma_r_cm1"]


def sigma_r_mass_cm2_g(material: str) -> float:
    """Compound mass removal cross-section Σ_R/ρ (cm²/g)."""
    return load_removal(material)["sigma_r_mass_cm2_g"]


def density(material: str) -> float:
    """Bulk density ρ (g/cm³) used to form Σ_R (matches the attenuation file)."""
    return load_removal(material)["rho_g_cm3"]


def hydrogen_weight_fraction(material: str) -> float:
    """Hydrogen weight fraction — the validity discriminator for the removal method."""
    return load_removal(material)["hydrogen_weight_fraction"]
