"""Decay-chain DAG (nodes + edges) for the Cytoscape view (HANDOFF_PLAN §8/§9).

Nodes are the *same descendant-closure set* the solve computes (shared verbatim,
so node list and inventory can't drift). Each node carries (Z, A, N=A−Z) — free
from ``rd.Nuclide`` and required by the locked (N, Z) chart-of-nuclides layout.
Edges are every closure member's direct progeny, so branch-and-reconverge
topology (e.g. U-238: Bi-214 branches β⁻/α, both merge back at Pb-210) falls out
without recursion.

Spontaneous fission is exposed by ``radioactivedecay`` as the pseudo-target
``'SF'`` (not a real nuclide). We render it as one honest terminal sink node so
the branch is visible without pretending to model fission products (out of scope
until M5). A *real* progeny outside the closure would be a drift bug → raised.
"""

from __future__ import annotations

import math

import radioactivedecay as rd

from engine.inventory import EngineError, SolvedInventory

SF_SINK_ID = "SF"
SF_SINK_LABEL = "spontaneous fission products"


def build_dag(solved: SolvedInventory) -> dict:
    dd = solved.decay_data
    names = list(solved.names)
    nameset = set(names)

    nodes: list[dict] = []
    edges: list[dict] = []
    has_sf = False

    for name in names:
        nuc = rd.Nuclide(name, dd)
        hl = float(dd.half_life(name, "s"))
        stable = math.isinf(hl)
        nodes.append(
            {
                "id": name,
                "Z": int(nuc.Z),
                "A": int(nuc.A),
                "N": int(nuc.A) - int(nuc.Z),
                "state": nuc.state or "",
                "half_life_s": None if stable else hl,
                "half_life_readable": dd.half_life(name, "readable"),
                "stable": bool(stable),
                "decay_modes": [str(m) for m in nuc.decay_modes()],
            }
        )
        if stable:
            continue

        for tgt, bf, mode in zip(nuc.progeny(), nuc.branching_fractions(), nuc.decay_modes()):
            tgt = str(tgt)
            if tgt in nameset:
                edges.append(
                    {"source": name, "target": tgt, "mode": str(mode), "branching": float(bf)}
                )
            elif tgt == SF_SINK_ID or str(mode) == "SF":
                has_sf = True
                edges.append(
                    {"source": name, "target": SF_SINK_ID, "mode": "SF", "branching": float(bf)}
                )
            else:
                raise EngineError(
                    f"progeny {tgt!r} of {name!r} is outside the solve closure "
                    f"({sorted(nameset)}) — DAG/solve drift"
                )

    if has_sf:
        nodes.append(
            {
                "id": SF_SINK_ID,
                "label": SF_SINK_LABEL,
                "Z": None,
                "A": None,
                "N": None,
                "state": "",
                "half_life_s": None,
                "half_life_readable": "terminal",
                "stable": True,
                "decay_modes": [],
            }
        )

    return {"nodes": nodes, "edges": edges}
