"""Relational control vs. the independent oracle and the live FalkorDB graph.

``evals/relational_control.py`` derives obligations from the raw fixture facts with SQL joins.
This test proves representational parity, not control failure: for every oracle case it compares
(a) the SQL obligation set with the oracle's and (b) the SQL set with the FalkorDB set produced by
the shipped pipeline, asserting exact equality of (service, record_id) pairs. A tie is the expected,
acceptable outcome.
"""
from __future__ import annotations

import importlib.util
import json
import uuid

import pytest

from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
from rw.pipeline import Session
from rw.verification import REPO_ROOT

CONTROL_PATH = REPO_ROOT / "evals" / "relational_control.py"
_spec = importlib.util.spec_from_file_location("relational_control", CONTROL_PATH)
assert _spec and _spec.loader
control = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(control)

ORACLE = json.loads((REPO_ROOT / "evals" / "expected" / "dispositions.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in ORACLE["cases"]}


@pytest.fixture(scope="module")
def conn():
    connection = control.load_facts()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def graph_name():
    name = f"rw_test_{uuid.uuid4().hex[:8]}"
    yield name
    from rw import graph as G
    try:
        G.connect().select_graph(name).delete()
    except Exception:
        pass


@pytest.fixture(scope="module")
def import_state():
    return {"imported": False}


def _release_id(session: Session, service: str, version: str) -> str:
    from rw import graph as G
    rows, _ = G.releases_for_service(session.g, service)
    match = [r["release_id"] for r in rows if r["version"] == version]
    assert len(match) == 1, (service, version, rows)
    return match[0]


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_sql_obligations_match_oracle_and_falkordb(case_id, conn, graph_name, import_state):
    case = CASES[case_id]
    snapshot = case["snapshot"].removeprefix("snapshot:")
    fleet = {service: spec["version"] for service, spec in case["fleet"].items()}
    flags = {service: (spec.get("flags") or {}) for service, spec in case["fleet"].items()}

    sql_rows = control.obligations(conn, snapshot, fleet)
    sql_set = {(row[0], row[4]) for row in sql_rows}
    want_set = {(o["service"], o["record_id"]) for o in case["obligations"]}
    assert sql_set == want_set, f"SQL control disagrees with the independent oracle on case {case_id}"

    session = Session(snapshot=snapshot, graph_name=graph_name, reimport=not import_state["imported"])
    import_state["imported"] = True
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
    graph_set = {(o["tuple"]["service"], o["tuple"]["record_id"])
                 for o in report["verification"]["obligations"]}
    assert sql_set == graph_set, f"SQL control disagrees with FalkorDB on case {case_id}"


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_sql_gap_kinds_match_oracle(case_id, conn):
    case = CASES[case_id]
    snapshot = case["snapshot"].removeprefix("snapshot:")
    fleet = {service: spec["version"] for service, spec in case["fleet"].items()}
    got = {g["kind"] for g in control.gaps(conn, snapshot, fleet)}
    assert got == {g["kind"] for g in case["gaps"]}, f"gap kinds differ on case {case_id}"


def test_bundle_rollback_naive_selector(conn):
    """Oracle case C: the naive release selector rolls both bundled services back one version."""
    assert control.bundle_rollback(conn, "snap-001", "rollout-2026-10-basket") == {
        "cart": "1.4", "checkout": "2.0"}
