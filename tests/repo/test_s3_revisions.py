"""S3 — correct revision handling (docs/repo/REQUIREMENTS.md S3; docs/repo/DESIGN.md).

Needs FalkorDB at 127.0.0.1:6379. Uses `make_branchy_repo` (tests/repo/conftest.py, built by
evals/repo_questions/build_branchy_history.py; history documented in that builder's docstring).

Interface assumed (in addition to the S2 interface in tests/repo/test_s2_evidence.py):

rw.repo.index.index_repository(config): `config.revisions` may name several branches
  (e.g. ["main", "release-1.x", "release-legacy", "feature/report"]); every commit reachable from
  them and from tags matching `tag_pattern` is indexed, with
  (Commit)-[:PARENT {order}]->(Commit) for every parent (order 0 = first parent). Branch names
  resolve via RepoQuery.resolve to the full sha of the branch tip.

rw.repo.query.RepoQuery
  is_ancestor(ancestor_rev, rev) -> bool | None
    Answered from the graph's PARENT edges; None when either revision is not indexed.

  fix_status(rev, fix_commit, *, symbol=None) -> FixStatus
    FixStatus (dataclass): state in {"PRESENT", "ABSENT", "UNCERTAIN"}, citations: list[Citation],
      gaps: list[Gap], reason: str.
    The verdict is checked against the CONTENT at `rev`, never inferred from ancestry alone:
    - PRESENT: the lines introduced by `fix_commit` are present at `rev`. Citations are at `rev`
      (Citation.commit == full sha of rev) and their span contains the fix's added lines.
      If `fix_commit` is not an ancestor of `rev` but a commit reachable from `rev` has the same
      patch (git patch-id equality, e.g. a cherry-pick), state is PRESENT and gaps contain a
      Gap(kind="EQUIVALENT_BY_PATCH") whose detail names that commit's full sha.
    - ABSENT: the fix's lines are not at `rev` and nothing similar is (e.g. after a revert, even
      though fix_commit is an ancestor; or before the fix). At least one citation is at `rev` and
      points at the current text of the file the fix touched.
    - UNCERTAIN: the fix's identity at `rev` cannot be established. Gap kinds:
      "BACKPORT_EQUIVALENCE_UNKNOWN" — not an ancestor, no patch-id match, but the touched
        symbol/file changed in a similar but non-identical way (modified backport);
      "CHANGE_IDENTITY_UNKNOWN" — fix_commit is an ancestor but its lines were later modified;
      "UNKNOWN_REVISION" — fix_commit (or rev) is not indexed / does not exist.
  changes_between(rev_a, rev_b): renames are detected by similarity (as `git diff -M`), not only
    identical content: a renamed-and-edited file yields one ChangeItem(status="R",
    old_path=<old>, path=<new>) and no separate A/D items for those paths.
  Identity: symbols/citations never mix repositories: Citation.repo and SymbolItem.id prefix are the
    queried repo's name even when another repo has byte-identical files.
"""
import hashlib
import re
import subprocess
import uuid

import pytest

REVS = ["main", "release-1.x", "release-legacy", "feature/report"]


# ---------------------------------------------------------------- helpers

def _rev_parse(repo, rev):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _show(repo, commit, path) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"],
                          capture_output=True, check=True).stdout


def assert_resolves(repo, cit, *, commit, contains=None, repo_name="branchy"):
    assert cit is not None
    assert cit.repo == repo_name
    assert re.fullmatch(r"[0-9a-f]{40}", cit.commit)
    assert cit.commit == commit, "citation must name the requested revision, not an ancestor"
    data = _show(repo, cit.commit, cit.path)
    if cit.content_hash is not None:
        assert hashlib.sha256(data).hexdigest() == cit.content_hash
    lines = data.decode("utf-8").splitlines()
    assert 1 <= cit.start_line <= cit.end_line <= max(len(lines), 1)
    span = "\n".join(lines[cit.start_line - 1:cit.end_line])
    if contains is not None:
        assert contains in span, f"{contains!r} not in {cit.path}:{cit.start_line}-{cit.end_line}"
    return span


def _gaps(page):
    gaps = page.coverage.get("gaps")
    assert isinstance(gaps, list)
    return gaps


def _index(make_branchy_repo, write_config, graph_name, name="branchy"):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    from rw.repo.query import RepoQuery

    info = make_branchy_repo(name)
    cfg = load_config(write_config(name, info["path"], revisions=list(REVS)))
    report = index_repository(cfg, graph_name=graph_name)
    assert report.status == "COMPLETE"
    return RepoQuery(graph_name, name), info


@pytest.fixture
def br(make_branchy_repo, write_config, graph_name):
    q, info = _index(make_branchy_repo, write_config, graph_name)
    repo = info["path"]
    shas = {t: _rev_parse(repo, t) for t in
            ("v1.0.0", "v1.0.1", "v1.0.2", "v1.1.0", "v2.0.0", "v2.1.0", "v2.2.0")}
    return q, repo, info, shas


FIX_LINE = 'raise ValueError("negative amount")'


# ---------------------------------------------------------------- ancestry / branches / merges

def test_merge_commit_has_two_ordered_parents(br):
    q, repo, info, _ = br
    rows = q.graph.ro_query("MATCH (:Commit {sha:$m})-[e:PARENT]->(p:Commit) RETURN e.order, p.sha "
                            "ORDER BY e.order", {"m": info["merge"]}).result_set
    assert [(r[0], r[1]) for r in rows] == [(0, info["readme"]), (1, info["feature_tip"])]


def test_all_branch_tips_indexed_and_resolve(br):
    q, repo, info, _ = br
    for branch in REVS:
        sha, gap = q.resolve(branch)
        assert gap is None, branch
        assert sha == _rev_parse(repo, branch)
    # commits that exist only on side branches are indexed too
    for sha in (info["pick"], info["legacy_backport"], info["feature_tip"]):
        assert q.resolve(sha)[0] == sha


def test_parent_edges_match_git_for_every_commit(br):
    q, repo, _, _ = br
    out = subprocess.run(["git", "-C", str(repo), "rev-list", "--parents", *REVS],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    for line in filter(None, out):
        c, *parents = line.split()
        rows = q.graph.ro_query("MATCH (:Commit {sha:$c})-[e:PARENT]->(p:Commit) RETURN e.order, p.sha "
                                "ORDER BY e.order", {"c": c}).result_set
        assert [r[1] for r in rows] == parents
        assert [r[0] for r in rows] == list(range(len(parents)))


def test_is_ancestor_across_branches(br):
    q, _, info, s = br
    assert q.is_ancestor(info["fix"], "v2.0.0") is True
    assert q.is_ancestor(info["feature_tip"], "v1.1.0") is True     # via merge second parent
    assert q.is_ancestor(info["fix"], "v1.0.1") is False            # cherry-pick, not ancestry
    assert q.is_ancestor(info["fix"], "v1.0.2") is False
    assert q.is_ancestor("v1.0.0", "release-legacy") is True
    assert q.is_ancestor("v1.0.1", "main") is False
    assert q.is_ancestor("0" * 40, "main") is None


# ---------------------------------------------------------------- fix status at a revision

def test_fix_present_at_merge_release(br):
    q, repo, info, s = br
    st = q.fix_status("v1.1.0", info["fix"])
    assert st.state == "PRESENT"
    assert st.citations
    for c in st.citations:
        assert c.commit == s["v1.1.0"]
    assert any(FIX_LINE in assert_resolves(repo, c, commit=s["v1.1.0"]) for c in st.citations)


def test_fix_absent_after_revert_although_ancestor(br):
    q, repo, info, s = br
    assert q.is_ancestor(info["fix"], "v2.0.0") is True
    st = q.fix_status("v2.0.0", info["fix"])
    assert st.state == "ABSENT"
    at_rev = [c for c in st.citations if c.commit == s["v2.0.0"]]
    assert at_rev, "ABSENT must cite the current text at the requested revision"
    assert any(c.path == "svc/validate.py" for c in at_rev)
    for c in at_rev:
        assert FIX_LINE not in assert_resolves(repo, c, commit=s["v2.0.0"])


def test_fix_absent_before_it_was_made(br):
    q, _, info, _ = br
    assert q.fix_status("v1.0.0", info["fix"]).state == "ABSENT"


def test_fix_present_again_after_reapply(br):
    q, repo, info, s = br
    st = q.fix_status("v2.1.0", info["fix"])
    assert st.state == "PRESENT"
    assert any(FIX_LINE in assert_resolves(repo, c, commit=s["v2.1.0"]) for c in st.citations)


def test_fix_later_modified_is_not_present(br):
    q, _, info, _ = br
    st = q.fix_status("v2.2.0", info["fix"])
    assert st.state in ("UNCERTAIN", "ABSENT")
    assert st.state != "PRESENT"
    if st.state == "UNCERTAIN":
        assert any(g.kind == "CHANGE_IDENTITY_UNKNOWN" for g in st.gaps)


def test_identical_cherry_pick_is_present_by_patch_equivalence(br):
    q, repo, info, s = br
    st = q.fix_status("v1.0.1", info["fix"])
    assert st.state == "PRESENT"
    eq = [g for g in st.gaps if g.kind == "EQUIVALENT_BY_PATCH"]
    assert eq and info["pick"] in eq[0].detail
    assert any(FIX_LINE in assert_resolves(repo, c, commit=s["v1.0.1"]) for c in st.citations)


def test_modified_backport_is_uncertain(br):
    q, _, info, s = br
    st = q.fix_status("v1.0.2", info["fix"])
    assert st.state == "UNCERTAIN"
    assert any(g.kind == "BACKPORT_EQUIVALENCE_UNKNOWN" for g in st.gaps)
    assert all(c.commit == s["v1.0.2"] for c in st.citations)


def test_unknown_fix_commit_reports_gap(br):
    q, _, _, _ = br
    st = q.fix_status("v2.1.0", "f" * 40)
    assert st.state == "UNCERTAIN"
    assert any(g.kind in ("UNKNOWN_REVISION", "CHANGE_IDENTITY_UNKNOWN") for g in st.gaps)


def test_unknown_rev_reports_gap(br):
    q, _, info, _ = br
    st = q.fix_status("v9.9.9", info["fix"])
    assert st.state == "UNCERTAIN"
    assert any(g.kind == "UNKNOWN_REVISION" for g in st.gaps)
    assert st.citations == []


def test_fix_status_by_branch_name_cites_branch_tip(br):
    q, repo, info, _ = br
    tip = _rev_parse(repo, "release-1.x")
    st = q.fix_status("release-1.x", info["fix"], symbol="svc.validate.parse_amount")
    assert st.state == "PRESENT"
    for c in st.citations:
        assert_resolves(repo, c, commit=tip)


# ---------------------------------------------------------------- renames / deletions

def test_rename_with_edits_is_detected(br):
    q, repo, _, s = br
    page = q.changes_between("v2.1.0", "v2.2.0")
    assert _gaps(page) == []
    by_path = {i.path: i for i in page.items}
    assert "svc/tools.py" in by_path
    r = by_path["svc/tools.py"]
    assert r.status == "R" and r.old_path == "svc/helpers.py"
    assert "svc/helpers.py" not in by_path, "rename must not also appear as a deletion"
    assert_resolves(repo, r.citation, commit=s["v2.2.0"])
    d = by_path["svc/legacy.py"]
    assert d.status == "D"
    assert d.citation.commit == s["v2.1.0"]


def test_renamed_symbols_cite_path_of_their_revision(br):
    q, repo, _, s = br
    [old] = q.symbols("v2.1.0", name="slugify").items
    assert old.path == "svc/helpers.py" and old.qualname == "svc.helpers.slugify"
    assert_resolves(repo, old.citation, commit=s["v2.1.0"], contains="def slugify")
    [new] = q.symbols("v2.2.0", name="slugify").items
    assert new.path == "svc/tools.py" and new.qualname == "svc.tools.slugify"
    assert_resolves(repo, new.citation, commit=s["v2.2.0"], contains="def slugify")
    assert q.symbols("v2.2.0", name="svc.helpers.slugify").items == []


def test_deleted_file_symbols_disappear(br):
    q, _, _, s = br
    hist = q.symbol_history("svc.legacy.old_api", ["v1.0.0", "v2.1.0", "v2.2.0"])
    assert [h.present for h in hist] == [True, True, False]
    assert hist[2].commit == s["v2.2.0"] and hist[2].citation is None
    assert q.symbols("v2.2.0", name="old_api").items == []


def test_feature_branch_file_absent_before_merge(br):
    q, repo, info, s = br
    assert q.symbols("v1.0.0", name="summarize").items == []
    [it] = q.symbols("v1.1.0", name="summarize").items
    assert_resolves(repo, it.citation, commit=s["v1.1.0"], contains="def summarize")
    [tip] = q.symbols(info["feature_tip"], name="summarize").items
    assert tip.citation.commit == info["feature_tip"]


# ---------------------------------------------------------------- cross-repository identity

def test_two_repos_with_identical_files_do_not_share_identity(br, make_branchy_repo, write_config):
    q1, repo1, _, s1 = br
    other_graph = f"rw_test_repo_{uuid.uuid4().hex[:12]}"
    try:
        q2, info2 = _index(make_branchy_repo, write_config, other_graph, name="branchy-two")
        repo2 = info2["path"]
        a = q1.symbols("v2.1.0", name="svc.validate.parse_amount").items[0]
        b = q2.symbols("v2.1.0", name="svc.validate.parse_amount").items[0]
        assert a.citation.content_hash == b.citation.content_hash   # byte-identical file
        assert a.id != b.id
        assert a.id.startswith("branchy:") and b.id.startswith("branchy-two:")
        assert a.citation.repo == "branchy" and b.citation.repo == "branchy-two"
        assert_resolves(repo2, b.citation, commit=_rev_parse(repo2, "v2.1.0"), repo_name="branchy-two")
        # repo 1's graph knows nothing of repo 2's symbols
        assert q1.graph.ro_query("MATCH (s:Symbol) WHERE s.id STARTS WITH 'branchy-two:' "
                                 "RETURN count(s)").result_set[0][0] == 0
        st = q2.fix_status("v2.0.0", info2["fix"])
        assert all(c.repo == "branchy-two" for c in st.citations)
    finally:
        try:
            from rw import graph as G
            G.connect().select_graph(other_graph).delete()
        except Exception:
            pass


def test_fix_status_citations_always_full_sha_of_requested_rev(br):
    q, repo, info, s = br
    for tag in ("v1.0.0", "v1.0.1", "v1.0.2", "v1.1.0", "v2.0.0", "v2.1.0", "v2.2.0"):
        st = q.fix_status(tag, info["fix"])
        assert st.state in ("PRESENT", "ABSENT", "UNCERTAIN")
        assert isinstance(st.reason, str) and st.reason
        for c in st.citations:
            assert_resolves(repo, c, commit=s[tag])
