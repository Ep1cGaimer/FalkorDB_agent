"""Request-local read budgets shared by graph operations and Git subprocesses.

Deadlines bound database execution and child-process waits. Python processing checks
cooperatively between reads and before publishing results. Byte/row limits account
for consumed evidence, not model tokens or a hard process-memory ceiling.
"""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadLimits:
    seconds: float = 120.0
    rows: int = 250_000
    source_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        if isinstance(self.seconds, bool) or not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("read deadline must be finite and positive")
        if any(type(v) is not int or v <= 0 for v in (self.rows, self.source_bytes)):
            raise ValueError("row and source-byte budgets must be positive integers")


class BudgetExhausted(RuntimeError):
    def __init__(self, budget: ReadBudget, resource: str):
        budget.exhausted = budget.exhausted or resource
        self.resource = resource
        self.coverage = budget.snapshot()
        super().__init__(f"retrieval {resource} budget exhausted; evidence is incomplete")


class ReadBudget:
    def __init__(self, limits: ReadLimits):
        self.limits = limits
        self.started = time.monotonic()
        self.rows = self.source_bytes = self.queries = 0
        self.exhausted: str | None = None

    def remaining(self) -> float:
        if self.exhausted:
            raise BudgetExhausted(self, self.exhausted)
        remaining = self.limits.seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise BudgetExhausted(self, "seconds")
        return remaining

    def consume_rows(self, rows: int):
        self.remaining()
        self.rows += rows
        if self.rows > self.limits.rows:
            raise BudgetExhausted(self, "rows")

    def check_source(self, size: int):
        self.remaining()
        if type(size) is not int or size < 0:
            raise ValueError("source byte count must be a nonnegative integer")
        if size > self.limits.source_bytes - self.source_bytes:
            raise BudgetExhausted(self, "source_bytes")

    def consume_source(self, size: int):
        self.check_source(size)
        self.source_bytes += size

    def snapshot(self, *, include_elapsed: bool = False) -> dict:
        out = {"limits": {"seconds": self.limits.seconds, "rows": self.limits.rows,
                           "source_bytes": self.limits.source_bytes},
                "rows": self.rows, "source_bytes": self.source_bytes,
                "graph_queries": self.queries, "exhausted": self.exhausted,
                "within_limits": self.exhausted is None}
        if include_elapsed:
            out["elapsed_seconds"] = time.monotonic() - self.started
        return out


_active: ContextVar[ReadBudget | None] = ContextVar("repository_read_budget", default=None)


def active_budget() -> ReadBudget | None:
    return _active.get()


@contextmanager
def read_scope(limits: ReadLimits | None = None):
    """Nested retrievals inherit their request's counters/deadline, never reset it."""
    existing = active_budget()
    if existing is not None:
        yield existing
        return
    budget = ReadBudget(limits or ReadLimits())
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)
