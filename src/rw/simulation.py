"""Human-approval-bound local fleet simulation with an atomic SQLite ledger."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from rw.contracts import (Approval, CandidatePlan, Disposition, FleetEntry,
                          SimulationReceipt, VerificationResult, canonical_json, h)

DEFAULT_DB_PATH = Path("artifacts/sim.sqlite")
DEFAULT_FORBIDDEN_IDENTITIES = frozenset({"gemini-3.8-flash", "agent", "model"})


class SimulationRefused(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@contextmanager
def _transaction(db_path):
    try:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS approvals (approval_hash TEXT PRIMARY KEY, approval_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS simulation_receipts (idempotency_key TEXT PRIMARY KEY, receipt_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS simulated_fleet (idempotency_key TEXT PRIMARY KEY, fleet_json TEXT NOT NULL)")
            yield connection
    except (sqlite3.Error, OSError) as exc:
        raise SimulationRefused(f"ledger error: {exc}") from exc


def _validate(approval, verification):
    if approval is None or verification is None:
        raise SimulationRefused("approval and verification required")
    if verification.disposition != Disposition.BOUNDED_PASS:
        raise SimulationRefused("verification is not BOUNDED_PASS")
    if approval.verification_hash != verification.verification_hash():
        raise SimulationRefused("verification hash mismatch")
    if approval.plan_hash != verification.plan_hash:
        raise SimulationRefused("plan hash mismatch")
    if approval.snapshot_manifest_hash != verification.snapshot_manifest_hash:
        raise SimulationRefused("snapshot manifest hash mismatch")


def record_approval(db_path=DEFAULT_DB_PATH, approval: Approval | None = None,
                    verification: VerificationResult | None = None,
                    forbidden_identities=DEFAULT_FORBIDDEN_IDENTITIES) -> None:
    _validate(approval, verification)
    forbidden = {value.strip().casefold() for value in forbidden_identities}
    identity = approval.approved_by.strip().casefold()
    if not identity or identity in forbidden:
        raise SimulationRefused("approval requires a human identity")
    with _transaction(db_path) as connection:
        connection.execute("INSERT OR IGNORE INTO approvals VALUES (?, ?)",
                           (h(approval), approval.model_dump_json()))


def _fleet_dump(fleet: list[FleetEntry]):
    return sorted([entry.model_dump(mode="json") for entry in fleet], key=canonical_json)


def simulate(db_path=DEFAULT_DB_PATH, approval: Approval | None = None,
             verification: VerificationResult | None = None,
             current_manifest_hash: str | None = None,
             current_fleet: list[FleetEntry] | None = None,
             plan: CandidatePlan | None = None) -> SimulationReceipt:
    with _transaction(db_path) as connection:
        _validate(approval, verification)
        if not connection.execute("SELECT 1 FROM approvals WHERE approval_hash = ?", (h(approval),)).fetchone():
            raise SimulationRefused("approval not recorded")
        if current_manifest_hash != approval.snapshot_manifest_hash:
            raise SimulationRefused("stale snapshot manifest")
        if plan is None or plan.plan_hash() != approval.plan_hash:
            raise SimulationRefused("plan hash mismatch")
        if (plan.snapshot_manifest_hash != approval.snapshot_manifest_hash
                or plan.snapshot_id != verification.snapshot_id):
            raise SimulationRefused("plan snapshot mismatch")
        if current_fleet is None:
            raise SimulationRefused("current fleet required")
        key = approval.idempotency_key()
        existing = connection.execute("SELECT receipt_json FROM simulation_receipts WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            return SimulationReceipt.model_validate_json(existing[0]).model_copy(update={"applied": False})
        fleet_dump = _fleet_dump(plan.fleet)
        receipt = SimulationReceipt(
            idempotency_key=key, plan_hash=approval.plan_hash, applied=True,
            previous_fleet_hash=h(_fleet_dump(current_fleet)), new_fleet_hash=h(fleet_dump),
            applied_at=datetime.now(timezone.utc).isoformat())
        connection.execute("INSERT INTO simulated_fleet VALUES (?, ?)", (key, canonical_json(fleet_dump).decode("utf-8")))
        connection.execute("INSERT INTO simulation_receipts VALUES (?, ?)", (key, receipt.model_dump_json()))
        return receipt
