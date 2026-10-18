"""Regression coverage derived from the independently supplied goal-branch audit.

These are development regressions, not fresh held-out acceptance measurements.
"""
from dataclasses import asdict

import pytest

from rw import graph as G
from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.investigate import investigate
from rw.repo.query import RepoQuery
from .conftest import git, write


@pytest.fixture
def indexed(tmp_path, graph_name):
    repo = tmp_path / "recovery repo Δ"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "pkg/__init__.py", "from .util import helper\n")
    write(repo, "pkg/util.py", "def helper():\n    return 1\n\ndef other():\n    return 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    cfg = RepoConfig(name="recovery", path=repo, revisions=["HEAD"])
    index_repository(cfg, graph_name)
    return repo, cfg, graph_name, RepoQuery(graph_name, cfg.name)


def test_cursor_rejects_changed_query_and_new_publication(indexed):
    repo, cfg, name, q = indexed
    cursor = q.symbols("HEAD", limit=1).next_cursor
    assert cursor
    with pytest.raises(ValueError, match="invalid cursor"):
        q.symbols("HEAD", "helper", cursor=cursor)
    with pytest.raises(ValueError, match="invalid cursor"):
        q.dependencies("HEAD", "pkg", cursor=cursor)
    index_repository(cfg, name)  # even unchanged bytes publish a new view
    with pytest.raises(ValueError, match="invalid cursor"):
        q.symbols("HEAD", limit=1, cursor=cursor)


def test_revision_pages_and_api_listing_bind_current_publication(indexed, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from rw.api import create_app
    repo, cfg, name, q = indexed
    for i in range(2):
        write(repo, f"added{i}.py", f"VALUE = {i}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"add revision {i}")
    report = index_repository(cfg, name)
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / f"{cfg.name}.json").write_text(cfg.model_dump_json())
    monkeypatch.setenv("RW_REPOS_DIR", str(configs))
    monkeypatch.setattr("rw.repo.index.graph_name_for", lambda config: name)
    with TestClient(create_app(db_path=tmp_path / "unused.sqlite")) as client:
        first = client.get(f"/api/repos/{cfg.name}/revisions?limit=1").json()
        assert len(first["items"]) == 1 and first["coverage"]["total"] == 3
        assert first["coverage"]["generation"] == report.import_run_id
        cursor = first["next_cursor"]
        second = client.get(f"/api/repos/{cfg.name}/revisions", params={"limit": 2, "cursor": cursor}).json()
        assert len({item["sha"] for item in first["items"] + second["items"]}) == 3
        found = client.post(f"/api/repos/{cfg.name}/investigate",
                            json={"revision": "HEAD", "question": "List symbols"}).json()
        assert found["index_generation"] == report.import_run_id
        index_repository(cfg, name)
        assert client.get(f"/api/repos/{cfg.name}/revisions", params={"cursor": cursor}).status_code == 422
        G.connect().select_graph(name).query("MATCH (r:Repository) SET r.status='FAILED'")
        entry = client.get("/api/repos").json()[0]
        assert entry["import_status"] == "FAILED" and entry["revisions"] == []


def test_cached_query_refreshes_after_update(indexed):
    repo, cfg, name, q = indexed
    assert q.dependencies("HEAD", "pkg").items[0].target == "pkg.util.helper"
    write(repo, "pkg/__init__.py", "from .util import other\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change import")
    index_repository(cfg, name)
    assert {i.target for i in q.dependencies("HEAD", "pkg").items} == {"pkg.util.other"}


def test_failed_reextraction_retry_restores_exact_results(indexed, monkeypatch):
    import rw.repo.index as I
    from rw.repo.adapters import ADAPTERS
    repo, cfg, name, q = indexed
    before = [(i.qualname, asdict(i.citation)) for i in q.symbols("HEAD").items]
    original = I._write

    def crash_after_delete(graph, cypher, rows):
        original(graph, cypher, rows)
        if "DETACH DELETE s" in cypher and rows:
            raise RuntimeError("crashed after symbol deletion")

    with monkeypatch.context() as m:
        m.setattr(type(ADAPTERS["python"]), "version", "new-test-version")
        m.setattr(I, "_write", crash_after_delete)
        with pytest.raises(RuntimeError, match="crashed"):
            index_repository(cfg, name)
    assert not q.symbols("HEAD").items
    index_repository(cfg, name)  # original extractor version, not the failed trial's version
    assert [(i.qualname, asdict(i.citation)) for i in q.symbols("HEAD").items] == before


def test_conflicting_writer_is_rejected_and_reads_expose_incomplete(indexed, monkeypatch):
    import rw.repo.index as I
    repo, cfg, name, q = indexed
    lock = G.connect().connection.lock(f"rw:repo-import:{name}", timeout=120)
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="already in progress"):
            index_repository(cfg, name)
    finally:
        lock.release()
    original, observed = I._write, []

    def observe(graph, cypher, rows):
        if rows and not observed:
            page = q.symbols("HEAD")
            assert not page.items
            assert {g.kind for g in page.coverage["gaps"]} == {"INCOMPLETE_IMPORT"}
            observed.append(True)
        return original(graph, cypher, rows)

    monkeypatch.setattr(I, "_write", observe)
    index_repository(cfg, name)
    assert observed and q.symbols("HEAD").items


def test_relative_targets_survive_nested_packages_calls_and_identical_non_source(indexed):
    repo, cfg, name, q = indexed
    content = "from ..util import helper\n\ndef run():\n    return helper()\n"
    for package in ("a", "b"):
        write(repo, f"{package}/nested/code.py", content)
        write(repo, f"{package}/util.py", "def helper():\n    return 1\n")
    write(repo, "0-not-source.txt", content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "duplicate source in different contexts")
    index_repository(cfg, name)
    for package in ("a", "b"):
        page = q.dependencies("HEAD", f"{package}.nested.code.run")
        assert {i.target for i in page.items} == {f"{package}.util.helper"}
    assert all(i.path != "0-not-source.txt" for i in q.symbols("HEAD").items)


def test_malformed_source_never_proves_symbol_absence(indexed):
    repo, cfg, name, q = indexed
    write(repo, "broken.py", "def hidden(:\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unparseable source")
    index_repository(cfg, name)
    entry = q.symbol_history("broken.hidden", ["HEAD"])[0]
    assert entry.present is None and entry.gap.kind == "INCOMPLETE_COVERAGE"
    result = investigate(cfg.name, "HEAD", "When did broken.hidden appear?", config=cfg, graph_name=name)
    assert any(g.kind == "INCOMPLETE_COVERAGE" for g in result.gaps)
    assert "absent at" not in " ".join(f.summary for f in result.findings)


def test_colliding_qualified_names_require_path_clarification(indexed):
    repo, cfg, name, q = indexed
    write(repo, "pkg.py", "from other import helper\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "module and package collision")
    index_repository(cfg, name)
    result = investigate(cfg.name, "HEAD", "What does pkg depend on?", config=cfg, graph_name=name)
    assert not result.findings and any(g.kind == "ambiguous_symbol" for g in result.gaps)
    page = q.dependencies("HEAD", "pkg")
    assert not page.items and any(g.kind == "AMBIGUOUS_SYMBOL" for g in page.coverage["gaps"])
    entry = q.symbol_history("pkg", ["HEAD"])[0]
    assert entry.present is None and entry.gap.kind == "AMBIGUOUS_SYMBOL"


def test_deletion_only_fix_is_rechecked_at_current_tree(indexed):
    repo, cfg, name, q = indexed
    vulnerable = "def unsafe():\n    return True\n\ndef normal():\n    return False\n"
    write(repo, "rules.py", vulnerable)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "baseline")
    write(repo, "rules.py", "def normal():\n    return False\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "remove unsafe bypass")
    fix = git(repo, "rev-parse", "HEAD")
    write(repo, "rules.py", vulnerable)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "restore bypass")
    index_repository(cfg, name)
    assert q.fix_status(fix, fix).state == "PRESENT"
    assert q.fix_status("HEAD", fix).state == "ABSENT"


def test_recovery_after_each_persistence_boundary(indexed, monkeypatch, tmp_path, request):
    """Inject after actual server writes, including final publication, then retry normally.

    This deliberately exercises ambiguous acknowledgement: a write may have committed even
    though its caller observed an exception. A retry must still produce one logical view.
    """
    import json
    from rw.repo.adapters import ADAPTERS
    repo, cfg, name, q = indexed
    db = G.connect()
    graph_type = type(db.select_graph(name))
    original = graph_type.query
    trace = []

    def mutates(cypher):
        return not cypher.startswith("CREATE INDEX") and any(
            token in cypher for token in (" SET ", "CREATE ", "MERGE ", "DELETE "))

    def capture(self, cypher, *args, **kwargs):
        result = original(self, cypher, *args, **kwargs)
        if mutates(cypher):
            trace.append(cypher)
        return result

    def view():
        fresh = RepoQuery(name, cfg.name)
        sha, gap = fresh.resolve("HEAD")
        assert gap is None
        files, syms, rels = fresh._snapshot(sha)
        return files, [asdict(s) for s in syms], sorted(tuple(r[:-1]) for r in rels)

    expected = view()
    with monkeypatch.context() as m:
        m.setattr(type(ADAPTERS["python"]), "version", "boundary-capture")
        m.setattr(graph_type, "query", capture)
        index_repository(cfg, name)
    assert len(trace) >= 10
    request.node.user_properties.append(("injected_persistence_boundaries", len(trace)))
    attempts = []
    for boundary in range(1, len(trace) + 1):
        count = 0
        fired = False

        def fail(self, cypher, *args, **kwargs):
            nonlocal count, fired
            result = original(self, cypher, *args, **kwargs)
            if mutates(cypher):
                count += 1
                if count == boundary:
                    fired = True
                    raise RuntimeError("injected acknowledgement failure")
            return result

        with monkeypatch.context() as m:
            m.setattr(type(ADAPTERS["python"]), "version", f"boundary-{boundary}")
            with m.context() as crash:
                crash.setattr(graph_type, "query", fail)
                with pytest.raises(RuntimeError, match="injected"):
                    index_repository(cfg, name)
            assert fired
            current, gap = RepoQuery(name, cfg.name).resolve("HEAD")
            if gap is None:  # final publication committed before acknowledgement failed
                assert view() == expected
            index_repository(cfg, name)
            assert view() == expected
            duplicate = db.select_graph(name).ro_query(
                "MATCH (c:Commit)-[f:HAS_FILE]->() WITH c.sha AS sha, f.path AS path, count(f) AS n "
                "WHERE n > 1 RETURN sha, path, n").result_set
            assert not duplicate
        attempts.append({"boundary": boundary, "query": trace[boundary - 1], "recovered": True})
    (tmp_path / "persistence-recovery.json").write_text(json.dumps(attempts, indent=2))


def test_writer_cannot_mutate_after_lease_ownership_changes(indexed, monkeypatch):
    import rw.repo.index as I
    from rw.repo.adapters import ADAPTERS
    repo, cfg, name, q = indexed
    db = G.connect()
    key = f"rw:repo-import:{name}"
    original = I._write
    changed = False

    def replace_owner(graph, cypher, rows):
        nonlocal changed
        if "DETACH DELETE s" in cypher and rows and not changed:
            changed = True
            # Simulate a paused writer waking after another process acquired its expired lease.
            db.connection.set(key, "different-owner", xx=True, ex=120)
        return original(graph, cypher, rows)

    try:
        with monkeypatch.context() as m:
            m.setattr(type(ADAPTERS["python"]), "version", "lost-lease")
            m.setattr(I, "_write", replace_owner)
            with pytest.raises(RuntimeError, match="lease lost"):
                index_repository(cfg, name)
        assert changed
        assert db.select_graph(name).ro_query("MATCH (:Blob)-[:DEFINES]->(s:Symbol) RETURN count(s)").result_set[0][0] > 0
        assert not q.symbols("HEAD").items
    finally:
        assert db.connection.get(key) == "different-owner"
        db.connection.delete(key)  # release the simulated second writer
    index_repository(cfg, name)
    assert q.symbols("HEAD").items


def test_process_crash_expires_lease_and_retry_recovers(indexed, tmp_path, request):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path
    repo, cfg, name, q = indexed
    expected = [(i.qualname, asdict(i.citation)) for i in q.symbols("HEAD").items]
    marker = tmp_path / "deleted-symbols"
    script = "\n".join([
        "import threading", "from pathlib import Path", "import rw.repo.index as I",
        "from rw.repo.config import RepoConfig", "from rw.repo.adapters import ADAPTERS",
        "I.IMPORT_LEASE_SECONDS = 2", "ADAPTERS['python'].version = 'process-crash'",
        "original = I._write", "def crash(graph, cypher, rows):",
        "    original(graph, cypher, rows)",
        "    if 'DETACH DELETE s' in cypher and rows:",
        f"        Path({str(marker)!r}).touch()", "        threading.Event().wait()",
        "I._write = crash",
        f"I.index_repository(RepoConfig.model_validate_json({cfg.model_dump_json()!r}), {name!r})",
    ])
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")})
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists() and process.poll() is None, process.communicate(timeout=1)
        process.kill()
        process.communicate(timeout=5)
        assert not q.symbols("HEAD").items
        connection = G.connect().connection
        deadline = time.monotonic() + 5
        while connection.exists(f"rw:repo-import:{name}") and time.monotonic() < deadline:
            time.sleep(0.02)
        started = time.monotonic()
        index_repository(cfg, name)
        assert [(i.qualname, asdict(i.citation)) for i in q.symbols("HEAD").items] == expected
        request.node.user_properties.append(("process_crash_point", "after committed symbol deletion"))
        request.node.user_properties.append(("test_lease_seconds", 2))
        request.node.user_properties.append(("retry_seconds", round(time.monotonic() - started, 3)))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
