"""Synthetic Git repositories for the repository-integration (S1) tests. Built with `git` plumbing in
tmp_path; deterministic author/committer dates. Nothing here imports repository code."""
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

BASE_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(repo: Path, *args: str, date: str = "2024-01-01T00:00:00+00:00") -> str:
    env = {**os.environ, **BASE_ENV, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "-c", "core.autocrlf=false",
                          "-c", "init.defaultBranch=main", "-c", "tag.gpgsign=false",
                          "-c", "commit.gpgsign=false", "-C", str(repo), *args],
                         env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


V1_FILES = {
    "pkg/__init__.py": "from pkg.core import Engine\n",
    "pkg/core.py": (
        "import os\n"
        "from pkg.util import helper\n"
        "\n"
        "\n"
        "class Base:\n"
        "    def run(self):\n"
        "        return helper(1)\n"
        "\n"
        "\n"
        "class Engine(Base):\n"
        "    def start(self):\n"
        "        return self.run()\n"
        "\n"
        "\n"
        "def build():\n"
        "    return Engine()\n"
    ),
    "pkg/util.py": "def helper(x):\n    return x + 1\n",
    "README.md": "# Demo\n",
    "web/app.js": "function hello() { return 1; }\n",
    "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- initial\n",
}


@pytest.fixture
def make_repo(tmp_path):
    """make_repo(name="demo", files=None, sentinel=None) -> Path of a git repo with 3 commits:
    c1 (v1 files, tag v1.0.0), c2 (adds pkg/extra.py), c3 (edits util + CHANGELOG, tag v1.1.0).
    `files` overrides the v1 file set. If `sentinel` (a Path) is given, pkg/danger.py would write it
    when imported/executed."""
    def _make(name: str = "demo", files: dict | None = None, sentinel: Path | None = None) -> Path:
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q")
        for rel, text in (files or V1_FILES).items():
            write(repo, rel, text)
        if sentinel is not None:
            write(repo, "pkg/danger.py",
                  f"open(r\"{sentinel}\", \"w\").write(\"x\")\n\n\ndef boom():\n    return 1\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "initial", date="2024-01-01T00:00:00+00:00")
        git(repo, "tag", "-a", "v1.0.0", "-m", "release 1.0.0", date="2024-01-01T00:00:00+00:00")
        write(repo, "pkg/extra.py", "from pkg.util import helper\n\n\ndef extra():\n    return helper(2)\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add extra", date="2024-01-02T00:00:00+00:00")
        write(repo, "pkg/util.py", "def helper(x):\n    return x + 2\n")
        write(repo, "CHANGELOG.md", "# Changelog\n\n## 1.1.0\n- helper\n\n## 1.0.0\n- initial\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "change helper", date="2024-01-03T00:00:00+00:00")
        git(repo, "tag", "-a", "v1.1.0", "-m", "release 1.1.0", date="2024-01-03T00:00:00+00:00")
        return repo
    return _make


@pytest.fixture
def write_config(tmp_path):
    """write_config(name, repo_path, **extra) -> Path of a repos/<name>.json config file."""
    def _write(name: str, repo: Path, **extra) -> Path:
        cfg_dir = tmp_path / "repos"
        cfg_dir.mkdir(exist_ok=True)
        path = cfg_dir / f"{name}.json"
        body = {"name": name, "path": str(repo), "tag_pattern": r"^v\d+\.\d+\.\d+$", "languages": ["python"]}
        body.update(extra)
        path.write_text(json.dumps(body), encoding="utf-8")
        return path
    return _write


@pytest.fixture
def graph_name():
    """Unique FalkorDB graph name; deleted after the test."""
    name = f"rw_test_repo_{uuid.uuid4().hex[:12]}"
    yield name
    try:
        from rw import graph as G
        G.connect().select_graph(name).delete()
    except Exception:
        pass


@pytest.fixture
def git_cmd():
    """The `git(repo, *args)` helper, for tests that inspect the synthetic repo directly."""
    return git


@pytest.fixture
def v1_files():
    return dict(V1_FILES)


# ---------------------------------------------------------------- S2 history repo
# Line numbers below are load-bearing for tests/repo/test_s2_evidence.py.

HISTORY_V1 = {
    "app/__init__.py": "",
    "app/api.py": (
        "from app.service import process\n"      # 1
        "\n"
        "\n"
        "def handle(req):\n"                      # 4
        "    return process(req)\n"               # 5
    ),
    "app/service.py": (
        "import requests\n"                       # 1  (unresolved third-party import)
        "from app.store import save\n"            # 2
        "\n"
        "\n"
        "def process(req):\n"                     # 5
        "    return save(req)\n"                  # 6
        "\n"
        "\n"
        "def legacy_check(x):\n"                  # 9
        "    return x\n"                          # 10
    ),
    "app/store.py": (
        "def save(item):\n"                       # 1
        "    return item\n"                       # 2
    ),
    "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- initial release\n",
}

HISTORY_V11_CHANGES = {
    "app/store.py": (
        "def sanitize(item):\n"                   # 1
        "    return item.strip()\n"               # 2
        "\n"
        "\n"
        "def save(item):\n"                       # 5
        "    return sanitize(item)\n"             # 6
    ),
    "app/service.py": (
        "import requests\n"
        "from app.store import save\n"
        "\n"
        "\n"
        "def process(req):\n"                     # 5
        "    return save(req)\n"                  # 6
    ),
    "app/extra.py": (
        "from app.store import save\n"            # 1
        "\n"
        "\n"
        "def bulk(items):\n"                      # 4
        "    return [save(i) for i in items]\n"   # 5
    ),
    "CHANGELOG.md": (
        "# Changelog\n\n## 1.1.0\n- add sanitize to store.save (fixes #12)\n- remove legacy_check\n"
        "\n## 1.0.0\n- initial release\n"
    ),
}

HISTORY_V12_CHANGES = {
    "app/store.py": "def save(item):\n    return item\n",
    "CHANGELOG.md": (
        "# Changelog\n\n## 1.2.0\n- drop sanitize (reintroduces #12)\n- remove app/extra.py\n"
        "\n## 1.1.0\n- add sanitize to store.save (fixes #12)\n- remove legacy_check\n"
        "\n## 1.0.0\n- initial release\n"
    ),
}


@pytest.fixture
def make_history_repo(tmp_path):
    """make_history_repo(name="hist") -> Path. Three commits on main, each tagged (annotated):
    v1.0.0 = HISTORY_V1; v1.1.0 = adds app.store.sanitize + app/extra.py, save now calls sanitize,
    removes app.service.legacy_check; v1.2.0 = removes sanitize (save reverts to v1 text) and
    deletes app/extra.py. CHANGELOG.md gains a section per release."""
    def _make(name: str = "hist") -> Path:
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q")
        steps = [(HISTORY_V1, [], "initial", "v1.0.0", "2024-02-01T00:00:00+00:00"),
                 (HISTORY_V11_CHANGES, [], "add sanitize", "v1.1.0", "2024-02-02T00:00:00+00:00"),
                 (HISTORY_V12_CHANGES, ["app/extra.py"], "drop sanitize", "v1.2.0",
                  "2024-02-03T00:00:00+00:00")]
        for files, deletions, msg, tag, date in steps:
            for rel, text in files.items():
                write(repo, rel, text)
            for rel in deletions:
                (repo / rel).unlink()
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", msg, date=date)
            git(repo, "tag", "-a", tag, "-m", f"release {tag}", date=date)
        return repo
    return _make


# ---------------------------------------------------------------- S3 branchy repo
# Built by evals/repo_questions/build_branchy_history.py (single source of truth; plain git only).

def _load_branchy_builder():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "evals" / "repo_questions" / "build_branchy_history.py"
    spec = importlib.util.spec_from_file_location("_build_branchy_history", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def make_branchy_repo(tmp_path):
    """make_branchy_repo(name="branchy") -> dict(path=Path, fix=sha, revert=sha, reapply=sha, merge=sha,
    pick=sha, legacy_backport=sha, feature_tip=sha, readme=sha, modify=sha). See the builder docstring:
    tags v1.0.0, v1.1.0 (merge), v2.0.0 (revert of fix), v2.1.0 (reapply), v2.2.0 (modified fix +
    rename svc/helpers.py->svc/tools.py with edit + delete svc/legacy.py) on main; v1.0.1 (cherry-pick
    -x of fix) on release-1.x; v1.0.2 (non-equivalent backport) on release-legacy."""
    mod = _load_branchy_builder()

    def _make(name: str = "branchy") -> dict:
        return mod.build(tmp_path / name)
    return _make
