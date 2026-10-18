"""Shared repository/history model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Citation:
    repo: str
    commit: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class Symbol:
    qualname: str
    kind: str  # module | class | function | method
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Relation:
    kind: str  # IMPORTS | CALLS | INHERITS
    source: str
    target: str
    provenance: str  # parsed | inferred
    extractor: str


@dataclass(frozen=True)
class Gap:
    kind: str
    detail: str


@dataclass
class Page:
    items: list[Any] = field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    coverage: dict[str, Any] = field(default_factory=dict)


@dataclass
class FixStatus:
    state: str  # PRESENT | ABSENT | UNCERTAIN
    citations: list[Citation] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    reason: str = ""
