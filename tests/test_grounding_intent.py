"""Enforcement tests for intent assessment, separate from live semantic judgment."""
import json

import pytest

from rw import grounding
from rw.contracts import GroundingClarification
from test_grounding import EX_ID, FakeTools, call, groq_call


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_unresolved_intent_stops_before_release_tools(provider, tmp_path):
    render = groq_call if provider == "groq" else call
    responses = [render("assess_intent", status="CLARIFY", identifiers=[],
                        unresolved=["change from yesterday"], question="Which change or release do you mean?"),
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
    {"status": "READY", "identifiers": [], "unresolved": [], "question": ""},
    {"status": "READY", "identifiers": ["invented feature"], "unresolved": [], "question": ""},
    {"status": "READY", "identifiers": ["yesterday"], "unresolved": ["yesterday"], "question": ""},
    {"status": "CLARIFY", "identifiers": [], "unresolved": ["specific change"], "question": "Which?"},
    {"status": "CLARIFY", "identifiers": [], "unresolved": ["yesterday"], "question": " "},
    {"status": "CLARIFY", "identifiers": [], "unresolved": [], "question": "Which?"},
    {"status": "CLARIFY", "identifiers": [], "unresolved": [3], "question": "Which?"},
    {"status": "CLARIFY", "identifiers": [], "unresolved": ["yesterday"], "question": "Which?", "changes": []},
], ids=["missing", "no-identity", "invented-identity", "contradictory-ready", "invented-span",
        "blank-question", "no-unresolved", "wrong-type", "extra-field"])
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
        response = render("assess_intent", status="READY", identifiers=["change"], unresolved=[], question="")
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
            return render("assess_intent", status="READY", identifiers=[], unresolved=[], question="")
        if len(bodies) == 2:
            return render("assess_intent", status="READY", identifiers=["named feature"], unresolved=[], question="")
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
            return call("assess_intent", status="CLARIFY", identifiers=[], unresolved=["that change"],
                        question="Which change do you mean?")
        return transport

    tools = FakeTools()
    result, path = grounding.ground("Undo that change.", tools, alternative_context="private old candidate",
                                    transport_factory=factory, models=["first", "second"], artifact_dir=tmp_path)
    assert result.model == "second" and not tools.calls
    assert len(requests) == 2
    assert all("private old candidate" not in json.dumps(body) for _, body in requests)
    assert json.loads(path.read_text())["abandoned_attempts"] == [{"model": "first", "error": "provider unavailable"}]


@pytest.mark.parametrize("filename", ["70a0b3fbd63b17a3.json", "4f5d394955ed1fda.json", "459f0e5b394a2f39.json"])
def test_legacy_replay_preserves_the_recorded_failure(filename):
    from test_grounding import ROOT
    replay = grounding.replay(ROOT / "artifacts/grounding" / filename)
    assert replay.live is False and replay.result.kind == "PROPOSAL"
