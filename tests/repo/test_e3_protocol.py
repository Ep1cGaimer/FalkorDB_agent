"""E3 protocol (docs/repo/REQUIREMENTS.md E3): budgets are declared before measurement, and any measurement
output under artifacts/repo_scale/*.json records what E3 requires against a specific budgets file.

Interface assumed:
  evals/repo_budgets.json (schema checked below).
  evals/repo_scale.py writes artifacts/repo_scale/<run>.json with at least:
    budgets_sha256: sha256 hex of the exact bytes of evals/repo_budgets.json it measured against
    corpus: {repository, selected_revisions (int), plaintext_tokens (int > context budget)}
    initial_index: {seconds, peak_memory_bytes, blobs_new, blobs_reused, commits, nodes, edges}
    update: {seconds, peak_memory_bytes, blobs_new, blobs_reused, ...}
    index_size_bytes: int
    peak_memory_bytes: int
    query_latency_ms: {count, p50, p95, max}
    truncation: {truncated_pages: int, ...}
    failures: list (each failure recorded; may be empty)
    interrupted_import: {interrupted: bool, partial_presented_complete: bool, recovered: bool,
                         final_status: str}
    invalidation: {passed: bool, ...}
    budgets_met: {<budget key>: bool}
No network, no FalkorDB needed.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUDGETS = ROOT / "evals" / "repo_budgets.json"
OUT_DIR = ROOT / "artifacts" / "repo_scale"


def _budgets():
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def test_budgets_file_schema():
    b = _budgets()
    assert b["declared_before_measurement"] is True
    c = b["corpus"]
    assert c["repository"] and c["path"]
    for k in ("total_commits", "total_tags", "selected_tags_approx"):
        assert isinstance(c[k], int) and c[k] > 0
    import re
    re.compile(c["tag_pattern"])
    assert isinstance(b["context_budget"]["tokens"], int) and b["context_budget"]["tokens"] > 0
    assert "exceed" in b["context_budget"]["requirement"]
    bud = b["budgets"]
    for k in ("initial_index_seconds_max", "update_seconds_max", "peak_memory_mb_max",
              "query_latency_p95_ms_max", "index_size_mb_max"):
        assert isinstance(bud[k], (int, float)) and bud[k] > 0, k
    assert 1 <= bud["query_page_limit"] <= 200
    assert isinstance(b["rationale"], str) and len(b["rationale"]) > 40


def _outputs():
    return sorted(OUT_DIR.glob("*.json")) if OUT_DIR.is_dir() else []


@pytest.mark.parametrize("path", _outputs() or [None])
def test_scale_output_records_required_fields(path):
    if path is None:
        pytest.skip("no artifacts/repo_scale/*.json output yet")
    out = json.loads(path.read_text(encoding="utf-8"))
    budgets_bytes = BUDGETS.read_bytes()
    assert out["budgets_sha256"] == hashlib.sha256(budgets_bytes).hexdigest(), \
        "output must be measured against the current declared budgets file"
    ctx = _budgets()["context_budget"]["tokens"]
    assert out["corpus"]["plaintext_tokens"] > ctx
    for phase in ("initial_index", "update"):
        m = out[phase]
        for k in ("seconds", "peak_memory_bytes", "blobs_new", "blobs_reused"):
            assert isinstance(m[k], (int, float)) and m[k] >= 0, (phase, k)
    assert out["update"]["blobs_reused"] > 0
    assert isinstance(out["index_size_bytes"], int) and out["index_size_bytes"] > 0
    assert isinstance(out["peak_memory_bytes"], int) and out["peak_memory_bytes"] > 0
    lat = out["query_latency_ms"]
    assert lat["count"] > 0 and 0 <= lat["p50"] <= lat["p95"] <= lat["max"]
    assert isinstance(out["truncation"]["truncated_pages"], int)
    assert isinstance(out["failures"], list)
    ii = out["interrupted_import"]
    assert ii["interrupted"] is True and ii["partial_presented_complete"] is False
    assert ii["recovered"] is True and ii["final_status"] == "COMPLETE"
    assert isinstance(out["invalidation"]["passed"], bool)
    assert isinstance(out["budgets_met"], dict) and out["budgets_met"]
