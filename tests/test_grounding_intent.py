"""Enforcement tests for intent assessment, separate from live semantic judgment."""
import json

import pytest

from rw import grounding
from rw.contracts import GroundingClarification, GroundingProposal
from test_grounding import EX_ID, FakeTools, call, groq_call


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_unresolved_intent_stops_before_release_tools(provider, tmp_path):
    render = groq_call if provider == "groq" else call
    responses = [render("assess_intent", references=[{"phrase": "change from yesterday", "basis": "UNRESOLVED", "relation": "AT"}], question="Which change or release do you mean?"),
                 render("release_history", service="cart"),
                 render("propose_fleet", changes=[{"service": "cart", "release_id": "release:cart:old"}],
                        citations=[{"excerpt_id": EX_ID, "quote": "Receipt correction"}], rationale="r")]
    bodies = []

    def transport(body):
        bodies.append(body)
        return responses.pop(0)

    transport.provider = provider
    tools = FakeTools()
    result, path = grounding.ground("Undo the change from yesterday.", tools,
                                    transport=transport, artifact_dir=tmp_path)
    assert isinstance(result.result, GroundingClarification)
    assert result.result.unresolved == ["change from yesterday"]
    assert not tools.calls and len(bodies) == 1
    assert not result.validation_errors
    body = bodies[0]
    names = ([tool["function"]["name"] for tool in body["tools"]] if provider == "groq" else
             [tool["name"] for tool in body["tools"][0]["functionDeclarations"]])
    assert names == ["assess_intent"]
    assert "release:cart" not in json.dumps(body)
    replay = grounding.replay(path)
    assert replay.result == result.result and replay.live is False


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize("decision", [
    {},
    {"references": [], "question": ""},
    {"references": [{"phrase": "invented feature", "basis": "NAMED_BEHAVIOR", "relation": "AT"}], "question": ""},
    {"references": [{"phrase": "yesterday", "basis": "NAMED_BEHAVIOR", "relation": "BEFORE"}], "question": "Which?"},
    {"references": [{"phrase": "specific change", "basis": "UNRESOLVED", "relation": "AT"}], "question": "Which?"},
    {"references": [{"phrase": "yesterday", "basis": "UNRESOLVED", "relation": "AT"}], "question": " "},
    {"references": [{"phrase": "yesterday", "basis": "UNRESOLVED", "relation": "SOMETIMES"}], "question": "Which?"},
    {"references": [{"phrase": 3, "basis": "UNRESOLVED", "relation": "AT"}], "question": "Which?"},
    {"references": [{"phrase": "yesterday", "basis": "UNRESOLVED", "relation": "AT"}], "question": "Which?", "status": "READY"},
], ids=["missing", "no-references", "invented-identity", "premature-artifact-question", "invented-span",
        "blank-question", "invalid-relation", "wrong-type", "readiness-override"])
def test_invalid_intent_is_bounded_and_never_opens_artifact_selection(provider, decision, tmp_path):
    render = groq_call if provider == "groq" else call
    bodies = []

    def transport(body):
        bodies.append(body)
        return render("assess_intent", **decision)

    transport.provider = provider
    tools = FakeTools()
    result, path = grounding.ground("Undo the change from yesterday.", tools,
                                    transport=transport, artifact_dir=tmp_path)
    assert grounding.is_aborted(result) and isinstance(result.result, GroundingClarification)
    assert len(bodies) == 2 and tools.calls == []
    assert grounding.replay(path).validation_errors == result.validation_errors


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize("attempt", ["release_history", "propose_fleet", "text-only", "parallel-proposal"])
def test_intent_phase_cannot_dispatch_or_smuggle_a_proposal(provider, attempt, tmp_path):
    render = groq_call if provider == "groq" else call
    if attempt == "text-only":
        response = {"choices": [{"message": {"content": "It is obvious"}}]} if provider == "groq" else {
            "candidates": [{"content": {"parts": [{"text": "It is obvious"}]}}]}
    elif attempt == "parallel-proposal":
        response = render("assess_intent", references=[{"phrase": "change", "basis": "NAMED_BEHAVIOR", "relation": "AT"}], question="")
        extra = render("propose_fleet", changes=[], citations=[], rationale="skip intent")
        if provider == "groq":
            response["choices"][0]["message"]["tool_calls"] += extra["choices"][0]["message"]["tool_calls"]
        else:
            response["candidates"][0]["content"]["parts"] += extra["candidates"][0]["content"]["parts"]
    else:
        response = render(attempt, service="cart")

    def transport(body):
        return response

    transport.provider = provider
    tools = FakeTools()
    result, _ = grounding.ground("Undo the change.", tools, transport=transport, artifact_dir=tmp_path)
    assert grounding.is_aborted(result) and not tools.calls


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_intent_correction_uses_one_shared_turn_budget(provider, tmp_path):
    render = groq_call if provider == "groq" else call
    bodies = []

    def transport(body):
        bodies.append(body)
        if len(bodies) == 1:
            return render("assess_intent", references=[], question="")
        if len(bodies) == 2:
            return render("assess_intent", references=[{"phrase": "named feature", "basis": "NAMED_BEHAVIOR", "relation": "AT"}], question="")
        return render("current_fleet")

    transport.provider = provider
    result, path = grounding.ground("Undo the named feature.", FakeTools(),
                                    transport=transport, artifact_dir=tmp_path)
    assert len(bodies) == grounding.MAX_TURNS and grounding.is_aborted(result)
    assert grounding.replay(path).validation_errors == result.validation_errors


def test_fallback_reassesses_intent_without_old_evidence_or_checker_context(tmp_path):
    requests = []

    def factory(model):
        def transport(body):
            requests.append((model, body))
            if model == "first":
                raise grounding.GroundingError("provider unavailable")
            return call("assess_intent", references=[{"phrase": "that change", "basis": "UNRESOLVED", "relation": "AT"}],
                        question="Which change do you mean?")
        return transport

    tools = FakeTools()
    result, path = grounding.ground("Undo that change.", tools, alternative_context="private old candidate",
                                    transport_factory=factory, models=["first", "second"], artifact_dir=tmp_path)
    assert result.model == "second" and not tools.calls
    assert len(requests) == 2
    assert all("private old candidate" not in json.dumps(body) for _, body in requests)
    assert json.loads(path.read_text())["abandoned_attempts"] == [{"model": "first", "error": "provider unavailable"}]


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_malformed_intent_response_aborts_without_a_crash(provider, tmp_path):
    response = ({"choices": [{"message": "not an object"}]} if provider == "groq" else
                {"candidates": [{"content": {"parts": [
                    {"functionCall": {"name": "assess_intent", "args": "not an object"}}]}}]})

    def transport(body):
        return response

    transport.provider = provider
    tools = FakeTools()
    result, _ = grounding.ground("Undo that change.", tools, transport=transport, artifact_dir=tmp_path)
    assert grounding.is_aborted(result) and not tools.calls


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_named_before_relationship_opens_artifact_search(provider, tmp_path):
    render = groq_call if provider == "groq" else call
    responses = [render("assess_intent", references=[
        {"phrase": "named feature", "basis": "NAMED_BEHAVIOR", "relation": "BEFORE"}], question=""),
        render("release_history", service="cart"),
        render("propose_fleet", changes=[{"service": "cart", "release_id": "release:cart:old"}],
               citations=[{"excerpt_id": EX_ID, "quote": "Receipt correction"}], rationale="r")]

    bodies = []

    def transport(body):
        bodies.append(body)
        return responses.pop(0)

    transport.provider = provider
    tools = FakeTools()
    result, path = grounding.ground("Restore the build from before the named feature.", tools,
                                    transport=transport, artifact_dir=tmp_path)
    assert isinstance(result.result, GroundingProposal) and not result.validation_errors
    assert tools.calls == ["release_history:cart"]
    search_request = (bodies[1]["messages"][1]["content"] if provider == "groq" else
                      bodies[1]["contents"][0]["parts"][0]["text"])
    assert '"relation": "BEFORE"' in search_request
    assert grounding.replay(path).result == result.result


def test_named_keep_reference_cannot_override_unresolved_undo_reference(tmp_path):
    def transport(body):
        return call("assess_intent", references=[
            {"phrase": "that change", "basis": "UNRESOLVED", "relation": "AT"},
            {"phrase": "named fix", "basis": "NAMED_BEHAVIOR", "relation": "AT"}], question="Which change?")

    tools = FakeTools()
    result, _ = grounding.ground("Undo that change but keep the named fix.", tools,
                                 transport=transport, artifact_dir=tmp_path)
    assert isinstance(result.result, GroundingClarification) and result.result.unresolved == ["that change"]
    assert not tools.calls


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_version_one_intent_replay_retains_its_original_decision(provider, tmp_path):
    render = groq_call if provider == "groq" else call
    path = tmp_path / "version-one.json"
    path.write_text(json.dumps({"request_text": "Undo that change.", "provider": provider, "intent_version": 1,
                                "events": [{"type": "model", "phase": "intent", "response": render(
                                    "assess_intent", status="CLARIFY", identifiers=[], unresolved=["that change"],
                                    question="Which change?")}]}))
    result = grounding.replay(path)
    assert result.live is False and result.result.question == "Which change?"


def test_unknown_intent_transcript_version_does_not_silently_use_legacy_replay(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"intent_version": 99}))
    with pytest.raises(grounding.GroundingError, match="unsupported intent transcript version"):
        grounding.replay(path)


@pytest.mark.parametrize("filename", ["70a0b3fbd63b17a3.json", "4f5d394955ed1fda.json", "459f0e5b394a2f39.json"])
def test_legacy_replay_preserves_the_recorded_failure(filename):
    from test_grounding import ROOT
    replay = grounding.replay(ROOT / "artifacts/grounding" / filename)
    assert replay.live is False and replay.result.kind == "PROPOSAL"
