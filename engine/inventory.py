"""Solve-once / evaluate-many decay inventory engine (HANDOFF_PLAN §3, §5).

``radioactivedecay`` solves ``N(t) = C · diag(exp(-t·λ)) · C⁻¹ · N₀`` but re-runs
the full sparse multiply on every ``.decay()``. The locked performance rule is
"solve once, evaluate many": we factorize the solve a single time, then evaluate
a whole time grid cheaply so a multi-decade log slider scrubs smoothly.

Factorization (validated to reproduce ``rd.decay()`` to machine precision on
meaningful nuclides):

* once — restrict to the **descendant-closure index set** of the loaded
  nuclides (proven closed under the operation), take dense submatrices ``C``,
  ``C⁻¹``, ``λ``, ``N₀``, and precompute ``b = C⁻¹ N₀``;
* per grid — ``N(t) = C · (exp(-t·λ) ⊙ b)``, vectorized over all times.

**No silent errors / two floors (advisor):** the closed form ``N_i = Σ_j
C[i,j]·P_j`` cancels large terms, so each nuclide has its own roundoff bound
``noise_i ≈ eps·Σ_j|C[i,j]·P_j|`` — even ``rd`` returns negatives/garbage below
it. The floor is therefore **per-nuclide, not a single global number**: a
short-lived daughter can have a minuscule atom count yet a fully meaningful
activity (Po-212: 300 ns, ~5e-7 atoms, ~1 Bq), so a global atom floor would
wrongly erase it. This *engine validity floor* is a correctness obligation,
distinct from the M6 UI display floor: we clip ``|N| < noise`` to honest zero and
surface ``clipped_count``; a value more negative than ``-noise`` is a loud
``EngineError`` (real bug, or a chain too stiff for double → use
``precision='hp'``), never a silent clip.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np
import radioactivedecay as rd

AVOGADRO = 6.02214076e23
BQ_PER_CI = 3.7e10

_EPS = float(np.finfo(float).eps)

#: Safety multiple on the per-row cancellation bound. The double-precision
#: roundoff of ``N_i = Σ_j C[i,j]·P_j`` is bounded by ``eps · Σ_j |C[i,j]·P_j|``;
#: a value below ``NOISE_SAFETY · eps · Σ|terms|`` is indistinguishable from zero.
NOISE_SAFETY = 16.0

#: The per-element relative noise floor (≈ a few ×eps). The *operational* floor
#: is per-nuclide (``NOISE_SAFETY·eps·Σ|terms|``), not a single global number —
#: a short-lived daughter with a tiny atom count but a large activity must NOT be
#: clipped just because a long-lived parent dominates the atom scale. This
#: constant is the nominal relative magnitude, surfaced in metadata.
VALIDITY_FLOOR_REL = NOISE_SAFETY * _EPS

#: ``hp_recommended`` trips when the finite half-life span over the closure
#: exceeds this — the regime where double precision suffers catastrophic
#: cancellation and ``InventoryHP`` (arbitrary precision) is warranted (§5).
HP_HALFLIFE_SPAN = 1e12

AXES = ("atoms", "activity", "mass")

_ATOM_UNITS = {"atoms": 1.0, "atom": 1.0, "num": 1.0, "number": 1.0}
_ACTIVITY_UNITS = {"Bq": 1.0, "Ci": 1.0 / BQ_PER_CI}
_MASS_UNITS = {"g": 1.0, "kg": 1e-3, "mg": 1e3}


class EngineError(Exception):
    """Loud failure in the physics path — never swallowed, never a fallback number."""


def _rd_input_unit(unit: str) -> str:
    if unit.lower() in ("atom", "atoms", "num", "number", "n"):
        return "num"
    return unit


def _apply_validity_floor(
    N: np.ndarray,
    noise: np.ndarray,
    names: Optional[Sequence[str]] = None,
    times_s: Optional[Sequence[float]] = None,
) -> tuple[np.ndarray, dict]:
    """Clip per-nuclide noise to zero; raise loudly on a negative beyond it.

    ``noise`` is the per-element double-precision cancellation bound
    (``NOISE_SAFETY·eps·Σ|terms|``, same shape as ``N``). A value with
    ``|N| < noise`` is indistinguishable from zero → honest zero. A value more
    negative than ``-noise`` is *not* noise (true atom counts are ≥ 0): it
    signals a real bug or a chain too stiff for double precision, so we raise.

    Per-nuclide (not a single global floor) on purpose: a short-lived daughter
    can have a tiny atom count yet a large, fully-meaningful activity — a global
    atom floor set by a long-lived parent would wrongly erase it.
    """
    if N.size == 0:
        return N, {"clipped_count": 0, "peak_atoms": 0.0, "floor_atoms": 0.0}

    below_neg = N < -noise
    if np.any(below_neg):
        j, k = (int(v) for v in np.argwhere(below_neg)[0])
        who = names[k] if names is not None else f"index {k}"
        when = times_s[j] if times_s is not None else f"row {j}"
        raise EngineError(
            f"negative atom count {float(N[j, k]):.3e} for {who} at t={when} "
            f"exceeds the cancellation noise bound {float(noise[j, k]):.3e}: chain "
            f"too stiff for double precision — re-solve with precision='hp'."
        )

    sub_floor = np.abs(N) < noise
    out = np.where(sub_floor, 0.0, N)
    return out, {
        "clipped_count": int(np.count_nonzero(sub_floor)),
        "peak_atoms": float(np.max(np.abs(N))),
        "floor_atoms": float(np.max(noise)),
    }


class SolvedInventory:
    """A single Bateman solve, evaluable cheaply at many times."""

    def __init__(self, contents_atoms: dict, decay_data=None, precision: str = "double"):
        if precision not in ("double", "hp"):
            raise EngineError(f"precision must be 'double' or 'hp', got {precision!r}")
        self.precision = precision
        dd = decay_data if decay_data is not None else rd.DEFAULTDATA
        self.decay_data = dd
        self.contents_atoms = dict(contents_atoms)

        sd = dd.scipy_data
        nuclide_dict = dd.nuclide_dict
        matrix_c = sd.matrix_c

        # Descendant-closure index set — the nuclides the loaded inventory can
        # ever populate. Reused verbatim by the DAG so the two can't drift.
        n0_full = sd.vector_n0.copy()
        idxset: set[int] = set()
        for nuc, val in contents_atoms.items():
            if nuc not in nuclide_dict:
                raise EngineError(f"unknown nuclide {nuc!r}")
            idx = nuclide_dict[nuc]
            n0_full[idx] = val
            idxset.update(matrix_c[:, idx].nonzero()[0])
        idxs = sorted(idxset)
        if not idxs:
            raise EngineError("empty inventory — nothing to solve")
        self.idxs = idxs
        self.names = [str(n) for n in dd.nuclides[idxs]]
        self.lam = np.asarray(sd.decay_consts)[idxs].astype(float)  # s^-1
        self.atomic_masses = np.asarray(sd.atomic_masses)[idxs].astype(float)  # g/mol
        self.half_lives_s = np.array([float(dd.half_life(n, "s")) for n in self.names])

        # Solve-once factorization (double path only).
        self.C = np.asarray(matrix_c[idxs][:, idxs].todense(), dtype=float)
        c_inv = np.asarray(sd.matrix_c_inv[idxs][:, idxs].todense(), dtype=float)
        self.b = c_inv @ np.asarray(n0_full[idxs], dtype=float).ravel()

        # On-demand arbitrary-precision path (slow, exact) — built only if asked.
        self._hp_inv = rd.InventoryHP(self.contents_atoms, "num") if precision == "hp" else None

    # -- construction -----------------------------------------------------

    @classmethod
    def from_spec(
        cls, nuclides: dict, unit: str = "Bq", precision: str = "double"
    ) -> "SolvedInventory":
        """Build from ``{nuclide: value}`` in a given input unit (reuses rd's
        validated unit conversions to atoms; stores internally in atoms)."""
        if not nuclides:
            raise EngineError("no nuclides supplied")
        for name in nuclides:
            try:
                rd.Nuclide(name)
            except Exception as exc:  # noqa: BLE001 - re-raise loudly, don't swallow
                raise EngineError(f"unknown nuclide {name!r}: {exc}") from exc
        inv = rd.Inventory(nuclides, _rd_input_unit(unit))
        contents_atoms = {str(k): float(v) for k, v in inv.contents.items()}
        return cls(contents_atoms, inv.decay_data, precision)

    @classmethod
    def from_entries(cls, entries: Sequence[dict], precision: str = "double") -> "SolvedInventory":
        """Build from per-entry units (the §9 inventory panel form): a list of
        ``{name, quantity, unit}`` where each entry may use a *different* unit.

        Each entry is converted to atoms by ``rd`` (reusing its validated unit
        conversions) and **summed** into the contents — so the same nuclide loaded
        in two units (e.g. Co-60 in Bq and Ci) is the physically-correct sum of
        atoms. One Bateman solve then runs over the union. Loud on an unknown
        nuclide or an empty list, exactly like :meth:`from_spec`."""
        if not entries:
            raise EngineError("no nuclides supplied")
        contents_atoms: dict[str, float] = {}
        for e in entries:
            name = e["name"]
            try:
                rd.Nuclide(name)
            except Exception as exc:  # noqa: BLE001 - re-raise loudly, don't swallow
                raise EngineError(f"unknown nuclide {name!r}: {exc}") from exc
            inv = rd.Inventory({name: float(e["quantity"])}, _rd_input_unit(e["unit"]))
            for k, v in inv.contents.items():
                contents_atoms[str(k)] = contents_atoms.get(str(k), 0.0) + float(v)
        # decay_data defaults to rd.DEFAULTDATA in __init__ — all entries share it.
        return cls(contents_atoms, None, precision)

    # -- evaluation -------------------------------------------------------

    def _evaluate_double_atoms(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # N(t) = C @ (exp(-t·λ) ⊙ b); vectorized over the grid as (E * b) @ Cᵀ.
        # Also return the per-row cancellation bound noise = K·eps·Σ_j|C[i,j]·P_j|
        # (P = exp(-t·λ)⊙b) so the validity floor is calibrated per nuclide.
        P = np.exp(-np.outer(t, self.lam)) * self.b  # (T, k)
        N = P @ self.C.T  # (T, k) atoms
        noise = NOISE_SAFETY * _EPS * (np.abs(P) @ np.abs(self.C).T)  # (T, k)
        return N, noise

    def _evaluate_hp_atoms(self, t: np.ndarray) -> np.ndarray:
        out = np.zeros((len(t), len(self.names)))
        col = {n: i for i, n in enumerate(self.names)}
        for j, tj in enumerate(t):
            decayed = self._hp_inv.decay(float(tj), "s")
            for nuc, val in decayed.contents.items():
                if nuc in col:
                    out[j, col[nuc]] = float(val)
        return out

    def _to_axis(self, N: np.ndarray, axis: str, unit: Optional[str]) -> tuple[np.ndarray, str]:
        if axis == "atoms":
            unit = unit or "atoms"
            factor = _ATOM_UNITS.get(unit)
            if factor is None:
                raise EngineError(f"unknown atoms unit {unit!r}")
            return N * factor, unit
        if axis == "activity":
            unit = unit or "Bq"
            factor = _ACTIVITY_UNITS.get(unit)
            if factor is None:
                raise EngineError(f"unknown activity unit {unit!r}")
            return (N * self.lam) * factor, unit  # A = λ·N (Bq)
        if axis == "mass":
            unit = unit or "g"
            factor = _MASS_UNITS.get(unit)
            if factor is None:
                raise EngineError(f"unknown mass unit {unit!r}")
            return (N * self.atomic_masses / AVOGADRO) * factor, unit  # grams
        raise EngineError(f"unknown axis {axis!r}; expected one of {AXES}")

    def evaluate(
        self, times_s: Sequence[float], axis: str = "activity", unit: Optional[str] = None
    ) -> dict:
        if axis not in AXES:
            raise EngineError(f"unknown axis {axis!r}; expected one of {AXES}")
        t = np.asarray(times_s, dtype=float)
        if t.ndim != 1:
            raise EngineError("times_s must be 1-D")
        if t.size and np.any(t < 0):
            raise EngineError("times_s must be >= 0 (decay time, seconds)")

        if self.precision == "hp":
            N = self._evaluate_hp_atoms(t)
            peak = float(np.max(np.abs(N))) if N.size else 0.0
            if peak > 0.0 and np.any(N < -peak * 1e-25):  # HP is exact; any real negative is a bug
                j, k = (int(v) for v in np.argwhere(N < -peak * 1e-25)[0])
                raise EngineError(f"HP produced negative atoms for {self.names[k]} at row {j}")
            info = {"clipped_count": 0, "peak_atoms": peak, "floor_atoms": 0.0}
        else:
            N, noise = self._evaluate_double_atoms(t)
            N, info = _apply_validity_floor(N, noise, names=self.names, times_s=t.tolist())

        values, resolved_unit = self._to_axis(N, axis, unit)
        series = {self.names[k]: values[:, k].tolist() for k in range(len(self.names))}
        return {
            "axis": axis,
            "unit": resolved_unit,
            "times_s": t.tolist(),
            "nuclides": list(self.names),
            "series": series,
            "precision": self.precision,
            "peak_atoms": info["peak_atoms"],
            "floor_atoms": info["floor_atoms"],
            "clipped_count": info["clipped_count"],
            "validity_floor_rel": VALIDITY_FLOOR_REL,
        }

    # -- metadata (§9) ----------------------------------------------------

    def _finite_halflives(self) -> np.ndarray:
        h = self.half_lives_s[np.isfinite(self.half_lives_s)]
        return h[h > 0.0]

    def auto_time_range_s(self) -> Optional[tuple[float, float]]:
        """``[0.01·min_finite_t½, 10·max_finite_t½]`` — the per-inventory slider
        envelope (§9). ``None`` if every nuclide is stable (degenerate)."""
        finite = self._finite_halflives()
        if finite.size == 0:
            return None
        return (0.01 * float(finite.min()), 10.0 * float(finite.max()))

    def hp_recommended(self) -> bool:
        finite = self._finite_halflives()
        if finite.size < 2:
            return False
        return bool(float(finite.max() / finite.min()) > HP_HALFLIFE_SPAN)

    def metadata(self) -> dict:
        rng = self.auto_time_range_s()
        return {
            "nuclides": list(self.names),
            "n_nuclides": len(self.names),
            "half_lives_s": {
                n: (None if not math.isfinite(h) else float(h))
                for n, h in zip(self.names, self.half_lives_s)
            },
            "time_range_s": list(rng) if rng else None,
            "hp_recommended": self.hp_recommended(),
            "precision": self.precision,
            "validity_floor_rel": VALIDITY_FLOOR_REL,
        }
