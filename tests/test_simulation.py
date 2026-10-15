from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import pytest

from rw.contracts import (Approval, CandidatePlan, Disposition, FleetEntry,
                          VerificationResult, canonical_json, h)
from rw.simulation import SimulationRefused, record_approval, simulate


@pytest.fixture
def case(tmp_path):
    fleet = [FleetEntry(service="cart", release_id="release:cart:old")]
    plan = CandidatePlan(snapshot_id="snapshot:test", snapshot_manifest_hash=h("manifest"),
        request_text_hash=h("rollback"), fleet=[FleetEntry(service="cart", release_id="release:cart:new", changed=True)],
        source_hashes=[h("source")], origin="fixture")
    verification = VerificationResult(plan_hash=plan.plan_hash(), snapshot_id=plan.snapshot_id,
        snapshot_manifest_hash=plan.snapshot_manifest_hash, disposition=Disposition.BOUNDED_PASS,
        obligations=[], receipts=[], gaps=[], blocking_receipts=[], computed_at="2026-10-15T10:00:00Z")
    approval = Approval(plan_hash=plan.plan_hash(), verification_hash=verification.verification_hash(),
        snapshot_manifest_hash=plan.snapshot_manifest_hash, approved_by="human:oncall",
        approved_at="2026-10-15T10:01:00Z")
    return dict(db_path=tmp_path / "nested/sim.sqlite", approval=approval, verification=verification,
                current_manifest_hash=plan.snapshot_manifest_hash, current_fleet=fleet, plan=plan)


def approve(case, **kwargs):
    record_approval(case["db_path"], case["approval"], case["verification"], **kwargs)


@pytest.mark.parametrize("disposition", [Disposition.BLOCKED, Disposition.NEEDS_EVIDENCE])
def test_refuse_nonpass(case, disposition):
    approve(case)
    verification = case["verification"].model_copy(update={"disposition": disposition})
    with pytest.raises(SimulationRefused, match="not BOUNDED_PASS"):
        record_approval(case["db_path"], case["approval"], verification)
    with pytest.raises(SimulationRefused, match="not BOUNDED_PASS"):
        simulate(**(case | {"verification": verification}))


@pytest.mark.parametrize("identity", ["", "   ", "agent", "model", "gemini-3.8-flash", "CUSTOM-MODEL", " Agent "])
def test_forbidden_approver(case, identity):
    case["approval"] = case["approval"].model_copy(update={"approved_by": identity})
    with pytest.raises(SimulationRefused, match="human identity"):
        approve(case, forbidden_identities={"agent", "model", "gemini-3.8-flash", "custom-model"})


@pytest.mark.parametrize("field", ["plan_hash", "verification_hash", "snapshot_manifest_hash"])
def test_approval_bindings(case, field):
    case["approval"] = case["approval"].model_copy(update={field: h("wrong")})
    with pytest.raises(SimulationRefused, match="hash mismatch"):
        approve(case)


def test_unrecorded_approval(case):
    with pytest.raises(SimulationRefused, match="not recorded"):
        simulate(**case)


def test_stale_manifest(case):
    approve(case)
    with pytest.raises(SimulationRefused, match="stale"):
        simulate(**(case | {"current_manifest_hash": h("new snapshot")}))


def test_mutated_plan(case):
    approve(case)
    plan = case["plan"].model_copy(update={"fleet": [FleetEntry(service="cart", release_id="unapproved")]})
    with pytest.raises(SimulationRefused, match="plan hash mismatch"):
        simulate(**(case | {"plan": plan}))


def test_mutated_verification(case):
    approve(case)
    verification = case["verification"].model_copy(update={"semantic_scope": "unapproved"})
    with pytest.raises(SimulationRefused, match="verification hash mismatch"):
        simulate(**(case | {"verification": verification}))


def assert_one_state(case):
    with sqlite3.connect(case["db_path"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM simulation_receipts").fetchone()[0] == 1
        rows = connection.execute("SELECT fleet_json FROM simulated_fleet").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0]) == [entry.model_dump(mode="json") for entry in case["plan"].fleet]


def test_duplicate_applies_once(case):
    approve(case)
    approve(case)  # Recording the exact approval is also idempotent.
    first = simulate(**case)
    second = simulate(**case)
    assert first.applied is True
    assert second.applied is False
    assert second == first.model_copy(update={"applied": False})
    assert first.previous_fleet_hash == h(sorted([x.model_dump(mode="json") for x in case["current_fleet"]], key=canonical_json))
    assert first.new_fleet_hash == h(sorted([x.model_dump(mode="json") for x in case["plan"].fleet], key=canonical_json))
    assert_one_state(case)
    # A duplicate must still pass freshness checks.
    with pytest.raises(SimulationRefused, match="stale"):
        simulate(**(case | {"current_manifest_hash": h("stale")}))


def test_concurrent_connections_apply_once(case):
    approve(case)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        return simulate(**case)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        receipts = [future.result(timeout=10) for future in futures]
    assert sorted(receipt.applied for receipt in receipts) == [False, True]
    assert receipts[0].idempotency_key == receipts[1].idempotency_key
    assert_one_state(case)


def test_refusal_rolls_back_without_state_change(case):
    approve(case)
    with pytest.raises(SimulationRefused):
        simulate(**(case | {"plan": None}))
    with sqlite3.connect(case["db_path"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM simulated_fleet").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM simulation_receipts").fetchone()[0] == 0


def test_recorded_approval_is_exact(case):
    approve(case)
    altered = case["approval"].model_copy(update={"approved_by": "different-human"})
    with pytest.raises(SimulationRefused, match="not recorded"):
        simulate(**(case | {"approval": altered}))
