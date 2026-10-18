"""Local Git ancestry overlays cannot replace the parents in immutable commit objects."""
import pytest

from rw.repo.config import RepoConfig
from rw.repo.git import GitRepo
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


@pytest.mark.parametrize("overlay", ["hide_all_parents", "skip_middle_commit"])
def test_local_grafts_cannot_rewrite_imported_ancestry(make_repo, git_cmd, graph_name, monkeypatch, overlay):
    repo = make_repo()
    tip = git_cmd(repo, "rev-parse", "HEAD")
    # cat-file reads immutable objects; rev-list/log could themselves honor grafts.
    middle = next(x.split()[1] for x in git_cmd(repo, "cat-file", "-p", tip).splitlines()
                  if x.startswith("parent "))
    root = next(x.split()[1] for x in git_cmd(repo, "cat-file", "-p", middle).splitlines()
                if x.startswith("parent "))
    graft = repo / ".git" / "info" / "grafts"
    graft.write_text(tip + (" " + root if overlay == "skip_middle_commit" else "") + "\n")
    monkeypatch.setenv("GIT_GRAFT_FILE", str(graft))
    git = GitRepo(repo)
    commits = git.commits([tip])
    assert [(c.sha, c.parents) for c in commits] == [(root, []), (middle, [root]), (tip, [middle])]
    assert git.is_ancestor(middle, tip)
    assert [sha for sha, _ in git.first_parent_changes([tip])] == [root, middle, tip]
    cfg = RepoConfig(name="graft-proof", path=repo, revisions=[tip])
    report = index_repository(cfg, graph_name)
    assert report.commits == 3
    q = RepoQuery(graph_name, cfg.name)
    actual = q._q("MATCH (c:Commit)-[e:PARENT]->(p:Commit) RETURN c.sha, p.sha, e.order ORDER BY c.sha")
    assert sorted(map(tuple, actual)) == sorted([(middle, root, 0), (tip, middle, 0)])
    assert q.resolve(middle) == (middle, None)
    assert q.symbols(middle, name="extra").items


def test_retry_replaces_parent_edges_left_by_an_old_grafted_import(make_repo, git_cmd, graph_name):
    repo = make_repo()
    tip = git_cmd(repo, "rev-parse", "HEAD")
    middle = next(x.split()[1] for x in git_cmd(repo, "cat-file", "-p", tip).splitlines()
                  if x.startswith("parent "))
    root = next(x.split()[1] for x in git_cmd(repo, "cat-file", "-p", middle).splitlines()
                if x.startswith("parent "))
    cfg = RepoConfig(name="graft-recovery", path=repo, revisions=[tip])
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    # Reproduce an old COMPLETE import's false parent while leaving files_done set.
    q.graph.query("MATCH (c:Commit {sha:$tip})-[e:PARENT]->() DELETE e", {"tip": tip})
    q.graph.query("MATCH (c:Commit {sha:$tip}), (p:Commit {sha:$root}) CREATE (c)-[:PARENT {order:0}]->(p)",
                  {"tip": tip, "root": root})
    index_repository(cfg, graph_name)
    assert q._q("MATCH (:Commit {sha:$s})-[e:PARENT]->(p:Commit) RETURN p.sha, e.order", {"s": tip}) == [[middle, 0]]
