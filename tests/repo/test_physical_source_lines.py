"""Source spans and fix evidence use physical LF lines, including Unicode text."""
import hashlib

from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def test_symbol_hash_and_change_identity_ignore_unicode_separators_before_definition(
    make_repo, git_cmd, graph_name,
):
    text = "label = 'left\u2028right'\ndef stable():\n    return 1\n"
    repo = make_repo(files={"pkg/unicode.py": text})
    cfg = RepoConfig(name="physical-lines", path=repo, revisions=["v1.0.0", "HEAD"])
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    sha, gap = q.resolve("v1.0.0")
    assert gap is None
    symbols = q.symbols(sha, name="stable")
    assert len(symbols.items) == 1
    citation = symbols.items[0].citation
    assert (citation.start_line, citation.end_line) == (2, 3)
    raw_hash = hashlib.sha256(b"def stable():\n    return 1").hexdigest()
    rows = q._q("MATCH (:Commit {sha:$s})-[:HAS_FILE]->(:Blob)-[:DEFINES]->(f:Symbol) "
                "WHERE f.qualname='pkg.unicode.stable' RETURN f.text_hash", {"s": sha})
    assert rows == [[raw_hash]]
    (repo / "pkg/unicode.py").write_text(text.replace("right", "changed"))
    git_cmd(repo, "add", ".")
    git_cmd(repo, "commit", "-qm", "only module literal changes")
    index_repository(cfg, graph_name)
    changes = q.changes_between(sha, "HEAD")
    item = next(i for i in changes.items if i.path == "pkg/unicode.py")
    assert "pkg.unicode.stable" not in item.symbols_modified


def test_release_note_citation_and_text_keep_unicode_inside_one_physical_line(make_repo, graph_name):
    note = "# Changelog\n\n## 1.0.0\n- left\u2028right\n- final bullet\n"
    repo = make_repo(files={"pkg/ok.py": "def ok():\n    return 1\n", "CHANGELOG.md": note})
    cfg = RepoConfig(name="physical-notes", path=repo, revisions=["v1.0.0"])
    index_repository(cfg, graph_name)
    page = RepoQuery(graph_name, cfg.name).release_notes("v1.0.0")
    assert not page.coverage.get("gaps") and len(page.items) == 1
    item = page.items[0]
    assert item.citation.end_line == 5
    assert "- left\u2028right" in item.text


def test_fix_patch_keeps_unicode_in_added_and_removed_lines(make_repo, git_cmd, graph_name):
    repo = make_repo(files={"pkg/unicode.py": "label = 'old\u2028value'\n"})
    (repo / "pkg/unicode.py").write_text("label = 'new\u2028value'\n")
    git_cmd(repo, "add", ".")
    git_cmd(repo, "commit", "-qm", "fix unicode string")
    fix = git_cmd(repo, "rev-parse", "HEAD")
    cfg = RepoConfig(name="physical-fix", path=repo, revisions=[fix])
    index_repository(cfg, graph_name)
    status = RepoQuery(graph_name, cfg.name).fix_status(fix, fix)
    assert status.state == "PRESENT"
    cite = next(c for c in status.citations if c.path == "pkg/unicode.py")
    assert (cite.start_line, cite.end_line) == (1, 1)


def test_normal_retry_migrates_legacy_source_spans_before_reuse(make_repo, graph_name):
    from rw.repo.source import LINE_SCHEMA
    repo = make_repo(files={"pkg/unicode.py": "label = 'left\u2028right'\ndef stable():\n    return 1\n"})
    cfg = RepoConfig(name="physical-migration", path=repo, revisions=["v1.0.0"])
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    # Simulate an old index with the old splitter's metadata and a valid extractor
    # completion marker. Migration must not reuse that metadata just by blob ID.
    q.graph.query("MATCH (b:Blob) SET b.line_schema=null")
    q.graph.query("MATCH (s:Symbol) WHERE s.qualname='pkg.unicode.stable' SET s.text_hash='legacy-wrong-hash'")
    rejected = q.symbols("v1.0.0", name="stable")
    assert not rejected.items and any(g.kind == "STALE_SOURCE" for g in rejected.coverage["gaps"])
    report = index_repository(cfg, graph_name)
    assert report.blobs_new > 0
    assert q.symbols("v1.0.0", name="stable").items
    assert q._q("MATCH (b:Blob) WHERE b.line_schema IS NULL OR b.line_schema <> $schema RETURN count(b)",
                {"schema": LINE_SCHEMA}) == [[0]]
    again = index_repository(cfg, graph_name)
    assert again.blobs_new == 0 and again.blobs_reused > 0


def test_physical_source_line_contract_handles_empty_crlf_and_control_content():
    from rw.repo.source import source_lines
    assert source_lines("") == []
    assert source_lines("\n") == [""]
    assert source_lines("one\r\ntwo\r\n") == ["one", "two"]
    assert source_lines("one\r") == ["one\r"]
    assert source_lines("one\u2028two\u0085three\vfour\nlast") == ["one\u2028two\u0085three\vfour", "last"]
