"""HTTP compatibility, output fidelity, pagination and new text budget boundaries."""
import base64
from copy import deepcopy
import json
import os

from fastapi.testclient import TestClient
import pytest

from rw.api import create_app
from rw.api_contracts import InvestigationView
from rw.contracts import GroundingClarification, GroundingResult
from test_api import api, clarifying_api, create, confirm, plan_url, REQUEST


def assert_public_contract(client, state):
    """Catch additions to public() before strict HTTP response models can break the UI."""
    public = client.app.state.investigations[state["id"]].public()
    assert InvestigationView.model_validate(public).model_dump(mode="json", exclude_unset=True) == public
    assert state == public
    response = client.get(f"/api/investigations/{state['id']}")
    assert response.status_code == 200, response.text
    assert response.json() == public


def test_public_contract_through_verification_alternative_approval_and_simulation(api):
    client, _, _ = api
    state = create(client)
    assert_public_contract(client, state)
    confirm(client, state)
    assert_public_contract(client, client.get(f"/api/investigations/{state['id']}").json())
    alternative = client.post(f"/api/investigations/{state['id']}/alternative")
    assert alternative.status_code == 200, alternative.text
    state = alternative.json()
    assert_public_contract(client, state)
    confirm(client, state)
    assert_public_contract(client, client.get(f"/api/investigations/{state['id']}").json())
    for endpoint, body in [("approve", {"approved_by": "oncall:alice"}), ("simulate", None), ("simulate", None)]:
        response = client.post(plan_url(state) + "/" + endpoint, json=body)
        assert response.status_code == 200, response.text
        assert_public_contract(client, client.get(f"/api/investigations/{state['id']}").json())


def test_public_contract_before_and_after_clarification(clarifying_api):
    client, _, _, _ = clarifying_api
    state = create(client)
    assert_public_contract(client, state)
    response = client.post(f"/api/investigations/{state['id']}/answer", json={"answer": "Keep checkout 2.1."})
    assert response.status_code == 200, response.text
    state = response.json()
    assert_public_contract(client, state)
    confirm(client, state)
    assert_public_contract(client, client.get(f"/api/investigations/{state['id']}").json())


def test_output_is_lossless_and_does_not_mutate_evidence(api):
    client, _, app = api
    state = create(client)
    inv = app.state.investigations[state["id"]]
    plan_before = inv.attempts[0].plan.model_dump(mode="json")
    assert state == inv.public()
    report = confirm(client, state)
    assert "citations" not in report["plan"]
    assert all("changed" in f for f in report["plan"]["fleet"])
    assert all(c["release_id"] and c["kind"] for c in state["grounding"]["result"]["citations"])
    saved_report = deepcopy(inv.attempts[0].report)
    after = client.get(f"/api/investigations/{state['id']}").json()
    assert after == inv.public()
    assert inv.attempts[0].report == saved_report
    assert inv.attempts[0].plan.model_dump(mode="json") == plan_before
    assert InvestigationView.model_validate(after).model_dump(mode="json", exclude_unset=True) == after
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"InvestigationView", "ReportView", "RefusalError", "ValidationErrorView"} <= schemas.keys()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 200


def test_investigation_pages_preserve_legacy_order_and_latest_null(api):
    client, _, _ = api
    states = [create(client) for _ in range(5)]
    legacy = client.get("/api/investigations").json()
    assert [row["id"] for row in legacy] == [s["id"] for s in states]
    items, cursor = [], None
    while True:
        response = client.get("/api/investigations", params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        items.extend(response.json())
        cursor = response.headers.get("X-Next-Cursor")
        if not cursor:
            break
    assert [r["id"] for r in items] == sorted(s["id"] for s in states)
    assert len({r["id"] for r in items}) == 5
    confirm(client, states[0])
    client.post(f"/api/investigations/{states[0]['id']}/alternative")
    assert next(r for r in client.get("/api/investigations?limit=100").json()
                if r["id"] == states[0]["id"])["latest_disposition"] is None


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=1.2", "cursor=abc", "limit=2&cursor=abc",
                                      "limit=2&cursor=%2Ftmp", "limit=2&cursor=" + "a" * 513])
@pytest.mark.parametrize("endpoint", ["investigations", "transcripts"])
def test_bad_pagination_is_422_without_changing_legacy_lookup(endpoint, query):
    with TestClient(create_app()) as client:
        assert client.get(f"/api/{endpoint}?{query}").status_code == 422
        assert client.get("/api/investigations/not-a-hex-id").status_code == 404


def test_endpoint_specific_cursor_and_empty_pages(api):
    client, _, _ = api
    create(client); create(client)
    response = client.get("/api/investigations?limit=1")
    cursor = response.headers["X-Next-Cursor"]
    assert client.get("/api/transcripts", params={"limit": 1, "cursor": cursor}).status_code == 422
    data = base64.urlsafe_b64encode(json.dumps([True, "investigations", ["a" * 32]]).encode()).decode().rstrip("=")
    assert client.get("/api/investigations", params={"limit": 1, "cursor": data}).status_code == 422
    with TestClient(create_app()) as empty:
        result = empty.get("/api/investigations?limit=1")
        assert result.json() == [] and "X-Next-Cursor" not in result.headers


def test_transcript_pages_size_order_metadata_and_legacy(tmp_path):
    meta = {"request_text": "π", "model": "saved", "live": True, "result": {"kind": "PROPOSAL"}}
    for name in ("a.json", "β.json", "c.json"):
        path = tmp_path / name
        path.write_text(json.dumps(meta), encoding="utf-8")
        os.utime(path, (100, 100))
    big = tmp_path / "big.json"
    big.write_text(json.dumps({**meta, "padding": "x" * (1024 * 1024)}), encoding="utf-8")
    (tmp_path / "bad.json").write_text("[]")
    with TestClient(create_app(transcript_dir=tmp_path)) as client:
        legacy = client.get("/api/transcripts").json()
        assert len(legacy) == 4
        first = client.get("/api/transcripts?limit=2")
        assert [r["file_name"] for r in first.json()] == ["β.json", "c.json"]
        second = client.get("/api/transcripts", params={"limit": 2, "cursor": first.headers["X-Next-Cursor"]})
        assert [r["file_name"] for r in second.json()] == ["a.json"]
        assert "X-Next-Cursor" not in second.headers
        assert client.get("/api/transcripts").json() == legacy


@pytest.mark.parametrize("size", [3000, 3001])
def test_live_question_budget_is_checked_before_registration(api, tmp_path, size):
    client, _, app = api
    source = app.state.investigations[create(client)["id"]].session
    def clarify(request, tools, alternative_context=None):
        return GroundingResult(request_text=request, result=GroundingClarification(question="q" * size,
            unresolved=["basket"]), model="fake", live=True), None
    app = create_app(session_factory=lambda: source, ground_function=clarify, db_path=tmp_path / "test.sqlite")
    with TestClient(app) as other:
        result = other.post("/api/investigations", json={"request_text": REQUEST})
        assert result.status_code == (200 if size == 3000 else 502)
        assert len(app.state.investigations) == (1 if size == 3000 else 0)
        if size > 3000:
            assert result.json()["detail"]["code"] == "provider_error"


def test_replay_long_question_answer_bound_is_atomic(api, tmp_path):
    client, _, app = api
    session = app.state.investigations[create(client)["id"]].session
    (tmp_path / "long.json").write_text("{}")
    original = "r" * 20000
    def replay(path):
        return GroundingResult(request_text=original, result=GroundingClarification(question="q" * 8000,
            unresolved=["basket"]), model="saved", live=True)
    app = create_app(session_factory=lambda: session, replay_function=replay, transcript_dir=tmp_path)
    with TestClient(app) as other:
        result = other.post("/api/investigations", json={"request_text": original, "mode": "replay", "replay_path": "long.json"})
        assert result.status_code == 200
        inv = app.state.investigations[result.json()["id"]]
        response = other.post(f"/api/investigations/{inv.id}/answer", json={"answer": "a", "replay_path": "long.json"})
        assert response.status_code == 422
        assert inv.request.request_text == original and not inv.answered and len(inv.attempts) == 1


@pytest.mark.parametrize("text,status", [("",422),(" ",422),(1,422),(None,422),("a",200),("x"*20000,200),("x"*20001,422)])
def test_http_create_boundaries_before_session(api, tmp_path, text, status):
    client, _, app = api
    session = app.state.investigations[create(client)["id"]].session
    def clarify(request, tools, alternative_context=None):
        return GroundingResult(request_text=request, result=GroundingClarification(question="Which?",unresolved=[]),model="fake",live=True),None
    with TestClient(create_app(session_factory=lambda: session, ground_function=clarify)) as other:
        assert other.post("/api/investigations",json={"request_text":text}).status_code == status


@pytest.mark.parametrize("total", [27999,28000,28001])
def test_exact_composed_text_budget_preserves_replay_and_answer_atomicity(api,tmp_path,total):
    from rw.pipeline import with_answer
    client,_,app=api
    session=app.state.investigations[create(client)["id"]].session
    original,answer="r"*20000,"a"*4000
    question="q"*(total-len(with_answer(original,"",answer)))
    bound=with_answer(original,question,answer)
    assert len(bound)==total
    for filename in ("first.json","answered.json"): (tmp_path/filename).write_text("{}")
    def replay(path):
        text=original if path.name=="first.json" else bound
        return GroundingResult(request_text=text,result=GroundingClarification(question=question,unresolved=[]),model="saved",live=True)
    app=create_app(session_factory=lambda:session,replay_function=replay,transcript_dir=tmp_path)
    with TestClient(app) as other:
        state=other.post("/api/investigations",json={"request_text":original,"mode":"replay","replay_path":"first.json"}).json()
        inv=app.state.investigations[state["id"]]
        result=other.post(f"/api/investigations/{inv.id}/answer",json={"answer":answer,"replay_path":"answered.json"})
        assert result.status_code==(200 if total<=28000 else 422)
        assert inv.answered==(total<=28000)
        assert len(inv.attempts)==(2 if total<=28000 else 1)
        assert inv.request.request_text==(bound if total<=28000 else original)
