"""Index a configured Git repository into its own FalkorDB graph (schema: docs/plans/repo-integration-v1.md).

Content is keyed by sha256 of blob bytes: each distinct blob is extracted once per run, and blobs
already extracted by the same adapter version in an earlier run are reused (incremental indexing).
Ingestion only reads git objects; repository code is never imported or executed.

Large-history design (S4/E3):
- Every reachable commit keeps a full per-revision file map (HAS_FILE edges), so any commit sha can be
  queried. Maps are derived from ONE `git log --raw --diff-merges=first-parent` pass (each commit =
  first parent's map + its first-parent diff), not one `ls-tree` per commit.
- Blobs are read through one streamed `git cat-file --batch`; blobs whose git sha is already stored
  with the current extractor identity are not read at all. Writes are batched UNWIND queries
  (BLOB_BATCH blobs per flush, CHUNK rows per query).
- Commits whose file map is fully written carry `files_done=true`; later runs (updates, resumes) only
  write file maps for new commits. A commit interrupted mid-write has its partial HAS_FILE/HAS_NOTE
  edges deleted and rewritten. Each run still links (ImportRun)-[:INDEXED]->(Commit) for all its
  commits; queries only trust commits linked from the currently published COMPLETE run.
- A renewable, fenced import lease excludes other writers. The Repository publication is STARTED
  before mutation and COMPLETE only after all writes. Queries reject an unfinished publication.
- Re-extraction clears `extracted_by` before deleting old symbols; interruption cannot leave a
  reusable completion marker over missing facts. Changed extraction configuration rebuilds file maps."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
import tracemalloc
import uuid
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rw import graph as G
from rw.repo.adapters import adapter_for
from rw.repo.config import RepoConfig
from rw.repo.git import GitRepo
from rw.repo.model import Gap

CHUNK = 1000
BLOB_BATCH = 200
IMPORT_LEASE_SECONDS = 120


class ImportInterrupted(RuntimeError):
    """Raised by the `interrupt_after` test hook; the ImportRun stays STARTED (not COMPLETE)."""


@dataclass
class IndexReport:
    repo: str
    graph_name: str
    import_run_id: str
    status: str
    commits: int = 0
    tags: int = 0
    blobs: int = 0
    blobs_new: int = 0
    blobs_reused: int = 0
    symbols: int = 0
    relations: int = 0
    extraction_errors: list[str] = field(default_factory=list)
    coverage_gaps: list[Gap] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def graph_name_for(config: RepoConfig) -> str:
    return f"rw_repo_{config.name}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches(path: str, globs: list[str]) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(path, g) or fnmatch.fnmatchcase(base, g) for g in globs)


def _write(graph, cypher: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        graph.query(cypher, {"rows": rows[i:i + CHUNK]})


def _read_all(graph, cypher: str, page: int = 5000) -> list:
    """All rows of an ORDER BY query in pages (the server caps result-set size)."""
    out, off = [], 0
    while True:
        rows = graph.query(cypher + " SKIP $o LIMIT $l", {"o": off, "l": page}).result_set
        out.extend(rows)
        if len(rows) < page:
            return out
        off += page


def _ensure_indexes(graph) -> None:
    for label, prop in [("Repository", "name"), ("Commit", "sha"), ("Tag", "name"),
                        ("Blob", "content_hash"), ("Symbol", "id"), ("ReleaseNote", "id"),
                        ("ImportRun", "id"), ("Blob", "git_sha")]:
        try:
            graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception:
            pass  # already exists


def select_revisions(config: RepoConfig, git: GitRepo) -> tuple[list[str], list]:
    tags = git.tags()
    if config.tag_pattern:
        pat = re.compile(config.tag_pattern)
        tags = [t for t in tags if pat.search(t.name)]
    else:
        tags = [t for t in tags if t.name in config.revisions]
    revs = list(dict.fromkeys(list(config.revisions) + [t.target_sha for t in tags]))
    return revs, tags


def index_repository(config: RepoConfig, graph_name: str | None = None, db=None, *,
                     interrupt_after: int | None = None) -> IndexReport:
    """Serialize writers across processes; a crashed writer's lease expires automatically.

    Queries reject an in-progress/failed publication. Retry is the recovery operation; no
    previous snapshot is served while shared extraction facts might have been changed.
    """
    db = db or G.connect()
    graph_name = graph_name or graph_name_for(config)
    lock = db.connection.lock(f"rw:repo-import:{graph_name}", timeout=IMPORT_LEASE_SECONDS, thread_local=False)
    if not lock.acquire(blocking=False):
        raise RuntimeError("repository import already in progress; retry after it finishes")
    stop, lost = threading.Event(), threading.Event()

    def renew():
        while not stop.wait(IMPORT_LEASE_SECONDS / 4):
            try:
                lock.extend(IMPORT_LEASE_SECONDS, replace_ttl=True)
            except Exception:
                lost.set()
                return

    heartbeat = threading.Thread(target=renew, daemon=True)
    heartbeat.start()
    try:
        return _index_repository(config, graph_name, db, interrupt_after=interrupt_after,
                                 lease_lost=lost, lease=lock)
    finally:
        stop.set()
        heartbeat.join(timeout=5)
        from redis.exceptions import LockNotOwnedError
        try:
            lock.release()
        except LockNotOwnedError:
            if not lost.is_set():
                raise


def _index_repository(config: RepoConfig, graph_name: str, db, *,
                      lease_lost: threading.Event, lease,
                     interrupt_after: int | None = None) -> IndexReport:
    """Index `config` into `graph_name`. See the module docstring for the storage/performance design."""
    graph_name = graph_name or graph_name_for(config)
    db = db or G.connect()
    underlying = db.select_graph(graph_name)
    def fenced_execute(*command, **kwargs):
        # WATCH + EXEC makes lease validation atomic with the actual GRAPH command. A paused
        # writer cannot resume after lease expiry and mutate a newer writer's publication.
        # A renewal changes the watched key's TTL without changing its owner. EXEC
        # aborts without running the command; retry that case under a fresh WATCH.
        from redis.exceptions import WatchError
        for _ in range(8):
            try:
                with db.connection.pipeline() as pipe:
                    pipe.watch(lease.name)
                    owner = pipe.get(lease.name)
                    owner = owner.encode() if isinstance(owner, str) else owner
                    if lease_lost.is_set() or owner != lease.local.token:
                        lease_lost.set()
                        raise RuntimeError("repository import lease lost; retry import")
                    pipe.multi()
                    pipe.execute_command(*command, **kwargs)
                    return pipe.execute()[0]
            except WatchError:
                # Re-entering checks the token atomically with the next command;
                # a successor's token is rejected before any write can execute.
                continue
        raise RuntimeError("repository import lease contention; retry import")

    underlying.execute_command = fenced_execute

    class LeasedGraph:
        def query(self, *args, **kwargs):
            if lease_lost.is_set():
                raise RuntimeError("repository import lease lost; retry import")
            return underlying.query(*args, **kwargs)

    graph = LeasedGraph()
    git = GitRepo(config.path)
    run_id = uuid.uuid4().hex
    report = IndexReport(config.name, graph_name, run_id, "STARTED")
    t0 = time.perf_counter()
    tracing = not tracemalloc.is_tracing()
    if tracing:
        tracemalloc.start()

    _ensure_indexes(graph)
    fingerprint = hashlib.sha256(json.dumps({
        "schema": 2, "include": config.include, "exclude": config.exclude,
        "languages": config.languages, "release_notes": config.release_notes,
    }, sort_keys=True).encode()).hexdigest()
    previous = graph.query("MATCH (r:Repository {name:$name}) RETURN r.config_hash",
                           {"name": config.name}).result_set
    graph.query("MERGE (r:Repository {name:$name}) SET r.path=$path, r.status='STARTED', r.generation=$id",
                {"name": config.name, "path": str(config.path), "id": run_id})
    graph.query("CREATE (:ImportRun {id:$id, repo:$repo, status:'STARTED', started_at:$t})",
                {"id": run_id, "repo": config.name, "t": _now()})
    phases: dict[str, float] = {}
    try:
        if not previous or previous[0][0] != fingerprint:
            graph.query("MATCH (c:Commit) SET c.files_done=null")
        tp = time.perf_counter()
        revs, tags = select_revisions(config, git)
        commits = git.commits(revs)
        report.commits, report.tags = len(commits), len(tags)
        done_commits = {r[0] for r in _read_all(
            graph, "MATCH (c:Commit) WHERE c.files_done = true RETURN c.sha ORDER BY c.sha")}
        todo = [c for c in commits if c.sha not in done_commits]

        _write(graph, "UNWIND $rows AS row MERGE (c:Commit {sha:row.sha}) "
                      "SET c.author_time=row.author_time, c.subject=row.subject, c.message=row.message, "
                      "c.repo=row.repo",
               [{"sha": c.sha, "author_time": c.author_time, "subject": c.subject,
                 "message": c.message, "repo": config.name} for c in todo])
        _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.c}), (p:Commit {sha:row.p}) "
                      "MERGE (c)-[e:PARENT {order:row.order}]->(p)",
               [{"c": c.sha, "p": p, "order": i} for c in todo for i, p in enumerate(c.parents)])
        # Tags are mutable aliases, replaced as a set while the publication is unavailable.
        graph.query("MATCH (t:Tag) DETACH DELETE t")
        _write(graph, "UNWIND $rows AS row MERGE (t:Tag {name:row.name}) SET t.message=row.message "
                      "WITH t, row MATCH (c:Commit {sha:row.sha}) MERGE (t)-[:POINTS_TO]->(c)",
               [{"name": t.name, "sha": t.target_sha, "message": t.message} for t in tags])
        phases["commits"] = time.perf_counter() - tp

        # ---- file maps of every reachable commit, from ONE first-parent `git log --raw` pass
        tp = time.perf_counter()
        todo_set = {c.sha for c in todo}
        children: dict[str, int] = {}
        first_parent: dict[str, str | None] = {}
        for c in commits:
            first_parent[c.sha] = c.parents[0] if c.parents else None
            if c.parents:
                children[c.parents[0]] = children.get(c.parents[0], 0) + 1
        maps: dict[str, dict[str, str]] = {}
        blob_first_path: dict[str, str] = {}          # git blob sha -> first path seen (adapter choice)
        file_rows: list[tuple[str, dict[str, str]]] = []
        for sha, changes in git.first_parent_changes(revs):
            p = first_parent.get(sha)
            if p is not None:
                base = maps.get(p, {})
                children[p] -= 1
                if children[p] <= 0:
                    maps.pop(p, None)
                    cur = base
                else:
                    cur = dict(base)
            else:
                cur = {}
            for status, path, bsha, mode in changes:
                if status == "D" or mode == "160000" or set(bsha) == {"0"}:
                    cur.pop(path, None)
                    continue
                if config.include and not _matches(path, config.include):
                    cur.pop(path, None)
                    continue
                if config.exclude and _matches(path, config.exclude):
                    cur.pop(path, None)
                    continue
                cur[path] = bsha
            if children.get(sha, 0) > 0:
                maps[sha] = cur
            for path, bsha in cur.items():
                first = blob_first_path.setdefault(bsha, path)
                if adapter_for(first, config.languages) is None and adapter_for(path, config.languages) is not None:
                    blob_first_path[bsha] = path
            if sha in todo_set:
                file_rows.append((sha, dict(cur) if sha in maps else cur))
        del maps
        for path in sorted({path for _, m in file_rows for path in m} | set(blob_first_path.values())):
            if adapter_for(path, config.languages) is None:
                report.coverage_gaps.append(Gap("UNSUPPORTED_LANGUAGE", path))
        phases["file_maps"] = time.perf_counter() - tp

        # ---- blobs: reuse those already extracted by the same extractor, read the rest in one stream
        tp = time.perf_counter()
        known: dict[str, tuple[str, str | None]] = {
            r[0]: (r[1], r[2]) for r in _read_all(
                graph, "MATCH (b:Blob) WHERE b.git_sha IS NOT NULL "
                       "RETURN b.git_sha, b.content_hash, b.extracted_by ORDER BY b.git_sha")}
        hash_of: dict[str, str] = {}
        to_read: list[str] = []
        for bsha, path in blob_first_path.items():
            extractor = _extractor(adapter_for(path, config.languages))
            if bsha in known and known[bsha][1] == extractor:
                hash_of[bsha] = known[bsha][0]
                report.blobs_reused += 1
            else:
                to_read.append(bsha)
        batch = _BlobBatch(graph, config, report)
        for bsha, data in git.blob_batch(to_read):
            if interrupt_after is not None and report.blobs_new >= interrupt_after:
                batch.flush()
                raise ImportInterrupted(f"interrupted after {interrupt_after} blobs")
            path = blob_first_path[bsha]
            chash = hashlib.sha256(data).hexdigest()
            hash_of[bsha] = chash
            batch.add(chash, bsha, path, data, adapter_for(path, config.languages), stale=bsha in known)
            report.blobs_new += 1
        batch.flush()
        phases["blobs"] = time.perf_counter() - tp

        # ---- per-commit file maps (HAS_FILE) and release notes, only for commits not yet stored
        tp = time.perf_counter()
        partial = {r[0] for r in _read_all(
            graph, "MATCH (c:Commit)-[:HAS_FILE|HAS_NOTE]->() WHERE c.files_done IS NULL "
                   "RETURN DISTINCT c.sha ORDER BY c.sha")}
        for i in range(0, len(file_rows), 200):
            part = file_rows[i:i + 200]
            shas = [{"sha": s} for s, _ in part]
            # drop partial writes of an interrupted earlier run before (re)writing these commits
            dirty = [r for r in shas if r["sha"] in partial]
            _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.sha})-[f:HAS_FILE]->() DELETE f", dirty)
            _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.sha})-[f:HAS_NOTE]->() DELETE f", dirty)
            files, notes = [], []
            for sha, m in part:
                for path, bsha in m.items():
                    chash = hash_of[bsha]
                    files.append({"sha": sha, "h": chash, "path": path})
                    if _matches(path, config.release_notes):
                        notes.append({"sha": sha, "id": f"{config.name}:{chash}:{path}", "path": path,
                                      "h": chash})
            _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.sha}), (b:Blob {content_hash:row.h}) "
                          "CREATE (c)-[:HAS_FILE {path:row.path}]->(b)", files)
            _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.sha}) "
                          "MERGE (n:ReleaseNote {id:row.id}) SET n.path=row.path, n.content_hash=row.h "
                          "CREATE (c)-[:HAS_NOTE]->(n)", notes)
            _write(graph, "UNWIND $rows AS row MATCH (c:Commit {sha:row.sha}) SET c.files_done = true", shas)
        phases["file_edges"] = time.perf_counter() - tp

        tp = time.perf_counter()
        _write(graph, "UNWIND $rows AS row MATCH (r:ImportRun {id:row.run}), (c:Commit {sha:row.sha}) "
                      "CREATE (r)-[:INDEXED]->(c)", [{"run": run_id, "sha": c.sha} for c in commits])
        phases["indexed"] = time.perf_counter() - tp
        report.blobs = len(blob_first_path)
        report.status = "COMPLETE"
    except BaseException:
        report.status = "FAILED"
        _finish(graph, report, t0, tracing, final_status=None if interrupt_after is not None else "FAILED",
                phases=phases)
        raise
    _finish(graph, report, t0, tracing, final_status="COMPLETE", phases=phases)
    graph.query("MATCH (r:Repository {name:$name}) SET r.status='COMPLETE', r.published_run=$id, "
                "r.config_hash=$h", {"name": config.name, "id": run_id, "h": fingerprint})
    return report


def _extractor(adapter) -> str:
    """Extractor identity `<language>@<adapter.version>` (instance attribute); "none" = no adapter."""
    return f"{adapter.language}@{adapter.version}" if adapter else "none"


class _BlobBatch:
    """Buffers extracted blobs and writes them with a few UNWIND queries per BLOB_BATCH blobs.

    A blob being (re)extracted first loses its previous Symbols (DETACH DELETE: their outgoing
    relation edges go with them; only same-blob edges point at a blob's own symbols), so a new
    extractor version never leaves stale relations behind. `extracted_by` is set last, so a blob
    interrupted mid-write is re-extracted by the next run."""

    def __init__(self, graph, config, report):
        self.graph, self.config, self.report = graph, config, report
        self.blobs: list[dict] = []
        self.stale: list[dict] = []
        self.syms: list[dict] = []
        self.rels: dict[str, list[dict]] = {}

    def add(self, chash, bsha, path, data, adapter, stale: bool = True) -> None:
        lines = data.decode("utf-8", "replace").splitlines()
        row = {"h": chash, "g": bsha, "lang": adapter.language if adapter else None, "size": len(data),
               "n": max(len(lines), 1), "x": _extractor(adapter), "errors": 0}
        self.blobs.append(row)
        if stale:  # a Blob node already exists: earlier symbols must go (deletes are costly; only then)
            self.stale.append({"h": chash})
        if adapter is not None:
            ex = adapter.extract(path, data)
            row["errors"] = len(ex.errors)
            self.report.extraction_errors.extend(ex.errors)
            sid = lambda q: f"{self.config.name}:{chash}:{q}"  # noqa: E731
            defs = {}
            for s in ex.symbols:  # duplicate qualnames (e.g. property setters): last definition wins
                defs[s.qualname] = {
                    "h": chash, "id": sid(s.qualname), "q": s.qualname, "kind": s.kind,
                    "sl": s.start_line, "el": s.end_line, "path": path,
                    "th": hashlib.sha256("\n".join(lines[s.start_line - 1:s.end_line])
                                         .encode("utf-8")).hexdigest()}
            self.syms.extend(defs.values())
            seen = set()
            for r in ex.relations:
                if r.source not in defs:
                    continue
                key = (r.kind, r.source, r.target, r.provenance, r.extractor, r.relative_target)
                if key in seen:
                    continue
                seen.add(key)
                local = r.target in defs
                tid = sid(r.target) if local else f"{self.config.name}:ref:{r.target}"
                self.rels.setdefault(r.kind, []).append(
                    {"src": sid(r.source), "tid": tid, "tq": r.target, "local": local,
                     "relative": r.relative_target,
                     "prov": r.provenance, "ext": r.extractor})
            self.report.symbols += len(ex.symbols)
            self.report.relations += len(ex.relations)
        if len(self.blobs) >= BLOB_BATCH:
            self.flush()

    def flush(self) -> None:
        if not self.blobs:
            return
        g = self.graph
        # Clear the completion marker BEFORE the first destructive write. A retry must never
        # reuse a blob whose old symbols were removed by an interrupted re-extraction.
        _write(g, "UNWIND $rows AS row MATCH (b:Blob {content_hash:row.h}) "
                  "SET b.extracted_by=null", self.stale)
        _write(g, "UNWIND $rows AS row MATCH (:Blob {content_hash:row.h})-[:DEFINES]->(s:Symbol) "
                  "DETACH DELETE s", self.stale)
        _write(g, "UNWIND $rows AS row MERGE (b:Blob {content_hash:row.h}) SET b.git_sha=row.g, "
                  "b.language=row.lang, b.size=row.size, b.lines=row.n, b.extracted_by=null", self.blobs)
        _write(g, "UNWIND $rows AS row MATCH (b:Blob {content_hash:row.h}) "
                  "CREATE (b)-[:DEFINES]->(:Symbol {id:row.id, qualname:row.q, kind:row.kind, "
                  "start_line:row.sl, end_line:row.el, content_hash:row.h, first_path:row.path, "
                  "text_hash:row.th})", self.syms)
        for kind, rows in self.rels.items():
            # unresolved / out-of-blob targets are placeholder Symbols{external:true}; resolution
            # against other blobs of the same revision happens at query time.
            local = [r for r in rows if r["local"]]
            ext = [r for r in rows if not r["local"]]
            _write(g, "UNWIND $rows AS row MATCH (s:Symbol {id:row.src}), (t:Symbol {id:row.tid}) "
                      f"CREATE (s)-[:{kind} {{provenance:row.prov, extractor:row.ext, relative_target:row.relative}}]->(t)", local)
            _write(g, "UNWIND $rows AS row MATCH (s:Symbol {id:row.src}) MERGE (t:Symbol {id:row.tid}) "
                      "ON CREATE SET t.qualname=row.tq, t.external=true "
                      f"CREATE (s)-[:{kind} {{provenance:row.prov, extractor:row.ext, relative_target:row.relative}}]->(t)", ext)
        _write(g, "UNWIND $rows AS row MATCH (b:Blob {content_hash:row.h}) "
                  "SET b.extracted_by=row.x, b.errors=row.errors", self.blobs)
        self.blobs, self.stale, self.syms, self.rels = [], [], [], {}


def _peak_rss_bytes() -> int | None:
    """Peak resident set size of this process (Windows: psapi GetProcessMemoryInfo via ctypes;
    POSIX: getrusage ru_maxrss). Includes the interpreter and C-level buffers, unlike tracemalloc."""
    try:
        import sys
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return int(pmc.PeakWorkingSetSize)
            return None
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss if sys.platform == "darwin" else rss * 1024)
    except Exception:
        return None


def _finish(graph, report: IndexReport, t0: float, tracing: bool, final_status: str | None,
            phases: dict | None = None) -> None:
    peak = tracemalloc.get_traced_memory()[1] if tracemalloc.is_tracing() else None
    if tracing:
        tracemalloc.stop()
    report.metrics = {"seconds": round(time.perf_counter() - t0, 3), "peak_memory_bytes": peak,
                      "peak_rss_bytes": _peak_rss_bytes(),
                      "phase_seconds": {k: round(v, 3) for k, v in (phases or {}).items()},
                      "blobs_new": report.blobs_new, "blobs_reused": report.blobs_reused,
                      "commits": report.commits, "symbols": report.symbols,
                      "relations": report.relations, "coverage_gaps": len(report.coverage_gaps),
                      "extraction_errors": len(report.extraction_errors)}
    try:
        stats = graph.query("MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[e]->() "
                            "RETURN nodes, count(e)").result_set[0]
        report.metrics.update(nodes=stats[0], edges=stats[1])
    except Exception:
        pass
    params = {"id": report.import_run_id, "t": _now(), "m": json.dumps(report.metrics)}
    if final_status == "FAILED":
        graph.query("MATCH (r:Repository {name:$name, generation:$id}) SET r.status='FAILED'",
                    {"name": report.repo, "id": report.import_run_id})
    if final_status:
        params["s"] = final_status
        graph.query("MATCH (r:ImportRun {id:$id}) SET r.status=$s, r.finished_at=$t, r.metrics_json=$m",
                    params)
    else:  # interrupted: leave STARTED so it is never presented as complete
        graph.query("MATCH (r:ImportRun {id:$id}) SET r.metrics_json=$m", params)
