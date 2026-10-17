"""End-to-end acceptance on the real FalkorDB server against the independent oracle.

evals/expected/dispositions.json was authored by a separate reviewer from the fixture sources
without running src/. Evaluation code alone reads the oracles; runtime code never does.
"""
from __future__ import annotations

from evals.obligation_identity import obligation_key, oracle_obligations

from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
from rw.pipeline import Session


def _release_id(session: Session, service: str, version: str) -> str:
    from rw import graph as G
    rows, _ = G.releases_for_service(session.g, service)
    match = [r["release_id"] for r in rows if r["version"] == version]
    assert len(match) == 1, (service, version, rows)
    return match[0]


def test_case_matches_independent_oracle(oracle_case, oracle_graph):
    root, case = oracle_case
    case_id = case["id"]
    snapshot = case["snapshot"].removeprefix("snapshot:")
    session = Session(snapshot=snapshot, graph_name=oracle_graph["name"],
                      reimport=not oracle_graph["imported"], fixture_root=root)
    oracle_graph["imported"] = True
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
    from rw import graph as G
    versions = {row["release_id"]: row["version"] for service in case["fleet"]
                for row in G.releases_for_service(session.g, service)[0]}

    def key(ob):
        return obligation_key({**ob["tuple"], "version": versions[ob["tuple"]["release_id"]]})

    got = {key(ob) for ob in v["obligations"]}
    want_probe = oracle_obligations(case)
    assert len(got) == len(v["obligations"]) == len(want_probe)
    assert got == set(want_probe)

    results = {r["obligation_hash"]: r["result"] for r in v["receipts"]}
    assert len(results) == len(v["receipts"]) == len(got)
    got_probe = {key(ob): results.get(ob["obligation_hash"]) for ob in v["obligations"]}
    assert got_probe == want_probe

    assert {g["kind"] for g in v["gaps"]} == {g["kind"] for g in case["gaps"]}
    if v["disposition"] == "BLOCKED":
        failing = {key(o) for o in v["obligations"]
                   if o["obligation_hash"] in v["blocking_receipts"]}
        assert len(failing) == len(v["blocking_receipts"])
        assert failing == {k for k, r in want_probe.items() if r == "FAIL"}
        # the witness must be a real multi-hop path ending at the writer of the failing record
        ob = next(o for o in v["obligations"] if o["obligation_hash"] in v["blocking_receipts"])
        labels = [hop["label"] for hop in ob["witness_path"]]
        assert labels == ["Plan", "Deployment", "Release", "ReaderRoute", "StateStore", "Batch", "Release"]
