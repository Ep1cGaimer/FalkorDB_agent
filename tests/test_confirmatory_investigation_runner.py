"""Development run orchestration, evidence locking and honest failures, using fakes."""
import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return (importlib.import_module("confirmatory.investigation_runner"),
            importlib.import_module("confirmatory.gemini_meter"))


TASK = {"id": "DEV-ONLY", "repository": "synthetic-development", "revision": "a" * 40,
        "question": "What is the literal returned by example?"}
FINAL = {"answer": "The literal is 1.", "citations": [{"repository": TASK["repository"],
    "commit": "a" * 40, "path": "example.py", "start_line": 1, "end_line": 2}],
    "gaps": ["runtime unverified"], "runtime_disposition": None}


class ScriptedAPI:
    model = "models/fake-development"
    def __init__(self, directory, actions=None):
        self.directory, self.requests = directory, []
        self.actions = actions or [{"action": "call", "name": "read", "arguments": {}},
                                   {"action": "finish"}, FINAL]
    def count(self, request, timeout):
        return {"totalTokens": 100}
    def generate(self, request, timeout):
        self.requests.append(copy.deepcopy(request))
        if request["systemInstruction"]["parts"][0]["text"].startswith("Answer the supplied repository/history question"):
            assert (self.directory / "retrieval.json").exists(), "evidence must lock before answer"
        value = self.actions[len(self.requests) - 1]
        text = value if isinstance(value, str) else json.dumps(value)
        return {"modelVersion": "fake-v1", "usageMetadata": {"promptTokenCount": 100,
            "candidatesTokenCount": 20, "thoughtsTokenCount": 5, "totalTokenCount": 125},
            "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [{"text": text}]}}]}


def setup(modules, tmp_path, actions=None, limits=None):
    runner, meter = modules
    directory = tmp_path / "attempt"
    api = ScriptedAPI(directory, actions)
    model = meter.MeteredModel(api, meter.Journal(directory), limits or meter.ModelLimits())
    return runner, model, api


def run(runner, model, *, capabilities=None, descriptions=None, **kwargs):
    return runner.run_development_question(TASK, capabilities or {"read": lambda: {"content": "return 1"}},
        descriptions or {"read": {"description": "Read synthetic source", "arguments": {}}}, model, **kwargs)


def test_evidence_is_durably_locked_before_final_generation_and_result_is_unscored(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    result = run(runner, model)
    assert result["status"] == "COMPLETE_UNSCORED" and not result["acceptance_validated"]
    assert result["answer"] == FINAL
    assert result["model_usage"]["reported_input_tokens"] == 300
    assert result["model_usage"]["reported_output_including_thinking"] == 75
    directory = tmp_path / "attempt"
    assert result["retrieval_sha256"] == hashlib.sha256((directory / "retrieval.json").read_bytes()).hexdigest()
    assert result["events_sha256"] == hashlib.sha256((directory / "events.jsonl").read_bytes()).hexdigest()
    events = [json.loads(x) for x in (directory / "events.jsonl").read_text().splitlines()]
    locked = next(e["sequence"] for e in events if e["kind"] == "retrieval_locked")
    final = next(e["sequence"] for e in events if e["kind"] == "generation_started" and e["phase"] == "answer")
    assert locked < final
    assert "elapsed_seconds" not in api.requests[-1]["contents"][0]["parts"][0]["text"]


def retrieval_receipt(locked):
    return {"schema": "retrieval-score-receipt/v1", "task_id": locked["task"]["id"],
            "retrieval_sha256": hashlib.sha256((locked["directory"] / "retrieval.json").read_bytes()).hexdigest(),
            "scorer_id": "independent-synthetic-reviewer", "rubric_sha256": "c" * 64,
            "oracle_manifest_sha256": "d" * 64, "assessment_sha256": "e" * 64,
            "evidence_applicable": True, "precision": 0.0, "recall": 0.0}


def test_retrieval_score_is_locked_before_answer_without_model_feedback(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    def score(locked):
        assert len(api.requests) == 2
        assert not (tmp_path / "attempt/result.json").exists()
        receipt = retrieval_receipt({**locked, "directory": tmp_path / "attempt"})
        locked["tool_trace"].clear()  # scorer cannot alter the model's evidence
        return receipt
    result = run(runner, model, retrieval_scorer=score, require_retrieval_scoring=True)
    assert result["status"] == "COMPLETE_UNSCORED"
    path = tmp_path / "attempt/retrieval-score.json"
    assert result["retrieval_score_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    final_input = api.requests[-1]["contents"][0]["parts"][0]["text"]
    assert 'independent-synthetic-reviewer' not in final_input and 'precision' not in final_input
    assert json.loads(final_input)["evidence"]
    events = [json.loads(x) for x in (tmp_path / "attempt/events.jsonl").read_text().splitlines()]
    scored = next(e["sequence"] for e in events if e["kind"] == "retrieval_score_locked")
    generated = next(e["sequence"] for e in events if e["kind"] == "generation_started" and e["phase"] == "answer")
    assert scored < generated


@pytest.mark.parametrize("defect", ["wrong_hash", "oracle_text", "nan", "tamper"])
def test_invalid_or_tampered_preanswer_scoring_prevents_final_generation(modules, tmp_path, defect):
    runner, model, api = setup(modules, tmp_path)
    def score(locked):
        r = retrieval_receipt({**locked, "directory": tmp_path / "attempt"})
        if defect == "wrong_hash": r["retrieval_sha256"] = "f" * 64
        if defect == "oracle_text": r["expected_answer"] = "must never reach model"
        if defect == "nan": r["precision"] = float("nan")
        if defect == "tamper": (tmp_path / "attempt/retrieval.json").write_text('{}')
        return r
    result = run(runner, model, retrieval_scorer=score, require_retrieval_scoring=True)
    assert result["status"] == "ERROR" and result["answer"] is None
    assert len(api.requests) == 2


def test_required_scoring_cannot_be_silently_skipped(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    result = run(runner, model, require_retrieval_scoring=True)
    assert result["failure"] == "RETRIEVAL_SCORER_REQUIRED" and not api.requests


def test_same_answer_instruction_for_different_retrieval_capabilities(modules, tmp_path):
    runner, meter = modules
    prompts = []
    for index, name in enumerate(["plain_read", "graph_read"]):
        directory = tmp_path / str(index)
        actions = [{"action": "call", "name": name, "arguments": {}}, {"action": "finish"}, FINAL]
        api = ScriptedAPI(directory, actions)
        model = meter.MeteredModel(api, meter.Journal(directory))
        runner.run_development_question(TASK, {name: lambda: {"source": "same raw corpus"}},
                                        {name: {"description": "arm-specific retrieval interface"}}, model)
        prompts.append(api.requests[-1]["systemInstruction"])
    assert prompts[0] == prompts[1]


@pytest.mark.parametrize("decision", ['{"action":"finish","action":"call"}',
    '{"action":"finish","bad":NaN}', '{"action":"call","name":"read"}', '["finish"]'])
def test_malformed_planner_output_remains_a_failed_attempt(modules, tmp_path, decision):
    runner, model, api = setup(modules, tmp_path, [decision])
    result = run(runner, model)
    assert result["status"] == "ERROR" and result["answer"] is None
    assert result["model_usage"]["calls"] == 1 and len(api.requests) == 1
    assert (tmp_path / "attempt/result.json").exists()


def test_tool_budget_exhaustion_prevents_unsupported_final_answer(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    budget = importlib.import_module("confirmatory.tool_budget")
    result = run(runner, model, capabilities={"read": lambda: "x" * 10000},
                 tool_limits=budget.ToolLimits(output_bytes=100))
    assert result["failure"] == "RETRIEVAL_BUDGET_EXHAUSTED" and result["answer"] is None
    assert len(api.requests) == 1 and result["tool_usage"]["exhausted"] == "output_bytes"


def test_model_budget_after_retrieval_preserves_lock_and_fails_case(modules, tmp_path):
    runner, meter = modules
    runner, model, api = setup(modules, tmp_path, limits=meter.ModelLimits(calls=2))
    result = run(runner, model)
    assert result["failure"] == "MODEL_CALL_BUDGET_EXHAUSTED" and result["answer"] is None
    assert result["retrieval_sha256"] and len(api.requests) == 2


def test_final_answer_reserve_stops_retrieval_with_explicit_limit_and_locked_evidence(modules, tmp_path):
    runner, meter = modules
    directory = tmp_path / "attempt"
    api = ScriptedAPI(directory, [FINAL])
    model = meter.MeteredModel(api, meter.Journal(directory),
        meter.ModelLimits(input_tokens=1000), reserve_final_answer=True)
    result = run(runner, model)
    assert result["status"] == "COMPLETE_UNSCORED" and len(api.requests) == 1
    locked = json.loads((directory / "retrieval.json").read_text())
    assert locked["retrieval_termination"]["kind"] == "FINAL_ANSWER_RESERVE"
    assert result["retrieval_termination"] == locked["retrieval_termination"]
    request = json.loads(api.requests[0]["contents"][0]["parts"][0]["text"])
    assert request["retrieval_termination"]["incomplete"] is True
    assert result["answer"]["gaps"] and result["model_usage"]["reported_input_tokens"] == 100


def test_answer_cannot_hide_a_controller_limit_with_an_empty_gap_list(modules, tmp_path):
    runner, meter = modules
    directory = tmp_path / "attempt"
    api = ScriptedAPI(directory, [{**FINAL, "gaps": []}])
    model = meter.MeteredModel(api, meter.Journal(directory),
        meter.ModelLimits(input_tokens=1000), reserve_final_answer=True)
    result = run(runner, model)
    assert result["failure"] == "MISSING_RETRIEVAL_LIMITATION" and result["answer"] is None
    assert result["retrieval_termination"]["incomplete"] is True
    assert result["model_usage"]["calls"] == 1


def test_source_only_runtime_pass_is_rejected_without_discarding_generation(modules, tmp_path):
    bad = {**FINAL, "runtime_disposition": "BOUNDED_PASS"}
    runner, model, api = setup(modules, tmp_path, [{"action": "finish"}, bad])
    result = run(runner, model)
    assert result["failure"] == "UNSUPPORTED_RUNTIME_DISPOSITION" and result["answer"] is None
    assert result["model_usage"]["calls"] == 2


def test_expected_answers_and_confirmatory_ids_cannot_enter_development_runner(modules):
    runner, _ = modules
    with pytest.raises(ValueError, match="scoring"):
        runner.public_task({**TASK, "expected_answer": "secret oracle"})
    with pytest.raises(ValueError, match="confirmatory"):
        runner.public_task({**TASK, "id": "CF-REQ-DEP-01"})


def test_persisted_failed_tool_can_be_followed_by_explicit_recovery(modules, tmp_path):
    actions = [{"action": "call", "name": "missing", "arguments": {}},
               {"action": "call", "name": "read", "arguments": {}}, {"action": "finish"}, FINAL]
    runner, model, api = setup(modules, tmp_path, actions)
    result = run(runner, model)
    assert result["status"] == "COMPLETE_UNSCORED"
    trace = json.loads((tmp_path / "attempt/retrieval.json").read_text())["tool_trace"]
    assert [t["response"]["status"] for t in trace] == ["ERROR", "OK"]
    assert result["tool_usage"]["used"]["tool_calls"] == 2


def test_fatal_arm_failure_cannot_be_followed_by_a_fallback_answer(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    class Unavailable(RuntimeError):
        fatal_tool_failure = True
        code = "GRAPH_INDEX_UNAVAILABLE"
    def unavailable():
        raise Unavailable()
    trace = [{"kind": "falkordb_query", "outcome": "ERROR"}]
    result = runner.run_development_question(TASK, {"read": unavailable}, {"read": {}}, model, audit_trace=trace)
    assert result["status"] == "ERROR" and result["failure"] == "GRAPH_INDEX_UNAVAILABLE"
    assert result["answer"] is None and len(api.requests) == 1
    assert json.loads((tmp_path / "attempt/retrieval-audit.json").read_text()) == trace


def test_failed_readiness_is_recorded_before_any_model_generation(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    _, meter = modules
    def readiness():
        raise meter.ModelFailure("GRAPH_CORPUS_MISMATCH")
    result = runner.run_development_question(TASK, {"read": lambda: {}}, {"read": {}}, model, readiness=readiness)
    assert result["failure"] == "GRAPH_CORPUS_MISMATCH" and api.requests == []
    assert result["model_usage"]["calls"] == 0


def test_same_raw_corpus_scope_reaches_planner_and_answer_without_oracle_annotations(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    context = {"corpus_sha256": "e" * 64, "spec": {"schema": "source-corpus-spec/v1",
        "repository": TASK["repository"], "roots": [TASK["revision"]], "include": ["*.py"], "exclude": ["vendor/*"]}}
    result = run(runner, model, corpus_context=context)
    assert result["status"] == "COMPLETE_UNSCORED"
    for request in [api.requests[0], api.requests[-1]]:
        message = json.loads(request["contents"][0]["parts"][0]["text"])
        assert message["corpus_context"] == context


def test_oracle_fields_are_rejected_in_corpus_context_before_model_request(modules, tmp_path):
    runner, model, api = setup(modules, tmp_path)
    with pytest.raises(ValueError):
        run(runner, model, corpus_context={"corpus_sha256": "e" * 64, "spec": {}, "expected_answer": "not allowed"})
    assert api.requests == []


def test_changed_locked_evidence_file_reopens_attempt_before_answer_is_accepted(modules, tmp_path):
    runner, model, _ = setup(modules, tmp_path)
    class TamperedAPI(ScriptedAPI):
        def generate(self, request, timeout):
            response = super().generate(request, timeout)
            if len(self.requests) == 3:
                (self.directory / "retrieval.json").write_text('{"unexpected":"changed evidence"}\n')
            return response
    model.api = TamperedAPI(tmp_path / "attempt")
    result = run(runner, model)
    assert result["status"] == "ERROR" and result["failure"] == "LOCKED_RETRIEVAL_CHANGED"
    assert result["answer"] is None and result["model_usage"]["calls"] == 3


def test_locked_evidence_is_detached_from_tool_caches_before_model_generation(modules, tmp_path):
    runner, model, _ = setup(modules, tmp_path)
    shared = {"content": "original immutable evidence"}
    class MutatingAPI(ScriptedAPI):
        def generate(self, request, timeout):
            response = super().generate(request, timeout)
            if len(self.requests) == 3:
                shared["content"] = "changed cache"
            return response
    class Guard:
        version = "test-cache-snapshot"
        def verify(self, citations, trace, **kwargs):
            return {"valid": trace[0]["response"]["result"]["content"] == "original immutable evidence"}
    model.api = MutatingAPI(tmp_path / "attempt")
    result = run(runner, model, capabilities={"read": lambda: shared}, citation_guard=Guard())
    assert result["status"] == "COMPLETE_UNSCORED" and result["citation_reference_validation"]["valid"]
