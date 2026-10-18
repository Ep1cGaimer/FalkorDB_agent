"""Native transport selects decisions; the application alone dispatches tools."""
import copy
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return (importlib.import_module("confirmatory.gemini_meter"),
            importlib.import_module("confirmatory.investigation_runner"))


FINAL = {"answer": "The retrieved development text is retained; runtime unverified.",
         "citations": [], "gaps": ["Protocol test only, no answer-quality score"], "runtime_disposition": None}


def provider(parts):
    return {"modelVersion": "fake-native", "usageMetadata": {"promptTokenCount": 100,
        "candidatesTokenCount": 30, "thoughtsTokenCount": 2, "totalTokenCount": 132},
        "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": parts}}]}


def decision(value, name="select_action"):
    return {"functionCall": {"name": name, "args": value}, "thoughtSignature": "FAKE-SIGNATURE"}


class API:
    model = "models/fake-native"
    def __init__(self, parts=None):
        self.requests, self.counted = [], []
        self.parts = parts or [[decision({"action": "call", "name": "read", "arguments": {}})],
                               [decision({"action": "finish"})], [{"text": json.dumps(FINAL)}]]
    def count(self, request, timeout):
        self.counted.append(copy.deepcopy(request))
        return {"totalTokens": 100}
    def generate(self, request, timeout):
        self.requests.append(copy.deepcopy(request))
        return provider(self.parts[len(self.requests) - 1])


def test_native_decisions_dispatch_only_after_validation_and_lock_before_common_answer(modules, tmp_path):
    meter, runner = modules
    api, calls = API(), []
    names = ["read"]
    model = meter.MeteredModel(api, meter.Journal(tmp_path / "run"), native_decision_tools=names,
                              generation={"responseMimeType": "application/json"})
    names.append("shell")  # caller mutation cannot expand a recorded protocol
    result = runner.run_development_question({"id": "DEV-NATIVE", "repository": "development",
        "revision": "a" * 40, "question": "Read the declared source."},
        {"read": lambda: calls.append("read") or {"content": "source-data"}}, {"read": {"arguments": {}}}, model)
    assert result["status"] == "COMPLETE_UNSCORED" and result["answer"] == FINAL
    assert calls == ["read"] and api.counted == api.requests
    assert (tmp_path / "run/retrieval.json").is_file()
    for request in api.requests[:2]:
        assert "responseMimeType" not in request["generationConfig"]
        declaration = request["tools"][0]["functionDeclarations"][0]
        assert declaration["name"] == "select_action"
        assert declaration["parametersJsonSchema"]["properties"]["name"]["enum"] == ["read"]
        assert request["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    history = api.requests[1]["contents"]
    assert len(history) == 3 and history[1]["role"] == "model"
    assert history[1]["parts"] == api.parts[0]
    assert history[1]["parts"][0]["thoughtSignature"] == "FAKE-SIGNATURE"
    reply = history[2]["parts"][0]["functionResponse"]
    assert reply["name"] == "select_action" and reply["response"]["selected_tool"] == "read"
    assert reply["response"]["tool_result"]["result"]["content"] == "source-data"
    assert "tools" not in api.requests[-1] and "toolConfig" not in api.requests[-1]
    assert api.requests[-1]["systemInstruction"]["parts"][0]["text"] == runner.ANSWER_SYSTEM
    assert api.requests[-1]["generationConfig"]["responseMimeType"] == "application/json"
    assert result["model_usage"]["reported_output_including_thinking"] == 96
    setup = json.loads((tmp_path / "run/model-setup.json").read_text())
    assert setup["native_decision_tools"] == ["read"]


def test_native_tool_reply_preserves_call_id_and_rejects_mismatched_dispatch(modules, tmp_path):
    meter, _ = modules
    part = decision({"action": "call", "name": "read", "arguments": {}})
    part["functionCall"]["id"] = "recorded-call-id"
    api = API([[part]])
    model = meter.MeteredModel(api, meter.Journal(tmp_path / "run"), native_decision_tools=["read"])
    text = model.ask("development", [{"role": "user", "parts": [{"text": "question"}]}], phase="retrieval")
    assert model.model_message(text)["parts"] == [part]
    with pytest.raises(ValueError, match="dispatch"):
        model.tool_message("other_tool", {"status": "OK"})
    reply = model.tool_message("read", {"status": "OK"})["parts"][0]["functionResponse"]
    assert reply["id"] == "recorded-call-id"


@pytest.mark.parametrize("parts", [
    [{"text": '{"action":"finish"}'}],
    [decision({"action": "finish"}, "not_registered")],
    [decision({"action": "finish"}), decision({"action": "finish"})],
    [decision({"action": "finish"}), {"text": "also execute this"}],
    [decision(["not an object"])],
    [decision({"action": "finish"}), {"inlineData": {"mimeType": "text/plain", "data": "eA=="}}],
])
def test_malformed_or_mixed_native_decisions_fail_without_dispatch_or_usage_loss(modules, tmp_path, parts):
    meter, _ = modules
    model = meter.MeteredModel(API([parts]), meter.Journal(tmp_path / "run"), native_decision_tools=["read"])
    with pytest.raises(meter.ModelFailure, match="NATIVE_DECISION"):
        model.ask("development", [{"role": "user", "parts": [{"text": "untrusted"}]}], phase="retrieval")
    assert model.summary()["calls"] == 1 and model.actual_input == 100 and model.actual_output == 32


@pytest.mark.parametrize("names", [[], ["read", "read"], ["read", "bad name"], "read", [42]])
def test_native_protocol_requires_an_explicit_unique_tool_allowlist(modules, tmp_path, names):
    meter, _ = modules
    with pytest.raises(ValueError, match="native_decision_tools"):
        meter.MeteredModel(API(), meter.Journal(tmp_path / "run"), native_decision_tools=names)


def test_typed_native_tools_publish_required_graph_arguments_and_preserve_continuation(modules, tmp_path):
    meter, runner = modules
    sha = "a" * 40
    parts = [[decision({"revision": sha, "symbol": "pkg.Child", "hops": 2}, "dependencies")],
             [decision({}, "finish_investigation")], [{"text": json.dumps(FINAL)}]]
    api, calls = API(parts), []
    descriptions = {"dependencies": {"description": "Traverse static relationships.", "arguments": {
        "revision": "required string", "symbol": "required qualified name", "hops": "optional integer1..5"}}}
    model = meter.MeteredModel(api, meter.Journal(tmp_path / "run"),
        native_decision_tools=["dependencies"], native_tool_descriptions=descriptions)
    result = runner.run_development_question({"id": "DEV-TYPED", "repository": "development",
        "revision": sha, "question": "Trace two dependency hops."},
        {"dependencies": lambda **kw: calls.append(kw) or {"relations": ["static edge"]}}, descriptions, model)
    assert result["status"] == "COMPLETE_UNSCORED"
    assert calls == [{"revision": sha, "symbol": "pkg.Child", "hops": 2}]
    declarations = {d["name"]: d for d in api.requests[0]["tools"][0]["functionDeclarations"]}
    assert set(declarations) == {"dependencies", "finish_investigation"}
    schema = declarations["dependencies"]["parametersJsonSchema"]
    assert schema["required"] == ["revision", "symbol"]
    assert schema["properties"]["hops"]["type"] == "integer"
    assert schema["additionalProperties"] is False
    reply = api.requests[1]["contents"][2]["parts"][0]["functionResponse"]
    assert reply["name"] == "dependencies"
    assert api.requests[1]["contents"][1]["parts"] == parts[0]
    assert "tools" not in api.requests[-1]


def test_typed_native_tool_names_cannot_expand_the_application_allowlist(modules, tmp_path):
    meter, _ = modules
    api = API([[decision({"revision": "a" * 40}, "shell")]])
    model = meter.MeteredModel(api, meter.Journal(tmp_path / "run"), native_decision_tools=["symbols"],
        native_tool_descriptions={"symbols": {"arguments": {"revision": "required string", "name": "optional symbol string"}}})
    with pytest.raises(meter.ModelFailure, match="NATIVE_DECISION"):
        model.ask("Investigate", [{"role": "user", "parts": [{"text": "Question"}]}], phase="retrieval")
    assert model.actual_input == 100 and model.actual_output == 32


def test_graph_capable_agent_can_choose_raw_source_without_forced_graph_call(modules, tmp_path):
    meter, runner = modules
    sha = "a" * 40
    api = API([[decision({"revision": sha, "path": "a.py"}, "read_file")],
               [decision({}, "finish_investigation")], [{"text": json.dumps(FINAL)}]])
    calls = []
    descriptions = {
        "read_file": {"arguments": {"revision": "required string", "path": "required path"}},
        "dependencies": {"arguments": {"revision": "required string", "symbol": "required qualified name"}}}
    model = meter.MeteredModel(api, meter.Journal(tmp_path / "run"),
        native_decision_tools=sorted(descriptions), native_tool_descriptions=descriptions)
    result = runner.run_development_question({"id": "DEV-CHOICE", "repository": "development",
        "revision": sha, "question": "Read this local definition."},
        {"read_file": lambda **kw: calls.append("raw") or {"source": "local definition"},
         "dependencies": lambda **kw: pytest.fail("must not force a graph traversal")}, descriptions, model)
    assert result["status"] == "COMPLETE_UNSCORED" and calls == ["raw"]
    allowed = api.requests[0]["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"]
    assert set(allowed) == {"read_file", "dependencies", "finish_investigation"}
