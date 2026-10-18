"""One investigation: ground -> confirm scope -> graph obligations -> probes -> disposition (-> one alternative).

Trusted code owns every step after the model's proposal. The model never sees graph names,
snapshot IDs, Cypher, probe execution or approval.
"""
from __future__ import annotations

import json
import os
import re
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
    fleet_hash,
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

DEFAULT_FIXTURE = "shop"
NO_CHANGE = "NO_CHANGE"
NO_CHANGE_RETRY = ("\nYour previous proposal kept every service exactly as it runs now, which undoes nothing the "
                   "operator asked to undo. Call trace_data_origin on failing records to see where their data came "
                   "from, then propose a change (another existing release or a declared flag) that undoes the "
                   "requested behavior without running a failing reader. If that change touches a service the operator "
                   "told you not to change, call ask_clarification naming the change and its evidence.")


def fixture_root_from_env() -> Path:
    """Fixture selected by RW_FIXTURE (a directory name under fixtures/); `shop` when unset.

    Every fixture uses the same snapshot names (ALL_SNAPSHOTS), so the API, UI and scripts need no
    per-fixture configuration. An unknown name fails at import instead of silently using `shop`.
    """
    name = os.environ.get("RW_FIXTURE", "").strip() or DEFAULT_FIXTURE
    root = REPO_ROOT / "fixtures" / name
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name) or not (root / "releases").is_dir():
        raise ValueError(f"RW_FIXTURE={name!r} is not a fixture directory under fixtures/")
    return root


FIXTURE_ROOT = fixture_root_from_env()
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

    def __init__(self, snapshot: str = "snap-001", graph_name: str | None = None, reimport: bool = True,
                 host: str = "127.0.0.1", port: int = 6379, fixture_root: Path | None = None):
        self.db = G.connect(host, port)
        self.fixture_root = Path(fixture_root) if fixture_root is not None else FIXTURE_ROOT
        if graph_name is None:  # one graph per fixture, so a browser shows which data it holds
            graph_name = GRAPH_NAME if self.fixture_root.name == DEFAULT_FIXTURE else f"rw_fixture_{self.fixture_root.name}"
        self.graph_name = graph_name
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
        if (origin == "agent" and plan is not None and plan.baseline_fleet_hash
                and fleet_hash(plan.fleet) == plan.baseline_fleet_hash):
            # same releases and flags as what runs now: nothing would change, so nothing is undone
            errors.append(f"{NO_CHANGE}: the proposed fleet is exactly the fleet running now; it undoes nothing")
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
    groups: dict[tuple, list[str]] = {}  # every failing reader/route/store/format/writer, so none is cut by the cap
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
            hops = {hop["label"]: hop for hop in ob.get("witness_path") or [] if hop["label"] != "Release"}
            reader = next((hop.get("display") for hop in ob.get("witness_path") or []
                           if hop["label"] == "Release" and hop["id"] == t["release_id"]), t["release_id"])
            route = (hops.get("ReaderRoute") or {}).get("display") or t["route_id"]
            writer_id = ob.get("writer_release_id")
            writer_version = next((hop.get("display", "").removeprefix("writer ").strip()
                                   for hop in ob.get("witness_path") or []
                                   if hop["label"] == "Release" and hop["id"] == writer_id), "")
            writer = (f"{writer_id.split(':')[1]} {writer_version} ({writer_id})".replace("  ", " ")
                      if writer_id and writer_id.count(":") >= 2 else writer_id)
            groups.setdefault((reader, route, t["store_id"], t["format_id"], writer), []).append(t["record_id"])
        elif ProbeResult.PASS.value in results:
            passed += 1
    group_lines = [
        f"* reader {reader} ({route}) fails on {len(ids)} record(s) in {store}, format {fmt}, written by "
        f"{writer or 'UNKNOWN writer'}; e.g. {', '.join(sorted(ids)[:3])}"
        for (reader, route, store, fmt, writer), ids in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0])))]

    lines = [f"Plan {report['plan_id']} disposition: {v['disposition']}."]
    fleet = (report.get("plan") or {}).get("fleet") or []
    if fleet:
        # name the exact fleet that failed, so a proposed alternative can be told apart from it
        lines.append("Blocked fleet (an alternative must differ from it): " + "; ".join(
            f"{e['service']} {e['release_id']}" + (f" flags {e['flags']}" if e.get("flags") else "")
            for e in sorted(fleet, key=lambda e: e["service"])))
    if group_lines:
        lines.append("Every failing reader, grouped (each listed release fails on these retained records "
                     "and must not run in the alternative):")
        lines += _capped(group_lines)
    lines += _capped(fail_lines)
    lines += _capped([f"- gap {g['kind']} on {g['subject']}: {g['detail']}" for g in v["gaps"]])
    if fail_lines:
        lines.append("trace_data_origin can follow the failing records' lineage to their origin writer.")
    lines.append(f"PASS: {passed} obligations")
    return "\n".join(lines)


def failure_lineage(session: "Session", verification: dict) -> list[str]:
    """Facts from FalkorDB lineage (DERIVED_FROM) about where the failing records' data came from.

    Trusted code runs the fixed record_origins query on the failing record ids, so the origin of the
    data reaches the agent even when it does not call trace_data_origin itself.
    """
    failing = {}  # (service, record_id) pairs that failed; the lineage query is per record
    for r in verification["receipts"]:
        if r["result"] == ProbeResult.FAIL.value:
            failing.setdefault(r["tuple"]["record_id"], set()).add(r["tuple"]["service"])
    if not failing:
        return []
    rows, log = G.record_origins(session.g, session.snapshot_id, sorted(failing))
    if not rows:
        return []
    label = lambda row: f"{row['origin_service']} {row['origin_version']}" if row["origin_service"] else "an UNKNOWN writer"  # noqa: E731
    derived: dict[tuple, int] = {}
    origins: dict[str, int] = {}
    for row in rows:
        reads = len(failing.get(row["record_id"], ()))
        origins[label(row)] = origins.get(label(row), 0) + reads
        if row["hops"]:
            key = (row["store_id"], row["origin_store_id"], label(row))
            derived[key] = derived.get(key, 0) + 1
    lines = [f"Lineage (DERIVED_FROM): {n} failing record(s) in {store} were derived from records in {origin_store} "
             f"first written by {writer}." for (store, origin_store, writer), n in sorted(derived.items())]
    lines.append("Origin of the data behind every failing read: " + "; ".join(
        f"{writer} ({n} read(s))" for writer, n in sorted(origins.items(), key=lambda kv: -kv[1])) + "."
                 + (" (lineage query truncated)" if log["truncated"] else ""))
    lines.append("Retained records stay in their stores after any change: a release listed above as failing "
                 "fails on them whatever the flags, so the alternative must not run it.")
    return lines


def alternative_context(session: "Session", report: dict) -> str:
    """The trusted summary plus, for every service whose reader failed, the release it runs today.

    Today's release is the one already reading the retained records, so naming it gives the agent a
    concrete existing artifact to keep instead of repeating the blocked fleet.
    """
    text = summarize_for_agent(report)
    v = report["verification"]
    lineage = failure_lineage(session, v)
    if lineage:
        lines = text.splitlines()
        lines[-1:-1] = lineage
        text = "\n".join(lines)
    failed = {r["tuple"]["release_id"] for r in v["receipts"] if r["result"] == ProbeResult.FAIL.value}
    services = sorted({ob["tuple"]["service"] for ob in v["obligations"] if ob["tuple"]["release_id"] in failed})
    if not services:
        return text
    rows, _ = G.current_fleet(session.g, session.snapshot_id)
    current = {row["service"]: row for row in rows}
    kept = [f"{s} {current[s]['release_id']} (version {current[s]['version']})" for s in services if s in current]
    if kept:
        lines = text.splitlines()
        lines.insert(-1, "Services whose reader failed, and the release each runs today (it already reads these "
                         "records): " + "; ".join(kept))
        text = "\n".join(lines)
    return text


ABLATABLE_EDGES = ("EXECUTES_ROUTE", "READS_FROM", "IN_STORE", "WRITTEN_BY", "DERIVED_FROM")


def ablate(session: "Session", fleet: list, removed: list[str]) -> dict[str, Any]:
    """Re-run one fleet on a disposable copy of the graph with some relationship types deleted.

    Every node, property and payload stays; only the named edge types are removed. The session's own
    graph is never touched: the copy is a fresh import under a unique name, deleted afterwards.
    """
    import uuid
    from .contracts import FleetEntry

    if not removed or any(edge not in ABLATABLE_EDGES for edge in removed):
        raise ValueError(f"removed must name edge types from {list(ABLATABLE_EDGES)}")
    copy = Session(snapshot=session.snapshot, graph_name=f"rw_ablation_{uuid.uuid4().hex[:8]}",
                   fixture_root=session.fixture_root)
    try:
        deleted = 0
        for edge in removed:  # names come from the fixed allowlist above, never from the request
            deleted += int(copy.g.query(f"MATCH ()-[e:{edge}]->() DELETE e").relationships_deleted)
        entries = [FleetEntry(service=e["service"], release_id=e["release_id"], flags=e.get("flags") or {})
                   for e in fleet]
        plan, errors = copy.plan_from_proposal(
            GroundingProposal(changes=entries, citations=[], rationale="relationship-removal check"),
            "relationship-removal check", origin="fixture")
        if plan is None:
            return {"removed": removed, "edges_deleted": deleted, "disposition": None, "errors": errors}
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="relationship-removal check",
                                         confirmed_at=_now())
        v = copy.verify(plan, confirmation)["verification"]
        failing = sorted({r["tuple"]["record_id"] for r in v["receipts"] if r["result"] == ProbeResult.FAIL.value})
        origin_rows, _ = G.record_origins(copy.g, copy.snapshot_id, failing) if failing else ([], {})
        return {"removed": removed, "edges_deleted": deleted, "disposition": v["disposition"],
                "obligations": len(v["obligations"]), "probes_run": len(v["receipts"]),
                "failures_found": sum(r["result"] == ProbeResult.FAIL.value for r in v["receipts"]),
                "witness_paths": sum(1 for ob in v["obligations"] if ob.get("witness_path")),
                "gap_kinds": sorted({g["kind"] for g in v["gaps"]}), "gaps": len(v["gaps"]),
                "origins_found": sum(1 for row in origin_rows if row["hops"])}
    finally:
        copy.g.delete()


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
    no_change_retried = False
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
        if (plan is None and context and not no_change_retried
                and any(e.startswith(NO_CHANGE) for e in errors)):
            # one more chance for an alternative that would change nothing (does not count as a plan)
            no_change_retried = True
            plans -= 1
            entry["outcome"] = "NO_CHANGE_RETRY"
            context += NO_CHANGE_RETRY
            continue
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
        context = alternative_context(session, report)
    out["finished_at"] = _now()
    return out


def save_report(result: dict) -> Path:
    path = ARTIFACTS / "reports" / f"{h(result)[7:23]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return path
