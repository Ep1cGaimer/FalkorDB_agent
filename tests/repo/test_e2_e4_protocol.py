"""E2/E4 protocol checks: held-out real-repo questions, the pre-registered benefit threshold, and (when
present) the shape of evaluation outputs. Imports no repository code; uses read-only git on the clones."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QDIR = ROOT / "evals" / "repo_questions"
THRESHOLD = ROOT / "evals" / "repo_benefit_threshold.json"
REPOS = ["requests", "itsdangerous"]
CATEGORIES = {"dependencies", "distant_release", "changes_between", "fix_appeared", "rename_delete",
              "ambiguous", "missing_evidence"}
CONTESTANTS = {"graph_tools", "plaintext_direct", "plaintext_search"}
METRICS = {"answer_accuracy", "grounded_answer_accuracy", "evidence_recall", "evidence_precision",
           "citation_validity", "wrong_revision", "tokens", "tool_calls", "latency_s", "cost_usd",
           "context_limit_failures"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(name):
    return json.loads((QDIR / f"{name}.json").read_text(encoding="utf-8"))


def clone(name):
    p = ROOT / "artifacts" / "repos" / name
    return p if (p / ".git").exists() or (p / "HEAD").exists() else None


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)


@pytest.mark.parametrize("name", REPOS)
def test_question_schema(name):
    d = load(name)
    assert d["repo"] == name and d["questions"]
    qs = d["questions"]
    assert 8 <= len(qs) <= 12
    assert len({q["id"] for q in qs}) == len(qs)
    assert CATEGORIES <= {q["category"] for q in qs}
    for q in qs:
        for k in ("id", "category", "question", "revision", "expected_answer", "expected_citations"):
            assert q.get(k) not in (None, ""), (q.get("id"), k)
        if q["category"] == "missing_evidence":
            assert q.get("expect_gap") is True and q["expected_citations"] == []
        else:
            assert q["expected_citations"], q["id"]
        for c in q["expected_citations"]:
            assert set(c) >= {"path", "start_line", "end_line", "revision"}
            assert 1 <= c["start_line"] <= c["end_line"]


@pytest.mark.parametrize("name", REPOS)
def test_citations_resolve_in_clone(name):
    repo = clone(name)
    if repo is None:
        pytest.skip(f"clone artifacts/repos/{name} absent")
    for q in load(name)["questions"]:
        revs = {q["revision"], q.get("compare_revision")} - {None}
        for r in revs:
            assert git(repo, "rev-parse", "--verify", "-q", f"{r}^{{commit}}").returncode == 0, (q["id"], r)
        for key in ("fix_commit", "merge_commit", "rename_commit"):
            if q.get(key):
                assert git(repo, "rev-parse", "--verify", "-q", f"{q[key]}^{{commit}}").returncode == 0
        if q.get("merge_commit"):
            parents = git(repo, "log", "-1", "--format=%P", q["merge_commit"]).stdout.split()
            assert len(parents) == 2, q["id"]
        if q["category"] == "fix_appeared":
            tags = git(repo, "tag", "--contains", q["fix_commit"], "--sort=creatordate").stdout.split()
            assert tags and tags[0] == q["revision"], (q["id"], tags[:3])
        for c in q["expected_citations"]:
            out = git(repo, "show", f"{c['revision']}:{c['path']}")
            assert out.returncode == 0, (q["id"], c)
            assert c["end_line"] <= len(out.stdout.splitlines()), (q["id"], c)


def test_threshold_declaration():
    t = json.loads(THRESHOLD.read_text(encoding="utf-8"))
    assert t["declared_before_any_run"] is True and t["amendment_rule"]
    assert {c["name"] for c in t["contestants"]} == CONTESTANTS
    assert t["repeats"] >= 2
    b = t["budget"]
    for k in ("max_turns_per_task", "max_total_tokens_per_task", "max_tool_output_chars", "max_tokens_per_request"):
        assert isinstance(b[k], int) and b[k] > 0
    assert b["max_tokens_per_request"] <= b["groq_tokens_per_minute_limit"] == 8000
    assert t["model"]["name"] and "temperature" in t["model"]
    assert t["primary_metric"] and t["threshold"]["PASS_if_any"] and t["threshold"]["INCONCLUSIVE"]
    assert set(t["secondary_metrics"]) >= {"evidence_recall", "evidence_precision", "citation_validity",
                                           "wrong_revision", "tokens", "tool_calls", "latency_s", "cost_usd",
                                           "indexing_cost"}
    assert t["cost_model"]["usd_per_million_input_tokens"] >= 0
    hashed = {Path(f["path"]).as_posix(): f["sha256"] for f in t["question_files"]}
    assert set(hashed) == {f"evals/repo_questions/{r}.json" for r in REPOS}
    for p, h in hashed.items():
        assert sha(ROOT / p) == h, f"{p} changed after pre-registration"


def outputs(d="repo_benefit"):
    return sorted((ROOT / "artifacts" / d).glob("*.json"))


E2_METRICS = {"answer_accuracy", "grounded_answer_accuracy", "evidence_recall", "evidence_precision",
              "citation_validity", "wrong_revision"}


@pytest.mark.parametrize("path", outputs("repo_history_eval") or [None], ids=lambda p: p.name if p else "none")
def test_e2_history_outputs(path):
    if path is None:
        pytest.skip("no E2 outputs yet")
    r = json.loads(path.read_text(encoding="utf-8"))
    assert r["repeats"] >= 1
    hashed = {Path(f["path"]).as_posix(): f["sha256"] for f in r["question_files"]}
    assert hashed
    for p, h in hashed.items():
        assert sha(ROOT / p) == h, f"{p} hash mismatch"
    res = r["results"]
    assert set(res["per_repo"]) >= set(REPOS)
    for where, m in [*res["per_repo"].items(), ("overall", res["overall"])]:
        assert not (E2_METRICS - set(m)), (where, E2_METRICS - set(m))
    assert r["records"]
    for rec in r["records"]:
        for k in ("repo", "question_id", "answer_correct", "evidence_recall", "evidence_precision", "citations"):
            assert k in rec, (path.name, k)
        assert isinstance(rec["answer_correct"], bool)
        for cit in rec["citations"]:
            assert {"path", "start_line", "end_line", "revision", "valid", "requested_revision_match"} <= set(cit)


def _metrics_ok(m, where):
    missing = METRICS - set(m)
    assert not missing, (where, missing)


@pytest.mark.parametrize("path", outputs() or [None], ids=lambda p: p.name if p else "none")
def test_eval_outputs(path):
    if path is None:
        pytest.skip("no E2/E4 outputs yet")
    r = json.loads(path.read_text(encoding="utf-8"))
    assert r["threshold_sha256"] == sha(THRESHOLD)
    assert set(r["contestants"]) == CONTESTANTS
    assert r["repeats"] >= 2 and len(r["runs"]) >= 2
    assert r["indexing_cost"]
    res = r["results"]
    assert set(res["per_repo"]) >= set(REPOS)
    for repo, by_c in res["per_repo"].items():
        assert set(by_c) == CONTESTANTS
        for c, m in by_c.items():
            _metrics_ok(m, (repo, c))
    assert set(res["overall"]) == CONTESTANTS
    for c, m in res["overall"].items():
        _metrics_ok(m, ("overall", c))
    for run in r["runs"]:
        for task in run["tasks"]:
            for k in ("repo", "question_id", "contestant", "answer_correct", "evidence_recall",
                      "evidence_precision", "citations", "tokens", "tool_calls", "latency_s", "context_limit"):
                assert k in task, (path.name, k)
            for cit in task["citations"]:
                assert {"path", "start_line", "end_line", "revision", "valid", "requested_revision_match"} <= set(cit)
    assert r["verdict"] in {"PASS", "FAIL", "INCONCLUSIVE"}
    assert r.get("verdict_reason")
