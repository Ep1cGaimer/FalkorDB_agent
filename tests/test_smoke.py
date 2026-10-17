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


def test_smoke_takes_the_server_address_from_the_environment(monkeypatch):
    """#7d: the smoke run honours RW_FALKORDB_HOST/RW_FALKORDB_PORT, defaulting to loopback."""
    monkeypatch.delenv("RW_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RW_FALKORDB_PORT", raising=False)
    assert smoke.target() == ("127.0.0.1", 6379)
    monkeypatch.setenv("RW_FALKORDB_HOST", "falkor.example")
    monkeypatch.setenv("RW_FALKORDB_PORT", "7001")
    assert smoke.target() == ("falkor.example", 7001)


def test_smoke_connects_to_the_configured_server(monkeypatch, capsys):
    """The configured endpoint is what main() connects to; the connection is refused before any server."""
    monkeypatch.setenv("RW_FALKORDB_HOST", "falkor.example")
    monkeypatch.setenv("RW_FALKORDB_PORT", "7001")
    monkeypatch.setattr(smoke.config, "load_env", lambda: None)
    seen = []

    def refuse(host, port):
        seen.append((host, port))
        raise RuntimeError("stop before the real server")

    monkeypatch.setattr(smoke.graph, "connect", refuse)
    assert smoke.main() == 1
    assert seen == [("falkor.example", 7001)]
    assert "FAIL deterministic-smoke incomplete" in capsys.readouterr().out


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
        # the CLI deletes the session graph in its finally block on every exit path; the factory
        # injects this test's session, so cleanup has already happened by the time we get here
        assert name not in graph.connect().list_graphs()
    finally:
        try:
            session.g.delete()
        except Exception:
            pass  # already deleted by the CLI's cleanup


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "whitespace"])
def test_operator_fleet_without_a_named_operator_never_verifies(monkeypatch, capsys, tmp_path, name):
    """#7d: an empty operator name stops at SCOPE_NOT_CONFIRMED: no prompt, no verify, clean output."""
    from rw.pipeline import Session

    graph_name = "rw_test_" + uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=graph_name)

    def no_prompt(*args, **kwargs):
        pytest.fail("an empty confirmation must not read stdin")

    def no_verify(*args, **kwargs):
        pytest.fail("an unconfirmed scope reached verification")

    monkeypatch.setattr("builtins.input", no_prompt)
    monkeypatch.setattr(session, "verify", no_verify)
    monkeypatch.setattr(investigate, "Session", lambda **kwargs: session)
    saved = []
    monkeypatch.setattr(investigate, "save_report",
                        lambda result: saved.append(result) or tmp_path / "report.json")
    try:
        assert investigate.main(["--fleet", "cart=1.4", "--confirm-as", name]) == 0
        output = capsys.readouterr()
        assert "OPERATOR-SPECIFIED FLEET — no agent involved" in output.out
        assert "SCOPE_NOT_CONFIRMED" in output.out
        assert "DISPOSITION" not in output.out
        assert not output.err
        attempt = saved[0]["attempts"][0]
        assert attempt["outcome"] == "SCOPE_NOT_CONFIRMED"
        assert "report" not in attempt
        assert attempt["plan"]["origin"] == "fixture"
        # the CLI deletes the session graph on every exit path (see test_cli_uses_and_deletes_its_own_graph)
        assert graph_name not in graph.connect().list_graphs()
    finally:
        try:
            session.g.delete()
        except Exception:
            pass  # already deleted by the CLI's cleanup


class FakeFleetEntry:
    changed = True
    service = "cart"
    flags = {"basket_v2": False}
    release_id = "release:cart:x"


class FakePlan:
    label = "stub plan"
    fleet = [FakeFleetEntry()]

    def plan_id(self):
        return "plan-stub"

    def plan_hash(self):
        return "plan-hash-stub"

    def model_dump(self, mode="python", **kwargs):
        return {"label": self.label, "fleet": [], "origin": "stub"}


def test_cli_deletes_the_graph_when_session_construction_fails(monkeypatch, tmp_path):
    """Session construction runs inside the same try/finally as the investigation: a failure during
    the fixture import (after the graph was created on the server) must not leave the rw_cli_ graph
    behind — the finally path deletes it by name through a fresh connection."""

    class StubUUID:
        hex = "0123abcd"

    name = "rw_cli_0123abcd"
    db = graph.connect()
    created = []

    def broken_import(*args, **kwargs):
        db.select_graph(name).query("CREATE (:Release {release_id: 'left-behind-by-injection'})")
        created.append(name in db.list_graphs())
        raise RuntimeError("injected importer failure")

    try:
        monkeypatch.setattr(investigate, "uuid4", lambda: StubUUID())
        monkeypatch.setattr(graph, "reset_and_import", broken_import)
        with pytest.raises(RuntimeError, match="injected importer failure"):
            investigate.main(["--fleet", "cart=1.4", "--confirm-as", "tester"])
        assert created == [True], "the injection must have created the graph before failing"
        assert name not in db.list_graphs()
    finally:
        try:
            db.select_graph(name).delete()
        except Exception:
            pass  # deleted already (fixed behaviour); only the red run leaves it for cleanup


def test_cli_uses_and_deletes_its_own_graph(monkeypatch, capsys, tmp_path):
    """The CLI must create its own rw_cli_<hex8> graph instead of (re)importing the shared evidence
    graph the UI reads, and must delete it in a finally block on every exit path: here the invalid
    plan error path (return 2) and the normal SCOPE_NOT_CONFIRMED flow (return 0)."""

    def run_cli(fail_plan, args, expect_code):
        deletes = []
        graph_names = []

        class FakeGraph:
            def delete(self):
                deletes.append(True)

        class StubSession:
            snapshot_id = "snapshot:snap-001"
            manifest_hash = "sha256:stub"

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.g = FakeGraph()

            def plan_from_proposal(self, *args_, **kwargs_):
                if fail_plan:
                    raise ValueError("injected plan failure")
                return FakePlan(), []

            def verify(self, *args_, **kwargs_):
                pytest.fail("stub session must not verify")

        def factory(**kwargs):
            graph_names.append(kwargs.get("graph_name"))
            return StubSession(**kwargs)

        monkeypatch.setattr(graph, "releases_for_service", release_rows)
        monkeypatch.setattr(investigate, "Session", factory)
        monkeypatch.setattr(investigate, "save_report",
                            lambda result: tmp_path / f"cli-report-{expect_code}.json")
        assert investigate.main(args) == expect_code
        return graph_names, deletes

    # exit path 1: plan materialization fails -> "Fleet error ... nothing verified", cleanup still runs
    names_1, deletes_1 = run_cli(True, ["--fleet", "cart=1.5", "--confirm-as", "tester"], 2)
    assert "Fleet error" in capsys.readouterr().err

    # exit path 2: normal flow ending in SCOPE_NOT_CONFIRMED (return 0), cleanup still runs
    names_2, deletes_2 = run_cli(False, ["--fleet", "cart=1.5", "--confirm-as", " "], 0)
    assert "SCOPE_NOT_CONFIRMED" in capsys.readouterr().out

    for names, deletes, label in ((names_1, deletes_1, "error path"), (names_2, deletes_2, "normal path")):
        assert len(names) == 1 and names[0] is not None, label
        assert re.fullmatch(r"rw_cli_[0-9a-f]{8}", names[0]), (label, names[0])
        assert deletes == [True], f"the CLI graph was not deleted on the {label}"
