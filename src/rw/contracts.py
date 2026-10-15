"""Frozen shared contracts for RollbackWitness (owner: orchestrator).

See docs/CONTRACTS.md. Workers must not edit this module; request changes instead.
All payloads are immutable; hashes use canonical JSON so identical facts hash identically.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCOPE_ID = "fixture-shop"
GRAPH_NAME = "rw_fixture_shop"
SEMANTIC_SCOPE = "BYTE_SHAPE_ONLY"
UNKNOWN = "UNKNOWN"
PROBE_FAMILY = "byte_shape_v1"
QUERY_CAP = 200  # fixed per-query row cap; queries fetch cap+1 to detect truncation
MAX_PLANS_PER_SESSION = 2


# --------------------------------------------------------------------------- hashing

def canonical_json(obj: Any) -> bytes:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def h(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj)).hexdigest()


def bh(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def short(hash_value: str) -> str:
    """16 hex chars after the 'sha256:' prefix, used inside IDs."""
    return hash_value[7:23]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- enums

class Coverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ProbeResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"  # harness error, timeout, unavailable reader — never an observed incompatibility


class Disposition(str, Enum):
    BLOCKED = "BLOCKED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    BOUNDED_PASS = "BOUNDED_PASS"


class GapKind(str, Enum):
    INVALID_FLEET = "INVALID_FLEET"                  # unknown release/service/flag, service missing from fleet
    ROUTE_EVIDENCE_MISSING = "ROUTE_EVIDENCE_MISSING"  # release declares neither routes nor no_state_read
    READ_DOMAIN_UNKNOWN = "READ_DOMAIN_UNKNOWN"
    STORE_MISSING = "STORE_MISSING"                  # route reads a store absent from snapshot/graph
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"      # coverage PARTIAL/UNKNOWN/missing for a read store
    INVENTORY_MISMATCH = "INVENTORY_MISMATCH"        # graph batch ID set != independently parsed manifest set
    WRITER_UNKNOWN = "WRITER_UNKNOWN"                # batch lacks WRITTEN_BY / manifest writer null
    FORMAT_UNKNOWN = "FORMAT_UNKNOWN"
    TRUNCATED = "TRUNCATED"                          # query hit cap+1
    RECEIPT_MISSING = "RECEIPT_MISSING"
    RECEIPT_UNKNOWN = "RECEIPT_UNKNOWN"              # probe ran but harness error/timeout
    RECEIPT_INAPPLICABLE = "RECEIPT_INAPPLICABLE"    # receipt tuple differs from obligation tuple
    STALE_SNAPSHOT = "STALE_SNAPSHOT"


# --------------------------------------------------------------------------- source & grounding

class Citation(Frozen):
    excerpt_id: str
    content_hash: str
    quote: str  # must be an exact substring of the excerpt text (verified by trusted code)


class FleetEntry(Frozen):
    service: str          # e.g. "cart"
    release_id: str       # exact graph Release.id
    flags: dict[str, bool] = Field(default_factory=dict)
    changed: bool = False  # differs from current deployment (filled by trusted code)


class GroundingProposal(Frozen):
    kind: Literal["PROPOSAL"] = "PROPOSAL"
    changes: list[FleetEntry]      # only services the agent proposes to change; trusted code completes the fleet
    citations: list[Citation]
    rationale: str


class GroundingClarification(Frozen):
    kind: Literal["CLARIFICATION"] = "CLARIFICATION"
    question: str
    unresolved: list[str]          # request phrases that could not be bound to one artifact
    citations: list[Citation] = Field(default_factory=list)


class GroundingResult(Frozen):
    request_text: str
    result: GroundingProposal | GroundingClarification = Field(discriminator="kind")
    model: str                     # e.g. "gemini-3.8-flash"; "replay:<file>" when not live
    live: bool
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # name, args, row counts — audit only
    validation_errors: list[str] = Field(default_factory=list)      # filled by trusted validation


# --------------------------------------------------------------------------- plans

class CandidatePlan(Frozen):
    scope_id: str = SCOPE_ID
    snapshot_id: str
    snapshot_manifest_hash: str
    request_text_hash: str
    fleet: list[FleetEntry]        # every service in the snapshot, sorted by service
    source_hashes: list[str]       # content hashes of cited excerpts, sorted
    origin: Literal["agent", "fixture"]
    label: str = ""

    def plan_hash(self) -> str:
        return h({
            "scope_id": self.scope_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "request_text_hash": self.request_text_hash,
            "fleet": sorted([f.model_dump(mode="json", exclude={"changed"}) for f in self.fleet],
                            key=lambda f: f["service"]),
            "source_hashes": sorted(self.source_hashes),
        })

    def plan_id(self) -> str:
        return "plan:" + short(self.plan_hash())


class ScopeConfirmation(Frozen):
    plan_hash: str
    confirmed_by: str              # human identity string; never the model
    confirmed_at: str


# --------------------------------------------------------------------------- obligations & receipts

class ObligationTuple(Frozen):
    scope_id: str
    plan_hash: str
    snapshot_id: str
    snapshot_manifest_hash: str
    service: str
    deployment_id: str
    release_id: str
    codec_hash: str
    route_id: str
    route_contract_hash: str
    store_id: str
    batch_id: str
    record_id: str
    payload_hash: str
    format_id: str                 # literal "UNKNOWN" when not established
    semantic_scope: str = SEMANTIC_SCOPE
    probe_spec_hash: str
    environment_hash: str

    def obligation_hash(self) -> str:
        return h(self)


class WitnessHop(Frozen):
    label: str                     # node label, e.g. "Release"
    id: str
    rel_to_next: str | None = None  # e.g. "-EXECUTES_ROUTE->" ; None on the last hop
    display: str = ""


class Obligation(Frozen):
    tuple: ObligationTuple
    obligation_hash: str
    writer_release_id: str | None  # None when WRITTEN_BY is missing (gap recorded separately)
    witness_path: list[WitnessHop]  # Plan -> Deployment -> Release -> ReaderRoute -> StateStore <- Batch -> writer Release
    reader_codec_path: str          # trusted fixture path used by the probe
    reader_entry: str


class Gap(Frozen):
    kind: GapKind
    subject: str                   # ID the gap is about
    detail: str


class ProbeReceipt(Frozen):
    obligation_hash: str
    tuple: ObligationTuple
    result: ProbeResult
    harness_exit: int | None       # None on timeout
    stdout_excerpt: str            # capped
    evidence_hash: str             # bh(raw stdout bytes)
    error_type: str | None = None
    message: str | None = None
    executed_at: str
    duration_ms: int

    def receipt_hash(self) -> str:
        return h(self)


class GraphEvidence(Frozen):
    """What the graph returned for one plan, before probing."""
    plan_hash: str
    obligations: list[Obligation]
    gaps: list[Gap]
    queries: list[dict[str, Any]]  # {"name","params","rows","truncated"} — the fixed queries actually executed


class VerificationResult(Frozen):
    plan_hash: str
    snapshot_id: str
    snapshot_manifest_hash: str
    disposition: Disposition
    obligations: list[Obligation]
    receipts: list[ProbeReceipt]
    gaps: list[Gap]
    blocking_receipts: list[str]   # obligation hashes with applicable FAIL
    semantic_scope: str = SEMANTIC_SCOPE
    computed_at: str

    def verification_hash(self) -> str:
        # computed_at excluded so a rerun on identical evidence yields the same hash
        return h(self.model_dump(mode="json", exclude={"computed_at"}))


# --------------------------------------------------------------------------- approval & simulation

class Approval(Frozen):
    plan_hash: str
    verification_hash: str
    snapshot_manifest_hash: str
    approved_by: str               # human identity; the model can never produce this
    approved_at: str

    def idempotency_key(self) -> str:
        return h([self.plan_hash, self.verification_hash])


class SimulationReceipt(Frozen):
    idempotency_key: str
    plan_hash: str
    applied: bool                  # False when a duplicate request was a no-op
    previous_fleet_hash: str
    new_fleet_hash: str
    applied_at: str
    note: str = "LOCAL SIMULATION ONLY — no deployment performed"
