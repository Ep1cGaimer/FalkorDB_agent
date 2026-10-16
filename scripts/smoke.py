"""No-key synthetic end-to-end check: python scripts/smoke.py.

Requires the installed project dependencies and FalkorDB (default 127.0.0.1:6379, overridable with
RW_FALKORDB_HOST / RW_FALKORDB_PORT for a non-default container).
Uses real graph queries, probes, approval and simulation; only grounding is fixed.
The temporary graph and SQLite ledger are removed, including on failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from rw import config, graph  # noqa: E402
from rw.api import create_app  # noqa: E402
from rw.contracts import FleetEntry, GroundingProposal, GroundingResult  # noqa: E402
from rw.pipeline import Session  # noqa: E402

MODEL = "deterministic-smoke"
ROLLBACK = "Synthetic smoke: select cart 1.4, retaining checkout 2.1"
MITIGATION = "Synthetic smoke: select cart 1.5 with basket_v2=false, retaining checkout 2.1"
# Fixed fixture assertions; independent expectations are cross-checked only by tests.
CASES = (
    ("A", "snap-001", "1.4", {}, "BLOCKED", frozenset()),
    ("B", "snap-001", "1.5", {"basket_v2": False}, "BOUNDED_PASS", frozenset()),
    ("E", "snap-002-partial", "1.5", {"basket_v2": False}, "NEEDS_EVIDENCE",
     frozenset({"COVERAGE_INCOMPLETE"})),
    ("G", "snap-003-orphan", "1.5", {"basket_v2": False}, "NEEDS_EVIDENCE",
     frozenset({"WRITER_UNKNOWN", "FORMAT_UNKNOWN"})),
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def target() -> tuple[str, int]:
    """The FalkorDB endpoint this run uses, so a non-default container needs no code edit."""
    return os.environ.get("RW_FALKORDB_HOST", "127.0.0.1"), int(os.environ.get("RW_FALKORDB_PORT", "6379"))


def plan_url(state):
    return f"/api/investigations/{state['id']}/plans/{state['plan_hash']}"


def run_checks(client):
    def post(url, body=None, expected=200):
        response = client.post(url, json=body) if body is not None else client.post(url)
        require(response.status_code == expected,
                f"{url}: expected HTTP {expected}, got {response.status_code}: {response.text}")
        return response.json()

    def create(snapshot, request):
        # The API's mode selects its injected grounding hook; it makes no provider call.
        state = post("/api/investigations", {"request_text": request, "snapshot": snapshot})
        require(state["grounding"]["model"] == MODEL and state["grounding"]["live"] is False,
                "grounding must be labeled deterministic-smoke, live=false")
        require(not state["validation_errors"] and state["plan"], "proposal was rejected")
        return state

    def verify(state, case):
        verified = post(plan_url(state) + "/confirm-scope", {"confirmed_by": "smoke-operator"})
        v = verified["verification"]
        require(v["disposition"] == case[4], f"{case[1]}: expected {case[4]}, got {v['disposition']}")
        kinds = {g["kind"] for g in v["gaps"]}
        require(kinds == case[5], f"{case[1]}: unexpected gap set {kinds}")
        require(v["obligations"] and v["receipts"], "missing real obligations or receipts")
        if case[4] != "BLOCKED":
            require(all(r["result"] == "PASS" for r in v["receipts"]), "expected passing readers")
        print(f"PASS {case[1]} {case[4]}" + (f" ({', '.join(sorted(kinds))})" if kinds else ""))
        return v

    initial = create("snap-001", ROLLBACK)
    blocked = verify(initial, CASES[0])
    failure = next((r for r in blocked["receipts"] if r["result"] == "FAIL"), None)
    require(failure is not None, "BLOCKED must include a failing receipt")
    obligation = next(o for o in blocked["obligations"] if o["obligation_hash"] == failure["obligation_hash"])
    require(failure["tuple"] == obligation["tuple"] and obligation["witness_path"], "missing bound failure witness")
    print(f"  receipt: {failure['tuple']['record_id']} {failure['error_type']}: {failure['message']}")
    print("  witness: " + " ".join(
        f"({hop['label']} {hop['display'] or hop['id']}){hop['rel_to_next'] or ''}"
        for hop in obligation["witness_path"]))
    post(plan_url(initial) + "/approve", {"approved_by": "smoke-operator"}, expected=409)
    print("PASS blocked approval refused (HTTP 409)")

    alternative = post(f"/api/investigations/{initial['id']}/alternative")
    require(len(alternative["attempts"]) == 2, "expected exactly one alternative")
    verify(alternative, CASES[1])
    post(plan_url(alternative) + "/approve", {"approved_by": "smoke-operator"})
    first = post(plan_url(alternative) + "/simulate")
    second = post(plan_url(alternative) + "/simulate")
    require(first["applied"] is True and second["applied"] is False, "simulation not idempotent")
    require(first["idempotency_key"] == second["idempotency_key"], "simulation identity changed")
    print("PASS approved as smoke-operator; simulate applied=true, repeat applied=false")

    for case in CASES[2:]:
        verify(create(case[1], MITIGATION), case)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config.load_env()
    name = "rw_smoke_" + uuid4().hex[:8]
    print(f"RollbackWitness deterministic-smoke (SYNTHETIC FIXTURE; no agent/model calls) graph={name}")
    g = None
    status = 0
    try:
        host, port = target()
        db = graph.connect(host, port)
        g = db.select_graph(name)
        Session(graph_name=name, host=host, port=port)  # imports once; later Sessions preserve the evidence graph

        def session_factory(snapshot="snap-001"):
            return Session(snapshot=snapshot, graph_name=name, reimport=False, host=host, port=port)

        def fixed_ground(request, tools, alternative_context=None):
            version = "1.4" if request == ROLLBACK and alternative_context is None else "1.5"
            if alternative_context is not None:
                require("BLOCKED" in alternative_context and "saved-cart-2002" in alternative_context,
                        "alternative did not receive the failure evidence")
            rows, log = graph.releases_for_service(g, "cart")
            require(not log["truncated"], "release inventory truncated")
            matches = [r for r in rows if r["version"] == version]
            require(len(matches) == 1, f"cart {version} did not resolve to exactly one graph artifact")
            proposal = GroundingProposal(changes=[FleetEntry(service="cart", release_id=matches[0]["release_id"],
                flags={"basket_v2": False} if version == "1.5" else {})], citations=[],
                rationale="deterministic-smoke fixed fleet; no agent involved")
            return GroundingResult(request_text=request, result=proposal, model=MODEL, live=False), None

        with TemporaryDirectory(prefix="rw_smoke_") as directory:
            app = create_app(session_factory=session_factory, ground_function=fixed_ground,
                             db_path=Path(directory) / "ledger.sqlite")
            with TestClient(app) as client:
                run_checks(client)
    except Exception as exc:
        print(f"FAIL deterministic-smoke: {type(exc).__name__}: {exc}")
        status = 1
    finally:
        if g is not None:
            try:
                g.delete()
                print(f"PASS cleanup graph={name}")
            except Exception as exc:
                print(f"FAIL cleanup graph={name}: {type(exc).__name__}: {exc}")
                status = 1
    print("PASS deterministic-smoke complete" if status == 0 else "FAIL deterministic-smoke incomplete")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
