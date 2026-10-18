"""S4 - large histories with bounded retrieval (docs/repo/REQUIREMENTS.md S4; docs/repo/DESIGN.md).

Needs FalkorDB at 127.0.0.1:6379. Builds a synthetic repo in tmp_path: 30 modules pkg/mNN.py x 20
functions fNN. Inside a module f_j calls f_{j+1..j+4}; f19 of module i calls pkg.m{i+1}.f00 (imported).
Ten annotated tags v1.0.0..v1.9.0; each tag after the first rewrites two modules (constant changes).

Interface assumed (in addition to tests/repo/test_s2_evidence.py and test_s3_revisions.py):

rw.repo.index.index_repository(config, graph_name=None, db=None, *, interrupt_after=None) -> IndexReport
  IndexReport: status ("COMPLETE"), commits, tags, blobs, blobs_new, blobs_reused, symbols,
    relations, import_run_id, metrics (dict).
  - blobs_new counts distinct file contents extracted in THIS run; blobs_reused counts contents
    already extracted by the same extractor (language@adapter.version) in an earlier run.
    report.symbols counts only symbols extracted in this run (no re-extraction of reused blobs).
  - Extractor identity is `<language>@<adapter.version>`: changing the adapter's `version` attribute
    invalidates earlier extraction; re-indexing re-extracts every blob, and afterwards queries return
    only relations whose `extractor` is the new identity (no stale duplicates).
  - interrupt_after=N raises ImportInterrupted after N new blobs. The ImportRun node stays STARTED
    or FAILED; queries at revisions of that run return a Page with no items and
    Gap(kind="INCOMPLETE_IMPORT"). Running index_repository again completes (status COMPLETE) and the
    resulting graph has the same Commit and Symbol node counts as a clean full index.
  - metrics (and (:ImportRun).metrics_json, JSON of the same dict) contain numeric >= 0 values for
    seconds, peak_memory_bytes, blobs_new, blobs_reused, commits, nodes, edges. Every run (initial
    and update) has its own ImportRun node with its own metrics_json.

rw.repo.query.RepoQuery paging (symbols, dependencies, dependents, ...):
  - limit must be an int in 1..200 else ValueError. len(page.items) <= limit.
  - page.coverage["total"] = total number of items of the full (bounded) result; following
    next_cursor yields every item exactly once; truncated is True iff next_cursor is not None.
  - coverage["returned"] (optional) = number of items in this page when present.
  - A malformed, negative-offset or out-of-range cursor raises ValueError or returns a Page with
    no items and a Gap in coverage["gaps"] (kind e.g. "INVALID_CURSOR"); it never silently
    restarts from the first page or returns a silent empty success.
  - dependencies(hops<=5): when the traversal is bounded before all reachable edges are collected,
    the bound is visible: some page carries a Gap(kind="TRUNCATED") in coverage["gaps"] (or
    coverage["frontier_truncated"] is True). Otherwise all reachable edges appear across pages.
  - symbol_history(symbol, revs) returns exactly one HistoryEntry per requested rev.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

N_MOD, N_FN = 30, 20
TAGS = [f"v1.{i}.0" for i in range(10)]


def _module_src(i: int, salt: int = 0, extra_top: int = 0, extra_fn: str = "") -> str:
    lines = ["# padding"] * extra_top
    if i + 1 < N_MOD:
        lines.append(f"from pkg.m{i + 1:02d} import f00 as next_f00")
    lines.append("")
    for j in range(N_FN):
        lines.append(f"def f{j:02d}(x):")
        calls = [f"f{k:02d}(x)" for k in range(j + 1, min(j + 5, N_FN))]
        if j == N_FN - 1 and i + 1 < N_MOD:
            calls.append("next_f00(x)")
        lines.append(f"    return {' + '.join(calls) if calls else 'x'} + {salt}")
        lines.append("")
    if extra_fn:
        lines.append(extra_fn)
    return "\n".join(lines) + "\n"


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _commit_tag(git, repo, msg, tag, n):
    date = f"2024-03-{n + 1:02d}T00:00:00+00:00"
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, date=date)
    git(repo, "tag", "-a", tag, "-m", f"release {tag}", date=date)


def _changed_modules(t: int) -> list[int]:
    return [] if t == 0 else [(2 * t) % N_MOD, (2 * t + 7) % N_MOD]


@pytest.fixture
def scale_repo(tmp_path, git_cmd):
    repo = tmp_path / "scale"
    repo.mkdir()
    git_cmd(repo, "init", "-q")
    _w(repo, "pkg/__init__.py", "")
    for t, tag in enumerate(TAGS):
        if t == 0:
            for i in range(N_MOD):
                _w(repo, f"pkg/m{i:02d}.py", _module_src(i))
        for i in _changed_modules(t):
            extra = "def g_new(x):\n    return x\n" if (t == 5 and i == _changed_modules(5)[0]) else ""
            _w(repo, f"pkg/m{i:02d}.py", _module_src(i, salt=t, extra_fn=extra))
        _commit_tag(git_cmd, repo, f"release {tag}", tag, t)
    return repo


def _cfg(write_config, repo, name="scale"):
    from rw.repo.config import load_config
    return load_config(write_config(name, repo))


@pytest.fixture
def indexed(scale_repo, write_config, graph_name):
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery
    cfg = _cfg(write_config, scale_repo)
    report = index_repository(cfg, graph_name=graph_name)
    assert report.status == "COMPLETE"
    return RepoQuery(graph_name, "scale"), scale_repo, cfg, report


@pytest.fixture
def second_graph():
    import uuid
    name = f"rw_test_repo_{uuid.uuid4().hex[:12]}"
    yield name
    try:
        from rw import graph as G
        G.connect().select_graph(name).delete()
    except Exception:
        pass


def _rev(repo, rev):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _all_pages(fn, limit=50, max_pages=500):
    pages, cursor = [], None
    for _ in range(max_pages):
        page = fn(limit=limit, cursor=cursor)
        pages.append(page)
        assert len(page.items) <= limit
        cursor = page.next_cursor
        if cursor is None:
            break
    else:
        pytest.fail("pagination did not terminate")
    return pages


def _gap_kinds(page):
    return [g.kind for g in page.coverage.get("gaps", [])]


def _graph(name):
    from rw import graph as G
    return G.connect().select_graph(name)


def _count(graph_name, label):
    return _graph(graph_name).query(f"MATCH (n:{label}) RETURN count(n)").result_set[0][0]


# ---------------------------------------------------------------- 1. pagination

def _check_paging(pages):
    items = [it for p in pages for it in p.items]
    total = pages[0].coverage["total"]
    assert len(items) == total
    for p in pages[:-1]:
        assert p.truncated is True and p.next_cursor is not None
    assert pages[-1].truncated is False and pages[-1].next_cursor is None
    for p in pages:
        assert p.coverage["total"] == total
        if "returned" in p.coverage:
            assert p.coverage["returned"] == len(p.items)
    return items


def test_symbols_pagination_exact_once(indexed):
    q, *_ = indexed
    pages = _all_pages(lambda **kw: q.symbols("v1.9.0", **kw))
    items = _check_paging(pages)
    assert len(pages) > 5
    ids = [(it.path, it.qualname) for it in items]
    assert len(ids) == len(set(ids)), "duplicate symbols across pages"
    fns = {qn for _, qn in ids if qn.rsplit(".", 1)[-1].startswith("f")}
    assert fns == {f"pkg.m{i:02d}.f{j:02d}" for i in range(N_MOD) for j in range(N_FN)}


def test_dependencies_pagination_exact_once(indexed):
    q, *_ = indexed
    pages = _all_pages(lambda **kw: q.dependencies("v1.9.0", "pkg.m00.f00", hops=5, **kw))
    items = _check_paging(pages)
    keys = [(i.source, i.target, i.kind) for i in items]
    assert len(keys) == len(set(keys)), "duplicate edges across pages"
    assert len(pages) >= 2
    assert all(1 <= i.hops <= 5 for i in items)


def test_limit_bounds_rejected(indexed):
    q, *_ = indexed
    for bad in (0, -1, 201, 10_000):
        with pytest.raises(ValueError):
            q.symbols("v1.9.0", limit=bad)
        with pytest.raises(ValueError):
            q.dependencies("v1.9.0", "pkg.m00.f00", hops=2, limit=bad)
    assert len(q.symbols("v1.9.0", limit=200).items) == 200


@pytest.mark.parametrize("cursor", [
    "!!!not-a-cursor",
    "bzotNQ==",                       # base64 "o:-5" (negative offset)
    "bzoxMDAwMDAw",                   # base64 "o:1000000" (beyond the result)
    "eyJvIjogMX0=",                   # base64 '{"o": 1}' (forged structure)
])
def test_bad_cursor_is_error_or_gap_never_restart(indexed, cursor):
    q, *_ = indexed
    first = q.symbols("v1.9.0", limit=50)
    try:
        page = q.symbols("v1.9.0", limit=50, cursor=cursor)
    except ValueError:
        return
    assert page.items == [], "a forged cursor must not silently restart or return data"
    assert page.coverage.get("gaps"), "a forged cursor must yield a visible Gap"
    assert [i.qualname for i in page.items] != [i.qualname for i in first.items]


# ---------------------------------------------------------------- 2. multi-release traversal

def test_symbol_history_across_ten_tags(indexed):
    q, repo, *_ = indexed
    hist = q.symbol_history("pkg.m04.f05", TAGS)
    assert [h.rev for h in hist] == TAGS
    for tag, h in zip(TAGS, hist):
        sha = _rev(repo, tag)
        assert h.commit == sha and h.present is True and h.gap is None
        data = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:pkg/m04.py"],
                              capture_output=True, check=True).stdout
        assert h.content_hash == hashlib.sha256(data).hexdigest()
        assert h.citation.commit == sha and h.citation.path == "pkg/m04.py"
    # m04 changes at t=2 (2*2) only -> exactly two distinct contents across the ten tags
    assert len({h.content_hash for h in hist}) == 2

    added_in = _changed_modules(5)[0]
    g = q.symbol_history(f"pkg.m{added_in:02d}.g_new", TAGS)
    assert [h.present for h in g] == [False] * 5 + [True] * 5


# ---------------------------------------------------------------- 3. hop / frontier bound

def _expected_edges(hops):
    adj = {}
    for i in range(N_MOD):
        for j in range(N_FN):
            src = f"pkg.m{i:02d}.f{j:02d}"
            tg = [f"pkg.m{i:02d}.f{k:02d}" for k in range(j + 1, min(j + 5, N_FN))]
            if j == N_FN - 1 and i + 1 < N_MOD:
                tg.append(f"pkg.m{i + 1:02d}.f00")
            adj[src] = tg
    dist, frontier, edges = {"pkg.m00.f00": 0}, ["pkg.m00.f00"], set()
    while frontier:
        nxt = []
        for n in frontier:
            if dist[n] >= hops:
                continue
            for t in adj.get(n, []):
                edges.add((n, t))
                if t not in dist:
                    dist[t] = dist[n] + 1
                    nxt.append(t)
        frontier = nxt
    return edges


def test_long_chain_hops_reports_truncation_not_silent_drop(indexed):
    q, *_ = indexed
    expected = _expected_edges(5)
    assert len(expected) > 50
    first = q.dependencies("v1.9.0", "pkg.m00.f00", hops=5, limit=50)
    assert len(first.items) == 50
    assert first.truncated is True and first.next_cursor is not None
    pages = _all_pages(lambda **kw: q.dependencies("v1.9.0", "pkg.m00.f00", hops=5, **kw))
    got = {(i.source, i.target) for p in pages for i in p.items if i.kind == "CALLS"}
    bounded = any("TRUNCATED" in _gap_kinds(p) or p.coverage.get("frontier_truncated") for p in pages)
    if not bounded:
        assert expected <= got, f"edges silently dropped: {sorted(expected - got)[:5]}"
    assert got <= expected | {(s, t) for s, t in got if not t.startswith("pkg.")}


# ---------------------------------------------------------------- 4. incremental indexing

def _add_release(git, repo, tag, n, modify=(), delete=(), new=None, edit=None):
    for i in modify:
        _w(repo, f"pkg/m{i:02d}.py", _module_src(i, salt=100 + n))
    for rel in delete:
        (repo / rel).unlink()
    for rel, text in (new or {}).items():
        _w(repo, rel, text)
    for rel, text in (edit or {}).items():
        _w(repo, rel, text)
    _commit_tag(git, repo, f"release {tag}", tag, n)


def _sym_snapshot(q, rev):
    return [(i.path, i.qualname, i.citation.start_line, i.citation.end_line, i.citation.content_hash)
            for p in _all_pages(lambda **kw: q.symbols(rev, **kw), limit=200) for i in p.items]


def test_incremental_update_reuses_unchanged_blobs(indexed, git_cmd):
    from rw.repo.index import index_repository
    q, repo, cfg, first = indexed
    before_old = _sym_snapshot(q, "v1.3.0")
    deps_old = [(i.source, i.target, i.kind) for i in q.dependencies("v1.3.0", "pkg.m00.f00", hops=3,
                                                                      limit=200).items]
    _add_release(git_cmd, repo, "v1.10.0", 10, modify=(1, 3),
                 new={"pkg/brand_new.py": "def fresh(x):\n    return x * 3\n"})
    upd = index_repository(cfg, graph_name=first.graph_name)
    assert upd.status == "COMPLETE"
    assert upd.blobs_new == 3, f"only 3 file contents are new, got blobs_new={upd.blobs_new}"
    assert upd.blobs_reused > 0
    assert upd.blobs_reused + upd.blobs_new == upd.blobs
    # extraction only for new contents: 2 modules x (20 functions + module) + brand_new (fresh + module)
    assert upd.symbols == 2 * (N_FN + 1) + 2
    assert upd.import_run_id != first.import_run_id

    from rw.repo.query import RepoQuery
    q2 = RepoQuery(first.graph_name, "scale")
    assert _sym_snapshot(q2, "v1.3.0") == before_old
    assert [(i.source, i.target, i.kind) for i in q2.dependencies("v1.3.0", "pkg.m00.f00", hops=3,
                                                                  limit=200).items] == deps_old
    assert q2.symbols("v1.10.0", name="pkg.brand_new.fresh").items


# ---------------------------------------------------------------- 5. invalidation

def test_changed_and_deleted_evidence_invalidated_at_new_revision(indexed, git_cmd):
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery
    q, repo, cfg, first = indexed
    old_f = q.symbols("v1.9.0", name="pkg.m01.f00").items
    assert len(old_f) == 1
    old_g = q.symbols("v1.9.0", name="pkg.m02.f03").items
    assert len(old_g) == 1
    _add_release(git_cmd, repo, "v1.10.0", 10, delete=("pkg/m02.py",),
                 edit={"pkg/m01.py": _module_src(1, salt=55, extra_top=3)})
    assert index_repository(cfg, graph_name=first.graph_name).status == "COMPLETE"
    q2 = RepoQuery(first.graph_name, "scale")

    new_f = q2.symbols("v1.10.0", name="pkg.m01.f00").items
    assert len(new_f) == 1
    assert new_f[0].citation.start_line == old_f[0].citation.start_line + 3
    assert new_f[0].citation.content_hash != old_f[0].citation.content_hash
    assert not [i for p in _all_pages(lambda **kw: q2.symbols("v1.10.0", **kw), limit=200)
                for i in p.items if i.path == "pkg/m02.py"]
    # old revision still answers with old evidence
    again = q2.symbols("v1.9.0", name="pkg.m01.f00").items
    assert [(i.citation.start_line, i.citation.content_hash) for i in again] == \
        [(i.citation.start_line, i.citation.content_hash) for i in old_f]
    assert len(q2.symbols("v1.9.0", name="pkg.m02.f03").items) == 1
    hist = q2.symbol_history("pkg.m02.f03", ["v1.9.0", "v1.10.0"])
    assert [h.present for h in hist] == [True, False]


def test_extractor_version_change_reextracts_and_drops_stale(indexed, monkeypatch):
    from rw.repo.adapters.python import PythonAdapter
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery
    q, repo, cfg, first = indexed
    old_ext = {i.extractor for i in q.dependencies("v1.9.0", "pkg.m00.f00", hops=2, limit=200).items}
    assert old_ext and all(e.startswith("python@") for e in old_ext)
    monkeypatch.setattr(PythonAdapter, "version", "999-test")
    upd = index_repository(cfg, graph_name=first.graph_name)
    assert upd.status == "COMPLETE"
    assert upd.blobs_reused == 0, "blobs extracted by an older extractor must not be reused"
    assert upd.blobs_new == first.blobs_new + first.blobs_reused
    q2 = RepoQuery(first.graph_name, "scale")
    for rev in ("v1.0.0", "v1.9.0"):
        items = [i for p in _all_pages(lambda **kw: q2.dependencies(rev, "pkg.m00.f00", hops=3, **kw))
                 for i in p.items]
        assert items
        assert {i.extractor for i in items} == {"python@999-test"}
        keys = [(i.source, i.target, i.kind) for i in items]
        assert len(keys) == len(set(keys))
    stale = _graph(first.graph_name).query(
        "MATCH ()-[e]->() WHERE e.extractor IS NOT NULL AND e.extractor <> 'python@999-test' "
        "RETURN count(e)").result_set[0][0]
    assert stale == 0, "edges from the old extractor version remain in the graph"


# ---------------------------------------------------------------- 6. interrupted import

def test_interrupted_import_never_complete_then_recovers(scale_repo, write_config, graph_name, second_graph):
    from rw.repo.index import ImportInterrupted, index_repository
    from rw.repo.query import RepoQuery
    cfg = _cfg(write_config, scale_repo)
    with pytest.raises(ImportInterrupted):
        index_repository(cfg, graph_name=graph_name, interrupt_after=5)
    q = RepoQuery(graph_name, "scale")
    for rev in ("v1.0.0", "v1.9.0"):
        page = q.symbols(rev)
        assert page.items == []
        assert "INCOMPLETE_IMPORT" in _gap_kinds(page)
        dep = q.dependencies(rev, "pkg.m00.f00")
        assert dep.items == [] and "INCOMPLETE_IMPORT" in _gap_kinds(dep)
    statuses = [r[0] for r in _graph(graph_name).query("MATCH (r:ImportRun) RETURN r.status").result_set]
    assert statuses and set(statuses) <= {"STARTED", "FAILED"}

    done = index_repository(cfg, graph_name=graph_name)
    assert done.status == "COMPLETE"
    q2 = RepoQuery(graph_name, "scale")
    assert q2.symbols("v1.9.0").items
    statuses = [r[0] for r in _graph(graph_name).query("MATCH (r:ImportRun) RETURN r.status").result_set]
    assert "COMPLETE" in statuses

    clean = index_repository(cfg, graph_name=second_graph)
    assert clean.status == "COMPLETE"
    for label in ("Commit", "Symbol", "Blob", "Tag"):
        assert _count(graph_name, label) == _count(second_graph, label), label
    assert _sym_snapshot(q2, "v1.9.0") == _sym_snapshot(RepoQuery(second_graph, "scale"), "v1.9.0")


# ---------------------------------------------------------------- 7. measurable costs

METRIC_KEYS = ("seconds", "peak_memory_bytes", "blobs_new", "blobs_reused", "commits", "nodes", "edges")


def _check_metrics(m):
    for k in METRIC_KEYS:
        assert k in m, k
        assert isinstance(m[k], (int, float)) and not isinstance(m[k], bool) and m[k] >= 0, (k, m[k])


def test_initial_and_update_costs_recorded_separately(indexed, git_cmd):
    from rw.repo.index import index_repository
    q, repo, cfg, first = indexed
    _check_metrics(first.metrics)
    assert first.metrics["peak_memory_bytes"] > 0 and first.metrics["nodes"] > 0
    _add_release(git_cmd, repo, "v1.10.0", 10, modify=(5,))
    upd = index_repository(cfg, graph_name=first.graph_name)
    _check_metrics(upd.metrics)
    assert upd.metrics["blobs_new"] == 1 and upd.metrics["blobs_reused"] > 0
    rows = _graph(first.graph_name).query(
        "MATCH (r:ImportRun) RETURN r.id, r.status, r.metrics_json").result_set
    by_id = {r[0]: (r[1], json.loads(r[2])) for r in rows}
    assert first.import_run_id in by_id and upd.import_run_id in by_id
    for rid in (first.import_run_id, upd.import_run_id):
        status, m = by_id[rid]
        assert status == "COMPLETE"
        _check_metrics(m)
    assert by_id[first.import_run_id][1]["blobs_new"] != by_id[upd.import_run_id][1]["blobs_new"]


# ---------------------------------------------------------------- optional real-repo smoke

REQUESTS = Path(__file__).resolve().parents[2] / "artifacts" / "repos" / "requests"


@pytest.mark.realrepo
@pytest.mark.skipif(not os.environ.get("RW_REALREPO_SMOKE"),
                    reason="slow (~8 min: walks the full requests history); set RW_REALREPO_SMOKE=1")
@pytest.mark.skipif(not (REQUESTS / "HEAD").exists() and not (REQUESTS / ".git").exists(),
                    reason="artifacts/repos/requests not cloned")
def test_requests_bounded_slice_smoke(graph_name):
    from rw.repo.config import RepoConfig
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery
    cfg = RepoConfig(name="requests-slice", path=str(REQUESTS), tag_pattern=r"^v2\.3[34]\.\d+$",
                     include=["src/requests/*.py", "requests/*.py"])
    report = index_repository(cfg, graph_name=graph_name)
    assert report.status == "COMPLETE" and report.tags >= 2
    _check_metrics(report.metrics)
    q = RepoQuery(graph_name, "requests-slice")
    pages = _all_pages(lambda **kw: q.symbols("v2.34.2", **kw))
    _check_paging(pages)
