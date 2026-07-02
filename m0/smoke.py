"""M0 Pyodide smoke test — physics core foundation check.

Single source of truth for the M0 smoke test (HANDOFF_PLAN.md §10). The *same*
file is executed in two hosts:

  * native CPython 3.14   -> fast correctness loop while developing (run_native.py)
  * Pyodide 314 (browser) -> the real foundation evidence (index.html, driven
    headless by drive_browser.mjs)

It does NOT print physics conclusions it did not check. ``run_smoke()`` returns a
JSON-serialisable dict; the host adds load/install timing and renders it. Per the
repo's "no silent errors" rule, failures are captured into the result and flip
``overall_pass`` to False rather than being swallowed — but we never fabricate a
fallback number.

What it proves (and only what it proves):
  1. radioactivedecay imports and reports versions of itself + the SciPy stack.
  2. A known chain solves: Cs-137 -> Ba-137m secular equilibrium, validated by
     asserting A(Ba-137m)/A(Cs-137) at equilibrium == the Cs-137->Ba-137m
     branching fraction *pulled from radioactivedecay's own data* (not hardcoded).
  3. Compute timing for a single solve and for a batch of time evaluations
     (the "solve once, evaluate many" cost, §3) — labelled compute-only.
  4. A lightweight spectral-data probe (§13.6): can we read Cs-137/Ba-137m's
     ~0.662 MeV photon line out of radioactivedecay's API at all? This only
     answers "does the path exist"; full spectral validation is M2.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from importlib.metadata import PackageNotFoundError, version

# Equilibrium is checked against the library's own branching fraction, so this
# tolerance only has to absorb the tiny lambda_d/(lambda_d - lambda_p) correction
# (Cs-137 ~30 yr vs Ba-137m ~2.55 min => correction < 1e-6) plus float noise.
EQUILIBRIUM_REL_TOL = 1e-3
# 1 day >> Ba-137m half-life (~564 half-lives) and << Cs-137 half-life, so the
# daughter is fully grown in and the parent has barely decayed.
EQUILIBRIUM_DECAY_DAYS = 1.0


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT INSTALLED"


def _collect_versions() -> dict:
    import radioactivedecay as rd

    return {
        "python": sys.version.split()[0],
        "radioactivedecay": getattr(rd, "__version__", _pkg_version("radioactivedecay")),
        "numpy": _pkg_version("numpy"),
        "scipy": _pkg_version("scipy"),
        "sympy": _pkg_version("sympy"),
        "pandas": _pkg_version("pandas"),
        "networkx": _pkg_version("networkx"),
    }


def _branching_to(parent: str, daughter: str) -> dict:
    """Pull the parent->daughter branching fraction straight from the library."""
    import radioactivedecay as rd

    nuc = rd.Nuclide(parent)
    progeny = list(nuc.progeny())
    fractions = list(nuc.branching_fractions())
    modes = list(nuc.decay_modes())
    if daughter not in progeny:
        raise ValueError(f"{daughter} is not listed as progeny of {parent}; progeny={progeny}")
    bf = float(fractions[progeny.index(daughter)])
    return {
        "parent": parent,
        "daughter": daughter,
        "progeny": progeny,
        "branching_fractions": [float(f) for f in fractions],
        "decay_modes": [str(m) for m in modes],
        "branching_to_daughter": bf,
        "half_life_parent_yr": float(nuc.half_life("y")),
        "half_life_daughter_min": float(rd.Nuclide(daughter).half_life("m")),
    }


def _equilibrium_check() -> dict:
    """Cs-137 -> Ba-137m secular equilibrium against the library's own branching."""
    import radioactivedecay as rd

    parent, daughter = "Cs-137", "Ba-137m"
    chain = _branching_to(parent, daughter)
    bf = chain["branching_to_daughter"]

    inv = rd.Inventory({parent: 1.0}, "Bq")
    decayed = inv.decay(EQUILIBRIUM_DECAY_DAYS, "d")
    activities = {k: float(v) for k, v in decayed.activities("Bq").items()}

    a_parent = activities.get(parent, 0.0)
    a_daughter = activities.get(daughter, 0.0)
    if a_parent <= 0.0:
        raise ValueError(f"parent activity non-positive after decay: {activities}")

    ratio = a_daughter / a_parent
    rel_err = abs(ratio - bf) / bf
    return {
        "description": (
            "A(Ba-137m)/A(Cs-137) at equilibrium should equal the "
            "Cs-137->Ba-137m branching fraction"
        ),
        "decay_time_days": EQUILIBRIUM_DECAY_DAYS,
        "activities_Bq": activities,
        "ratio_measured": ratio,
        "branching_expected": bf,
        "rel_error": rel_err,
        "rel_tol": EQUILIBRIUM_REL_TOL,
        "chain": chain,
        "pass": rel_err <= EQUILIBRIUM_REL_TOL,
    }


def _timing_check() -> dict:
    """Compute-only timing: one solve, then a batch of log-spaced evaluations.

    radioactivedecay re-solves analytically on each .decay(); the true
    "solve once, evaluate many" optimisation (§3) is M1's job. This measures the
    naive per-evaluation cost so we know how much M1 has to beat.
    """
    import radioactivedecay as rd

    inv = rd.Inventory({"Cs-137": 1.0}, "Bq")

    t0 = time.perf_counter()
    _ = inv.decay(1.0, "d").activities("Bq")
    single_solve_s = time.perf_counter() - t0

    # A log-time sweep like the slider/animate control would request.
    n_eval = 200
    times = [10 ** (-3 + 6 * i / (n_eval - 1)) for i in range(n_eval)]  # 1e-3 .. 1e3 days
    t0 = time.perf_counter()
    for t in times:
        inv.decay(t, "d").activities("Bq")
    batch_s = time.perf_counter() - t0

    return {
        "note": "compute-only; excludes Pyodide load + micropip install",
        "single_solve_s": single_solve_s,
        "n_evaluations": n_eval,
        "batch_total_s": batch_s,
        "per_evaluation_ms": (batch_s / n_eval) * 1000.0,
    }


def _spectral_probe() -> dict:
    """Does radioactivedecay expose photon line energies/yields at all? (§13.6)

    This is a *discovery* probe, not a validation. It introspects the API and
    tries to find Cs-137 / Ba-137m's ~0.662 MeV line. The answer steers M2: if
    radioactivedecay surfaces ICRP-107 RAD spectra we can lean on it; if not, M2
    must bundle ENSDF / ICRP-107 RAD tables separately.
    """
    import radioactivedecay as rd

    findings: dict = {"checked": [], "found_0662_line": False, "details": []}

    keywords = ("gamma", "photon", "spectr", "energ", "emiss", "intens", "yield")

    def surface(obj, label):
        names = sorted(n for n in dir(obj) if not n.startswith("_"))
        hits = [n for n in names if any(k in n.lower() for k in keywords)]
        findings["checked"].append({"object": label, "candidate_attrs": hits})
        return hits

    surface(rd, "module radioactivedecay")
    nuc = rd.Nuclide("Cs-137")
    surface(nuc, "Nuclide('Cs-137')")

    # Inspect the underlying decay dataset directly — this is where spectra would
    # live if radioactivedecay carried them.
    dataset = getattr(nuc, "decay_data", None) or getattr(rd, "DEFAULTDATA", None)
    if dataset is not None:
        ds_fields = sorted(n for n in dir(dataset) if not n.startswith("_"))
        spectral_fields = [n for n in ds_fields if any(k in n.lower() for k in keywords)]
        findings["dataset_name"] = getattr(dataset, "dataset_name", "unknown")
        findings["dataset_fields"] = ds_fields
        findings["dataset_spectral_fields"] = spectral_fields

    # Try the most likely spectral entry points without assuming they exist.
    for nuclide_id in ("Cs-137", "Ba-137m"):
        try:
            n = rd.Nuclide(nuclide_id)
        except Exception as exc:  # noqa: BLE001 - record, don't swallow
            findings["details"].append(f"Nuclide({nuclide_id!r}) failed: {exc!r}")
            continue
        for attr in (
            "gammas",
            "photons",
            "gamma_spectrum",
            "spectrum",
            "plot_spectrum",
            "radiations",
        ):
            fn = getattr(n, attr, None)
            if fn is None:
                continue
            try:
                value = fn() if callable(fn) else fn
                text = repr(value)
                findings["details"].append(f"{nuclide_id}.{attr} -> {text[:300]}")
                if "0.66" in text or "662" in text:
                    findings["found_0662_line"] = True
            except Exception as exc:  # noqa: BLE001 - record, don't swallow
                findings["details"].append(f"{nuclide_id}.{attr}() raised {exc!r}")

    spectral_available = findings["found_0662_line"] or bool(
        findings.get("dataset_spectral_fields")
    )
    findings["spectral_available"] = spectral_available
    findings["verdict"] = (
        "radioactivedecay exposes photon line data — M2 may lean on it."
        if spectral_available
        else (
            "radioactivedecay exposes decay topology only (no emission spectra); "
            "M2 must bundle ICRP-107 RAD / ENSDF source-term tables separately, "
            "as HANDOFF_PLAN.md §7 anticipates."
        )
    )
    return findings


def run_smoke() -> dict:
    # `errors` gate overall_pass (foundation-critical); `warnings` are captured
    # loudly but do not fail the smoke test (informative checks).
    result: dict = {"overall_pass": False, "errors": [], "warnings": []}

    # Versions gate: if radioactivedecay can't import, the foundation is broken.
    try:
        result["versions"] = _collect_versions()
    except Exception:  # noqa: BLE001
        result["errors"].append("versions: " + traceback.format_exc())

    gating = {"equilibrium"}  # timing/probe are informative, not gating
    for key, fn in (
        ("equilibrium", _equilibrium_check),
        ("timing", _timing_check),
        ("spectral_probe", _spectral_probe),
    ):
        try:
            result[key] = fn()
        except Exception:  # noqa: BLE001 - capture loudly, never swallow
            result[key] = {"error": traceback.format_exc()}
            bucket = "errors" if key in gating else "warnings"
            result[bucket].append(f"{key}: see result[{key!r}]['error']")

    eq = result.get("equilibrium", {})
    result["overall_pass"] = bool(eq.get("pass")) and not result["errors"]
    return result


if __name__ == "__main__":
    print(json.dumps(run_smoke(), indent=2))
