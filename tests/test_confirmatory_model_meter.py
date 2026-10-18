"""Model metering failure contracts using explicit fake providers; not live quality."""
import copy
import importlib
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("confirmatory.gemini_meter")


def response(text='{"action":"finish"}', *, prompt=100, generated=20, thoughts=7, version="test-version"):
    return {"modelVersion": version,
            "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": generated,
                              "thoughtsTokenCount": thoughts, "totalTokenCount": prompt + generated + thoughts},
            "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [{"text": text}]}}]}


class FakeAPI:
    model = "models/fake-development"
    def __init__(self, *, count=100, responses=None):
        self.counted, self.generated = [], []
        self.count_value = count
        self.responses = responses or [response()]
    def count(self, request, timeout):
        self.counted.append((copy.deepcopy(request), timeout))
        return {"totalTokens": self.count_value}
    def generate(self, request, timeout):
        self.generated.append((copy.deepcopy(request), timeout))
        item = self.responses[min(len(self.generated) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)


def meter(module, tmp_path, api=None, **kwargs):
    return module.MeteredModel(api or FakeAPI(), module.Journal(tmp_path / "attempt"), **kwargs)


def events(tmp_path):
    return [json.loads(x) for x in (tmp_path / "attempt/events.jsonl").read_text().splitlines()]


def ask(meter):
    return meter.ask("SAME SYSTEM", [{"role": "user", "parts": [{"text": "development task"}]}], phase="retrieval")


def test_full_count_payload_equals_generation_and_reports_thinking(module, tmp_path):
    api = FakeAPI()
    model = meter(module, tmp_path, api)
    assert ask(model) == '{"action":"finish"}'
    assert api.counted[0][0] == api.generated[0][0]
    assert model.summary()["reported_output_including_thinking"] == 27
    assert model.input_charged == 100 and model.output_charged == 27
    assert [x["kind"] for x in events(tmp_path)] == ["token_count_started", "token_count_completed",
        "generation_started", "generation_completed", "usage_reconciled"]


def test_cumulative_input_refuses_second_request_before_generation(module, tmp_path):
    api = FakeAPI()
    model = meter(module, tmp_path, api, limits=module.ModelLimits(input_tokens=200))
    ask(model)
    with pytest.raises(module.ModelFailure, match="INPUT_BUDGET"):
        ask(model)
    assert len(api.generated) == 1 and len(api.counted) == 2


def test_actual_generation_caps_include_remaining_reasoning_and_planner_use(module, tmp_path):
    api = FakeAPI(responses=[response(generated=10, thoughts=7)])
    model = meter(module, tmp_path, api, limits=module.ModelLimits(output_tokens=20, per_call_output=15))
    with pytest.raises(module.ModelFailure, match="EXCEEDED_OUTPUT"):
        ask(model)
    assert api.generated[0][0]["generationConfig"]["maxOutputTokens"] == 15
    assert model.actual_output == 17  # preserve actual overshoot, not a clipped measurement


def test_provider_failure_keeps_reservation_unknown_usage_and_no_retry(module, tmp_path):
    api = FakeAPI(responses=[RuntimeError("SECRET provider error")])
    model = meter(module, tmp_path, api)
    with pytest.raises(module.ModelFailure, match="GENERATION_FAILED"):
        ask(model)
    assert model.usage_unknown and model.output_charged == 1000
    assert model.input_charged == 164 and len(api.generated) == 1
    with pytest.raises(module.ModelFailure, match="UNKNOWN"):
        ask(model)
    assert len(api.generated) == 1 and "SECRET" not in str(events(tmp_path))


@pytest.mark.parametrize("bad", [{}, {"promptTokenCount": True}, {"promptTokenCount": 100, "totalTokenCount": 2}])
def test_missing_or_invalid_usage_cannot_become_a_free_success(module, tmp_path, bad):
    payload = response()
    payload["usageMetadata"] = bad
    model = meter(module, tmp_path, FakeAPI(responses=[payload]))
    with pytest.raises(module.ModelFailure, match="TOKEN_METADATA"):
        ask(model)
    assert model.usage_unknown and model.output_charged == 1000
    assert any(e["kind"] == "generation_completed" for e in events(tmp_path))


def test_response_model_change_is_visible_and_usage_stays_counted(module, tmp_path):
    model = meter(module, tmp_path, FakeAPI(responses=[response(), response(version="changed")]))
    ask(model)
    with pytest.raises(module.ModelFailure, match="VERSION_CHANGED"):
        ask(model)
    assert model.actual_input == 200 and model.actual_output == 54


def test_context_reserve_checked_before_generation(module, tmp_path):
    api = FakeAPI()
    model = meter(module, tmp_path, api, limits=module.ModelLimits(context_tokens=1000))
    with pytest.raises(module.ModelFailure, match="CONTEXT"):
        ask(model)
    assert api.generated == []


def test_deadline_after_response_withholds_answer_but_retains_usage(module, tmp_path):
    now = [0.0]
    class Slow(FakeAPI):
        def generate(self, request, timeout):
            value = super().generate(request, timeout)
            now[0] = 121
            return value
    model = meter(module, tmp_path, Slow(), clock=lambda: now[0])
    with pytest.raises(module.ModelFailure, match="DEADLINE"):
        ask(model)
    assert model.actual_output == 27


def test_truncated_response_retained_and_counted_not_returned_as_answer(module, tmp_path):
    payload = response()
    payload["candidates"][0]["finishReason"] = "MAX_TOKENS"
    model = meter(module, tmp_path, FakeAPI(responses=[payload]))
    with pytest.raises(module.ModelFailure, match="INCOMPLETE"):
        ask(model)
    assert model.actual_input == 100


@pytest.mark.parametrize("finish", ["STOP", "MALFORMED_FUNCTION_CALL"])
@pytest.mark.parametrize("missing", [True, False])
def test_visible_output_with_zero_or_missing_candidate_tokens_keeps_unknown_reservation(module, tmp_path, finish, missing):
    # Observed live failure: nonempty planner JSON, prompt-only usage, and
    # MALFORMED_FUNCTION_CALL. It cannot establish that generated text was free.
    payload = response(generated=0, thoughts=0)
    payload["candidates"][0]["finishReason"] = finish
    if missing:
        del payload["usageMetadata"]["candidatesTokenCount"]
    model = meter(module, tmp_path, FakeAPI(responses=[payload]))
    with pytest.raises(module.ModelFailure, match="UNUSABLE_TOKEN_METADATA"):
        ask(model)
    assert model.usage_unknown and model.output_charged == 1000
    assert model.actual_input == 100
    assert not model.summary()["reported_token_counts_complete"]
    assert any(e["kind"] == "generation_completed" for e in events(tmp_path))


def test_journal_preserves_attempt_and_will_not_overwrite(module, tmp_path):
    journal = module.Journal(tmp_path / "attempt")
    journal.write_new("retrieval.json", {"locked": True})
    with pytest.raises(FileExistsError):
        journal.write_new("retrieval.json", {})
    with pytest.raises(FileExistsError):
        module.Journal(tmp_path / "attempt")


def test_http_header_key_never_appears_in_url_and_count_includes_full_request(module):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers["x-goog-api-key"] == "SECRET"
        return httpx.Response(200, json={"totalTokens": 12})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        api = module.GeminiAPI("models/development", "SECRET", client=client)
        payload = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                   "systemInstruction": {"parts": [{"text": "same instructions"}]}}
        assert api.count(payload, 3)["totalTokens"] == 12
    assert "SECRET" not in str(calls[0].url)
    assert json.loads(calls[0].content) == {"generateContentRequest": {"model": "models/development", **payload}}


@pytest.mark.parametrize("status", [302, 400, 429, 503])
def test_http_error_body_and_credentials_are_never_replayed_or_retried(module, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "SECRET echoed by provider"},
                              headers={"location": "https://attacker.invalid/"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        api = module.GeminiAPI("models/development", "SECRET", client=client)
        with pytest.raises(module.ModelFailure) as error:
            api.count({}, 3)
    assert len(calls) == 1 and "SECRET" not in str(error.value)
    assert error.value.status == status


@pytest.mark.parametrize("model", ["../secret", "models/a:countTokens", "https://attacker.invalid", "models/a/b"])
def test_model_name_cannot_route_credentials_to_another_host(module, model):
    with pytest.raises(ValueError):
        module.GeminiAPI(model, "SECRET")
