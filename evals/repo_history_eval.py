"""E2 history correctness (remquirements-v1.md E2): deterministic retrieval, no LLM.

For every held-out question (synthetic_history, branchy_history, requests, itsdangerous) this runs
rw.repo.investigate in retrieval mode at the question's revision: the raw question first (recorded;
used only if investigate supports its shape), then the hand-written supported-shape queries declared
in evals/repo_eval_keys.json `e2_retrieval_plans`. It scores retrieved EVIDENCE (recall/precision vs
expected_citations: same path + revision, intersecting spans) separately from the ANSWER (rule in
evals/repo_eval_keys.json `answer_rule`, structural form for ambiguous/missing_evidence), checks
every citation with read-only git (revision resolves in the requested clone, path exists, span inside
the file) and counts wrong-revision citations. Two identical repeats check determinism.

    PYTHONPATH=src .venv/Scripts/python.exe evals/repo_history_eval.py

Writes artifacts/repo_history_eval/<timestamp>.json (+ traces sidecar): `results` (per_repo, overall),
`records` (repeat-0 per-question records; both repeats under `runs`) and the E5 keys."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_eval_common import (IGNORED_GAPS, KEYS_PATH, ROOT, SETS, THRESHOLD, Clone, allowed_shas,  # noqa: E402
                              answer_check, check_citation, evidence_scores, expected_citations, fabricated,
                              grounded, load_keys, load_questions, manifest_for, now_iso, question_revs, rel,
                              sha256_file, sha256_text, stamp)

OUT = ROOT / "artifacts" / "repo_history_eval"
REPEATS = 2
NAMES = ["synthetic-history", "branchy-history", "requests", "itsdangerous"]
SKIP_GAPS = IGNORED_GAPS | {"unsupported_question"}


def run_question(name: str, q: dict, keys: dict, clone: Clone, cfg) -> tuple[dict, dict]:
    from rw.repo.investigate import investigate
    graph = SETS[name][2]
    rev = q.get("revision")
    plan = keys["e2_retrieval_plans"].get(q["id"], [])
    calls = [("raw", q["question"])] + [("plan", t) for t in plan]
    trace, used = [], []
    t0 = time.perf_counter()
    for kind, text in calls:
        t1 = time.perf_counter()
        try:
            r = investigate(cfg.name, rev, text, graph_name=graph, config=cfg).to_dict()
            err = None
        except Exception as exc:  # recorded, never hidden
            r, err = None, f"{type(exc).__name__}: {exc}"
        dt = time.perf_counter() - t1
        trace.append({"kind": kind, "query": text, "revision": rev, "seconds": round(dt, 4), "error": err,
                      "result": r})
        if r is None:
            continue
        unsupported = any(g["kind"] == "unsupported_question" for g in r["gaps"])
        if kind == "raw" and unsupported and plan:
            continue
        used.append(r)
    latency = time.perf_counter() - t0
    texts, cits_raw, gap_kinds, unresolved = [], [], [], None
    for r in used:
        if r.get("unresolved"):
            unresolved = unresolved or r["unresolved"]
            texts.append("UNRESOLVED: " + r["unresolved"])
        for f in r["findings"]:
            texts.append(f["summary"])
        for g in r["gaps"]:
            gap_kinds.append(g["kind"])
            texts.append(f"GAP {g['kind']}: {g['detail']}")
        for c in r["citations"]:
            cits_raw.append({"path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"],
                             "revision": c["commit"], "repo": c["repo"]})
    seen, uniq = set(), []
    for c in cits_raw:
        k = (c["path"], c["start_line"], c["end_line"], c["revision"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    allowed = allowed_shas(clone, q)
    cits = []
    for c in uniq:
        cc = check_citation(clone, c, allowed, rev)
        if c["repo"] != cfg.name:
            cc["valid"], cc["why"] = False, f"citation names repo {c['repo']!r}"
        cits.append(cc)
    answer = "\n".join(texts)
    structural = {"unresolved": unresolved, "gap_kinds": [g for g in gap_kinds if g not in SKIP_GAPS]
                  if q["category"] == "missing_evidence" else gap_kinds}
    correct, decision = answer_check(q, answer, cits, keys,
                                     structural=structural if q["category"] in ("ambiguous", "missing_evidence")
                                     else None)
    recall, precision = evidence_scores(cits, q, clone)
    wrong = [c for c in cits if not c["requested_revision_match"]]
    task = {"repo": name, "question_id": q["id"], "category": q["category"], "revision": rev,
            "contestant": "deterministic_retrieval", "answer": answer, "answer_correct": correct,
            "answer_decision": decision, "grounded_answer_correct": grounded(q, correct, recall, cits),
            "evidence_recall": recall, "evidence_precision": precision,
            "expected_citations": expected_citations(q), "citations": cits,
            "citation_validity": (sum(c["valid"] for c in cits) / len(cits)) if cits else None,
            "wrong_revision_citations": len(wrong), "wrong_revision": bool(wrong),
            "fabricated_citations": len(fabricated(cits)), "gap_kinds": gap_kinds, "unresolved": unresolved,
            "queries_used": len(used), "tokens": 0, "tool_calls": len(calls), "latency_s": round(latency, 4),
            "context_limit": False, "budget_exhausted": False, "infra_error": any(t["error"] for t in trace)}
    return task, {"repo": name, "question_id": q["id"], "calls": trace}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def metrics(tasks: list[dict]) -> dict:
    cits = [c for t in tasks for c in t["citations"]]
    return {"n_tasks": len(tasks),
            "answer_accuracy": _mean([float(t["answer_correct"]) for t in tasks]),
            "grounded_answer_accuracy": _mean([float(t["grounded_answer_correct"]) for t in tasks]),
            "evidence_recall": _mean([t["evidence_recall"] for t in tasks]),
            "evidence_precision": _mean([t["evidence_precision"] for t in tasks]),
            "citation_validity": round(sum(c["valid"] for c in cits) / len(cits), 4) if cits else None,
            "citations": len(cits),
            "wrong_revision": sum(t["wrong_revision"] for t in tasks),
            "wrong_revision_citations": sum(t["wrong_revision_citations"] for t in tasks),
            "tokens": 0, "tool_calls": _mean([t["tool_calls"] for t in tasks]),
            "latency_s": _mean([t["latency_s"] for t in tasks]), "cost_usd": 0.0,
            "context_limit_failures": 0, "infra_errors": sum(t["infra_error"] for t in tasks),
            "by_category": {cat: {"n": len(ts), "answer_accuracy": _mean([float(t["answer_correct"]) for t in ts]),
                                  "evidence_recall": _mean([t["evidence_recall"] for t in ts])}
                            for cat in sorted({t["category"] for t in tasks})
                            for ts in [[t for t in tasks if t["category"] == cat]]}}


def latest_e4() -> Path | None:
    files = sorted((ROOT / "artifacts" / "repo_benefit").glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    from rw.repo.config import load_config
    started = now_iso()
    ts = stamp()
    keys = load_keys()
    runs, traces, failures = [], [], []
    manifests, coverage, configs = [], {"gaps": [], "limits": []}, {}
    qsets = {n: load_questions(n) for n in NAMES}
    for n in NAMES:
        cfg_path = SETS[n][1]
        configs[n] = {"file": rel(cfg_path), "sha256": sha256_file(cfg_path),
                      "config": json.loads(Path(cfg_path).read_text(encoding="utf-8")), "graph": SETS[n][2]}
        revs = set().union(*(question_revs(q) for q in qsets[n]["questions"]))
        manifests.append(manifest_for(n, revs))
        missing = sorted(r for r in revs if r not in manifests[-1]["revisions"])
        if missing:
            coverage["gaps"].append({"repo": n, "kind": "revision_not_in_clone", "revisions": missing})
    for rep in range(REPEATS):
        tasks = []
        for n in NAMES:
            cfg = load_config(SETS[n][1])
            clone = Clone(SETS[n][3])
            for q in qsets[n]["questions"]:
                try:
                    task, tr = run_question(n, q, keys, clone, cfg)
                except Exception as exc:
                    failures.append(f"repeat {rep} {q['id']}: {type(exc).__name__}: {exc}")
                    continue
                task["repeat"] = rep
                tasks.append(task)
                if rep == 0:
                    traces.append(tr)
        runs.append({"repeat": rep, "tasks": tasks})
    # determinism across repeats
    sig = lambda t: (t["question_id"], t["answer"], json.dumps(t["citations"], sort_keys=True))  # noqa: E731
    deterministic = [sig(t) for t in runs[0]["tasks"]] == [sig(t) for t in runs[-1]["tasks"]]
    tasks0 = runs[0]["tasks"]
    per_repo = {n: metrics([t for t in tasks0 if t["repo"] == n]) for n in NAMES}
    overall = metrics(tasks0)
    # graph coverage gaps for the evaluated revisions (S4: explicit gaps, not silent)
    from rw.repo.query import RepoQuery
    for n in NAMES:
        q = RepoQuery(SETS[n][2], load_config(SETS[n][1]).name)
        for r in sorted(set().union(*(question_revs(x) for x in qsets[n]["questions"]))):
            _, gap = q.resolve(r)
            if gap:
                coverage["gaps"].append({"repo": n, "revision": r, "kind": gap.kind, "detail": gap.detail})
    coverage["limits"] = ["investigate() answers only fixed question shapes (rw.repo.investigate.SUPPORTED); "
                          "held-out questions are mapped to them by the declared e2_retrieval_plans",
                          "finding summaries carry symbol names, spans and change lists, not source text, so "
                          "facts that live only in code text (constants, literals) cannot appear in E2 answers",
                          "python adapter only; non-Python files (CHANGES.rst etc.) are indexed as release notes "
                          "or reported UNSUPPORTED_LANGUAGE; Python 2 files that fail to parse are extraction errors"]
    idx = sorted((ROOT / "artifacts" / "repo_eval_index").glob("*.json"))
    indexing_cost = {"records": [rel(p) for p in idx] + [rel(p) for p in sorted((ROOT / "artifacts" / "repo_scale").glob("*.json"))[-1:]],
                     "per_repo": {}}
    for p in idx:
        d = json.loads(p.read_text(encoding="utf-8"))
        indexing_cost["per_repo"][d["repo"]] = {"seconds": d["metrics"].get("seconds"),
                                                "peak_rss_bytes": d["metrics"].get("peak_rss_bytes"),
                                                "tags": d.get("tags"), "commits": d.get("commits"), "tokens": 0}
    traces_path = OUT / "traces" / f"{ts}.json"
    traces_path.parent.mkdir(parents=True, exist_ok=True)
    traces_path.write_text(json.dumps(traces, indent=1, default=str), encoding="utf-8")
    config_blob = json.dumps(configs, sort_keys=True)
    rec = {
        "schema": "repo_history_eval/v1", "evidence": "E2", "status": "complete",
        "started_at": started, "finished_at": now_iso(),
        "command": "PYTHONPATH=src .venv/Scripts/python.exe evals/repo_history_eval.py",
        "llm_used": False, "scored": True,
        "manifest": {"repos": manifests}, "coverage": coverage,
        "config": configs, "config_sha256": sha256_text(config_blob),
        "keys_file": rel(KEYS_PATH), "keys_sha256": sha256_file(KEYS_PATH),
        "question_files": [{"repo": n, "path": f"evals/repo_questions/{SETS[n][0]}",
                            "sha256": sha256_file(ROOT / 'evals' / 'repo_questions' / SETS[n][0])} for n in NAMES],
        "traces_path": rel(traces_path),
        "answers": [{"repo": t["repo"], "question_id": t["question_id"], "answer": t["answer"],
                     "answer_correct": t["answer_correct"]} for t in tasks0],
        "timings": {"per_task_latency_s": {f"{t['repo']}/{t['question_id']}": t["latency_s"] for t in tasks0},
                    "mean_latency_s": overall["latency_s"]},
        "usage": {"llm_tokens": 0, "investigate_calls": sum(t["tool_calls"] for t in tasks0)},
        "scoring": {"answer_rule": load_keys()["answer_rule"],
                    "evidence": "recall = fraction of expected citations overlapped by a returned citation (same "
                                "path, same resolved revision sha, intersecting line spans); precision = fraction "
                                "of returned citations overlapping some expected citation; scored separately from "
                                "the answer",
                    "citation_validity": "git rev-parse of the citation revision in the requested clone, path "
                                         "exists there (git show sha:path), 1 <= start <= end <= file length, "
                                         "citation repo equals the requested repo",
                    "wrong_revision": "a citation whose resolved sha is not the requested, compare or an "
                                      "expected-citation revision; `wrong_revision` counts tasks with any",
                    "grounded": "answer correct AND evidence_recall > 0 (missing_evidence without expected "
                                "citations: answer correct and no fabricated citation)",
                    "decisions": [{"question_id": t["question_id"], "answer_correct": t["answer_correct"],
                                   "decision": t["answer_decision"]} for t in tasks0]},
        "repeats": REPEATS, "deterministic_across_repeats": deterministic,
        "e2_contestant": "deterministic_retrieval (rw.repo.investigate, mode=retrieval, no LLM)",
        "results": {"per_repo": per_repo, "overall": overall},
        "records": tasks0,
        "runs": runs, "indexing_cost": indexing_cost, "failures": failures,
    }
    out = OUT / f"{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
    print(rel(out))
    for n, m in {**per_repo, "overall": overall}.items():
        print(f"{n:18s} ans={m['answer_accuracy']} grounded={m['grounded_answer_accuracy']} "
              f"recall={m['evidence_recall']} prec={m['evidence_precision']} valid={m['citation_validity']} "
              f"wrong_rev={m['wrong_revision']} n={m['n_tasks']}")
    print("deterministic:", deterministic, "failures:", failures)
    return 0


if __name__ == "__main__":
    if "--round" in sys.argv and sys.argv[sys.argv.index("--round") + 1] in ("2", "3"):
        from repo_history_round2 import main2
        sys.exit(main2(metrics, int(sys.argv[sys.argv.index("--round") + 1])))
    sys.exit(main())
