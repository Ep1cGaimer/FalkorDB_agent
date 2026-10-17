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
        # the scorer keys evidence by the full (service, version, route_id, store_id, record_id)
        probed[tuple(ob[f] for f in ("service", "version", "route_id", "store_id", "record_id"))] = status
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


# ------------------------------------------------- product receipts must bind to the obligation

CASE_B_PAIRS = [
    ("cart", "1.5", "saved-cart-1001"),
    ("cart", "1.5", "saved-cart-2002"),
    ("checkout", "2.1", "saved-cart-1001"),
    ("checkout", "2.1", "saved-cart-2002"),
]


def release_id_of(service: str, version: str) -> str:
    return FIXTURES["by_service_version"][(service, version)]["release_id"]


def obligation_tuple(service: str, version: str, record_id: str, payload_hash="sha256:payload") -> dict:
    """A compact but realistic serialized ObligationTuple, like the saved reports carry."""
    rid = release_id_of(service, version)
    return {"service": service, "release_id": rid, "record_id": record_id,
            "route_id": f"route:{rid}:" + ("load_saved_cart" if service == "cart" else "price_saved_cart"),
            "store_id": "store:cart-cache",
            "batch_id": f"batch:{record_id}", "payload_hash": payload_hash, "format_id": "cart/v1"}


def full_key(service: str, version: str, record_id: str) -> tuple[str, str, str, str, str]:
    """The scorer's five-field obligation key for one (service, version, record) of case B."""
    tup = obligation_tuple(service, version, record_id)
    return (service, version, tup["route_id"], tup["store_id"], record_id)


def ob_hash(i: int) -> str:
    """The canonical obligation hash of case B's i-th obligation tuple, as the runtime computes it."""
    from rw.contracts import h
    return h(obligation_tuple(*CASE_B_PAIRS[i]))


def make_report(receipts: list[dict], claim: str | None = None,
                statuses: dict | None = None) -> dict:
    """A saved-report-shaped dict for case B (BOUNDED_PASS): 4 obligations, receipts built by the
    caller. ``receipts`` carry ``obligation_hash``, ``tuple`` and ``result`` like real reports do."""
    case = OI["cases"]["B"]
    obligations = [{"obligation_hash": ob_hash(i), "tuple": obligation_tuple(*pair)}
                   for i, pair in enumerate(CASE_B_PAIRS)]
    hashes = {pair: ob["obligation_hash"] for ob, pair in zip(obligations, CASE_B_PAIRS)}
    if statuses is not None:
        # receipts bound to the exact obligation tuples, one per obligation
        receipts = [{"obligation_hash": hashes[pair], "tuple": obligation_tuple(*pair), "result": status}
                    for pair, status in statuses.items()]
    assert all("obligation_hash" in r and "tuple" in r and "result" in r for r in receipts)
    plan_fleet = [{"service": "cart", "release_id": release_id_of("cart", "1.5"),
                   "flags": {"basket_v2": False}},
                  {"service": "checkout", "release_id": release_id_of("checkout", "2.1"),
                   "flags": {}}]
    claim = case["disposition"] if claim is None else claim
    return {"_path": "reports/hand-made.json", "snapshot": "snap-001",
            "attempts": [{"grounding": {"model": "test", "live": False},
                          "outcome": claim, "report": {
                              "plan": {"label": "p", "fleet": plan_fleet},
                              "verification": {"disposition": claim, "obligations": obligations,
                                               "receipts": receipts}}}]}


def from_report(report: dict) -> dict:
    runs = scoring.runs_from_report(report, FIXTURES, MANIFESTS["snap-001"])
    assert len(runs) == 1 and runs[0]["origin"] == "product"
    return runs[0]


def test_report_receipt_with_a_mismatched_tuple_is_not_evidence():
    """A receipt that matches an obligation only by obligation_hash (stale copy, foreign binding)
    must not discharge the pair: last-write-wins by hash let mismatched PASS receipts score a case B
    BOUNDED_PASS claim as consistent, while deterministic recomputation gives NEEDS_EVIDENCE."""
    report = make_report([{"obligation_hash": ob_hash(i),
                           "tuple": dict(obligation_tuple(*pair), payload_hash="sha256:foreign"),
                           "result": "PASS"} for i, pair in enumerate(CASE_B_PAIRS)])
    run = from_report(report)
    assert run["probed"] == {}                      # no bound receipt: nothing was probed
    assert run["probed"] != {"FAIL": "x"}           # sanity: statuses folded downstream
    row = score(run)
    assert row["recall"] == "0/4"
    assert row["evidence_supports_claim"] is False and row["unsupported_pass"] is True
    assert not scoring.consistent(row) and scoring._unsafe(row)
    notes = " ".join(row["notes"])
    assert "4" in notes and "receipt" in notes      # non-binding receipts are reported, not silent


def test_applicable_fail_beats_a_later_pass_for_the_same_pair():
    """Two receipts bound to the same obligation tuple (retry): the FAIL dominates. Last-write-wins
    scored the later PASS, hiding a BLOCKED outcome behind an established BOUNDED_PASS."""
    fail_then_pass = []
    for i, pair in enumerate(CASE_B_PAIRS):
        tup = obligation_tuple(*pair)
        if pair == ("cart", "1.5", "saved-cart-2002"):
            fail_then_pass.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "FAIL",
                                   "executed_at": "t1"})
            fail_then_pass.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "PASS",
                                   "executed_at": "t2"})
        else:
            fail_then_pass.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "PASS"})
    report = make_report(fail_then_pass)
    run = from_report(report)
    key = full_key("cart", "1.5", "saved-cart-2002")
    assert run["probed"][key] == "FAIL"
    blocked = dict(run, disposition="BLOCKED")
    bounded = dict(run, disposition="BOUNDED_PASS")
    row = score(bounded)
    assert row["observed_fails"] == 1 and row["established_passes"] == 3
    assert row["evidence_supports_claim"] is False      # FAIL dominates a later PASS
    blocked_row = score(blocked)
    assert blocked_row["evidence_supports_claim"] is True   # observed FAIL supports a BLOCKED claim
    assert not scoring.consistent(row)
    line = scoring.markdown_row(row)
    assert "1 FAIL on the proposed fleet" in line


def test_pass_then_unknown_is_not_an_established_pass():
    """A pair probed PASS and (on retry) UNKNOWN was not established: UNKNOWN dominates PASS."""
    receipts = []
    for i, pair in enumerate(CASE_B_PAIRS):
        tup = obligation_tuple(*pair)
        if pair == ("checkout", "2.1", "saved-cart-2002"):
            receipts.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "PASS"})
            receipts.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "UNKNOWN"})
        else:
            receipts.append({"obligation_hash": ob_hash(i), "tuple": tup, "result": "PASS"})
    report = make_report(receipts)
    run = from_report(report)
    assert run["probed"][full_key("checkout", "2.1", "saved-cart-2002")] == "UNKNOWN"
    row = score(run)
    assert row["recall"] == "4/4" and row["established_passes"] == 3
    assert row["unknown_probes"] == 1
    assert row["evidence_supports_claim"] is False and row["unsupported_pass"] is True
    assert not scoring.consistent(row)


def test_bound_receipts_still_count_as_evidence():
    """Regression guard: honest reports whose receipts bind to the exact obligation tuples keep
    scoring as before (case B fully passed -> oracle-consistent)."""
    report = make_report([], statuses={pair: "PASS" for pair in CASE_B_PAIRS})
    run = from_report(report)
    assert all(run["probed"][full_key(*pair)] == "PASS" for pair in CASE_B_PAIRS)
    row = score(run)
    assert row["recall"] == "4/4" and row["established_passes"] == 4
    assert row["evidence_supports_claim"] is True
    assert scoring.consistent(row) and not scoring._unsafe(row)
    assert not any("receipt" in note for note in row["notes"])


def test_control_transcript_repeated_probe_pair_uses_dominance():
    """Controls can probe one pair more than once (a retry); the fold is FAIL > unresolved > PASS,
    never last-write-wins."""
    base = {"_path": str(Path("artifacts/controls/llm_flat_20261015T101112000000Z.json")),
            "model": "m", "live": True, "snapshot": "snap-001", "aborted": False,
            "model_turns": 5, "tool_call_count": 4,
            "result": {"fleet": {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                                 "checkout": {"version": "2.1", "flags": {}}},
                       "disposition": "BOUNDED_PASS"}}
    def transcript(*statuses_for_cart2002):
        t = dict(base)
        t["probe_calls"] = [
            {"service": "cart", "version": "1.5", "record_id": "saved-cart-1001",
             "result": {"status": "PASS"}},
        ] + [{"service": "cart", "version": "1.5", "record_id": "saved-cart-2002",
              "result": {"status": s}} for s in statuses_for_cart2002] + [
            {"service": "checkout", "version": "2.1", "record_id": "saved-cart-1001",
             "result": {"status": "PASS"}},
            {"service": "checkout", "version": "2.1", "record_id": "saved-cart-2002",
             "result": {"status": "PASS"}},
        ]
        return t

    fail_fold = score(scoring.run_from_control(transcript("FAIL", "PASS"), FIXTURES, MANIFESTS["snap-001"]))
    key = ("cart", "1.5", "saved-cart-2002")
    assert fail_fold["established_passes"] == 3 and fail_fold["observed_fails"] == 1
    unknown_fold = score(scoring.run_from_control(transcript("PASS", "UNKNOWN"), FIXTURES, MANIFESTS["snap-001"]))
    assert unknown_fold["established_passes"] == 3 and unknown_fold["unknown_probes"] == 1
    assert unknown_fold["evidence_supports_claim"] is False
    assert not scoring.consistent(unknown_fold)


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


def test_scorer_canonical_hash_matches_the_runtime_hash():
    """The scorer re-states the documented canonical hash; it must equal the product's."""
    from rw.contracts import h
    tup = obligation_tuple(*CASE_B_PAIRS[0])
    assert scoring._canonical_hash(tup) == h(tup)


def test_obligation_hash_that_is_not_its_tuples_hash_is_not_evidence():
    """Replacing obligation and receipt hashes with matching arbitrary values must not bind."""
    fake = "sha256:" + "ab" * 32
    report = make_report([{"obligation_hash": fake, "tuple": obligation_tuple(*pair), "result": "PASS"}
                          for pair in CASE_B_PAIRS], claim="BOUNDED_PASS")
    for ob in report["attempts"][0]["report"]["verification"]["obligations"]:
        ob["obligation_hash"] = fake
    [run] = scoring.runs_from_report(report, FIXTURES, MANIFESTS["snap-001"])
    assert run["probed"] == {}
    assert any("not the canonical hash" in note for note in run["fleet_notes"])
    row = scoring.score_run(run, OI, FIXTURES, MANIFESTS)
    assert row["unsupported_pass"] and not scoring.consistent(row)


def test_reported_evidence_gap_leaves_a_bounded_pass_unsupported():
    """Four bound PASS receipts plus a reported WRITER_UNKNOWN gap: the runtime says NEEDS_EVIDENCE,
    so a BOUNDED_PASS claim from that report is not supported."""
    report = make_report([{"obligation_hash": ob_hash(i), "tuple": obligation_tuple(*pair), "result": "PASS"}
                          for i, pair in enumerate(CASE_B_PAIRS)], claim="BOUNDED_PASS")
    report["attempts"][0]["report"]["verification"]["gaps"] = [
        {"kind": "WRITER_UNKNOWN", "subject": "saved-cart-2002"}]
    [run] = scoring.runs_from_report(report, FIXTURES, MANIFESTS["snap-001"])
    row = scoring.score_run(run, OI, FIXTURES, MANIFESTS)
    assert row["established_passes"] == 4
    assert row["unsupported_pass"] and not scoring.consistent(row)
