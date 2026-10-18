"""S1 — configurable repository integration (docs/plans/repo-integration-v1.md).

Graph tests need FalkorDB at 127.0.0.1:6379 and use unique graph names that are deleted afterwards.

Interface assumed (where the design contract is silent, the simplest reasonable choice):

rw.repo.config
  RepoConfig (pydantic BaseModel): name: str matching ^[a-z0-9][a-z0-9-]{0,63}$ (else ValidationError,
    a ValueError subclass), path: str|Path, revisions: list[str] = [], tag_pattern: str|None = None,
    languages: list[str] = ["python"], include: list[str] = [], exclude: list[str] = [],
    release_notes: list[str] = default globs including "CHANGELOG*".
  load_config(name_or_path: str|Path) -> RepoConfig  (a path to a .json file, str or Path, is accepted).

rw.repo.git
  GitRepo(path)  — read-only; methods:
    resolve(rev: str) -> str (40-hex commit sha; annotated tags are peeled to the commit)
    commits(revs: list[str]) -> list[Commit], topological order, parents before children;
        Commit(sha, parents: list[str], author_time: int, subject: str, message: str)
    tags() -> list[Tag]; Tag(name, target_sha (peeled commit sha), message)
    tree(sha) -> list[tuple[path: str, blob_sha: str, mode: str]]   (paths use "/")
    blob(sha) -> bytes
    changes(parent, child) -> list[Change(status in "A","M","D","R", old_path, new_path, similarity)]
        (for "A" new_path is set; for "M" new_path == old_path)
    is_ancestor(a, b) -> bool

rw.repo.adapters
  SUPPORTED_LANGUAGES: collection of str containing "python"
  ADAPTERS: dict[language -> adapter instance]
  adapter_for(path: str) -> adapter | None   (None => the file is a coverage gap)
  Adapter attributes: language, extensions, version, LIMITS (non-empty list[str]),
    extract(path: str, data: bytes) -> Extraction(symbols, relations, errors, limits)
rw.repo.adapters.python: PythonAdapter (no-arg constructor) and module-level LIMITS.
rw.repo.model
  Symbol: .qualname (dotted, module prefix from the path, e.g. "pkg.core.Engine.start"),
    .kind in {"module","class","function","method"}, .start_line, .end_line (1-based, inclusive;
    the module symbol's qualname is the module name, e.g. "pkg.core")
  Relation(kind in {"IMPORTS","CALLS","INHERITS"}, source: qualname str, target: name str,
    provenance in {"parsed","inferred"}, extractor="python@<version>")
  Gap(kind, detail) — coverage gaps for unsupported files mention the file path in detail.

rw.repo.index
  index_repository(config, graph_name=None, db=None) -> IndexReport with
    .commits: int, .blobs: int, .coverage_gaps: list[Gap], .import_run_id: str, .status == "COMPLETE"
  Indexes commits reachable from config.revisions plus tags matching config.tag_pattern.
  Graph: Symbol nodes carry .id containing the repo name (identity = repo, blob hash, qualname);
  HAS_FILE edges carry .path; ImportRun{id, status}.
"""
import re
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- config

def test_config_loads_from_json(make_repo, write_config):
    from rw.repo.config import RepoConfig, load_config
    repo = make_repo()
    cfg = load_config(write_config("demo", repo, revisions=["main"]))
    assert isinstance(cfg, RepoConfig)
    assert cfg.name == "demo"
    assert Path(cfg.path) == repo
    assert cfg.revisions == ["main"]
    assert cfg.tag_pattern == r"^v\d+\.\d+\.\d+$"


def test_config_load_accepts_str_path(make_repo, write_config):
    from rw.repo.config import load_config
    path = write_config("demo", make_repo())
    assert load_config(str(path)).name == "demo"


@pytest.mark.parametrize("bad", ["", "Demo", "-demo", "de mo", "de/mo", "x" * 65, "../etc"])
def test_config_rejects_bad_names(bad, tmp_path):
    from rw.repo.config import RepoConfig
    with pytest.raises(ValueError):
        RepoConfig(name=bad, path=str(tmp_path))


def test_config_defaults_and_revision_forms(tmp_path):
    from rw.repo.config import RepoConfig
    only_revs = RepoConfig(name="a1", path=str(tmp_path), revisions=["v1.0.0", "main"])
    assert only_revs.revisions == ["v1.0.0", "main"]
    assert only_revs.languages == ["python"]
    assert any(g.startswith("CHANGELOG") for g in only_revs.release_notes)
    only_tags = RepoConfig(name="a-2", path=str(tmp_path), tag_pattern=r"^v")
    assert only_tags.revisions == [] and only_tags.tag_pattern == r"^v"


def test_config_does_not_need_fixture_layout(make_repo, write_config):
    from rw.repo.config import load_config
    repo = make_repo()
    assert not (repo / "release.json").exists() and not list(repo.rglob("codec.py"))
    load_config(write_config("demo", repo))


# ---------------------------------------------------------------- git (read-only)

def _snapshot(repo: Path, git):
    files = {p.relative_to(repo).as_posix(): p.read_bytes()
             for p in repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(repo).parts}
    return (files, (repo / ".git" / "HEAD").read_bytes(), git(repo, "rev-parse", "HEAD"),
            git(repo, "status", "--porcelain"))


def test_git_resolve_tags_and_commits(make_repo, git_cmd):
    from rw.repo.git import GitRepo
    repo = make_repo()
    g = GitRepo(repo)
    v1, v11 = g.resolve("v1.0.0"), g.resolve("v1.1.0")
    assert v1 == git_cmd(repo, "rev-parse", "v1.0.0^{commit}")
    assert v11 == git_cmd(repo, "rev-parse", "HEAD")
    assert re.fullmatch(r"[0-9a-f]{40}", v1)

    commits = g.commits(["v1.1.0"])
    assert [c.subject for c in commits] == ["initial", "add extra", "change helper"]
    assert commits[0].parents == [] and commits[1].parents == [commits[0].sha]
    assert commits[2].parents == [commits[1].sha]
    assert commits[0].author_time < commits[2].author_time
    seen = set()
    for c in commits:  # topological: parents first
        assert all(p in seen for p in c.parents)
        seen.add(c.sha)

    tags = {t.name: t for t in g.tags()}
    assert set(tags) == {"v1.0.0", "v1.1.0"}
    assert tags["v1.0.0"].target_sha == v1
    assert "release 1.0.0" in tags["v1.0.0"].message
    assert g.is_ancestor(v1, v11) and not g.is_ancestor(v11, v1)


def test_git_tree_blob_changes(make_repo):
    from rw.repo.git import GitRepo
    repo = make_repo()
    g = GitRepo(repo)
    v1, v11 = g.resolve("v1.0.0"), g.resolve("v1.1.0")
    tree1 = {path: (sha, mode) for path, sha, mode in g.tree(v1)}
    assert {"pkg/core.py", "pkg/util.py", "README.md", "web/app.js", "CHANGELOG.md"} <= set(tree1)
    assert "pkg/extra.py" not in tree1
    assert g.blob(tree1["pkg/util.py"][0]) == b"def helper(x):\n    return x + 1\n"

    changes = {(c.status, c.new_path or c.old_path) for c in g.changes(v1, v11)}
    assert ("A", "pkg/extra.py") in changes
    assert ("M", "pkg/util.py") in changes
    assert ("M", "CHANGELOG.md") in changes


def test_git_access_is_read_only(make_repo, git_cmd):
    from rw.repo.git import GitRepo
    repo = make_repo()
    git_cmd(repo, "checkout", "-q", "v1.0.0")  # detached at an older revision
    before = _snapshot(repo, git_cmd)
    g = GitRepo(repo)
    v11 = g.resolve("v1.1.0")
    g.commits(["v1.1.0"])
    g.tags()
    g.changes(g.resolve("v1.0.0"), v11)
    for _path, sha, _mode in g.tree(v11):
        g.blob(sha)
    assert _snapshot(repo, git_cmd) == before
    assert not (repo / "pkg" / "extra.py").exists()  # no checkout of v1.1.0 happened


# ---------------------------------------------------------------- adapters

def test_supported_languages_and_limits():
    from rw.repo import adapters
    from rw.repo.adapters import python as py
    assert "python" in adapters.SUPPORTED_LANGUAGES
    assert py.LIMITS and all(isinstance(s, str) and s for s in py.LIMITS)
    assert "python" in adapters.ADAPTERS
    for lang, adapter in adapters.ADAPTERS.items():
        assert adapter.language == lang
        assert adapter.LIMITS, f"{lang} adapter must declare its extraction limits"
        assert adapter.extensions and adapter.version


def test_adapter_registry_routes_by_extension():
    from rw.repo.adapters import adapter_for
    assert adapter_for("pkg/core.py").language == "python"
    assert adapter_for("web/app.js") is None
    assert adapter_for("README.md") is None


def _extract(path, text):
    from rw.repo.adapters.python import PythonAdapter
    return PythonAdapter().extract(path, text.encode("utf-8"))


def test_python_adapter_symbols(v1_files):
    ex = _extract("pkg/core.py", v1_files["pkg/core.py"])
    syms = {s.qualname: s for s in ex.symbols}
    assert syms["pkg.core"].kind == "module"
    assert syms["pkg.core.Base"].kind == "class"
    assert (syms["pkg.core.Base"].start_line, syms["pkg.core.Base"].end_line) == (5, 7)
    assert syms["pkg.core.Base.run"].kind == "method"
    assert (syms["pkg.core.Base.run"].start_line, syms["pkg.core.Base.run"].end_line) == (6, 7)
    assert syms["pkg.core.Engine.start"].kind == "method"
    assert syms["pkg.core.build"].kind == "function"
    assert (syms["pkg.core.build"].start_line, syms["pkg.core.build"].end_line) == (15, 16)
    assert ex.errors == []
    assert ex.limits


def test_python_adapter_relations_and_provenance(v1_files):
    ex = _extract("pkg/core.py", v1_files["pkg/core.py"])
    rels = ex.relations
    imports = [r for r in rels if r.kind == "IMPORTS"]
    assert any(r.target == "os" for r in imports)
    assert any("pkg.util" in r.target for r in imports)
    assert all(r.provenance == "parsed" for r in imports)
    inherits = [r for r in rels if r.kind == "INHERITS"]
    assert any(r.source == "pkg.core.Engine" and r.target.endswith("Base") for r in inherits)
    assert all(r.provenance == "parsed" for r in inherits)
    calls = [r for r in rels if r.kind == "CALLS"]
    assert any(r.source == "pkg.core.Base.run" and r.target.endswith("helper") for r in calls)
    assert calls and all(r.provenance == "inferred" for r in calls)
    assert all(r.extractor.startswith("python@") for r in rels)


def test_python_adapter_syntax_error_is_recorded_not_raised():
    ex = _extract("pkg/broken.py", "def oops(:\n    pass\n")
    assert ex.errors
    assert not any(s.kind in ("class", "function", "method") for s in ex.symbols)


# ---------------------------------------------------------------- indexing

def _q(graph_name, cypher, params=None):
    from rw import graph as G
    return G.connect().select_graph(graph_name).query(cypher, params or {}).result_set


def _count(graph_name, pattern):
    return _q(graph_name, f"MATCH {pattern} RETURN count(*)")[0][0]


def test_index_repository_builds_graph(make_repo, write_config, graph_name, git_cmd):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    repo = make_repo()
    cfg = load_config(write_config("demo", repo))
    report = index_repository(cfg, graph_name=graph_name)

    assert report.status == "COMPLETE"
    assert report.commits == 3
    assert report.blobs > 0
    gap_text = " ".join(str(g.detail) for g in report.coverage_gaps)
    assert "web/app.js" in gap_text and "README.md" in gap_text
    assert "pkg/core.py" not in gap_text

    assert _q(graph_name, "MATCH (r:Repository) RETURN r.name")[0][0] == "demo"
    assert _count(graph_name, "(:Commit)") == 3
    assert {row[0] for row in _q(graph_name, "MATCH (t:Tag) RETURN t.name")} == {"v1.0.0", "v1.1.0"}
    assert _count(graph_name, "(:Tag)-[:POINTS_TO]->(:Commit)") == 2
    assert _count(graph_name, "(:Commit)-[:PARENT]->(:Commit)") == 2
    assert _count(graph_name, "(:Commit)-[:HAS_FILE]->(:Blob)") > 0
    assert _count(graph_name, "(:Blob)") >= report.blobs
    qualnames = {row[0] for row in _q(graph_name,
                 "MATCH (:Blob)-[:DEFINES]->(s:Symbol) RETURN s.qualname")}
    assert {"pkg.core.Engine", "pkg.core.Engine.start", "pkg.util.helper", "pkg.extra.extra"} <= qualnames
    head = git_cmd(repo, "rev-parse", "HEAD")
    paths = {row[0] for row in _q(graph_name,
             "MATCH (c:Commit {sha:$sha})-[h:HAS_FILE]->(:Blob) RETURN h.path", {"sha": head})}
    assert {"pkg/core.py", "pkg/extra.py", "CHANGELOG.md"} <= paths
    runs = [tuple(r) for r in _q(graph_name, "MATCH (r:ImportRun) RETURN r.id, r.status")]
    assert runs == [(report.import_run_id, "COMPLETE")]


def test_two_repos_onboard_by_configuration_only(make_repo, write_config):
    """Two structurally different repos, two JSON configs, same code path; identities never mix."""
    from rw import graph as G
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    alpha = make_repo("alpha")
    beta = make_repo("beta", files={
        "lib/__init__.py": "",
        "lib/shapes/geom.py": "class Shape:\n    def area(self):\n        return 0\n\n\n"
                              "class Square(Shape):\n    def area(self):\n        return 4\n",
        "lib/util.py": "def helper(x):\n    return x\n",
        "CHANGELOG.md": "# Changes\n",
    })
    names = [f"rw_test_repo_{uuid.uuid4().hex[:12]}" for _ in range(2)]
    try:
        ra = index_repository(load_config(write_config("alpha", alpha)), graph_name=names[0])
        rb = index_repository(load_config(write_config("beta", beta, tag_pattern=r"^v1\.")),
                              graph_name=names[1])
        assert ra.status == rb.status == "COMPLETE"
        assert _q(names[0], "MATCH (r:Repository) RETURN r.name")[0][0] == "alpha"
        assert _q(names[1], "MATCH (r:Repository) RETURN r.name")[0][0] == "beta"
        qa = {r[0] for r in _q(names[0], "MATCH (s:Symbol) RETURN s.qualname")}
        qb = {r[0] for r in _q(names[1], "MATCH (s:Symbol) RETURN s.qualname")}
        assert "lib.shapes.geom.Square.area" in qb and "lib.shapes.geom.Square" not in qa
        cy = "MATCH (s:Symbol) WHERE s.id IS NOT NULL AND s.external IS NULL RETURN s.id"
        ids_a = {r[0] for r in _q(names[0], cy)}
        ids_b = {r[0] for r in _q(names[1], cy)}
        assert ids_a and ids_b and not (ids_a & ids_b)
        assert all("alpha" in i for i in ids_a) and all("beta" in i for i in ids_b)
    finally:
        for n in names:
            try:
                G.connect().select_graph(n).delete()
            except Exception:
                pass


def test_ingestion_never_executes_repo_code(make_repo, write_config, graph_name, tmp_path):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    sentinel = tmp_path / "EXECUTED"
    repo = make_repo("danger", sentinel=sentinel)
    report = index_repository(load_config(write_config("danger", repo)), graph_name=graph_name)
    assert report.status == "COMPLETE"
    assert not sentinel.exists()
    assert "pkg.danger.boom" in {r[0] for r in _q(graph_name, "MATCH (s:Symbol) RETURN s.qualname")}


# ---------------------------------------------------------------- regression baseline

def test_fixture_baseline_still_present():
    import rw.pipeline  # noqa: F401
    assert (ROOT / "fixtures" / "shop" / "releases").is_dir()
