"""Numerical tests use synthetic scores, never presented as observed model performance."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def stats(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("repo_statistics")


def rows():
    return [{"repo": f"repo-{i // 4}", "question_id": f"q{i}", "stratum": f"s{i % 2}",
             "arm": arm, "repeat": repeat, "evidence_applicable": True, "outcome": "PASS",
             "answer_pass": 1.0, "evidence_precision": 1.0, "evidence_recall": 1.0,
             "input_tokens": 75 if arm == "graph" else 100, "output_tokens": 10,
             "query_cost_usd": 0.0, "latency_s": 0.1}
            for i in range(8) for repeat in range(3) for arm in ("graph", "search")]


def test_bootstrap_keeps_question_repeats_together_and_gate_b_has_no_quality_loss(stats):
    result = stats.paired_bootstrap(rows(), "graph", "search", seed=42)
    assert result["n_questions"] == 8 and result["resamples"] == 10_000
    assert result["point"]["input_token_ratio"] == 0.75
    assert result["intervals"]["input_token_ratio"] == [0.75, 0.75]
    assert result["intervals"]["answer_pass_difference"] == [0.0, 0.0]
    conditions = stats.advantage_conditions(result, "B")
    assert conditions["numerical_conditions_pass"] and not conditions["acceptance_validated"]
    assert stats.break_even_queries(1.0, 0.0) is None
    assert stats.break_even_queries(1.0, -0.01) is None
    assert stats.break_even_queries(1.0, 0.01) == 100
    with pytest.raises(ValueError, match="exactly one"):
        stats.advantage_conditions(result, "A or B")


def test_missing_duplicate_invalid_or_unpaired_attempts_are_errors(stats):
    data = rows()
    for invalid in (data[:-1], data + [data[0]], [{**r, "repeat": 0} for r in data]):
        with pytest.raises(ValueError):
            stats.paired_bootstrap(invalid, "graph", "search", seed=42)
    with pytest.raises(ValueError, match="10000"):
        stats.paired_bootstrap(data, "graph", "search", seed=42, resamples=9999)
    invalid = deepcopy(data)
    invalid[0]["input_tokens"] = float("nan")
    with pytest.raises(ValueError, match="measurement"):
        stats.paired_bootstrap(invalid, "graph", "search", seed=42)
    invalid = deepcopy(data)
    invalid[0]["outcome"] = "ERROR"
    with pytest.raises(ValueError, match="zero quality"):
        stats.paired_bootstrap(invalid, "graph", "search", seed=42)


def test_pooled_quality_cannot_hide_a_repository_regression(stats):
    data = rows()
    for r in data:
        r["answer_pass"] = (0.8 if r["repo"] == "repo-0" else 1.0) if r["arm"] == "graph" else 0.9
    result = stats.paired_bootstrap(data, "graph", "search", seed=42)
    conditions = stats.advantage_conditions(result, "B")
    assert not conditions["no_repository_quality_regression"]
    assert not conditions["numerical_conditions_pass"]


def test_gate_a_requires_input_and_cost_constraints(stats):
    data = rows()
    for r in data:
        r["answer_pass"] = 1.0 if r["arm"] == "graph" else 0.8
        r["query_cost_usd"] = 0.01
    result = stats.paired_bootstrap(data, "graph", "search", seed=42)
    assert stats.advantage_conditions(result, "A")["numerical_conditions_pass"]
    result["means"]["graph"]["query_cost_usd"] = 0.011
    assert not stats.advantage_conditions(result, "A")["numerical_conditions_pass"]
