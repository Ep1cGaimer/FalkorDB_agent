"""E1 — onboarding real repositories (protocol: evals/repo_onboarding/README.md).

Runs only with RW_REALREPO=1 and for configs in evals/repo_onboarding/configs/*.json whose `path`
(relative to the project root) exists. Uses the S5 interface documented in tests/repo/test_s5_access.py
(rw.repo.investigate.investigate -> RepoFindings). Writes artifacts/repo_onboarding/<repo>-<ts>.json.
For configs with "unseen": true, src/rw/**/*.py must match evals/repo_onboarding/core_manifest.json
({"files": {"src/rw/...py": sha256}}) exactly.
"""
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONF_DIR = ROOT / "evals" / "repo_onboarding" / "configs"
MANIFEST = ROOT / "evals" / "repo_onboarding" / "core_manifest.json"
OUT = ROOT / "artifacts" / "repo_onboarding"


def _configs():
    out = []
    for p in sorted(CONF_DIR.glob("*.json")):
        body = json.loads(p.read_text(encoding="utf-8"))
        out.append(pytest.param(p, body, id=body.get("name", p.stem)))
    return out


def core_hashes() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src" / "rw").rglob("*.py"))}


def _cit(c):
    return {k: getattr(c, k, None) for k in ("repo", "commit", "path", "start_line", "end_line")}


def _check_citations(path: Path, name: str, res, allowed: set[str]):
    for f in res.findings:
        assert f.disposition is None
        for c in f.citations:
            c = _cit(c)
            assert c["repo"] == name and c["commit"] in allowed, c
            text = subprocess.run(["git", "-C", str(path), "show", f"{c['commit']}:{c['path']}"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  check=True).stdout
            if c["start_line"] is not None:
                assert 1 <= c["start_line"] <= (c["end_line"] or c["start_line"]) <= max(
                    len(text.splitlines()), 1), c


@pytest.mark.realrepo
@pytest.mark.skipif(not os.environ.get("RW_REALREPO"), reason="set RW_REALREPO=1 (indexes real clones)")
@pytest.mark.parametrize("cfg_path,body", _configs())
def test_onboard(cfg_path, body):
    from rw.repo.config import RepoConfig, load_config
    from rw.repo.git import GitRepo
    from rw.repo.index import index_repository
    from rw.repo.investigate import investigate

    path = Path(load_config(cfg_path).path)
    if not path.exists():
        pytest.skip(f"{body['path']} not cloned")
    if body.get("unseen"):
        freeze = ROOT / body.get("core_manifest_file", str(MANIFEST.relative_to(ROOT)))
        assert freeze.exists(), "unseen repo requires its independently recorded core freeze"
        recorded = json.loads(freeze.read_text(encoding="utf-8"))["files"]
        assert core_hashes() == recorded, "core src/rw changed while onboarding an unseen repo"

    name = body["name"]
    fields = {k: v for k, v in body.items() if k != "unseen"}
    fields["path"] = str(path)
    cfg = RepoConfig(**fields)
    revs = list(body["revisions"])
    assert len(revs) >= 2, "config must select at least two revisions"
    g = GitRepo(path)
    shas = {r: g.resolve(r) for r in revs}
    allowed = set(shas.values())
    graph = f"rw_e1_{name.replace('-', '_')}_{uuid.uuid4().hex[:8]}"

    record = {"repo": name, "config_file": cfg_path.relative_to(ROOT).as_posix(),
              "config_fields": sorted(body), "config_field_count": len(body),
              "config_lines": len(cfg_path.read_text(encoding="utf-8").splitlines()),
              "unseen": bool(body.get("unseen")), "revisions": shas, "questions": [],
              # E5 reproducibility keys (tests/repo/test_e5_reproducibility.py)
              "command": "RW_REALREPO=1 .venv/Scripts/python.exe -m pytest -q -m realrepo "
                         "tests/repo/test_e1_onboarding.py",
              "manifest": {"repos": [{"repo": name, "path": body["path"],
                                      "revisions": [{"ref": r, "sha": s} for r, s in shas.items()]}]},
              "config": body, "config_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
              "coverage": {"gaps": [], "limits": {}}, "traces": [], "answers": [],
              "timings": {"questions": []}, "llm_used": False, "scored": False}
    record["core_before"] = core_hashes()
    if body.get("historical_unseen_trial"):
        record["historical_unseen_trial"] = body["historical_unseen_trial"]
    t0 = time.time()
    try:
        report = index_repository(cfg, graph_name=graph)
        record["index"] = {"status": report.status, "seconds": round(time.time() - t0, 2),
                           "commits": report.commits, "tags": report.tags, "blobs": report.blobs,
                           "symbols": report.symbols, "relations": report.relations,
                           "extraction_errors": report.extraction_errors[:200],
                           "coverage_gaps": [{"kind": x.kind, "detail": x.detail}
                                             for x in report.coverage_gaps][:500],
                           "coverage_gap_count": len(report.coverage_gaps)}
        record["timings"]["index_seconds"] = record["index"]["seconds"]
        record["coverage"]["gaps"] = record["index"]["coverage_gaps"]
        try:
            from rw.repo.adapters import ADAPTERS
            record["adapter_limitations"] = {lang: list(getattr(a, "LIMITS", []))
                                             for lang, a in ADAPTERS.items() if lang in cfg.languages}
        except Exception as exc:  # recorded, not fatal
            record["adapter_limitations"] = {"error": repr(exc)}
        record["coverage"]["limits"] = record["adapter_limitations"]
        assert report.status == "COMPLETE"

        first, last = revs[0], revs[-1]

        def ask(rev, q, allowed_shas):
            tq = time.time()
            res = investigate(name, rev, q, graph_name=graph, config=cfg)
            record["timings"]["questions"].append({"revision": rev, "question": q,
                                                   "seconds": round(time.time() - tq, 3)})
            record["traces"].append({"revision": rev, "question": q, **res.to_dict()})
            record["answers"].append({"revision": rev, "question": q, "resolved_sha": res.resolved_sha,
                                      "summaries": [f.summary for f in res.findings],
                                      "unresolved": res.unresolved})
            _check_citations(path, name, res, allowed_shas)
            record["questions"].append({"revision": rev, "question": q, "findings": len(res.findings),
                                        "citations": len(res.citations),
                                        "gaps": sorted({x.kind for x in res.gaps}),
                                        "unresolved": res.unresolved})
            return res

        listing = ask(last, "List symbols", {shas[last]})
        assert listing.findings and not listing.unresolved
        blob = json.dumps(listing.to_dict())
        target = None
        for f in listing.findings:
            for word in f.summary.replace(",", " ").split():
                w = word.strip("`'\"()[]:")
                if "." in w and w.split(".")[-1].isidentifier() and not w.endswith(".py"):
                    target = w
                    break
            if target:
                break
        assert target, f"no qualified symbol in listing: {blob[:500]}"
        record["dependency_target"] = target
        dep = ask(last, f"What does {target} depend on?", {shas[last]})
        assert dep.findings or dep.gaps or dep.unresolved
        ch = ask(last, f"What changed between {first} and {last}?", {shas[first], shas[last]})
        assert ch.findings and not ch.unresolved
        ask(last, "Release notes", {shas[last]})
    finally:
        record["core_after"] = core_hashes()
        record["core_unchanged"] = record["core_before"] == record["core_after"]
        OUT.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%dT%H%M%S")
        (OUT / f"{name}-{ts}.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        try:
            from rw import graph as G
            G.connect().select_graph(graph).delete()
        except Exception:
            pass
