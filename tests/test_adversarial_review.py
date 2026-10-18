"""Independent audit probes. Assertions describe the local T0–T11 contract.

Run from the reviewed checkout with PYTHONPATH=src. No application fixes here.
"""
import json
import subprocess
import uuid
from dataclasses import asdict

import pytest

from rw import graph as G
from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def git(path, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Audit", "-c", "user.email=audit@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(path), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def commit(path, files, message):
    for name, content in files.items():
        p = path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-qm", message)
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "repo with spaces — Δ"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    name = "audit-" + uuid.uuid4().hex[:12]
    graph = "rw_test_" + name.replace("-", "_")
    cfg = RepoConfig(name=name, path=str(path), revisions=["HEAD"], tag_pattern="^v")
    yield path, cfg, graph
    G.connect().select_graph(graph).delete()


def query(cfg, graph):
    return RepoQuery(graph, cfg.name)


def record(tmp_path, name, value):
    # Also print evidence into the captured pytest transcript/JUnit report.
    print(name, json.dumps(value, default=str, sort_keys=True))
    (tmp_path / (name + ".json")).write_text(json.dumps(value, default=str, indent=2))


def test_moved_tag_resolves_only_new_target(env, tmp_path):
    path, cfg, graph = env
    old = commit(path, {"a.py": "def a():\n    return 1\n"}, "initial")
    git(path, "tag", "v1")
    index_repository(cfg, graph)
    new = commit(path, {"a.py": "def a():\n    return 2\n"}, "update")
    git(path, "tag", "-f", "v1", new)
    index_repository(cfg, graph)
    q = query(cfg, graph)
    targets = q._q("MATCH (:Tag {name:'v1'})-[:POINTS_TO]->(c:Commit) RETURN c.sha")
    resolved, gap = q.resolve("v1")
    record(tmp_path, "moved_tag", dict(old=old, expected=new, actual=resolved, targets=targets, gap=gap))
    assert targets == [[new]] and resolved == new and gap is None


def test_deleted_tag_does_not_silently_resolve(env, tmp_path):
    path, cfg, graph = env
    commit(path, {"a.py": "def a():\n    return 1\n"}, "initial")
    git(path, "tag", "v1")
    index_repository(cfg, graph)
    git(path, "tag", "-d", "v1")
    index_repository(cfg, graph)
    resolved, gap = query(cfg, graph).resolve("v1")
    record(tmp_path, "deleted_tag", dict(resolved=resolved, gap=gap))
    assert resolved is None and gap is not None


def test_configuration_update_matches_clean_index(env, tmp_path):
    path, cfg, graph = env
    commit(path, {"keep.py": "def keep():\n    return 1\n",
                  "drop.py": "def drop():\n    return 2\n"}, "initial")
    index_repository(cfg, graph)
    narrowed = cfg.model_copy(update={"exclude": ["drop.py"]})
    index_repository(narrowed, graph)
    actual = sorted(x.qualname for x in query(cfg, graph).symbols("HEAD", limit=200).items)
    clean_graph = graph + "_clean"
    try:
        index_repository(narrowed, clean_graph)
        expected = sorted(x.qualname for x in query(cfg, clean_graph).symbols("HEAD", limit=200).items)
        record(tmp_path, "config_update", dict(incremental=actual, clean=expected))
        assert actual == expected
    finally:
        G.connect().select_graph(clean_graph).delete()


def test_cursor_is_bound_to_repository_and_revision(env, tmp_path):
    path, cfg, graph = env
    old = commit(path, {"a.py": "def a():\n    return 1\n\ndef b():\n    return 2\n"}, "initial")
    new = commit(path, {"a.py": "def a():\n    return 3\n\ndef c():\n    return 4\n"}, "update")
    index_repository(cfg, graph)
    q = query(cfg, graph)
    cursor = q.symbols(old, limit=1).next_cursor
    try:
        reused = q.symbols(new, limit=1, cursor=cursor)
    except ValueError:
        return
    record(tmp_path, "cross_revision_cursor", dict(cursor=cursor, from_revision=old,
           to_revision=new, result=asdict(reused)))
    assert any(g.kind == "INVALID_CURSOR" for g in reused.coverage.get("gaps", []))


def test_identical_content_preserves_relative_import_identity(env, tmp_path):
    path, cfg, graph = env
    commit(path, {"pkg_a/__init__.py": "from .util import helper\n",
                  "pkg_b/__init__.py": "from .util import helper\n",
                  "pkg_a/util.py": "def helper():\n    return 'a'\n",
                  "pkg_b/util.py": "def helper():\n    return 'b'\n"}, "initial")
    index_repository(cfg, graph)
    a = query(cfg, graph).dependencies("HEAD", "pkg_a", hops=1, limit=200)
    b = query(cfg, graph).dependencies("HEAD", "pkg_b", hops=1, limit=200)
    record(tmp_path, "relative_imports", dict(a=asdict(a), b=asdict(b)))
    assert {x.target for x in b.items} == {"pkg_b.util.helper"}
    assert {x.target for x in a.items} == {"pkg_a.util.helper"}


def test_parse_failure_is_visible_in_retrieval_coverage(env, tmp_path):
    path, cfg, graph = env
    commit(path, {"broken.py": "def hidden(:\n    pass\n"}, "malformed source")
    report = index_repository(cfg, graph)
    page = query(cfg, graph).symbols("HEAD", "hidden")
    record(tmp_path, "parse_gap", dict(extraction_errors=report.extraction_errors, page=asdict(page)))
    assert report.extraction_errors
    assert any("parse" in (g.kind + g.detail).lower() or "extract" in (g.kind + g.detail).lower()
               for g in page.coverage.get("gaps", []))


def test_failed_reextraction_does_not_corrupt_complete_snapshot(env, tmp_path, monkeypatch):
    import rw.repo.index as I
    from rw.repo.adapters import ADAPTERS
    path, cfg, graph = env
    sha = commit(path, {"a.py": "def a():\n    return 1\n"}, "initial")
    index_repository(cfg, graph)
    before = [x.qualname for x in query(cfg, graph).symbols(sha).items]
    original = I._write
    fired = []

    def fail_after_delete(g, cypher, rows):
        original(g, cypher, rows)
        if "DETACH DELETE s" in cypher and rows:
            fired.append(True)
            raise RuntimeError("audit fault immediately after deleting old symbols")

    with monkeypatch.context() as m:
        m.setattr(type(ADAPTERS["python"]), "version", "audit-new-version")
        m.setattr(I, "_write", fail_after_delete)
        with pytest.raises(RuntimeError, match="audit fault"):
            index_repository(cfg, graph)
    q = query(cfg, graph)
    after = q.symbols(sha)
    resolved, gap = q.resolve(sha)
    record(tmp_path, "failed_reextraction", dict(fault_fired=bool(fired), before=before,
           after=asdict(after), resolved=resolved, gap=gap))
    assert fired
    assert gap is not None or [x.qualname for x in after.items] == before


def test_empty_answerable_retrieval_precision_is_zero():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
    from repo_eval_common import evidence_scores
    q = {"revision": "HEAD", "expected_citations": [
        {"path": "a.py", "start_line": 1, "end_line": 2, "revision": "HEAD"}]}
    recall, precision = evidence_scores([], q, None)
    print("empty_retrieval", dict(recall=recall, precision=precision))
    assert recall == 0 and precision == 0


def test_fabricated_citation_cannot_pass_grounding():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
    from repo_eval_common import grounded
    q = {"category": "dependencies"}
    cits = [{"valid": True, "requested_revision_match": True},
            {"valid": False, "requested_revision_match": True}]
    assert not grounded(q, True, 1.0, cits)
