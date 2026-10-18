"""Question-level resource contracts and explicit exhaustion across tool arms."""
import concurrent.futures
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("confirmatory.tool_budget")


def test_nested_tool_output_is_counted_once_and_whole_question_accumulates(budget):
    @budget.bounded_tool
    def inner():
        budget.checkpoint(source_bytes=7)
        return {"content": "abc"}
    @budget.bounded_tool
    def outer():
        return inner()
    with budget.tool_budget(budget.ToolLimits(tool_calls=2)) as state:
        assert outer() == {"content": "abc"}
        assert state.used == {"tool_calls": 1, "source_bytes": 7, "work_units": 1, "output_bytes": 17, "graph_rows": 0}
        outer()
        with pytest.raises(budget.ToolBudgetExceeded, match="tool_calls"):
            outer()
        assert state.used["source_bytes"] == 14


def test_failure_envelope_retains_attempt_and_never_returns_oversized_evidence(budget):
    with budget.ToolSession({"read": lambda: {"content": "é" * 1000}},
                            budget.ToolLimits(output_bytes=100)) as session:
        result = session.call("read", {})
        assert result == {"status": "INCOMPLETE", "result": None, "complete": False,
                          "gap": {"kind": "TOOL_BUDGET_EXHAUSTED", "unit": "output_bytes"}}
        assert session.call("read", {})["status"] == "INCOMPLETE"
        assert len(session.trace) == 2
        assert session.trace[0]["after"]["exhausted"] == "output_bytes"


def test_unauthorized_calls_and_exceptions_stay_in_denominator_without_secret_echo(budget):
    def broken():
        raise RuntimeError("SECRET transport info")
    with budget.ToolSession({"broken": broken}, budget.ToolLimits(tool_calls=3)) as session:
        assert session.call("open_arbitrary_file", {})["status"] == "ERROR"
        assert session.call("broken", {})["gap"]["exception_type"] == "RuntimeError"
        assert "SECRET" not in str(session.trace)
        assert session.budget.used["tool_calls"] == 2
        assert len(session.trace) == 2


@pytest.mark.parametrize("unit", ["source_bytes", "work_units"])
def test_scan_work_is_stopped_before_a_conclusion(budget, unit):
    def scan():
        budget.checkpoint(**{unit: 11})
        return {"definitive_absence": True}
    with budget.ToolSession({"scan": scan}, budget.ToolLimits(**{unit: 10})) as session:
        result = session.call("scan", {})
        assert result["result"] is None and result["gap"]["unit"] == unit


def test_deadline_is_cumulative_and_checked_after_tool_returns(budget):
    now = [0.0]
    def slow():
        now[0] += 0.6
        return {"conclusion": "do not retain after timeout"}
    with budget.ToolSession({"slow": slow}, budget.ToolLimits(seconds=1), clock=lambda: now[0]) as session:
        assert session.call("slow", {})["status"] == "OK"
        result = session.call("slow", {})
        assert result["gap"]["unit"] == "seconds" and result["result"] is None


def test_parallel_question_sessions_do_not_share_usage(budget):
    def question(limit):
        with budget.ToolSession({"read": lambda: {"source": "x" * 100}},
                                budget.ToolLimits(output_bytes=limit)) as session:
            return session.call("read", {})["status"], session.budget.used["tool_calls"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(question, [10, 1000]))
    assert results == [("INCOMPLETE", 1), ("OK", 1)]


def test_session_cannot_be_reopened_or_called_after_exit(budget):
    session = budget.ToolSession({"ok": lambda: True})
    with session:
        assert session.call("ok", {})["status"] == "OK"
    with pytest.raises(ValueError):
        session.call("ok", {})
    with pytest.raises(ValueError):
        session.__enter__()


@pytest.mark.parametrize("limits", [{"seconds": float("nan")}, {"seconds": -1},
                                   {"output_bytes": True}, {"work_units": 0}])
def test_invalid_budget_cannot_disable_enforcement(budget, limits):
    with pytest.raises(ValueError):
        budget.ToolLimits(**limits)


def test_session_counts_transmitted_result_envelope_and_failed_operation_bytes(budget):
    import json
    with budget.ToolSession({"ok": lambda: "a"}) as session:
        response = session.call("ok", {})
        expected = len(json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        assert session.budget.used["output_bytes"] == expected
        failure = session.call("unknown", {})
        expected += len(json.dumps(failure, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        assert session.budget.used["output_bytes"] == expected
