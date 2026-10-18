"""MCP-facing wrapper for repository investigation; importable without the `mcp` package."""
from __future__ import annotations

from typing import Any

from rw.repo.investigate import investigate


def repo_investigate(repo: str, revision: str, question: str) -> dict[str, Any]:
    """Same workflow as the CLI/API: investigate(repo, revision, question).to_dict()."""
    return investigate(repo, revision, question).to_dict()
