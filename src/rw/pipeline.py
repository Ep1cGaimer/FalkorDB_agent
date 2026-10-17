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
    ProbeResult,
    ScopeConfirmation,
    h,
)
from .verification import (
    REPO_ROOT,
    DuplicateReleaseId,
    build_evidence,
    dispose,
    duplicate_release_evidence,
    load_manifest,
    load_release_declarations,
    materialize_plan,
    unreadable_manifest_evidence,
    validate_citations,
)

FIXTURE_ROOT = REPO_ROOT / "fixtures" / "shop"
ALL_SNAPSHOTS = ["snap-001", "snap-002-partial", "snap-003-orphan"]
ARTIFACTS = REPO_ROOT / "artifacts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _agent_citation_gate(proposal: GroundingProposal, ex_rows: list[dict[str, Any]]) -> list[str]:
    """Defense in depth for agent-origin proposals: a plan's candidate must be grounded.

    Every `changes` entry of an agent proposal must carry at least one citation whose excerpt
    row (as the graph actually returned it via ``get_excerpts``) is a *changelog* excerpt of
    exactly the release the agent chose — the row's fields, not the citation's claim, are the
    evidence. Fixture/operator fleets (origin "fixture", e.g. ``investigate.py --fleet`` and
    the controls) are authored by trusted code and never pass through this gate.
    """
    by_id = {row["excerpt_id"]: row for row in ex_rows}
    errors: list[str] = []
    for change in proposal.changes:
        if not any(row is not None and row["kind"] == "changelog" and row["release_id"] == change.release_id
                   for row in (by_id.get(c.excerpt_id) for c in proposal.citations)):
            errors.append(
                f"CITATION_MISSING: change {change.service!r} to {change.release_id!r} cites no "
                f"changelog excerpt of that release")
    return errors


def startup_check(codec_path: str, timeout_s: int = 5) -> dict[str, Any]:
    """What a typical deploy verification sees: the build loads and answers health().

    Reported beside the obligations for contrast only; it reads no retained state and can never
    discharge an obligation.
    """
    from . import probes as P
    outcome = P.run_harness(REPO_ROOT / codec_path, "health", b"", timeout_s=timeout_s)
    if outcome["timed_out"]:
        return {"codec_path": codec_path, "result": "UNKNOWN", "exit": None}
    return {"codec_path": codec_path,
            "result": "GREEN" if outcome["result"] == "PASS" else "RED",
            "exit": outcome["exit"]}


class Session:
    """Server-side binding of one graph + snapshot; nothing here comes from model output."""

    def __init__(self, snapshot: str = "snap-001", graph_name: str = GRAPH_NAME, reimport: bool = True,
                 host: str = "127.0.0.1", port: int = 6379, fixture_root: Path | None = None):
        self.db = G.connect(host, port)
        self.graph_name = graph_name
        self.fixture_root = Path(fixture_root) if fixture_root is not None else FIXTURE_ROOT
        self.snapshot = snapshot
        self.import_report = (G.reset_and_import(self.db, graph_name, self.fixture_root, ALL_SNAPSHOTS)
                             if reimport else None)
        self.g = self.db.select_graph(graph_name)
        self.manifest, self.manifest_hash = load_manifest(self.fixture_root, snapshot)
        self.snapshot_id = "snapshot:" + self.manifest["snapshot"]

    # ---- plan from a grounded proposal (or a fixture-defined fleet for controls/tests)
    def plan_from_proposal(self, proposal: GroundingProposal, request_text: str, origin: str = "agent",
                           label: str = "") -> tuple[CandidatePlan | None, list[str]]:
        # Completeness: a capped query returned cap rows and truncated=True, so the observation is
        # provably incomplete. Materializing a plan (and possibly BOUNDED_PASSing it) from a
        # truncated fleet or release inventory would certify unseen deployments; refuse instead.
        fleet_rows, fleet_log = G.current_fleet(self.g, self.snapshot_id)
        if fleet_log["truncated"]:
            return None, ["current fleet observation is truncated; cannot build a complete plan"]
        releases: dict[str, list[dict[str, Any]]] = {}
        for row in fleet_rows:
            rows, release_log = G.releases_for_service(self.g, row["service"])
            if release_log["truncated"]:
                return None, [f"release inventory for service {row['service']!r} is truncated; "
                              "cannot build a complete plan"]
            releases[row["service"]] = rows
        errors: list[str] = []
        ex_rows: list[dict[str, Any]] = []
        if proposal.citations:
            ex_rows, _ = G.get_excerpts(self.g, [c.excerpt_id for c in proposal.citations])
            errors += validate_citations(proposal.citations, ex_rows)
        if origin == "agent":
            errors += _agent_citation_gate(proposal, ex_rows)
        plan, plan_errors = materialize_plan(proposal, fleet_rows, releases, self.snapshot_id,
                                             self.manifest_hash, request_text, origin, label)
        return (plan if not errors else None), errors + plan_errors

    # ---- the graph + probe check for one confirmed plan
    def verify(self, plan: CandidatePlan, confirmation: ScopeConfirmation) -> dict[str, Any]:
        from . import probes as P  # imported lazily so pure graph tests don't need the harness

        if confirmation.plan_hash != plan.plan_hash():
            raise ValueError("scope confirmation does not match this plan")

        def unresolved(evidence) -> dict[str, Any]:
            """A verification taken with no graph work: the plan binding survives, the gaps are all we have."""
            result = dispose(evidence, [])
            return {
                "startup_checks": {},
                "plan": plan.model_dump(mode="json"),
                "plan_id": plan.plan_id(),
                "plan_hash": plan.plan_hash(),
                "scope_confirmation": confirmation.model_dump(mode="json"),
                "verification": result.model_dump(mode="json"),
                "verification_hash": result.verification_hash(),
                "queries": [],
            }

        # Re-read the manifest from disk at verification time: the plan is bound to specific manifest
        # bytes, so a snapshot that changed after the plan was built must show up as STALE_SNAPSHOT
        # instead of being certified from the copy cached at session construction. A manifest that is
        # now missing or invalid is unresolved evidence (NEEDS_EVIDENCE), never a raised request.
        try:
            manifest, manifest_hash = load_manifest(self.fixture_root, self.snapshot)
        except (OSError, ValueError) as exc:
            return unresolved(unreadable_manifest_evidence(plan, f"{type(exc).__name__}: {exc}"))
        # Re-read the release declarations independently of the graph too. Two directories claiming one
        # release id make every obligation ambiguous, so that is unresolved evidence as well; the gap
        # names the duplicated id and both directories instead of escaping as a request error.
        try:
            declarations = load_release_declarations(self.fixture_root)
        except DuplicateReleaseId as exc:
            return unresolved(duplicate_release_evidence(plan, exc))
        plan_id = G.write_plan(self.g, plan)
        route_rows, route_log = G.plan_reader_routes(self.g, plan_id)
        stores = sorted({r["store_id"] for r in route_rows if r.get("store_id")})
        inventories = {s: G.store_inventory(self.g, self.snapshot_id, s) for s in stores}
        path_rows, path_log = G.obligation_paths(self.g, plan_id, self.snapshot_id)
        evidence = build_evidence(plan, manifest, manifest_hash, route_rows, route_log, inventories,
                                  path_rows, path_log, P.probe_spec_hash, P.environment_hash(),
                                  declarations=declarations)

        payload_paths = {b["batch_id"]: b.get("payload_path") for _, rows, _ in inventories.values() for b in rows}
        written: set[str] = set()
        for ob in evidence.obligations:
            path = payload_paths.get(ob.tuple.batch_id)
            receipt = P.run_probe(ob, REPO_ROOT / path) if path else None
            if receipt is not None:
                written.add(G.write_receipt(self.g, receipt))
        # read the receipts this verification wrote back from FalkorDB by exact ProbeRun id:
        # selecting by obligation hash alone would sweep historical ProbeRun copies into the
        # cap, and once ~200 of them accumulate for one hash the fresh receipts fall past it.
        # Only ProbeRuns written by this verification count; anything absent is then no
        # applicable receipt and stays an evidence gap, never a silent pass
        rows, receipt_log = G.receipts_by_id(self.g, sorted(written))
        receipts = [ProbeReceipt.model_validate_json(r["receipt_json"]) for r in rows]
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


SUMMARY_SECTION_CAP = 20


def _capped(lines: list[str], cap: int = SUMMARY_SECTION_CAP) -> list[str]:
    """Keep a section bounded: at most `cap` lines, then a single '... and N more' line."""
    if len(lines) <= cap:
        return lines
    return lines[:cap] + [f"... and {len(lines) - cap} more"]


def summarize_for_agent(report: dict) -> str:
    """Trusted, factual summary handed to the agent when it may propose one alternative.

    Capped so a large batch cannot flood the next grounding turn: every FAIL obligation and every gap
    is listed (at most 20 lines each), then one count of passed obligations. PASS obligations are
    never listed individually; obligations without an applicable receipt result are already gaps.
    """
    v = report["verification"]
    by_hash: dict[str, list[dict]] = {}
    for r in v["receipts"]:
        by_hash.setdefault(r["obligation_hash"], []).append(r)

    fail_lines: list[str] = []
    passed = 0
    for ob in v["obligations"]:
        t = ob["tuple"]
        bound = [r for r in by_hash.get(ob["obligation_hash"], []) if r.get("tuple") == t]
        results = {r["result"] for r in bound}
        if ProbeResult.FAIL.value in results:
            r = next(r for r in bound if r["result"] == ProbeResult.FAIL.value)
            detail = f" ({r.get('error_type')}: {r.get('message')})" if r.get("error_type") else ""
            fail_lines.append(f"- FAIL reader {t['release_id']} route {t['route_id']} on record "
                              f"{t['record_id']} format {t['format_id']} written by "
                              f"{ob.get('writer_release_id')}: FAIL{detail}")
        elif ProbeResult.PASS.value in results:
            passed += 1

    lines = [f"Plan {report['plan_id']} disposition: {v['disposition']}."]
    lines += _capped(fail_lines)
    lines += _capped([f"- gap {g['kind']} on {g['subject']}: {g['detail']}" for g in v["gaps"]])
    lines.append(f"PASS: {passed} obligations")
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
        if grounding.request_text != request_text:
            # A replay can carry a proposal authored for a different request; binding it to the
            # current text would let the report answer a question nobody asked. Stop before the
            # clarification, materialization and confirmation steps.
            entry["outcome"] = "REQUEST_MISMATCH"
            entry["bound_request"] = grounding.request_text
            break
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
        if grounding.validation_errors:
            # the adapter rejected this grounding (unknown excerpt, invented artifact, ...): never
            # materialize, confirm or verify a proposal the trusted layer already refused
            entry["validation_errors"] = list(grounding.validation_errors)
            entry["outcome"] = "REJECTED_PROPOSAL"
            break
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
