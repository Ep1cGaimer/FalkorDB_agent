"""Graph retrieval over exactly one exported raw corpus, with audited readiness.

Raw source/history tools remain available to both arms. Graph tools add extracted
relations and source-verified revision evidence. Every graph-arm operation checks
the pinned publication; an unavailable/changed service cannot silently use raw
tools as a replacement graph result. No indexing or mutation is exposed to models.
"""
from __future__ import annotations

import dataclasses
import re
from contextlib import contextmanager

from rw.repo.budget import ReadLimits, read_scope
from rw.repo.config import RepoConfig
from rw.repo.model import Citation
from rw.repo.query import RepoQuery

from .development_cli import plaintext_capabilities
from .gemini_meter import ModelFailure
from .tool_budget import ToolBudgetExceeded, active_tool_budget, bounded_tool, checkpoint


class CorpusMismatch(ModelFailure):
    fatal_tool_failure = True
    def __init__(self, detail):
        self.detail = detail
        super().__init__("GRAPH_CORPUS_MISMATCH")


class GraphUnavailable(ModelFailure):
    fatal_tool_failure = True


def config_for_export(raw, repository_path):
    tags = sorted(name[len("refs/tags/"):] for name in raw.refs if name.startswith("refs/tags/"))
    pattern = "^(?:" + "|".join(re.escape(name) for name in tags) + ")$" if tags else r"(?!)"
    return RepoConfig(name=raw.repository, path=repository_path, revisions=raw.spec["roots"],
                      tag_pattern=pattern, include=raw.spec["include"], exclude=raw.spec["exclude"],
                      languages=["python"], path_matching="path", regular_files_only=True)


class GraphTools:
    def __init__(self, raw, graph_name, *, db=None, trace=None, limits=None):
        self.raw, self.trace = raw, trace if trace is not None else []
        self.query = RepoQuery(graph_name, raw.repository, db=db, trace=self.trace,
                               limits=limits or ReadLimits())
        self.generation = None
        self.receipt = None

    def _state(self):
        try:
            status, generation = self.query._state()
        except Exception:
            raise GraphUnavailable("GRAPH_INDEX_UNAVAILABLE") from None
        if status != "COMPLETE" or not generation:
            raise GraphUnavailable("GRAPH_INDEX_INCOMPLETE")
        return generation

    def _guard(self):
        generation = self._state()
        if self.generation is None:
            raise GraphUnavailable("GRAPH_CORPUS_NOT_ATTESTED")
        if generation != self.generation:
            raise GraphUnavailable("GRAPH_PUBLICATION_CHANGED")

    def prepare(self):
        """Exhaustively compare published commit/file membership before generation.

        Setup work is timed by the caller; its raw graph trace is retained. Only
        the current COMPLETE ImportRun counts; unrelated graphs are never read.
        """
        with read_scope(self.query.limits):
            generation = self._state()
            params = {"repo": self.raw.repository}
            published = ("MATCH (r:Repository {name:$repo, status:'COMPLETE'}), "
                         "(i:ImportRun {status:'COMPLETE'})-[:INDEXED]->(c:Commit) "
                         "WHERE i.id=r.published_run ")
            commits = self.query._q_paged(published + "RETURN c.sha ORDER BY c.sha", params)
            if len(commits) != len(self.raw.commits) or {r[0] for r in commits} != set(self.raw.commits):
                raise CorpusMismatch("published graph commits differ from exported ancestor corpus")
            rows = self.query._q_paged(published +
                "MATCH (c)-[f:HAS_FILE]->(b:Blob) RETURN c.sha, f.path, b.git_sha, b.content_hash ORDER BY c.sha, f.path", params)
            observed = set()
            for sha, path, git_blob, content_hash in rows:
                key = (sha, path)
                if key in observed:
                    raise CorpusMismatch("duplicate graph source membership")
                observed.add(key)
                entry = self.raw.trees[self.raw.commits[sha]["tree"]].get(path)
                if not entry or entry["coverage"] != "included" or git_blob != entry["oid"] or (
                    content_hash != self.raw.blobs[entry["oid"]]["sha256"]
                ):
                    raise CorpusMismatch("graph has extra or mismatched source outside exported corpus")
            expected = {(sha, path) for sha, commit in self.raw.commits.items()
                        for path, e in self.raw.trees[commit["tree"]].items() if e["coverage"] == "included"}
            if observed != expected:
                raise CorpusMismatch("graph is missing exported historical source memberships")
            parents = self.query._q_paged("MATCH (c:Commit)-[e:PARENT]->(p:Commit) "
                "RETURN c.sha, p.sha, e.order ORDER BY c.sha, e.order", {})
            expected_parents = {(sha, parent, n) for sha, c in self.raw.commits.items()
                                for n, parent in enumerate(c["parents"])}
            if len(parents) != len(expected_parents) or set(map(tuple, parents)) != expected_parents:
                raise CorpusMismatch("graph ordered ancestry differs from raw Git commit objects")
            if self._state() != generation:
                raise GraphUnavailable("GRAPH_PUBLICATION_CHANGED")
            self.generation = generation
            self.query._refresh_generation(generation)
            self.receipt = {"corpus_sha256": self.raw.corpus_hash, "repository": self.raw.repository,
                            "graph": self.query.graph.name, "generation": generation,
                            "commits_checked": len(commits), "memberships_checked": len(observed),
                            "ordered_parent_edges_checked": len(parents),
                            "scope": "membership/provenance attestation; not extraction/answer correctness"}
            return self.receipt

    def _serialize(self, value):
        if isinstance(value, Citation):
            if value.repo != self.raw.repository or value.commit not in self.raw.commits:
                raise CorpusMismatch("graph citation has wrong repository or revision")
            entry = self.raw.trees[self.raw.commits[value.commit]["tree"]].get(value.path)
            if not entry or entry["coverage"] != "included" or (
                self.raw.blobs[entry["oid"]]["sha256"] != value.content_hash
            ):
                raise CorpusMismatch("graph citation not supported by common raw source corpus")
            identity = {"repository": value.repo, "commit": value.commit, "path": value.path,
                        "content_hash": value.content_hash, "git_blob": entry["oid"]}
            if value.start_line is None and value.end_line is None:
                return {"proof_type": "file_membership", **identity}
            if value.start_line is None or value.end_line is None:
                raise CorpusMismatch("graph citation has an incomplete source span")
            return {**identity, "start_line": value.start_line, "end_line": value.end_line}
        if dataclasses.is_dataclass(value):
            return {f.name: self._serialize(getattr(value, f.name)) for f in dataclasses.fields(value)}
        if isinstance(value, dict):
            return {key: self._serialize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._serialize(item) for item in value]
        return value

    @contextmanager
    def _graph_scope(self):
        checkpoint()
        shared = active_tool_budget()
        remaining = {unit: getattr(shared.limits, unit) - shared.used[unit]
                     for unit in ("graph_rows", "source_bytes")}
        for unit, value in remaining.items():
            if value <= 0:
                shared.exhausted = unit
                raise ToolBudgetExceeded(shared, unit)
        limits = ReadLimits(seconds=min(self.query.limits.seconds, shared.limits.seconds - (shared.clock() - shared.started)),
                            rows=min(self.query.limits.rows, remaining["graph_rows"]),
                            source_bytes=min(self.query.limits.source_bytes, remaining["source_bytes"]))
        with read_scope(limits) as budget:
            try:
                self._guard()
                yield budget
                self._guard()
            finally:
                checkpoint(source_bytes=budget.source_bytes, graph_rows=budget.rows, work_units=budget.rows)
                if budget.exhausted:
                    shared.exhausted = {"rows": "graph_rows", "seconds": "seconds", "source_bytes": "source_bytes"}[budget.exhausted]
                    raise ToolBudgetExceeded(shared, shared.exhausted)

    def _read(self, fn, *args, **kwargs):
        with self._graph_scope():
            value = fn(*args, **kwargs)
            serialized = self._serialize(value)
        if isinstance(serialized, dict) and "coverage" in serialized:
            gaps = serialized["coverage"].get("gaps", [])
            serialized["coverage"]["complete"] = not gaps and not serialized["truncated"] and not serialized["next_cursor"]
        return serialized

    @bounded_tool
    def symbols(self, revision, name=None, limit=20, cursor=None):
        return self._read(self.query.symbols, self.raw.resolve(revision), name, self._limit(limit), cursor)

    @bounded_tool
    def dependencies(self, revision, symbol, hops=1, limit=20, cursor=None):
        if type(hops) is not int or not 1 <= hops <= 5:
            raise ValueError("hops must be integer1..5")
        return self._read(self.query.dependencies, self.raw.resolve(revision), symbol, hops, self._limit(limit), cursor)

    @bounded_tool
    def dependents(self, revision, symbol, hops=1, limit=20, cursor=None):
        if type(hops) is not int or not 1 <= hops <= 5:
            raise ValueError("hops must be integer1..5")
        return self._read(self.query.dependents, self.raw.resolve(revision), symbol, hops, self._limit(limit), cursor)

    @bounded_tool
    def changes_between(self, old, new, limit=20, cursor=None):
        return self._read(self.query.changes_between, self.raw.resolve(old), self.raw.resolve(new), self._limit(limit), cursor)

    @bounded_tool
    def release_notes(self, revision, limit=20, cursor=None):
        return self._read(self.query.release_notes, self.raw.resolve(revision), self._limit(limit), cursor)

    @bounded_tool
    def fix_status(self, revision, fix):
        return self._read(self.query.fix_status, self.raw.resolve(revision), self.raw.resolve(fix))

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be integer1..100")
        return limit

    def capabilities(self):
        raw_capabilities, descriptions = plaintext_capabilities(self.raw)
        capabilities = {}
        for name, fn in raw_capabilities.items():
            @bounded_tool
            def guarded(*args, _fn=fn, **kwargs):
                with self._graph_scope():
                    return _fn(*args, **kwargs)
            capabilities[name] = guarded
        graph = {
            "symbols": ("Extracted definitions with exact source citations, optional exact qualified/short name.",
                        {"revision": "required string", "name": "optional symbol string"}),
            "dependencies": ("Parsed/inferred calls/imports/bases up to requested hops; missing edges do not establish absence.",
                             {"revision": "required string", "symbol": "required qualified name", "hops": "optional integer1..5"}),
            "dependents": ("Reverse parsed/inferred relationships; static extraction is incomplete.",
                           {"revision": "required string", "symbol": "required qualified name", "hops": "optional integer1..5"}),
            "changes_between": ("Revision-specific source-backed file and symbol changes; rename candidates have limitations.",
                                {"old": "required revision", "new": "required revision"}),
            "release_notes": ("Release-note sections with exact source citations.", {"revision": "required string"}),
        }
        for name, (description, fields) in graph.items():
            capabilities[name] = getattr(self, name)
            descriptions[name] = {"description": description,
                                  "arguments": {**fields, "limit": "optional integer1..100", "cursor": "optional next_cursor"}}
        capabilities["fix_status"] = self.fix_status
        descriptions["fix_status"] = {"description": "Check required additions/deletions at the selected state; uncertain identity stays uncertain.",
                                       "arguments": {"revision": "required revision", "fix": "required fix commit revision"}}
        return capabilities, descriptions
