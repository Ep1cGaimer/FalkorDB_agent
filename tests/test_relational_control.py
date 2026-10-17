"""Relational control vs. the independent oracle and the live FalkorDB graph.

``evals/relational_control.py`` derives obligations from the raw fixture facts with SQL joins.
This test proves representational parity, not control failure: for every oracle case it compares
(a) the SQL obligation set with the oracle's and (b) the SQL set with the FalkorDB set produced by
the shipped pipeline, asserting exact equality of (service, version, route_id, store_id, record_id) keys. A tie is the expected,
acceptable outcome.
"""
from __future__ import annotations

import importlib.util

import pytest

from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
from rw.pipeline import Session
from rw.verification import REPO_ROOT
from evals.obligation_identity import oracle_obligations

CONTROL_PATH = REPO_ROOT / "evals" / "relational_control.py"
_spec = importlib.util.spec_from_file_location("relational_control", CONTROL_PATH)
assert _spec and _spec.loader
control = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(control)


@pytest.fixture(scope="module")
def connections():
    connections = {}
    yield connections
    for connection in connections.values():
        connection.close()


@pytest.fixture
def conn(oracle_case, connections):
    root, _case = oracle_case
    if root not in connections:
        connections[root] = control.load_facts(root)
    return connections[root]


def _release_id(session: Session, service: str, version: str) -> str:
    from rw import graph as G
    rows, _ = G.releases_for_service(session.g, service)
    match = [r["release_id"] for r in rows if r["version"] == version]
    assert len(match) == 1, (service, version, rows)
    return match[0]


def test_sql_obligations_match_oracle_and_falkordb(oracle_case, conn, oracle_graph):
    root, case = oracle_case
    case_id = case["id"]
    ids = control.release_ids(root)
    snapshot = case["snapshot"].removeprefix("snapshot:")
    fleet = {service: spec["version"] for service, spec in case["fleet"].items()}
    flags = {service: (spec.get("flags") or {}) for service, spec in case["fleet"].items()}

    sql_rows = control.obligations(conn, snapshot, fleet)
    sql_set = control.sql_keys(sql_rows, ids)
    want_set = set(oracle_obligations(case))
    assert len(sql_set) == len(sql_rows) == len(want_set)
    assert sql_set == want_set, f"SQL control disagrees with the independent oracle on case {case_id}"

    session = Session(snapshot=snapshot, graph_name=oracle_graph["name"],
                      reimport=not oracle_graph["imported"], fixture_root=root)
    oracle_graph["imported"] = True
    changes = [FleetEntry(service=service, release_id=_release_id(session, service, version),
                          flags=flags.get(service) or {})
               for service, version in sorted(fleet.items())]
    plan, errors = session.plan_from_proposal(
        GroundingProposal(changes=changes, citations=[], rationale="relational control"),
        f"relational control case {case_id}", origin="fixture", label=case_id)
    assert not errors and plan is not None
    report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(),
                                                    confirmed_by="test-operator",
                                                    confirmed_at="2026-10-15T00:00:00Z"))
    graph_set = control.graph_keys(report["verification"], ids)
    assert len(graph_set) == len(sql_rows)
    assert sql_set == graph_set, f"SQL control disagrees with FalkorDB on case {case_id}"


def test_sql_gap_kinds_match_oracle(oracle_case, conn):
    _root, case = oracle_case
    case_id = case["id"]
    snapshot = case["snapshot"].removeprefix("snapshot:")
    fleet = {service: spec["version"] for service, spec in case["fleet"].items()}
    got = {g["kind"] for g in control.gaps(conn, snapshot, fleet)}
    assert got == {g["kind"] for g in case["gaps"]}, f"gap kinds differ on case {case_id}"


def test_bundle_rollback_naive_selector():
    """Oracle case C: the naive release selector rolls both bundled services back one version."""
    with control.load_facts() as conn:
        assert control.bundle_rollback(conn, "snap-001", "rollout-2026-10-basket") == {
            "cart": "1.4", "checkout": "2.0"}


def test_variant_comparison_cli(identity_fixture_root):
    assert control.compare(identity_fixture_root, REPO_ROOT / "evals/expected/obligation_identity.json") == 0
