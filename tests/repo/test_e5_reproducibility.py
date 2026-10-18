"""E5 — reproducibility of recorded evidence runs (remquirements-v1.md E5; evals/REPRODUCIBILITY.md).

Validates every run file under artifacts/repo_scale/*.json, artifacts/repo_onboarding/*.json and
artifacts/repo_benefit/*.json (a category with no files is skipped). Failed/incomplete attempts live in
artifacts/<category>/attempts/*.json; they must record `status` and `error`/`failures`. An attempt
whose status is not complete must still carry every required key, but a key may be null when its name
appears in `error`/`failures` text or in `missing_fields`/`backfilled_fields`. Complete runs are strict.

Required top-level keys of each run record (name alternatives accepted where listed):
  command        str or list — the exact command line that produced the file
  manifest       {"repos": [{"repo": name, "revisions": {rev: 40-hex sha, ...}}...]} or
                 {"repo": name, "revisions": {...}}; revisions may also be [{"ref", "sha"}]
  coverage       extraction coverage: dict/list containing gaps and/or limits
  config         the configuration used, or config_sha256 (64-hex)
  traces         raw retrieval traces (list) or traces_path (existing file relative to project root)
  answers        list/dict of produced answers (repo_scale may record "query_workload" instead)
  usage/timings  "usage" or "timings" (scale runs may use "query_latency_ms" + "started_at"/"finished_at")
  model          {"model": id, "prompt_id"/"prompt_sha256": ...} — required when "llm_used" is true or
                 the category is repo_benefit
  scoring        required where the run is scored ("scored": true, or repo_benefit)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts"
CATEGORIES = ["repo_scale", "repo_onboarding", "repo_benefit"]
SHA = re.compile(r"^[0-9a-f]{40}$")


def _runs(cat):
    d = ART / cat
    files = sorted(d.glob("*.json")) + sorted((d / "attempts").glob("*.json")) if d.is_dir() else []
    return files


ALL = [(c, p) for c in CATEGORIES for p in _runs(c)]


@pytest.mark.parametrize("cat", CATEGORIES)
def test_category_has_runs_or_is_skipped(cat):
    if not _runs(cat):
        pytest.skip(f"no runs recorded under artifacts/{cat}")


def _manifest_ok(m) -> bool:
    entries = m.get("repos") if isinstance(m, dict) and "repos" in m else [m]
    if not entries:
        return False
    for e in entries:
        if not isinstance(e, dict) or not e.get("repo"):
            return False
        revs = e.get("revisions")
        if isinstance(revs, list):  # [{"ref": ..., "sha": ...}]
            revs = {str(r.get("ref")): r.get("sha") for r in revs if isinstance(r, dict)}
        if not isinstance(revs, dict) or not revs or not all(SHA.match(str(v)) for v in revs.values()):
            return False
    return True


COMPLETE_STATUSES = {"complete", "completed", "ok", "pass", "passed"}


def _groups(cat, rec):
    """(label, keys that may satisfy it, strict check) for every required field of this record."""
    tp = rec.get("traces_path")
    g = [
        ("command", ["command"], lambda: bool(rec.get("command"))),
        ("manifest (repo + resolved 40-hex shas)", ["manifest"], lambda: _manifest_ok(rec.get("manifest"))),
        ("coverage (gaps/limits)", ["coverage"],
         lambda: bool(rec.get("coverage")) and any(k in json.dumps(rec["coverage"]) for k in ("gap", "limit"))),
        ("config or config_sha256", ["config", "config_sha256"],
         lambda: bool(rec.get("config") or re.fullmatch(r"[0-9a-f]{64}", str(rec.get("config_sha256", ""))))),
        ("traces or existing traces_path", ["traces", "traces_path"],
         lambda: isinstance(rec.get("traces"), list) or bool(tp and (ROOT / tp).exists())),
        ("answers", ["answers"] + (["query_workload"] if cat == "repo_scale" else []),
         lambda: bool(rec.get("answers") or (cat == "repo_scale" and rec.get("query_workload")))),
        ("usage/timings", ["usage", "timings"] + (["query_latency_ms"] if cat == "repo_scale" else []),
         lambda: bool(rec.get("usage") or rec.get("timings")
                      or (cat == "repo_scale" and rec.get("query_latency_ms") and rec.get("started_at")
                          and rec.get("finished_at")))),
    ]
    if rec.get("llm_used") or cat == "repo_benefit":
        g.append(("model/prompt identifiers", ["model"],
                  lambda: bool((rec.get("model") or {}).get("model")
                               and ((rec.get("model") or {}).get("prompt_id")
                                    or (rec.get("model") or {}).get("prompt_sha256")))))
    if rec.get("scored") or cat == "repo_benefit":
        g.append(("scoring decisions", ["scoring"], lambda: bool(rec.get("scoring"))))
    return g


def _explained(rec, key) -> bool:
    text = json.dumps([rec.get("error"), rec.get("failures")], default=str)
    listed = list(rec.get("missing_fields") or []) + list(rec.get("backfilled_fields") or [])
    return key in listed or re.search(r"(?<![\w])" + re.escape(key) + r"(?![\w])", text) is not None


@pytest.mark.parametrize("cat,path", ALL, ids=[f"{c}/{p.name}" for c, p in ALL] or None)
def test_run_record_is_reproducible(cat, path):
    rec = json.loads(path.read_text(encoding="utf-8"))
    missing = []
    attempt = path.parent.name == "attempts"
    if attempt and (not rec.get("status") or not (rec.get("error") or rec.get("failures"))):
        missing.append("attempt status + error/failures")
    incomplete = attempt and str(rec.get("status", "")).lower() not in COMPLETE_STATUSES
    for label, keys, ok in _groups(cat, rec):
        if ok():
            continue
        if incomplete:
            present = [k for k in keys if k in rec]
            if not present:
                missing.append(f"{label} (key absent; incomplete attempts must still carry the key)")
            elif all(rec[k] is None for k in present) and any(_explained(rec, k) for k in present):
                continue  # every alternative null, and error / missing_fields names the field
            else:
                missing.append(f"{label} (null/invalid and not explained by error or missing_fields)")
        else:
            missing.append(label)
    assert not missing, f"{path.relative_to(ROOT)} lacks: {', '.join(missing)}"


def test_attempts_are_kept_not_overwritten():
    """Each run file is timestamped (no fixed 'latest.json' that would overwrite earlier attempts)."""
    for cat, path in ALL:
        assert re.search(r"\d{8}T\d{6}", path.name), f"{path} is not a timestamped run record"


def test_reproducibility_protocol_documented():
    doc = (ROOT / "evals" / "REPRODUCIBILITY.md").read_text(encoding="utf-8")
    for e in ("E1", "E2", "E3", "E4", "E5"):
        assert e in doc
    for cat in CATEGORIES:
        assert f"artifacts/{cat}" in doc
    assert "attempts/" in doc
