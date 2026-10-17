"""Comparison CLI regression tests: fake provider/test process, real scoring, no network or graph."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_comparison", ROOT / "evals" / "run_comparison.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
MODEL = "groq:comparison-test"


@pytest.fixture
def comparison(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.config, "load_env", lambda: None)
    monkeypatch.setattr(runner.grounding, "has_credentials", lambda model: True)
    monkeypatch.setattr(runner.grounding, "make_transport", lambda model: SimpleNamespace(settings={}))
    cleaned = []

    class Session:
        def __init__(self, graph_name):
            self.g = SimpleNamespace(delete=lambda: cleaned.append(graph_name))

    monkeypatch.setattr(runner, "Session", Session)

    def pytest_process(args, **kwargs):
        directory = Path(args[args.index("--basetemp") + 1])
        directory.mkdir(parents=True)
        (directory / "llm_flat_trial.json").write_text(json.dumps({
            "model": MODEL, "live": True, "snapshot": "snap-001",
            "result": {"fleet": {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                                 "checkout": {"version": "2.1"}}, "disposition": "BOUNDED_PASS"},
            "probe_calls": [], "model_turns": 1
        }))
        junit = args[args.index("--junitxml") + 1]
        Path(junit).write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", pytest_process)
    return tmp_path / "trial", cleaned


def report(outcome, **extra):
    return {"request": runner.REQUEST, "snapshot": "snap-001", "attempts": [{
        "outcome": outcome, "grounding": {"model": MODEL, "live": True, "result": {}}, **extra
    }]}


@pytest.mark.parametrize("failure", ["raised", "outcome", "flag"])
def test_provider_error_never_completes_comparison_even_when_model_matches(comparison, monkeypatch, failure):
    out, cleaned = comparison

    def product(*args, **kwargs):
        if failure == "raised":
            # A successful prefix establishes the same model, but the subsequent call failed.
            transcript = out / "grounding" / "failure.json"
            transcript.write_text(json.dumps({"live": True}))
            error = runner.grounding.GroundingError("HTTP 429 org_FAKE000 SECRET-KEY raw_provider_body")
            error.transcript_path = transcript
            raise error
        return report("PROVIDER_ERROR") if failure == "outcome" else report("BLOCKED", provider_failed=True)

    monkeypatch.setattr(runner, "run_investigation", product)
    assert runner.main(["--runs", "3", "--model", MODEL, "--out", str(out)]) == 1
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["pairs"]) == 1 and len(cleaned) == 1
    assert manifest["pairs"][0]["same_model"] is True
    assert manifest["pairs"][0]["product_completed"] is False
    assert not manifest["requested_pairs_complete"] and not manifest["issue_3_complete"]
    raw = (out / "reports" / "product-1.json").read_text()
    assert all(marker not in raw for marker in ("org_FAKE", "SECRET-KEY", "raw_provider_body"))


def test_honest_blocked_and_needs_evidence_outcomes_can_complete_the_comparison(comparison, monkeypatch):
    out, cleaned = comparison
    outcomes = iter(["BLOCKED", "NEEDS_EVIDENCE", "BOUNDED_PASS"])
    monkeypatch.setattr(runner, "run_investigation", lambda *a, **kw: report(next(outcomes)))
    assert runner.main(["--runs", "3", "--model", MODEL, "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["requested_pairs_complete"] and manifest["issue_3_complete"]
    assert all(p["product_completed"] and p["same_model"] for p in manifest["pairs"])
    assert len(cleaned) == 3


@pytest.mark.parametrize("name", ["releases/cart/CHANGELOG.md", "payloads/record.bin"])
def test_source_inventory_detects_evidence_changes_additions_and_removals(tmp_path, name):
    (tmp_path / "pyproject.toml").write_text("[project]")
    evidence = tmp_path / "fixtures" / "shop" / name
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"original bytes")
    initial = runner.source_hashes(tmp_path)
    key = evidence.relative_to(tmp_path).as_posix()
    assert key in initial
    evidence.write_bytes(b"changed bytes")
    changed = runner.source_hashes(tmp_path)
    assert changed != initial and changed[key] != initial[key]
    evidence.unlink()
    assert runner.source_hashes(tmp_path) != initial
    evidence.write_bytes(b"original bytes")
    assert runner.source_hashes(tmp_path) == initial


def test_source_inventory_excludes_generated_eval_results_but_not_fixture_evidence(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    for name in ("evals/results/generated.json", "fixtures/results/retained.bin", "fixtures/__pycache__/cache.pyc"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
    assert set(runner.source_hashes(tmp_path)) == {"pyproject.toml", "fixtures/results/retained.bin"}
