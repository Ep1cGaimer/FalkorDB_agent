"""S2 — useful code and history evidence (docs/plans/repo-integration-v1.md, query.py contract).

Needs FalkorDB at 127.0.0.1:6379. Uses the `make_history_repo` fixture (tests/repo/conftest.py):
tags v1.0.0 / v1.1.0 / v1.2.0 on main; line numbers of its files are documented there.

Interface assumed:

rw.repo.query
  RepoQuery(graph_name: str, repo_name: str, db=None)
    Reads the per-repo graph written by rw.repo.index.index_repository(config, graph_name=...).
    `rev` arguments accept a tag name, branch name, or (abbreviated or full) commit sha.
    All list methods take limit (1..200, default 50) and cursor (str|None) and return
    rw.repo.model.Page(items, next_cursor, truncated, coverage).
    Unknown / unindexed revision: returns a Page with items == [] and
      page.coverage["gaps"] a list containing rw.repo.model.Gap(kind="UNKNOWN_REVISION", detail
      mentioning the revision string). Never a silent empty success (coverage["gaps"] is always a
      list, empty when there is no gap). symbol_history marks such revisions with present=None
      and gap set instead.

    symbols(rev, name=None, limit=50, cursor=None) -> Page[SymbolItem]
      SymbolItem: id (str "<repo>:<content_hash>:<qualname>"), qualname, kind, path, citation.
      `name` filters by exact qualname or by last dotted component.
      Only internal (non-external) symbols defined in files present at `rev`.

    dependencies(rev, symbol, hops=1, limit=50, cursor=None) -> Page[DependencyItem]
    dependents(rev, symbol, hops=1, limit=50, cursor=None)   -> Page[DependencyItem]
      `symbol` is a qualname. Targets are resolved against symbols defined at the SAME revision
      across all files (cross-file). Items are deduplicated per (source, target, kind).
      DependencyItem: source (qualname), target (qualname or raw name if external),
        kind in {"IMPORTS","CALLS","INHERITS"}, provenance in {"parsed","inferred"},
        extractor (str "python@<version>"), hops (int >=1, distance from the queried symbol),
        external (bool: True when the target is not defined in the repo at rev),
        citation (Citation of the SOURCE symbol's definition at rev — where the edge was parsed),
        target_citation (Citation of the target definition at rev, or None when external).
      For dependents, `source` is the dependent and `target` the symbol it depends on.

    changes_between(rev_a, rev_b, limit=50, cursor=None) -> Page[ChangeItem]
      ChangeItem: path, status in {"A","M","D","R"}, old_path (str|None),
        (a symbol is "modified" when present at both revs with different source text in its span)
        symbols_added, symbols_removed, symbols_modified (lists of qualnames),
        citation: for A/M/R a Citation at rev_b, for D a Citation at rev_a; whole-file span
        (start_line=1, end_line=number of lines) with the file's content_hash.

    release_notes(rev, limit=50, cursor=None) -> Page[NoteItem]
      NoteItem: path, text (the note excerpt for the release the revision belongs to, or full
      file text), citation (Citation at rev covering the lines of `text`).

    symbol_history(symbol, revs: list[str]) -> list[HistoryEntry], in the order of `revs`
      HistoryEntry: rev (as given), commit (full sha or None), present (bool, or None if the
        revision is unknown), content_hash (of the defining file at that rev, or None),
        citation (Citation or None when absent), gap (Gap or None).

rw.repo.model.Citation(repo, commit, path, start_line, end_line, content_hash): `commit` is the
full 40-hex sha of the REQUESTED revision (peeled tag), never of an ancestor.
"""
import hashlib
import re
import subprocess

import pytest


# ---------------------------------------------------------------- helpers

@pytest.fixture
def hist(make_history_repo, write_config, graph_name):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery

    repo = make_history_repo()
    cfg = load_config(write_config("hist", repo, revisions=["main"]))
    report = index_repository(cfg, graph_name=graph_name)
    assert report.status == "COMPLETE"
    q = RepoQuery(graph_name, "hist")
    shas = {t: _rev_parse(repo, t) for t in ("v1.0.0", "v1.1.0", "v1.2.0")}
    return q, repo, shas


def _rev_parse(repo, rev):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _show(repo, commit, path) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"],
                          capture_output=True, check=True).stdout


def assert_resolves(repo, cit, *, commit, contains=None, repo_name="hist"):
    """A citation resolves: right repo + requested commit, blob hash matches, span holds `contains`."""
    assert cit is not None
    assert cit.repo == repo_name
    assert re.fullmatch(r"[0-9a-f]{40}", cit.commit)
    assert cit.commit == commit, "citation must name the requested revision, not an ancestor"
    data = _show(repo, cit.commit, cit.path)
    assert hashlib.sha256(data).hexdigest() == cit.content_hash
    lines = data.decode("utf-8").splitlines()
    assert 1 <= cit.start_line <= cit.end_line <= max(len(lines), 1)
    span = "\n".join(lines[cit.start_line - 1:cit.end_line])
    if contains is not None:
        assert contains in span, f"{contains!r} not in cited span {cit.path}:{cit.start_line}-{cit.end_line}"
    return span


def _gaps(page):
    gaps = page.coverage.get("gaps")
    assert isinstance(gaps, list)
    return gaps


def _all(fn, *args, **kw):
    items, cursor = [], None
    for _ in range(50):
        page = fn(*args, cursor=cursor, **kw)
        items.extend(page.items)
        cursor = page.next_cursor
        if not cursor:
            return items
    raise AssertionError("pagination did not terminate")


# ---------------------------------------------------------------- symbols / provenance

def test_symbols_carry_revision_path_span_hash(hist):
    q, repo, shas = hist
    page = q.symbols("v1.0.0", name="app.service.process")
    assert _gaps(page) == []
    [item] = page.items
    assert item.qualname == "app.service.process"
    assert item.kind == "function"
    assert item.path == "app/service.py"
    assert item.id.startswith("hist:") and item.id.endswith(":app.service.process")
    assert item.citation.path == "app/service.py"
    assert (item.citation.start_line, item.citation.end_line) == (5, 6)
    assert item.id.split(":")[1] == item.citation.content_hash
    assert_resolves(repo, item.citation, commit=shas["v1.0.0"], contains="def process")


def test_symbols_by_short_name(hist):
    q, repo, shas = hist
    items = q.symbols("v1.1.0", name="save").items
    assert [i.qualname for i in items] == ["app.store.save"]
    assert (items[0].citation.start_line, items[0].citation.end_line) == (5, 6)
    assert_resolves(repo, items[0].citation, commit=shas["v1.1.0"], contains="def save")


def test_revision_isolation_later_symbol_absent_at_earlier_tag(hist):
    q, repo, shas = hist
    assert q.symbols("v1.0.0", name="app.store.sanitize").items == []
    assert q.symbols("v1.0.0", name="app.extra.bulk").items == []
    [later] = q.symbols("v1.1.0", name="app.store.sanitize").items
    assert_resolves(repo, later.citation, commit=shas["v1.1.0"], contains="def sanitize")
    all_v1 = {i.qualname for i in _all(q.symbols, "v1.0.0")}
    assert "app.service.legacy_check" in all_v1
    assert not {"app.store.sanitize", "app.extra.bulk", "app.extra"} & all_v1


def test_symbols_pagination_is_bounded_and_complete(hist):
    q, _, _ = hist
    first = q.symbols("v1.0.0", limit=2)
    assert len(first.items) <= 2
    assert first.truncated is True and first.next_cursor
    everything = _all(q.symbols, "v1.0.0", limit=2)
    ids = [i.id for i in everything]
    assert len(ids) == len(set(ids))
    assert {i.qualname for i in everything} >= {
        "app.api.handle", "app.service.process", "app.service.legacy_check", "app.store.save"}


def test_unresolved_import_is_external_not_fabricated(hist):
    q, repo, shas = hist
    deps = _all(q.dependencies, "v1.0.0", "app.service", hops=1)
    ext = [d for d in deps if d.target == "requests"]
    assert ext, "unresolved import must still surface"
    for d in ext:
        assert d.external is True
        assert d.target_citation is None
        assert d.kind == "IMPORTS" and d.provenance == "parsed"
        assert_resolves(repo, d.citation, commit=shas["v1.0.0"])
    assert q.symbols("v1.0.0", name="requests").items == []
    internal = [d for d in deps if d.target == "app.store.save"]
    assert internal and all(d.external is False for d in internal)


def test_parsed_vs_inferred_provenance_on_edges(hist):
    q, _, _ = hist
    mod_deps = _all(q.dependencies, "v1.0.0", "app.api", hops=1)
    imports = [d for d in mod_deps if d.kind == "IMPORTS" and d.target == "app.service.process"]
    assert imports and all(d.provenance == "parsed" for d in imports)
    fn_deps = _all(q.dependencies, "v1.0.0", "app.api.handle", hops=1)
    calls = [d for d in fn_deps if d.kind == "CALLS" and d.target == "app.service.process"]
    assert calls and all(d.provenance == "inferred" for d in calls)
    for d in imports + calls:
        assert d.provenance in {"parsed", "inferred"}
        assert re.fullmatch(r"python@\S+", d.extractor)


# ---------------------------------------------------------------- dependencies

def test_multi_hop_cross_file_dependencies(hist):
    q, repo, shas = hist
    one = _all(q.dependencies, "v1.0.0", "app.api.handle", hops=1)
    assert "app.service.process" in {d.target for d in one}
    assert "app.store.save" not in {d.target for d in one}

    two = _all(q.dependencies, "v1.0.0", "app.api.handle", hops=2)
    by_target = {d.target: d for d in two}
    assert by_target["app.service.process"].hops == 1
    save = by_target["app.store.save"]
    assert save.hops == 2
    assert save.source == "app.service.process"
    assert save.external is False
    assert_resolves(repo, save.citation, commit=shas["v1.0.0"], contains="def process")
    assert save.citation.path == "app/service.py"
    assert save.target_citation.path == "app/store.py"
    assert (save.target_citation.start_line, save.target_citation.end_line) == (1, 2)
    assert_resolves(repo, save.target_citation, commit=shas["v1.0.0"], contains="def save")


def test_dependencies_resolve_at_requested_revision(hist):
    q, repo, shas = hist
    v11 = _all(q.dependencies, "v1.1.0", "app.api.handle", hops=3)
    by_target = {d.target: d for d in v11}
    assert by_target["app.store.sanitize"].hops == 3
    tc = by_target["app.store.save"].target_citation
    assert (tc.start_line, tc.end_line) == (5, 6)
    assert_resolves(repo, tc, commit=shas["v1.1.0"], contains="def save")
    v10 = _all(q.dependencies, "v1.0.0", "app.api.handle", hops=3)
    assert "app.store.sanitize" not in {d.target for d in v10}
    v12 = _all(q.dependencies, "v1.2.0", "app.api.handle", hops=3)
    assert "app.store.sanitize" not in {d.target for d in v12}


def test_dependents_identify_affected_components(hist):
    q, repo, shas = hist
    deps = _all(q.dependents, "v1.1.0", "app.store.save", hops=2)
    by_source = {d.source: d for d in deps}
    assert by_source["app.service.process"].hops == 1
    assert by_source["app.extra.bulk"].hops == 1
    assert by_source["app.api.handle"].hops == 2
    assert_resolves(repo, by_source["app.extra.bulk"].citation, commit=shas["v1.1.0"], contains="def bulk")
    assert_resolves(repo, by_source["app.api.handle"].citation, commit=shas["v1.1.0"], contains="def handle")
    one = {d.source for d in _all(q.dependents, "v1.1.0", "app.store.save", hops=1)}
    assert "app.api.handle" not in one
    # app/extra.py is deleted in v1.2.0: not a dependent there
    v12 = {d.source for d in _all(q.dependents, "v1.2.0", "app.store.save", hops=2)}
    assert "app.extra.bulk" not in v12
    assert {"app.service.process", "app.api.handle"} <= v12


def test_dependents_of_function_only_present_later(hist):
    q, _, _ = hist
    deps = _all(q.dependents, "v1.1.0", "app.store.sanitize", hops=1)
    assert "app.store.save" in {d.source for d in deps}


# ---------------------------------------------------------------- changes / releases

def test_changes_between_releases(hist):
    q, repo, shas = hist
    items = _all(q.changes_between, "v1.0.0", "v1.1.0")
    by_path = {i.path: i for i in items}
    assert by_path["app/extra.py"].status == "A"
    assert "app.extra.bulk" in by_path["app/extra.py"].symbols_added
    store = by_path["app/store.py"]
    assert store.status == "M"
    assert "app.store.sanitize" in store.symbols_added
    assert "app.store.save" in store.symbols_modified
    service = by_path["app/service.py"]
    assert service.status == "M"
    assert "app.service.legacy_check" in service.symbols_removed
    assert "app.service.process" not in service.symbols_modified
    assert "app/api.py" not in by_path
    assert by_path["CHANGELOG.md"].status == "M"
    assert_resolves(repo, store.citation, commit=shas["v1.1.0"], contains="def sanitize")


def test_changes_between_reports_deletion_cited_at_old_revision(hist):
    q, repo, shas = hist
    by_path = {i.path: i for i in _all(q.changes_between, "v1.1.0", "v1.2.0")}
    extra = by_path["app/extra.py"]
    assert extra.status == "D"
    assert "app.extra.bulk" in extra.symbols_removed
    assert_resolves(repo, extra.citation, commit=shas["v1.1.0"], contains="def bulk")
    assert "app.store.sanitize" in by_path["app/store.py"].symbols_removed


def test_release_notes_text_with_citation(hist):
    q, repo, shas = hist
    page = q.release_notes("v1.1.0")
    assert _gaps(page) == []
    notes = [n for n in page.items if n.path == "CHANGELOG.md"]
    assert notes
    note = notes[0]
    assert "add sanitize to store.save (fixes #12)" in note.text
    assert "1.2.0" not in note.text
    span = assert_resolves(repo, note.citation, commit=shas["v1.1.0"], contains="fixes #12")
    assert note.text.strip() in span or span.strip() in note.text


def test_release_notes_for_later_release(hist):
    q, repo, shas = hist
    note = [n for n in q.release_notes("v1.2.0").items if n.path == "CHANGELOG.md"][0]
    assert "drop sanitize" in note.text
    assert_resolves(repo, note.citation, commit=shas["v1.2.0"], contains="drop sanitize")


# ---------------------------------------------------------------- fix appeared / disappeared

def test_symbol_history_appears_then_disappears(hist):
    q, repo, shas = hist
    hist_entries = q.symbol_history("app.store.sanitize", ["v1.0.0", "v1.1.0", "v1.2.0"])
    assert [e.rev for e in hist_entries] == ["v1.0.0", "v1.1.0", "v1.2.0"]
    assert [e.present for e in hist_entries] == [False, True, False]
    assert [e.commit for e in hist_entries] == [shas["v1.0.0"], shas["v1.1.0"], shas["v1.2.0"]]
    absent0, present, absent2 = hist_entries
    assert absent0.citation is None and absent2.citation is None
    assert (present.citation.start_line, present.citation.end_line) == (1, 2)
    assert present.content_hash == present.citation.content_hash
    assert_resolves(repo, present.citation, commit=shas["v1.1.0"], contains="def sanitize")


def test_symbol_history_tracks_content_changes(hist):
    q, repo, shas = hist
    entries = q.symbol_history("app.store.save", ["v1.0.0", "v1.1.0", "v1.2.0"])
    assert all(e.present for e in entries)
    h0, h1, h2 = (e.content_hash for e in entries)
    assert h0 != h1 and h0 == h2  # v1.2.0 restores the v1.0.0 file bytes
    for e in entries:
        assert_resolves(repo, e.citation, commit=e.commit, contains="def save")


# ---------------------------------------------------------------- unknown revisions

@pytest.mark.parametrize("method,args", [
    ("symbols", ("v9.9.9",)),
    ("dependencies", ("v9.9.9", "app.api.handle")),
    ("dependents", ("v9.9.9", "app.store.save")),
    ("release_notes", ("v9.9.9",)),
    ("changes_between", ("v1.0.0", "v9.9.9")),
])
def test_unknown_revision_is_a_gap_not_empty_success(hist, method, args):
    q, _, _ = hist
    page = getattr(q, method)(*args)
    assert page.items == []
    gaps = _gaps(page)
    assert any(g.kind == "UNKNOWN_REVISION" and "v9.9.9" in g.detail for g in gaps)


def test_symbol_history_unknown_revision_gap(hist):
    q, _, shas = hist
    known, unknown = q.symbol_history("app.store.save", ["v1.0.0", "v9.9.9"])
    assert known.present is True and known.commit == shas["v1.0.0"]
    assert unknown.present is None and unknown.citation is None
    assert unknown.gap is not None and unknown.gap.kind == "UNKNOWN_REVISION"
