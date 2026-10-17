"""Investigation-loop and summary behaviour of the trusted pipeline (F5, F7, capped summary).

The loop tests use a real FalkorDB server on a uniquely named temporary graph (imported from a
throwaway copy of the fixture) and delete it; the summary test is pure data.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from rw import graph as G
from rw.contracts import (
    CandidatePlan,
    Citation,
    FleetEntry,
    GroundingClarification,
    GroundingProposal,
    GroundingResult,
    ProbeReceipt,
    ScopeConfirmation,
    h,
)
from rw.pipeline import FIXTURE_ROOT, Session, run_investigation, summarize_for_agent
from rw.verification import load_manifest, load_release_declarations


# --------------------------------------------------------------------------- F7: rejected grounding

class _StubSession:
    """No graph at all: a rejected grounding must never reach planning, confirmation or verification."""

    def __init__(self, plan=None):
        self.g = None
        self.snapshot_id = "snapshot:snap-001"
        self.manifest_hash = h("stub-manifest")
        self.plan = plan

    def plan_from_proposal(self, *args, **kwargs):
        assert self.plan is not None, "plan_from_proposal ran for a grounding the adapter rejected"
        return self.plan, []

    def verify(self, *args, **kwargs):
        raise AssertionError("verify ran for a grounding the adapter rejected")


def test_grounding_validation_errors_reject_before_confirmation():
    proposal = GroundingProposal(
        changes=[FleetEntry(service="cart", release_id="release:cart:1.4")],
        citations=[], rationale="rollback proposal the adapter refused")
    result = GroundingResult(request_text="roll cart back", result=proposal, model="fake", live=True,
                             validation_errors=["CITATION_UNKNOWN_EXCERPT: invented citation dropped"])
    confirmations: list = []

    def ground(request_text, tools, alternative_context=None):
        return result, None

    def confirm(plan):
        confirmations.append(plan)
        return ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="oncall:alice",
                                 confirmed_at="2026-10-16T00:00:00Z")

    out = run_investigation("roll cart back", ground=ground, confirm=confirm, session=_StubSession())

    attempt = out["attempts"][0]
    assert attempt["outcome"] == "REJECTED_PROPOSAL"
    assert attempt["validation_errors"] == ["CITATION_UNKNOWN_EXCERPT: invented citation dropped"]
    assert confirmations == []
    assert "plan" not in attempt and "report" not in attempt


def test_grounding_without_validation_errors_still_reaches_confirmation():
    """Control for the gate above: a clean grounding does reach confirm."""
    plan = CandidatePlan(scope_id="fixture-shop", snapshot_id="snapshot:snap-001",
                         snapshot_manifest_hash=h("stub-manifest"),
                         request_text_hash=h("roll cart back"),
                         fleet=[FleetEntry(service="cart", release_id="release:cart:1.4")],
                         source_hashes=[], origin="fixture", label="candidate 1")
    seen: list = []

    def ground(request_text, tools, alternative_context=None):
        proposal = GroundingProposal(changes=[FleetEntry(service="cart", release_id="release:cart:1.4")],
                                     citations=[], rationale="clean")
        return GroundingResult(request_text=request_text, result=proposal, model="fake", live=True), None

    def confirm(candidate):
        seen.append(candidate)
        return None  # operator declines the scope

    out = run_investigation("roll cart back", ground=ground, confirm=confirm,
                            session=_StubSession(plan=plan))

    assert out["attempts"][0]["outcome"] == "SCOPE_NOT_CONFIRMED"
    assert seen and seen[0].plan_id() == plan.plan_id()


# --------------------------------------------------------------------------- I4: replay request binding

def _replay_transcript(path: Path, request_text: str) -> Path:
    """A gemini-shaped transcript that reads the fleet, reads the release's excerpts, then proposes a
    cart-1.4 fleet cited from that release's changelog. Valid on purpose at the adapter's
    citation gate and the pipeline's alike. Without the request-binding guard the
    loop would materialize and confirm this proposal under whatever request text the caller
    passed.
    """
    path.write_text(json.dumps({
        "request_text": request_text, "provider": "gemini", "alternative_context": None,
        "events": [
            {"type": "model", "response": {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "current_fleet", "args": {}}}]}}]}},
            {"type": "tool", "name": "current_fleet", "log": "read-only",
             "rows": [{"release_id": "release:cart:1.4", "service": "cart", "declared_flags": []}]},
            {"type": "model", "response": {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "release_history", "args": {"service": "cart"}}}]}}]}},
            {"type": "tool", "name": "release_history", "log": "read-only",
             "rows": [{"release_id": "release:cart:1.4", "service": "cart", "version": "1.4",
                       "excerpts": [{"excerpt_id": "excerpt:cart-1.4:changelog-saved-carts",
                                     "kind": "changelog",
                                     "content_hash": "sha256:synthetic-cart-1-4-changelog",
                                     "text": "- Saved carts are persisted to cart-cache "
                                             "as cart/v1."}]}]},
            {"type": "model", "response": {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "propose_fleet", "args": {
                    "changes": [{"service": "cart", "release_id": "release:cart:1.4"}],
                    "citations": [{"excerpt_id": "excerpt:cart-1.4:changelog-saved-carts",
                                   "quote": "- Saved carts are persisted to cart-cache "
                                            "as cart/v1."}],
                    "request_references": [request_text],
                    "rationale": "replayed proposal"}}}]}}]}},
        ]}, indent=2), encoding="utf-8")
    return path


def test_replayed_transcript_of_a_different_request_is_refused(tmp_path):
    """A replay bound to another request must not be confirmed for this one."""
    from rw import grounding

    bound = _replay_transcript(tmp_path / "other.json", "a different request")
    plan = CandidatePlan(scope_id="fixture-shop", snapshot_id="snapshot:snap-001",
                         snapshot_manifest_hash=h("stub-manifest"), request_text_hash=h("roll cart back"),
                         fleet=[FleetEntry(service="cart", release_id="release:cart:1.4")],
                         source_hashes=[], origin="fixture", label="candidate 1")
    seen: list = []
    out = run_investigation(
        "roll cart back",
        ground=lambda request, tools, alternative_context=None: (grounding.replay(bound), bound),
        confirm=lambda candidate: (seen.append(candidate), None)[1],
        session=_StubSession(plan=plan))

    attempt = out["attempts"][0]
    assert attempt["outcome"] == "REQUEST_MISMATCH"
    assert attempt["grounding"]["request_text"] == "a different request"
    assert seen == [] and "plan" not in attempt and "report" not in attempt


def test_grounding_bound_to_another_request_stops_before_clarification():
    """The same guard stops a mismatched clarification before the operator is asked."""
    asked: list = []

    def ground(request_text, tools, alternative_context=None):
        return GroundingResult(request_text="not the request",
                               result=GroundingClarification(question="which build?", unresolved=[]),
                               model="fake", live=True), None

    out = run_investigation("roll cart back", ground=ground, confirm=lambda plan: None,
                            answer=lambda clar: asked.append(clar) or "cart 1.4",
                            session=_StubSession())

    assert out["attempts"][0]["outcome"] == "REQUEST_MISMATCH"
    assert asked == [] and "request_with_answer" not in out


# --------------------------------------------------------------------------- F5: manifest re-read

@pytest.fixture
def copied_fixture(tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def test_verify_reads_the_manifest_from_disk_not_from_the_session_cache(copied_fixture):
    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=copied_fixture)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="keep 1.5 with the basket rollout off")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        assert plan.snapshot_manifest_hash == session.manifest_hash

        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="oncall:alice",
                                         confirmed_at="2026-10-16T00:00:00Z")
        before = session.verify(plan, confirmation)
        assert before["verification"]["disposition"] == "BOUNDED_PASS"
        assert not before["verification"]["gaps"]

        # the snapshot on disk changes after the plan was built: verification must notice
        manifest_path = copied_fixture / "snapshots" / "snap-001" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["stores"][0]["coverage"] = "PARTIAL"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        after = session.verify(plan, confirmation)
        v = after["verification"]
        kinds = {g["kind"] for g in v["gaps"]}
        assert "STALE_SNAPSHOT" in kinds and "COVERAGE_INCOMPLETE" in kinds
        assert v["disposition"] == "NEEDS_EVIDENCE"
        _, fresh_hash = load_manifest(copied_fixture, "snap-001")
        assert fresh_hash != plan.snapshot_manifest_hash
        assert v["snapshot_manifest_hash"] == fresh_hash
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


# --------------------------------------------------------------------------- fresh receipts vs history

def test_verify_survives_a_full_history_of_prior_receipts(copied_fixture):
    """~205 historical ProbeRun copies of the same obligation hashes must not push this
    verification's fresh receipts past the read-back cap: an unchanged plan that passed before
    the backlog was written must still be BOUNDED_PASS.

    The old read path (receipts_for over obligation hashes, cap 200, then a filter to the fresh
    ids) hid the fresh receipts once a single hash's history alone filled the cap; this test
    fills exactly that scenario.
    """
    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=copied_fixture)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="keep 1.5 with the basket rollout off")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="oncall:alice",
                                         confirmed_at="2026-10-16T00:00:00Z")
        first = session.verify(plan, confirmation)
        assert first["verification"]["disposition"] == "BOUNDED_PASS"

        hashes = [o["obligation_hash"] for o in first["verification"]["obligations"]]
        stored, _ = G.receipts_for(session.g, hashes)
        assert len(stored) == len(hashes)

        # Copy every receipt written above 205 times with distinct executed_at: same obligation
        # hashes, distinct ProbeRun ids — the kind of historical receipt backlog a busy graph
        # accumulates.
        for i in range(205):
            for row in stored:
                old_receipt = ProbeReceipt.model_validate_json(row["receipt_json"])
                G.write_receipt(session.g, old_receipt.model_copy(
                    update={"executed_at": f"2020-01-01T00:{i // 60:02d}:{i % 60:02d}Z"}))

        again = session.verify(plan, confirmation)
        v = again["verification"]
        assert v["disposition"] == "BOUNDED_PASS"
        assert not [g for g in v["gaps"] if g["kind"] == "RECEIPT_MISSING"], v["gaps"]
        assert len(v["receipts"]) == len(hashes)
        receipt_logs = [q for q in again["queries"] if q["name"] == "receipts_by_id"]
        assert len(receipt_logs) == 1
        assert receipt_logs[0]["truncated"] is False and receipt_logs[0]["rows"] == len(hashes)
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


# --------------------------------------------------------------------------- agent citation gate

def _changelog_citation(session, service, version):
    """A real changelog excerpt of one fixture release, built from the graph's rows."""
    rows, _ = G.release_history(session.g, session.snapshot_id, service)
    row = next(r for r in rows if r["version"] == version)
    excerpt = next(e for e in row["excerpts"] if e["kind"] == "changelog")
    citation = Citation(excerpt_id=excerpt["excerpt_id"], content_hash=excerpt["content_hash"],
                        quote=excerpt["text"])
    return row["release_id"], citation


def _passing_cart_session():
    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name)
    rows, _ = G.releases_for_service(session.g, "cart")
    release = next(r for r in rows if r["version"] == "1.5")
    return session, release


def _delete_graph(session):
    try:
        session.g.delete()
    except Exception:
        pass


def test_uncited_agent_proposal_makes_no_plan():
    """Zero-citation agent proposals must not become verifiable plans (deep defense)."""
    session, release = _passing_cart_session()
    try:
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="the agent just says so")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="agent")
        assert plan is None
        assert any(e.startswith("CITATION_MISSING") for e in errors), errors

        # Fixture/operator fleets are authored by trusted code, not an agent: they still plan
        # without citations.
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        assert plan.origin == "fixture"
    finally:
        _delete_graph(session)


def test_agent_proposal_citing_the_wrong_or_wrongly_typed_source_makes_no_plan():
    """A changelog of another release, or a code excerpt of the right one, grounds nothing."""
    session, target = _passing_cart_session()
    try:
        other_release, other_citation = _changelog_citation(session, "cart", "1.4")
        assert other_release != target["release_id"]
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=target["release_id"], flags={"basket_v2": False})],
            citations=[other_citation], rationale="cites the wrong release")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="agent")
        assert plan is None  # the citation itself is valid; only the binding is missing
        assert any(e.startswith("CITATION_MISSING: change 'cart'") for e in errors), errors

        history, _ = G.release_history(session.g, session.snapshot_id, "cart")
        row = next(r for r in history if r["release_id"] == target["release_id"])
        code_excerpt = next(e for e in row["excerpts"] if e["kind"] == "code")
        proposal = proposal.model_copy(update={"citations": [Citation(
            excerpt_id=code_excerpt["excerpt_id"], content_hash=code_excerpt["content_hash"],
            quote=code_excerpt["text"])]})
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="agent")
        assert plan is None
        assert any(e.startswith("CITATION_MISSING") for e in errors), errors
    finally:
        _delete_graph(session)


def test_properly_cited_agent_proposal_makes_a_plan():
    """A changelog excerpt of exactly the chosen release completes the proposal."""
    session, release = _passing_cart_session()
    try:
        release_id, citation = _changelog_citation(session, "cart", "1.5")
        assert release_id == release["release_id"]
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release_id, flags={"basket_v2": False})],
            citations=[citation], rationale="grounded in the 1.5 changelog")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="agent")
        assert not errors and plan is not None
        assert plan.origin == "agent"
        assert plan.source_hashes == sorted({citation.content_hash})
    finally:
        _delete_graph(session)


# --------------------------------------------------------------------------- I8/minors: verify edge cases

def test_verify_maps_an_unreadable_manifest_to_a_stale_snapshot_gap(copied_fixture):
    """A manifest that breaks after planning is unresolved evidence, not a raised request."""
    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=copied_fixture)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="keep 1.5 with the basket rollout off")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="oncall:alice",
                                         confirmed_at="2026-10-16T00:00:00Z")
        assert session.verify(plan, confirmation)["verification"]["disposition"] == "BOUNDED_PASS"

        (copied_fixture / "snapshots" / "snap-001" / "manifest.json").write_text("{ not json", encoding="utf-8")
        report = session.verify(plan, confirmation)
        v = report["verification"]
        assert v["disposition"] == "NEEDS_EVIDENCE"
        assert [g["kind"] for g in v["gaps"]] == ["STALE_SNAPSHOT"]
        assert v["obligations"] == [] and v["receipts"] == []
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


def test_verify_reports_a_duplicated_release_id_as_an_invalid_fleet_gap(tmp_path):
    """#7a: two fixture dirs claiming one release identity is unresolved evidence, never a 500."""
    root = tmp_path / "shop"
    shutil.copytree(FIXTURE_ROOT, root)
    shutil.copytree(root / "releases" / "cart-1.4", root / "releases" / "cart-1.4-duplicate")
    duplicate_id = next(rid for rid, decl in load_release_declarations(FIXTURE_ROOT).items()
                        if (decl["service"], decl["version"]) == ("cart", "1.4"))

    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=root)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="keep 1.5 with the basket rollout off")
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None

        report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="oncall:alice",
                                                        confirmed_at="2026-10-16T00:00:00Z"))
        v = report["verification"]
        assert v["disposition"] == "NEEDS_EVIDENCE"
        gaps = [g for g in v["gaps"] if g["kind"] == "INVALID_FLEET"]
        assert len(gaps) == 1, v["gaps"]
        assert gaps[0]["subject"] == duplicate_id
        assert (root / "releases" / "cart-1.4").as_posix() in gaps[0]["detail"]
        assert (root / "releases" / "cart-1.4-duplicate").as_posix() in gaps[0]["detail"]
        assert v["obligations"] == [] and v["receipts"] == []
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


def test_startup_check_branches_on_the_timed_out_flag(monkeypatch):
    """startup_check must use run_harness's explicit flag, not the message string."""
    from rw import probes
    from rw.pipeline import startup_check

    monkeypatch.setattr(probes, "run_harness", lambda *a, **k: {
        "timed_out": True, "result": "FAIL", "exit": 10,
        "message": "harness error or invalid stdout"})
    assert startup_check("fixtures/shop/releases/cart-1.4/codec.py") == {
        "codec_path": "fixtures/shop/releases/cart-1.4/codec.py", "result": "UNKNOWN", "exit": None}

    monkeypatch.setattr(probes, "run_harness", lambda *a, **k: {
        "timed_out": False, "result": "PASS", "exit": 0, "message": None})
    assert startup_check("fixtures/shop/releases/cart-1.4/codec.py") == {
        "codec_path": "fixtures/shop/releases/cart-1.4/codec.py", "result": "GREEN", "exit": 0}


# --------------------------------------------------------------------------- capped summary

def _report(results: list[str], gaps: int = 0) -> dict:
    """A synthetic report: one obligation per result ('PASS', 'FAIL', 'NO_RECEIPT')."""
    obligations, receipts = [], []
    for i, result in enumerate(results):
        tuple_ = {
            "scope_id": "fixture-shop", "plan_hash": "plan:deadbeefdeadbeef",
            "snapshot_id": "snapshot:snap-001", "snapshot_manifest_hash": "sha256:manifest",
            "service": "cart", "deployment_id": "deployment:snap-001:cart",
            "release_id": "release:cart:1.5", "codec_hash": "sha256:codec", "route_id": "route:read",
            "route_contract_hash": "sha256:contract", "store_id": "store:cart-cache",
            "batch_id": f"batch:cart-cache:snap-001:rec-{i}:{i:04d}", "record_id": f"rec-{i}",
            "payload_hash": f"sha256:payload-{i}", "format_id": "cart/v1",
            "semantic_scope": "BYTE_SHAPE_ONLY", "probe_spec_hash": "sha256:spec",
            "environment_hash": "sha256:env",
        }
        ob_hash = h(tuple_)
        obligations.append({"obligation_hash": ob_hash, "tuple": tuple_,
                            "writer_release_id": "release:cart:1.4"})
        if result != "NO_RECEIPT":
            receipts.append({"obligation_hash": ob_hash, "tuple": tuple_, "result": result,
                             "error_type": "ValueError" if result == "FAIL" else None,
                             "message": "unsupported saved-cart format 'cart/v2'" if result == "FAIL" else None})
    return {"plan_id": "plan:deadbeefdeadbeef",
            "verification": {"disposition": "BLOCKED" if "FAIL" in results else "BOUNDED_PASS",
                             "obligations": obligations, "receipts": receipts,
                             "gaps": [{"kind": "RECEIPT_MISSING", "subject": f"gap-{i}",
                                       "detail": "no probe receipt for this obligation"} for i in range(gaps)]}}


def test_summary_lists_every_fail_and_caps_the_section():
    text = summarize_for_agent(_report(["FAIL"] * 50))
    lines = text.splitlines()
    fail_lines = [line for line in lines if line.startswith("- FAIL")]
    more = [line for line in lines if line.startswith("... and ")]
    assert len(fail_lines) == 20
    assert more == ["... and 30 more"]
    assert len(fail_lines) + len(more) <= 22  # the cap the brief asks for, including the rollup line
    assert lines[-1] == "PASS: 0 obligations"


def test_summary_never_lists_a_passing_obligation_and_counts_them():
    text = summarize_for_agent(_report(["PASS", "FAIL", "NO_RECEIPT", "PASS"]))
    lines = text.splitlines()
    assert [line for line in lines if line.startswith("- FAIL")] == [
        "- FAIL reader release:cart:1.5 route route:read on record rec-1 format cart/v1 "
        "written by release:cart:1.4: FAIL (ValueError: unsupported saved-cart format 'cart/v2')"]
    assert "rec-0" not in text and "rec-3" not in text  # PASS obligations stay unlisted
    assert lines[-1] == "PASS: 2 obligations"


def test_summary_caps_the_gap_section_too():
    text = summarize_for_agent(_report(["PASS"], gaps=25))
    gap_lines = [line for line in text.splitlines() if line.startswith("- gap")]
    more = [line for line in text.splitlines() if line.startswith("... and ")]
    assert len(gap_lines) == 20
    assert more == ["... and 5 more"]
    assert text.splitlines()[-1] == "PASS: 1 obligations"


# --------------------------------------------------------------------------- completeness: truncated observations

def test_truncated_current_fleet_or_release_inventory_makes_no_plan(copied_fixture):
    """A fleet observation or a release inventory past the fixed query cap is incomplete evidence.

    With cap+1 deployments the current_fleet query returns `cap` rows and truncated=True; trusting
    those rows anyway materialized a plan from an unseen fleet, and verification could then
    BOUNDED_PASS while whole deployments were missing from the observation. A truncated
    observation must refuse planning with a clear error instead (completeness: caps/truncation
    are incomplete, never passed).
    """
    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=copied_fixture)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={"basket_v2": False})],
            citations=[], rationale="keep 1.5 with the basket rollout off")
        # control: the complete observation plans normally
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None

        # push the current fleet past the cap: 2 real deployments + 199 extra = cap + 1
        session.g.query(
            "UNWIND $rows AS row "
            "MATCH (s:Snapshot {id: $snapshot_id}) "
            "CREATE (d:Deployment {id: row.id, scope_id: $scope_id, service: row.service, "
            "snapshot_id: $snapshot_id}) CREATE (s)-[:HAS_DEPLOYMENT]->(d)",
            params={"rows": [{"id": f"deployment:snap-001:extra-{i}", "service": f"extra-{i}"}
                             for i in range(199)],
                    "snapshot_id": session.snapshot_id, "scope_id": "fixture-shop"})

        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert plan is None
        assert "current fleet observation is truncated; cannot build a complete plan" in errors, errors

        # the same refusal closes the release inventory of any fleet service:
        # 2 real cart builds + 199 unlisted ones = cap + 1 rows for releases_for_service("cart")
        session.g.query("MATCH (d:Deployment) WHERE d.service STARTS WITH $prefix DETACH DELETE d",
                        params={"prefix": "extra-"})
        session.g.query(
            "UNWIND $rows AS row "
            "CREATE (r:Release {id: row.id, scope_id: $scope_id, service: 'cart', "
            "version: row.version, codec_hash: 'sha256:unlisted'})",
            params={"rows": [{"id": f"release:cart:unlisted-{i}", "version": f"9.{i}"}
                             for i in range(199)],
                    "scope_id": "fixture-shop"})
        plan, errors = session.plan_from_proposal(proposal, "undo the basket rollout", origin="fixture")
        assert plan is None
        assert ("release inventory for service 'cart' is truncated; cannot build a complete plan"
                in errors), errors
    finally:
        try:
            session.g.delete()
        except Exception:
            pass
