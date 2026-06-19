"""Build canonical fast-neutron removal cross-section files (M10 neutron shielding, §6.3).

Output : data/neutron_removal/<material>.json  (water, polyethylene, pmma)

The fast-neutron **effective removal cross-section** Σ_R (cm⁻¹) gives a hydrogenous shield's
dose attenuation directly: ``T = exp(−Σ_R·x)`` (no buildup factor — Σ_R is already
dose-calibrated against fission-spectrum measurements; a single energy-independent scalar per
material, valid ~2–12 MeV). It is assembled from the NCRP-20 (1957) **measured** elemental mass
removal cross-sections Σ_R/ρ (cm²/g) via the mixture rule:

    Σ_R/ρ (compound) = Σ_i w_i · (Σ_R/ρ)_i          [cm²/g]
    Σ_R (compound)   = ρ · Σ_R/ρ (compound)          [cm⁻¹]

Provenance + honesty: see data/vendor/ncrp20_removal/PROVENANCE.md and HANDOFF_PLAN §11 (M10).
The Wood (1982) semi-empirical Z-fit is deliberately NOT used — it gives H ≈ 0.190 cm²/g vs the
NCRP-20 measured 0.602, and hydrogen dominates fast-neutron removal. Only the pure hydrogenous
shields (H/C/O composition) are shipped; concrete/paraffin/borated-poly are deferred (would need
heavy-element Σ_R/ρ not sourced here — no-fabrication discipline).

Bulk densities are read from the existing data/attenuation/<material>.json so γ and neutron use
one density source. Dev-time step only; the Pyodide runtime reads the generated canonical files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
DATA_DIR = Path(__file__).resolve().parents[1]              # .../data
OUT_DIR = DATA_DIR / "neutron_removal"
ATTEN_DIR = DATA_DIR / "attenuation"

#: NCRP-20 (1957) measured elemental mass removal cross-sections Σ_R/ρ (cm²/g), transcribed via
#: Akyıldırım (2019) p.1144 (DOI 10.18185/erzifbed.587514). MEASURED, not the Wood Z-fit.
SIGMA_R_MASS_CM2_G: dict[str, float] = {
    "H": 0.602,
    "C": 0.051,
    "O": 0.041,
}

#: IUPAC standard atomic weights (g/mol) for the shipped light elements.
ATOMIC_WEIGHT: dict[str, float] = {
    "H": 1.008,
    "C": 12.011,
    "O": 15.999,
}

#: Shipped materials → element stoichiometry (atom counts in the formula unit). Every element
#: MUST be in SIGMA_R_MASS_CM2_G — a missing one is a loud build error, never a silent drop.
MATERIALS: dict[str, dict[str, int]] = {
    "water": {"H": 2, "O": 1},          # H₂O
    "polyethylene": {"C": 1, "H": 2},   # (CH₂)ₙ monomer unit
    "pmma": {"C": 5, "H": 8, "O": 2},   # C₅H₈O₂ (acrylic / Perspex)
}

CITATION = (
    "NCRP Report No. 20 (1957), Protection against Neutron Radiation up to 30 MeV, "
    "NBS Handbook 63; elemental Σ_R/ρ via Akyıldırım (2019), Erzincan Univ. J. Sci. Tech. "
    "12(2) 1141–1148, DOI 10.18185/erzifbed.587514."
)


class BuildError(Exception):
    """A structural / integrity failure in the removal-data build. Never swallowed."""


def weight_fractions(stoich: dict[str, int]) -> dict[str, float]:
    """Element weight fractions w_i = (n_i·A_i) / Σ(n_j·A_j) for a formula unit."""
    masses = {}
    for el, n in stoich.items():
        if el not in ATOMIC_WEIGHT:
            raise BuildError(f"no atomic weight for element {el!r}")
        masses[el] = n * ATOMIC_WEIGHT[el]
    total = sum(masses.values())
    if total <= 0:
        raise BuildError(f"non-positive formula weight for {stoich!r}")
    return {el: m / total for el, m in masses.items()}


def mass_removal(stoich: dict[str, int]) -> tuple[float, dict[str, float]]:
    """Mixture-rule compound Σ_R/ρ (cm²/g) and the per-element weight fractions."""
    w = weight_fractions(stoich)
    sigma_mass = 0.0
    for el, frac in w.items():
        if el not in SIGMA_R_MASS_CM2_G:
            raise BuildError(
                f"element {el!r} has no NCRP-20 Σ_R/ρ — refusing to drop it silently "
                f"(would under-count the shield). Source its value or defer the material."
            )
        sigma_mass += frac * SIGMA_R_MASS_CM2_G[el]
    return sigma_mass, w


def attenuation_density(material: str) -> float:
    """Bulk density ρ (g/cm³) from the existing attenuation file (one density source)."""
    path = ATTEN_DIR / f"{material}.json"
    if not path.is_file():
        raise BuildError(
            f"{material}: no attenuation file at {path} to source the bulk density from"
        )
    rho = json.loads(path.read_text(encoding="utf-8")).get("rho_g_cm3")
    if not (isinstance(rho, (int, float)) and rho > 0):
        raise BuildError(f"{material}: missing/invalid density in {path}")
    return float(rho)


def build_material(material: str, stoich: dict[str, int]) -> dict:
    rho = attenuation_density(material)
    sigma_mass, w = mass_removal(stoich)
    sigma_r = rho * sigma_mass
    # The hydrogen weight fraction is the validity discriminator (the removal method needs H);
    # store it so the engine's hydrogen-presence gate has an auditable basis, not a hard-coded set.
    return {
        "schema_version": SCHEMA_VERSION,
        "material": material,
        "rho_g_cm3": rho,
        "composition": {el: n for el, n in stoich.items()},
        "weight_fractions": {el: round(f, 6) for el, f in w.items()},
        "hydrogen_weight_fraction": round(w.get("H", 0.0), 6),
        "sigma_r_mass_cm2_g": round(sigma_mass, 6),
        "sigma_r_cm1": round(sigma_r, 6),
        "elemental_sigma_r_mass_cm2_g": {el: SIGMA_R_MASS_CM2_G[el] for el in stoich},
        "method": "NCRP-20 elemental Σ_R/ρ × mixture rule (Σ_R = ρ·Σ w_i·(Σ_R/ρ)_i)",
        "citation": CITATION,
    }


def _self_check() -> None:
    """Two independent cross-checks (also asserted as a test): glucose exact, water ~1.5%."""
    # Glucose C₆H₁₂O₆ ρ=1.562 → Akyıldırım Table 2 gives Σ_R = 0.129 cm⁻¹ exactly.
    glu_mass, _ = mass_removal({"C": 6, "H": 12, "O": 6})
    glu_sigma = 1.562 * glu_mass
    if abs(glu_sigma - 0.129) > 5e-4:
        raise BuildError(f"glucose cross-check failed: {glu_sigma:.4f} != 0.129 (Akyıldırım T2)")
    # Water vs El Abd (2017) Table 1 measured 0.1023 cm⁻¹ (independent source) → within ~2%.
    wat_mass, _ = mass_removal({"H": 2, "O": 1})
    wat_sigma = 1.0 * wat_mass
    if abs(wat_sigma - 0.1023) / 0.1023 > 0.03:
        raise BuildError(f"water cross-check failed: {wat_sigma:.4f} vs El Abd 0.1023")


def main() -> int:
    _self_check()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for material, stoich in MATERIALS.items():
        rec = build_material(material, stoich)
        out = OUT_DIR / f"{material}.json"
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {material:14s} rho={rec['rho_g_cm3']:.3f}  SigmaR/rho={rec['sigma_r_mass_cm2_g']:.4f} "
              f"cm2/g  SigmaR={rec['sigma_r_cm1']:.4f} cm-1  (w_H={rec['hydrogen_weight_fraction']:.3f})")
    print(f"Wrote {len(MATERIALS)} removal-cross-section files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
