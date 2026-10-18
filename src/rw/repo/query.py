"""Bounded, read-only evidence queries over a per-repository graph (docs/repo/DESIGN.md).

Every query resolves the requested revision in the current COMPLETE publication, then reads
that commit's file map (HAS_FILE{path} -> Blob) and the symbols/relations of those blobs.

Bounds: `symbols` pages server-side (Cypher ORDER BY/SKIP/LIMIT plus a count query) and `symbol_history`
reads only candidate symbols, so neither builds a whole-revision snapshot. Dependency walks need the
revision's relation set for cross-file resolution (cached per commit) and stop collecting after
MAX_WALK_EDGES edges, reporting Gap("TRUNCATED") and coverage["frontier_truncated"]. `changes_between`
diffs file maps and loads symbols only for changed files. Ancestry uses `git merge-base`/`rev-list`
when the clone is available (graph PARENT walk otherwise). Cursors bind offsets to graph/repository/revision/query/publication identity; a negative,
malformed or past-the-end cursor raises ValueError or yields a Gap("INVALID_CURSOR") page. Relation
targets are resolved at query time against the symbols defined at the SAME revision (cross-file);
anything else is reported as external. Citations always name the requested commit."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from functools import wraps
import re
from collections import deque
from dataclasses import dataclass, field
from redis.exceptions import TimeoutError as RedisTimeoutError

from rw import graph as G
from rw.repo.adapters.python import module_name
from rw.repo.adapters import ADAPTERS, adapter_for
from rw.repo.git import GitError, GitRepo
import difflib

from rw.repo.model import Citation, FixStatus, Gap, Page
from rw.repo.budget import BudgetExhausted, ReadLimits, active_budget, read_scope
from rw.repo.source import source_lines

MAX_LIMIT = 200
MAX_HOPS = 5
MAX_ANCESTRY = 100_000
MAX_PATCH_CANDIDATES = 300
MAX_WALK_EDGES = 10_000
RESULT_PAGE = 5000  # below the server RESULTSET_SIZE cap (10000 on the local FalkorDB)
SHA_RE = re.compile(r"^[0-9a-f]{4,40}$")


@dataclass
class SymbolItem:
    id: str
    qualname: str
    kind: str
    path: str
    citation: Citation


@dataclass
class DependencyItem:
    source: str
    target: str
    kind: str
    provenance: str
    extractor: str
    hops: int
    external: bool
    citation: Citation | None
    target_citation: Citation | None


@dataclass
class ChangeItem:
    path: str
    status: str
    old_path: str | None
    symbols_added: list[str] = field(default_factory=list)
    symbols_removed: list[str] = field(default_factory=list)
    symbols_modified: list[str] = field(default_factory=list)
    citation: Citation | None = None
    kinds: dict = field(default_factory=dict)       # qualname -> symbol kind (both sides)
    similarity: int | None = None                   # rename similarity percent
    old_citation: Citation | None = None            # the file at A (modified/renamed files)


@dataclass
class NoteItem:
    path: str
    text: str
    citation: Citation


@dataclass
class HistoryEntry:
    rev: str
    commit: str | None
    present: bool | None
    content_hash: str | None
    citation: Citation | None
    gap: Gap | None = None


@dataclass
class _Sym:
    qualname: str
    kind: str
    path: str
    content_hash: str
    start_line: int
    end_line: int
    text_hash: str | None
    stored_qualname: str


def _encode(offset: int, scope: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([offset, scope]).encode()).decode()


def _decode(cursor: str | None, scope: str) -> int:
    if not cursor:
        return 0
    if not isinstance(cursor, str) or len(cursor) > 2048:
        raise ValueError("invalid cursor")
    try:
        off, bound = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
        if bound == scope and type(off) is int and off >= 0:
            return off
    except Exception:
        pass
    raise ValueError("invalid cursor")


def _limit(limit: int) -> int:
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be in 1..{MAX_LIMIT}")
    return limit


def _bad_offset(off: int, total: int) -> Page | None:
    """A cursor past the end of the result is reported, never answered with a silent empty page."""
    if off > 0 and off >= total:
        return Page([], None, False, {"total": total, "offset": off, "returned": 0, "gaps": [
            Gap("INVALID_CURSOR", f"cursor offset {off} is beyond the result ({total} items)")]})
    return None


def _page(items: list, limit: int, cursor: str | None, coverage: dict, *, total: int | None = None,
          off: int | None = None, scope: str) -> Page:
    """Page over `items`; with `total`/`off` given, `items` is already the server-side page."""
    limit = _limit(limit)
    if off is None:
        off = _decode(cursor, scope)
    if total is None:
        total = len(items)
        items = items[off:off + limit]
    bad = _bad_offset(off, total)
    if bad:
        return bad
    more = off + limit < total
    coverage = {"total": total, "offset": off, "returned": len(items), **coverage}
    coverage.setdefault("gaps", [])
    return Page(items, _encode(off + limit, scope) if more else None, more, coverage)


class IndexChangedError(RuntimeError):
    """The index changed during a read; the caller must restart the investigation."""


class EvidenceError(RuntimeError):
    """An indexed fact cannot be bound to current extraction and immutable source bytes."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.gap = Gap(kind, detail)


def _consistent(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        def failed(gap, budget=None):
            if method.__name__ == "resolve":
                return None, gap
            if method.__name__ == "fix_status":
                return FixStatus("UNCERTAIN", [], [gap], gap.detail)
            if method.__name__ == "symbol_history":
                revs = kwargs.get("revs", args[1] if len(args) > 1 else [])
                return [HistoryEntry(rev, None, None, None, None, gap) for rev in revs]
            page = self._gap_page(gap)
            if budget is not None:
                page.truncated = True
                page.coverage.update(complete=False, budget=budget)
            return page

        with read_scope(getattr(self, "limits", None)) as budget:
            try:
                before = self._state()
                self._begin_read()
                result = method(self, *args, **kwargs)
                if self._state() != before:
                    self._snap.clear()
                    self._fmap.clear()
                    raise IndexChangedError("repository index changed during retrieval; retry from the first page")
                budget.remaining()
                return result
            except EvidenceError as exc:
                return failed(exc.gap)
            except BudgetExhausted as exc:
                return failed(Gap("RETRIEVAL_BUDGET_EXHAUSTED", str(exc)), exc.coverage)
    return call


def _rebase(stored_q: str, stored_path: str | None, path: str) -> str:
    """Qualnames are stored relative to the blob's first path; rebase onto the path at this revision."""
    if not stored_path or not stored_path.endswith((".py", ".pyi")):
        return stored_q
    old, new = module_name(stored_path), module_name(path)
    if old == new:
        return stored_q
    if stored_q == old:
        return new
    if stored_q.startswith(old + "."):
        return new + stored_q[len(old):]
    return stored_q


class RepoQuery:
    def __init__(self, graph_name: str, repo_name: str, db=None, *, trace: list[dict] | None = None,
                 limits: ReadLimits | None = None):
        self.repo = repo_name
        self.limits = limits or (active_budget().limits if active_budget() else ReadLimits())
        self.db = db or G.connect(socket_timeout=min(2.0, self.limits.seconds))
        self.graph = self.db.select_graph(graph_name)
        self._snap: dict[str, tuple] = {}
        self._fmap: dict[str, dict] = {}
        self._repo_path: str | None | bool = False
        self._trees: dict[str, dict] = {}
        self._source_bytes: dict[str, bytes] = {}
        self.trace = trace

    def _begin_read(self):
        # Graph caches are scoped to one operation. Even controlled edge/source ablations
        # without an ImportRun update must affect the next result from this query object.
        self._snap = {}
        self._fmap = {}
        self._trees = {}
        self._source_bytes = {}
        self._repo_path = False

    # ------------------------------------------------------------ plumbing
    def _q(self, cypher: str, params: dict | None = None) -> list:
        capture = getattr(self, "trace", None)
        budget = active_budget()
        timeout = min(1000, max(1, math.floor(budget.remaining() * 1000))) if budget else None
        clipped = False
        query, query_params = cypher, params or {}
        if budget:
            available = budget.limits.rows - budget.rows
            if available <= 0:
                raise BudgetExhausted(budget, "rows")
            # Trusted queries have either a final LIMIT integer/parameter or no LIMIT.
            # Clamp graph output before materializing it. If a clamped page fills,
            # completeness is unknown: reject it rather than silently dropping rows.
            match = re.search(r"\s+LIMIT\s+(\$\w+|\d+)\s*$", cypher, re.I)
            requested = (query_params[match[1][1:]] if match and match[1].startswith("$")
                         else int(match[1]) if match else None)
            if requested is None or requested > available:
                clipped = True
                query = (cypher[:match.start()] if match else cypher) + " LIMIT $__read_rows"
                query_params = {**query_params, "__read_rows": available}
        started = time.perf_counter()
        event = {"kind": "falkordb_query", "query_id": hashlib.sha256(query.encode()).hexdigest()[:16],
                 "cypher": query, "parameters": query_params, "repo": self.repo,
                 "graph": getattr(self.graph, "name", None), "generation": getattr(self, "_generation", None)}
        try:
            if budget:
                budget.queries += 1
            rows = (self.graph.ro_query(query, query_params, timeout=timeout) if budget else
                    self.graph.ro_query(query, query_params)).result_set
            event.update(rows=rows, row_count=len(rows), outcome="PASS", timeout_ms=timeout)
            if budget:
                budget.consume_rows(len(rows))
                if clipped and len(rows) == available:
                    raise BudgetExhausted(budget, "rows")
            return rows
        except Exception as exc:
            event.update(outcome="ERROR", error_type=type(exc).__name__)
            if budget and ("query timed out" in str(exc).lower() or isinstance(exc, (TimeoutError, RedisTimeoutError))):
                budget.remaining()  # total deadline takes precedence when it has expired
                raise EvidenceError("RETRIEVAL_TIMEOUT", "database read timed out; retrieval is incomplete") from None
            raise
        finally:
            event["seconds"] = time.perf_counter() - started
            if capture is not None:
                capture.append(event)

    def _q_paged(self, cypher: str, params: dict) -> list:
        """All rows of an ORDER BY query, fetched in RESULT_PAGE pages (the server caps result sets)."""
        out, off = [], 0
        while True:
            rows = self._q(cypher + " SKIP $_o LIMIT $_l", {**params, "_o": off, "_l": RESULT_PAGE})
            out.extend(rows)
            if len(rows) < RESULT_PAGE:
                return out
            off += RESULT_PAGE

    def _q_split(self, cypher: str, hs: list[str]) -> list:
        """Rows of a `b.content_hash IN $hs` query; halves the hash group whenever a result reaches the
        server's result-set cap, so no rows are silently cut off."""
        rows = self._q(cypher, {"hs": hs})
        if len(rows) < RESULT_PAGE:
            return rows
        if len(hs) == 1:
            ordering = " ORDER BY s.id, type(e), t.id" if "-[e]->" in cypher else " ORDER BY s.id"
            return self._q_paged(cypher + ordering, {"hs": hs})
        mid = len(hs) // 2
        return self._q_split(cypher, hs[:mid]) + self._q_split(cypher, hs[mid:])

    def _git(self) -> GitRepo | None:
        if self._repo_path is False:
            rows = self._q("MATCH (r:Repository {name:$n}) RETURN r.path", {"n": self.repo})
            self._repo_path = rows[0][0] if rows else None
        return GitRepo(self._repo_path) if self._repo_path else None

    def _complete(self, sha: str) -> bool:
        return bool(self._q("MATCH (repo:Repository {name:$n, status:'COMPLETE'}), "
                            "(r:ImportRun {status:'COMPLETE'})-[:INDEXED]->(c:Commit {sha:$s}) "
                            "WHERE r.id=repo.published_run RETURN c.sha LIMIT 1", {"s": sha, "n": self.repo}))

    def _state(self):
        rows = self._q("MATCH (r:Repository {name:$n}) RETURN r.status, r.generation", {"n": self.repo})
        return tuple(rows[0]) if rows else (None, None)

    def _scope(self, *args) -> str:
        return hashlib.sha256(json.dumps([self.repo, getattr(self.graph, "name", None),
            getattr(self, "_generation", None), args], sort_keys=True).encode()).hexdigest()

    def _refresh_generation(self, generation):
        if getattr(self, "_generation", None) != generation:
            self._snap.clear()
            self._fmap.clear()
            self._trees.clear()
            self._source_bytes.clear()
            self._repo_path = False
            self._generation = generation

    def _coverage_gaps(self, sha: str) -> list[Gap]:
        self._source_tree(sha)
        extractors = [f"{lang}@{adapter.version}" for lang, adapter in ADAPTERS.items()]
        rows = self._q_paged("MATCH (:Commit {sha:$s})-[f:HAS_FILE]->(b:Blob) "
            "WHERE b.language IS NULL OR b.errors > 0 OR b.extracted_by IS NULL "
            "OR NOT b.extracted_by IN $extractors "
            "RETURN f.path, b.language, b.errors, b.extracted_by ORDER BY f.path",
            {"s": sha, "extractors": extractors})
        for path, lang, errors, extractor in rows:
            if lang is not None and extractor not in extractors:
                raise EvidenceError("STALE_EXTRACTION", f"{path}: extraction identity is stale or incomplete; reindex repository")
        return [Gap("UNSUPPORTED_LANGUAGE" if lang is None else "EXTRACTION_ERROR",
                    f"{path}: " + ("no extraction adapter" if lang is None else "source not completely parsed/extracted"))
                for path, lang, errors, extractor in rows
                if lang is not None or not path.lower().endswith((".md", ".rst", ".txt"))]

    @_consistent
    def resolve(self, rev: str) -> tuple[str | None, Gap | None]:
        """Full sha of an indexed (COMPLETE) commit for a tag/branch/sha, else a gap."""
        if not isinstance(rev, str) or not rev or rev.startswith("-"):
            return None, Gap("UNKNOWN_REVISION", f"invalid revision {rev!r}")
        status, generation = self._state()
        if status != "COMPLETE":
            return None, Gap("INCOMPLETE_IMPORT", "repository has no complete current publication; retry the import")
        self._refresh_generation(generation)
        sha = None
        rows = self._q("MATCH (:Tag {name:$n})-[:POINTS_TO]->(c:Commit) RETURN c.sha", {"n": rev})
        if len(rows) > 1:
            return None, Gap("AMBIGUOUS_REVISION", f"tag {rev!r} has conflicting targets")
        if rows:
            sha = rows[0][0]
        if sha is None and SHA_RE.fullmatch(rev):
            rows = self._q("MATCH (c:Commit) WHERE c.sha STARTS WITH $p RETURN c.sha LIMIT 2", {"p": rev})
            if len(rows) > 1:
                return None, Gap("AMBIGUOUS_REVISION", f"revision {rev!r} matches several commits")
            if rows:
                sha = rows[0][0]
        if sha is None:
            git = self._git()
            if git is not None:
                try:
                    sha = git.resolve(rev) or None
                except (GitError, OSError):
                    sha = None
        if sha is None or not self._q("MATCH (c:Commit {sha:$s}) RETURN c.sha", {"s": sha}):
            return None, Gap("UNKNOWN_REVISION", f"revision {rev!r} is not indexed for repository {self.repo!r}")
        if not self._complete(sha):
            return None, Gap("INCOMPLETE_IMPORT", f"revision {rev!r} ({sha}) has no COMPLETE import run")
        return sha, None

    def _snapshot(self, sha: str):
        """(files: path -> (hash, lines, git_sha), syms: list[_Sym], rels: list[tuple])."""
        if sha in self._snap:
            return self._snap[sha]
        files = self._files(sha)
        syms, rels = self._load(files)
        snap = (files, syms, rels)
        self._snap[sha] = snap
        return snap

    def _files(self, sha: str) -> dict:
        """path -> (content_hash, lines, git_sha) at commit `sha` (cached)."""
        if sha not in self._fmap:
            rows = self._q_paged(
                "MATCH (:Commit {sha:$s})-[f:HAS_FILE]->(b:Blob) "
                "RETURN f.path, b.content_hash, b.lines, b.git_sha ORDER BY f.path", {"s": sha})
            if len({r[0] for r in rows}) != len(rows):
                raise EvidenceError("CONFLICTING_SOURCE", f"duplicate file bindings at {sha}; reindex repository")
            self._fmap[sha] = {path: (h, n, g) for path, h, n, g in rows}
            tree = self._source_tree(sha)
            for path, (_, _, git_sha) in self._fmap[sha].items():
                if path not in tree or tree[path][0] != git_sha:
                    raise EvidenceError("STALE_SOURCE", f"{path}: indexed file binding disagrees with Git tree {sha}")
        return self._fmap[sha]

    def _source_tree(self, sha: str) -> dict:
        if sha not in self._trees:
            git = self._git()
            if git is None:
                raise EvidenceError("MISSING_SOURCE", "source repository is unavailable")
            try:
                self._trees[sha] = {p: (g, mode) for p, g, mode in git.tree(sha)}
            except (GitError, OSError):
                raise EvidenceError("MISSING_SOURCE", f"cannot read Git tree {sha}") from None
        return self._trees[sha]

    def _source(self, sha: str, path: str, content_hash: str) -> bytes:
        """Verify graph provenance against Git objects, without deriving graph relationships."""
        budget = active_budget()
        if budget:
            budget.remaining()
        entry = self._source_tree(sha).get(path)
        if entry is None:
            raise EvidenceError("STALE_SOURCE", f"{path}: path is absent at {sha}")
        git_sha, mode = entry
        if mode not in ("100644", "100755"):
            raise EvidenceError("UNSUPPORTED_FILE_KIND", f"{path}: Git mode {mode} is not a regular source file")
        if git_sha not in self._source_bytes:
            data = self._blob(git_sha)
            if data is None:
                raise EvidenceError("MISSING_SOURCE", f"{path}: source bytes unavailable at {sha}")
            if budget:
                budget.consume_source(len(data))
            self._source_bytes[git_sha] = data
        data = self._source_bytes[git_sha]
        if hashlib.sha256(data).hexdigest() != content_hash:
            raise EvidenceError("STALE_SOURCE", f"{path}: indexed content hash disagrees with source bytes at {sha}")
        if self.trace is not None:
            self.trace.append({"kind": "source_verification", "repo": self.repo, "commit": sha,
                "generation": getattr(self, "_generation", None), "path": path, "git_blob": git_sha,
                "content_hash": content_hash, "bytes": len(data), "outcome": "PASS"})
        return data

    def _load(self, files: dict, with_rels: bool = True):
        """Symbols (sorted) and relations of the blobs in `files` (a path -> entry map)."""
        by_hash: dict[str, list[str]] = {}
        for p, (h, _, _) in files.items():
            by_hash.setdefault(h, []).append(p)
        syms: list[_Sym] = []
        rels: list[tuple] = []
        hashes = list(by_hash)
        for i in range(0, len(hashes), 200):
            hs = hashes[i:i + 200]
            for h, q, kind, sl, el, th, fp in self._q_split(
                    "MATCH (b:Blob)-[:DEFINES]->(s:Symbol) WHERE b.content_hash IN $hs "
                    "RETURN b.content_hash, s.qualname, s.kind, s.start_line, s.end_line, s.text_hash, "
                    "s.first_path", hs):
                for p in by_hash[h]:
                    if adapter_for(p) is None:
                        continue
                    syms.append(_Sym(_rebase(q, fp, p), kind, p, h, sl, el, th, q))
            if not with_rels:
                continue
            for h, sq, fp, kind, tq, text, prov, ext, relative in self._q_split(
                    "MATCH (b:Blob)-[:DEFINES]->(s:Symbol)-[e]->(t:Symbol) WHERE b.content_hash IN $hs "
                    "RETURN b.content_hash, s.qualname, s.first_path, type(e), t.qualname, t.external, "
                    "e.provenance, e.extractor, e.relative_target", hs):
                if ext not in {f"{lang}@{a.version}" for lang, a in ADAPTERS.items()}:
                    raise EvidenceError("STALE_EXTRACTION", f"relationship {sq} -> {tq} has stale extraction identity")
                for p in by_hash[h]:
                    if adapter_for(p) is None:
                        continue
                    target = tq if text else _rebase(tq, fp, p)
                    if relative:
                        level = len(relative) - len(relative.lstrip("."))
                        mod = module_name(p)
                        package = mod if p.endswith(("__init__.py", "__init__.pyi")) else mod.rpartition(".")[0]
                        parts = package.split(".") if package else []
                        anchor = parts[:max(0, len(parts) - level + 1)]
                        target = ".".join([*anchor, relative[level:]]).rstrip(".")
                    rels.append((_rebase(sq, fp, p), p, kind, target, prov, ext))
        syms.sort(key=lambda s: (s.path, s.start_line, s.qualname))
        return syms, rels

    def _candidates(self, sha: str, name: str) -> list[_Sym]:
        """Symbols at `sha` that may be called `name` (exact or last component), sorted; server-side
        filtered by the last name component (module symbols are kept since rebasing renames them)."""
        last = name.rsplit(".", 1)[-1]
        out = []
        for path, h, q, kind, sl, el, th, fp in self._q_paged(
                "MATCH (:Commit {sha:$s})-[f:HAS_FILE]->(b:Blob)-[:DEFINES]->(s:Symbol) "
                "WHERE (toLower(f.path) ENDS WITH '.py' OR toLower(f.path) ENDS WITH '.pyi') "
                "AND (s.kind = 'module' OR s.qualname = $last OR s.qualname ENDS WITH $dl) "
                "RETURN f.path, b.content_hash, s.qualname, s.kind, s.start_line, s.end_line, s.text_hash, "
                "s.first_path ORDER BY f.path, s.start_line, s.qualname", {"s": sha, "last": last, "dl": "." + last}):
            out.append(_Sym(_rebase(q, fp, path), kind, path, h, sl, el, th, q))
        out.sort(key=lambda s: (s.path, s.start_line, s.qualname))
        return out

    def _cite(self, sha: str, s: _Sym) -> Citation:
        lines = source_lines(self._source(sha, s.path, s.content_hash).decode("utf-8", "replace"))
        # The extractor uses a 1:1 module marker for empty ASTs. It identifies
        # the file, not a physical source line; never publish it as a line span.
        empty_module = not lines and s.kind == "module" and s.start_line == s.end_line == 1
        if not empty_module and not (1 <= s.start_line <= s.end_line <= len(lines)):
            raise EvidenceError("STALE_SOURCE", f"{s.path}: indexed symbol span is outside source at {sha}")
        actual = hashlib.sha256("\n".join(lines[s.start_line - 1:s.end_line]).encode("utf-8")).hexdigest()
        if actual != s.text_hash:
            raise EvidenceError("STALE_SOURCE", f"{s.path}: indexed symbol span hash disagrees with source at {sha}")
        if empty_module:
            return Citation(self.repo, sha, s.path, content_hash=s.content_hash)
        return Citation(self.repo, sha, s.path, s.start_line, s.end_line, s.content_hash)

    def _gap_page(self, gap: Gap) -> Page:
        return Page([], None, False, {"complete": False, "gaps": [gap]})

    @_consistent
    def revisions(self, limit: int = 50, cursor: str | None = None) -> Page:
        """Published revision identities, including detached commits, with bounded transport."""
        _limit(limit)
        status, generation = self._state()
        if status != "COMPLETE":
            return self._gap_page(Gap("INCOMPLETE_IMPORT", "no complete current publication"))
        self._refresh_generation(generation)
        scope = self._scope("revisions")
        off = _decode(cursor, scope)
        params = {"name": self.repo}
        match = ("MATCH (repo:Repository {name:$name, status:'COMPLETE'}), "
                 "(r:ImportRun {status:'COMPLETE'})-[:INDEXED]->(c:Commit) "
                 "WHERE r.id=repo.published_run ")
        total = self._q(match + "RETURN count(c)", params)[0][0]
        bad = _bad_offset(off, total)
        if bad:
            return bad
        rows = self._q(match + "OPTIONAL MATCH (t:Tag)-[:POINTS_TO]->(c) "
            "RETURN c.sha, collect(DISTINCT t.name) ORDER BY c.sha SKIP $o LIMIT $l",
            {**params, "o": off, "l": limit})
        return _page([{"sha": sha, "refs": sorted(refs)} for sha, refs in rows], limit, cursor,
                     {"generation": generation, "gaps": []}, total=total, off=off, scope=scope)

    # ------------------------------------------------------------ symbols
    @_consistent
    def symbols(self, rev: str, name: str | None = None, limit: int = 50, cursor: str | None = None) -> Page:
        _limit(limit)
        sha, gap = self.resolve(rev)
        if gap:
            return self._gap_page(gap)
        scope = self._scope("symbols", sha, name)
        off = _decode(cursor, scope)
        coverage = {"commit": sha, "generation": getattr(self, "_generation", None), "gaps": self._coverage_gaps(sha)}

        def item(s: _Sym) -> SymbolItem:
            return SymbolItem(f"{self.repo}:{s.content_hash}:{s.qualname}", s.qualname, s.kind, s.path,
                              self._cite(sha, s))
        if name:
            syms = [s for s in self._candidates(sha, name)
                    if s.qualname == name or s.qualname.rsplit(".", 1)[-1] == name]
            return _page([item(s) for s in syms], limit, cursor, coverage, off=off, scope=scope)
        if sha in self._snap:  # already loaded: page in memory
            return _page([item(s) for s in self._snap[sha][1]], limit, cursor, coverage,
                         off=off, scope=scope)
        match = ("MATCH (:Commit {sha:$s})-[f:HAS_FILE]->(b:Blob)-[:DEFINES]->(s:Symbol) "
                 "WHERE toLower(f.path) ENDS WITH '.py' OR toLower(f.path) ENDS WITH '.pyi' ")
        total = self._q(match + "RETURN count(s)", {"s": sha})[0][0]
        bad = _bad_offset(off, total)
        if bad:
            return bad
        rows = self._q(match + "RETURN f.path, b.content_hash, s.qualname, s.kind, s.start_line, s.end_line, "
                       "s.text_hash, s.first_path ORDER BY f.path, s.start_line, s.qualname SKIP $o LIMIT $l",
                       {"s": sha, "o": off, "l": limit})
        items = [item(_Sym(_rebase(q, fp, path), kind, path, h, sl, el, th, q))
                 for path, h, q, kind, sl, el, th, fp in rows]
        return _page(items, limit, cursor, coverage, total=total, off=off, scope=scope)

    # ------------------------------------------------------------ dependencies
    def _edges(self, sha: str):
        files, syms, rels = self._snapshot(sha)
        defs: dict[str, _Sym] = {}
        ambiguous = set()
        for s in syms:
            if s.qualname in defs and defs[s.qualname].path != s.path:
                ambiguous.add(s.qualname)
            defs.setdefault(s.qualname, s)
        edges = {}
        for src, _p, kind, tgt, prov, ext in rels:
            key = (src, tgt, kind)
            if key not in edges or (edges[key][0] == "inferred" and prov == "parsed"):
                edges[key] = (prov, ext)
        return defs, edges, ambiguous

    @_consistent
    def _walk(self, rev, symbol, hops, limit, cursor, reverse: bool) -> Page:
        _limit(limit)
        if not isinstance(hops, int) or not 1 <= hops <= MAX_HOPS:
            raise ValueError(f"hops must be in 1..{MAX_HOPS}")
        sha, gap = self.resolve(rev)
        if gap:
            return self._gap_page(gap)
        scope = self._scope("walk", sha, symbol, hops, reverse)
        off = _decode(cursor, scope)
        defs, edges, ambiguous = self._edges(sha)
        gaps = self._coverage_gaps(sha)
        if symbol in ambiguous:
            return self._gap_page(Gap("AMBIGUOUS_SYMBOL", f"{symbol!r} is defined at multiple paths; clarify its identity"))
        if symbol not in defs:
            gaps.append(Gap("UNKNOWN_SYMBOL", f"{symbol!r} is not defined in {self.repo} at {rev!r}"))
        adj: dict[str, list] = {}
        for (src, tgt, kind), (prov, ext) in edges.items():
            adj.setdefault(tgt if reverse else src, []).append((src, tgt, kind, prov, ext))
        items, seen_edges, dist = [], set(), {symbol: 0}
        queue = deque([symbol])
        cut = False
        while queue and not cut:
            if active_budget():
                active_budget().remaining()
            node = queue.popleft()
            d = dist[node]
            if d >= hops:
                continue
            for src, tgt, kind, prov, ext in sorted(adj.get(node, [])):
                if src in ambiguous or tgt in ambiguous:
                    gap = Gap("AMBIGUOUS_SYMBOL", f"cannot bind edge {src} -> {tgt} to a unique source path")
                    if gap not in gaps:
                        gaps.append(gap)
                    continue
                if (src, tgt, kind) in seen_edges:
                    continue
                if len(items) >= MAX_WALK_EDGES:
                    cut = True
                    break
                seen_edges.add((src, tgt, kind))
                s_def, t_def = defs.get(src), defs.get(tgt)
                items.append(DependencyItem(
                    src, tgt, kind, prov, ext, d + 1, t_def is None,
                    self._cite(sha, s_def) if s_def else None,
                    self._cite(sha, t_def) if t_def else None))
                nxt = src if reverse else tgt
                if nxt in defs and nxt not in dist:
                    dist[nxt] = d + 1
                    queue.append(nxt)
        if cut:
            gaps.append(Gap("TRUNCATED", f"traversal stopped after {MAX_WALK_EDGES} edges; "
                                         "deeper/remaining edges are not listed"))
        return _page(items, limit, cursor, {"commit": sha, "hops": hops, "gaps": gaps,
                                            "frontier_truncated": cut}, off=off, scope=scope)

    def dependencies(self, rev, symbol, hops=1, limit=50, cursor=None) -> Page:
        return self._walk(rev, symbol, hops, limit, cursor, reverse=False)

    def dependents(self, rev, symbol, hops=1, limit=50, cursor=None) -> Page:
        return self._walk(rev, symbol, hops, limit, cursor, reverse=True)

    # ------------------------------------------------------------ changes
    @_consistent
    def changes_between(self, rev_a, rev_b, limit=50, cursor=None) -> Page:
        _limit(limit)
        sha_a, gap_a = self.resolve(rev_a)
        sha_b, gap_b = self.resolve(rev_b)
        if gap_a or gap_b:
            return Page([], None, False, {"gaps": [g for g in (gap_a, gap_b) if g]})
        scope = self._scope("changes", sha_a, sha_b)
        off = _decode(cursor, scope)
        fa, fb = self._files(sha_a), self._files(sha_b)
        changed_a = {p: e for p, e in fa.items() if p not in fb or fb[p][0] != e[0]}
        changed_b = {p: e for p, e in fb.items() if p not in fa or fa[p][0] != e[0]}
        sa, _ = self._load(changed_a, with_rels=False)
        sb, _ = self._load(changed_b, with_rels=False)
        syms_a: dict[str, dict] = {}
        syms_b: dict[str, dict] = {}
        for s in sa:
            syms_a.setdefault(s.path, {})[s.qualname] = s
        for s in sb:
            syms_b.setdefault(s.path, {})[s.qualname] = s
        removed = [p for p in fa if p not in fb]
        added = [p for p in fb if p not in fa]
        renames = {}
        sims: dict[str, int] = {}
        git = self._git()
        if git is not None:
            try:
                for ch in git.changes(sha_a, sha_b):
                    if (ch.status == "R" and ch.old_path in fa and ch.new_path in fb
                            and ch.old_path not in fb and ch.new_path not in fa):
                        renames[ch.new_path] = ch.old_path
                        if ch.similarity is not None:
                            sims[ch.new_path] = int(ch.similarity)
            except (GitError, OSError):
                pass
        removed = [p for p in removed if p not in renames.values()]
        added = [p for p in added if p not in renames]
        by_hash_removed = {}
        for p in removed:
            by_hash_removed.setdefault(fa[p][0], []).append(p)
        for p in added:
            olds = by_hash_removed.get(fb[p][0])
            if olds:
                renames[p] = olds.pop(0)
                sims[p] = 100
        renamed_old = set(renames.values())

        def whole(sha, path, files):
            h, n, _ = files[path]
            lines = len(source_lines(self._source(sha, path, h).decode("utf-8", "replace")))
            if n is not None and n != max(lines, 1):
                raise EvidenceError("STALE_SOURCE", f"{path}: indexed line count disagrees with source at {sha}")
            return Citation(self.repo, sha, path, 1 if lines else None, lines or None, h)

        def diff(old: dict, new: dict):
            add = sorted(q for q in new if q not in old)
            rem = sorted(q for q in old if q not in new)
            mod = sorted(q for q in new if q in old and
                         (new[q].text_hash or new[q].content_hash) != (old[q].text_hash or old[q].content_hash))
            return add, rem, mod

        def kinds(*ds):
            return {q: s.kind for d in ds for q, s in d.items()}

        def moved(old: dict, old_path: str, new_path: str) -> dict:
            # match a renamed file's symbols by their module-relative name
            return {_rebase(q, old_path, new_path): s for q, s in old.items()}

        items = []
        for p in sorted(set(fa) | set(fb)):
            if p in fa and p in fb:
                if fa[p][0] == fb[p][0]:
                    continue
                a, r, m = diff(syms_a.get(p, {}), syms_b.get(p, {}))
                items.append(ChangeItem(p, "M", p, a, r, m, whole(sha_b, p, fb),
                                        kinds(syms_a.get(p, {}), syms_b.get(p, {})),
                                        old_citation=whole(sha_a, p, fa)))
            elif p in fb:
                if p in renames:
                    old = moved(syms_a.get(renames[p], {}), renames[p], p)
                    a, r, m = diff(old, syms_b.get(p, {}))
                    items.append(ChangeItem(p, "R", renames[p], a, r, m, whole(sha_b, p, fb),
                                            kinds(old, syms_b.get(p, {})), sims.get(p),
                                            whole(sha_a, renames[p], fa)))
                else:
                    items.append(ChangeItem(p, "A", None, sorted(syms_b.get(p, {})), [], [],
                                            whole(sha_b, p, fb), kinds(syms_b.get(p, {}))))
            elif p not in renamed_old:
                items.append(ChangeItem(p, "D", p, [], sorted(syms_a.get(p, {})), [], whole(sha_a, p, fa),
                                        kinds(syms_a.get(p, {}))))
        return _page(items, limit, cursor, {"from": sha_a, "to": sha_b,
            "gaps": self._coverage_gaps(sha_a) + self._coverage_gaps(sha_b)}, off=off, scope=scope)

    def _blob(self, git_sha: str | None) -> bytes | None:
        git = self._git()
        if git is None or not git_sha:
            return None
        try:
            return git.blob(git_sha)
        except (GitError, OSError):
            return None

    # ------------------------------------------------------------ release notes
    @_consistent
    def release_notes(self, rev, limit=50, cursor=None) -> Page:
        _limit(limit)
        sha, gap = self.resolve(rev)
        if gap:
            return self._gap_page(gap)
        scope = self._scope("notes", sha)
        off = _decode(cursor, scope)
        files = self._files(sha)
        match = "MATCH (:Commit {sha:$s})-[:HAS_NOTE]->(n:ReleaseNote) "
        total = self._q(match + "RETURN count(n)", {"s": sha})[0][0]
        bad = _bad_offset(off, total)
        if bad:
            return bad
        rows = self._q(match + "RETURN n.path, n.content_hash ORDER BY n.path "
                       "SKIP $o LIMIT $l", {"s": sha, "o": off, "l": limit})
        tags = [r[0] for r in self._q_paged("MATCH (t:Tag)-[:POINTS_TO]->(:Commit {sha:$s}) RETURN t.name ORDER BY t.name",
                                      {"s": sha})]
        if rev not in tags and not SHA_RE.fullmatch(rev):
            tags.append(rev)
        versions = [t[1:] if re.match(r"^[vV]\d", t) else t for t in tags]
        items, gaps = [], []
        for path, h in rows:
            entry = files.get(path)
            if entry is None:
                gaps.append(Gap("MISSING_SOURCE", f"cannot read {path} at {sha}"))
                continue
            data = self._source(sha, path, h)
            lines = source_lines(data.decode("utf-8", "replace"))
            start, end = _section(lines, versions)
            text = "\n".join(lines[start - 1:end])
            citation = Citation(self.repo, sha, path, start if lines else None, end if lines else None, h)
            items.append(NoteItem(path, text, citation))
        return _page(items, limit, cursor, {"commit": sha, "gaps": gaps}, off=off, scope=scope, total=total)

    # ------------------------------------------------------------ history
    @_consistent
    def symbol_history(self, symbol: str, revs: list[str]) -> list[HistoryEntry]:
        out = []
        for rev in revs:
            sha, gap = self.resolve(rev)
            if gap:
                out.append(HistoryEntry(rev, None, None, None, None, gap))
                continue
            syms = self._candidates(sha, symbol)
            matches = [s for s in syms if s.qualname == symbol]
            if len({s.path for s in matches}) > 1:
                out.append(HistoryEntry(rev, sha, None, None, None,
                                        Gap("AMBIGUOUS_SYMBOL", f"{symbol!r} is defined at multiple paths")))
                continue
            hit = next((s for s in syms if s.qualname == symbol), None)
            if hit is None:
                hit_path = next((s for s in syms if s.path == symbol and s.kind == "module"), None)
                hit = hit_path
            if hit is None:
                gaps = self._coverage_gaps(sha)
                out.append(HistoryEntry(rev, sha, None if gaps else False, None, None,
                                        Gap("INCOMPLETE_COVERAGE", "; ".join(g.detail for g in gaps)) if gaps else None))
            else:
                out.append(HistoryEntry(rev, sha, True, hit.content_hash, self._cite(sha, hit)))
        return out

    # ------------------------------------------------------------ ancestry
    def _ancestors(self, sha: str, stop: str | None = None) -> tuple[set[str], bool]:
        """Commits reachable from `sha` over PARENT edges (inclusive); (set, stop was reached)."""
        seen, frontier = {sha}, [sha]
        while frontier and len(seen) < MAX_ANCESTRY:
            if stop is not None and stop in seen:
                return seen, True
            rows = self._q("MATCH (c:Commit)-[:PARENT]->(p:Commit) WHERE c.sha IN $f RETURN DISTINCT p.sha",
                           {"f": frontier})
            frontier = [r[0] for r in rows if r[0] not in seen]
            seen.update(frontier)
        return seen, stop is not None and stop in seen

    def is_ancestor(self, ancestor_rev: str, rev: str) -> bool | None:
        a, gap_a = self.resolve(ancestor_rev)
        b, gap_b = self.resolve(rev)
        if gap_a or gap_b:
            return None
        return self._is_ancestor(a, b)

    def _is_ancestor(self, a: str, b: str) -> bool:
        git = self._git()
        if git is not None:
            try:
                return git.is_ancestor(a, b)
            except (GitError, OSError):
                pass
        return self._ancestors(b, stop=a)[1]

    # ------------------------------------------------------------ fix status
    @_consistent
    def fix_status(self, rev: str, fix_commit: str, *, symbol: str | None = None) -> FixStatus:
        """Is the change introduced by `fix_commit` present in the CONTENT at `rev`?"""
        sha, gap = self.resolve(rev)
        if gap:
            return FixStatus("UNCERTAIN", [], [gap], f"revision {rev!r} cannot be resolved")
        fix, gap = self.resolve(fix_commit)
        if gap:
            return FixStatus("UNCERTAIN", [], [Gap("UNKNOWN_REVISION", gap.detail)],
                             f"fix commit {fix_commit!r} is not indexed")
        git = self._git()
        parents = self._q("MATCH (:Commit {sha:$s})-[e:PARENT]->(p:Commit) RETURN p.sha ORDER BY e.order",
                          {"s": fix})
        if git is None or not parents:
            return FixStatus("UNCERTAIN", [], [Gap("CHANGE_IDENTITY_UNKNOWN",
                             f"cannot read the change introduced by {fix}")], "the fix diff is unavailable")
        try:
            hunks = _parse_patch(git.patch(parents[0][0], fix))
        except (GitError, OSError) as e:
            return FixStatus("UNCERTAIN", [], [Gap("CHANGE_IDENTITY_UNKNOWN", str(e))],
                             "the fix diff is unavailable")
        hunks = [h for h in hunks if any(x.strip() for x in h[1] + h[2])]
        if not hunks:
            return FixStatus("UNCERTAIN", [], [Gap("CHANGE_IDENTITY_UNKNOWN", f"{fix} has no textual hunks")],
                             "the fix has no textual change to check")
        files = self._files(sha)
        pre_files = self._files(parents[0][0])
        fix_files = self._files(fix)
        # files outside the indexed include scope cannot be checked and do not count as missing
        hunks = [h for h in hunks if h[0] in fix_files or h[0] in pre_files]
        if not hunks:
            return FixStatus("UNCERTAIN", [], [Gap("CHANGE_IDENTITY_UNKNOWN", "fix is outside indexed scope")],
                             "the fix's changed files are outside indexed scope")
        ancestor = self._is_ancestor(fix, sha)
        rename_map: dict[str, str] = {}
        if any(h[0] not in files for h in hunks):
            try:
                for ch in git.changes(fix, sha):
                    if ch.status == "R":
                        rename_map[ch.old_path] = ch.new_path
            except (GitError, OSError):
                pass

        found, missing, file_cits, similar = [], [], {}, False
        for path, removed, added in hunks:
            p = path if path in files else rename_map.get(path)
            if p is None or p not in files:
                if not added and path not in fix_files:
                    continue  # a file deleted by the fix remains deleted
                missing.append(path)
                continue
            h, _, g = files[p]
            data = self._source(sha, p, h)
            lines = source_lines(data.decode("utf-8", "replace"))
            file_cits[p] = Citation(self.repo, sha, p, 1 if lines else None, len(lines) or None, h)
            if any(x.strip() for x in removed):
                fixed_data = self._source(fix, path, fix_files[path][0]) if path in fix_files else b""
                fixed_lines = source_lines(fixed_data.decode("utf-8", "replace"))
                def occurrences(source):
                    return sum(source[i:i + len(removed)] == removed
                               for i in range(len(source) - len(removed) + 1))
                if occurrences(lines) > occurrences(fixed_lines):
                    missing.append(path)
                    continue  # required deletion has been undone, even if added guards survive
                if path not in fix_files:
                    return FixStatus("UNCERTAIN", list(file_cits.values()), [Gap("CHANGE_IDENTITY_UNKNOWN",
                        f"{path} was deleted by the fix but a different file now exists at that path")],
                        "the deleted path was recreated; content alone cannot establish change identity")
            if not any(x.strip() for x in added):
                found.append(file_cits[p])
                continue
            at = _find_block(lines, added)
            span = None
            if at is not None:
                span = (at + 1, at + len(added))
            elif ancestor:
                span = _find_subsequence(lines, added)
            if span is None:
                missing.append(path)
                pre_blob = self._source(parents[0][0], path, pre_files[path][0]) if path in pre_files else None
                pre = source_lines(pre_blob.decode("utf-8", "replace")) if pre_blob else []
                similar = similar or _similar(lines, added, removed + pre)
            else:
                found.append(Citation(self.repo, sha, p, span[0], span[1], h))

        if not missing:
            gaps, reason = [], f"the additions and deletions of {fix[:12]} remain at {sha[:12]}"
            if not ancestor:
                match = self._patch_match(git, fix, sha)
                if match:
                    gaps.append(Gap("EQUIVALENT_BY_PATCH",
                                    f"{fix} is not an ancestor of {sha}; commit {match} has the same patch-id"))
                    reason += f" via patch-equivalent commit {match[:12]}"
                else:
                    # The text is there, but nothing ties it to this fix: say so instead of implying identity.
                    gaps.append(Gap("CHANGE_IDENTITY_UNKNOWN",
                                    f"{fix} is not an ancestor of {sha} and no patch-equivalent commit was found "
                                    f"among at most {MAX_PATCH_CANDIDATES} candidates; the matching lines may have "
                                    "another origin"))
                    reason += f" (by content; {fix[:12]} is not an ancestor and no patch-equivalent commit found)"
            return FixStatus("PRESENT", found, gaps, reason)
        cits = list(file_cits.values())
        if similar:
            if ancestor:
                return FixStatus("UNCERTAIN", cits, [Gap("CHANGE_IDENTITY_UNKNOWN",
                                 f"{fix} is an ancestor of {sha} but its lines were later modified")],
                                 "the fix lines were modified after it was applied")
            return FixStatus("UNCERTAIN", cits, [Gap("BACKPORT_EQUIVALENCE_UNKNOWN",
                             f"{fix} is not an ancestor of {sha} and no patch-equivalent commit exists; "
                             "the touched file changed in a similar but non-identical way")],
                             "a similar but non-identical change exists at the revision")
        why = "was reverted or removed" if ancestor else "was never applied"
        return FixStatus("ABSENT", cits, [],
                         f"the lines added by {fix[:12]} are not at {sha[:12]}; the fix {why}")

    def _patch_match(self, git: GitRepo, fix: str, sha: str) -> str | None:
        try:
            target = git.patch_id(fix)
        except (GitError, OSError):
            return None
        if not target:
            return None
        try:  # commits reachable from `sha` but not from `fix`
            candidates = set(git._text("rev-list", sha, f"^{fix}", "--").split())
        except (GitError, OSError):
            ancestors, _ = self._ancestors(sha)
            fix_anc, _ = self._ancestors(fix)
            candidates = ancestors - fix_anc
        for c in sorted(candidates)[:MAX_PATCH_CANDIDATES]:
            try:
                if git.patch_id(c) == target:
                    return c
            except (GitError, OSError):
                continue
        return None


def _parse_patch(text: str) -> list[tuple[str, list[str], list[str]]]:
    """Hunks of a -U0 patch: (new path, removed lines, added lines)."""
    hunks, path, old_path, cur = [], None, None, None
    for line in source_lines(text):
        if line.startswith("diff "):
            cur = None
            old_path = None
        elif line.startswith("+++ ") and cur is None:
            t = line[4:]
            path = old_path if t == "/dev/null" else (t[2:] if t.startswith("b/") else t)
        elif line.startswith("--- ") and cur is None:
            t = line[4:]
            old_path = None if t == "/dev/null" else (t[2:] if t.startswith("a/") else t)
        elif line.startswith("@@"):
            cur = (path, [], [])
            if path is not None:
                hunks.append(cur)
        elif cur is not None and line.startswith("+"):
            cur[2].append(line[1:])
        elif cur is not None and line.startswith("-"):
            cur[1].append(line[1:])
    return hunks


def _find_block(lines: list[str], block: list[str]) -> int | None:
    n = len(block)
    for i in range(len(lines) - n + 1):
        if lines[i:i + n] == block:
            return i
    return None


def _find_subsequence(lines: list[str], block: list[str]) -> tuple[int, int] | None:
    """1-based (first, last) lines of the earliest in-order occurrence of every non-blank line of
    `block` in `lines` (other lines may sit between them); None when one is missing."""
    want = [b for b in block if b.strip()]
    if not want:
        return None
    for i, x in enumerate(lines):
        if x != want[0]:
            continue
        j, k = 1, i + 1
        while j < len(want) and k < len(lines):
            if lines[k] == want[j]:
                j += 1
            k += 1
        if j == len(want):
            return i + 1, k
    return None


def _similar(lines: list[str], added: list[str], removed: list[str]) -> bool:
    """A line at the revision resembles (but does not equal) an added line and is not pre-fix text."""
    pre = set(removed)
    for a in added:
        if not a.strip():
            continue
        for x in lines:
            if x == a or x in pre:
                continue
            if difflib.SequenceMatcher(None, a.strip(), x.strip()).ratio() >= 0.6:
                return True
    return False


def _section(lines: list[str], versions: list[str]) -> tuple[int, int]:
    """1-based inclusive line span of the release section naming one of `versions`, else whole file."""
    n = max(len(lines), 1)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m or not any(re.search(rf"(?<![\w.]){re.escape(v)}(?![\w]|\.\d)", m.group(2))
                            for v in versions if v):
            continue
        level = len(m.group(1))
        end = len(lines)
        for j in range(i + 1, len(lines)):
            m2 = re.match(r"^(#{1,6})\s", lines[j])
            if m2 and len(m2.group(1)) <= level:
                end = j
                break
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        return i + 1, end
    return 1, n
