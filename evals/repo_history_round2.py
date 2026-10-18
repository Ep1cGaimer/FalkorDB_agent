"""Round-2 E2 mode for evals/repo_history_eval.py (`--round 2`): held-out questions in
evals/repo_questions/round2/*.json, answers scored by comparing RepoFindings.facts with expected_facts
(rule in evals/repo_eval_keys_round2.json `facts_rule`), evidence scored separately, every citation
checked with read-only git. Deterministic, no LLM."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from repo_eval_common import (ROOT, SETS, Clone, allowed_shas, check_citation, evidence_scores,
                              expected_citations, fabricated, manifest_for, now_iso, question_revs, rel,
                              sha256_file, sha256_text, stamp, failed_task, grounded)

R2DIR = ROOT / "evals" / "repo_questions" / "round2"
KEYS2 = ROOT / "evals" / "repo_eval_keys_round2.json"
OUT = ROOT / "artifacts" / "repo_history_eval"
REPEATS = 3
# round-2 file -> question-set name used in SETS
FILES = {"requests.json": "requests", "itsdangerous.json": "itsdangerous", "synthetic.json": "round2-synthetic"}
for _r in (2, 3):
    SETS.setdefault(f"round{_r}-synthetic", (f"round{_r}/synthetic.json", ROOT / "evals" / "repo_eval_configs" / f"round{_r}-synthetic.json",
                                             f"rw_repo_round{_r}-synthetic", ROOT / "artifacts" / "question_repos" / f"round{_r}-synthetic"))
SHA_KEYS = {"fix_commit", "removing_commit"}
SHA_RX = re.compile(r"^[0-9a-f]{7,40}$")


def _name_ok(exp: str, got: str) -> bool:
    return got == exp or got.endswith("." + exp)


def _scalar_ok(key: str, exp, got) -> bool:
    if isinstance(exp, str) and isinstance(got, str):
        if key in SHA_KEYS or (SHA_RX.match(exp) and SHA_RX.match(got)):
            return exp.startswith(got) or got.startswith(exp)
        if "." in exp or "." in got:
            return _name_ok(exp, got) if not re.match(r"^v?\d", exp) else exp == got
        return exp == got
    if isinstance(exp, (list, tuple)) or isinstance(got, (list, tuple)):
        return isinstance(got, (list, tuple)) and isinstance(exp, (list, tuple)) and list(exp) == list(got)
    if isinstance(exp, bool) or isinstance(got, bool):
        return exp is got
    return exp == got


def _item_ok(exp, got) -> bool:
    if isinstance(exp, dict):
        return isinstance(got, dict) and all(k in got and _scalar_ok(k, v, got[k]) for k, v in exp.items())
    if isinstance(exp, str) and isinstance(got, str):
        return _name_ok(exp, got)
    if isinstance(exp, str) and isinstance(got, dict):
        return any(_name_ok(exp, str(got.get(k))) for k in ("name", "qualname", "target") if got.get(k))
    return exp == got


def compare_facts(expected: dict, got: dict) -> tuple[bool, list[dict]]:
    checks = []
    for k, exp in expected.items():
        if k.endswith("_include"):
            base = k[: -len("_include")]
            pool = got.get("targets") if base == "resolved_targets" else None
            if pool is None:
                pool = got.get(base)
            ok = isinstance(pool, list) and all(any(_item_ok(e, g) for g in pool) for e in exp)
            checks.append({"key": k, "expected": exp, "got": pool, "ok": ok, "rule": "subset"})
            continue
        if k not in got:
            checks.append({"key": k, "expected": exp, "got": None, "ok": False, "rule": "missing key"})
            continue
        g = got[k]
        if k == "value":
            g2 = list(g) if isinstance(g, tuple) else g
            ok = _scalar_ok(k, exp, g2)
            rule = "value =="
        elif isinstance(exp, list):
            ok = isinstance(g, list) and all(any(_item_ok(e, x) for x in g) for e in exp) and \
                all(any(_item_ok(e, x) for e in exp) for x in g)
            rule = "set equality"
        else:
            ok = _scalar_ok(k, exp, g)
            rule = "scalar"
        checks.append({"key": k, "expected": exp, "got": g, "ok": ok, "rule": rule})
    return all(c["ok"] for c in checks), checks


def _q(name, q, clone, cfg, graph):
    from rw.repo.investigate import investigate
    rev = q.get("revision")
    calls = [("raw", q["question"])]
    trace, used = [], []
    t0 = time.perf_counter()
    for kind, text in calls:
        t1 = time.perf_counter()
        try:
            r, err = investigate(cfg.name, rev, text, graph_name=graph, config=cfg).to_dict(), None
        except Exception as exc:
            r, err = None, f"{type(exc).__name__}: {exc}"
        trace.append({"kind": kind, "query": text, "revision": rev, "seconds": round(time.perf_counter() - t1, 4),
                      "error": err, "result": r})
        if r is None:
            continue
        used.append(r)
    facts = {}
    for r in used:
        for k, v in (r.get("facts") or {}).items():
            facts.setdefault(k, v)
    raw, seen = [], set()
    for r in used:
        for c in r["citations"]:
            k = (c["path"], c["start_line"], c["end_line"], c["commit"])
            if k not in seen:
                seen.add(k)
                raw.append(c)
    allowed = allowed_shas(clone, q)
    cits = []
    for c in raw:
        cc = check_citation(clone, {"path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"],
                                    "revision": c["commit"]}, allowed, rev)
        if c["repo"] != cfg.name:
            cc["valid"], cc["why"] = False, f"citation names repo {c['repo']!r}"
        cits.append(cc)
    correct, checks = compare_facts(q["expected_facts"], facts)
    recall, precision = evidence_scores(cits, q, clone)
    wrong = [c for c in cits if not c["requested_revision_match"]]
    task = {"repo": name, "question_id": q["id"], "category": q["category"], "revision": rev,
            "contestant": "deterministic_retrieval", "facts": facts, "expected_facts": q["expected_facts"],
            "fact_checks": checks, "answer": " ".join(r.get("answer") or "" for r in used).strip(),
            "answer_correct": bool(correct),
            "grounded_answer_correct": grounded(q, correct, recall, cits),
            "evidence_recall": recall, "evidence_precision": precision,
            "expected_citations": expected_citations(q), "citations": cits,
            "citation_validity": (sum(c["valid"] for c in cits) / len(cits)) if cits else None,
            "wrong_revision_citations": len(wrong), "wrong_revision": bool(wrong),
            "fabricated_citations": len(fabricated(cits)),
            "gap_kinds": [g["kind"] for r in used for g in r["gaps"]],
            "unresolved": next((r["unresolved"] for r in used if r.get("unresolved")), None),
            "tokens": 0, "tool_calls": len(calls), "latency_s": round(time.perf_counter() - t0, 4),
            "context_limit": False, "infra_error": any(t["error"] for t in trace)}
    return task, {"repo": name, "question_id": q["id"], "calls": trace}


def main2(metrics, rnd: int = 2) -> int:
    """Round 2 or 3 (same schema and facts rule; questions, plans and synthetic repo per round)."""
    global R2DIR, KEYS2, FILES
    R2DIR = ROOT / "evals" / "repo_questions" / f"round{rnd}"
    KEYS2 = ROOT / "evals" / f"repo_eval_keys_round{rnd}.json"
    FILES = {"requests.json": "requests", "itsdangerous.json": "itsdangerous", "synthetic.json": f"round{rnd}-synthetic"}
    from rw.repo.config import load_config
    started, ts = now_iso(), stamp()
    keys = json.loads(KEYS2.read_text(encoding="utf-8"))
    manifest_doc = json.loads((R2DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    qsets = {n: json.loads((R2DIR / f).read_text(encoding="utf-8")) for f, n in FILES.items()}
    failures, mismatch = [], []
    qfiles = []
    for f, n in FILES.items():
        h = sha256_file(R2DIR / f)
        mh = manifest_doc["files"][f]["sha256"]
        if h != mh:
            mismatch.append(f"{f}: sha256 {h} != MANIFEST {mh}")
        qfiles.append({"repo": n, "path": f"evals/repo_questions/round{rnd}/{f}", "sha256": h, "manifest_sha256": mh})
    if mismatch:
        failures.extend(mismatch)
    runs, traces = [], []
    for rep in range(REPEATS):
        tasks = []
        for n, d in qsets.items():
            cfg = load_config(SETS[n][1])
            clone = Clone(SETS[n][3])
            for q in d["questions"]:
                try:
                    t, tr = _q(n, q, clone, cfg, SETS[n][2])
                except Exception as exc:
                    error = f"repeat {rep} {q['id']}: {type(exc).__name__}: {exc}"
                    failures.append(error)
                    t = {**failed_task(n, q, error), "facts": {}, "expected_facts": q["expected_facts"], "fact_checks": []}
                    tr = {"repo": n, "question_id": q["id"], "error": error, "calls": []}
                t["repeat"] = rep
                tasks.append(t)
                traces.append({"repeat": rep, **tr})
        runs.append({"repeat": rep, "tasks": tasks})
    sig = lambda t: (t["question_id"], json.dumps(t["facts"], sort_keys=True, default=str),  # noqa: E731
                     json.dumps(t["citations"], sort_keys=True))
    deterministic = [sig(t) for t in runs[0]["tasks"]] == [sig(t) for t in runs[-1]["tasks"]]
    tasks0 = runs[0]["tasks"]
    names = list(qsets)
    all_tasks = [t for r in runs for t in r["tasks"]]
    per_repo = {n: metrics([t for t in all_tasks if t["repo"] == n]) for n in names}
    overall = metrics(all_tasks)
    configs = {n: {"file": rel(SETS[n][1]), "sha256": sha256_file(SETS[n][1]), "graph": SETS[n][2],
                   "config": json.loads(Path(SETS[n][1]).read_text(encoding="utf-8"))} for n in names}
    coverage = {"gaps": [], "limits": [
        "investigate() answers fixed question shapes only; oracle retrieval plans are never executed",
        "python adapter only; Python 2 files that fail to parse have no symbols"]}
    from rw.repo.query import RepoQuery
    for n in names:
        rq = RepoQuery(SETS[n][2], load_config(SETS[n][1]).name)
        for r in sorted(set().union(*(question_revs(x) for x in qsets[n]["questions"]))):
            _, gap = rq.resolve(r)
            if gap:
                coverage["gaps"].append({"repo": n, "revision": r, "kind": gap.kind, "detail": gap.detail})
    traces_path = OUT / "traces" / f"{ts}-round{rnd}.json"
    traces_path.parent.mkdir(parents=True, exist_ok=True)
    traces_path.write_text(json.dumps(traces, indent=1, default=str), encoding="utf-8")
    rec = {
        "schema": "repo_history_eval/v2-development", "acceptance_validated": False, "evidence": "E2", "round": rnd, "status": "complete",
        "started_at": started, "finished_at": now_iso(),
        "command": "PYTHONPATH=src .venv/Scripts/python.exe evals/repo_history_eval.py --round " + str(rnd),
        "llm_used": False, "scored": True,
        "manifest": {"repos": [manifest_for(n, set().union(*(question_revs(q) for q in qsets[n]["questions"])))
                               for n in names]},
        "coverage": coverage, "config": configs, "config_sha256": sha256_text(json.dumps(configs, sort_keys=True)),
        "keys_file": rel(KEYS2), "keys_sha256": sha256_file(KEYS2),
        "question_files": qfiles, "question_manifest": f"evals/repo_questions/round{rnd}/MANIFEST.json",
        "investigate_sha256": sha256_file(ROOT / "src" / "rw" / "repo" / "investigate.py"),
        "traces_path": rel(traces_path),
        "answers": [{"repo": t["repo"], "question_id": t["question_id"], "facts": t["facts"],
                     "answer": t["answer"], "answer_correct": t["answer_correct"]} for t in tasks0],
        "timings": {"per_task_latency_s": {f"{t['repo']}/{t['question_id']}": t["latency_s"] for t in tasks0},
                    "mean_latency_s": overall["latency_s"]},
        "usage": {"llm_tokens": 0, "investigate_calls": sum(t["tool_calls"] for t in tasks0)},
        "scoring": {"answer_rule": keys["facts_rule"],
                    "evidence": "recall = fraction of expected citations overlapped by a returned citation (same "
                                "path, same resolved sha, intersecting spans); precision = fraction of returned "
                                "citations overlapping an expected one; scored separately from the answer",
                    "citation_validity": "revision resolves in the requested clone, path exists there, 1 <= start "
                                         "<= end <= file length, citation repo is the requested repo",
                    "wrong_revision": "citations whose resolved sha is not the requested, compare or an expected-"
                                      "citation revision; `wrong_revision` counts tasks with any",
                    "grounded": "answer correct AND evidence_recall == 1 AND no invalid/wrong-revision citation (questions without expected citations: answer correct and no fabricated citation)",
                    "decisions": [{"question_id": t["question_id"], "answer_correct": t["answer_correct"],
                                   "fact_checks": t["fact_checks"]} for t in tasks0]},
        "repeats": REPEATS, "deterministic_across_repeats": deterministic,
        "results": {"per_repo": per_repo, "overall": overall},
        "records": tasks0, "runs": runs, "failures": failures,
    }
    out = OUT / f"{ts}.json"
    out.write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
    print(rel(out))
    for n, m in {**per_repo, "overall": overall}.items():
        print(f"{n:18s} ans={m['answer_accuracy']} grounded={m['grounded_answer_accuracy']} "
              f"recall={m['evidence_recall']} prec={m['evidence_precision']} valid={m['citation_validity']} "
              f"wrong_rev={m['wrong_revision']} n={m['n_tasks']}")
    print("deterministic:", deterministic, "failures:", failures)
    return 0
