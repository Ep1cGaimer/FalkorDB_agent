"""Deterministic (no LLM) investigation over an indexed repository (docs/repo/REQUIREMENTS.md S5).

A rule-based router maps a small set of question shapes onto rw.repo.query.RepoQuery and returns
source-backed findings plus explicit gaps. Retrieval only: findings never carry a compatibility
disposition, and every successful answer carries a `runtime_unverified` gap (S6). mode="compatibility"
adds a RepoFindings.disposition only from an explicitly named rw.repo.runtime adapter."""
from __future__ import annotations

import ast
import re
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rw.repo.config import NAME_RE, RepoConfig, load_config
from rw.repo.model import Citation, Gap

MAX_ITEMS = 200      # findings per answer (one RepoQuery page)
MAX_HISTORY_REVS = 200

SUPPORTED = ("What does <symbol> depend on? | What does <symbol> call? | What depends on <symbol>? | "
             "Who calls <symbol>? | What changed between <revA> and <revB>? | Is fix <sha> present? | "
             "When did <symbol> appear/disappear? | What is the value of <symbol>? | "
             "What/Which exceptions does <symbol> raise? | Release notes | List symbols | Where is <symbol> defined?")
RUNTIME_GAP = Gap("runtime_unverified", "retrieved from indexed source and history only; runtime behaviour "
                                        "and compatibility were not checked")

_SYM = r"[`'\"]?([A-Za-z_][\w.]*)[`'\"]?"
_REV = r"[`'\"]?(\S+?)[`'\"]?"
ROUTES = [
    ("constant", re.compile(rf"^what is the value of {_SYM}$", re.I)),
    ("raises", re.compile(rf"^(?:what|which) exceptions does {_SYM} raise$", re.I)),
    ("dependencies", re.compile(rf"^what does {_SYM} (?:depend on|call)$", re.I)),
    ("dependents", re.compile(rf"^(?:what depends on|who calls) {_SYM}$", re.I)),
    ("changes", re.compile(rf"^what changed between {_REV} and {_REV}$", re.I)),
    ("fix", re.compile(r"^is (?:the )?fix [`'\"]?([0-9a-fA-F]{4,40}|\S+?)[`'\"]? present$", re.I)),
    ("history", re.compile(rf"^when did {_SYM} (appear|disappear)$", re.I)),
    ("notes", re.compile(r"^(?:what are the |show (?:the )?)?release notes$", re.I)),
    ("list", re.compile(r"^list (?:all )?symbols$", re.I)),
    ("locate", re.compile(rf"^where is {_SYM} defined$", re.I)),
]
COMPAT_RX = re.compile(rf"^is {_REV} compatible with {_REV}$", re.I)


@dataclass
class Finding:
    kind: str
    summary: str
    citations: list[Citation] = field(default_factory=list)
    disposition: None = None  # retrieval mode never sets a compatibility disposition
    facts: dict = field(default_factory=dict)
    revision: str | None = None  # set only on labelled per-revision history entries


@dataclass
class RepoFindings:
    repo: str
    revision: str | None
    resolved_sha: str | None = None
    findings: list[Finding] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    unresolved: str | None = None
    disposition: str | None = None  # only set by mode="compatibility" with a runtime adapter
    receipts: list = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    answer: str | None = None
    index_generation: str | None = None
    retrieval_budget: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"repo": self.repo, "revision": self.revision, "resolved_sha": self.resolved_sha,
                "index_generation": self.index_generation,
                "retrieval_budget": self.retrieval_budget,
                "unresolved": self.unresolved,
                "facts": _jsonable(self.facts), "answer": self.answer,
                "findings": [{"kind": f.kind, "summary": f.summary,
                              "citations": [asdict(c) for c in f.citations], "disposition": None,
                              "facts": _jsonable(f.facts), "revision": f.revision}
                             for f in self.findings],
                "citations": [asdict(c) for c in self.citations],
                "gaps": [{"kind": g.kind, "detail": g.detail} for g in self.gaps],
                "disposition": self.disposition,
                "receipts": [asdict(r) for r in self.receipts]}


def _jsonable(v):
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted((_jsonable(x) for x in v), key=repr)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return repr(v)


def _gaps_of(page) -> list[Gap]:
    out = [Gap(str(g.kind), str(g.detail)) for g in page.coverage.get("gaps", [])]
    if page.next_cursor:
        out.append(Gap("truncated", f"only the first {len(page.items)} of {page.coverage.get('total')} "
                                    "items are listed"))
    return out


def _span(c: Citation | None) -> str:
    if c is None:
        return "?"
    return f"{c.path}:{c.start_line}-{c.end_line}" if c.start_line is not None else c.path


def _load(repo: str, config) -> tuple[RepoConfig | None, Gap | None]:
    try:
        if isinstance(config, RepoConfig):
            cfg = config
        elif config is not None:
            cfg = load_config(Path(config))
        else:
            if not isinstance(repo, str) or not NAME_RE.fullmatch(repo):
                return None, Gap("INVALID_REPOSITORY", f"unknown repository {repo!r}: not a valid repository name")
            cfg = load_config(repo)
        if cfg.name != repo:
            return None, Gap("REPOSITORY_SELECTION_MISMATCH", "configuration belongs to a different repository")
        return cfg, None
    except FileNotFoundError:
        return None, Gap("UNKNOWN_REPOSITORY", f"unknown repository {repo!r}: no usable configuration (FileNotFoundError)")
    except (OSError, ValueError) as exc:
        return None, Gap("INVALID_CONFIGURATION", f"unknown repository {repo!r}: no usable configuration ({type(exc).__name__})")


def investigate(repo: str, revision: str | None, question: str, *, graph_name: str | None = None,
                db=None, config: RepoConfig | str | Path | None = None, mode: str = "retrieval",
                runtime_adapter: str | None = None, trace: list[dict] | None = None) -> RepoFindings:
    from rw.repo.budget import BudgetExhausted, ReadLimits, read_scope
    cfg, _ = _load(repo, config)
    limits = (ReadLimits(cfg.query_timeout_seconds, cfg.query_max_rows, cfg.query_max_source_bytes)
              if cfg else ReadLimits())
    with read_scope(limits) as budget:
        out = None
        try:
            out = _investigate(repo, revision, question, graph_name=graph_name, db=db,
                               config=cfg if cfg else config, mode=mode,
                               runtime_adapter=runtime_adapter, trace=trace)
            budget.remaining()
        except BudgetExhausted as exc:
            if out is None:
                out = RepoFindings(repo, revision, unresolved=str(exc),
                                   gaps=[Gap("RETRIEVAL_BUDGET_EXHAUSTED", str(exc))])
        if budget.exhausted:
            # A paged helper may return a gap instead of raising. No partial evidence
            # can become a definitive answer (or a compatibility disposition).
            out.findings, out.citations, out.facts, out.answer = [], [], {}, None
            out.disposition, out.receipts = None, []
            out.unresolved = "retrieval budget exhausted; evidence is incomplete"
            out.gaps = [Gap("RETRIEVAL_BUDGET_EXHAUSTED", f"retrieval {budget.exhausted} budget exhausted; retry with a narrower investigation")]
        out.retrieval_budget = budget.snapshot()
        if trace is not None:
            trace.append({"kind": "retrieval_budget", "repo": repo, **budget.snapshot(include_elapsed=True)})
        return out


def _investigate(repo: str, revision: str | None, question: str, *, graph_name: str | None = None,
                 db=None, config: RepoConfig | str | Path | None = None, mode: str = "retrieval",
                 runtime_adapter: str | None = None, trace: list[dict] | None = None) -> RepoFindings:
    if mode not in ("retrieval", "compatibility"):
        raise ValueError(f"mode must be 'retrieval' or 'compatibility', not {mode!r}")
    out = RepoFindings(repo, revision)
    cfg, err = _load(repo, config)
    if cfg is None:
        out.gaps = [err]
        out.unresolved = err.detail
        return out
    if not revision:
        out.unresolved = f"Which revision of {repo!r} should be investigated? (a tag, branch or commit sha)"
        return out
    from rw.repo.index import graph_name_for
    from rw.repo.query import RepoQuery
    try:
        q = RepoQuery(graph_name or graph_name_for(cfg), repo, db=db, trace=trace)
        sha, gap = q.resolve(revision)
    except Exception as exc:  # graph missing / database unavailable
        out.gaps = [Gap("INDEX_UNAVAILABLE", f"resolve revision failed ({type(exc).__name__}); index or database is unavailable")]
        out.unresolved = (f"repository {repo!r} has no queryable index for revision {revision!r} "
                          f"({type(exc).__name__}); index it first")
        return out
    if gap:
        out.gaps.append(gap)
        out.unresolved = (f"revision {revision!r} cannot be used for {repo!r} ({gap.detail}); "
                          "which indexed revision should be investigated?")
        return out
    out.resolved_sha = sha
    out.index_generation = q._generation

    text = (question or "").strip().rstrip("?.!").strip()
    text = re.sub(r"\s+", " ", text)
    route, m = next(((name, rx.match(text)) for name, rx in ROUTES if rx.match(text)), (None, None))
    if route is None and mode == "compatibility" and COMPAT_RX.match(text):
        out.findings = []
        _compatibility(cfg, out, question, runtime_adapter)
        return out
    if route is None:
        out.gaps.append(Gap("unsupported_question", f"question not recognised; supported shapes: {SUPPORTED}"))
        return out

    handler = {"constant": _constant, "raises": _raises, "dependencies": _deps, "dependents": _deps, "changes": _changes, "fix": _fix,
               "history": _history, "notes": _notes, "list": _list, "locate": _locate}[route]
    generation = q._state()
    from rw.repo.query import EvidenceError, IndexChangedError
    try:
        out.gaps.extend(q._coverage_gaps(sha))
        unresolved = handler(q, out, revision, route, m)
        if q._state() != generation:
            raise IndexChangedError("index publication changed")
    except EvidenceError as exc:
        out.findings, out.citations, out.facts, out.answer = [], [], {}, None
        out.gaps = [exc.gap]
        out.unresolved = "indexed evidence could not be bound to current source and extraction"
        return out
    except IndexChangedError:
        out.findings, out.citations, out.facts, out.answer = [], [], {}, None
        out.gaps = [Gap("INDEX_CHANGED", "index changed during investigation; retry from the first page")]
        out.unresolved = "repository index changed during investigation"
        return out
    except Exception as exc:
        # Preserve selection and expose the failed operation, never a partial supported answer.
        out.findings, out.citations, out.facts, out.answer = [], [], {}, None
        out.gaps = [Gap("RETRIEVAL_FAILED", f"{route} retrieval failed ({type(exc).__name__}); retry investigation")]
        out.unresolved = f"{route} retrieval could not complete"
        return out
    if any(g.kind in {"STALE_EXTRACTION", "STALE_SOURCE", "MISSING_SOURCE", "CONFLICTING_SOURCE",
                      "UNSUPPORTED_FILE_KIND", "INDEX_CHANGED", "RETRIEVAL_FAILED",
                      "RETRIEVAL_TIMEOUT", "RETRIEVAL_BUDGET_EXHAUSTED"} for g in out.gaps):
        # Lower-level paged operations return gaps rather than exceptions. Do not turn those
        # failures into an empty dependency set or a definitive absence conclusion.
        out.findings, out.citations, out.facts, out.answer = [], [], {}, None
        out.unresolved = "current source-backed evidence is unavailable or stale; restore or reindex before retrying"
        return out
    if unresolved:
        out.unresolved = unresolved
        out.findings = []
        out.facts, out.answer = {}, None
    elif not out.facts:
        heads = [f for f in out.findings if f.revision is None and f.facts]
        for f in heads:
            out.facts.update(f.facts)
        if heads:
            out.answer = " ".join(f.summary for f in heads)
    seen = {}
    for f in out.findings:
        if f.revision is not None:  # labelled per-revision entries are not promoted to the top level
            continue
        for c in f.citations:
            seen.setdefault(c, None)
    out.citations = list(seen)
    if mode == "compatibility" and not out.unresolved:
        _compatibility(cfg, out, question, runtime_adapter)
    elif out.findings:
        out.gaps.append(RUNTIME_GAP)
    return out


def _compatibility(cfg: RepoConfig, out: RepoFindings, question: str, adapter_name: str | None) -> None:
    """Disposition from an explicitly named runtime adapter's receipts (S6 status rules)."""
    from rw.repo import runtime
    adapter = runtime.RUNTIME_ADAPTERS.get(adapter_name) if adapter_name else None
    if adapter is None:
        why = "no runtime adapter named" if not adapter_name else f"runtime adapter {adapter_name!r} is not registered"
        out.gaps.append(Gap("NO_RUNTIME_ADAPTER", f"{why}; compatibility is not decided from retrieval alone"))
        out.gaps.append(RUNTIME_GAP)
        return
    sha = out.resolved_sha
    obligations = list(adapter.obligations(cfg.path, sha, question))
    if not obligations:
        out.gaps.append(Gap("NO_MODELED_OBLIGATIONS", f"runtime adapter {adapter_name!r} models no obligation "
                                                      "for this question; nothing was verified"))
        out.gaps.append(RUNTIME_GAP)
        return
    receipts = list(adapter.check(cfg.path, sha, obligations))
    out.receipts = receipts
    disp, missing = runtime.disposition(obligations, receipts, sha, adapter.version)
    out.disposition = disp
    if missing:
        out.gaps.append(Gap("missing_runtime_evidence", "no current receipt (missing or stale revision/"
                                                        "extractor/adapter) for: " + ", ".join(missing)))


# ---------------------------------------------------------------- handlers

@dataclass
class _Resolved:
    qualname: str
    kind: str
    path: str
    citation: Citation


def _match_suffix(syms, name: str):
    """(exact matches, dotted-component suffix matches) among `syms` (objects with .qualname)."""
    exact = [s for s in syms if s.qualname == name]
    suffix = [s for s in syms if s.qualname.endswith("." + name)]
    return exact, suffix


def _resolve_symbol(q, out: RepoFindings, rev: str, name: str):
    """Exact qualname, else the unique qualname ending with `name` on dotted-component boundaries;
    else a gap (unknown / ambiguous)."""
    sha = out.resolved_sha
    syms = q._candidates(sha, name)
    exact, suffix = _match_suffix(syms, name)
    if len({s.path for s in exact}) > 1:
        out.gaps.append(Gap("ambiguous_symbol", f"{name!r} is defined at multiple paths; clarify which one: "
                           + ", ".join(sorted({s.path for s in exact}))))
        return None
    if exact:
        s = exact[0]
        return _Resolved(s.qualname, s.kind, s.path, q._cite(sha, s))
    cands = sorted({s.qualname for s in suffix})
    if len(cands) == 1:
        s = suffix[0]
        return _Resolved(s.qualname, s.kind, s.path, q._cite(sha, s))
    if not cands:
        out.gaps.append(Gap("unknown_symbol", f"{name!r} was not found in extracted evidence for {out.repo} at {rev!r}"))
    else:
        out.gaps.append(Gap("ambiguous_symbol", f"{name!r} matches several symbols; clarify which one: "
                                                + ", ".join(cands)))
    return None


def _deps(q, out, rev, route, m):
    sym = _resolve_symbol(q, out, rev, m.group(1))
    if sym is None:
        return None
    reverse = route == "dependents"
    page = (q.dependents if reverse else q.dependencies)(rev, sym.qualname, hops=1, limit=MAX_ITEMS)
    head = Finding("definition", "", [sym.citation])
    out.findings.append(head)
    targets, external = [], []
    for d in page.items:
        if d.hops == 1:
            name = d.source if reverse else d.target
            lst = external if (d.external and not reverse) else targets
            if name not in lst:
                lst.append(name)
        cits = [c for c in (d.citation, d.target_citation) if c is not None]
        if not cits:
            continue
        ext = ", external/unresolved target" if d.external else ""
        out.findings.append(Finding("dependent" if reverse else "dependency",
                                    f"{d.source} {d.kind} {d.target} ({d.provenance} by {d.extractor}{ext})",
                                    cits))
    head.facts = {"symbol": sym.qualname, ("sources" if reverse else "targets"): targets}
    if not reverse:
        head.facts["external"] = external
    rel = "is used by" if reverse else "depends on"
    head.summary = (f"{sym.kind} {sym.qualname} (defined at {_span(sym.citation)}) {rel}: "
                    + (", ".join(targets) or "no resolved in-repository targets in this retrieval")
                    + (f"; external/unresolved: {', '.join(external)}" if external else ""))
    if not page.items:
        out.gaps.append(Gap("no_relations", f"no {'dependents' if reverse else 'dependencies'} of "
                                            f"{sym.qualname} were extracted at {rev!r}"))
    out.gaps.extend(g for g in _gaps_of(page) if g.kind != "UNKNOWN_SYMBOL")
    return None


def _changes(q, out, rev, route, m):
    a, b = m.group(1), m.group(2)
    for r in (a, b):
        _, gap = q.resolve(r)
        if gap:
            return f"revision {r!r} cannot be used for {out.repo!r} ({gap.detail}); which indexed revision?"
    page = q.changes_between(a, b, limit=MAX_ITEMS)
    fx = {"from": a, "to": b, "added": [], "removed": [], "modified": [],
          "classes_added": [], "classes_removed": [], "classes_modified": [],
          "deleted_files": [], "added_files": [], "modified_files": [], "renamed": [], "tests_changed": []}
    all_cits = []
    for c in page.items:
        is_test = _is_test_path(c.path)
        if not is_test:
            for label, xs in (("added", c.symbols_added), ("removed", c.symbols_removed),
                              ("modified", c.symbols_modified)):
                for qn in xs:
                    kind = c.kinds.get(qn)
                    if kind in ("function", "method"):
                        fx[label].append(qn)
                    elif kind == "class":
                        fx["classes_" + label].append(qn)
        if c.status == "R":
            fx["renamed"].append({"old": c.old_path, "new": c.path,
                                  "similarity": int(c.similarity) if c.similarity is not None else 100})
        if is_test:
            fx["tests_changed"].append(c.path)
        elif c.status in ("A", "D", "M"):
            fx[{"A": "added_files", "D": "deleted_files", "M": "modified_files"}[c.status]].append(c.path)
        for cit in (c.citation, c.old_citation):
            if cit is not None and cit not in all_cits:
                all_cits.append(cit)
        parts = [f"{c.status} {c.path}" + (f" (from {c.old_path})" if c.status == "R" else "")]
        for label, xs in (("added", c.symbols_added), ("removed", c.symbols_removed),
                          ("modified", c.symbols_modified)):
            if xs:
                parts.append(f"{label}: {', '.join(xs[:20])}" + (" ..." if len(xs) > 20 else ""))
        if c.citation is not None:
            out.findings.append(Finding("change", "; ".join(parts), [c.citation]))
    for k in ("added", "removed", "modified", "classes_added", "classes_removed", "classes_modified",
              "deleted_files", "added_files", "modified_files", "tests_changed"):
        fx[k] = sorted(set(fx[k]))
    if all_cits:
        def lst(xs):
            return (", ".join(xs[:100]) + (" ..." if len(xs) > 100 else "")) if xs else "none"
        summary = (f"between {a} and {b}: renamed "
                   + lst([f"{r['old']} -> {r['new']}" for r in fx["renamed"]])
                   + f"; added symbols: {lst(fx['added'])}; removed symbols: {lst(fx['removed'])}"
                   + f"; modified symbols: {lst(fx['modified'])}")
        out.findings.insert(0, Finding("changes_summary", summary, all_cits, facts=fx))
    if not page.items:
        out.gaps.append(Gap("no_changes", f"no indexed file differs between {a!r} and {b!r}"))
    out.gaps.extend(_gaps_of(page))
    return None


def _is_test_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    fn = parts[-1]
    return (any(p in ("tests", "test") for p in parts[:-1])
            or (fn.startswith("test_") and fn.endswith(".py")) or fn.endswith("_test.py"))


def _notes(q, out, rev, route, m):
    page = q.release_notes(rev, limit=MAX_ITEMS)
    for n in page.items:
        text = n.text if len(n.text) <= 1000 else n.text[:1000] + " ..."
        out.findings.append(Finding("release_note", f"{n.path}: {text}", [n.citation]))
    if not page.items:
        out.gaps.append(Gap("no_release_notes", f"no release-note file is indexed at {rev!r}"))
    out.gaps.extend(_gaps_of(page))
    return None


def _sym_finding(s) -> Finding:
    return Finding("symbol", f"{s.kind} {s.qualname} at {_span(s.citation)}", [s.citation])


def _list(q, out, rev, route, m):
    page = q.symbols(rev, limit=MAX_ITEMS)
    out.findings.extend(_sym_finding(s) for s in page.items)
    if not page.items:
        out.gaps.append(Gap("no_symbols", f"no symbols were extracted at {rev!r}"))
    out.gaps.extend(_gaps_of(page))
    return None


def _locate(q, out, rev, route, m):
    page = q.symbols(rev, m.group(1), limit=MAX_ITEMS)
    out.findings.extend(_sym_finding(s) for s in page.items)
    if not page.items:
        out.gaps.append(Gap("unknown_symbol", f"{m.group(1)!r} was not found in extracted evidence for {out.repo} at {rev!r}"))
    out.gaps.extend(_gaps_of(page))
    return None


def _fix_first_tag(q, fix_sha: str) -> str | None:
    """Earliest (by commit time) indexed tag whose commit has `fix_sha` as an ancestor."""
    read = getattr(q, "_q_paged", lambda cypher, params: q._q(cypher))
    rows = read("MATCH (t:Tag)-[:POINTS_TO]->(c:Commit) RETURN t.name, c.sha, c.author_time "
                "ORDER BY c.author_time, t.name", {})
    for name, sha, _ in rows:
        if sha == fix_sha or q._is_ancestor(fix_sha, sha):
            return name
    return None


def _fix(q, out, rev, route, m):
    fs = q.fix_status(rev, m.group(1))
    out.gaps.extend(Gap(g.kind, g.detail) for g in fs.gaps)
    fix_sha, _ = q.resolve(m.group(1))
    first = _fix_first_tag(q, fix_sha) if fix_sha else None
    facts = {"fix_commit": fix_sha, "state": fs.state, "first_tag_containing": first}
    summary = (f"fix {fix_sha or m.group(1)} at {rev}: {fs.state} - {fs.reason}; first tag containing "
               f"the fix commit: {first}")
    cits = [c for c in fs.citations if c.commit == out.resolved_sha]
    if cits:
        out.findings.append(Finding("fix_content", summary, cits, facts=facts))
    else:
        out.gaps.append(Gap("fix_uncited", f"{fs.state}: {fs.reason}"))
        out.facts, out.answer = facts, summary
    return None


def _history(q, out, rev, route, m):
    name = m.group(1)
    rows = q._q_paged("MATCH (t:Tag)-[:POINTS_TO]->(c:Commit) RETURN t.name, c.sha, c.author_time "
                "ORDER BY c.author_time, t.name", {})
    revs, seen = [], set()
    for tag, sha, _ in rows:
        if sha in seen or sha == out.resolved_sha:
            continue
        if q._is_ancestor(sha, out.resolved_sha):
            seen.add(sha)
            revs.append(tag)
    revs = revs[-(MAX_HISTORY_REVS - 1):] + [rev]
    # resolve the name (exact, else a unique dotted suffix) across every examined revision
    exact_any, suffix = False, set()
    for r in revs:
        sha_r, g = q.resolve(r)
        if g:
            continue
        ex, sf = _match_suffix(q._candidates(sha_r, name), name)
        exact_any = exact_any or bool(ex)
        suffix.update(s.qualname for s in sf)
    symbol = name
    if not exact_any:
        if len(suffix) > 1:
            out.gaps.append(Gap("ambiguous_symbol", f"{name!r} matches several symbols; clarify which one: "
                                                    + ", ".join(sorted(suffix))))
            return None
        if len(suffix) == 1:
            symbol = next(iter(suffix))
    entries = q.symbol_history(symbol, revs)
    first_present = first_absent = None
    for e in entries:
        if e.gap:
            out.gaps.append(e.gap)
        if e.present is None:
            continue
        if e.present and first_present is None:
            first_present = e.rev
        elif not e.present and first_present is not None and first_absent is None:
            first_absent = e.rev
        if e.present and e.citation is not None:
            out.findings.append(Finding("history_entry", f"{symbol} present at {e.rev} ({_span(e.citation)})",
                                        [e.citation], revision=e.rev))
        elif not e.present:
            out.findings.append(Finding("history_entry", f"{symbol} absent at {e.rev}", [], revision=e.rev))
    last = entries[-1] if entries else None
    at_req = last.present if last else None
    if first_present is None:
        out.findings = []
        out.gaps.append(Gap("unknown_symbol", f"{symbol!r} was not found in extracted evidence at examined revisions: "
                                              + ", ".join(revs)))
    else:
        facts = {"symbol": symbol, "first_present_revision": first_present,
                 "first_absent_revision": first_absent, "present_at_requested": at_req}
        cits = [last.citation] if (at_req and last.citation is not None
                                   and last.citation.commit == out.resolved_sha) else []
        summary = (f"{symbol}: first present at {first_present}; first absent (after appearing) at "
                   f"{first_absent}; present at requested revision {rev}: {at_req}")
        out.findings.insert(0, Finding("symbol_history", summary, cits, facts=facts))
    out.gaps.append(Gap("history_sampled", "only tagged ancestor revisions and the requested revision were "
                                           "examined: " + ", ".join(revs)))
    return None


# ---------------------------------------------------------------- source facts (parsed, never executed)

MAX_SCAN_FILES = 5000


def _parse_at(q, sha: str, path: str):
    """(text, tree, content_hash) of `path` at `sha`, read from its git blob; None when unavailable."""
    entry = q._files(sha).get(path)
    if entry is None:
        return None
    data = q._source(sha, path, entry[0])
    text = data.decode("utf-8", "replace")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return text, ast.parse(text, filename=path), entry[0]
    except (SyntaxError, ValueError):
        return None


def _assignments(tree, mod: str):
    """(qualname, node) for module- and class-level assignments of simple names."""
    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        yield f"{prefix}.{t.id}", node
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                yield f"{prefix}.{node.target.id}", node
            elif isinstance(node, ast.ClassDef):
                yield from walk(node.body, f"{prefix}.{node.name}")
    yield from walk(tree.body, mod)


def _constant(q, out, rev, route, m):
    from rw.repo.adapters.python import module_name
    name = m.group(1)
    sha = out.resolved_sha
    files = q._files(sha)
    paths = sorted(p for p in files if p.endswith((".py", ".pyi")))
    if "." in name:
        narrowed = [p for p in paths if name.startswith(module_name(p) + ".")]
        paths = narrowed or paths
    if len(paths) > MAX_SCAN_FILES:
        out.gaps.append(Gap("truncated", f"only {MAX_SCAN_FILES} of {len(paths)} Python files were scanned"))
        paths = paths[:MAX_SCAN_FILES]
    hits = {}
    for p in paths:
        parsed = _parse_at(q, sha, p)
        if parsed is None:
            continue
        text, tree, h = parsed
        for qual, node in _assignments(tree, module_name(p)):
            if qual == name or qual.endswith("." + name):
                hits[qual] = (p, node, text, h)  # the last assignment at this level wins
    exact = [k for k in hits if k == name]
    keys = exact or sorted(hits)
    if not keys:
        out.gaps.append(Gap("unknown_symbol", f"{name!r} is not assigned at module or class level in "
                                              f"{out.repo} at {rev!r}"))
        return None
    if len(keys) > 1:
        out.gaps.append(Gap("ambiguous_symbol", f"{name!r} matches several assignments; clarify which one: "
                                                + ", ".join(keys)))
        return None
    qual = keys[0]
    p, node, text, h = hits[qual]
    expr = ast.get_source_segment(text, node.value) or ast.unparse(node.value)
    cit = Citation(out.repo, sha, p, node.lineno, node.end_lineno or node.lineno, h)
    facts = {"symbol": qual, "expression": expr, "is_plain_literal": False, "evaluated": False}
    try:
        facts["value"] = ast.literal_eval(node.value)  # literals only; source is never executed
        facts["is_plain_literal"] = facts["evaluated"] = True
        summary = f"{qual} = {facts['value']!r} at {rev} ({_span(cit)})"
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        out.gaps.append(Gap("non_literal_value", f"{qual} is assigned the non-literal expression {expr!r}; "
                                                 "it was not evaluated"))
        summary = f"{qual} is assigned the expression {expr} at {rev} ({_span(cit)}); value not evaluated"
    out.findings.append(Finding("constant", summary, [cit], facts=facts))
    return None


def _raises(q, out, rev, route, m):
    sym = _resolve_symbol(q, out, rev, m.group(1))
    if sym is None:
        return None
    if sym.kind not in ("function", "method"):
        out.gaps.append(Gap("not_a_function", f"{sym.qualname} is a {sym.kind}, not a function"))
        return None
    parsed = _parse_at(q, out.resolved_sha, sym.citation.path)
    fn = None
    if parsed is not None:
        fn = next((n for n in ast.walk(parsed[1]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.lineno == sym.citation.start_line
                   and n.name == sym.qualname.rsplit(".", 1)[-1]), None)
    if fn is None:
        out.gaps.append(Gap("MISSING_SOURCE", f"cannot read the source of {sym.qualname} at {rev!r}"))
        return None
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Raise) and n.exc is not None:
            e = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
            if isinstance(e, (ast.Name, ast.Attribute)):
                names.add(ast.unparse(e))
    exc = sorted(names)
    facts = {"symbol": sym.qualname, "exceptions": exc}
    summary = (f"{sym.qualname} at {rev} ({_span(sym.citation)}) raises: "
               + (", ".join(exc) or "nothing explicitly"))
    out.findings.append(Finding("raises", summary, [sym.citation], facts=facts))
    if not exc:
        out.gaps.append(Gap("no_raise", f"no raise statement in {sym.qualname}; exceptions raised by callees "
                                        "are not traced"))
    return None
