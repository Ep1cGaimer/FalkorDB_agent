"""Strict MCP arguments and safe, typed projections of stored HTTP evidence."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .api_contracts import (AttemptView, GroundingView, InvestigationSummary, ProposalView, ClarificationView,
                            ReportView, TranscriptSummary, TupleView, VerificationView, View)
from .contracts import WitnessHop


InvestigationID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SnapshotID = Annotated[str, Field(pattern=r"^snapshot:snap-(001|002-partial|003-orphan)$")]


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def picker_filename(value: str) -> str:
    if (not 1 <= len(value) <= 255 or not value.lower().endswith(".json")
            or any(c in value for c in "/\\:") or value in {".", ".."}
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("must be a saved JSON filename")
    return value


ReplaySelector = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(picker_filename)]
RequestText = Annotated[str, Field(min_length=1, max_length=20000), AfterValidator(nonblank)]
AnswerText = Annotated[str, Field(min_length=1, max_length=4000), AfterValidator(nonblank)]
Cursor = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")]


class Input(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class StartInput(Input):
    request_text: RequestText
    mode: Literal["live", "replay"] = "live"
    replay_path: ReplaySelector | None = None
    snapshot: Literal["snap-001", "snap-002-partial", "snap-003-orphan"] = "snap-001"

    @model_validator(mode="after")
    def mode_path(self):
        if (self.mode == "replay") != (self.replay_path is not None):
            raise ValueError("replay mode requires a filename; live mode forbids it")
        return self


class GetInput(Input):
    investigation_id: InvestigationID


class ListInput(Input):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: Cursor | None = None


class AnswerInput(GetInput):
    answer: AnswerText
    replay_path: ReplaySelector | None = None


class AlternativeInput(GetInput):
    replay_path: ReplaySelector | None = None


class ScopeLabels(View):
    schema_version: Literal["1"] = "1"
    synthetic_fixture: Literal[True] = True
    semantic_scope: Literal["BYTE_SHAPE_ONLY"] = "BYTE_SHAPE_ONLY"
    local_simulation_only: Literal[True] = True


class SafeGrounding(View):
    request_text: str
    result: ProposalView | ClarificationView = Field(discriminator="kind")
    model: str
    live: bool
    validation_errors: list[str]


class SafeObligation(View):
    tuple: TupleView
    obligation_hash: Hash
    writer_release_id: str | None
    witness_path: list[WitnessHop]
    reader_entry: str


class SafeVerification(VerificationView):
    obligations: list[SafeObligation]


class SafeStartup(View):
    result: Literal["GREEN", "RED", "UNKNOWN"]
    exit: int | None
    release_id: str | None = None


class SafeReport(ReportView):
    startup_checks: dict[str, SafeStartup]
    verification: SafeVerification


class SafeAttempt(AttemptView):
    grounding: SafeGrounding
    report: SafeReport | None
    transcript: ReplaySelector | None


class SafeInvestigation(SafeAttempt):
    id: InvestigationID
    investigation_id: InvestigationID
    request_text: str
    original_request_text: str
    answered: bool
    mode: Literal["live", "replay"]
    snapshot_id: SnapshotID
    snapshot_manifest_hash: Hash
    attempts: list[SafeAttempt]


NextAction = Literal["answer_clarification", "resolve_validation_errors", "human_confirm_scope",
                     "request_alternative", "human_review", "none"]


class InvestigationResult(ScopeLabels):
    investigation_id: InvestigationID
    snapshot_id: SnapshotID
    snapshot_manifest_hash: Hash
    plan_hash: Hash | None
    verification_hash: Hash | None
    mode: Literal["live", "replay"]
    model: str
    live: bool
    data: SafeInvestigation
    next_action: NextAction
    review_url: str
    evidence_note: str = ("Stored verification only; reading does not recheck byte freshness. "
                          "After evidence drift, start a new investigation and have the human confirm and approve the new exact plan.")


class InvestigationList(ScopeLabels):
    items: list[InvestigationSummary]
    next_cursor: Cursor | None


class TranscriptList(ScopeLabels):
    items: list[TranscriptSummary]
    next_cursor: Cursor | None


INPUTS = {
    "rw_start_investigation": StartInput,
    "rw_get_investigation": GetInput,
    "rw_list_investigations": ListInput,
    "rw_list_transcripts": ListInput,
    "rw_answer_clarification": AnswerInput,
    "rw_request_alternative": AlternativeInput,
}
