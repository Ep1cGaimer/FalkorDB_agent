"""Unit tests for the flat-context LLM control and the control/product scorer.

Offline: a fake transport and the real fixture-local harness (no network, no graph, no database).
Fake transports speak both the Gemini and the OpenAI-compatible (Groq) shapes the product's adapters
handle. One ``@pytest.mark.live`` test runs the control once against the live provider on the product's
``RW_GROUNDING_MODEL`` chain and is skipped without ``GROQ_API_KEY``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


control = _load("llm_control", ROOT / "evals" / "llm_control.py")
scoring = _load("score_controls", ROOT / "evals" / "score_controls.py")


BASE_FIXTURES = scoring.fixture_index()


def route_identity(service, version):
    info = BASE_FIXTURES["by_service_version"].get((service, version))
    return info["routes"][0]["route_id"] if info else "route:unknown"


def key(service, version, record_id):
    return (service, version, route_identity(service, version), "store:cart-cache", record_id)


# --------------------------------------------------------------------------- fakes

def call(name, **args):
    return {"candidates": [{"content": {"role": "model",
                                        "parts": [{"functionCall": {"name": name, "args": args}}]}}]}


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.model_used = "fake-model-1"

    def __call__(self, body):
        self.bodies.append(json.loads(json.dumps(body)))
        if self.responses:
            return self.responses.pop(0)
        return call("run_reader_probe", service="cart", version="1.4",
                    route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-1001")


PROBE_1001 = call("run_reader_probe", service="cart", version="1.4",
                    route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-1001")


def final(fleet, disposition, evidence=None):
    return call("submit_assessment", fleet=fleet, disposition=disposition, evidence=evidence or ["observed"])


# ------------------------------------------------------- OpenAI-compatible (Groq) fakes

GROQ_MODEL = "groq:openai/gpt-oss-120b"


def groq_call(name, call_id="call_1", **args):
    """One Groq/OpenAI-compatible Chat Completions response carrying a single tool call."""
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": "openai/gpt-oss-120b", "choices": [
        {"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


class FakeGroqTransport:
    """Speaks the OpenAI-compatible shape the product's Groq provider renders and parses."""

    provider = "groq"

    def __init__(self, responses, model=GROQ_MODEL):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.model_used = model

    def __call__(self, body):
        self.bodies.append(json.loads(json.dumps(body)))
        if not self.responses:
            raise AssertionError("fake Groq script exhausted")
        return self.responses.pop(0)


@pytest.fixture(scope="module")
def tools():
    return control.FlatControlTools()


@pytest.fixture(scope="module")
def fixtures():
    return scoring.fixture_index()


@pytest.fixture(scope="module")
def manifests():
    return {name: scoring.manifest_index(scoring.FIXTURE_ROOT, name)
            for name in ("snap-001", "snap-002-partial", "snap-003-orphan")}


@pytest.fixture(scope="module")
def oracle_index(fixtures, manifests):
    return scoring.oracle_index(scoring.load_oracle(), fixtures, manifests)


# --------------------------------------------------------------------------- prompt hygiene

def test_system_prompt_hints_nothing():
    prompt = control.SYSTEM_PROMPT
    for hint in ("cart", "checkout", "1.4", "1.5", "2.0", "2.1", "cart/v2", "cart/v1", "basket_v2",
                 "saved-cart", "basket"):
        assert hint not in prompt, f"system prompt leaks {hint!r}"
    # the same safety rules as the product's prompt, and the retained-record warning
    for rule in ("Never invent a hybrid build", "untrusted", "retained records may need checking",
                 "Cite every claim", "call submit_assessment.", "at most 8 turns"):
        assert rule in prompt


def test_flat_context_has_every_file_and_no_payloads():
    context = control.flat_context()
    for service, version in (("cart", "1.4"), ("cart", "1.5"), ("checkout", "2.0"), ("checkout", "2.1")):
        for fname in ("release.json", "CHANGELOG.md", "codec.py"):
            assert f"===== FILE: fixtures/shop/releases/{service}-{version}/{fname} =====" in context
    assert "===== FILE: fixtures/shop/snapshots/snap-001/manifest.json =====" in context
    assert "saved-cart-2002.bin" in context and "sha256:00d293f0" in context  # records + payload_hash
    assert "===== FILE: fixtures/shop/payloads" not in context  # only the probe may read payload bytes
    assert "def read_cart" in context and "Receipt correction" in context


# --------------------------------------------------------------------------- allowlist / probe wiring

def test_dispatch_allowlist_is_exactly_the_declared_tools():
    assert control.TOOLS == ("run_reader_probe", "submit_assessment", "ask_clarification")
    assert set(control._DISPATCH) == {"run_reader_probe"}
    declared = [f["name"] for group in control._declarations() for f in group["functionDeclarations"]]
    assert declared == list(control.TOOLS)
    # the OpenAI-compatible rendering comes from the same neutral spec list
    assert [t["function"]["name"] for t in control._openai_tools()] == list(control.TOOLS)
    assert control._openai_tools()[0]["type"] == "function"
    gemini_params = control._declarations()[0]["functionDeclarations"][1]["parameters"]
    assert gemini_params["properties"]["disposition"]["enum"] == list(control.DISPOSITIONS)
    assert gemini_params["properties"]["fleet"]["items"]["properties"]["service"]["type"] == "STRING"


def test_probe_tool_rejects_everything_not_in_the_fixture(tools):
    with pytest.raises(ValueError):
        tools.run_reader_probe("cart", "9.9", route_identity("cart", "9.9"), "store:cart-cache", "saved-cart-1001")
    with pytest.raises(ValueError):
        tools.run_reader_probe("cart", "1.4", route_identity("cart", "1.4"), "store:cart-cache", "saved-cart-9999")
    with pytest.raises(ValueError):
        tools.run_reader_probe("../etc/passwd", "1.4", route_identity("../etc/passwd", "1.4"), "store:cart-cache", "saved-cart-1001")
    with pytest.raises(ValueError):
        tools.run_reader_probe("cart", "1.4", route_identity("cart", "1.4"), "store:cart-cache", "saved-cart-1001; rm -rf /")
    with pytest.raises(ValueError):
        tools.run_reader_probe(None, "1.4", route_identity(None, "1.4"), "store:cart-cache", "saved-cart-1001")


def test_probe_tool_result_shape_and_mapping(tools):
    passed = tools.run_reader_probe("cart", "1.5", route_identity("cart", "1.5"), "store:cart-cache", "saved-cart-2002")
    assert passed == {"status": "PASS", "error_type": None, "message": None}
    failed = tools.run_reader_probe("cart", "1.4", route_identity("cart", "1.4"), "store:cart-cache", "saved-cart-2002")
    assert failed["status"] == "FAIL" and failed["error_type"] == "ValueError"
    assert "cart/v2" in failed["message"]
    assert tools.run_reader_probe("checkout", "2.1", route_identity("checkout", "2.1"), "store:cart-cache", "saved-cart-1001")["status"] == "PASS"


def _direct_harness(harness, codec, entry, payload):
    """Run the trusted harness by hand, the way the sanctioned caller does: fresh nonce in env."""
    nonce = secrets.token_hex(16)
    env = {"RW_PROBE_NONCE": nonce,
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PATH": os.environ.get("PATH", "")}
    proc = subprocess.run([sys.executable, "-I", str(harness), str(codec), entry], input=payload,
                          capture_output=True, timeout=30, env=env)
    data = json.loads(proc.stdout)
    assert data["nonce"] == nonce  # the returned line carries this run's nonce
    return proc, data


def test_probe_matches_a_direct_harness_run(tools):
    """Independent expected outcome: the same harness invocation run by hand, outside the control."""
    harness = control.HARNESS_PATH
    codec = scoring.FIXTURE_ROOT / "releases" / "cart-1.4" / "codec.py"
    payload = (scoring.FIXTURE_ROOT / "payloads" / "saved-cart-2002.bin").read_bytes()
    proc, direct = _direct_harness(harness, codec, "read_cart", payload)
    assert proc.returncode == 10 and direct["status"] == "FAIL" and direct["error_type"] == "ValueError"
    got = tools.run_reader_probe("cart", "1.4", route_identity("cart", "1.4"), "store:cart-cache", "saved-cart-2002")
    assert (got["status"], got["error_type"], got["message"]) == ("FAIL", direct["error_type"], direct["message"])
    # and the newer reader passes on the same bytes (also checked by hand)
    codec_new = scoring.FIXTURE_ROOT / "releases" / "cart-1.5" / "codec.py"
    proc_new, direct_new = _direct_harness(harness, codec_new, "read_cart", payload)
    assert proc_new.returncode == 0 and direct_new["status"] == "PASS"


def test_extra_args_never_reach_the_tool_and_unknown_tools_error(tmp_path):
    transport = ScriptedTransport([
        call("run_reader_probe", service="cart", version="1.4",
                    route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-1001",
             snapshot_id="evil", graph="other", entry="os.system"),
        call("delete_everything", target="graph"),
        final([{"service": "cart", "version": "1.4"}], "BLOCKED"),
    ])
    transcript, path = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transcript["result"]["disposition"] == "BLOCKED"
    first = transport.bodies[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert first == {"status": "PASS", "error_type": None, "message": None}  # extra args ignored
    assert transcript["probe_calls"][0]["result"]["status"] == "PASS"
    unknown = [c for c in transcript["tool_calls"] if c.get("error") == "unknown tool"]
    assert unknown and unknown[0]["name"] == "delete_everything"
    assert [c["name"] for c in transcript["tool_calls"]] == ["run_reader_probe", "delete_everything"]


# --------------------------------------------------------------------------- loop behaviour

def test_transcript_is_saved_and_labeled(tmp_path):
    transport = ScriptedTransport([
        PROBE_1001,
        call("run_reader_probe", service="checkout", version="2.1",
                    route_id=route_identity("checkout", "2.1"), store_id="store:cart-cache",
                    record_id="saved-cart-2002"),
        final({"cart": {"version": "1.5", "flags": {"basket_v2": False}},
               "checkout": {"version": "2.1", "flags": {}}}, "BOUNDED_PASS",
              ["cart 1.5 read cart/v2", "checkout 2.1 read cart/v2"]),
    ])
    transcript, path = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert path is not None and path.parent == tmp_path
    assert path.name.startswith("llm_flat_") and path.suffix == ".json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["model"] == "fake-model-1" and saved["live"] is True
    assert saved["control"] == "flat_context_no_graph" and saved["temperature"] == 0
    assert saved["max_turns"] == control.MAX_TURNS
    assert saved["model_turns"] == len(transport.bodies) == 3
    assert saved["aborted"] is False and saved["saved_at"]
    assert [c["name"] for c in saved["tool_calls"]] == ["run_reader_probe", "run_reader_probe"]
    assert saved["tool_calls"][0]["args"]["record_id"] == "saved-cart-1001"
    assert len(saved["context_files"]) == 13 and saved["context_files"][0]["sha256"].startswith("sha256:")
    assert saved["result"]["fleet"] == {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                                        "checkout": {"version": "2.1", "flags": {}}}
    assert saved["system_prompt"] == control.SYSTEM_PROMPT
    request_text = transport.bodies[0]["contents"][0]["parts"][0]["text"]
    assert request_text.startswith(f"Rollback request: {control.REQUEST}")
    assert "===== FILE: fixtures/shop/snapshots/snap-001/manifest.json =====" in request_text


def test_turn_cap_aborts_without_an_answer(tmp_path):
    transport = ScriptedTransport([PROBE_1001] * 20)
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert len(transport.bodies) == control.MAX_TURNS == 8
    assert transcript["aborted"] and transcript["result"] is None
    assert any("CONTROL_ABORTED" in e for e in transcript["validation_errors"])
    assert len(transcript["probe_calls"]) == control.MAX_TURNS


def test_text_only_turn_is_nudged(tmp_path):
    text_only = {"candidates": [{"content": {"parts": [{"text": "I think cart 1.4 is fine"}]}}]}
    transport = ScriptedTransport([text_only, final([{"service": "cart", "version": "1.5"}], "BOUNDED_PASS")])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transcript["model_turns"] == 2 and not transcript["aborted"]
    assert transport.bodies[1]["contents"][-1]["parts"][0]["text"] == "Respond only by calling a tool."


def test_unusable_terminal_calls_are_reported_back_to_the_model(tmp_path):
    transport = ScriptedTransport([
        final([{"service": "cart", "version": "9.9"}], "BOUNDED_PASS"),
        final([{"service": "cart", "version": "1.4", "flags": {"made_up": True}}], "BLOCKED"),
        final([{"service": "cart", "version": "1.4"}], "disposition=BLOCKED"),
        final([{"service": "cart", "version": "1.4"}], "BLOCKED", evidence=[1, 2]),
        final([{"service": "cart", "version": "1.4"}], "BLOCKED"),
    ])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    errors = [transport.bodies[i]["contents"][-1]["parts"][0]["functionResponse"]["response"].get("error")
              for i in (1, 2, 3, 4)]
    assert "unknown release cart 9.9" in errors[0]
    assert "not declared" in errors[1]
    assert "disposition must be one of" in errors[2]
    assert "evidence must be a list" in errors[3]
    assert transcript["result"]["disposition"] == "BLOCKED"
    assert transcript["model_turns"] == 5


def test_submit_assessment_completes_unlisted_services_from_the_snapshot(tmp_path):
    transport = ScriptedTransport([final([{"service": "cart", "version": "1.4"}], "BLOCKED")])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    result = transcript["result"]
    assert result["fleet"] == {"cart": {"version": "1.4", "flags": {}},
                               "checkout": {"version": "2.1", "flags": {}}}
    assert result["completed_services"] == ["checkout"]


def test_extra_terminal_keys_are_kept_verbatim(tmp_path):
    transport = ScriptedTransport([call("submit_assessment", fleet=[{"service": "cart", "version": "1.4"}],
                                        disposition="BLOCKED", evidence=["no probe ran"],
                                        unresolved=["scope of 'the basket rollout'"])])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transcript["result"]["extra_keys"] == {"unresolved": ["scope of 'the basket rollout'"]}


def test_normalize_fleet_accepts_map_and_entry_list(tools):
    as_map = {"cart": {"version": "1.5", "flags": {"basket_v2": False}}, "checkout": {"version": "2.1"}}
    as_list = [{"service": "cart", "version": "1.5", "flags": [{"name": "basket_v2", "enabled": False}]},
               {"service": "checkout", "version": "2.1", "flags": {}}]
    want = {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
            "checkout": {"version": "2.1", "flags": {}}}
    assert tools.normalize_fleet(as_map)[0] == want
    assert tools.normalize_fleet(as_list)[0] == want


# ------------------------------------------------------- product chain + OpenAI-compatible provider

def test_groq_control_round_trip_to_a_scored_answer(tmp_path):
    """The control runs on the product's Groq provider: OpenAI-format tool call, terminal answer."""
    transport = FakeGroqTransport([
        groq_call("run_reader_probe", call_id="c1", service="cart", version="1.4",
                  route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-2002"),
        groq_call("submit_assessment", call_id="c2", fleet=[{"service": "cart", "version": "1.4"}],
                  disposition="BLOCKED", evidence=["probe on saved-cart-2002 FAIL (ValueError)"]),
    ])
    transcript, path = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transcript["provider"] == "groq" and transcript["model"] == GROQ_MODEL
    assert transcript["aborted"] is False and transcript["model_turns"] == 2
    assert transcript["result"]["disposition"] == "BLOCKED"
    assert transcript["result"]["fleet"] == {"cart": {"version": "1.4", "flags": {}},
                                             "checkout": {"version": "2.1", "flags": {}}}
    first = transport.bodies[0]
    assert first["messages"][0] == {"role": "system", "content": control.SYSTEM_PROMPT}
    assert first["tool_choice"] == "required" and first["temperature"] == 0
    assert [t["function"]["name"] for t in first["tools"]] == list(control.TOOLS)
    # the probe reply binds to the model's own tool_call_id and carries the observed FAIL
    replies = [m for m in transport.bodies[1]["messages"] if m.get("role") == "tool"]
    assert replies[-1]["tool_call_id"] == "c1"
    assert json.loads(replies[-1]["content"])["status"] == "FAIL"
    assert transcript["probe_calls"][0]["result"]["error_type"] == "ValueError"
    assert [c["name"] for c in transcript["tool_calls"]] == ["run_reader_probe"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["provider"] == "groq" and saved["model"] == GROQ_MODEL
    assert saved["system_prompt"] == control.SYSTEM_PROMPT  # the control's prompt, not the product's


def test_groq_control_unknown_tool_and_text_nudge(tmp_path):
    text_only = {"choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": "cart 1.4 looks fine"}}]}
    transport = FakeGroqTransport([
        text_only,
        groq_call("delete_everything", call_id="c1", graph="other"),
        groq_call("submit_assessment", call_id="c2", fleet=[{"service": "cart", "version": "1.4"}],
                  disposition="BLOCKED", evidence=["no probe ran"]),
    ])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transport.bodies[1]["messages"][-1] == {"role": "user", "content": "Respond only by calling a tool."}
    assert json.loads(transport.bodies[2]["messages"][-1]["content"])["error"].startswith("unknown tool")
    assert [c["name"] for c in transcript["tool_calls"]] == ["delete_everything"]
    assert transcript["result"]["disposition"] == "BLOCKED"


def test_control_chain_restarts_with_the_next_model(tmp_path, monkeypatch):
    from rw import grounding

    made, bodies = [], {}

    def make_transport(spec):
        made.append(spec)
        n = []

        def tr(body):
            bodies.setdefault(spec, []).append(body)
            n.append(1)
            if spec == "groq:m1" and len(n) == 2:  # fails mid-conversation, after one successful turn
                raise grounding.GroundingError("groq:m1 request failed after 6 attempts; last error: HTTP 503")
            if spec == "groq:m1" or len(n) == 1:
                return groq_call("run_reader_probe", call_id=f"{spec}-{len(n)}", service="cart",
                                 version="1.4",
                    route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-1001")
            return groq_call("submit_assessment", call_id="m2-2", fleet=[{"service": "cart", "version": "1.4"}],
                             disposition="BLOCKED", evidence=["probe PASS"])
        tr.model_used, tr.provider = spec, "groq"
        return tr

    monkeypatch.setattr(grounding, "make_transport", make_transport)
    transcript, _ = control.run_control(artifact_dir=tmp_path, models=["groq:m1", "groq:m2"])
    assert made == ["groq:m1", "groq:m2"] and transcript["model"] == "groq:m2"
    # m2 started from turn 0: system + user only, none of m1's history
    assert [m["role"] for m in bodies["groq:m2"][0]["messages"]] == ["system", "user"]
    assert transcript["abandoned"][0]["model"] == "groq:m1"
    assert transcript["abandoned"][0]["error"]["status"] == 503
    assert transcript["result"]["disposition"] == "BLOCKED"


def test_control_reports_all_models_failing(tmp_path, monkeypatch):
    from rw import grounding

    def make_transport(spec):
        def tr(body):
            raise grounding.GroundingError(f"{spec} down")
        tr.model_used, tr.provider = spec, "groq"
        return tr

    monkeypatch.setattr(grounding, "make_transport", make_transport)
    with pytest.raises(grounding.GroundingError, match="groq:m1.*groq:m2"):
        control.run_control(artifact_dir=tmp_path, models=["groq:m1", "groq:m2"])
    saved = list(tmp_path.glob("llm_flat_*.json"))
    assert len(saved) == 1
    failed = json.loads(saved[0].read_text())
    assert failed["aborted"] and failed["result"] is None and failed["partial_evidence_unavailable"]
    assert [attempt["model"] for attempt in failed["abandoned"]] == ["groq:m1", "groq:m2"]
    fixtures = scoring.fixture_index()
    snapshot = scoring.manifest_index()
    assert scoring.run_from_control(failed, fixtures, snapshot)["aborted"]


def test_control_uses_the_same_bounded_rejection_correction(tmp_path):
    from rw import grounding
    bodies = []

    def transport(body):
        bodies.append(body)
        if len(bodies) == 1:
            raise grounding.ToolCallRejected({"code": "tool_use_failed", "failed_generation": "untrusted text"})
        return groq_call("submit_assessment", fleet={"cart": {"version": "1.4"}, "checkout": {"version": "2.1"}},
                         disposition="NEEDS_EVIDENCE", evidence=["Readers not checked"])

    transport.provider, transport.model_used = "groq", GROQ_MODEL
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert not transcript["aborted"] and transcript["model_turns"] == 2
    assert transcript["probe_calls"] == [] and transcript["events"][0]["type"] == "model_error"
    correction = bodies[1]["messages"][-1]["content"]
    assert "submit_assessment" in correction and "run_reader_probe" in correction
    assert "propose_fleet" not in correction and "untrusted text" not in correction


def test_cli_loads_env_before_selecting_models(tmp_path, monkeypatch):
    from rw import config, grounding
    seen = []
    monkeypatch.delenv("RW_GROUNDING_MODEL", raising=False)

    def load_env():
        seen.append("load_env")
        monkeypatch.setenv("RW_GROUNDING_MODEL", "groq:configured-in-dotenv")

    def run_control(*args, **kwargs):
        seen.append("run_control")
        assert kwargs["models"] == ["groq:configured-in-dotenv"]
        return {"model": kwargs["models"][0], "model_turns": 1, "tool_call_count": 0, "probe_calls": [],
                "aborted": False, "result": {"fleet": {}, "disposition": "NEEDS_EVIDENCE", "evidence": [],
                                              "validation_errors": []}}, tmp_path / "transcript.json"

    monkeypatch.setattr(config, "load_env", load_env)
    monkeypatch.setattr(control, "run_control", run_control)
    assert control.main([]) == 0
    assert seen == ["load_env", "run_control"]


def test_product_turn_counts_include_rejected_generations(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps({"events": [{"type": "model_error"}, {"type": "model"}, {"type": "tool"}]}))
    assert scoring._turns_from_grounding_transcript(str(path)) == 2


@pytest.mark.parametrize("fallback", [False, True])
def test_control_failure_and_fallback_artifacts_never_save_raw_provider_errors(tmp_path, monkeypatch, fallback):
    from rw import grounding
    private = "org_FAKE000 SECRET-KEY raw_provider_body"

    def factory(model):
        calls = []

        def transport(body):
            calls.append(body)
            if model == "groq:good":
                return groq_call("submit_assessment", fleet={"cart": {"version": "1.4"},
                                                              "checkout": {"version": "2.1"}},
                                 disposition="NEEDS_EVIDENCE", evidence=["Not fully checked"])
            if len(calls) == 1:
                return groq_call("run_reader_probe", service="cart", version="1.4",
                    route_id=route_identity("cart", "1.4"), store_id="store:cart-cache",
                    record_id="saved-cart-1001")
            if len(calls) == 2:
                raise grounding.ToolCallRejected({"message": private, "failed_generation": private})
            raise grounding.GroundingError("HTTP 429: " + private)

        transport.provider, transport.model_used = "groq", model
        return transport

    monkeypatch.setattr(grounding, "make_transport", factory)
    models = ["groq:bad", "groq:good"] if fallback else ["groq:bad"]
    if fallback:
        _, path = control.run_control(models=models, artifact_dir=tmp_path)
    else:
        with pytest.raises(grounding.GroundingError) as error:
            control.run_control(models=models, artifact_dir=tmp_path)
        assert "org_FAKE" not in str(error.value) and "SECRET-KEY" not in str(error.value)
        path = next(tmp_path.glob("llm_flat_*.json"))
    raw = path.read_text()
    assert all(marker not in raw for marker in ("org_FAKE", "SECRET-KEY", "raw_provider_body", "failed_generation"))
    failed = json.loads(raw)["abandoned"][0]
    assert failed["error"] == {"status": 429, "code": "rate_limited", "message": "Provider rate limit reached."}
    assert any(e["type"] == "model_error" for e in failed["events"])


# --------------------------------------------------------------------------- scoring math

def test_canonical_fleet_fills_declared_defaults_and_matches_cases(fixtures, manifests, oracle_index):
    fleet, notes = scoring.canonical_fleet({"cart": {"version": "1.5", "flags": {}},
                                            "checkout": {"version": "2.1", "flags": {}}},
                                           fixtures, manifests["snap-001"])
    assert fleet["cart"]["flags"] == {"basket_v2": True} and notes == []
    case = oracle_index["by_fleet"][("snap-001", scoring.fleet_key(fleet))]
    assert case["id"] == "D"
    fleet_b, _ = scoring.canonical_fleet({"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                                          "checkout": {"version": "2.1", "flags": {}}},
                                         fixtures, manifests["snap-001"])
    assert oracle_index["by_fleet"][("snap-001", scoring.fleet_key(fleet_b))]["id"] == "B"
    fleet_a, _ = scoring.canonical_fleet({"cart": {"version": "1.4"}, "checkout": {"version": "2.1"}},
                                         fixtures, manifests["snap-001"])
    assert oracle_index["by_fleet"][("snap-001", scoring.fleet_key(fleet_a))]["id"] == "A"


def test_release_and_manifest_index_are_fixture_derived(fixtures, manifests):
    ids = {info["release_id"] for info in fixtures["by_release_id"].values()}
    assert len(ids) == 4 and all(i.startswith("release:") for i in ids)
    records = manifests["snap-001"]["stores"]["cart-cache"]["records"]
    assert set(records) == {"saved-cart-1001", "saved-cart-2002"}
    assert records["saved-cart-2002"]["format"] == "cart/v2"
    assert records["saved-cart-1001"]["writer"] == "1.4"
    assert manifests["snap-001"]["stores"]["cart-cache"]["coverage"] == "COMPLETE"


def test_reader_obligations_and_derived_disposition(fixtures, manifests, oracle_index):
    fleet_a = {"cart": {"version": "1.4", "flags": {}}, "checkout": {"version": "2.1", "flags": {}}}
    pairs, gaps = scoring.reader_obligations(fixtures, manifests["snap-001"], fleet_a)
    assert pairs == {key("cart", "1.4", "saved-cart-1001"): True, key("cart", "1.4", "saved-cart-2002"): True,
                     key("checkout", "2.1", "saved-cart-1001"): True, key("checkout", "2.1", "saved-cart-2002"): True}
    assert gaps == []
    disposition, source = scoring.derived_disposition(pairs, oracle_index["predictions"], gaps)
    assert disposition == "BLOCKED" and "1 predicted FAIL" in source
    fleet_b = {"cart": {"version": "1.5", "flags": {"basket_v2": False}}, "checkout": {"version": "2.1", "flags": {}}}
    pairs_b, gaps_b = scoring.reader_obligations(fixtures, manifests["snap-001"], fleet_b)
    assert scoring.derived_disposition(pairs_b, oracle_index["predictions"], gaps_b)[0] == "BOUNDED_PASS"
    pairs_g, gaps_g = scoring.reader_obligations(fixtures, manifests["snap-003-orphan"], fleet_b)
    assert {g["kind"] for g in gaps_g} == {"WRITER_UNKNOWN", "FORMAT_UNKNOWN"}
    assert key("cart", "1.5", "saved-cart-3003") in pairs_g
    assert scoring.derived_disposition(pairs_g, oracle_index["predictions"], gaps_g, "snap-003-orphan")[0] == "NEEDS_EVIDENCE"


def _run(**kw):
    base = {"label": "hand-made", "origin": "control", "model": "fake", "live": True, "snapshot": "snap-001",
            "fleet": {"cart": {"version": "1.4", "flags": {}}, "checkout": {"version": "2.1", "flags": {}}},
            "fleet_notes": [], "disposition": "BLOCKED", "probed": {}, "model_turns": 3, "tool_calls": 3,
            "aborted": False}
    base.update(kw)
    return base


def test_score_run_rewards_exact_obligation_recall(fixtures, manifests, oracle_index):
    run = _run(probed={key("cart", "1.4", "saved-cart-1001"): "PASS", key("cart", "1.4", "saved-cart-2002"): "FAIL",
                       key("checkout", "2.1", "saved-cart-1001"): "PASS", key("checkout", "2.1", "saved-cart-2002"): "PASS"})
    row = scoring.score_run(run, oracle_index, fixtures, manifests)
    assert row["case"] == "A" and row["receipt_kept"] is True and row["recall"] == "4/4"
    assert row["critical_probed"] is True and row["false_pass"] is False and row["disp_match"] is True
    assert row["observed_fails"] == 1 and row["other_fails"] == 0
    assert row["expected_disposition"] == "BLOCKED"
    assert scoring.consistent(row)

    partial = scoring.score_run(_run(disposition="BLOCKED",
                                     probed={key("cart", "1.4", "saved-cart-1001"): "PASS",
                                             key("cart", "1.5", "saved-cart-2002"): "PASS"}),  # wrong version
                                oracle_index, fixtures, manifests)
    assert partial["recall"] == "1/4" and partial["critical_probed"] is False
    assert not scoring.consistent(partial)  # right disposition, but no evidence for the fleet's obligations
    assert any("never probed" in n for n in partial["notes"])


def test_false_bounded_pass_is_detected(fixtures, manifests, oracle_index):
    run = _run(disposition="BOUNDED_PASS", probed={key("cart", "1.4", "saved-cart-1001"): "PASS"})
    row = scoring.score_run(run, oracle_index, fixtures, manifests)
    assert row["false_pass"] is True and row["disp_match"] is False and row["critical_probed"] is False
    assert any("never probed" in n for n in row["notes"])


def test_case_b_pass_is_not_false(fixtures, manifests, oracle_index):
    fleet = {"cart": {"version": "1.5", "flags": {"basket_v2": False}}, "checkout": {"version": "2.1", "flags": {}}}
    run = _run(fleet=fleet, disposition="BOUNDED_PASS",
               probed={key("cart", "1.5", "saved-cart-1001"): "PASS", key("cart", "1.5", "saved-cart-2002"): "PASS",
                       key("checkout", "2.1", "saved-cart-1001"): "PASS", key("checkout", "2.1", "saved-cart-2002"): "PASS"})
    row = scoring.score_run(run, oracle_index, fixtures, manifests)
    assert row["case"] == "B" and row["false_pass"] is False and row["disp_match"] is True
    assert row["receipt_kept"] is True and row["critical_probed"] is True and scoring.consistent(row)


def test_unmapped_fleet_uses_a_derived_expectation(fixtures, manifests, oracle_index):
    fleet = {"cart": {"version": "1.4", "flags": {}}, "checkout": {"version": "2.0", "flags": {}}}  # oracle case C
    row = scoring.score_run(_run(fleet=fleet, disposition="BOUNDED_PASS"), oracle_index, fixtures, manifests)
    assert row["case"] == "C" and row["false_pass"] is True
    odd = scoring.score_run(_run(fleet={"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                                        "checkout": {"version": "2.0", "flags": {}}},
                                 disposition="BOUNDED_PASS"), oracle_index, fixtures, manifests)
    assert odd["case"] == "H" and odd["disp_match"] is False
    unmapped = scoring.score_run(_run(fleet={"cart": {"version": "1.4", "flags": {}}}),
                                 oracle_index, fixtures, manifests)
    assert unmapped["case"] == "—" and unmapped["expected_source"].startswith("derived")
    assert "no oracle case for this fleet" in " ".join(unmapped["notes"])


def test_control_transcript_is_scored_end_to_end(fixtures, manifests, oracle_index):
    transcript = {
        "_path": str(Path("artifacts/controls/llm_flat_20261015T101112123456Z.json")),
        "model": "gemini-3.1-flash-lite", "live": True, "snapshot": "snap-001", "aborted": False,
        "model_turns": 4, "tool_call_count": 3,
        "result": {"fleet": {"cart": {"version": "1.5", "flags": {"basket_v2": False}},
                             "checkout": {"version": "2.1", "flags": {}}},
                   "disposition": "BOUNDED_PASS"},
        "probe_calls": [
            {"service": "cart", "version": "1.5", "record_id": "saved-cart-1001",
             "result": {"status": "PASS"}},
            {"service": "cart", "version": "1.5", "record_id": "saved-cart-2002",
             "result": {"status": "PASS"}},
            {"service": "checkout", "version": "2.1", "record_id": "saved-cart-9999",
             "result": None, "error": "unknown record_id"},
        ],
    }
    row = scoring.score_run(scoring.run_from_control(transcript, fixtures, manifests["snap-001"]),
                            oracle_index, fixtures, manifests)
    assert row["run"] == "flat_control 10-15 10:11:12" and row["case"] == "B"
    assert row["recall"] == "2/4" and row["critical_probed"] is True
    assert row["disposition"] == "BOUNDED_PASS" and row["false_pass"] is False and row["disp_match"] is True
    assert row["turns"] == 4 and row["tool_calls"] == 3
    assert not scoring.consistent(row)  # right answer, but the checkout probes were never executed

def test_aborted_control_run_is_scored_honestly(fixtures, manifests, oracle_index):
    transcript = {"_path": "llm_flat_20261015T000000000000Z.json", "model": "m", "live": True,
                  "snapshot": "snap-001", "aborted": True, "result": None, "model_turns": 8,
                  "tool_call_count": 2, "probe_calls": []}
    row = scoring.score_run(scoring.run_from_control(transcript, fixtures, manifests["snap-001"]),
                            oracle_index, fixtures, manifests)
    assert row["disposition"] == "ABORTED" and row["false_pass"] is None and row["recall"] == "—"


def test_product_report_with_a_plan_resolves_release_ids_and_receipts(fixtures, manifests, oracle_index):
    """The product path: a saved report's ``plan.fleet`` release ids resolve to versions and the
    ``verification`` obligations/receipts give the full probed identities — no live graph required."""
    cart_14 = fixtures["by_service_version"][("cart", "1.4")]["release_id"]
    checkout_21 = fixtures["by_service_version"][("checkout", "2.1")]["release_id"]

    from rw.contracts import h

    obs, receipts = [], []
    for service, release_id, record_id, result in (
        ("cart", cart_14, "saved-cart-1001", "PASS"),
        ("cart", cart_14, "saved-cart-2002", "FAIL"),
        ("checkout", checkout_21, "saved-cart-1001", "PASS"),
        ("checkout", checkout_21, "saved-cart-2002", "PASS"),
    ):
        tup = {"service": service, "release_id": release_id, "record_id": record_id,
               "route_id": f"route:{release_id}:" + ("load_saved_cart" if service == "cart" else "price_saved_cart"),
               "store_id": "store:cart-cache",
               "format_id": "cart/v1" if record_id.endswith("1001") else "cart/v2"}
        ob_hash = h(tup)  # a saved obligation's hash is the canonical hash of its tuple
        obs.append({"obligation_hash": ob_hash, "writer_release_id": None, "witness_path": [],
                    "tuple": tup})
        # A saved ProbeReceipt carries the exact obligation tuple it was run on.
        receipts.append({"obligation_hash": ob_hash, "tuple": dict(obs[-1]["tuple"]), "result": result,
                         "error_type": "ValueError" if result == "FAIL" else None})

    report = {
        "_path": "artifacts/reports/deadbeefdeadbeef.json",
        "request": "Undo the basket rollout, but keep the receipt correction.",
        "snapshot": "snapshot:snap-001",
        "attempts": [
            {"grounding": {"model": "gemini-3.1-flash-lite", "live": True, "tool_calls": [],
                           "result": {"kind": "CLARIFICATION"}},
             "transcript": None, "outcome": "CLARIFICATION"},
            {"grounding": {"model": "gemini-3.1-flash-lite", "live": True,
                           "tool_calls": [{"name": "run_reader_probe"}] * 4,
                           "result": {"kind": "PLAN"}},
             "transcript": None, "outcome": "BLOCKED",
             "report": {
                 "plan": {"fleet": [
                     {"service": "cart", "release_id": cart_14, "flags": {}, "changed": True},
                     {"service": "checkout", "release_id": checkout_21, "flags": {}, "changed": False}]},
                 "verification": {"disposition": "BLOCKED", "obligations": obs, "receipts": receipts,
                                  "blocking_receipts": ["ob:cart:saved-cart-2002"], "gaps": []}}},
        ],
    }
    runs = scoring.runs_from_report(report, fixtures, manifests["snap-001"])
    assert [r["label"] for r in runs] == ["product deadbeefdead#1", "product deadbeefdead#2"]
    assert runs[0]["disposition"] is None and runs[0]["aborted"] and runs[0]["clarification"]
    assert runs[0]["probed"] == {}
    assert runs[1]["fleet"] == {"cart": {"version": "1.4", "flags": {}},
                                "checkout": {"version": "2.1", "flags": {}}}
    assert runs[1]["probed"] == {key("cart", "1.4", "saved-cart-1001"): "PASS",
                                 key("cart", "1.4", "saved-cart-2002"): "FAIL",
                                 key("checkout", "2.1", "saved-cart-1001"): "PASS",
                                 key("checkout", "2.1", "saved-cart-2002"): "PASS"}
    assert runs[1]["tool_calls"] == 4 and runs[1]["model_turns"] is None  # no grounding transcript path

    row = scoring.score_run(runs[1], oracle_index, fixtures, manifests)
    assert row["case"] == "A" and row["recall"] == "4/4" and row["receipt_kept"] is True
    assert row["critical_probed"] is True and row["false_pass"] is False
    assert row["disp_match"] is True and row["expected_source"] == "oracle case A"
    assert row["observed_fails"] == 1 and scoring.consistent(row)
    assert "4/4 (1 FAIL on the proposed fleet)" in scoring.markdown_row(row)


def test_fails_are_split_between_the_proposed_fleet_and_other_readers(fixtures, manifests, oracle_index):
    """A FAIL observed on a reader the proposal does not include must not be attributed to it."""
    fleet = {"cart": {"version": "1.5", "flags": {"basket_v2": False}}, "checkout": {"version": "2.1", "flags": {}}}
    run = _run(fleet=fleet, disposition="BLOCKED",
               probed={key("cart", "1.5", "saved-cart-1001"): "PASS", key("cart", "1.5", "saved-cart-2002"): "PASS",
                       key("checkout", "2.1", "saved-cart-1001"): "PASS", key("checkout", "2.1", "saved-cart-2002"): "PASS",
                       key("cart", "1.4", "saved-cart-2002"): "FAIL"})  # the rejected alternative
    row = scoring.score_run(run, oracle_index, fixtures, manifests)
    assert row["observed_fails"] == 0 and row["other_fails"] == 1
    assert row["false_pass"] is False and row["disp_match"] is False  # claims BLOCKED for a passing fleet
    table = scoring.markdown_table([row])
    assert "4/4 [1 FAIL on other readers]" in table and "proposed fleet)" not in table


def test_markdown_table_and_verdict(fixtures, manifests, oracle_index):
    full = {key("cart", "1.4", "saved-cart-1001"): "PASS", key("cart", "1.4", "saved-cart-2002"): "FAIL",
            key("checkout", "2.1", "saved-cart-1001"): "PASS", key("checkout", "2.1", "saved-cart-2002"): "PASS"}
    good = scoring.score_run(_run(probed=full), oracle_index, fixtures, manifests)
    table = scoring.markdown_table([good])
    assert table.count("\n") == 2 and "probe recall" in table and "| A |" in table
    assert "4/4 (1 FAIL on the proposed fleet)" in table
    assert scoring.consistent(good)
    assert scoring.verdict([good], [good]).startswith("TIED")
    assert scoring.verdict([good], []).startswith("control only")
    assert scoring.verdict([good], [dict(good, case="—")]).startswith("CONTROL WINS")
    assert scoring.verdict([], [good]).startswith("no control run scored")
    narrow = scoring.score_run(_run(probed={key("cart", "1.5", "saved-cart-2002"): "PASS"}),
                               oracle_index, fixtures, manifests)
    assert scoring.verdict([narrow], [good]).startswith("product ahead")
    unsafe = scoring.score_run(_run(disposition="BOUNDED_PASS",
                                    probed={key("cart", "1.4", "saved-cart-2002"): "FAIL"}),
                               oracle_index, fixtures, manifests)
    line = scoring.verdict([unsafe], [good])
    assert "false BOUNDED_PASS: control 1/1, product 0/1" in line


def test_collect_reads_saved_files(tmp_path, fixtures):
    controls = tmp_path / "controls"
    controls.mkdir()
    (controls / "llm_flat_20261015T101112000000Z.json").write_text(json.dumps({
        "model": "m", "live": True, "snapshot": "snap-001", "aborted": True, "result": None,
        "model_turns": 8, "tool_call_count": 0, "probe_calls": []}), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "abc.json").write_text(json.dumps({"request": "r", "snapshot": "snapshot:snap-001",
                                                  "attempts": [{"outcome": "BLOCKED", "grounding": {
                                                      "model": "m2", "live": True, "tool_calls": [],
                                                      "result": {"kind": "CLARIFICATION"}},
                                                      "report": None}]}), encoding="utf-8")
    control_rows, product_rows = scoring.collect(controls, reports)
    assert len(control_rows) == 1 and len(product_rows) == 1
    assert product_rows[0]["disposition"] == "CLARIFICATION" and product_rows[0]["case"] == "—"


# --------------------------------------------------------------------------- live

@pytest.mark.live
def test_live_control_runs_once(tmp_path):
    from rw import config, grounding

    config.load_env()  # GROQ_API_KEY from the git-ignored .env; never printed
    chain = grounding.configured_models()
    if not any(grounding.has_credentials(model) for model in chain):
        pytest.skip("no provider key for the configured chain: " + ",".join(chain))
    print("LIVE CHAIN:", ",".join(chain))

    # One test execution is one conversation. Do not silently discard a failed trial and restart
    # the whole experiment; transport retries and correction turns already have explicit bounds.
    transcript, path = control.run_control(artifact_dir=tmp_path)
    print("LIVE CONTROL:", json.dumps({"model": transcript["model"], "provider": transcript["provider"],
                                       "turns": transcript["model_turns"],
                                       "tool_calls": transcript["tool_call_count"],
                                       "probes": [p["result"] for p in transcript["probe_calls"]],
                                       "result": transcript["result"]}, indent=2, default=str))
    print("transcript:", path)
    assert transcript["live"] is True
    assert transcript["model"] in chain
    assert transcript["aborted"] is False, transcript["validation_errors"]
    assert not transcript["validation_errors"], transcript["validation_errors"]
    if transcript["result"].get("kind") == "CLARIFICATION":
        assert transcript["result"]["question"].strip()
        return  # usable terminal execution; no readability verdict
    assert transcript["result"]["disposition"] in control.DISPOSITIONS
    assert set(transcript["result"]["fleet"]) == {"cart", "checkout"}
    if transcript["result"]["disposition"] == "BOUNDED_PASS":
        assert transcript["probe_calls"], "claimed BOUNDED_PASS without probing anything"


def _raw_groq(name, arguments, call_id="call_bad"):
    """A Groq response whose tool call carries a raw (possibly malformed) name/arguments."""
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}]}}]}


@pytest.mark.parametrize("bad", [_raw_groq("run_reader_probe", "[1, 2]"), _raw_groq([], "{}")])
def test_control_malformed_call_is_an_error_payload_and_the_loop_continues(tmp_path, bad):
    transport = FakeGroqTransport([bad, groq_call("submit_assessment", call_id="ok",
                                                  fleet=[{"service": "cart", "version": "1.4"}],
                                                  disposition="BLOCKED", evidence=["observed"])])
    transcript, _ = control.run_control(transport=transport, artifact_dir=tmp_path)
    assert transcript["result"]["disposition"] == "BLOCKED"
    errors = [e.get("error") for e in transcript["events"] if e.get("type") == "tool"]
    assert any(e in ("arguments must be a JSON object", "tool name must be a string") for e in errors)


def test_control_malformed_envelope_falls_through_and_is_not_saved(tmp_path, monkeypatch):
    from rw import grounding

    marker = "RAW-PROVIDER-MARKER-7f3a"
    made = []

    def make_transport(spec):
        made.append(spec)

        def tr(body):
            if spec == "groq:m1":
                return {"error": {"message": marker}}
            return groq_call("submit_assessment", call_id="m2", fleet=[{"service": "cart", "version": "1.4"}],
                             disposition="BLOCKED", evidence=["observed"])
        tr.model_used, tr.provider = spec, "groq"
        return tr

    monkeypatch.setattr(grounding, "make_transport", make_transport)
    transcript, path = control.run_control(artifact_dir=tmp_path, models=["groq:m1", "groq:m2"])
    assert made == ["groq:m1", "groq:m2"] and transcript["model"] == "groq:m2"
    assert transcript["abandoned"][0]["error"]["code"] == "malformed_response"
    assert marker not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("reads_from", [None, "<absent>"])
def test_flat_context_keeps_a_route_without_a_store_as_a_visible_gap(tmp_path, reads_from):
    """A declared route with reads_from null or missing must not crash context construction; the
    route stays listed with store_id null so the missing store remains evidence."""
    import shutil

    root = tmp_path / "shop"
    shutil.copytree(Path(__file__).resolve().parents[1] / "fixtures" / "shop", root)
    declaration_path = root / "releases" / "cart-1.4" / "release.json"
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    for route in declaration["routes"]:
        if reads_from == "<absent>":
            route.pop("reads_from", None)
        else:
            route["reads_from"] = None
    declaration_path.write_text(json.dumps(declaration), encoding="utf-8")
    text = control.flat_context(root)
    mappings = [json.loads(line) for line in text.splitlines() if line.startswith('{"release_identity_sources"')]
    cart_14 = [m for m in mappings if m["service"] == "cart" and m["version"] == "1.4"]
    assert cart_14 and all(m["store_id"] is None for m in cart_14)
