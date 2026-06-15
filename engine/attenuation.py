"""Loader for the bundled NIST mass attenuation / energy-absorption data (§7).

Canonical files live in ``data/attenuation/<material>.json`` and are produced by
``data/build/build_attenuation.py`` from the vendored NIST Hubbell & Seltzer tables
(see ``data/vendor/nist_xraymac/PROVENANCE.md``). This module is the single read path
the physics core (and tests) use to reach them.

Each record carries, per material, the photon energy grid and the two mass
coefficients the M3 gamma-dose engine needs:

- ``mu_rho_cm2_g``    — mass **attenuation** coefficient μ/ρ (shielding: I = I₀·e^(−μx)).
- ``muen_rho_cm2_g``  — mass **energy-absorption** coefficient μ_en/ρ (the dose
  line-sum ``E·y·(μ_en/ρ)``, §6).

No silent errors (CLAUDE.md): a missing or malformed material raises
``AttenuationError`` rather than returning empty/zero coefficients — a data hole is
not "transparent material".

**Interpolation is deliberately NOT done here.** The grid contains *duplicate energies*
at absorption edges (e.g. Pb K-edge at 0.088 MeV: μ/ρ steps up across one energy), so
``np.interp`` is ill-defined *at* an edge. Edge-aware log–log interpolation — and the
documented "skip photon lines below the 1 keV table floor, explicitly and logged" rule
(see ``data/README.md``) — belong to the M3 dose engine, which owns that contract.
This loader only loads, validates, and exposes the raw grid + the edge markers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

# Default location: repo ``data/attenuation``. The browser/Pyodide host mounts the
# same files into its virtual FS; M6 can repoint this via :func:`set_data_root`.
_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "attenuation"
_data_root = _DEFAULT_ROOT


class AttenuationError(Exception):
    """A missing or malformed attenuation dataset. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different attenuation directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load_attenuation.cache_clear()


def data_root() -> Path:
    return _data_root


def available_materials() -> set[str]:
    """Set of material IDs that have a bundled attenuation file."""
    return {p.stem for p in _data_root.glob("*.json")}


def has_material(material: str) -> bool:
    return (_data_root / f"{material}.json").is_file()


@lru_cache(maxsize=None)
def load_attenuation(material: str) -> dict:
    """Load and validate one material's canonical attenuation record."""
    path = _data_root / f"{material}.json"
    if not path.is_file():
        raise AttenuationError(
            f"no attenuation data for {material!r} (expected {path}); "
            "a material without coefficients is a data hole, not a transparent medium"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise AttenuationError(
            f"{material}: attenuation schema_version {version!r} != {SCHEMA_VERSION}"
        )
    if data.get("material") != material:
        raise AttenuationError(
            f"{path.name}: embedded material {data.get('material')!r} != {material!r}"
        )
    e = data["E_MeV"]
    mu = data["mu_rho_cm2_g"]
    muen = data["muen_rho_cm2_g"]
    if not (len(e) == len(mu) == len(muen)) or not e:
        raise AttenuationError(
            f"{material}: ragged/empty coefficient arrays "
            f"(E={len(e)}, mu={len(mu)}, muen={len(muen)})"
        )
    rho = data.get("rho_g_cm3")
    if not (isinstance(rho, (int, float)) and rho > 0):
        raise AttenuationError(f"{material}: missing/invalid density {rho!r}")
    return data


def energies(material: str) -> list[float]:
    """Photon energy grid (MeV), ascending; duplicated at absorption edges."""
    return load_attenuation(material)["E_MeV"]


def mu_rho(material: str) -> list[float]:
    """Mass attenuation coefficient μ/ρ (cm²/g), aligned to :func:`energies`."""
    return load_attenuation(material)["mu_rho_cm2_g"]


def muen_rho(material: str) -> list[float]:
    """Mass energy-absorption coefficient μ_en/ρ (cm²/g), aligned to :func:`energies`."""
    return load_attenuation(material)["muen_rho_cm2_g"]


def density(material: str) -> float:
    """Material density ρ (g/cm³) — to convert μ/ρ → linear μ (cm⁻¹)."""
    return load_attenuation(material)["rho_g_cm3"]


def edges(material: str) -> list[dict]:
    """Absorption edges as ``{"label", "E_MeV"}`` (empty for low-Z compounds)."""
    return load_attenuation(material).get("edges", [])
