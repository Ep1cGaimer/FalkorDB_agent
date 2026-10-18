"""E3 (S4) scale and update measurement on a real repository, against declared budgets.

Budgets and the corpus are declared in evals/repo_budgets.json BEFORE measuring; this script only reads
that file (its sha256 is recorded in the output) and never changes it.

Protocol (all on the local FalkorDB at 127.0.0.1:6379):
 1. Corpus: tags of the clone matching corpus.tag_pattern, ordered by version. Initial import = all
    but the newest N=5 tags; update = all tags (the newest 5 are new). Indexed files: Python sources
    (*.py, *.pyi) plus release notes (HISTORY*); languages=["python"].
 2. Initial index and update into the measured graph (default rw_repo_requests, recreated), each with
    its IndexReport metrics (wall seconds, tracemalloc peak, blob reuse, node/edge counts).
 3. Index size: `GRAPH.MEMORY USAGE <graph>` (FalkorDB >= 4.10, total_graph_sz_mb, MB -> bytes); if the
    command is unavailable, Redis `MEMORY USAGE <key> SAMPLES 0`. The method used is recorded.
 4. Peak memory: max over both runs of the process peak working set / RSS (Windows psapi
    GetProcessMemoryInfo via ctypes, POSIX getrusage), which covers C buffers too; tracemalloc peaks
    (Python heap) are recorded alongside. Compared to peak_memory_mb_max.
 5. Query workload (fixed, declared here in WORKLOAD_DOC, limit = budgets.query_page_limit), latency
    per call with time.perf_counter on a fresh RepoQuery (cold per-revision caches).
 6. Truncation: pages with more results behind a cursor, and pages with a TRUNCATED gap.
 7. Failures: every exception or unexpected gap from the workload, recorded with its call.
 8. Interrupted import on a scratch graph: interrupt after INTERRUPT_AFTER new blobs, check that
    queries show INCOMPLETE_IMPORT with no items, resume, check COMPLETE and answers.
 9. Invalidation on the measured graph: for files changed / deleted between two revisions (per git),
    the new revision cites the new content hash (sha256 of `git show rev:path`) or nothing for a
    deleted file, while the old revision still cites the old content.
10. Plaintext size: bytes/4 over every selected revision's indexed Python source plus the commit
    messages (history text) of all reachable commits, against context_budget.tokens.

Every attempt is recorded: a completed measurement goes to artifacts/repo_scale/<timestamp>.json (even
when budgets are missed); a crashed attempt goes to artifacts/repo_scale/attempts/<timestamp>.json.
Each record also carries the E5 reproducibility keys (evals/REPRODUCIBILITY.md): command, manifest
(repo + resolved shas), coverage (gaps/limits), config + config_sha256, traces_path (sidecar
artifacts/repo_scale/traces/<timestamp>.json with every workload call's raw result), answers, timings,
llm_used=false, scored=false.

    .venv\\Scripts\\python.exe evals\\repo_scale.py [--graph rw_repo_requests]
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import statistics
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rw import graph as G  # noqa: E402
from rw.repo.config import RepoConfig  # noqa: E402
from rw.repo.git import GitRepo  # noqa: E402
from rw.repo.index import ImportInterrupted, index_repository, _peak_rss_bytes  # noqa: E402
from rw.repo.query import RepoQuery  # noqa: E402

BUDGETS = ROOT / "evals" / "repo_budgets.json"
OUT_DIR = ROOT / "artifacts" / "repo_scale"
TRACE_DIR = OUT_DIR / "traces"
UPDATE_TAGS = 5
INTERRUPT_AFTER = 300
INCLUDE = ["*.py", "*.pyi", "HISTORY*"]
WORKLOAD_DOC = (
    "For 8 revisions evenly spaced over the selected tags (always including the oldest and newest): "
    "symbols(rev) first 3 pages; symbols(rev, name='Session'); dependencies(<Session>.request, hops=2) "
    "and dependents(<Session>.request, hops=1), up to 3 pages each; changes_between(previous sampled "
    "rev, rev) up to 3 pages; fix_status(rev, F) where F is the newest non-merge commit touching the "
    "package before the oldest sampled tag. Plus symbol_history(<Session>.request of the newest tag, "
    "all selected tags) once. All with limit = budgets.query_page_limit.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _version_key(name: str):
    return tuple(int(x) for x in re.findall(r"\d+", name))


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return s[k]


def _jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _cfg_dict(cfg) -> dict:
    if hasattr(cfg, "model_dump"):
        return cfg.model_dump(mode="json")
    return _jsonable(cfg)


def _command() -> list[str]:
    return [sys.executable, *sys.argv]


def _graph_size(db, graph_name: str) -> tuple[int, str, object]:
    r = db.connection
    try:
        raw = r.execute_command("GRAPH.MEMORY", "USAGE", graph_name)
        flat = {}
        if isinstance(raw, (list, tuple)):
            for i in range(0, len(raw) - 1, 2):
                k = raw[i].decode() if isinstance(raw[i], bytes) else str(raw[i])
                flat[k] = raw[i + 1]
        elif isinstance(raw, dict):
            flat = {(k.decode() if isinstance(k, bytes) else k): v for k, v in raw.items()}
        mb = float(flat["total_graph_sz_mb"])
        return int(mb * 1024 * 1024), "GRAPH.MEMORY USAGE total_graph_sz_mb", {
            k: (v.decode() if isinstance(v, bytes) else v) for k, v in flat.items()}
    except Exception as e:  # older FalkorDB: Redis key memory usage
        n = r.execute_command("MEMORY", "USAGE", graph_name, "SAMPLES", "0")
        return int(n), f"MEMORY USAGE SAMPLES 0 (GRAPH.MEMORY unavailable: {e})", None


def _plaintext(git: GitRepo, tags: list, include: list[str]) -> dict:
    import fnmatch
    src_bytes = 0
    for t in tags:
        out = git._text("ls-tree", "-r", "-l", "-z", "--full-tree", t.target_sha)
        for entry in out.split("\x00"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            _mode, otype, _sha, size = meta.split()
            if otype == "blob" and path.endswith((".py", ".pyi")):
                src_bytes += int(size)
    history = git._bytes("log", "--format=%H%n%an%n%at%n%B", *[t.target_sha for t in tags], "--")
    return {"python_source_bytes_all_selected_revisions": src_bytes, "history_text_bytes": len(history),
            "plaintext_tokens": (src_bytes + len(history)) // 4,
            "method": "bytes/4 of every selected tag's .py/.pyi blobs (git ls-tree -l sizes) plus "
                      "`git log --format=%H%n%an%n%at%n%B` over all reachable commits"}


class Workload:
    def __init__(self, q: RepoQuery, limit: int):
        self.q, self.limit = q, limit
        self.latencies: list[float] = []
        self.calls: list[dict] = []
        self.traces: list[dict] = []
        self.failures: list[dict] = []
        self.truncated_pages = 0
        self.truncated_gap_pages = 0
        self.pages = 0

    def call(self, label: str, fn, *, expect_gaps: tuple = ()):
        t = time.perf_counter()
        try:
            res = fn()
        except Exception as e:  # recorded, never hidden
            ms = (time.perf_counter() - t) * 1000
            self.latencies.append(ms)
            self.failures.append({"call": label, "error": f"{type(e).__name__}: {e}"})
            self.calls.append({"call": label, "ms": round(ms, 2), "ok": False})
            self.traces.append({"call": label, "ms": round(ms, 2), "error": f"{type(e).__name__}: {e}"})
            return None
        ms = (time.perf_counter() - t) * 1000
        self.latencies.append(ms)
        entry = {"call": label, "ms": round(ms, 2), "ok": True}
        cov = getattr(res, "coverage", None)
        if cov is not None:
            self.pages += 1
            kinds = [g.kind for g in cov.get("gaps", [])]
            entry.update(items=len(res.items), total=cov.get("total"), truncated=res.truncated, gaps=kinds)
            self.truncated_pages += int(bool(res.truncated))
            self.truncated_gap_pages += int("TRUNCATED" in kinds)
            bad = [k for k in kinds if k not in expect_gaps + ("TRUNCATED",)]
            if bad:
                self.failures.append({"call": label, "error": f"unexpected gaps {bad}"})
                entry["ok"] = False
        self.calls.append(entry)
        self.traces.append({"call": label, "ms": round(ms, 2), "result": _jsonable(res)})
        return res

    def pages_of(self, label: str, fn, max_pages: int = 3, **kw):
        cursor, out = None, []
        for i in range(max_pages):
            page = self.call(f"{label} page {i + 1}", lambda: fn(limit=self.limit, cursor=cursor), **kw)
            if page is None:
                break
            out.append(page)
            cursor = page.next_cursor
            if cursor is None:
                break
        return out


def _session_symbol(q: RepoQuery, rev: str) -> str | None:
    page = q.symbols(rev, name="Session", limit=50)
    for it in page.items:
        if it.kind == "class" and it.path.endswith("sessions.py"):
            return it.qualname
    return None


def run_workload(q: RepoQuery, git: GitRepo, tags: list, limit: int) -> tuple[Workload, dict]:
    w = Workload(q, limit)
    idx = sorted({round(i * (len(tags) - 1) / 7) for i in range(8)})
    sample = [tags[i].name for i in idx]
    fix = git._text("log", "-1", "--no-merges", "--format=%H", tags[idx[0]].target_sha, "--",
                    "requests", "src/requests").strip()
    prev = None
    for rev in sample:
        w.pages_of(f"symbols({rev})", lambda **kw: q.symbols(rev, **kw))
        w.call(f"symbols({rev}, name=Session)", lambda: q.symbols(rev, name="Session", limit=limit))
        sess = _session_symbol(q, rev)
        if sess is None:
            w.failures.append({"call": f"resolve Session at {rev}", "error": "Session class not found"})
        else:
            w.pages_of(f"dependencies({rev}, {sess}.request, hops=2)",
                       lambda **kw: q.dependencies(rev, f"{sess}.request", hops=2, **kw))
            w.pages_of(f"dependents({rev}, {sess}.request, hops=1)",
                       lambda **kw: q.dependents(rev, f"{sess}.request", hops=1, **kw))
        if prev:
            w.pages_of(f"changes_between({prev}, {rev})", lambda **kw: q.changes_between(prev, rev, **kw))
        w.call(f"fix_status({rev}, {fix[:12]})", lambda: q.fix_status(rev, fix))
        prev = rev
    sess = _session_symbol(q, tags[-1].name)
    if sess:
        hist = w.call(f"symbol_history({sess}.request, {len(tags)} tags)",
                      lambda: q.symbol_history(f"{sess}.request", [t.name for t in tags]))
        if hist is not None and len(hist) != len(tags):
            w.failures.append({"call": "symbol_history", "error": "entry count != requested revisions"})
    return w, {"sampled_revisions": sample, "fix_commit": fix, "description": WORKLOAD_DOC}


def check_invalidation(q: RepoQuery, git: GitRepo, old_rev: str, new_rev: str, max_files: int = 10) -> dict:
    old_sha, new_sha = git.resolve(old_rev), git.resolve(new_rev)
    changes = [c for c in git.changes(old_sha, new_sha)
               if (c.old_path or c.new_path or "").endswith(".py")]
    checks, ok = [], True
    cache: dict[str, list] = {}

    def all_syms(rev):
        if rev not in cache:
            cache[rev] = [i for p in _pages(lambda **kw: q.symbols(rev, **kw)) for i in p.items]
        return cache[rev]
    for ch in changes[:max_files]:
        if ch.status == "M":
            path = ch.new_path
            new_hash = hashlib.sha256(git._bytes("show", f"{new_sha}:{path}")).hexdigest()
            old_hash = hashlib.sha256(git._bytes("show", f"{old_sha}:{path}")).hexdigest()
            new_items = [i for i in all_syms(new_rev) if i.path == path]
            old_items = [i for i in all_syms(old_rev) if i.path == path]
            good = (bool(new_items) and all(i.citation.content_hash == new_hash for i in new_items)
                    and bool(old_items) and all(i.citation.content_hash == old_hash for i in old_items)
                    and all(i.citation.commit == new_sha for i in new_items))
            checks.append({"path": path, "status": "M", "passed": good, "new_symbols": len(new_items),
                           "old_symbols": len(old_items)})
        elif ch.status in ("D", "R"):
            path = ch.old_path
            new_items = [i for i in all_syms(new_rev) if i.path == path]
            old_items = [i for i in all_syms(old_rev) if i.path == path]
            good = not new_items and bool(old_items)
            checks.append({"path": path, "status": ch.status, "passed": good, "new_symbols": len(new_items),
                           "old_symbols": len(old_items)})
        else:
            continue
        ok = ok and checks[-1]["passed"]
    return {"old": old_rev, "new": new_rev, "python_changes": len(changes), "checked": checks,
            "passed": ok and bool(checks)}


def _pages(fn, limit: int = 200, max_pages: int = 1000):
    cursor = None
    for _ in range(max_pages):
        page = fn(limit=limit, cursor=cursor)
        yield page
        cursor = page.next_cursor
        if cursor is None:
            return


def measure(args, budgets: dict, budgets_sha: str, stamp: str) -> dict:
    corpus = budgets["corpus"]
    bud = budgets["budgets"]
    limit = bud["query_page_limit"]
    repo_path = ROOT / corpus["path"]
    git = GitRepo(repo_path)
    pat = re.compile(corpus["tag_pattern"])
    tags = sorted([t for t in git.tags() if pat.search(t.name)], key=lambda t: _version_key(t.name))
    initial_tags, update_tags = tags[:-UPDATE_TAGS], tags[-UPDATE_TAGS:]
    mk = lambda ts: RepoConfig(name=args.repo_name, path=str(repo_path), revisions=[t.name for t in ts],  # noqa: E731
                               languages=corpus["languages"], include=INCLUDE)
    db = G.connect()
    full_cfg = _cfg_dict(mk(tags))
    cfg_bytes = json.dumps(full_cfg, sort_keys=True).encode()
    out: dict = {"started_at": stamp, "command": _command(), "llm_used": False, "scored": False,
                 "budgets_file": str(BUDGETS.relative_to(ROOT)),
                 "budgets_sha256": budgets_sha, "graph": args.graph,
                 "manifest": {"repo": args.repo_name, "repository": corpus["repository"],
                              "revisions": {t.name: t.target_sha for t in tags}},
                 "config": {"initial": _cfg_dict(mk(initial_tags)), "update": full_cfg,
                            "update_tags": UPDATE_TAGS, "interrupt_after_blobs": INTERRUPT_AFTER},
                 "config_sha256": hashlib.sha256(cfg_bytes).hexdigest()}
    plain = _plaintext(git, tags, INCLUDE)
    out["corpus"] = {"repository": corpus["repository"], "path": corpus["path"],
                     "selected_revisions": len(tags), "initial_revisions": len(initial_tags),
                     "update_revisions": [t.name for t in update_tags],
                     "total_commits_reachable": len(git._text("rev-list", *[t.target_sha for t in tags],
                                                              "--").split()),
                     "include": INCLUDE, **plain,
                     "context_budget_tokens": budgets["context_budget"]["tokens"]}

    try:
        db.select_graph(args.graph).delete()
    except Exception:
        pass
    init = index_repository(mk(initial_tags), graph_name=args.graph, db=db)
    upd = index_repository(mk(tags), graph_name=args.graph, db=db)
    keep = ("seconds", "peak_memory_bytes", "peak_rss_bytes", "phase_seconds", "blobs_new", "blobs_reused",
            "commits", "symbols", "relations", "nodes", "edges", "coverage_gaps", "extraction_errors")
    out["initial_index"] = {"status": init.status, "tags": init.tags, **{k: init.metrics.get(k) for k in keep}}
    out["update"] = {"status": upd.status, "tags": upd.tags, **{k: upd.metrics.get(k) for k in keep}}
    size, method, detail = _graph_size(db, args.graph)
    out["index_size_bytes"] = size
    out["index_size_method"] = method
    out["index_size_detail"] = detail

    q = RepoQuery(args.graph, args.repo_name, db=db)
    w, wl = run_workload(q, git, tags, limit)
    lat = w.latencies
    out["query_workload"] = wl
    out["query_latency_ms"] = {"count": len(lat), "p50": round(_pct(lat, 50), 2),
                               "p95": round(_pct(lat, 95), 2), "max": round(max(lat), 2),
                               "mean": round(statistics.fmean(lat), 2), "page_limit": limit}
    out["query_calls"] = w.calls
    out["answers"] = w.calls
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_file = TRACE_DIR / f"{stamp}.json"
    trace_file.write_text(json.dumps(w.traces, default=str), encoding="utf-8")
    out["traces_path"] = trace_file.relative_to(ROOT).as_posix()
    out["truncation"] = {"truncated_pages": w.truncated_pages, "pages": w.pages,
                         "truncated_gap_pages": w.truncated_gap_pages,
                         "note": "truncated_pages = pages with a next_cursor (more results behind the "
                                 "page); truncated_gap_pages = traversals cut by the edge bound"}
    failures = list(w.failures)

    inv_update = check_invalidation(q, git, initial_tags[-1].name, tags[-1].name)
    inv_wide = check_invalidation(q, git, tags[0].name, tags[-1].name)
    out["invalidation"] = {"passed": inv_update["passed"] and inv_wide["passed"],
                           "update_pair": inv_update, "wide_pair": inv_wide}

    # interrupted import on a scratch graph (same full corpus)
    scratch = f"rw_scale_scratch_{uuid.uuid4().hex[:10]}"
    ii = {"graph": scratch, "interrupt_after_blobs": INTERRUPT_AFTER, "interrupted": False,
          "partial_presented_complete": None, "recovered": False, "final_status": None}
    try:
        try:
            index_repository(mk(tags), graph_name=scratch, db=db, interrupt_after=INTERRUPT_AFTER)
        except ImportInterrupted:
            ii["interrupted"] = True
        sq = RepoQuery(scratch, args.repo_name, db=db)
        shown = []
        for rev in (tags[0].name, tags[-1].name):
            page = sq.symbols(rev, limit=limit)
            kinds = [g.kind for g in page.coverage.get("gaps", [])]
            shown.append({"rev": rev, "items": len(page.items), "gaps": kinds})
        ii["before_resume"] = shown
        ii["partial_presented_complete"] = any(s["items"] or "INCOMPLETE_IMPORT" not in s["gaps"] for s in shown)
        statuses = [r[0] for r in db.select_graph(scratch).query("MATCH (r:ImportRun) RETURN r.status").result_set]
        ii["statuses_before_resume"] = statuses
        t = time.perf_counter()
        res = index_repository(mk(tags), graph_name=scratch, db=db)
        ii["resume_seconds"] = round(time.perf_counter() - t, 3)
        ii["resume_blobs_new"], ii["resume_blobs_reused"] = res.blobs_new, res.blobs_reused
        ii["final_status"] = res.status
        sq2 = RepoQuery(scratch, args.repo_name, db=db)
        after = sq2.symbols(tags[-1].name, limit=limit)
        main_total = q.symbols(tags[-1].name, limit=limit).coverage.get("total")
        ii["after_resume_total_symbols"] = after.coverage.get("total")
        ii["clean_total_symbols"] = main_total
        ii["recovered"] = res.status == "COMPLETE" and bool(after.items) and \
            after.coverage.get("total") == main_total
    except Exception as e:
        failures.append({"call": "interrupted_import", "error": f"{type(e).__name__}: {e}"})
    finally:
        try:
            db.select_graph(scratch).delete()
        except Exception:
            pass
    out["interrupted_import"] = ii
    out["failures"] = failures

    rss = [m.get("peak_rss_bytes") or 0 for m in (init.metrics, upd.metrics)] + [_peak_rss_bytes() or 0]
    trace = [m.get("peak_memory_bytes") or 0 for m in (init.metrics, upd.metrics)]
    out["peak_memory_bytes"] = int(max(rss) or max(trace))
    out["peak_memory_method"] = ("process peak working set / RSS (psapi GetProcessMemoryInfo or getrusage), "
                                 "max over the whole measurement process; tracemalloc peaks per run in "
                                 "peak_memory_tracemalloc_bytes")
    out["peak_memory_tracemalloc_bytes"] = {"initial_index": trace[0], "update": trace[1]}

    mb = 1024 * 1024
    out["budgets_met"] = {
        "initial_index_seconds_max": init.metrics["seconds"] <= bud["initial_index_seconds_max"],
        "update_seconds_max": upd.metrics["seconds"] <= bud["update_seconds_max"],
        "peak_memory_mb_max": out["peak_memory_bytes"] / mb <= bud["peak_memory_mb_max"],
        "query_latency_p95_ms_max": out["query_latency_ms"]["p95"] <= bud["query_latency_p95_ms_max"],
        "index_size_mb_max": size / mb <= bud["index_size_mb_max"],
        "failures_max": len(failures) <= bud.get("failures_max", 0),
        "context_budget_exceeded": out["corpus"]["plaintext_tokens"] > budgets["context_budget"]["tokens"],
    }
    out["all_budgets_met"] = all(out["budgets_met"].values())
    from rw.repo.adapters import ADAPTERS
    out["coverage"] = {
        "gaps": {"initial_index": [_jsonable(g) for g in init.coverage_gaps],
                 "update": [_jsonable(g) for g in upd.coverage_gaps]},
        "extraction_errors": {"initial_index": _count(init.metrics.get("extraction_errors")),
                              "update": _count(upd.metrics.get("extraction_errors"))},
        "limits": {"query_page_limit": limit, "max_pages_per_query": 3, "include": INCLUDE,
                   "languages": corpus["languages"],
                   "adapter_limitations": {k: list(getattr(a, "LIMITS", []) or [])
                                           for k, a in ADAPTERS.items()}}}
    out["finished_at"] = _now()
    out["timings"] = {"started_at": stamp, "finished_at": out["finished_at"],
                      "initial_index_seconds": init.metrics.get("seconds"),
                      "update_seconds": upd.metrics.get("seconds"),
                      "query_latency_ms": out["query_latency_ms"]}
    return out


def _count(value) -> int:
    """Extraction errors are recorded either as a count or as a list of messages."""
    return value if isinstance(value, int) else len(value or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--graph", default="rw_repo_requests")
    ap.add_argument("--repo-name", default="requests")
    args = ap.parse_args()
    raw = BUDGETS.read_bytes()
    budgets, sha = json.loads(raw), hashlib.sha256(raw).hexdigest()
    stamp = _now()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        out = measure(args, budgets, sha, stamp)
    except BaseException as e:
        att = OUT_DIR / "attempts"
        att.mkdir(parents=True, exist_ok=True)
        path = att / f"{stamp}.json"
        path.write_text(json.dumps({"started_at": stamp, "command": _command(), "budgets_sha256": sha,
                                    "llm_used": False, "scored": False, "status": "FAILED",
                                    # the run crashed before these were assembled; keys kept, values null
                                    "manifest": None, "coverage": None, "config_sha256": None,
                                    "traces_path": None, "answers": None, "timings": None,
                                    "missing_fields": ["manifest", "coverage", "config_sha256", "traces_path",
                                                       "traces", "answers", "timings"],
                                    "error": f"{type(e).__name__}: {e} (run crashed; manifest, coverage, "
                                             "config_sha256, traces, answers and timings were not recorded)",
                                    "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
        print(f"attempt FAILED, recorded in {path}")
        raise
    path = OUT_DIR / f"{stamp}.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("budgets_met", "query_latency_ms", "index_size_bytes",
                                          "peak_memory_bytes")}, indent=2))
    print(f"initial {out['initial_index']['seconds']}s update {out['update']['seconds']}s "
          f"tokens {out['corpus']['plaintext_tokens']} failures {len(out['failures'])}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
