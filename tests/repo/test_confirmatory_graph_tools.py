"""Real graph/source-corpus parity and failure boundaries on synthetic histories."""
import importlib
from pathlib import Path

import pytest

from rw.repo.config import RepoConfig
from rw.repo.git import GitRepo
from rw.repo.index import index_repository


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "evals"))
    return (importlib.import_module("confirmatory.corpus_export"),
            importlib.import_module("confirmatory.plaintext_tools"),
            importlib.import_module("confirmatory.graph_tools"),
            importlib.import_module("confirmatory.tool_budget"))


@pytest.fixture
def common_corpus(make_repo, tmp_path, modules):
    exporter, plain, _, _ = modules
    repo = make_repo(files={
        "pkg/core.py": "from .util import helper\n\ndef run():\n    return helper(1)\n",
        "pkg/util.py": "def helper(x):\n    return x + 1\n",
        "pkg/empty.py": "",
        "setup.py": "ROOT_METADATA = True\n",
        "nested/setup.py": "EXTRA_EVIDENCE_MUST_BE_EXCLUDED = True\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- first\n",
    })
    root = GitRepo(repo).resolve("v1.1.0")
    out = tmp_path / "common-export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "graph-development",
        "roots": [root], "include": ["pkg/*.py", "setup.py", "CHANGELOG.md"], "exclude": []}, out)
    return repo, plain.PlaintextTools(out)


@pytest.fixture
def arm(common_corpus, graph_name, modules):
    repo, raw = common_corpus
    _, _, graph, _ = modules
    cfg = graph.config_for_export(raw, repo)
    index_repository(cfg, graph_name)
    instance = graph.GraphTools(raw, graph_name)
    receipt = instance.prepare()
    return instance, receipt


def test_real_graph_has_identical_historical_source_and_ordered_parent_memberships(arm):
    instance, receipt = arm
    assert receipt["commits_checked"] == 3 and receipt["ordered_parent_edges_checked"] == 2
    assert receipt["memberships_checked"] > 0
    assert receipt["corpus_sha256"] == instance.raw.corpus_hash
    result = instance.symbols("v1.0.0", "run")
    assert len(result["items"]) == 1
    citation = result["items"][0]["citation"]
    assert citation["repository"] == instance.raw.repository
    raw = instance.raw.read_file(citation["commit"], citation["path"], start=citation["start_line"], end=citation["end_line"])
    assert raw["citation"]["content_hash"] == citation["content_hash"]
    assert "return helper" in raw["content"]
    assert any(e["kind"] == "falkordb_query" and e["rows"] for e in instance.trace)


def test_empty_graph_module_serializes_as_verified_membership_and_passes_common_guard(arm, monkeypatch):
    instance, _ = arm
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "evals"))
    guard = importlib.import_module("confirmatory.citation_guard").CitationGuard(instance.raw)
    result = instance.symbols("v1.0.0", "pkg.empty")
    assert len(result["items"]) == 1 and not result["coverage"].get("gaps")
    citation = result["items"][0]["citation"]
    assert citation["proof_type"] == "file_membership"
    assert "start_line" not in citation and "end_line" not in citation
    trace = [{"tool": "graph_symbols", "response": {"status": "OK", "result": result}}]
    assert guard.verify([citation], trace)["valid"]


def test_edge_ablation_changes_fresh_graph_result_and_source_stays_same(arm):
    instance, _ = arm
    before = instance.dependencies("v1.0.0", "pkg.core.run", hops=2)
    assert any(e["target"] == "pkg.util.helper" for e in before["items"])
    instance.query.graph.query("MATCH (:Symbol {qualname:'pkg.core.run'})-[e:CALLS]->() DELETE e")
    after = instance.dependencies("v1.0.0", "pkg.core.run", hops=2)
    assert not after["items"]
    assert "helper(1)" in instance.raw.read_file("v1.0.0", "pkg/core.py")["content"]


def test_extra_basename_source_is_rejected_before_question(common_corpus, graph_name, modules):
    repo, raw = common_corpus
    _, _, graph, _ = modules
    cfg = RepoConfig(name=raw.repository, path=repo, revisions=raw.spec["roots"], include=raw.spec["include"])
    index_repository(cfg, graph_name)
    with pytest.raises(graph.CorpusMismatch) as error:
        graph.GraphTools(raw, graph_name).prepare()
    assert "extra" in error.value.detail


def test_missing_historical_membership_is_rejected_without_manual_repair(arm, modules):
    instance, _ = arm
    _, _, graph, _ = modules
    instance.query.graph.query("MATCH (c:Commit)-[f:HAS_FILE {path:'pkg/core.py'}]->() DELETE f")
    with pytest.raises(graph.CorpusMismatch) as error:
        instance.prepare()
    assert "missing" in error.value.detail


@pytest.mark.parametrize("mutation", [
    "MATCH (r:Repository) SET r.status='STARTED'",
    "MATCH (r:Repository) SET r.generation='different-generation'",
])
def test_raw_graph_arm_tools_cannot_become_a_silent_fallback(arm, modules, mutation):
    instance, _ = arm
    _, _, _, budget = modules
    capabilities, _ = instance.capabilities()
    instance.query.graph.query(mutation)
    with budget.ToolSession(capabilities) as session:
        result = session.call("read_file", {"revision": "v1.0.0", "path": "pkg/core.py"})
    assert result["status"] == "UNAVAILABLE" and result["result"] is None
    assert result["gap"]["kind"] in {"GRAPH_INDEX_INCOMPLETE", "GRAPH_PUBLICATION_CHANGED"}


def test_unavailable_graph_is_fatal_even_when_raw_export_is_readable(arm, modules, monkeypatch):
    instance, _ = arm
    _, _, _, budget = modules
    capabilities, _ = instance.capabilities()
    def unavailable(*_, **__):
        raise ConnectionError("DB unavailable")
    monkeypatch.setattr(instance.query.graph, "ro_query", unavailable)
    with budget.ToolSession(capabilities) as session:
        result = session.call("search", {"revision": "v1.0.0", "text": "helper"})
    assert result["status"] == "UNAVAILABLE" and result["gap"]["kind"] == "GRAPH_INDEX_UNAVAILABLE"


def test_all_raw_baseline_tools_are_available_with_graph_additions(arm, modules):
    instance, _ = arm
    _, _, _, _ = modules
    from confirmatory.development_cli import plaintext_capabilities
    plain_capabilities, _ = plaintext_capabilities(instance.raw)
    graph_capabilities, descriptions = instance.capabilities()
    assert set(plain_capabilities) < set(graph_capabilities)
    assert set(graph_capabilities) == set(descriptions)
    assert "shell" not in descriptions and "index_repository" not in descriptions


def test_graph_rows_accumulate_across_graph_and_raw_operations(arm, modules):
    instance, _ = arm
    _, _, _, budget = modules
    capabilities, _ = instance.capabilities()
    with budget.ToolSession(capabilities, budget.ToolLimits(graph_rows=3)) as session:
        first = session.call("read_file", {"revision": "v1.0.0", "path": "pkg/core.py"})
        assert first["status"] == "OK" and session.budget.used["graph_rows"] == 2
        second = session.call("read_file", {"revision": "v1.0.0", "path": "pkg/core.py"})
        assert second["status"] == "INCOMPLETE" and second["gap"]["unit"] == "graph_rows"
        assert second["result"] is None
