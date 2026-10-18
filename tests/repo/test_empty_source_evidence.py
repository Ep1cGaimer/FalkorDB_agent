"""Zero-byte Git files have membership evidence, never physical line 1."""
import hashlib

from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def test_empty_module_release_note_and_change_citations_have_no_lines(make_repo, git_cmd, graph_name):
    repo = make_repo(files={"pkg/empty.py": "", "CHANGELOG.md": ""})
    (repo / "pkg/empty.py").write_text("VALUE = 1\n")
    git_cmd(repo, "add", ".")
    git_cmd(repo, "commit", "-qm", "populate formerly empty module")
    cfg = RepoConfig(name="empty-evidence", path=repo, revisions=["HEAD"])
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    symbols = q.symbols("v1.0.0", name="pkg.empty")
    assert not symbols.coverage.get("gaps") and len(symbols.items) == 1
    notes = q.release_notes("v1.0.0")
    assert not notes.coverage.get("gaps") and len(notes.items) == 1
    changes = q.changes_between("v1.0.0", "HEAD")
    changed = next(i for i in changes.items if i.path == "pkg/empty.py")
    for citation in (symbols.items[0].citation, notes.items[0].citation, changed.old_citation):
        assert citation.start_line is None and citation.end_line is None
        assert citation.content_hash == hashlib.sha256(b"").hexdigest()
    assert notes.items[0].text == ""
    assert (changed.citation.start_line, changed.citation.end_line) == (1, 1)


def test_deletion_only_fix_retains_empty_file_membership_without_fake_span(make_repo, git_cmd, graph_name):
    repo = make_repo(files={"pkg/empty.py": "UNSAFE = True\n"})
    (repo / "pkg/empty.py").write_bytes(b"")
    git_cmd(repo, "add", ".")
    git_cmd(repo, "commit", "-qm", "remove unsafe content leaving empty module")
    fix = git_cmd(repo, "rev-parse", "HEAD")
    cfg = RepoConfig(name="empty-fix", path=repo, revisions=[fix])
    index_repository(cfg, graph_name)
    result = RepoQuery(graph_name, cfg.name).fix_status(fix, fix)
    assert result.state == "PRESENT" and not result.gaps
    citation = next(c for c in result.citations if c.path == "pkg/empty.py")
    assert citation.start_line is None and citation.end_line is None
