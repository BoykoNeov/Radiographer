"""Acquire the NIST X-Ray Mass Attenuation Coefficient pages we vendor.

Source : NIST Standard Reference Database 126 — "Tables of X-Ray Mass Attenuation
         Coefficients and Mass Energy-Absorption Coefficients", J.H. Hubbell &
         S.M. Seltzer (NISTIR 5632), https://physics.nist.gov/PhysRefData/XrayMassCoef/
Output : data/vendor/nist_xraymac/{elem,comp}/*.html  + tab1.html + tab2.html

This is a *one-time acquisition* step, analogous to `pip install icrp107-database`
for emissions: it pulls the upstream bytes that then get vendored verbatim. The
hermetic build (`build_attenuation.py`) reads only the vendored files and never the
network. Re-run this only to deliberately re-vendor (then regenerate the manifest and
update the pinned hash in the build).

Bytes are written **verbatim** (exactly as served) so the provenance is byte-exact.
NIST gates on a User-Agent, so we send one.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://physics.nist.gov/PhysRefData/XrayMassCoef"
UA = {"User-Agent": "Mozilla/5.0 (Radiographer dataset build; research/non-commercial)"}

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "nist_xraymac"

# Elements we vendor: id -> Z (page is ElemTab/z<Z>.html). Density comes from tab1.
ELEMENTS = {
    "lead": 82,
    "tungsten": 74,
    "iron": 26,
    "copper": 29,
    "aluminium": 13,
}

# Compounds we vendor: id -> NIST ComTab basename (page is ComTab/<base>.html).
# Density + exact material name come from tab2.
COMPOUNDS = {
    "water": "water",
    "air": "air",
    "tissue_soft": "tissue",
    "concrete": "concrete",
    "pmma": "pmma",
    "polyethylene": "polyethylene",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (trusted host)
        return r.read()


def fetch() -> int:
    (VENDOR / "elem").mkdir(parents=True, exist_ok=True)
    (VENDOR / "comp").mkdir(parents=True, exist_ok=True)
    n = 0
    for _id, z in ELEMENTS.items():
        out = VENDOR / "elem" / f"z{z}.html"
        out.write_bytes(_get(f"{BASE}/ElemTab/z{z}.html"))
        n += 1
    for _id, base in COMPOUNDS.items():
        out = VENDOR / "comp" / f"{base}.html"
        out.write_bytes(_get(f"{BASE}/ComTab/{base}.html"))
        n += 1
    # Density index tables (Table 1 = elements, Table 2 = compounds/mixtures).
    for tab in ("tab1", "tab2"):
        (VENDOR / f"{tab}.html").write_bytes(_get(f"{BASE}/{tab}.html"))
        n += 1
    return n


if __name__ == "__main__":
    count = fetch()
    print(f"fetched {count} NIST pages into {VENDOR}", file=sys.stderr)
