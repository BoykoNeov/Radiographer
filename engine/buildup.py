"""Loader + G-P evaluator for the bundled gamma-ray buildup-factor data (§6.5, §7).

Canonical files live in ``data/buildup/<material>.json`` and are produced by
``data/build/build_buildup.py`` from a hand-keyed transcription of the public-domain
NUREG/CR-5740 (Trubey 1991) tables — the same data as ANSI/ANS-6.4.3-1991. See
``docs/plans/M2-buildup.md`` for the (degraded) provenance model and
``data/vendor/ans643/PROVENANCE.md``.

The buildup factor ``B(E, x)`` corrects the bare point-kernel for scattered photons:

    I = I0 · B(E, μx) · exp(−μx)          (§6.5)

``x`` is the penetration depth in **mean free paths (mfp)**. Each material stores the
five **geometric-progression (G-P, Harima)** fit coefficients ``b, c, a, Xk, d`` per
photon energy; ``B`` is reconstructed from them by :func:`gp_buildup`:

    K(x) = c·x^a + d·(tanh(x/Xk − 2) − tanh(−2)) / (1 − tanh(−2))
    B(x) = 1 + (b − 1)·(K^x − 1)/(K − 1)     for K ≠ 1
    B(x) = 1 + (b − 1)·x                       for K = 1

with the algebraic identities ``B(0)=1`` and ``B(1 mfp)=b``.

This is the **exposure (air-kerma)** buildup factor for a point isotropic source in an
infinite medium (the response consistent with the μ_en/ρ-in-air dose path, §6.1).

No silent errors (CLAUDE.md): a missing/malformed material, or an off-grid energy
request (energy interpolation is M3's job, see below), raises ``BuildupError`` rather
than guessing.

**Energy interpolation is deliberately NOT done here** (mirrors ``engine.attenuation``).
The G-P coefficients are *not* smooth in energy (Xk in particular is erratic), so a code
that needs ``B`` between tabulated energies must interpolate the *buildup factor* (ln B
vs ln E), not the coefficients — and must handle the 15 keV / 15 MeV grid bounds
explicitly and logged (``data/README.md``). That energy-axis contract belongs to the
**M3** dose engine. This module evaluates the G-P formula only **at a tabulated grid
energy**.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = 1

#: Upper bound (mean free paths) of the ANS-6.4.3 / NUREG-CR-5740 G-P fit validity. The
#: published coefficient tables are tabulated and validated to 40 mfp; beyond that the
#: geometric-progression form is both numerically unstable (``K**mfp`` overflows float64
#: around a few hundred mfp) and physically meaningless (extrapolation past the fit). The
#: buildup is **frozen** at ``B(MFP_FIT_MAX)`` for deeper penetration while the exact
#: ``exp(−mfp)`` attenuation (applied by the dose engine at the TRUE mfp) drives the
#: transmission of that already-negligible component to ~0. Callers that want to surface a
#: §11 honesty note compare their total mfp against this constant — never a hardcoded 40.
MFP_FIT_MAX = 40.0

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "buildup"
_data_root = _DEFAULT_ROOT

_GP_KEYS = ("b", "c", "a", "Xk", "d")
_TANH_M2 = math.tanh(-2.0)            # ≈ −0.96403, the Harima reference constant


class BuildupError(Exception):
    """A missing/malformed buildup dataset or an off-grid request. Never swallowed."""


def set_data_root(root: str | Path) -> None:
    """Point the loader at a different buildup directory (e.g. the Pyodide FS)."""
    global _data_root
    _data_root = Path(root)
    load_buildup.cache_clear()


def data_root() -> Path:
    return _data_root


def available_materials() -> set[str]:
    """Set of material IDs that have a bundled buildup file."""
    return {p.stem for p in _data_root.glob("*.json")}


def has_material(material: str) -> bool:
    return (_data_root / f"{material}.json").is_file()


@lru_cache(maxsize=None)
def load_buildup(material: str) -> dict:
    """Load and validate one material's canonical buildup record."""
    path = _data_root / f"{material}.json"
    if not path.is_file():
        raise BuildupError(
            f"no buildup data for {material!r} (expected {path}). "
            "Not every shield has ANS-6.4.3 buildup coefficients (e.g. PMMA, "
            "polyethylene): the dose engine must handle that absence explicitly, "
            "never with a silent surrogate."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise BuildupError(
            f"{material}: buildup schema_version {data.get('schema_version')!r} "
            f"!= {SCHEMA_VERSION}"
        )
    if data.get("material") != material:
        raise BuildupError(
            f"{path.name}: embedded material {data.get('material')!r} != {material!r}"
        )
    e = data.get("E_MeV")
    gp = data.get("gp")
    if not e or not gp or len(e) != len(gp):
        raise BuildupError(
            f"{material}: ragged/empty arrays (E={len(e or [])}, gp={len(gp or [])})"
        )
    return data


def energies(material: str) -> list[float]:
    """Photon energy grid (MeV), ascending — the ANS-6.4.3 tabulation for this material."""
    return load_buildup(material)["E_MeV"]


def gp_coefficients(material: str) -> list[dict]:
    """List of ``{b, c, a, Xk, d}`` dicts, aligned to :func:`energies`."""
    return load_buildup(material)["gp"]


def gp_buildup(b: float, c: float, a: float, Xk: float, d: float, mfp: float) -> float:
    """Geometric-progression (Harima) buildup factor B at depth ``mfp`` (mean free paths).

    Pure function of the five G-P coefficients. ``B(0)=1`` and ``B(1)=b`` hold exactly.
    Raises ``BuildupError`` if the geometric ratio K ≤ 0 (the G-P form assumes K > 0; a
    non-positive K would make ``K**mfp`` complex — surfaced, never silently returned).

    Beyond :data:`MFP_FIT_MAX` the ANS-6.4.3 fit is invalid and ``K**mfp`` overflows, so the
    evaluation depth is clamped: ``B`` is **frozen** at ``B(MFP_FIT_MAX)`` (its last valid
    value) for deeper penetration. This is a no-op for ``mfp <= MFP_FIT_MAX`` — the algebraic
    identities and every tabulated check point are untouched. The transmission of such a deep
    component is ~0 once the dose engine multiplies by the exact ``exp(−mfp)`` at the TRUE
    mfp; the cap removes the overflow artifact without fabricating buildup past the fit. The
    dose engine surfaces a §11 honesty note when this clamp engages (see ``engine.dose``).
    """
    if mfp < 0:
        raise BuildupError(f"negative penetration depth mfp={mfp}")
    if mfp == 0:
        return 1.0
    mfp = min(mfp, MFP_FIT_MAX)  # freeze buildup at the fit limit; attenuation stays exact
    k = c * (mfp ** a) + d * (math.tanh(mfp / Xk - 2.0) - _TANH_M2) / (1.0 - _TANH_M2)
    if k <= 0.0:
        raise BuildupError(
            f"non-physical G-P ratio K={k:.4g} at mfp={mfp} "
            f"(b={b}, c={c}, a={a}, Xk={Xk}, d={d})"
        )
    if abs(k - 1.0) < 1e-9:
        return 1.0 + (b - 1.0) * mfp
    return 1.0 + (b - 1.0) * (k ** mfp - 1.0) / (k - 1.0)


def _grid_index(material: str, E_MeV: float, rel_tol: float = 1e-6) -> int:
    """Index of the tabulated energy equal to ``E_MeV`` (no interpolation — that's M3)."""
    e = energies(material)
    for i, ei in enumerate(e):
        if abs(ei - E_MeV) <= rel_tol * max(ei, E_MeV):
            return i
    raise BuildupError(
        f"{material}: energy {E_MeV} MeV is not a tabulated grid point "
        f"(grid {e[0]}..{e[-1]} MeV). Energy interpolation belongs to the M3 dose "
        "engine; this loader evaluates only at tabulated energies."
    )


def buildup_factor(material: str, E_MeV: float, mfp: float) -> float:
    """Exposure buildup factor B at a **tabulated** grid energy and depth ``mfp``.

    Raises if ``E_MeV`` is not on this material's grid (interpolation is M3's job).
    """
    coeffs = gp_coefficients(material)[_grid_index(material, E_MeV)]
    return gp_buildup(*(coeffs[k] for k in _GP_KEYS), mfp)
