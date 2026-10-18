"""Scoring and information-boundary regressions; these do not establish answer quality."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def common(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("repo_eval_common")


def test_partial_or_invalid_evidence_cannot_earn_grounded_pass(common):
    q = {"category": "dependencies"}
    good = {"valid": True, "requested_revision_match": True}
    assert not common.grounded(q, True, 0.5, [good])
    assert not common.grounded(q, True, 1.0, [good, {**good, "valid": False}])
    assert not common.grounded(q, True, 1.0, [{**good, "requested_revision_match": False}])
    assert common.grounded(q, True, 1.0, [good])


def test_justified_clarification_without_evidence_has_separate_inapplicable_metrics(common):
    q = {"category": "ambiguous", "expected_citations": []}
    assert common.evidence_scores([], q, None) == (None, None)
    assert common.grounded(q, True, None, [])
    assert not common.grounded(q, False, None, [])


def test_invalid_citation_does_not_count_as_retrieved_evidence(common):
    exp = {"path": "a.py", "revision": "HEAD", "start_line": 1, "end_line": 2}
    q = {"expected_citations": [exp]}
    clone = SimpleNamespace(sha=lambda r: "a" * 40)
    invalid = {**exp, "resolved_sha": "a" * 40, "valid": False, "requested_revision_match": True}
    assert common.evidence_scores([invalid], q, clone) == (0.0, 0.0)


def test_history_investigation_never_executes_oracle_retrieval_plan(common, monkeypatch):
    from rw.repo.investigate import RepoFindings
    from rw.repo.model import Gap
    module = importlib.import_module("repo_history_eval")
    called = []

    def investigate(repo, rev, text, **kwargs):
        called.append(text)
        return RepoFindings(repo, rev, gaps=[Gap("unknown_symbol", "not found in extracted evidence")])

    monkeypatch.setattr("rw.repo.investigate.investigate", investigate)
    q = {"id": "audit-public", "revision": "HEAD", "question": "Where is missing defined?",
         "category": "missing_evidence", "expected_citations": []}
    keys = {"keys": {}, "e2_retrieval_plans": {q["id"]: ["SECRET ORACLE RETRIEVAL INSTRUCTION"]}}
    module.run_question("requests", q, keys, SimpleNamespace(sha=lambda rev: "a" * 40),
                        SimpleNamespace(name="requests"))
    assert called == [q["question"]]


def test_direct_context_selection_does_not_read_expected_citations(common, monkeypatch):
    module = importlib.import_module("repo_benefit")
    git_calls = []
    clone = SimpleNamespace(sha=lambda rev: "a" * 40,
        show=lambda sha, path: "def real():\n    return 1\n",
        run=lambda *args: (git_calls.append(args) or SimpleNamespace(stdout="real.py" if args[0] == "ls-tree" else "")))
    monkeypatch.setattr(module, "Clone", lambda path: clone)
    monkeypatch.setattr("rw.repo.config.load_config", lambda path: SimpleNamespace(exclude=[]))

    class PublicOnly(dict):
        def get(self, key, *args):
            assert key not in {"expected_citations", "expected_answer"}
            return super().get(key, *args)

        def __getitem__(self, key):
            assert key not in {"expected_citations", "expected_answer"}
            return super().__getitem__(key)

    q = PublicOnly(revision="HEAD", expected_citations=[{"path": "fabricated.py"}])
    text, files = module.direct_context("requests", q, ["*.py"])
    assert files == [("real.py", "HEAD")] and "fabricated.py" not in text
