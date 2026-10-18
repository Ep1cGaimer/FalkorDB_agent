"""Exact corpus path rules must not admit extra basename-matching evidence."""
from rw.repo.config import RepoConfig
from rw.repo.git import GitRepo
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery


def test_path_profile_does_not_match_nested_root_metadata(make_repo, graph_name):
    repo = make_repo(files={"setup.py": "ROOT = True\n", "nested/setup.py": "SECRET_EXTRA = True\n",
                            "pkg/keep.py": "def keep():\n    return 1\n"})
    cfg = RepoConfig(name="exact-paths", path=repo, revisions=["v1.0.0"],
                     include=["setup.py", "pkg/*.py"], path_matching="path")
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    sha = GitRepo(repo).resolve("v1.0.0")
    assert set(q._files(sha)) == {"setup.py", "pkg/keep.py"}


def test_default_basename_profile_remains_explicit_and_reconfigurable(make_repo, graph_name):
    repo = make_repo(files={"setup.py": "ROOT = True\n", "nested/setup.py": "EXTRA = True\n"})
    cfg = RepoConfig(name="path-migration", path=repo, revisions=["v1.0.0"], include=["setup.py"])
    index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    sha = GitRepo(repo).resolve("v1.0.0")
    assert set(q._files(sha)) == {"setup.py", "nested/setup.py"}
    strict = cfg.model_copy(update={"path_matching": "path"})
    index_repository(strict, graph_name)
    # Public resolution refreshes a long-lived query object's generation caches.
    assert q.resolve(sha) == (sha, None)
    assert set(q._files(sha)) == {"setup.py"}


def test_regular_file_profile_labels_symlink_exclusion_without_following_it(make_repo, git_cmd, graph_name):
    repo = make_repo(files={"pkg/keep.py": "def keep():\n    return 1\n"})
    (repo / "pkg/link.py").symlink_to("/outside/source.py")
    git_cmd(repo, "add", ".")
    git_cmd(repo, "commit", "-qm", "add symlink metadata")
    cfg = RepoConfig(name="regular-source", path=repo, revisions=["HEAD"], include=["pkg/*.py"],
                     path_matching="path", regular_files_only=True)
    report = index_repository(cfg, graph_name)
    q = RepoQuery(graph_name, cfg.name)
    assert "pkg/link.py" not in q._files(GitRepo(repo).resolve("HEAD"))
    assert any(g.kind == "UNSUPPORTED_FILE_KIND" and "pkg/link.py" in g.detail for g in report.coverage_gaps)
