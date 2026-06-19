"""Build the fresh fission-product fallout vector (HANDOFF_PLAN §8 / §13 #5; M7d).

Output: ``data/fallout/u235_fission_fallout.json`` — a named inventory of fission
products with per-fission **cumulative** yields, which the §8 picker loads (like a
spent-fuel vector) so the existing Bateman solve + γ-dose light up and the time
control becomes the post-detonation clock.

Provenance / honesty (§11 — cite, never reconstruct from memory):
- Yields are ENDF/B-VIII.0 neutron fission yields for ²³⁵U, **MF=8 MT=459**
  (cumulative), **thermal** incident energy (0.0253 eV). Source file vendored at
  ``data/vendor/endf_nfy/nfy-092_U_235.endf`` (SHA + citation in its PROVENANCE.md).
- **Cumulative, not independent**, on purpose: independent yields are born on
  very neutron-rich, sub-second precursors mostly ABSENT from the ICRP-107 emission
  set, so seeding them drops ~69 % of the fragments and underfeeds the longer-lived
  γ emitters. Cumulative yield = the chain-fed population once those fast precursors
  have decayed in — i.e. the inventory at ≈ H+1 h, the standard fallout reference.
  This double-counts within a chain (a daughter's cumulative yield includes its
  parent's), a documented APPROXIMATION; it inflates the absolute scale roughly
  uniformly in time, so the *shape* — the Way–Wigner t⁻¹·² (7:10) decay law — is
  preserved (validated in tests/test_fallout_data.py).
- A real weapon is FAST fission of ²³⁵U/²³⁹Pu, not thermal ²³⁵U; the dominant γ
  emitters and the t⁻¹·² law are broadly common across fission systems, so this is
  an illustrative representative mix (labelled as such), not a weapon-specific vector.

Only nuclides present in the bundled decay data (radioactivedecay / ICRP-107) and
with cumulative yield ≥ ``YIELD_CUTOFF`` are kept — the slope is insensitive to the
cutoff (tested), and it keeps the closure browser-tractable (≈ spent-fuel size).

Dev-time step only; the browser/Pyodide runtime reads the generated canonical file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import radioactivedecay as rd

SCHEMA_VERSION = 1
DATA_DIR = Path(__file__).resolve().parents[1]                       # .../data
ENDF_FILE = DATA_DIR / "vendor" / "endf_nfy" / "nfy-092_U_235.endf"
OUT_DIR = DATA_DIR / "fallout"
OUT_ID = "u235_fission_fallout"

#: Drop fission products below this per-fission cumulative yield. The t⁻¹·² slope is
#: insensitive to this (tested: 0 → 5e-3 all give −1.22); it bounds the closure size.
YIELD_CUTOFF = 1.0e-3

#: Z → element symbol over the fission-product range (light + heavy peaks).
_Z_SYMBOL = {
    27: "Co", 28: "Ni", 29: "Cu", 30: "Zn", 31: "Ga", 32: "Ge", 33: "As", 34: "Se",
    35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr", 41: "Nb", 42: "Mo",
    43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce",
    59: "Pr", 60: "Nd", 61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy",
    67: "Ho",
}


class BuildError(Exception):
    """A structural / integrity failure in the fallout build. Never swallowed."""


def _endf_float(s: str) -> float:
    """Parse an ENDF-format real (e.g. ``9.223500+4`` → 92235.0, `` 1.000-3`` → 1e-3)."""
    s = s.strip()
    if not s:
        return 0.0
    m = re.match(r"^([+-]?\d*\.?\d+)([+-]\d+)$", s)
    return float(f"{m.group(1)}e{m.group(2)}") if m else float(s)


def parse_cumulative_thermal(path: Path) -> dict[tuple[int, int], float]:
    """``{(ZA, state): cumulative_yield}`` from MF=8 MT=459, the thermal (first) energy block."""
    lines = path.read_text(encoding="latin-1").splitlines()
    recs = [ln for ln in lines if len(ln) >= 75 and ln[70:72].strip() == "8" and ln[72:75].strip() == "459"]
    if not recs:
        raise BuildError(f"{path.name}: no MF=8/MT=459 (cumulative fission yields) section")

    def fields(ln: str) -> list[str]:
        return [ln[i : i + 11] for i in range(0, 66, 11)]

    hdr = recs[1]                                      # first LIST = lowest (thermal) energy
    energy_eV = _endf_float(hdr[:11])
    nn, nfp = int(hdr[44:55]), int(hdr[55:66])
    if abs(energy_eV - 0.0253) > 1e-3:
        raise BuildError(f"{path.name}: first NFY energy {energy_eV} eV is not thermal (0.0253)")

    vals: list[float] = []
    i = 2
    while len(vals) < nn:
        vals.extend(_endf_float(c) for c in fields(recs[i]) if c.strip())
        i += 1
    vals = vals[:nn]

    out: dict[tuple[int, int], float] = {}
    for k in range(nfp):
        zafp, state, y, _dy = vals[4 * k : 4 * k + 4]
        out[(int(zafp), int(state))] = y
    # Independent yields sum to 2 (two fragments/fission); cumulative sum to more — a
    # sanity floor that catches a truncated/misaligned parse.
    if not (2.0 < sum(out.values()) < 12.0):
        raise BuildError(f"{path.name}: cumulative-yield sum {sum(out.values()):.3f} out of [2,12]")
    return out


def _name(za: int, state: int) -> str | None:
    z, a = divmod(za, 1000)
    sym = _Z_SYMBOL.get(z)
    if not sym:
        return None
    suffix = {0: "", 1: "m", 2: "n"}.get(state, "")
    return f"{sym}-{a}{suffix}"


def build_fallout() -> dict:
    raw = parse_cumulative_thermal(ENDF_FILE)
    entries: list[dict] = []
    for (za, state), y in raw.items():
        if y < YIELD_CUTOFF:
            continue
        name = _name(za, state)
        if not name:
            continue
        try:
            rd.Nuclide(name)                           # keep only nuclides the engine can solve
        except Exception:                              # noqa: BLE001 - unknown to the decay data
            continue
        entries.append({"name": name, "yield_per_fission": y})

    if not entries:
        raise BuildError("fallout vector is empty — parse/mapping failure (a data hole)")
    entries.sort(key=lambda e: -e["yield_per_fission"])

    return {
        "schema_version": SCHEMA_VERSION,
        "id": OUT_ID,
        "label": "Fresh fission-product fallout (7:10)",
        "fissioning_system": "U-235 (thermal)",
        "yield_type": "cumulative",
        "yield_cutoff_per_fission": YIELD_CUTOFF,
        "n_nuclides": len(entries),
        "reference": (
            "ENDF/B-VIII.0 neutron fission yields, U-235, MF=8/MT=459 (cumulative), thermal "
            "0.0253 eV; see data/vendor/endf_nfy/PROVENANCE.md. Cumulative yields ≈ the H+1 h "
            "chain-fed inventory; double-count within chains is a documented shape-preserving "
            "approximation. Representative mix — a real weapon is fast U/Pu fission."
        ),
        "entries": entries,
    }


def build() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rec = build_fallout()
    (OUT_DIR / f"{rec['id']}.json").write_text(
        json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return rec["n_nuclides"]


if __name__ == "__main__":
    try:
        n = build()
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built fallout vector ({n} nuclides) into {OUT_DIR}")
