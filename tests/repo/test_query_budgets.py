"""Resource exhaustion must be visible and cannot support an absence conclusion."""
import concurrent.futures
import sys
import time
import socket
import threading

import pytest

from rw.repo.config import RepoConfig
from rw.repo.git import GitRepo
from rw.repo.index import index_repository
from rw.repo.investigate import investigate
from rw.repo.query import RepoQuery


@pytest.fixture
def corpus(make_repo, graph_name):
    path = make_repo()
    cfg = RepoConfig(name="budgets", path=path, revisions=["main"])
    report = index_repository(cfg, graph_name)
    return path, cfg, report


def test_graph_work_budget_returns_partial_not_empty_complete(corpus):
    from rw.repo.budget import ReadLimits
    path, cfg, report = corpus
    page = RepoQuery(report.graph_name, cfg.name, limits=ReadLimits(rows=1)).symbols("main")
    assert page.items == [] and page.truncated
    assert {g.kind for g in page.coverage["gaps"]} == {"RETRIEVAL_BUDGET_EXHAUSTED"}
    assert page.coverage["budget"]["exhausted"] == "rows"


def test_investigation_shares_budget_across_resolution_and_retrieval(corpus):
    path, cfg, report = corpus
    cfg = cfg.model_copy(update={"query_max_rows": 1})
    result = investigate(cfg.name, "main", "What does pkg.core depend on?", config=cfg,
                         graph_name=report.graph_name)
    assert not result.findings and not result.facts and result.answer is None
    assert result.unresolved and "RETRIEVAL_BUDGET_EXHAUSTED" in {g.kind for g in result.gaps}
    assert result.retrieval_budget["exhausted"] == "rows"


def test_git_process_is_terminated_at_shared_deadline(tmp_path, monkeypatch):
    from rw.repo.budget import BudgetExhausted, ReadLimits, read_scope
    git = GitRepo(tmp_path)
    monkeypatch.setattr(git, "_command", lambda *args: [sys.executable, "-c", "import time; time.sleep(5)"])
    started = time.monotonic()
    with read_scope(ReadLimits(seconds=0.15)):
        with pytest.raises(BudgetExhausted):
            git._proc("deliberately-slow-test-process")
    assert time.monotonic() - started < 2


def test_exhausted_request_does_not_poison_another_or_next_request(corpus):
    from rw.repo.budget import ReadLimits
    path, cfg, report = corpus
    def run(rows):
        return RepoQuery(report.graph_name, cfg.name, limits=ReadLimits(rows=rows)).symbols("main")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        low, normal = list(pool.map(run, [1, 250000]))
    assert low.truncated and not low.items
    assert normal.items and not normal.truncated
    assert run(250000).items


def test_source_byte_budget_cannot_leave_cited_findings(corpus):
    path, cfg, report = corpus
    cfg = cfg.model_copy(update={"query_max_source_bytes": 1})
    result = investigate(cfg.name, "main", "Where is pkg.core.Engine defined?", config=cfg,
                         graph_name=report.graph_name)
    assert not result.findings and not result.citations
    assert "RETRIEVAL_BUDGET_EXHAUSTED" in {g.kind for g in result.gaps}
    assert result.retrieval_budget["exhausted"] == "source_bytes"


def test_unresponsive_database_cannot_wait_without_a_deadline(corpus, monkeypatch):
    path, cfg, report = corpus
    cfg = cfg.model_copy(update={"query_timeout_seconds": 0.15})
    stop = threading.Event()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(2)
    def stall():
        try:
            connection, _ = server.accept()
            with connection:
                stop.wait(2)
        finally:
            server.close()
    thread = threading.Thread(target=stall, daemon=True)
    thread.start()
    monkeypatch.setenv("RW_FALKORDB_PORT", str(server.getsockname()[1]))
    started = time.monotonic()
    try:
        result = investigate(cfg.name, "main", "List symbols", config=cfg, graph_name=report.graph_name)
        assert time.monotonic() - started < 1.5
        assert not result.findings and result.unresolved
        assert result.retrieval_budget["exhausted"] == "seconds"
    finally:
        stop.set()
        thread.join(timeout=3)


def test_server_timeout_does_not_return_an_empty_complete_page(corpus):
    from rw.repo.budget import BudgetExhausted, ReadLimits, read_scope
    from rw.repo.query import EvidenceError
    path, cfg, report = corpus
    q = RepoQuery(report.graph_name, cfg.name)
    with read_scope(ReadLimits(seconds=0.03)):
        with pytest.raises((BudgetExhausted, EvidenceError)):
            q._q("UNWIND range(0, 100000000) AS x RETURN sum(x)")
