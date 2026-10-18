"""Independent adversarial audit: assertions describe required, correct behavior.

The fix test uses real Git and FalkorDB. The pagination test uses a faithful
10,000-row result ceiling to exercise the boundary without importing 10,001 files.
No test executes code from the indexed repository.
"""
from types import SimpleNamespace
import os
import subprocess
import uuid

import pytest

from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def _git(repo, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", "-c", "user.name=Audit", "-c", "user.email=audit@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(repo), *args],
        env=env, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo, text, message):
    (repo / "rules.py").write_text(text, encoding="utf-8")
    _git(repo, "add", "rules.py")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def audit_graph():
    from rw import graph as G
    db = G.connect()
    name = "audit_" + uuid.uuid4().hex
    yield db, name
    db.select_graph(name).delete()


def test_mixed_fix_does_not_pass_when_its_deleted_vulnerable_code_returns(tmp_path, audit_graph):
    repo = tmp_path / "mixed-fix"
    repo.mkdir()
    _git(repo, "init", "-q")
    original = (
        "def unsafe_override(value):\n"
        "    return True\n\n\n"
        "def allowed(value):\n"
        "    return bool(value)\n"
    )
    _commit(repo, original, "vulnerable baseline")
    fixed = (
        "def allowed(value):\n"
        "    if value is None:\n"
        "        return False\n"
        "    return bool(value)\n"
    )
    fix_sha = _commit(repo, fixed, "remove unsafe bypass and reject missing values")
    # The addition remains intact but the separately deleted bypass returns.
    restored = original.split("def allowed", 1)[0] + fixed
    current_sha = _commit(repo, restored, "accidentally restore bypass")
    db, name = audit_graph
    cfg = RepoConfig(name="mixed-fix", path=repo, revisions=["HEAD"])
    assert index_repository(cfg, graph_name=name, db=db).status == "COMPLETE"
    verdict = RepoQuery(name, cfg.name, db=db).fix_status(current_sha, fix_sha)
    assert verdict.state != "PRESENT", (
        "The fix's deletion was undone; intact added lines cannot prove the whole fix present. "
        f"Got {verdict.state}: {verdict.reason}"
    )


class _CappedNoteGraph:
    """Minimal graph transport with the documented FalkorDB result ceiling."""

    def __init__(self, rows, cap=10_000):
        self.rows = rows
        self.cap = cap

    def ro_query(self, cypher, params, timeout=None):
        if "HAS_NOTE" not in cypher:
            return SimpleNamespace(result_set=[])
        if "count(" in cypher.lower():
            return SimpleNamespace(result_set=[[len(self.rows)]])
        offset = params.get("_o", params.get("o", 0))
        limit = params.get("_l", params.get("l", self.cap))
        return SimpleNamespace(result_set=self.rows[offset:offset + min(limit, self.cap)])


def test_release_notes_total_must_not_silently_equal_server_row_ceiling(monkeypatch):
    rows = [[f"NOTE-{i:05d}.md", "h"] for i in range(10_001)]
    q = object.__new__(RepoQuery)
    q.repo = "notes"
    q.graph = _CappedNoteGraph(rows)
    monkeypatch.setattr(q, "resolve", lambda rev: ("a" * 40, None))
    monkeypatch.setattr(q, "_files", lambda sha: {})
    monkeypatch.setattr(q, "_blob", lambda sha: b"# Release notes\n")
    page = q.release_notes("a" * 40, limit=1)
    explicit_gap = any("TRUNCAT" in gap.kind.upper() for gap in page.coverage.get("gaps", []))
    assert page.coverage["total"] == len(rows) or explicit_gap, (
        "10,001 notes exist but the unpaged transport returned only 10,000; "
        f"the page presents total={page.coverage['total']} without a truncation gap"
    )


def test_first_containing_tag_search_does_not_silently_ignore_candidate_2001():
    from rw.repo.investigate import _fix_first_tag
    tags = [(f"v{i:04d}", f"commit-{i}", i) for i in range(2001)]
    q = SimpleNamespace(
        _q=lambda cypher: tags,
        _is_ancestor=lambda fix, sha: sha == "commit-2000",
    )
    result = _fix_first_tag(q, "fix-sha")
    assert result == "v2000", (
        "The first containing tag is candidate 2001. A silent 2,000-tag search ceiling "
        f"must not turn known positive evidence into {result!r}."
    )
