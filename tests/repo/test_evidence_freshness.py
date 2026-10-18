"""Source/graph ablation regressions derived from T1/T4/T9; no held-out score claims."""
import json
from pathlib import Path

import pytest

from rw import graph as G
from rw.repo.config import RepoConfig, load_config
from rw.repo.git import GitRepo
from rw.repo.index import index_repository
from rw.repo.investigate import investigate
from rw.repo.query import RepoQuery


@pytest.fixture
def indexed(make_repo, graph_name):
    path = make_repo(files={
        "pkg/core.py": "from .util import helper\n\ndef run():\n    return helper(1)\n",
        "pkg/util.py": "def helper(x):\n    return x + 1\n",
    })
    cfg = RepoConfig(name="freshness", path=path, revisions=["main"])
    report = index_repository(cfg, graph_name)
    return path, cfg, report, RepoQuery(graph_name, cfg.name), G.connect().select_graph(graph_name)


def test_relative_configuration_is_independent_of_process_cwd(tmp_path, monkeypatch, make_repo):
    repo = make_repo("source repo Δ")
    directory = tmp_path / "configuration"
    directory.mkdir()
    config = directory / "source.json"
    config.write_text(json.dumps({"name": "source", "path": "../source repo Δ", "revisions": ["main"]}))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    cfg = load_config(config)
    assert Path(cfg.path) == repo
    assert GitRepo(cfg.path).resolve("main") == GitRepo(repo).resolve("main")


def test_missing_repository_keeps_same_semantic_response_across_surfaces(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from rw.api import create_app
    from rw.repo.mcp import repo_investigate
    monkeypatch.setenv("RW_REPOS_DIR", str(tmp_path))
    expected = investigate("unconfigured", "HEAD", "List symbols").to_dict()
    assert expected == repo_investigate("unconfigured", "HEAD", "List symbols")
    with TestClient(create_app(db_path=tmp_path / "unused.sqlite")) as client:
        response = client.post("/api/repos/unconfigured/investigate",
                               json={"revision": "HEAD", "question": "List symbols"})
    assert response.status_code == 404
    assert response.json() == expected


def test_database_selection_is_explicit_and_environment_configurable(monkeypatch):
    monkeypatch.setenv("RW_FALKORDB_HOST", "127.0.0.2")
    monkeypatch.setenv("RW_FALKORDB_PORT", "16379")
    monkeypatch.setattr(G.falkordb, "FalkorDB", lambda **kwargs: kwargs)
    configured = G.connect()
    assert configured["host"] == "127.0.0.2" and configured["port"] == 16379
    explicit = G.connect("127.0.0.3", 16380)
    assert explicit["host"] == "127.0.0.3" and explicit["port"] == 16380


def test_graph_edge_ablation_cannot_reuse_a_previous_query_view(indexed):
    path, cfg, report, q, graph = indexed
    before = q.dependencies("v1.0.0", "pkg.core")
    assert {i.target for i in before.items} == {"pkg.util.helper"}
    graph.query("MATCH (s:Symbol {qualname:'pkg.core'})-[e:IMPORTS]->() DELETE e")
    after = q.dependencies("v1.0.0", "pkg.core")
    assert not after.items or after.coverage.get("gaps")


@pytest.mark.parametrize("mutation,kind", [
    ("MATCH (b:Blob)-[:DEFINES]->(:Symbol {qualname:'pkg.core.run'}) SET b.extracted_by='python@old'", "STALE_EXTRACTION"),
    ("MATCH (b:Blob)-[:DEFINES]->(:Symbol {qualname:'pkg.core.run'}) SET b.content_hash='invalid-content-hash'", "STALE_SOURCE"),
    ("MATCH (s:Symbol {qualname:'pkg.core.run'}) SET s.text_hash='invalid-span-hash'", "STALE_SOURCE"),
])
def test_stale_source_or_extraction_cannot_support_an_answer(indexed, mutation, kind):
    path, cfg, report, q, graph = indexed
    assert q.symbols("v1.0.0", "run").items
    graph.query(mutation)
    page = q.symbols("v1.0.0", "run")
    assert not page.items and kind in {g.kind for g in page.coverage["gaps"]}
    result = investigate(cfg.name, "v1.0.0", "Where is run defined?", config=cfg, graph_name=report.graph_name)
    assert not result.findings and kind in {g.kind for g in result.gaps}


def test_missing_source_clone_is_not_reported_as_verified_citation(indexed, tmp_path):
    path, cfg, report, q, graph = indexed
    sha = GitRepo(path).resolve("v1.0.0")
    assert q.symbols(sha, "run").items
    path.rename(tmp_path / "moved-source")
    page = q.symbols(sha, "run")
    assert not page.items and "MISSING_SOURCE" in {g.kind for g in page.coverage["gaps"]}


def test_stale_relationship_does_not_turn_into_a_definitive_empty_dependency_answer(indexed):
    path, cfg, report, q, graph = indexed
    graph.query("MATCH (:Symbol {qualname:'pkg.core'})-[e:IMPORTS]->() SET e.extractor='python@stale'")
    page = q.dependencies("v1.0.0", "pkg.core")
    assert not page.items and "STALE_EXTRACTION" in {g.kind for g in page.coverage["gaps"]}
    result = investigate(cfg.name, "v1.0.0", "What does pkg.core depend on?", config=cfg, graph_name=report.graph_name)
    assert not result.findings and not result.facts and result.unresolved
    assert "STALE_EXTRACTION" in {g.kind for g in result.gaps}
