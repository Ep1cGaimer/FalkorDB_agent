"""No-model smoke uses the live local database; it is part of the non-LLM suite."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
from uuid import uuid4

import pytest

from rw import graph, grounding

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"rw_script_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


investigate = load_script("investigate")
smoke = load_script("smoke")


def test_smoke_matches_independent_expected_dispositions():
    expected = json.loads((ROOT / "evals/expected/dispositions.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in expected["cases"]}
    for id_, snapshot, version, flags, disposition, gaps in smoke.CASES:
        case = by_id[id_]
        assert case["snapshot"] == snapshot
        assert case["fleet"] == {"cart": {"version": version, "flags": flags},
                                  "checkout": {"version": "2.1", "flags": {}}}
        assert case["disposition"] == disposition
        assert {gap["kind"] for gap in case["gaps"]} == gaps


@pytest.mark.parametrize("fail", [False, True], ids=["end-to-end", "cleanup-on-failure"])
def test_smoke_without_model_keys_and_no_graph_left(monkeypatch, capsys, fail):
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(smoke.config, "load_env", lambda: None)

    def no_model(*args, **kwargs):
        pytest.fail("live model must never be called")

    monkeypatch.setattr(grounding, "ground", no_model)
    if fail:
        def broken_checks(client):
            raise RuntimeError("injected smoke failure")
        monkeypatch.setattr(smoke, "run_checks", broken_checks)
    assert smoke.main() == (1 if fail else 0)
    output = capsys.readouterr().out
    name = re.search(r"graph=(rw_smoke_[0-9a-f]{8})", output).group(1)
    assert name not in graph.connect().list_graphs()
    assert f"PASS cleanup graph={name}" in output
    if fail:
        assert "FAIL deterministic-smoke: RuntimeError: injected smoke failure" in output
    else:
        for text in ("PASS snap-001 BLOCKED", "saved-cart-2002 ValueError", "witness:",
                     "blocked approval refused", "PASS snap-001 BOUNDED_PASS",
                     "applied=true, repeat applied=false", "COVERAGE_INCOMPLETE", "WRITER_UNKNOWN",
                     "FORMAT_UNKNOWN", "PASS deterministic-smoke complete"):
            assert text in output


@pytest.mark.parametrize("text, expected", [
    ("cart=1.4", ("cart", "1.4", {})),
    ("cart=1.5:basket_v2=false", ("cart", "1.5", {"basket_v2": False})),
    ("cart=1.5:basket_v2=true,another=false", ("cart", "1.5", {"basket_v2": True, "another": False})),
])
def test_parse_fleet(text, expected):
    assert investigate.parse_fleet(text) == expected


@pytest.mark.parametrize("text", ["cart", "cart=", "cart=1.5:", "cart=1.5:basket_v2=0",
    "cart=1.5:basket_v2=False", "cart=1.5:basket_v2=false,", "cart=1.5:basket_v2=false,basket_v2=true",
    "cart=1.4,checkout=2.1", "=1.4"])
def test_parse_fleet_bad_syntax(text):
    with pytest.raises(argparse.ArgumentTypeError):
        investigate.parse_fleet(text)


def release_rows(g, service):
    return ([{"release_id": "exact-graph-release", "version": "1.5",
              "declared_flags": [{"name": "basket_v2", "default": True}]}]
            if service == "cart" else []), {"truncated": False}


def test_resolve_fleet_exact_artifact(monkeypatch):
    monkeypatch.setattr(graph, "releases_for_service", release_rows)
    proposal = investigate.resolve_fleet(object(), [investigate.parse_fleet("cart=1.5:basket_v2=false")])
    assert proposal.changes[0].release_id == "exact-graph-release"
    assert proposal.changes[0].flags == {"basket_v2": False}


@pytest.mark.parametrize("text, message", [("cart=1.5:unknown=false", "unknown flags"),
    ("cart=9.9", "unknown or ambiguous version"), ("unknown=1.5", "unknown service")])
def test_invalid_operator_fleet_never_verifies(monkeypatch, capsys, text, message):
    monkeypatch.setattr(graph, "releases_for_service", release_rows)

    class UnverifiedSession:
        g = object()
        snapshot_id = "snapshot:snap-001"

        def __init__(self, **kwargs):
            pass

        def plan_from_proposal(self, *args, **kwargs):
            pytest.fail("invalid fleet reached materialization")

        def verify(self, *args, **kwargs):
            pytest.fail("invalid fleet reached verification")

    monkeypatch.setattr(investigate, "Session", UnverifiedSession)
    assert investigate.main(["--fleet", text, "--confirm-as", "tester"]) == 2
    output = capsys.readouterr()
    assert "OPERATOR-SPECIFIED FLEET — no agent involved" in output.out
    assert message in output.err
    assert "nothing verified" in output.err


def test_resolve_fleet_rejects_duplicate_service_and_incomplete_inventory(monkeypatch):
    monkeypatch.setattr(graph, "releases_for_service", release_rows)
    entry = investigate.parse_fleet("cart=1.5")
    with pytest.raises(ValueError, match="duplicate fleet service"):
        investigate.resolve_fleet(object(), [entry, entry])
    monkeypatch.setattr(graph, "releases_for_service", lambda *args: ([], {"truncated": True}))
    with pytest.raises(ValueError, match="truncated"):
        investigate.resolve_fleet(object(), [entry])


@pytest.mark.parametrize("snapshot, fleet, disposition", [
    ("snap-001", "cart=1.4", "BLOCKED"),
    ("snap-002-partial", "cart=1.5:basket_v2=false", "NEEDS_EVIDENCE"),
])
def test_operator_fleet_uses_fixture_origin_and_bypasses_agent(monkeypatch, capsys, tmp_path,
                                                            snapshot, fleet, disposition):
    from rw.pipeline import Session

    name = "rw_test_" + uuid4().hex[:8]
    session = Session(snapshot=snapshot, graph_name=name)
    origins = []
    original_plan = session.plan_from_proposal

    def plan_from_proposal(proposal, request, origin, label):
        origins.append(origin)
        return original_plan(proposal, request, origin=origin, label=label)

    def no_agent(*args, **kwargs):
        pytest.fail("operator fleet invoked the agent path")

    def factory(**kwargs):
        assert kwargs["snapshot"] == snapshot
        return session

    monkeypatch.setattr(session, "plan_from_proposal", plan_from_proposal)
    monkeypatch.setattr(investigate, "Session", factory)
    monkeypatch.setattr(investigate, "run_investigation", no_agent)
    monkeypatch.setattr(grounding, "ground", no_agent)
    saved = []
    monkeypatch.setattr(investigate, "save_report", lambda result: saved.append(result) or tmp_path / "report.json")
    try:
        assert investigate.main(["--fleet", fleet, "--snapshot", snapshot, "--confirm-as", "tester"]) == 0
        output = capsys.readouterr().out
        assert "OPERATOR-SPECIFIED FLEET — no agent involved" in output
        assert f"DISPOSITION: {disposition}" in output
        assert origins == ["fixture"]
        report = saved[0]["attempts"][0]["report"]
        assert report["plan"]["origin"] == "fixture"
        assert report["scope_confirmation"]["confirmed_by"] == "tester"
    finally:
        session.g.delete()
