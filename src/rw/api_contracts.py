"""HTTP presentation contracts. These models never participate in evidence hashes."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator

from .contracts import (Approval, CandidatePlan, Citation, Disposition, FleetEntry,
                        GroundingClarification, GroundingProposal, Obligation, ObligationTuple, ProbeReceipt,
                        ScopeConfirmation, SimulationReceipt, VerificationResult)


HashString = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ReleaseID = Annotated[str, Field(pattern=r"^release:[^:\s/\\]+:[0-9a-f]{16}$")]
SnapshotID = Annotated[str, Field(pattern=r"^snapshot:snap-(001|002-partial|003-orphan)$")]


def aware_timestamp(value: str) -> str:
    if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value  # preserve the original HTTP spelling (including +00:00)


Timestamp = Annotated[str, AfterValidator(aware_timestamp), Field(json_schema_extra={"format": "date-time"})]


class View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryAudit(View):
    # Params are JSON values from fixed, parameterized server queries, never executable queries.
    name: str
    params: dict[str, JsonValue]
    rows: int = Field(ge=0)
    truncated: bool


class CitationView(Citation):
    kind: str | None
    release_id: str | None


class ProposalView(GroundingProposal):
    citations: list[CitationView]


class ClarificationView(GroundingClarification):
    citations: list[CitationView]


class GroundingView(View):
    request_text: str = Field(min_length=1, max_length=28000)
    result: Annotated[ProposalView | ClarificationView, Field(discriminator="kind")]
    model: str
    live: bool
    # Provider audit payloads are retained by HTTP only, and omitted from MCP projections.
    tool_calls: list[dict[str, JsonValue]]
    validation_errors: list[str]


class FleetEntryView(FleetEntry):
    current_release_id: str | None
    current_version: str | None
    proposed_version: str | None


class ReportPlanView(CandidatePlan):
    fleet: list[FleetEntryView]
    snapshot_id: SnapshotID
    snapshot_manifest_hash: HashString
    request_text_hash: HashString
    source_hashes: list[HashString]
    release_labels: dict[str, str]


class PlanView(ReportPlanView):
    citations: list[CitationView]


class StartupResult(View):
    result: Literal["GREEN", "RED", "UNKNOWN"]
    codec_path: str
    exit: int | None
    release_id: str | None = None


class TupleView(ObligationTuple):
    plan_hash: HashString
    snapshot_id: SnapshotID
    snapshot_manifest_hash: HashString
    release_id: ReleaseID
    codec_hash: HashString
    route_contract_hash: HashString
    payload_hash: HashString
    probe_spec_hash: HashString
    environment_hash: HashString
    semantic_scope: Literal["BYTE_SHAPE_ONLY"] = "BYTE_SHAPE_ONLY"


class ObligationView(Obligation):
    tuple: TupleView
    obligation_hash: HashString
    writer_release_id: ReleaseID | None


class ReceiptView(ProbeReceipt):
    tuple: TupleView
    obligation_hash: HashString
    evidence_hash: HashString
    executed_at: Timestamp
    duration_ms: int = Field(ge=0)


class VerificationView(VerificationResult):
    plan_hash: HashString
    snapshot_id: SnapshotID
    snapshot_manifest_hash: HashString
    obligations: list[ObligationView]
    receipts: list[ReceiptView]
    blocking_receipts: list[HashString]
    computed_at: Timestamp
    dependencies: list[ReleaseID] = Field(default_factory=list)
    semantic_scope: Literal["BYTE_SHAPE_ONLY"] = "BYTE_SHAPE_ONLY"


class ReportView(View):
    startup_checks: dict[str, StartupResult]
    plan: ReportPlanView
    plan_id: Annotated[str, Field(pattern=r"^plan:[0-9a-f]{16}$")]
    plan_hash: HashString
    scope_confirmation: ScopeConfirmation
    verification: VerificationView
    verification_hash: HashString
    queries: list[QueryAudit]
    release_labels: dict[str, str]


class AttemptView(View):
    grounding: GroundingView
    is_live_provider: bool
    transcript: str | None
    plan: PlanView | None
    plan_hash: str | None
    citations: list[CitationView]
    validation_errors: list[str]
    clarification: ClarificationView | None
    report: ReportView | None
    approval: Approval | None
    simulation: SimulationReceipt | None
    release_labels: dict[str, str]


class InvestigationView(AttemptView):
    id: str
    investigation_id: str
    request_text: str = Field(min_length=1, max_length=28000)
    original_request_text: str = Field(min_length=1, max_length=20000)
    answered: bool
    mode: Literal["live", "replay"]
    snapshot_id: str
    snapshot_manifest_hash: str
    attempts: list[AttemptView] = Field(min_length=1)

    @model_validator(mode="after")
    def aliases(self):
        if self.id != self.investigation_id:
            raise ValueError("investigation IDs disagree")
        for name in AttemptView.model_fields:
            if getattr(self, name) != getattr(self.attempts[-1], name):
                raise ValueError("latest-attempt alias disagrees")
        return self


class InvestigationSummary(View):
    id: str
    investigation_id: str
    request_text: str
    mode: Literal["live", "replay"]
    latest_disposition: Disposition | None

    @model_validator(mode="after")
    def ids(self):
        if self.id != self.investigation_id:
            raise ValueError("investigation IDs disagree")
        return self


class TranscriptSummary(View):
    file_name: str
    replay_path: str
    request_text: str
    model: str
    live: bool
    outcome: Literal["question", "proposal"] | None
    mtime: Timestamp

    @model_validator(mode="after")
    def selector(self):
        if (self.file_name != self.replay_path or not self.replay_path
                or any(c in self.replay_path for c in "/\\:")
                or any(ord(c) < 32 or ord(c) == 127 for c in self.replay_path)):
            raise ValueError("transcript selector must be a basename")
        return self


class ValidationDetail(View):
    type: str
    loc: list[str | int]
    msg: str
    input: JsonValue = None
    ctx: dict[str, JsonValue] | None = None


class ValidationErrorView(View):
    detail: list[ValidationDetail]


class ProviderDetail(View):
    code: Literal["provider_quota", "provider_unavailable", "provider_error"]
    message: str


class DriftDetail(View):
    reason: str
    drift: list[str]


class DetailError(View):
    detail: str | ProviderDetail


class RefusalError(View):
    detail: str | DriftDetail
    reason: str


ERROR_RESPONSES = {
    404: {"model": DetailError},
    409: {"model": RefusalError | DetailError},
    422: {"model": ValidationErrorView | DetailError},
    502: {"model": DetailError},
}
PAGE_RESPONSES = {**ERROR_RESPONSES, 200: {"headers": {
    "X-Next-Cursor": {"description": "Opaque continuation cursor; absent on the last page. Weakly consistent across concurrent changes.",
                      "schema": {"type": "string"}},
}}}
