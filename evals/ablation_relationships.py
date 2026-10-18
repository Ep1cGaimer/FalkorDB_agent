"""Remove the graph's relationships, keep every raw record, and rerun the same check.

The brief's test for a graph contribution: delete the relationships while the raw records stay,
and a specific useful capability must disappear. On the Astronomy Shop fixture, the all-to-3.1.0
rollback is checked once on the full graph, then once per removed relationship type (and once with
all four removed). Every node, property and payload is untouched; only edges are deleted.

No model is called: the fleet is fixed, so the only thing that changes is the graph.

    .venv\\Scripts\\python.exe evals\\ablation_relationships.py
Writes artifacts/ablation/<timestamp>.json and prints a markdown table.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURE = ROOT / "fixtures" / "astronomy-shop"
OUT = ROOT / "artifacts" / "ablation"
FLEET = [("checkout", "3.1.0"), ("accounting", "3.1.0"), ("fraud-detection", "3.1.0")]
EDGES = ["EXECUTES_ROUTE", "READS_FROM", "IN_STORE", "WRITTEN_BY"]
CONDITIONS = [("full graph", [])] + [(f"no {e}", [e]) for e in EDGES] + [("no relationships (all four)", EDGES)]


def run(removed: list[str]) -> dict:
    from rw import graph as G
    from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
    from rw.pipeline import Session

    session = Session(snapshot="snap-001", graph_name=f"rw_ablation_{uuid.uuid4().hex[:8]}", fixture_root=FIXTURE)
    try:
        nodes_before = session.g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
        deleted = 0
        for edge in removed:
            deleted += int(session.g.query(f"MATCH ()-[e:{edge}]->() DELETE e").relationships_deleted)
        nodes_after = session.g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
        assert nodes_after == nodes_before, "ablation must keep every node"
        changes = []
        for service, version in FLEET:
            rows, _ = G.releases_for_service(session.g, service)
            (release,) = [r for r in rows if r["version"] == version]
            changes.append(FleetEntry(service=service, release_id=release["release_id"], flags={}))
        plan, errors = session.plan_from_proposal(
            GroundingProposal(changes=changes, citations=[], rationale="ablation"),
            "Put checkout, accounting and fraud-detection back on 3.1.0.", origin="fixture")
        assert plan is not None and not errors, errors
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="eval",
                                         confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        report = session.verify(plan, confirmation)
        v = report["verification"]
        witnesses = sum(1 for ob in v["obligations"] if ob.get("witness_path"))
        return {"edges_deleted": deleted, "nodes": nodes_after, "disposition": v["disposition"],
                "obligations": len(v["obligations"]), "probes_run": len(v["receipts"]),
                "failures_found": sum(r["result"] == "FAIL" for r in v["receipts"]),
                "witness_paths": witnesses, "gap_kinds": sorted({g["kind"] for g in v["gaps"]}),
                "gaps": len(v["gaps"])}
    finally:
        session.g.delete()


def main() -> int:
    rows = [{"condition": name, "removed": removed, **run(removed)} for name, removed in CONDITIONS]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps({"fixture": "astronomy-shop", "snapshot": "snap-001", "fleet": FLEET,
                                "rows": rows}, indent=2), encoding="utf-8")
    print("| condition | edges deleted | nodes | disposition | checks derived | probes run | failures found | witness paths | gaps |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['condition']} | {r['edges_deleted']} | {r['nodes']} | {r['disposition']} | {r['obligations']} | "
              f"{r['probes_run']} | {r['failures_found']} | {r['witness_paths']} | {r['gaps']} ({', '.join(r['gap_kinds']) or '-'}) |")
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
