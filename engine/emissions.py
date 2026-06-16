"""Loader for the bundled ICRP-107 emission spectra (HANDOFF_PLAN.md §7).

Canonical files live in ``data/emissions/<Nuclide>.json`` and are produced by
``data/build/build_emissions.py`` from the vendored upstream. This module is the
single read path the physics core (and tests) use to reach them; the M3 gamma dose
engine sums ``photons(nuclide)`` for its line source term.

No silent errors (CLAUDE.md): asking for a nuclide with no emission file raises
``EmissionsError`` rather than returning an empty spectrum — a missing radioactive
nuclide is a data hole, not "no radiation". Callers that legitimately expect nothing
(stable nuclides) should check :func:`has_emissions` first.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

# Default location: repo ``data/emissions``. The browser/Pyodide host will mount the
# same files into its virtual FS; M6 can repoint this via :func:`set_data_root`.
_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "emissions"
_data_root = _DEFAULT_ROOT


class EmissionsError(Exception):
    """A missing or malformed emission dataset. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different emissions directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load_emissions.cache_clear()


def data_root() -> Path:
    return _data_root


def available_nuclides() -> set[str]:
    """Set of nuclide IDs that have a bundled emission file."""
    return {p.stem for p in _data_root.glob("*.json")}


def has_emissions(nuclide: str) -> bool:
    return (_data_root / f"{nuclide}.json").is_file()


@lru_cache(maxsize=None)
def load_emissions(nuclide: str) -> dict:
    """Load and validate one nuclide's canonical emission record."""
    path = _data_root / f"{nuclide}.json"
    if not path.is_file():
        raise EmissionsError(
            f"no emission data for {nuclide!r} (expected {path}); "
            "a radioactive nuclide without emissions is a data hole, not zero dose"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise EmissionsError(f"{nuclide}: emission schema_version {version!r} != {SCHEMA_VERSION}")
    if data.get("nuclide") != nuclide:
        raise EmissionsError(
            f"{path.name}: embedded nuclide {data.get('nuclide')!r} != {nuclide!r}"
        )
    return data


def photons(nuclide: str) -> list[dict]:
    """Photon lines (gamma ∪ X-ray ∪ annihilation), ascending in energy.

    Each entry is ``{"E_MeV", "yield", "origin"}`` where origin ∈
    {gamma, X, annihilation}. This is the gamma-dose line source term.
    """
    return load_emissions(nuclide)["photons"]


def betas(nuclide: str) -> list[dict]:
    """Discrete beta lines; ``E_mean_MeV`` is the ICRP-107 *mean* energy.

    ICRP-107 gives a per-branch **mean** energy (not an endpoint) and a single
    continuous :func:`beta_spectra` summed over all branches — see
    ``docs/plans/M2-emissions.md``. The M4 beta-dose engine recovers the endpoint
    from :func:`beta_endpoint_MeV` and assigns it to the dominant branch.
    """
    return load_emissions(nuclide)["betas"]


def beta_spectra(nuclide: str) -> list[dict]:
    """Continuous β⁻ spectrum ``{"E_MeV", "intensity"}`` (dN/dE), **summed over
    branches**, normalized to ≈ 1 β per decay (∫ I dE) with ∫ E·I dE = MeV/decay.
    Empty when the nuclide emits no betas."""
    return load_emissions(nuclide)["beta_spectra"]


def beta_endpoint_MeV(nuclide: str) -> float:
    """Highest β endpoint (MeV) — the maximum energy in the summed :func:`beta_spectra`.

    0.0 when the nuclide has no beta spectrum. This is the only clean endpoint
    ICRP-107 exposes (per-branch endpoints do not exist); it belongs to the
    highest-energy branch.
    """
    spec = load_emissions(nuclide)["beta_spectra"]
    return max((float(p["E_MeV"]) for p in spec), default=0.0)


def alphas(nuclide: str) -> list[dict]:
    return load_emissions(nuclide)["alphas"]
