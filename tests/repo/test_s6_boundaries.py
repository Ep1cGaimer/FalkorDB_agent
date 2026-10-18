"""S6 — preserve verification boundaries (remquirements-v1.md S6, E5; Status Rules).

Graph tests need FalkorDB at 127.0.0.1:6379 (unique graph names, deleted afterwards). Nothing realrepo.

Interface assumed (new module rw.repo.runtime; investigate gains `mode` and `runtime_adapter`):

rw.repo.runtime
  RUNTIME_ADAPTERS: dict[str, adapter]          — empty by default (runtime checks are optional).
  register_runtime_adapter(name: str, adapter) -> None   (adds to RUNTIME_ADAPTERS).
  RuntimeReceipt(obligation: str, status: "PASS"|"FAIL", revision: str (40-hex commit sha),
                 extractor_version: str, adapter_version: str)   (dataclass; keyword construction)
  extractor_fingerprint() -> str   — current extractor identity (e.g. joined adapter versions); a receipt
                 whose extractor_version differs is stale.
  Adapter protocol (duck-typed):  .version: str
      .obligations(repo: str, sha: str, question: str) -> list[str]   modeled obligation ids
      .check(repo: str, sha: str, obligations: list[str]) -> list[RuntimeReceipt]
  Adapters must never be invoked by ingestion or retrieval mode.

rw.repo.investigate.investigate(repo, revision, question, *, graph_name=None, db=None, config=None,
                                mode="retrieval", runtime_adapter: str | None = None) -> RepoFindings
  RepoFindings gains .disposition: None | "BLOCKED" | "NEEDS_EVIDENCE" | "BOUNDED_PASS"
  and .receipts: list[RuntimeReceipt]. Finding.disposition stays None always.
  mode="retrieval" (default): .disposition is None, whatever the question; no adapter is called.
  mode="compatibility": recognises "Is <revA> compatible with <revB>?" (and any routed question).
    - no adapter named/registered -> disposition None and a Gap kind "NO_RUNTIME_ADAPTER" or
      "runtime_unverified". Never BOUNDED_PASS.
    - adapter given: any FAIL receipt on a modeled obligation -> "BLOCKED";
      else any modeled obligation lacking a current receipt -> "NEEDS_EVIDENCE";
      else (all PASS, all current) -> "BOUNDED_PASS".
      Current = receipt.revision == resolved_sha and extractor_version == extractor_fingerprint()
      and adapter_version == adapter.version; a stale receipt counts as missing (revalidation).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPAT_Q = "Is v1.1.0 compatible with v1.0.0?"
ALLOWED_GIT = {"cat-file", "ls-tree", "log", "rev-list", "rev-parse", "diff-tree", "for-each-ref",
               "merge-base", "patch-id", "show"}
QUESTIONS = ["What does pkg.core.Engine.start depend on?", "What depends on pkg.util.helper?",
             "What changed between v1.0.0 and v1.1.0?", "Is fix v1.0.0 present?",
             "When did pkg.extra.extra appear?", "Release notes", "List symbols",
             "Where is pkg.core.Engine defined?", COMPAT_Q]


def _indexed(make_repo, write_config, graph_name, name="s6"):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    repo = make_repo(name)
    cfg = load_config(write_config(name, repo))
    assert index_repository(cfg, graph_name=graph_name).status == "COMPLETE"
    return cfg


# ---------------------------------------------------------------- 1. optional, pluggable runtime adapters

def test_runtime_registry_is_empty_by_default_and_pluggable(monkeypatch):
    from rw.repo import runtime
    assert isinstance(runtime.RUNTIME_ADAPTERS, dict)
    assert not runtime.RUNTIME_ADAPTERS, "runtime adapters must be optional (none built in)"
    monkeypatch.setattr(runtime, "RUNTIME_ADAPTERS", {})
    a = object()
    runtime.register_runtime_adapter("fake", a)
    assert runtime.RUNTIME_ADAPTERS["fake"] is a


class FakeAdapter:
    version = "fake@1"

    def __init__(self, obligations, receipts_fn):
        self._obl = obligations
        self._fn = receipts_fn
        self.calls = 0

    def obligations(self, repo, sha, question):
        return list(self._obl)

    def check(self, repo, sha, obligations):
        self.calls += 1
        return self._fn(sha)


def _receipt(ob, status, sha, **over):
    from rw.repo import runtime
    kw = dict(obligation=ob, status=status, revision=sha,
              extractor_version=runtime.extractor_fingerprint(), adapter_version=FakeAdapter.version)
    kw.update(over)
    return runtime.RuntimeReceipt(**kw)


def _compat(cfg, graph_name, adapter=None, monkeypatch=None):
    from rw.repo import runtime
    from rw.repo.investigate import investigate
    if adapter is not None:
        monkeypatch.setattr(runtime, "RUNTIME_ADAPTERS", {})
        runtime.register_runtime_adapter("fake", adapter)
    return investigate(cfg.name, "v1.1.0", COMPAT_Q, graph_name=graph_name, config=cfg,
                       mode="compatibility", runtime_adapter="fake" if adapter else None)


def test_compatibility_without_adapter_is_explicit_gap(make_repo, write_config, graph_name):
    cfg = _indexed(make_repo, write_config, graph_name)
    out = _compat(cfg, graph_name)
    assert out.disposition is None
    assert {g.kind for g in out.gaps} & {"NO_RUNTIME_ADAPTER", "runtime_unverified"}
    assert all(f.disposition is None for f in out.findings)


@pytest.mark.parametrize("case,expected", [
    ("all_pass", "BOUNDED_PASS"),
    ("one_fail", "BLOCKED"),
    ("fail_and_missing", "BLOCKED"),
    ("missing", "NEEDS_EVIDENCE"),
    ("stale_revision", "NEEDS_EVIDENCE"),
    ("stale_extractor", "NEEDS_EVIDENCE"),
    ("stale_adapter", "NEEDS_EVIDENCE"),
    ("no_receipts", "NEEDS_EVIDENCE"),
])
def test_compatibility_dispositions_follow_status_rules(case, expected, make_repo, write_config,
                                                        graph_name, monkeypatch):
    cfg = _indexed(make_repo, write_config, graph_name)
    obls = ["ob.a", "ob.b"]
    other = "0" * 40

    def receipts(sha):
        return {
            "all_pass": [_receipt("ob.a", "PASS", sha), _receipt("ob.b", "PASS", sha)],
            "one_fail": [_receipt("ob.a", "PASS", sha), _receipt("ob.b", "FAIL", sha)],
            "fail_and_missing": [_receipt("ob.a", "FAIL", sha)],
            "missing": [_receipt("ob.a", "PASS", sha)],
            "stale_revision": [_receipt("ob.a", "PASS", sha), _receipt("ob.b", "PASS", other)],
            "stale_extractor": [_receipt("ob.a", "PASS", sha),
                                _receipt("ob.b", "PASS", sha, extractor_version="python@0-old")],
            "stale_adapter": [_receipt("ob.a", "PASS", sha),
                              _receipt("ob.b", "PASS", sha, adapter_version="fake@0")],
            "no_receipts": [],
        }[case]
    adapter = FakeAdapter(obls, receipts)
    out = _compat(cfg, graph_name, adapter, monkeypatch)
    assert adapter.calls >= 1
    assert out.disposition == expected
    assert all(f.disposition is None for f in out.findings)


def test_bounded_pass_requires_modeled_obligations(make_repo, write_config, graph_name, monkeypatch):
    """An adapter modelling no obligations proves nothing: never BOUNDED_PASS."""
    cfg = _indexed(make_repo, write_config, graph_name)
    out = _compat(cfg, graph_name, FakeAdapter([], lambda sha: []), monkeypatch)
    assert out.disposition != "BOUNDED_PASS"


# ---------------------------------------------------------------- 2. retrieval never yields a disposition

@pytest.mark.parametrize("q", [COMPAT_Q, "What changed between v1.0.0 and v1.1.0?", "List symbols"])
def test_retrieval_mode_never_dispositions(q, make_repo, write_config, graph_name, monkeypatch):
    from rw.repo import runtime
    from rw.repo.investigate import investigate
    cfg = _indexed(make_repo, write_config, graph_name)
    adapter = FakeAdapter(["ob.a"], lambda sha: [_receipt("ob.a", "PASS", sha)])
    monkeypatch.setattr(runtime, "RUNTIME_ADAPTERS", {"fake": adapter})
    for kw in ({}, {"mode": "retrieval"}):
        out = investigate(cfg.name, "v1.1.0", q, graph_name=graph_name, config=cfg, **kw)
        assert getattr(out, "disposition", None) is None
        assert all(f.disposition is None for f in out.findings)
        assert all(d["disposition"] is None for d in out.to_dict()["findings"])
        assert out.to_dict().get("disposition") is None
    assert adapter.calls == 0, "retrieval must not invoke runtime adapters"


# ---------------------------------------------------------------- 3. ingestion never executes repo code

def _hostile_files(sentinel_dir: Path) -> dict:
    def w(tag):
        return f"open(r\"{sentinel_dir / tag}\", \"w\").write(\"x\")\n"
    from tests.repo.conftest import V1_FILES
    files = dict(V1_FILES)
    files.update({
        "setup.py": w("setup") + "def configure():\n    return 1\n",
        "conftest.py": w("conftest"),
        "pkg/__init__.py": w("init") + "from pkg.core import Engine\n",
        "sitecustomize.py": w("sitecustomize"),
        "usercustomize.py": w("usercustomize"),
        "evil.pth": "import os; " + w("pth").strip() + "\n",
        "pkg/danger.py": w("danger") + "\n\ndef boom():\n    return 1\n",
        "Makefile": f"all:\n\techo x > {sentinel_dir / 'make'}\n",
        ".gitattributes": "*.py filter=evil\n",
    })
    return files


def test_ingestion_and_investigation_never_execute_repo_code(make_repo, write_config, graph_name,
                                                             tmp_path, monkeypatch):
    from rw.repo.config import load_config
    from rw.repo.index import index_repository
    from rw.repo.investigate import investigate
    sentinels = tmp_path / "sentinels"
    sentinels.mkdir()
    repo = make_repo("hostile", files=_hostile_files(sentinels))

    spawned: list[list[str]] = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # subprocess.run goes through Popen
        def __init__(self, args, *a, **kw):
            spawned.append([str(x) for x in (args if isinstance(args, (list, tuple)) else [args])])
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    monkeypatch.setattr(os, "system", lambda *a, **k: pytest.fail(f"os.system called: {a}"))
    monkeypatch.chdir(repo)  # even with the repo as cwd nothing may be imported from it

    cfg = load_config(write_config("hostile", repo))
    assert index_repository(cfg, graph_name=graph_name).status == "COMPLETE"
    for q in QUESTIONS:
        for mode in ("retrieval", "compatibility"):
            investigate(cfg.name, "v1.1.0", q, graph_name=graph_name, config=cfg, mode=mode)

    assert not list(sentinels.iterdir()), f"repository code executed: {list(sentinels.iterdir())}"
    assert not any(str(getattr(m, "__file__", "") or "").startswith(str(repo))
                   for m in list(sys.modules.values())), "a module was imported from the repository"
    assert spawned, "expected git subprocesses"
    for cmd in spawned:
        exe = Path(cmd[0]).name.lower()
        assert exe in ("git", "git.exe"), f"non-git process spawned: {cmd}"
        assert not any("python" in c.lower() for c in cmd), cmd
        # first positional that is not an option value
        args = cmd[1:]
        i, positional = 0, None
        while i < len(args):
            if args[i] in ("-C", "-c"):
                i += 2
                continue
            if args[i].startswith("-"):
                i += 1
                continue
            positional = args[i]
            break
        assert positional in ALLOWED_GIT, f"git subcommand not allowlisted (read-only): {cmd}"


# ---------------------------------------------------------------- 4. no fixture-harness inheritance

def test_repo_package_does_not_import_fixture_harness():
    code = ("import sys, importlib, pkgutil, rw.repo\n"
            "for m in pkgutil.walk_packages(rw.repo.__path__, 'rw.repo.'):\n"
            "    importlib.import_module(m.name)\n"
            "bad = [m for m in ('rw.probes', 'rw.verification') if m in sys.modules]\n"
            "print(','.join(bad))\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                         cwd=str(ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"rw.repo imports the fixture harness: {out.stdout.strip()}"


def test_investigate_never_calls_fixture_probes(make_repo, write_config, graph_name, monkeypatch):
    import rw.probes as probes
    import rw.verification as verification
    from rw.repo.investigate import investigate

    def boom(*a, **k):
        raise AssertionError("general retrieval called the fixture harness")
    for name in ("run_probe", "run_harness"):
        monkeypatch.setattr(probes, name, boom)
    for name in dir(verification):
        if name.startswith(("run", "verify")) and callable(getattr(verification, name)):
            monkeypatch.setattr(verification, name, boom)
    cfg = _indexed(make_repo, write_config, graph_name)
    for q in QUESTIONS:
        for mode in ("retrieval", "compatibility"):
            out = investigate(cfg.name, "v1.1.0", q, graph_name=graph_name, config=cfg, mode=mode)
            assert getattr(out, "disposition", None) is None  # no adapter configured
