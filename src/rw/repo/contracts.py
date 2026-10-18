"""Published retrieval response contract, shared by transport adapters."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rw.repo.model import Citation, Gap


class FindingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    summary: str
    citations: list[Citation] = Field(default_factory=list)
    disposition: None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    revision: str | None = None


class RepoInvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str
    revision: str | None
    resolved_sha: str | None = None
    index_generation: str | None = None
    retrieval_budget: dict[str, Any] | None = None
    unresolved: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
    findings: list[FindingResult] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    disposition: None = None
    receipts: list[Any] = Field(default_factory=list)
