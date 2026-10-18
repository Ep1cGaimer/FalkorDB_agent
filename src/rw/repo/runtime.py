"""Optional, pluggable runtime-check adapters for compatibility dispositions (docs/repo/REQUIREMENTS.md S6).

None are built in. Ingestion and retrieval never call an adapter; only investigate(mode="compatibility")
with an explicitly named adapter does. Status rules over the adapter's modeled obligations:
any FAIL -> BLOCKED; else any obligation without a current receipt -> NEEDS_EVIDENCE; else BOUNDED_PASS.
Zero modeled obligations never yields BOUNDED_PASS."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RUNTIME_ADAPTERS: dict[str, Any] = {}


def register_runtime_adapter(name: str, adapter: Any) -> None:
    RUNTIME_ADAPTERS[name] = adapter


@dataclass(frozen=True)
class RuntimeReceipt:
    obligation: str
    status: Literal["PASS", "FAIL"]
    revision: str
    extractor_version: str
    adapter_version: str


def extractor_fingerprint() -> str:
    from rw.repo.adapters import ADAPTERS
    return ",".join(f"{lang}@{a.version}" for lang, a in sorted(ADAPTERS.items()))


def is_current(r: RuntimeReceipt, sha: str, adapter_version: str) -> bool:
    return (r.revision == sha and r.extractor_version == extractor_fingerprint()
            and r.adapter_version == adapter_version)


def disposition(obligations: list[str], receipts: list[RuntimeReceipt], sha: str,
                adapter_version: str) -> tuple[str | None, list[str]]:
    """Return (disposition, obligations lacking a current receipt)."""
    if not obligations:
        return None, []
    obl = set(obligations)
    current = [r for r in receipts if r.obligation in obl and is_current(r, sha, adapter_version)]
    if any(r.status == "FAIL" for r in current):
        return "BLOCKED", []
    passed = {r.obligation for r in current if r.status == "PASS"}
    missing = [o for o in obligations if o not in passed]
    return ("NEEDS_EVIDENCE" if missing else "BOUNDED_PASS"), missing
