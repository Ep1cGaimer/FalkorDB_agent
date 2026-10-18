"""Per-repository configuration, loaded from repos/<name>.json."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REPOS_DIR = Path(__file__).resolve().parents[3] / "repos"
DEFAULT_RELEASE_NOTES = ["CHANGELOG*", "CHANGES*", "HISTORY*", "NEWS*", "RELEASE*",
                         "docs/changelog*", "docs/CHANGELOG*", "docs/history*", "docs/release*"]


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    path: str | Path
    revisions: list[str] = Field(default_factory=list)
    tag_pattern: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["python"])
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    release_notes: list[str] = Field(default_factory=lambda: list(DEFAULT_RELEASE_NOTES))

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME_RE.fullmatch(v):
            raise ValueError(f"invalid repository name {v!r}: must match {NAME_RE.pattern}")
        return v

    @field_validator("tag_pattern")
    @classmethod
    def _pattern(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v


def repos_dir() -> Path:
    """Directory of named configs: $RW_REPOS_DIR when set, else <project>/repos."""
    env = os.environ.get("RW_REPOS_DIR")
    return Path(env) if env else REPOS_DIR


def load_config(name_or_path: str | Path) -> RepoConfig:
    """Load a config from a .json file path, or by name from repos/<name>.json
    ($RW_REPOS_DIR/<name>.json when that variable is set)."""
    if isinstance(name_or_path, str) and NAME_RE.fullmatch(name_or_path):
        p = repos_dir() / f"{name_or_path}.json"
    else:
        p = Path(name_or_path)
    return RepoConfig(**json.loads(p.read_text(encoding="utf-8")))
