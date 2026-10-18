"""S2/S3 round 2 — findings carry the concrete answer, and cite only the requested revision.

Needs FalkorDB at 127.0.0.1:6379. Round-1 E2 showed high evidence recall but low answer accuracy:
findings named symbols and spans but not the facts (constant values, raised exception names, the
first tag containing a fix, the old->new path of a rename), and some findings cited revisions other
than the requested one. These tests pin the interface below on deterministic synthetic repos:
a test-only `facts` repo built here, plus `make_history_repo` / `make_branchy_repo` (conftest).

Interface assumed (additions to rw.repo.investigate; everything else as in test_s5_access.py):

Finding
  facts: dict           (default {}) — machine-readable answer carried by this finding.
  revision: str | None  (default None) — set ONLY on per-revision history entries; names the
                        revision (tag name as given / examined) whose content the entry describes.
                        Every citation of such an entry is at that revision, and the entry's
                        summary contains the revision name. Findings with revision=None are
                        "headline" findings.
RepoFindings
  facts: dict           (default {}) — the answer: the merged facts of the headline finding(s).
  answer: str | None    — one human-readable sentence/line stating every fact value (the same
                        values also appear in the headline finding's summary).
  to_dict() adds "facts" and "answer" at top level and "facts"/"revision" per finding; the result
  is JSON-serialisable (tuples become lists).

Question shapes and facts (revision = the `revision` argument of investigate()):
  "What is the value of <SYM>?"        (NEW route "constant": ast parse + ast.literal_eval of the
      module-/class-level assignment at the requested revision; source is never executed)
      facts = {"symbol": <qualname>, "value": <python literal>, "expression": <source text of rhs>}
      Non-literal rhs (e.g. `len(NAMES)`): no "value" key, "expression" present, and a
      Gap(kind="non_literal_value"). Unknown name: Gap(kind="unknown_symbol"), facts == {}.
      Citation: the assignment line(s) at the requested revision.
  "What exceptions does <SYM> raise?" / "Which exceptions does <SYM> raise?"   (NEW route "raises")
      facts = {"symbol": <qualname>, "exceptions": sorted unique names from `raise X(...)` /
      `raise X` statements in the function body at the requested revision}
      Citation: the function's span at the requested revision.
  "Is fix <sha> present?"
      facts = {"fix_commit": <full sha>, "state": PRESENT|ABSENT|UNCERTAIN,
               "first_tag_containing": <earliest (by commit time) indexed tag whose commit has the
                                        fix as an ancestor, or None>}
  "When did <SYM> appear?" / "When did <SYM> disappear?"
      facts = {"symbol", "first_present_revision": <tag or requested rev or None>,
               "first_absent_revision": <first examined revision after the first presence at which
                                         it is absent, or None>, "present_at_requested": bool}
      Headline citations (if any) are at the requested revision; per-revision entries are
      labelled with `revision` and cite only that revision.
  "What changed between <A> and <B>?"
      facts = {"from": A, "to": B, "added": [qualnames], "removed": [qualnames],
               "modified": [qualnames], "renamed": [{"old": path, "new": path, "similarity": int}], ...}
      Citations only at A or B.
  "What does <SYM> depend on?" / "What does <SYM> call?"
      facts = {"symbol": <qualname>, "targets": [resolved in-repo target qualnames],
               "external": [unresolved/external target names]}

Revision discipline (all routes): no citation (in findings or RepoFindings.citations) names any
commit other than the resolved sha of the requested revision, except (a) changes questions: A or B
only; (b) history: per-revision entries at their own labelled revision.
"""
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from .conftest import git as _git, write as _write, _load_branchy_builder

# ---------------------------------------------------------------- test-only `facts` repo

CONFIG_V1 = 'TIMEOUT = 30\nNAMES = ("a", "b")\nCOMPUTED = len(NAMES)\n'
CORE_HEAD = ("from pkg.config import TIMEOUT\nfrom pkg.errors import AppError\n\n\n"
             "def check(x):\n"                               # 5
             "    if x is None:\n"                           # 6
             "        raise ValueError(\"x required\")\n"    # 7
             "    if x < 0:\n"                               # 8
             "        raise AppError(\"negative\")\n")       # 9
CORE_FIX = "    if x == 0:\n        raise ZeroDivisionError(\"zero\")\n"
CORE_TAIL = "    return x\n\n\ndef run(x):\n    return check(x) + TIMEOUT\n"
FRESH = "\n\ndef fresh():\n    return run(1)\n"
FIX_LINE = 'raise ZeroDivisionError("zero")'


def _build_facts_repo(repo: Path) -> dict:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")

    def commit(files, msg, date, tag=None, deletions=()):
        for rel, text in files.items():
            _write(repo, rel, text)
        for rel in deletions:
            (repo / rel).unlink()
        _git(repo, "add", "-A", date=date)
        _git(repo, "commit", "-q", "-m", msg, date=date)
        if tag:
            _git(repo, "tag", "-a", tag, "-m", f"release {tag}", date=date)
        return _git(repo, "rev-parse", "HEAD")

    commit({"pkg/__init__.py": "", "pkg/config.py": CONFIG_V1,
            "pkg/errors.py": "class AppError(Exception):\n    pass\n",
            "pkg/core.py": CORE_HEAD + CORE_TAIL, "pkg/old_name.py": "def util():\n    return 1\n"},
           "initial", "2024-07-01T00:00:00+00:00", "v1.0.0")
    commit({"pkg/config.py": CONFIG_V1.replace("30", "60"), "pkg/core.py": CORE_HEAD + CORE_TAIL + FRESH},
           "longer timeout, add fresh", "2024-07-05T00:00:00+00:00", "v1.1.0")
    fix = commit({"pkg/core.py": CORE_HEAD + CORE_FIX + CORE_TAIL + FRESH}, "fix: reject zero",
                 "2024-07-08T00:00:00+00:00")
    commit({"README.md": "# facts\n"}, "docs", "2024-07-09T00:00:00+00:00", "v1.2.0")
    _git(repo, "mv", "pkg/old_name.py", "pkg/new_name.py")
    commit({"pkg/core.py": CORE_HEAD + CORE_FIX + CORE_TAIL}, "rename old_name, drop fresh",
           "2024-07-15T00:00:00+00:00", "v1.3.0")
    shas = {t: _git(repo, "rev-parse", f"{t}^{{commit}}") for t in ("v1.0.0", "v1.1.0", "v1.2.0", "v1.3.0")}
    return {"path": repo, "fix": fix, "shas": shas}


def _index(tmp: Path, name: str, repo: Path, **extra):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    cfg_dir = tmp / "repos"
    cfg_dir.mkdir(exist_ok=True)
    body = {"name": name, "path": str(repo), "tag_pattern": r"^v\d+\.\d+\.\d+$", "languages": ["python"]}
    body.update(extra)
    cfg_path = cfg_dir / f"{name}.json"
    cfg_path.write_text(json.dumps(body), encoding="utf-8")
    graph = f"rw_test_repo_{uuid.uuid4().hex[:12]}"
    cfg = load_config(cfg_path)
    report = index_repository(cfg, graph_name=graph)
    assert report.status == "COMPLETE"
    return cfg_path, graph


def _drop(graph):
    try:
        from rw import graph as G
        G.connect().select_graph(graph).delete()
    except Exception:
        pass


@pytest.fixture(scope="module")
def facts(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("r2facts")
    info = _build_facts_repo(tmp / "facts")
    cfg, graph = _index(tmp, "facts", info["path"])
    yield {**info, "name": "facts", "config": cfg, "graph": graph}
    _drop(graph)


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    from .conftest import HISTORY_V1, HISTORY_V11_CHANGES, HISTORY_V12_CHANGES
    tmp = tmp_path_factory.mktemp("r2hist")
    repo = tmp / "hist"
    repo.mkdir()
    _git(repo, "init", "-q")
    for files, dels, tag, date in ((HISTORY_V1, [], "v1.0.0", "2024-02-01T00:00:00+00:00"),
                                   (HISTORY_V11_CHANGES, [], "v1.1.0", "2024-02-02T00:00:00+00:00"),
                                   (HISTORY_V12_CHANGES, ["app/extra.py"], "v1.2.0", "2024-02-03T00:00:00+00:00")):
        for rel, text in files.items():
            _write(repo, rel, text)
        for rel in dels:
            (repo / rel).unlink()
        _git(repo, "add", "-A", date=date)
        _git(repo, "commit", "-q", "-m", tag, date=date)
        _git(repo, "tag", "-a", tag, "-m", tag, date=date)
    cfg, graph = _index(tmp, "hist", repo)
    shas = {t: _git(repo, "rev-parse", f"{t}^{{commit}}") for t in ("v1.0.0", "v1.1.0", "v1.2.0")}
    yield {"path": repo, "name": "hist", "config": cfg, "graph": graph, "shas": shas}
    _drop(graph)


@pytest.fixture(scope="module")
def branchy(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("r2branchy")
    info = _load_branchy_builder().build(tmp / "branchy")
    cfg, graph = _index(tmp, "branchy", info["path"],
                        revisions=["main", "release-1.x", "release-legacy", "feature/report"])
    shas = {t: _git(info["path"], "rev-parse", f"{t}^{{commit}}")
            for t in ("v1.0.0", "v1.0.1", "v1.0.2", "v1.1.0", "v2.0.0", "v2.1.0", "v2.2.0")}
    yield {**info, "name": "branchy", "config": cfg, "graph": graph, "shas": shas}
    _drop(graph)


# ---------------------------------------------------------------- helpers

def ask(env, rev, question):
    from rw.repo.investigate import investigate
    return investigate(env["name"], rev, question, graph_name=env["graph"], config=env["config"])


def _show(repo, commit, path) -> str:
    return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"],
                          capture_output=True, check=True).stdout.decode("utf-8")


def _span(repo, c) -> str:
    lines = _show(repo, c.commit, c.path).splitlines()
    assert c.start_line is not None and 1 <= c.start_line <= c.end_line <= max(len(lines), 1), c
    return "\n".join(lines[c.start_line - 1:c.end_line])


def headline(res):
    return [f for f in res.findings if getattr(f, "revision", None) is None]


def entries(res):
    return [f for f in res.findings if getattr(f, "revision", None) is not None]


def check_discipline(res, env, allowed: set[str], *, history: bool = False):
    """No citation to any commit outside `allowed`, except labelled history entries at their own rev."""
    assert res.unresolved in (None, ""), res.unresolved
    assert res.findings, "expected findings"
    labelled = set()
    for f in res.findings:
        rev = getattr(f, "revision", None)
        if rev is None:
            for c in f.citations:
                assert c.repo == env["name"]
                assert c.commit in allowed, (f.kind, f.summary, c, allowed)
        else:
            assert history, f"only history entries may carry a revision label: {f}"
            want = env["shas"].get(rev) or _git(env["path"], "rev-parse", f"{rev}^{{commit}}")
            assert rev in f.summary, f"entry summary must name its revision {rev!r}: {f.summary!r}"
            for c in f.citations:
                assert c.commit == want, (rev, c)
                labelled.add(c.commit)
    for c in res.citations:
        assert c.commit in allowed | labelled, (c, allowed)


def facts_of(res) -> dict:
    assert isinstance(getattr(res, "facts", None), dict), "RepoFindings.facts must be a dict"
    return res.facts


def assert_stated(res, *values):
    """Each fact value is written in the answer text and in a headline finding's summary."""
    answer = getattr(res, "answer", None)
    assert isinstance(answer, str) and answer, "RepoFindings.answer must be a non-empty string"
    text = " ".join(f.summary for f in headline(res))
    for v in values:
        assert str(v) in answer, (v, answer)
        assert str(v) in text, (v, text)


def assert_json(res):
    d = res.to_dict()
    json.dumps(d)
    assert "facts" in d and "answer" in d
    for f in d["findings"]:
        assert "facts" in f and "revision" in f


# ---------------------------------------------------------------- (a)+(b)+(c) constants

def test_constant_value_at_requested_revision(facts):
    sha = facts["shas"]["v1.0.0"]
    res = ask(facts, "v1.0.0", "What is the value of TIMEOUT?")
    check_discipline(res, facts, {sha})
    fx = facts_of(res)
    assert fx["value"] == 30 and fx["symbol"].endswith("TIMEOUT")
    cit = headline(res)[0].citations[0]
    assert cit.path == "pkg/config.py" and "TIMEOUT = 30" in _span(facts["path"], cit)
    assert headline(res)[0].facts.get("value") == 30
    assert_stated(res, 30)
    assert_json(res)


def test_constant_cites_requested_revision_not_where_it_last_changed(facts):
    # TIMEOUT last changed in v1.1.0; asked at v1.3.0 the citation must be at v1.3.0
    sha = facts["shas"]["v1.3.0"]
    res = ask(facts, "v1.3.0", "What is the value of pkg.config.TIMEOUT?")
    check_discipline(res, facts, {sha})
    assert facts_of(res)["value"] == 60
    assert all(c.commit == sha for c in res.citations)
    assert "TIMEOUT = 60" in _span(facts["path"], res.citations[0])
    assert_stated(res, 60)


def test_constant_tuple_literal(facts):
    res = ask(facts, "v1.0.0", "What is the value of NAMES?")
    check_discipline(res, facts, {facts["shas"]["v1.0.0"]})
    assert list(facts_of(res)["value"]) == ["a", "b"]
    assert_stated(res, "a", "b")
    assert_json(res)


def test_constant_non_literal_is_not_evaluated(facts):
    res = ask(facts, "v1.0.0", "What is the value of COMPUTED?")
    fx = facts_of(res)
    assert "value" not in fx
    assert fx.get("expression") == "len(NAMES)"
    assert any(g.kind == "non_literal_value" for g in res.gaps)
    for c in res.citations:
        assert c.commit == facts["shas"]["v1.0.0"]


def test_constant_unknown_is_a_gap(facts):
    res = ask(facts, "v1.0.0", "What is the value of NO_SUCH_CONST?")
    assert facts_of(res) == {}
    assert res.findings == [] and res.citations == []
    assert any(g.kind == "unknown_symbol" for g in res.gaps)


# ---------------------------------------------------------------- raises

def test_raised_exceptions_before_fix(facts):
    sha = facts["shas"]["v1.0.0"]
    res = ask(facts, "v1.0.0", "What exceptions does pkg.core.check raise?")
    check_discipline(res, facts, {sha})
    fx = facts_of(res)
    assert fx["symbol"] == "pkg.core.check"
    assert fx["exceptions"] == ["AppError", "ValueError"]
    assert "def check" in _span(facts["path"], headline(res)[0].citations[0])
    assert_stated(res, "AppError", "ValueError")


def test_raised_exceptions_after_fix(facts):
    sha = facts["shas"]["v1.3.0"]
    res = ask(facts, "v1.3.0", "Which exceptions does check raise?")
    check_discipline(res, facts, {sha})
    assert facts_of(res)["exceptions"] == ["AppError", "ValueError", "ZeroDivisionError"]
    assert FIX_LINE in _span(facts["path"], headline(res)[0].citations[0])
    assert_stated(res, "ZeroDivisionError")
    assert_json(res)


# ---------------------------------------------------------------- fix: state + first tag

def test_fix_present_reports_first_tag_containing(facts):
    sha = facts["shas"]["v1.3.0"]
    res = ask(facts, "v1.3.0", f"Is fix {facts['fix'][:10]} present?")
    check_discipline(res, facts, {sha})
    fx = facts_of(res)
    assert fx["state"] == "PRESENT"
    assert fx["fix_commit"] == facts["fix"]
    assert fx["first_tag_containing"] == "v1.2.0"   # the fix commit itself is untagged
    assert any(FIX_LINE in _span(facts["path"], c) for c in res.citations)
    assert_stated(res, "PRESENT", "v1.2.0")
    assert_json(res)


def test_fix_absent_before_it_landed_still_names_first_tag(facts):
    sha = facts["shas"]["v1.1.0"]
    res = ask(facts, "v1.1.0", f"Is fix {facts['fix']} present?")
    check_discipline(res, facts, {sha})
    fx = facts_of(res)
    assert fx["state"] == "ABSENT"
    assert fx["first_tag_containing"] == "v1.2.0"
    assert_stated(res, "ABSENT", "v1.2.0")


def test_fix_absent_after_revert_branchy(branchy):
    sha = branchy["shas"]["v2.0.0"]
    res = ask(branchy, "v2.0.0", f"Is fix {branchy['fix']} present?")
    check_discipline(res, branchy, {sha})
    fx = facts_of(res)
    assert fx["state"] == "ABSENT"
    assert fx["first_tag_containing"] == "v1.1.0"
    assert_stated(res, "ABSENT", "v1.1.0")


def test_fix_reapplied_branchy_cites_only_requested(branchy):
    sha = branchy["shas"]["v2.1.0"]
    res = ask(branchy, "v2.1.0", f"Is fix {branchy['fix'][:12]} present?")
    check_discipline(res, branchy, {sha})
    assert facts_of(res)["state"] == "PRESENT"
    assert facts_of(res)["first_tag_containing"] == "v1.1.0"


# ---------------------------------------------------------------- history

def test_history_appear_and_disappear_tags(facts):
    sha = facts["shas"]["v1.3.0"]
    for q in ("When did pkg.core.fresh appear?", "When did pkg.core.fresh disappear?"):
        res = ask(facts, "v1.3.0", q)
        check_discipline(res, facts, {sha}, history=True)
        fx = facts_of(res)
        assert fx["first_present_revision"] == "v1.1.0", q
        assert fx["first_absent_revision"] == "v1.3.0", q
        assert fx["present_at_requested"] is False
        assert_stated(res, "v1.1.0", "v1.3.0")
        # per-revision entries exist and are labelled; intermediate tags only appear there
        labels = {f.revision for f in entries(res)}
        assert "v1.1.0" in labels
        for f in headline(res):
            assert all(c.commit == sha for c in f.citations)
        assert_json(res)


def test_history_still_present_symbol(facts):
    sha = facts["shas"]["v1.3.0"]
    res = ask(facts, "v1.3.0", "When did pkg.core.check appear?")
    check_discipline(res, facts, {sha}, history=True)
    fx = facts_of(res)
    assert fx["first_present_revision"] == "v1.0.0"
    assert fx["first_absent_revision"] is None
    assert fx["present_at_requested"] is True
    hl = headline(res)
    assert hl and any(c.commit == sha for f in hl for c in f.citations), \
        "headline citation must be at the requested revision"
    assert "def check" in _span(facts["path"], next(c for f in hl for c in f.citations))
    assert_stated(res, "v1.0.0")


def test_history_sanitize_on_history_repo(hist):
    sha = hist["shas"]["v1.2.0"]
    res = ask(hist, "v1.2.0", "When did app.store.sanitize disappear?")
    check_discipline(res, hist, {sha}, history=True)
    fx = facts_of(res)
    assert fx["first_present_revision"] == "v1.1.0"
    assert fx["first_absent_revision"] == "v1.2.0"
    ent = {f.revision: f for f in entries(res)}
    assert "v1.1.0" in ent and ent["v1.1.0"].citations
    assert "def sanitize" in _span(hist["path"], ent["v1.1.0"].citations[0])
    assert_stated(res, "v1.1.0", "v1.2.0")


# ---------------------------------------------------------------- changes

def test_changes_rename_and_removed_symbols(facts):
    a, b = facts["shas"]["v1.2.0"], facts["shas"]["v1.3.0"]
    res = ask(facts, "v1.3.0", "What changed between v1.2.0 and v1.3.0?")
    check_discipline(res, facts, {a, b})
    fx = facts_of(res)
    assert any(r["old"] == "pkg/old_name.py" and r["new"] == "pkg/new_name.py" for r in fx["renamed"])
    assert "pkg.core.fresh" in fx["removed"]
    assert "pkg.core.fresh" not in fx["added"]
    assert_stated(res, "pkg/old_name.py", "pkg/new_name.py", "pkg.core.fresh")
    assert_json(res)


def test_changes_added_and_modified_symbols(facts):
    a, b = facts["shas"]["v1.0.0"], facts["shas"]["v1.1.0"]
    res = ask(facts, "v1.1.0", "What changed between v1.0.0 and v1.1.0?")
    check_discipline(res, facts, {a, b})
    fx = facts_of(res)
    assert "pkg.core.fresh" in fx["added"]
    assert fx["renamed"] == []
    assert_stated(res, "pkg.core.fresh")

    a, b = facts["shas"]["v1.1.0"], facts["shas"]["v1.2.0"]
    res = ask(facts, "v1.2.0", "What changed between v1.1.0 and v1.2.0?")
    check_discipline(res, facts, {a, b})
    assert "pkg.core.check" in facts_of(res)["modified"]


def test_changes_never_cite_outside_pair_branchy(branchy):
    # asked at v2.2.0 about a pair that excludes it: citations only at v2.1.0 / v2.2.0 here,
    # and for a non-adjacent pair (v1.1.0..v2.2.0) never at the intermediate v2.0.0/v2.1.0
    s = branchy["shas"]
    res = ask(branchy, "v2.2.0", "What changed between v2.1.0 and v2.2.0?")
    check_discipline(res, branchy, {s["v2.1.0"], s["v2.2.0"]})
    assert any(r["old"] == "svc/helpers.py" and r["new"] == "svc/tools.py" for r in facts_of(res)["renamed"])
    assert_stated(res, "svc/helpers.py", "svc/tools.py")
    res = ask(branchy, "v2.2.0", "What changed between v1.1.0 and v2.2.0?")
    check_discipline(res, branchy, {s["v1.1.0"], s["v2.2.0"]})


# ---------------------------------------------------------------- dependencies

def test_dependencies_resolved_targets(facts):
    sha = facts["shas"]["v1.0.0"]
    res = ask(facts, "v1.0.0", "What does pkg.core.run depend on?")
    check_discipline(res, facts, {sha})
    fx = facts_of(res)
    assert fx["symbol"] == "pkg.core.run"
    assert "pkg.core.check" in fx["targets"]
    assert_stated(res, "pkg.core.check")


def test_dependencies_history_repo(hist):
    sha = hist["shas"]["v1.1.0"]
    res = ask(hist, "v1.1.0", "What does app.store.save call?")
    check_discipline(res, hist, {sha})
    assert "app.store.sanitize" in facts_of(res)["targets"]
    assert_stated(res, "app.store.sanitize")


# ---------------------------------------------------------------- discipline sweep

@pytest.mark.parametrize("rev,question", [
    ("v1.0.0", "What does pkg.core.check depend on?"),
    ("v1.3.0", "Where is check defined?"),
    ("v1.3.0", "List symbols"),
    ("v1.1.0", "What is the value of TIMEOUT?"),
    ("v1.2.0", "What exceptions does pkg.core.check raise?"),
])
def test_every_citation_at_requested_revision(facts, rev, question):
    res = ask(facts, rev, question)
    check_discipline(res, facts, {facts["shas"][rev]})
    assert not entries(res)
