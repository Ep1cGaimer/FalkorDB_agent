"""S5 — accessible investigation (docs/repo/REQUIREMENTS.md S5; docs/repo/DESIGN.md "Access surfaces").

Graph tests need FalkorDB at 127.0.0.1:6379. Each test uses a unique repo name (``s5-<hex>``) so the
default graph ``rw_repo_<name>`` is unique; it is deleted afterwards.

Interface assumed (the implementer must provide exactly this):

rw.repo.investigate
  investigate(repo: str, revision: str | None, question: str, *, graph_name: str | None = None,
              db=None, config: RepoConfig | str | Path | None = None) -> RepoFindings
    - Deterministic, NO LLM: a rule-based router over rw.repo.query.RepoQuery. Supported question shapes
      (case-insensitive):
        "What does <symbol> depend on?" / "What does <symbol> call?"      -> dependencies
        "What depends on <symbol>?" / "Who calls <symbol>?"                -> dependents
        "What changed between <revA> and <revB>?"                          -> changes_between
        "Is fix <sha> present?"                                            -> fix_status at `revision`
        "When did <symbol> appear?" / "... disappear?"                     -> symbol_history
        "Release notes" / "What are the release notes?"                    -> release_notes at `revision`
        "List symbols" / "Where is <symbol> defined?"                      -> symbols
    - `repo` is a repo name. `config` (RepoConfig or path to a config json) defaults to
      load_config(repo) (repos/<name>.json, or $RW_REPOS_DIR/<name>.json when that env var is set).
      graph_name defaults to rw.repo.index.graph_name_for(config).
    - Unknown repo (no config) -> unresolved set (mentions the repo), findings == [].
    - revision None/"" or not resolvable -> unresolved set (asks which revision), findings == [].
    - Ambiguous symbol (same short name defined in >1 module) -> either unresolved set or a Gap whose
      kind contains "ambig" or "clarif" and whose detail lists every candidate qualname; findings == [].
    - Unrecognised question -> unresolved or a Gap(kind contains "unsupported"/"clarif"); findings == [].
    - Every successful answer carries Gap(kind="runtime_unverified") (S6: retrieval is not a
      compatibility check).
  RepoFindings: findings: list[Finding], gaps: list[Gap], citations: list[Citation] (union of the
    findings' citations), unresolved: str | None, repo: str, revision: str | None,
    resolved_sha: str | None (40-hex);  to_dict() -> JSON-safe dict with the same keys
    (findings[i] -> {"kind","summary","citations":[...],"disposition"}, citations -> {"repo","commit",
    "path","start_line","end_line", ...}, gaps -> {"kind","detail"}).
  Finding: kind: str, summary: str, citations: list[rw.repo.model.Citation], disposition: None
    (retrieval mode never sets a compatibility disposition).
  Citation.commit is always a full 40-hex sha that is the requested revision (or, for
  "changed between A and B", one of the two named revisions); citation.repo == the requested repo name.

rw.repo.mcp
  repo_investigate(repo: str, revision: str, question: str) -> dict   (== investigate(...).to_dict());
  rw/mcp_server.py registers it as a tool named "repo_investigate" (checked in source text, since the
  `mcp` package may be absent).

CLI (JSON on stdout = RepoFindings.to_dict(); index prints the IndexReport incl. "status"):
  scripts/repo_index.py --config PATH [--graph NAME]
  scripts/repo_investigate.py --repo NAME --rev REF --config PATH [--graph NAME] "question"

API (rw.api.create_app(session_factory=...)); configs looked up via load_config(name):
  POST /api/repos/{name}/index                  -> 200 {"status": "COMPLETE", "import_run_id", ...}
  GET  /api/repos                               -> 200 [{"name", "import_status", "revisions":
                                                    [{"sha", "refs": [...]} | sha-string, ...]}, ...]
  POST /api/repos/{name}/investigate {revision, question} -> 200 RepoFindings.to_dict()
  Bad repo names / path traversal -> 404 or 422 (never 200, never 500).
"""
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from .conftest import git as _git, write as _write

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)
SHA40 = re.compile(r"^[0-9a-f]{40}$")


# ---------------------------------------------------------------- helpers / fixtures

@pytest.fixture
def repo_name():
    name = f"s5-{uuid.uuid4().hex[:10]}"
    yield name
    try:
        from rw import graph as G
        G.connect().select_graph(f"rw_repo_{name}").delete()
    except Exception:
        pass


@pytest.fixture
def repos_env(tmp_path, monkeypatch):
    """Point load_config(name) at tmp_path/repos via RW_REPOS_DIR."""
    d = tmp_path / "repos"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("RW_REPOS_DIR", str(d))
    return d


@pytest.fixture
def indexed_hist(make_history_repo, write_config, repo_name, repos_env):
    from rw.repo.index import index_repository
    from rw.repo.config import load_config
    repo = make_history_repo(name=repo_name)
    cfg_path = write_config(repo_name, repo)
    assert cfg_path.parent == repos_env
    report = index_repository(load_config(cfg_path))
    assert report.status == "COMPLETE"
    return {"name": repo_name, "path": repo, "config": cfg_path}


def _sha(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", f"{rev}^{{commit}}")


def _cit(c):
    return c if isinstance(c, dict) else {k: getattr(c, k, None) for k in
                                           ("repo", "commit", "path", "start_line", "end_line")}


def _assert_citation_resolves(repo: Path, name: str, c, allowed_shas: set[str]):
    c = _cit(c)
    assert c["repo"] == name
    assert SHA40.match(c["commit"]), c
    assert c["commit"] in allowed_shas, (c, allowed_shas)
    text = subprocess.run(["git", "-C", str(repo), "show", f"{c['commit']}:{c['path']}"],
                          capture_output=True, text=True, check=True).stdout
    n = len(text.splitlines())
    if c.get("start_line") is not None:
        assert 1 <= c["start_line"] <= (c.get("end_line") or c["start_line"]) <= max(n, 1), (c, n)


def _check_result(res, repo: Path, name: str, allowed: set[str]):
    assert res.unresolved in (None, "")
    assert res.findings, "expected findings"
    for f in res.findings:
        assert f.disposition is None
        assert f.citations, f
        for c in f.citations:
            _assert_citation_resolves(repo, name, c, allowed)
    assert set(map(_key, res.citations)) >= {_key(c) for f in res.findings for c in f.citations}
    assert any(g.kind == "runtime_unverified" for g in res.gaps)


def _key(c):
    c = _cit(c)
    return (c["repo"], c["commit"], c["path"], c.get("start_line"), c.get("end_line"))


def _no_findings(res):
    assert res.findings == []
    assert res.citations == []


# ---------------------------------------------------------------- 1. investigate() routing

def test_dependencies_question(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    sha = _sha(h["path"], "v1.0.0")
    res = investigate(h["name"], "v1.0.0", "What does app.api.handle depend on?")
    assert res.repo == h["name"] and res.resolved_sha == sha
    _check_result(res, h["path"], h["name"], {sha})
    assert "process" in json.dumps(res.to_dict())


def test_changes_between_question(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    a, b = _sha(h["path"], "v1.0.0"), _sha(h["path"], "v1.1.0")
    res = investigate(h["name"], "v1.1.0", "What changed between v1.0.0 and v1.1.0?")
    _check_result(res, h["path"], h["name"], {a, b})
    blob = json.dumps(res.to_dict())
    assert "app/store.py" in blob and "app/extra.py" in blob


def test_release_notes_question(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    sha = _sha(h["path"], "v1.1.0")
    res = investigate(h["name"], "v1.1.0", "What are the release notes?")
    _check_result(res, h["path"], h["name"], {sha})
    assert any(_cit(c)["path"] == "CHANGELOG.md" for c in res.citations)


def test_symbol_history_question(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    shas = {_sha(h["path"], t) for t in ("v1.0.0", "v1.1.0", "v1.2.0")}
    res = investigate(h["name"], "v1.2.0", "When did app.store.sanitize appear?")
    assert res.unresolved in (None, "")
    for f in res.findings:
        assert f.disposition is None
        for c in f.citations:
            _assert_citation_resolves(h["path"], h["name"], c, shas)
    assert res.findings or res.gaps
    labelled = {_cit(c)["commit"] for f in res.findings if getattr(f, "revision", None) for c in f.citations}
    assert _sha(h["path"], "v1.1.0") in labelled
    assert all(_cit(c)["commit"] == _sha(h["path"], "v1.2.0") for c in res.citations)


def test_fix_present_question_has_no_disposition(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    fix = _sha(h["path"], "v1.1.0")
    res = investigate(h["name"], "v1.2.0", f"Is fix {fix} present?")
    assert res.unresolved in (None, "")
    shas = {fix, _sha(h["path"], "v1.2.0"), _sha(h["path"], "v1.0.0")}
    for f in res.findings:
        assert f.disposition is None
        for c in f.citations:
            _assert_citation_resolves(h["path"], h["name"], c, shas)
    d = res.to_dict()
    assert all(f["disposition"] is None for f in d["findings"])
    assert "BOUNDED_PASS" not in json.dumps(d)


def test_to_dict_is_json_safe(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    d = investigate(h["name"], "v1.0.0", "What does app.api.handle depend on?").to_dict()
    d2 = json.loads(json.dumps(d))
    assert set(d2) >= {"findings", "gaps", "citations", "unresolved", "repo", "revision", "resolved_sha"}


# ---------------------------------------------------------------- 2. unresolved inputs

def test_unknown_repo_is_unresolved(repos_env):
    from rw.repo.investigate import investigate
    res = investigate("no-such-repo-s5", "v1.0.0", "What does x depend on?")
    assert res.unresolved and "no-such-repo-s5" in res.unresolved
    _no_findings(res)


@pytest.mark.parametrize("rev", [None, "", "v9.9.9", "deadbeef" * 5])
def test_missing_or_unknown_revision_asks_which(indexed_hist, rev):
    from rw.repo.investigate import investigate
    h = indexed_hist
    res = investigate(h["name"], rev, "What does app.api.handle depend on?")
    assert res.unresolved and "revision" in res.unresolved.lower()
    _no_findings(res)


def test_ambiguous_symbol_lists_candidates(make_repo, write_config, repo_name, repos_env):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    from rw.repo.investigate import investigate
    files = {"a/__init__.py": "", "a/one.py": "def helper():\n    return 1\n",
             "b/__init__.py": "", "b/two.py": "def helper():\n    return 2\n"}
    repo = make_repo(name=repo_name, files=files)
    assert index_repository(load_config(write_config(repo_name, repo))).status == "COMPLETE"
    res = investigate(repo_name, "v1.0.0", "What does helper depend on?")
    _no_findings(res)
    text = (res.unresolved or "") + " ".join(g.detail for g in res.gaps
                                             if "ambig" in g.kind or "clarif" in g.kind)
    assert res.unresolved or any("ambig" in g.kind or "clarif" in g.kind for g in res.gaps)
    assert "a.one.helper" in text and "b.two.helper" in text


def test_unsupported_question_not_fabricated(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    res = investigate(h["name"], "v1.0.0", "Please write me a poem about databases")
    _no_findings(res)
    assert res.unresolved or any("unsupported" in g.kind or "clarif" in g.kind for g in res.gaps)


def test_unknown_symbol_gives_gap_not_finding(indexed_hist):
    from rw.repo.investigate import investigate
    h = indexed_hist
    res = investigate(h["name"], "v1.0.0", "What does app.nothing.here depend on?")
    _no_findings(res)
    assert res.unresolved or res.gaps


# ---------------------------------------------------------------- 3. same workflow across surfaces

def _cli(*args, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run([str(PY), *args], capture_output=True, text=True, cwd=str(ROOT), env=env,
                         timeout=300)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from rw.api import create_app
    return TestClient(create_app(session_factory=lambda *a, **k: None))


def _summary(d: dict):
    return ({_key(c) for c in d["citations"]}, sorted({g["kind"] for g in d["gaps"]}),
            d["unresolved"], len(d["findings"]))


QUESTIONS = [("v1.0.0", "What does app.api.handle depend on?"),
             ("v1.1.0", "What changed between v1.0.0 and v1.1.0?"),
             ("v1.1.0", "Release notes"),
             ("v9.9.9", "What does app.api.handle depend on?")]


@pytest.mark.parametrize("rev,question", QUESTIONS)
def test_cli_api_mcp_equivalent(indexed_hist, client, rev, question):
    from rw.repo.investigate import investigate
    from rw.repo.mcp import repo_investigate
    h = indexed_hist
    direct = investigate(h["name"], rev, question).to_dict()
    cli = _cli("scripts/repo_investigate.py", "--repo", h["name"], "--rev", rev, "--config",
               str(h["config"]), question, env_extra={"RW_REPOS_DIR": str(h["config"].parent)})
    r = client.post(f"/api/repos/{h['name']}/investigate", json={"revision": rev, "question": question})
    assert r.status_code == 200, r.text
    mcp = repo_investigate(h["name"], rev, question)
    assert _summary(cli) == _summary(direct) == _summary(r.json()) == _summary(json.loads(json.dumps(mcp)))


def test_mcp_server_registers_repo_investigate():
    src = (ROOT / "src" / "rw" / "mcp_server.py").read_text(encoding="utf-8")
    assert re.search(r"name\s*=\s*[\"']repo_investigate[\"']", src)
    assert "repo_investigate" in src and ("rw.repo.mcp" in src or "repo.mcp" in src)
    from rw.repo import mcp as repo_mcp
    assert callable(repo_mcp.repo_investigate)
    try:
        import mcp  # noqa: F401
    except ImportError:
        return
    import anyio
    from rw.mcp_server import create_mcp_server

    async def names():
        return [t.name for t in await create_mcp_server().list_tools()]
    assert "repo_investigate" in anyio.run(names)


# ---------------------------------------------------------------- 4. indexing via CLI and API

def _import_runs(name):
    from rw import graph as G
    rows = G.connect().select_graph(f"rw_repo_{name}").query(
        "MATCH (r:ImportRun) RETURN r.id, r.status").result_set
    return {r[0]: r[1] for r in rows}


def _listed(client, name):
    r = client.get("/api/repos")
    assert r.status_code == 200, r.text
    hits = [x for x in r.json() if x["name"] == name]
    assert len(hits) == 1, r.json()
    return hits[0]


def _rev_shas(entry):
    return {(x if isinstance(x, str) else x["sha"]) for x in entry["revisions"]}


def test_index_via_cli_then_listed(make_history_repo, write_config, repo_name, repos_env, client):
    repo = make_history_repo(name=repo_name)
    cfg = write_config(repo_name, repo)
    rep = _cli("scripts/repo_index.py", "--config", str(cfg), env_extra={"RW_REPOS_DIR": str(repos_env)})
    assert rep["status"] == "COMPLETE"
    runs = _import_runs(repo_name)
    assert runs and all(s == "COMPLETE" for s in runs.values())
    entry = _listed(client, repo_name)
    assert entry["import_status"] == "COMPLETE"
    assert _rev_shas(entry) >= {_sha(repo, t) for t in ("v1.0.0", "v1.1.0", "v1.2.0")}


def test_index_via_api_then_listed(make_history_repo, write_config, repo_name, repos_env, client):
    repo = make_history_repo(name=repo_name)
    write_config(repo_name, repo)
    r = client.post(f"/api/repos/{repo_name}/index")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "COMPLETE" and body["import_run_id"]
    assert _import_runs(repo_name)[body["import_run_id"]] == "COMPLETE"
    entry = _listed(client, repo_name)
    assert entry["import_status"] == "COMPLETE"
    assert _sha(repo, "v1.2.0") in _rev_shas(entry)


def test_index_unknown_repo_api(repos_env, client):
    r = client.post("/api/repos/no-such-repo-s5/index")
    assert r.status_code in (404, 422)


# ---------------------------------------------------------------- 5. revision selection

def test_revision_changes_citations(indexed_hist, client):
    h = indexed_hist
    q = "What does app.store.save depend on?"
    out = {}
    for rev in ("v1.0.0", "v1.1.0"):
        r = client.post(f"/api/repos/{h['name']}/investigate", json={"revision": rev, "question": q})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["unresolved"] in (None, "") and d["findings"]
        out[rev] = {c["commit"] for c in d["citations"]}
        assert out[rev] == {_sha(h["path"], rev)}
    assert out["v1.0.0"] != out["v1.1.0"]
    assert "sanitize" in json.dumps(d)  # v1.1.0: save -> sanitize


@pytest.mark.parametrize("bad", ["Bad_Name", "..", "..%2F..%2Fetc", "%2E%2E", "a" * 80, "x%00y",
                                 "..%5Csecrets"])
def test_api_rejects_bad_names(client, repos_env, bad):
    for method, url, kw in (("post", f"/api/repos/{bad}/investigate",
                             {"json": {"revision": "v1.0.0", "question": "Release notes"}}),
                            ("post", f"/api/repos/{bad}/index", {})):
        r = getattr(client, method)(url, **kw)
        assert r.status_code in (404, 422), (url, r.status_code, r.text)


def test_api_investigate_requires_fields(indexed_hist, client):
    r = client.post(f"/api/repos/{indexed_hist['name']}/investigate", json={"revision": "v1.0.0"})
    assert r.status_code == 422


# ---------------------------------------------------------------- 6. no runtime instrumentation

def test_plain_repo_without_fixture_layout(tmp_path, write_config, repo_name, repos_env):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    from rw.repo.investigate import investigate
    repo = tmp_path / repo_name
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "lib/mathx.py", "def square(x):\n    return mul(x, x)\n\n\ndef mul(a, b):\n    return a * b\n")
    _write(repo, "lib/__init__.py", "")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c1")
    _git(repo, "tag", "-a", "v0.1.0", "-m", "r")
    for f in ("release.json", "codec.py", "fixture", "graph.json"):
        assert not (repo / f).exists()
    assert index_repository(load_config(write_config(repo_name, repo))).status == "COMPLETE"
    sha = _sha(repo, "v0.1.0")
    res = investigate(repo_name, "v0.1.0", "What does lib.mathx.square depend on?")
    _check_result(res, repo, repo_name, {sha})
    assert "mul" in json.dumps(res.to_dict())
    res = investigate(repo_name, "v0.1.0", "List symbols")
    _check_result(res, repo, repo_name, {sha})
