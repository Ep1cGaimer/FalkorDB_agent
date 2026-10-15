"""Minimal .env loader for the scripts (no dependency, no key ever printed).

`.env` holds local secrets (for example ``GROQ_API_KEY``) and is git-ignored. Loading is additive:
a variable that is already set in the process environment always wins, so a shell override is
never silently replaced by the file. Invalid lines are skipped rather than fatal.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_env(path: Path = DEFAULT_ENV_PATH) -> None:
    """Set os.environ from `KEY=VALUE` lines in `path`, without overriding existing variables.

    Blank lines and `#` comments are ignored; optional surrounding single or double quotes are
    stripped; `export KEY=VALUE` is accepted. Values are never logged or returned.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return  # no .env (or unreadable): nothing to load
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
