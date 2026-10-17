"""Evaluation identities derived from fixture bytes, independently of the runtime checker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIELDS = ("service", "version", "route_id", "store_id", "record_id")
ObligationKey = tuple[str, str, str, str, str]


def release_identity(directory: Path) -> str:
    """Implement the documented release identity rule without importing the graph/checker."""
    declaration = json.loads((directory / "release.json").read_text(encoding="utf-8"))
    files = [[p.relative_to(directory).as_posix(),
              "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()]
             for p in sorted(directory.rglob("*")) if p.is_file()]
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"release:{declaration['service']}:{hashlib.sha256(canonical).hexdigest()[:16]}"


def obligation_key(row: dict) -> ObligationKey:
    values = tuple(row.get(field) for field in FIELDS)
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"obligation requires nonempty {FIELDS}: {row}")
    return values


def oracle_obligations(case: dict) -> dict[ObligationKey, str]:
    """Validate authored rows before a dict or set could hide a duplicate obligation."""
    result = {}
    for row in case["obligations"]:
        key = obligation_key(row)
        if key in result:
            raise ValueError(f"duplicate obligation in case {case['id']}: {key}")
        if row.get("expected_probe") not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError(f"invalid expected_probe in case {case['id']}: {row}")
        result[key] = row["expected_probe"]
    return result
