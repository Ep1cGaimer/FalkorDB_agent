"""Language adapter registry. Files with no adapter become coverage gaps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from rw.repo.model import Relation, Symbol


@dataclass
class Extraction:
    symbols: list[Symbol] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)


class Adapter(Protocol):
    language: str
    extensions: tuple[str, ...]
    version: str
    LIMITS: list[str]

    def extract(self, path: str, data: bytes) -> Extraction: ...


from rw.repo.adapters.python import PythonAdapter  # noqa: E402

ADAPTERS: dict[str, Adapter] = {a.language: a for a in (PythonAdapter(),)}
SUPPORTED_LANGUAGES = frozenset(ADAPTERS)


def adapter_for(path: str, languages: list[str] | None = None) -> Adapter | None:
    """The adapter for `path` (optionally restricted to `languages`), or None => coverage gap."""
    lower = path.lower()
    for lang, adapter in ADAPTERS.items():
        if languages is not None and lang not in languages:
            continue
        if lower.endswith(tuple(adapter.extensions)):
            return adapter
    return None
