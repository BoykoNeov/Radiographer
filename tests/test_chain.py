"""DAG topology tests — nodes (with N,Z coords) + edges, reconvergence, SF sink."""

from __future__ import annotations

from engine.bridge import _solve_obj  # internal helper returning the SolvedInventory
from engine.chain import SF_SINK_ID, build_dag


def _dag(spec):
    return build_dag(_solve_obj(spec, "Bq"))


def test_nodes_carry_NZ_coordinates_and_halflife():
    dag = _dag({"Cs-137": 1.0})
    by_id = {n["id"]: n for n in dag["nodes"]}
    cs = by_id["Cs-137"]
    assert cs["Z"] == 55 and cs["A"] == 137 and cs["N"] == 82
    assert cs["stable"] is False
    assert cs["half_life_s"] > 0
    ba = by_id["Ba-137"]
    assert ba["stable"] is True and ba["half_life_s"] is None
    assert by_id["Ba-137m"]["state"] == "m"


def test_edges_have_mode_and_branching():
    dag = _dag({"Cs-137": 1.0})
    edge = next(e for e in dag["edges"] if e["source"] == "Cs-137" and e["target"] == "Ba-137m")
    assert edge["mode"]  # e.g. "β-"
    assert 0.9 < edge["branching"] <= 1.0


def test_u238_chain_branches_and_reconverges():
    """Bi-214 branches (β-/α) and both paths merge back at Pb-210 — a true DAG."""
    dag = _dag({"U-238": 1.0})
    edges = dag["edges"]
    bi214_targets = {e["target"] for e in edges if e["source"] == "Bi-214"}
    assert {"Po-214", "Tl-210"}.issubset(bi214_targets)  # the branch
    # both Po-214 and Tl-210 lead (directly) to Pb-210 -> reconvergence
    into_pb210 = {e["source"] for e in edges if e["target"] == "Pb-210"}
    assert {"Po-214", "Tl-210"}.issubset(into_pb210)


def test_spontaneous_fission_is_an_honest_sink():
    """U-238's tiny SF branch is shown as a terminal sink, not silently dropped."""
    dag = _dag({"U-238": 1.0})
    ids = {n["id"] for n in dag["nodes"]}
    assert SF_SINK_ID in ids
    sf_node = next(n for n in dag["nodes"] if n["id"] == SF_SINK_ID)
    assert sf_node["stable"] is True  # terminal
    assert any(e["target"] == SF_SINK_ID and e["mode"] == "SF" for e in dag["edges"])


def test_every_edge_target_is_a_node():
    """No dangling edges — every target resolves to a node (closure integrity)."""
    dag = _dag({"Th-232": 1.0, "U-238": 1.0})
    ids = {n["id"] for n in dag["nodes"]}
    for e in dag["edges"]:
        assert e["source"] in ids
        assert e["target"] in ids


def test_nodes_match_solve_closure():
    """DAG nodes (minus the SF sink) are exactly the solve's closure — no drift."""
    solved = _solve_obj({"U-238": 1.0}, "Bq")
    dag = build_dag(solved)
    node_ids = {n["id"] for n in dag["nodes"] if n["id"] != SF_SINK_ID}
    assert node_ids == set(solved.names)
