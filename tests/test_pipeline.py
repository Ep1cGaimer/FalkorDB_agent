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
    FleetEntry,
    GroundingProposal,
    GroundingResult,
    ScopeConfirmation,
    h,
)
from rw.pipeline import FIXTURE_ROOT, Session, run_investigation, summarize_for_agent
from rw.verification import load_manifest


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
