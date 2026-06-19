"""Build canonical fast-neutron removal cross-section files (M10 neutron shielding, §6.3).

Output : data/neutron_removal/<material>.json
         (water, polyethylene, pmma, paraffin — mixture rule; concrete — published value)

The fast-neutron **effective removal cross-section** Σ_R (cm⁻¹) gives a hydrogenous shield's
dose attenuation directly: ``T = exp(−Σ_R·x)`` (no buildup factor — Σ_R is already
dose-calibrated against fission-spectrum measurements; a single energy-independent scalar per
material, valid ~2–12 MeV). Two construction paths, by data availability:

**(1) Mixture rule** (water, polyethylene, pmma, paraffin) — pure H/C/O compounds whose every
element has a NCRP-20 (1957) **measured** mass removal cross-section Σ_R/ρ (cm²/g):

    Σ_R/ρ (compound) = Σ_i w_i · (Σ_R/ρ)_i          [cm²/g]
    Σ_R (compound)   = ρ · Σ_R/ρ (compound)          [cm⁻¹]

The Wood (1982) semi-empirical Z-fit is deliberately NOT used here — it gives H ≈ 0.190 cm²/g vs
the NCRP-20 measured 0.602, and hydrogen dominates fast-neutron removal. Paraffin (CₙH₂ₙ₊₂) is
pure H/C, so it uses the SAME measured elemental values as polyethylene — no new empiricism.

**(2) Published whole-material value** (concrete) — concrete's heavy elements (Si/Ca/Al/Fe/…)
have no measured Σ_R/ρ in the NCRP-20 light-element set, and reconstructing them from an
empirical Z-fit is unanchored (no measured element above Z=8 in our set to validate it). So
concrete instead ships a **directly published** ordinary-concrete Σ_R (Ahmed et al. 2023), mass-
normalized and re-derived at the repo's γ density. The user's instruction order is honored:
credible source first, empirical only as a fallback we did not need.

Provenance + honesty: see data/vendor/ncrp20_removal/PROVENANCE.md and HANDOFF_PLAN §11 (M10).
Bulk densities come from the existing data/attenuation/<material>.json so γ and neutron use one
density source; a neutron-only material with no attenuation file (paraffin) declares its density
inline with a cited source. Dev-time step only; the Pyodide runtime reads the canonical files.
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

#: Mixture-rule materials → element stoichiometry (atom counts in the formula unit). Every
#: element MUST be in SIGMA_R_MASS_CM2_G — a missing one is a loud build error, never a silent
#: drop. Paraffin (CₙH₂ₙ₊₂, n=25 representative) is pure H/C, like polyethylene.
MATERIALS: dict[str, dict[str, int]] = {
    "water": {"H": 2, "O": 1},          # H₂O
    "polyethylene": {"C": 1, "H": 2},   # (CH₂)ₙ monomer unit
    "pmma": {"C": 5, "H": 8, "O": 2},   # C₅H₈O₂ (acrylic / Perspex)
    "paraffin": {"C": 25, "H": 52},     # CₙH₂ₙ₊₂, n=25 (paraffin wax, ~15 wt% H)
}

#: Bulk density (g/cm³) for materials with NO attenuation file (neutron-only shields). Cited
#: inline because there is no γ-side density to inherit. Paraffin wax density varies 0.87–0.93
#: with grade; 0.93 (NIST/PNNL "Paraffin wax") is used — the upper end is the standard reference.
DENSITY_INLINE: dict[str, tuple[float, str]] = {
    "paraffin": (
        0.93,
        "NIST/PNNL Compendium of Material Composition Data, 'Paraffin wax' (ρ=0.93 g/cm³; "
        "grade-dependent 0.87–0.93).",
    ),
}

#: Materials whose Σ_R ships as a DIRECTLY PUBLISHED whole-material value (not a mixture-rule
#: reconstruction) because the heavy elements lack a measured Σ_R/ρ in our set. Stored as the
#: density-independent mass removal Σ_R/ρ (= published Σ_R / published ρ) so Σ_R can be re-derived
#: at the repo's own bulk density (γ↔n slab consistency). ``h_weight_fraction`` feeds the engine's
#: hydrogen-presence validity gate and is the published composition's value (auditable, not 0).
PUBLISHED_REMOVAL: dict[str, dict] = {
    "concrete": {
        "published_sigma_r_cm1": 0.09989,   # Ahmed et al. (2023) OC-2, ordinary concrete
        "published_rho_g_cm3": 2.35,        # the density that value was reported at
        "h_weight_fraction": 0.0056,        # OC-2 Table 1: 0.56 wt% H (lowest of 5 → conservative)
        "composition_weight_fractions": {   # Ahmed et al. (2023), Table 1 (OC-2), for provenance
            "H": 0.0056, "O": 0.4956, "Na": 0.0171, "Mg": 0.0011, "Al": 0.0456,
            "Si": 0.3135, "K": 0.0192, "Ca": 0.0826, "Fe": 0.0122,
        },
        "method": (
            "published whole-material Σ_R (ordinary concrete, OC-2), mass-normalized and "
            "re-derived at the repo's γ-attenuation density for γ↔n slab consistency"
        ),
        "citation": (
            "Ahmed, R., Hassan, G.S., Scott, T. & Bakr, M. (2023), 'Assessment of Five Concrete "
            "Types as Candidate Shielding Materials for a Compact Radiation Source Based on the "
            "IECF', Materials 16(7) 2845, DOI 10.3390/ma16072845 (ordinary concrete OC-2: "
            "Σ_R = 0.09989 cm⁻¹ at ρ = 2.35 g/cm³)."
        ),
    },
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


def bulk_density(material: str) -> tuple[float, str]:
    """Bulk density ρ (g/cm³) and its source. Prefer the existing γ attenuation file (one density
    source for γ↔n); a neutron-only material with no attenuation file falls back to a cited inline
    density (DENSITY_INLINE). A material with neither is a loud build error, never a guessed ρ."""
    path = ATTEN_DIR / f"{material}.json"
    if path.is_file():
        rho = json.loads(path.read_text(encoding="utf-8")).get("rho_g_cm3")
        if not (isinstance(rho, (int, float)) and rho > 0):
            raise BuildError(f"{material}: missing/invalid density in {path}")
        return float(rho), f"data/attenuation/{material}.json (γ density source)"
    if material in DENSITY_INLINE:
        rho, src = DENSITY_INLINE[material]
        return float(rho), src
    raise BuildError(
        f"{material}: no attenuation file at {path} and no DENSITY_INLINE entry — refusing to "
        f"guess a bulk density (Σ_R = ρ·Σ_R/ρ would be fabricated)."
    )


def build_material(material: str, stoich: dict[str, int]) -> dict:
    rho, rho_src = bulk_density(material)
    sigma_mass, w = mass_removal(stoich)
    sigma_r = rho * sigma_mass
    # The hydrogen weight fraction is the validity discriminator (the removal method needs H);
    # store it so the engine's hydrogen-presence gate has an auditable basis, not a hard-coded set.
    return {
        "schema_version": SCHEMA_VERSION,
        "material": material,
        "rho_g_cm3": rho,
        "rho_source": rho_src,
        "composition": {el: n for el, n in stoich.items()},
        "weight_fractions": {el: round(f, 6) for el, f in w.items()},
        "hydrogen_weight_fraction": round(w.get("H", 0.0), 6),
        "sigma_r_mass_cm2_g": round(sigma_mass, 6),
        "sigma_r_cm1": round(sigma_r, 6),
        "elemental_sigma_r_mass_cm2_g": {el: SIGMA_R_MASS_CM2_G[el] for el in stoich},
        "method": "NCRP-20 elemental Σ_R/ρ × mixture rule (Σ_R = ρ·Σ w_i·(Σ_R/ρ)_i)",
        "citation": CITATION,
    }


def build_published_material(material: str, spec: dict) -> dict:
    """A material whose Σ_R is a directly published whole-material value. The published Σ_R is
    mass-normalized (Σ_R/ρ, density-independent) then re-densified at the repo's bulk density, so
    the SAME physical slab thickness feeds both the γ (attenuation) and neutron paths."""
    rho, rho_src = bulk_density(material)  # the repo's γ density (γ↔n consistency)
    sigma_mass = spec["published_sigma_r_cm1"] / spec["published_rho_g_cm3"]
    sigma_r = rho * sigma_mass
    wh = spec["h_weight_fraction"]
    if not (wh > 0.0):
        raise BuildError(
            f"{material}: published material needs a positive hydrogen weight fraction for the "
            f"validity gate (got {wh!r}) — the removal method is only valid with H present."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "material": material,
        "rho_g_cm3": rho,
        "rho_source": rho_src,
        "weight_fractions": {el: round(f, 6) for el, f in spec["composition_weight_fractions"].items()},
        "hydrogen_weight_fraction": round(wh, 6),
        "sigma_r_mass_cm2_g": round(sigma_mass, 6),
        "sigma_r_cm1": round(sigma_r, 6),
        "published_sigma_r_cm1": spec["published_sigma_r_cm1"],
        "published_rho_g_cm3": spec["published_rho_g_cm3"],
        "method": spec["method"],
        "citation": spec["citation"],
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
    # Paraffin (pure H/C) should land just above polyethylene per gram (more H per unit mass).
    par_mass, par_w = mass_removal({"C": 25, "H": 52})
    if not (0.13 < par_mass < 0.14 and 0.14 < par_w["H"] < 0.16):
        raise BuildError(f"paraffin cross-check failed: Σ_R/ρ={par_mass:.4f}, w_H={par_w['H']:.4f}")
    # Concrete: the re-densified published Σ_R must stay at the conservative low end of the
    # published ordinary-concrete band (Ahmed 2023: OC-2 0.0999 … OC-1 0.1496 @ ρ≈2.3–2.35).
    crec = build_published_material("concrete", PUBLISHED_REMOVAL["concrete"])
    if not (0.09 < crec["sigma_r_cm1"] < 0.11):
        raise BuildError(f"concrete cross-check failed: Σ_R={crec['sigma_r_cm1']:.4f} cm⁻¹")


def main() -> int:
    _self_check()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for material, stoich in MATERIALS.items():
        rec = build_material(material, stoich)
        out = OUT_DIR / f"{material}.json"
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {material:14s} rho={rec['rho_g_cm3']:.3f}  SigmaR/rho={rec['sigma_r_mass_cm2_g']:.4f} "
              f"cm2/g  SigmaR={rec['sigma_r_cm1']:.4f} cm-1  (w_H={rec['hydrogen_weight_fraction']:.3f})")
        written += 1
    for material, spec in PUBLISHED_REMOVAL.items():
        rec = build_published_material(material, spec)
        out = OUT_DIR / f"{material}.json"
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {material:14s} rho={rec['rho_g_cm3']:.3f}  SigmaR/rho={rec['sigma_r_mass_cm2_g']:.4f} "
              f"cm2/g  SigmaR={rec['sigma_r_cm1']:.4f} cm-1  (w_H={rec['hydrogen_weight_fraction']:.3f}) [published]")
        written += 1
    print(f"Wrote {written} removal-cross-section files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
