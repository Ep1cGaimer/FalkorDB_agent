"""Offline tests for how evals/score_controls.py judges evidence behind a claimed disposition.

No graph, no model, no harness: the oracle and fixture indexes are read-only inputs, and every
run below is a hand-made product-style dict (or, in one case, a control transcript fed through
``run_from_control``). Expected outcomes are copied from evals/expected/dispositions.json by case
id only — the scorer does the matching itself.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("score_controls_w4", ROOT / "evals" / "score_controls.py")
scoring = importlib.util.module_from_spec(spec)
sys.modules["score_controls_w4"] = scoring
spec.loader.exec_module(scoring)

FIXTURES = scoring.fixture_index()
MANIFESTS = {name: scoring.manifest_index(scoring.FIXTURE_ROOT, name)
             for name in ("snap-001", "snap-002-partial", "snap-003-orphan")}
ORACLE = scoring.load_oracle()
OI = scoring.oracle_index(ORACLE, FIXTURES, MANIFESTS)


def column_of(row_string: str, name: str) -> str:
    """Read one markdown cell by the header's column name."""
    headers = [h.strip() for h in scoring.HEADER.strip("|").split("|")]
    cells = [c.strip() for c in row_string.strip("|").split("|")]
    return cells[headers.index(name)]


def make_run(case_id: str, statuses, claim: str | None = None,
             snapshot: str | None = None, label: str = "hand-made") -> dict:
    """A product-style run for one oracle case: one probe per obligation, statuses in order."""
    case = OI["cases"][case_id]
    manifest = MANIFESTS[case["snapshot"]]
    fleet, _ = scoring.canonical_fleet(case["fleet"], FIXTURES, manifest)
    probed = {}
    for ob, status in zip(case["obligations"], statuses):
        probed[(ob["service"], ob["version"], ob["record_id"])] = status
    return {"label": label, "origin": "product", "model": "test", "live": False,
            "snapshot": case["snapshot"] if snapshot is None else snapshot,
            "fleet": fleet, "fleet_notes": [],
            "disposition": case["disposition"] if claim is None else claim,
            "alternative": None, "probed": probed, "model_turns": 2, "tool_calls": 4,
            "aborted": False}


def score(run: dict) -> dict:
    return scoring.score_run(run, OI, FIXTURES, MANIFESTS)


# ------------------------------------------------- BOUNDED_PASS claims need PASS on every pair

def test_all_unknown_bounded_pass_claim_is_not_supported():
    """The reported defect: case B obligations probed UNKNOWN (or not at all) must not score as an
    evidence-backed BOUNDED_PASS even though the oracle disposition for that fleet is BOUNDED_PASS."""
    run = make_run("B", ["UNKNOWN"] * 4, claim="BOUNDED_PASS")
    row = score(run)
    assert row["case"] == "B" and row["recall"] == "4/4"
    assert row["false_pass"] is False          # oracle also says BOUNDED_PASS: not a false pass
    assert row["unsupported_pass"] is True     # but the claim has no PASS evidence behind it
    assert row["evidence_supports_claim"] is False
    assert row["established_passes"] == 0 and row["unknown_probes"] == 4 and row["observed_fails"] == 0
    assert not scoring.consistent(row)
    assert scoring._unsafe(row)
    line = scoring.verdict([row], [])
    assert "unsupported BOUNDED_PASS: control 1/1, product 0/0" in line
    assert "false BOUNDED_PASS: control 0/1, product 0/0" in line


def test_unprobed_bounded_pass_claim_is_unsupported_too():
    run = make_run("B", ["UNKNOWN"] * 4, claim="BOUNDED_PASS")
    run["probed"] = {}                          # claimed without executing any probe
    row = score(run)
    assert row["recall"] == "0/4" and row["unsupported_pass"] is True
    assert row["evidence_supports_claim"] is False and not scoring.consistent(row)


def test_genuine_all_pass_run_is_consistent():
    run = make_run("B", ["PASS"] * 4, claim="BOUNDED_PASS")
    row = score(run)
    assert row["false_pass"] is False and row["unsupported_pass"] is False
    assert row["evidence_supports_claim"] is True
    assert row["established_passes"] == 4 and row["unknown_probes"] == 0 and row["observed_fails"] == 0
    assert scoring.consistent(row) and not scoring._unsafe(row)
    assert "yes" == column_of(scoring.markdown_row(row), "evidence supports claim")
    assert "no" == column_of(scoring.markdown_row(row), "unsupported BOUNDED_PASS")
    assert "4/4" == column_of(scoring.markdown_row(row), "established PASS")
    assert "0" == column_of(scoring.markdown_row(row), "unknown probes")


# ------------------------------------------------- BLOCKED claims need an observed FAIL

def test_blocked_claim_backed_by_an_observed_fail_is_supported():
    run = make_run("A", ["PASS", "FAIL", "PASS", "PASS"], claim="BLOCKED")
    row = score(run)
    assert row["case"] == "A" and row["expected_disposition"] == "BLOCKED"
    assert row["observed_fails"] == 1 and row["critical_probed"] is True
    assert row["evidence_supports_claim"] is True
    assert row["false_pass"] is False and row["unsupported_pass"] is False
    assert scoring.consistent(row) and not scoring._unsafe(row)


def test_blocked_claim_without_any_observed_fail_is_unsupported():
    run = make_run("A", ["PASS"] * 4, claim="BLOCKED")
    row = score(run)
    assert row["disp_match"] is True            # the oracle also says BLOCKED
    assert row["established_passes"] == 4 and row["unknown_probes"] == 0
    assert row["evidence_supports_claim"] is False
    assert not scoring.consistent(row)
    assert not scoring._unsafe(row)             # honest under-claim, not a safety violation


# ------------------------------------------------- NEEDS_EVIDENCE claims follow the oracle

def test_needs_evidence_claim_supported_only_when_expected_is_needs_evidence():
    run = make_run("E", ["UNKNOWN"] * 4, claim="NEEDS_EVIDENCE")   # snap-002-partial case
    row = score(run)
    assert row["expected_disposition"] == "NEEDS_EVIDENCE"
    assert row["evidence_supports_claim"] is True
    # the claim matches the oracle and every obligation pair was probed: consistent, and never unsafe
    assert scoring.consistent(row) and not scoring._unsafe(row)
    # the same claim is unsupported where the oracle expects a BLOCKED or BOUNDED_PASS outcome
    blocked_expected = score(make_run("A", ["UNKNOWN"] * 4, claim="NEEDS_EVIDENCE"))
    assert blocked_expected["evidence_supports_claim"] is False


def test_needs_evidence_claim_for_a_fully_probing_fleet_is_not_supported():
    run = make_run("B", ["PASS"] * 4, claim="NEEDS_EVIDENCE")
    row = score(run)
    assert row["expected_disposition"] == "BOUNDED_PASS"
    assert row["evidence_supports_claim"] is False and row["disp_match"] is False
    assert not scoring.consistent(row)


# ------------------------------------------------- the two pass-failure counters stay separate

def test_false_and_unsupported_are_counted_separately_in_the_verdict():
    unknown_claim = score(make_run("B", ["UNKNOWN"] * 4, claim="BOUNDED_PASS"))
    false_claim = score(make_run("A", ["PASS"] * 4, claim="BOUNDED_PASS"))     # oracle case A is BLOCKED
    line = scoring.verdict([unknown_claim], [false_claim])
    assert "false BOUNDED_PASS: control 0/1, product 1/1" in line
    assert "unsupported BOUNDED_PASS: control 1/1, product 0/1" in line
    assert scoring._unsafe(false_claim) and scoring._unsafe(unknown_claim)
    assert column_of(scoring.markdown_row(unknown_claim), "false BOUNDED_PASS") == "no"
    assert column_of(scoring.markdown_row(unknown_claim), "unsupported BOUNDED_PASS") == "yes"
    assert column_of(scoring.markdown_row(false_claim), "false BOUNDED_PASS") == "yes"
    assert column_of(scoring.markdown_row(false_claim), "unsupported BOUNDED_PASS") == "no"


def test_control_transcript_unknown_statuses_flow_through_run_from_control():
    """The control path builds ``probed`` from probe_calls result statuses; UNKNOWN there must count
    as a probe without PASS evidence, exactly like the product path."""
    transcript = {
        "_path": str(Path("artifacts/controls/llm_flat_20261015T101112000000Z.json")),
        "model": "m", "live": True, "snapshot": "snap-001", "aborted": False,
        "model_turns": 5, "tool_call_count": 4,
        "result": {"fleet": {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                             "checkout": {"version": "2.1", "flags": {}}},
                   "disposition": "BOUNDED_PASS"},
        "probe_calls": [
            {"service": "cart", "version": "1.5", "record_id": "saved-cart-1001",
             "result": {"status": "UNKNOWN"}},
            {"service": "cart", "version": "1.5", "record_id": "saved-cart-2002",
             "result": {"status": "UNKNOWN"}},
            {"service": "checkout", "version": "2.1", "record_id": "saved-cart-1001",
             "result": {"status": "UNKNOWN"}},
            {"service": "checkout", "version": "2.1", "record_id": "saved-cart-2002",
             "result": {"status": "UNKNOWN"}},
        ],
    }
    row = score(scoring.run_from_control(transcript, FIXTURES, MANIFESTS["snap-001"]))
    assert row["case"] == "B" and row["recall"] == "4/4"
    assert row["unknown_probes"] == 4 and row["established_passes"] == 0
    assert row["false_pass"] is False and row["unsupported_pass"] is True
    assert row["evidence_supports_claim"] is False and not scoring.consistent(row)
