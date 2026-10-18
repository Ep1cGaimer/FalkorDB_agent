"""Shared evaluation-tool work budgets, independent of any retrieval arm.

Counts UTF8 JSON output bytes and scanned raw-source bytes separately. Exact
provider input/output tokens belong to the model runner; there is no byte/token
conversion here. Deadlines are cooperative, not OS process/memory isolation.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import functools
import json
import math
import time


@dataclasses.dataclass(frozen=True)
class ToolLimits:
    seconds: float = 120
    tool_calls: int = 30
    source_bytes: int = 64 * 1024 * 1024
    work_units: int = 1_000_000
    output_bytes: int = 98_304
    graph_rows: int = 250_000

    def __post_init__(self):
        if type(self.seconds) not in {int, float} or not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("seconds must be finite and positive")
        for field in ("tool_calls", "source_bytes", "work_units", "output_bytes", "graph_rows"):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError(field + " must be a positive integer")


class ToolBudgetExceeded(RuntimeError):
    def __init__(self, budget, unit):
        self.unit = unit
        self.usage = budget.snapshot()
        super().__init__("TOOL_BUDGET_EXHAUSTED: " + unit)


class ToolBudget:
    def __init__(self, limits=ToolLimits(), *, clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.used = dict(tool_calls=0, source_bytes=0, work_units=0, output_bytes=0, graph_rows=0)
        self.exhausted = None

    def snapshot(self):
        return {"limits": dataclasses.asdict(self.limits), "used": dict(self.used),
                "elapsed_seconds": self.clock() - self.started, "exhausted": self.exhausted,
                "exact_model_tokens": "UNMEASURED_BY_TOOL_LAYER"}

    def consume(self, unit=None, amount=0):
        if self.exhausted:
            raise ToolBudgetExceeded(self, self.exhausted)
        if self.clock() - self.started >= self.limits.seconds:
            self.exhausted = "seconds"
        elif unit is not None:
            if unit not in self.used or type(amount) is not int or amount < 0:
                raise ValueError("invalid budget counter")
            self.used[unit] += amount
            if self.used[unit] > getattr(self.limits, unit):
                self.exhausted = unit
        if self.exhausted:
            raise ToolBudgetExceeded(self, self.exhausted)

    def output(self, result):
        # Stream encoding avoids constructing another copy of an oversized payload.
        encoder = json.JSONEncoder(ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        for chunk in encoder.iterencode(result):
            self.consume("output_bytes", len(chunk.encode("ascii")))


_active = contextvars.ContextVar("confirmatory_tool_budget", default=None)
_depth = contextvars.ContextVar("confirmatory_tool_depth", default=0)


@contextlib.contextmanager
def tool_budget(limits=ToolLimits(), *, clock=time.monotonic):
    """One instance per question/arm; nested tool calls share counters/deadline."""
    if _active.get() is not None:
        raise ValueError("a question budget is already active; use the existing one")
    budget = ToolBudget(limits, clock=clock)
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)


def active_tool_budget():
    return _active.get()


def checkpoint(*, source_bytes=0, work_units=1, graph_rows=0):
    budget = _active.get()
    if budget is None:
        raise RuntimeError("tool work requires a bounded operation")
    budget.consume("source_bytes", source_bytes)
    budget.consume("work_units", work_units)
    budget.consume("graph_rows", graph_rows)


def bounded_tool(fn):
    """Bound direct calls too; a surrounding question context shares all calls."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        if _active.get() is None:
            with tool_budget():
                return wrapped(*args, **kwargs)
        outermost = _depth.get() == 0
        budget = _active.get()
        if outermost:
            budget.consume("tool_calls", 1)
        token = _depth.set(_depth.get() + 1)
        try:
            result = fn(*args, **kwargs)
            budget.consume()
            if outermost:
                budget.output(result)
            return result
        finally:
            _depth.reset(token)
    return wrapped


class ToolSession:
    """Explicit capability map and one cumulative budget for a question/arm.

    Keep this session open across model turns. A failed operation remains a trace
    entry; exhausted budgets stay exhausted. Provider token limits and final-answer
    handling must be supplied by the eventual model runner.
    """
    def __init__(self, capabilities: dict, limits=ToolLimits(), *, clock=time.monotonic):
        if not capabilities or any(not isinstance(k, str) or k.startswith("_") or not callable(v)
                                   for k, v in capabilities.items()):
            raise ValueError("explicit named callable capabilities required")
        self.capabilities, self.limits, self.clock = dict(capabilities), limits, clock
        self.trace = []
        self._context = None

    def __enter__(self):
        if self._context is not None:
            raise ValueError("session cannot be reopened")
        self._context = tool_budget(self.limits, clock=self.clock)
        self.budget = self._context.__enter__()
        return self

    def __exit__(self, *exc):
        self.closed = True
        return self._context.__exit__(*exc)

    def call(self, name: str, arguments: dict):
        if self._context is None or getattr(self, "closed", False) or _active.get() is not self.budget:
            raise ValueError("tool session must be active in its own request context")
        before = self.budget.snapshot()
        try:
            if name not in self.capabilities or not isinstance(arguments, dict):
                # Failed/unauthorized calls consume the same tool-call budget.
                self.budget.consume("tool_calls", 1)
                raise ValueError("unknown tool or malformed arguments")
            # Adapter-independent enforcement, including otherwise undecorated arms.
            def operation():
                return {"status": "OK", "result": self.capabilities[name](**arguments)}
            # Count the actual transmitted success envelope once, including nested
            # tool results. Terminal diagnostics are small, explicit overhead.
            response = bounded_tool(operation)()
        except ToolBudgetExceeded as exc:
            response = {"status": "INCOMPLETE", "result": None, "complete": False,
                        "gap": {"kind": "TOOL_BUDGET_EXHAUSTED", "unit": exc.unit}}
        except Exception as exc:
            # Exception messages may contain private paths or transport credentials.
            response = {"status": "ERROR", "result": None, "complete": False,
                        "gap": {"kind": "TOOL_OPERATION_FAILED", "exception_type": type(exc).__name__}}
            if getattr(exc, "fatal_tool_failure", False):
                response.update(status="UNAVAILABLE", gap={"kind": getattr(exc, "code", "ARM_UNAVAILABLE")})
            try:
                self.budget.output(response)
            except ToolBudgetExceeded as budget_exc:
                response = {"status": "INCOMPLETE", "result": None, "complete": False,
                            "gap": {"kind": "TOOL_BUDGET_EXHAUSTED", "unit": budget_exc.unit}}
        self.trace.append({"tool": name, "arguments": arguments, "before": before,
                           "after": self.budget.snapshot(), "response": response})
        return response
