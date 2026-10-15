"""One investigation: ground -> confirm scope -> graph obligations -> probes -> disposition (-> one alternative).

Trusted code owns every step after the model's proposal. The model never sees graph names,
snapshot IDs, Cypher, probe execution or approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import graph as G
from .contracts import (
    GRAPH_NAME,
    MAX_PLANS_PER_SESSION,
    CandidatePlan,
    Disposition,
    GroundingClarification,
    GroundingProposal,
    GroundingResult,
    ProbeReceipt,
    ScopeConfirmation,
    VerificationResult,
    h,
)
from .verification import REPO_ROOT, build_evidence, dispose, load_manifest, materialize_plan, validate_citations

FIXTURE_ROOT = REPO_ROOT / "fixtures" / "shop"
ALL_SNAPSHOTS = ["snap-001", "snap-002-partial", "snap-003-orphan"]
ARTIFACTS = REPO_ROOT / "artifacts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def startup_check(codec_path: str, timeout_s: int = 5) -> dict[str, Any]:
    """What a typical deploy verification sees: the build loads and answers health().

    Reported beside the obligations for contrast only; it reads no retained state and can never
    discharge an obligation.
    """
    import subprocess
    import sys

    from . import probes as P
    try:
        proc = subprocess.run([sys.executable, "-I", str(P.harness_path()), str(REPO_ROOT / codec_path), "health"],
                              input=b"", capture_output=True, timeout=timeout_s)
        ok = proc.returncode == 0 and b'"PASS"' in proc.stdout[:8192]
        return {"codec_path": codec_path, "result": "GREEN" if ok else "RED", "exit": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"codec_path": codec_path, "result": "UNKNOWN", "exit": None}


class Session:
    """Server-side binding of one graph + snapshot; nothing here comes from model output."""

    def __init__(self, snapshot: str = "snap-001", graph_name: str = GRAPH_NAME, reimport: bool = True,
                 host: str = "127.0.0.1", port: int = 6379):
        self.db = G.connect(host, port)
        self.graph_name = graph_name
        self.import_report = G.reset_and_import(self.db, graph_name, FIXTURE_ROOT, ALL_SNAPSHOTS) if reimport else None
        self.g = self.db.select_graph(graph_name)
        self.manifest, self.manifest_hash = load_manifest(FIXTURE_ROOT, snapshot)
        self.snapshot_id = "snapshot:" + self.manifest["snapshot"]

    # ---- plan from a grounded proposal (or a fixture-defined fleet for controls/tests)
    def plan_from_proposal(self, proposal: GroundingProposal, request_text: str, origin: str = "agent",
                           label: str = "") -> tuple[CandidatePlan | None, list[str]]:
        fleet_rows, _ = G.current_fleet(self.g, self.snapshot_id)
        releases = {r["service"]: G.releases_for_service(self.g, r["service"])[0] for r in fleet_rows}
        errors: list[str] = []
        if proposal.citations:
            ex_rows, _ = G.get_excerpts(self.g, [c.excerpt_id for c in proposal.citations])
            errors += validate_citations(proposal.citations, ex_rows)
        plan, plan_errors = materialize_plan(proposal, fleet_rows, releases, self.snapshot_id,
                                             self.manifest_hash, request_text, origin, label)
        return (plan if not errors else None), errors + plan_errors

    # ---- the graph + probe check for one confirmed plan
    def verify(self, plan: CandidatePlan, confirmation: ScopeConfirmation) -> dict[str, Any]:
        from . import probes as P  # imported lazily so pure graph tests don't need the harness

        if confirmation.plan_hash != plan.plan_hash():
            raise ValueError("scope confirmation does not match this plan")
        plan_id = G.write_plan(self.g, plan)
        route_rows, route_log = G.plan_reader_routes(self.g, plan_id)
        stores = sorted({r["store_id"] for r in route_rows if r.get("store_id")})
        inventories = {s: G.store_inventory(self.g, self.snapshot_id, s) for s in stores}
        path_rows, path_log = G.obligation_paths(self.g, plan_id, self.snapshot_id)
        evidence = build_evidence(plan, self.manifest, self.manifest_hash, route_rows, route_log, inventories,
                                  path_rows, path_log, P.probe_spec_hash, P.environment_hash())

        payload_paths = {b["batch_id"]: b.get("payload_path") for _, rows, _ in inventories.values() for b in rows}
        written: set[str] = set()
        for ob in evidence.obligations:
            path = payload_paths.get(ob.tuple.batch_id)
            receipt = P.run_probe(ob, REPO_ROOT / path) if path else None
            if receipt is not None:
                written.add(G.write_receipt(self.g, receipt))
        # read receipts back from FalkorDB by exact obligation hash; historical receipt reuse is
        # excluded, so only ProbeRuns written by this verification count
        rows, receipt_log = G.receipts_for(self.g, [o.obligation_hash for o in evidence.obligations])
        receipts = [ProbeReceipt.model_validate_json(r["receipt_json"]) for r in rows if r["probe_id"] in written]
        result = dispose(evidence, receipts)
        startup = {}
        for r in route_rows:
            if r["service"] not in startup and r.get("codec_path"):
                startup[r["service"]] = {"release_id": r["release_id"], **startup_check(r["codec_path"])}
        return {
            "startup_checks": startup,
            "plan": plan.model_dump(mode="json"),
            "plan_id": plan_id,
            "plan_hash": plan.plan_hash(),
            "scope_confirmation": confirmation.model_dump(mode="json"),
            "verification": result.model_dump(mode="json"),
            "verification_hash": result.verification_hash(),
            "queries": evidence.queries + [receipt_log],
        }


def summarize_for_agent(report: dict) -> str:
    """Trusted, factual summary handed to the agent when it may propose one alternative."""
    v = report["verification"]
    lines = [f"Plan {report['plan_id']} disposition: {v['disposition']}."]
    by_hash = {r["obligation_hash"]: r for r in v["receipts"]}
    for ob in v["obligations"]:
        t = ob["tuple"]
        r = by_hash.get(ob["obligation_hash"])
        res = r["result"] if r else "NO_RECEIPT"
        msg = f" ({r.get('error_type')}: {r.get('message')})" if r and r["result"] == "FAIL" else ""
        lines.append(f"- reader {t['release_id']} route {t['route_id']} on record {t['record_id']} "
                     f"format {t['format_id']} written by {ob.get('writer_release_id')}: {res}{msg}")
    for g in v["gaps"]:
        lines.append(f"- gap {g['kind']} on {g['subject']}: {g['detail']}")
    return "\n".join(lines)


def with_answer(request_text: str, question: str, answer: str) -> str:
    """The operator's answer becomes part of the request the plan is bound to (and hashed)."""
    return f"{request_text}\n\nAgent asked: {question}\nOperator answered: {answer}"


def run_investigation(request_text: str, *, ground: Callable[..., tuple[GroundingResult, Path | None]],
                      confirm: Callable[[CandidatePlan], ScopeConfirmation | None],
                      answer: Callable[[GroundingClarification], str | None] | None = None,
                      session: Session | None = None, allow_alternative: bool = True) -> dict[str, Any]:
    """Full loop. `ground(request, tools, alternative_context=None)` is the live agent; `confirm` and
    `answer` are the human. One clarification round is allowed; plans stay capped at MAX_PLANS_PER_SESSION."""
    from .grounding import GroundingTools

    session = session or Session()
    tools = GroundingTools(session.g, session.snapshot_id)
    out: dict[str, Any] = {"request": request_text, "snapshot": session.snapshot_id,
                           "manifest_hash": session.manifest_hash, "started_at": _now(), "attempts": []}
    context = None
    clarified = False
    plans = 0
    while plans < MAX_PLANS_PER_SESSION:
        grounding, transcript = ground(request_text, tools, alternative_context=context)
        entry: dict[str, Any] = {"grounding": grounding.model_dump(mode="json"),
                                 "transcript": str(transcript) if transcript else None}
        out["attempts"].append(entry)
        if isinstance(grounding.result, GroundingClarification):
            entry["outcome"] = "CLARIFICATION"
            reply = answer(grounding.result) if (answer and not clarified) else None
            if not reply:
                break
            clarified = True
            entry["operator_answer"] = reply
            request_text = with_answer(request_text, grounding.result.question, reply)
            out["request_with_answer"] = request_text
            continue
        attempt = plans
        plans += 1
        plan, errors = session.plan_from_proposal(grounding.result, request_text, "agent",
                                                  label=f"candidate {attempt + 1}")
        entry["validation_errors"] = errors
        if plan is None:
            entry["outcome"] = "REJECTED_PROPOSAL"
            break
        confirmation = confirm(plan)
        if confirmation is None:
            entry["outcome"] = "SCOPE_NOT_CONFIRMED"
            entry["plan"] = plan.model_dump(mode="json")
            break
        report = session.verify(plan, confirmation)
        entry["report"] = report
        entry["outcome"] = report["verification"]["disposition"]
        if entry["outcome"] == Disposition.BOUNDED_PASS.value or not allow_alternative:
            break
        context = summarize_for_agent(report)
    out["finished_at"] = _now()
    return out


def save_report(result: dict) -> Path:
    path = ARTIFACTS / "reports" / f"{h(result)[7:23]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return path
