"""Build canonical per-nuclide emission files from the vendored ICRP-107 data.

Source  : data/vendor/icrp107/<Nuclide>.json   (verbatim OpenGATE/icrp107-database
          0.0.3 reformat of ICRP Publication 107; see data/vendor/PROVENANCE.md)
Output  : data/emissions/<Nuclide>.json          (this project's canonical schema)

Design contract: HANDOFF_PLAN.md ss7 (data layer is the critical path) and the M2
dev-doc (docs/plans/M2-emissions.md). This is a *dev-time* step: the browser/Pyodide
runtime only ever reads the generated canonical files, never the upstream package.

No silent errors (CLAUDE.md): every structural surprise -- an unknown emission
category, a row that is not [energy, value], a negative energy/yield, a filename that
disagrees with the embedded name -- raises loudly rather than being dropped or
papered over. A drift in the vendored bytes (against the pinned manifest hash) also
raises, so the canonical files can never be silently rebuilt from changed inputs.

The upstream files are *double-encoded*: a JSON string whose content is itself JSON.
We decode both layers. Floats are passed through unchanged (no rounding), so the
transform-integrity tests can compare canonical vs upstream by exact equality.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SOURCE = (
    "ICRP-107 (Endo & Eckerman 2008, Ann. ICRP 38(3)); "
    "reformatted via OpenGATE/icrp107-database 0.0.3"
)

DATA_DIR = Path(__file__).resolve().parents[1]          # .../data
VENDOR_DIR = DATA_DIR / "vendor" / "icrp107"
MANIFEST_PATH = DATA_DIR / "vendor" / "MANIFEST.sha256"
OUT_DIR = DATA_DIR / "emissions"

# Pinned combined hash of the vendored upstream (sha256 over the sorted
# "<sha256>  <name>" manifest lines). Regenerating from drifted bytes must fail.
EXPECTED_MANIFEST_SHA256 = (
    "e47776c9f46440a4445ccc275630a4a930a17f710fa527936a2d11786331c14d"
)

# Every ICRP-107 emission category must map to exactly one canonical destination.
# A category seen in the data but absent here is a loud error, not a silent drop.
# Photons (gamma U X U annihilation) are aggregated for the dose engine and tagged
# with provenance via `origin`; annihilation yields are already per-photon (verified
# on Na-22: 0.511 MeV at ~1.798 ~= 2 x the 0.899 beta+ branch).
PHOTON_ORIGINS = {"gamma", "X", "annihilation"}
ELECTRON_ORIGINS = {"auger", "IE"}            # IE = internal-conversion electrons
BETA_KINDS = {"beta-", "beta+"}               # discrete lines; ICRP energy is the MEAN
# Continuous beta spectrum (dN/dE, summed over branches -- see M2 dev-doc).
SPECTRUM_CATEGORIES = {"b-spectra"}
ALPHA_CATEGORIES = {"alpha"}
NEUTRON_CATEGORIES = {"neutron"}
# Categories captured verbatim; their physical semantics are deferred (M4/M5).
EXTRA_CATEGORIES = {"alpha recoil", "betaD", "fission"}

KNOWN_CATEGORIES = (
    PHOTON_ORIGINS
    | ELECTRON_ORIGINS
    | BETA_KINDS
    | SPECTRUM_CATEGORIES
    | ALPHA_CATEGORIES
    | NEUTRON_CATEGORIES
    | EXTRA_CATEGORIES
)


class BuildError(Exception):
    """A structural / integrity failure in the data build. Never swallowed."""


def verify_vendor_manifest() -> None:
    """Recompute the vendored-bytes hash and refuse to build on any drift."""
    files = sorted(p.name for p in VENDOR_DIR.glob("*.json"))
    if not files:
        raise BuildError(f"no vendored upstream files under {VENDOR_DIR}")
    lines = []
    for name in files:
        digest = hashlib.sha256((VENDOR_DIR / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    manifest = "\n".join(lines)
    combined = hashlib.sha256(manifest.encode()).hexdigest()
    if combined != EXPECTED_MANIFEST_SHA256:
        raise BuildError(
            "vendored ICRP-107 bytes drifted from the pinned manifest hash\n"
            f"  expected {EXPECTED_MANIFEST_SHA256}\n  got      {combined}\n"
            "If this change is intentional, update EXPECTED_MANIFEST_SHA256 and "
            "data/vendor/MANIFEST.sha256 deliberately."
        )
    # Keep the on-disk manifest in sync (cheap; documents the pinned set).
    MANIFEST_PATH.write_text(manifest + "\n", encoding="utf-8")


def load_upstream(path: Path) -> dict:
    """Decode an upstream file's two JSON layers, validating the envelope."""
    outer = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(outer, str):
        raise BuildError(f"{path.name}: expected a JSON-string outer layer")
    data = json.loads(outer)
    required = {"emissions", "half_life", "name", "time_unit"}
    missing = required - set(data)
    if missing:
        raise BuildError(f"{path.name}: missing top-level keys {sorted(missing)}")
    stem = path.stem
    if data["name"] != stem:
        raise BuildError(
            f"{path.name}: embedded name {data['name']!r} != filename stem {stem!r}"
        )
    return data


def _row(name: str, cat: str, row) -> tuple[float, float]:
    """Validate and unpack one [energy_MeV, value] row."""
    if not isinstance(row, list) or len(row) != 2:
        raise BuildError(f"{name}/{cat}: row is not [energy, value]: {row!r}")
    energy, value = row
    if energy < 0:
        raise BuildError(f"{name}/{cat}: negative energy {energy}")
    if value < 0:
        raise BuildError(f"{name}/{cat}: negative value {value}")
    return energy, value


def transform(data: dict) -> dict:
    """Map one upstream record into the canonical schema (no rounding)."""
    name = data["name"]
    emissions = data["emissions"]

    photons: list[dict] = []
    betas: list[dict] = []
    alphas: list[dict] = []
    electrons: list[dict] = []
    neutrons: list[dict] = []
    beta_spectra: list[dict] = []
    extra: dict[str, list] = {}

    for cat, rows in emissions.items():
        if cat not in KNOWN_CATEGORIES:
            raise BuildError(
                f"{name}: unknown emission category {cat!r} -- refusing to drop it"
            )
        if not rows:
            continue
        if cat in PHOTON_ORIGINS:
            for e, y in (_row(name, cat, r) for r in rows):
                photons.append({"E_MeV": e, "yield": y, "origin": cat})
        elif cat in BETA_KINDS:
            for e, y in (_row(name, cat, r) for r in rows):
                betas.append({"E_mean_MeV": e, "yield": y, "kind": cat})
        elif cat in ALPHA_CATEGORIES:
            for e, y in (_row(name, cat, r) for r in rows):
                alphas.append({"E_MeV": e, "yield": y})
        elif cat in ELECTRON_ORIGINS:
            for e, y in (_row(name, cat, r) for r in rows):
                electrons.append({"E_MeV": e, "yield": y, "origin": cat})
        elif cat in NEUTRON_CATEGORIES:
            for e, y in (_row(name, cat, r) for r in rows):
                neutrons.append({"E_MeV": e, "yield": y})
        elif cat in SPECTRUM_CATEGORIES:
            for e, i in (_row(name, cat, r) for r in rows):
                beta_spectra.append({"E_MeV": e, "intensity": i})
        elif cat in EXTRA_CATEGORIES:
            # Validate shape, preserve verbatim (semantics deferred to M4/M5).
            for r in rows:
                _row(name, cat, r)
            extra[cat] = rows
        else:  # pragma: no cover - KNOWN_CATEGORIES guards this
            raise BuildError(f"{name}: unrouted category {cat!r}")

    # Photons feed the dose line-sum; emit them in ascending energy.
    photons.sort(key=lambda p: p["E_MeV"])

    canonical = {
        "schema_version": SCHEMA_VERSION,
        "nuclide": name,
        "source": SOURCE,
        "photons": photons,
        "betas": betas,
        "alphas": alphas,
        "electrons": electrons,
        "neutrons": neutrons,
        "beta_spectra": beta_spectra,
    }
    if extra:
        canonical["extra"] = extra
    return canonical


def build() -> int:
    verify_vendor_manifest()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(VENDOR_DIR.glob("*.json"))
    count = 0
    for path in files:
        canonical = transform(load_upstream(path))
        out = OUT_DIR / f"{canonical['nuclide']}.json"
        # Deterministic, readable, exact-float output for auditable git diffs.
        out.write_text(
            json.dumps(canonical, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        count += 1
    return count


if __name__ == "__main__":
    try:
        n = build()
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"built {n} canonical emission files into {OUT_DIR}")
