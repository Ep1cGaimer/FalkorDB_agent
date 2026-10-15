"""End-to-end acceptance on the real FalkorDB server against the independent oracle.

evals/expected/dispositions.json was authored by a separate reviewer from the fixture sources
without running src/. Only this test reads it; runtime code never does.
"""
from __future__ import annotations

import json
import uuid

import pytest

from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
from rw.pipeline import Session
from rw.verification import REPO_ROOT

ORACLE = json.loads((REPO_ROOT / "evals" / "expected" / "dispositions.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in ORACLE["cases"]}


@pytest.fixture(scope="module")
def graph_name():
    name = f"rw_test_{uuid.uuid4().hex[:8]}"
    yield name
    from rw import graph as G
    try:
        G.connect().select_graph(name).delete()
    except Exception:
        pass


def _release_id(session: Session, service: str, version: str) -> str:
    from rw import graph as G
    rows, _ = G.releases_for_service(session.g, service)
    match = [r["release_id"] for r in rows if r["version"] == version]
    assert len(match) == 1, (service, version, rows)
    return match[0]


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_case_matches_independent_oracle(case_id, graph_name):
    case = CASES[case_id]
    snapshot = case["snapshot"].removeprefix("snapshot:")
    session = Session(snapshot=snapshot, graph_name=graph_name, reimport=(case_id == "A"))
    changes = [FleetEntry(service=s, release_id=_release_id(session, s, spec["version"]),
                          flags=spec.get("flags") or {})
               for s, spec in sorted(case["fleet"].items())]
    plan, errors = session.plan_from_proposal(GroundingProposal(changes=changes, citations=[], rationale="oracle"),
                                              f"oracle case {case_id}", origin="fixture", label=case_id)
    assert not errors and plan is not None
    report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="test-operator",
                                                    confirmed_at="2026-10-15T00:00:00Z"))
    v = report["verification"]

    assert v["disposition"] == case["disposition"]
    got = {(o["tuple"]["service"], o["tuple"]["record_id"]) for o in v["obligations"]}
    want = {(o["service"], o["record_id"]) for o in case["obligations"]}
    assert got == want

    results = {r["obligation_hash"]: r["result"] for r in v["receipts"]}
    got_probe = {(o["tuple"]["service"], o["tuple"]["record_id"]): results.get(o["obligation_hash"])
                 for o in v["obligations"]}
    want_probe = {(o["service"], o["record_id"]): o["expected_probe"] for o in case["obligations"]}
    assert got_probe == want_probe

    assert {g["kind"] for g in v["gaps"]} == {g["kind"] for g in case["gaps"]}
    if v["disposition"] == "BLOCKED":
        failing = {(o["tuple"]["service"], o["tuple"]["record_id"]) for o in v["obligations"]
                   if o["obligation_hash"] in v["blocking_receipts"]}
        assert failing == {k for k, r in want_probe.items() if r == "FAIL"}
        # the witness must be a real multi-hop path ending at the writer of the failing record
        ob = next(o for o in v["obligations"] if o["obligation_hash"] in v["blocking_receipts"])
        labels = [hop["label"] for hop in ob["witness_path"]]
        assert labels == ["Plan", "Deployment", "Release", "ReaderRoute", "StateStore", "Batch", "Release"]
