"""Real FalkorDB + real probes; only the language-model grounding is replaced."""
from pathlib import Path
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from rw.api import create_app
from rw.contracts import (Citation, FleetEntry, GroundingClarification,
                          GroundingProposal, GroundingResult)

REQUEST = "Undo the basket rollout but keep the receipt correction"


@pytest.fixture
def api(tmp_path):
    from rw import graph
    from rw.pipeline import Session

    name = "rw_test_api_" + uuid4().hex
    session = Session(snapshot="snap-001", graph_name=name)
    contexts = []
    transcript_dir = tmp_path / "grounding"
    transcript_dir.mkdir()
    (transcript_dir / "fake-replay.json").write_text(json.dumps({"request_text": REQUEST,
        "model": "fake-grounder", "result": {"model": "fake-grounder", "live": True}}), encoding="utf-8")

    def fake_ground(request, tools, alternative_context=None):
        contexts.append(alternative_context)
        rows, log = graph.releases_for_service(session.g, "cart")
        assert not log["truncated"]
        version = "1.5" if alternative_context else "1.4"
        release = next(row for row in rows if row["version"] == version)
        history, _ = tools.release_history("cart")
        excerpt = next(ex for row in history if row["release_id"] == release["release_id"]
                       for ex in row["excerpts"] if ex["kind"] == "changelog")
        proposal = GroundingProposal(changes=[FleetEntry(service="cart", release_id=release["release_id"],
            flags={"basket_v2": False} if alternative_context else {})],
            citations=[Citation(excerpt_id=excerpt["excerpt_id"], content_hash=excerpt["content_hash"],
                                quote=excerpt["text"])], rationale="Fixed integration-test proposal")
        return GroundingResult(request_text=request, result=proposal, model="fake-grounder", live=True), None

    def fake_replay(path):
        from rw.grounding import GroundingTools
        result, _ = fake_ground(REQUEST, GroundingTools(session.g, session.snapshot_id))
        return result

    app = create_app(session_factory=lambda: Session(snapshot="snap-001", graph_name=name, reimport=False),
                     ground_function=fake_ground, replay_function=fake_replay, db_path=tmp_path / "sim.sqlite",
                     transcript_dir=transcript_dir)
    try:
        with TestClient(app) as client:
            yield client, contexts, app
    finally:
        # Only this test's uniquely named graph is removed.
        session.g.delete()


def create(client):
    response = client.post("/api/investigations", json={"request_text": REQUEST, "mode": "live"})
    assert response.status_code == 200, response.text
    return response.json()


def plan_url(state):
    return f"/api/investigations/{state['id']}/plans/{state['plan_hash']}"


def confirm(client, state):
    response = client.post(plan_url(state) + "/confirm-scope", json={"confirmed_by": "oncall:alice"})
    assert response.status_code == 200, response.text
    return response.json()


def test_blocked_then_alternative_pass_and_idempotent_simulation(api):
    client, contexts, _ = api
    initial = create(client)
    assert initial["grounding"]["live"] is True
    assert initial["grounding"]["model"] == "fake-grounder"
    assert not initial["validation_errors"]
    assert initial["plan"]["citations"][0]["quote"]
    assert next(f for f in initial["plan"]["fleet"] if f["service"] == "cart")["changed"] is True
    blocked = confirm(client, initial)
    assert blocked["verification"]["disposition"] == "BLOCKED"
    assert any(receipt["result"] == "FAIL" for receipt in blocked["verification"]["receipts"])
    assert blocked["verification"]["obligations"][0]["witness_path"]
    assert {q["name"] for q in blocked["queries"]} >= {"plan_reader_routes", "obligation_paths"}
    assert client.post(plan_url(initial) + "/approve", json={"approved_by": "oncall:alice"}).status_code == 409
    assert client.post(plan_url(initial) + "/simulate").status_code == 409

    response = client.post(f"/api/investigations/{initial['id']}/alternative")
    assert response.status_code == 200, response.text
    alternative = response.json()
    assert len(alternative["attempts"]) == 2
    assert alternative["plan_hash"] != initial["plan_hash"]
    assert alternative["report"] is None
    cart = next(f for f in alternative["plan"]["fleet"] if f["service"] == "cart")
    assert cart["flags"]["basket_v2"] is False
    assert "BLOCKED" in contexts[-1]
    assert "saved-cart-2002" in contexts[-1]
    assert client.post(plan_url(alternative) + "/approve", json={"approved_by": "oncall:alice"}).status_code == 409
    assert client.post(plan_url(alternative) + "/simulate").status_code == 409
    passing = confirm(client, alternative)
    assert passing["verification"]["disposition"] == "BOUNDED_PASS"
    assert not passing["verification"]["gaps"]
    assert all(receipt["result"] == "PASS" for receipt in passing["verification"]["receipts"])
    assert client.post(plan_url(alternative) + "/simulate").status_code == 409
    for identity in ("fake-grounder", "agent", "model", "gemini-3.8-flash"):
        assert client.post(plan_url(alternative) + "/approve", json={"approved_by": identity}).status_code == 409
    approval = client.post(plan_url(alternative) + "/approve", json={"approved_by": "oncall:alice"})
    assert approval.status_code == 200, approval.text
    assert approval.json()["plan_hash"] == alternative["plan_hash"]
    assert approval.json()["verification_hash"] == passing["verification_hash"]
    first = client.post(plan_url(alternative) + "/simulate")
    second = client.post(plan_url(alternative) + "/simulate")
    assert first.status_code == second.status_code == 200, first.text + second.text
    assert first.json()["applied"] is True
    assert second.json()["applied"] is False
    assert first.json()["idempotency_key"] == second.json()["idempotency_key"]
    third = client.post(f"/api/investigations/{initial['id']}/alternative")
    assert third.status_code == 409
    assert "limit" in third.json()["reason"]
    state = client.get(f"/api/investigations/{initial['id']}").json()
    assert len(state["attempts"]) == 2
    assert state["simulation"]["applied"] is False


def test_unconfirmed_plan_and_model_confirmation_refused(api):
    client, contexts, _ = api
    state = create(client)
    assert client.post(plan_url(state) + "/approve", json={"approved_by": "alice"}).status_code == 409
    assert client.post(plan_url(state) + "/simulate").status_code == 409
    for identity in ("agent", "model", "fake-grounder", " "):
        assert client.post(plan_url(state) + "/confirm-scope", json={"confirmed_by": identity}).status_code == 409
    assert client.post(f"/api/investigations/{state['id']}/alternative").status_code == 409
    assert contexts == [None]


def test_client_cannot_supply_verdicts_or_approval_fields(api):
    client, _, _ = api
    for field in ("disposition", "receipts", "approved_by", "plan", "graph_name"):
        response = client.post("/api/investigations", json={"request_text": REQUEST, field: "injected"})
        assert response.status_code == 422
    state = create(client)
    assert client.post(plan_url(state) + "/confirm-scope", json={
        "confirmed_by": "alice", "disposition": "BOUNDED_PASS"}).status_code == 422
    assert client.post(plan_url(state) + "/approve", json={
        "approved_by": "alice", "verification_hash": "injected"}).status_code == 422
    assert client.get("/api/investigations/missing").status_code == 404
    assert client.post(f"/api/investigations/{state['id']}/plans/missing/simulate").status_code == 404


def test_replay_is_labeled_and_request_bound(api):
    client, _, _ = api
    response = client.post("/api/investigations", json={
        "request_text": REQUEST, "mode": "replay", "replay_path": "fake-replay.json"})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["mode"] == "replay"
    assert state["grounding"]["live"] is False
    assert state["grounding"]["model"] == "replay:fake-replay.json"
    assert Path(state["transcript"]).name == "fake-replay.json"
    assert confirm(client, state)["verification"]["disposition"] == "BLOCKED"
    assert client.post(f"/api/investigations/{state['id']}/alternative").status_code == 409
    mismatch = client.post("/api/investigations", json={
        "request_text": "different request", "mode": "replay", "replay_path": "fake-replay.json"})
    assert mismatch.status_code == 409
    assert client.post("/api/investigations", json={"request_text": REQUEST, "mode": "replay"}).status_code == 422


def test_clarification(tmp_path):
    # Uses a real session too, even when grounding does not produce a plan.
    from rw.pipeline import Session
    name = "rw_test_api_" + uuid4().hex
    session = Session(graph_name=name)
    def clarify(request, tools, alternative_context=None):
        return GroundingResult(request_text=request, result=GroundingClarification(
            question="Which basket change?", unresolved=["basket"]), model="fake", live=True), None
    app = create_app(session_factory=lambda: session, ground_function=clarify, db_path=tmp_path / "sim.sqlite")
    try:
        with TestClient(app) as client:
            state = create(client)
            assert state["plan"] is None
            assert state["clarification"]["question"] == "Which basket change?"
    finally:
        session.g.delete()


@pytest.mark.parametrize("failure", ["adapter", "release", "citation"])
def test_grounding_validation_errors_prevent_plan(api, tmp_path, failure):
    client, _, original_app = api
    state = create(client)
    inv = original_app.state.investigations[state["id"]]
    source = inv.attempts[0].grounding
    proposal = source.result
    if failure == "release":
        proposal = proposal.model_copy(update={"changes": [FleetEntry(service="cart", release_id="invented")]})
    elif failure == "citation":
        citation = proposal.citations[0].model_copy(update={"quote": "invented quote"})
        proposal = proposal.model_copy(update={"citations": [citation]})
    result = source.model_copy(update={"result": proposal,
        "validation_errors": ["adapter rejected proposal"] if failure == "adapter" else []})
    def invalid_ground(request, tools, alternative_context=None):
        return result, None
    app = create_app(session_factory=lambda: inv.session, ground_function=invalid_ground,
                     db_path=tmp_path / "validation.sqlite")
    with TestClient(app) as other:
        rejected = create(other)
        assert rejected["plan"] is None
        assert rejected["validation_errors"]
        assert other.post(f"/api/investigations/{rejected['id']}/alternative").status_code == 409


def test_stale_disk_manifest_refused(api, monkeypatch):
    from rw import verification
    client, _, _ = api
    state = create(client)
    confirm(client, state)
    alternative = client.post(f"/api/investigations/{state['id']}/alternative").json()
    confirm(client, alternative)
    assert client.post(plan_url(alternative) + "/approve", json={"approved_by": "alice"}).status_code == 200
    original = verification.load_manifest
    reads = []
    def stale(root, snapshot):
        reads.append((root, snapshot))
        manifest, _ = original(root, snapshot)
        return manifest, "sha256:changed-on-disk"
    monkeypatch.setattr(verification, "load_manifest", stale)
    response = client.post(plan_url(alternative) + "/simulate")
    assert response.status_code == 409
    assert "stale" in response.json()["reason"]
    assert reads == [(Path(__file__).resolve().parents[1] / "fixtures/shop", "snap-001")]


def test_root():
    with TestClient(create_app()) as client:
        response = client.get("/")
        assert response.status_code == 200


def test_fleet_metadata_and_all_release_labels_are_graph_derived(api):
    from rw import graph
    client, _, app = api
    state = create(client)
    inv = app.state.investigations[state["id"]]
    cart_releases, _ = graph.releases_for_service(inv.session.g, "cart")
    cart_ids = {row["version"]: row["release_id"] for row in cart_releases}
    cart = next(entry for entry in state["plan"]["fleet"] if entry["service"] == "cart")
    assert cart["current_release_id"] == cart_ids["1.5"]
    assert cart["current_version"] == "1.5"
    assert cart["proposed_version"] == "1.4"
    assert state["plan"]["release_labels"][cart_ids["1.4"]] == "cart 1.4"
    assert state["release_labels"][cart_ids["1.5"]] == "cart 1.5"
    report = confirm(client, state)
    assert report["plan"]["fleet"][0]["current_version"]
    alternative = client.post(f"/api/investigations/{state['id']}/alternative").json()
    confirm(client, alternative)
    full = client.get(f"/api/investigations/{state['id']}").json()
    expected = {}
    current, _ = graph.current_fleet(inv.session.g, inv.session.snapshot_id)
    for service in {row["service"] for row in current}:
        releases, _ = graph.releases_for_service(inv.session.g, service)
        expected.update({r["release_id"]: f"{service} {r['version']}" for r in releases})

    def check_release_ids(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key != "release_labels":
                    check_release_ids(child)
        elif isinstance(value, list):
            for child in value:
                check_release_ids(child)
        elif isinstance(value, str) and value.startswith("release:"):
            assert full["release_labels"][value] == expected[value]

    check_release_ids(full)
    for attempt in full["attempts"]:
        assert attempt["plan"]["release_labels"] == full["release_labels"]
        for entry in attempt["plan"]["fleet"]:
            assert entry["current_release_id"]
            assert entry["current_version"]
            assert entry["proposed_version"]
        assert attempt["report"]["release_labels"] == full["release_labels"]
    # Presentation metadata never mutates the objects used for verification or approval.
    for attempt in inv.attempts:
        assert "release_labels" not in attempt.plan.model_dump()
        assert "release_labels" not in attempt.report
        assert "current_version" not in attempt.report["plan"]["fleet"][0]


def test_transcript_picker_lists_metadata_and_ignores_invalid_files(tmp_path):
    directory = tmp_path / "grounding"
    directory.mkdir()
    (directory / "saved.json").write_text(json.dumps({"request_text": REQUEST, "model": "original-model",
        "result": {"model": "original-model", "live": True}}), encoding="utf-8")
    (directory / "replayed.json").write_text(json.dumps({"request_text": "Replay example",
        "model": "replay:saved.json", "live": False}), encoding="utf-8")
    (directory / "broken.json").write_text("{invalid", encoding="utf-8")
    (directory / "unrelated.json").write_text("{}", encoding="utf-8")
    (directory / "array.json").write_text("[]", encoding="utf-8")
    (directory / "ignored.txt").write_text("not a transcript", encoding="utf-8")
    (directory / "subdirectory").mkdir()
    (directory / "subdirectory/nested.json").write_text("{}", encoding="utf-8")
    with TestClient(create_app(transcript_dir=directory)) as client:
        response = client.get("/api/transcripts")
        assert response.status_code == 200
        rows = {row["file_name"]: row for row in response.json()}
        assert set(rows) == {"saved.json", "replayed.json"}
        assert rows["saved.json"]["request_text"] == REQUEST
        assert rows["saved.json"]["model"] == "original-model"
        assert rows["saved.json"]["live"] is True
        assert rows["replayed.json"]["live"] is False
        assert rows["saved.json"]["mtime"].endswith("+00:00")
        assert rows["saved.json"]["replay_path"] == "saved.json"
    with TestClient(create_app(transcript_dir=tmp_path / "absent")) as client:
        assert client.get("/api/transcripts").json() == []


def test_transcript_picker_selection_replays(api):
    client, _, _ = api
    selected = client.get("/api/transcripts").json()[0]
    response = client.post("/api/investigations", json={
        "request_text": selected["request_text"], "mode": "replay", "replay_path": selected["replay_path"]})
    assert response.status_code == 200, response.text
    assert response.json()["grounding"]["live"] is False


@pytest.mark.parametrize("path", ["../outside.json", "artifacts/grounding/../outside.json",
    "C:/Windows/outside.json", "missing.json", "subdir/nested.json"])
def test_replay_rejects_outside_paths_before_grounding(api, path):
    client, contexts, _ = api
    response = client.post("/api/investigations", json={
        "request_text": REQUEST, "mode": "replay", "replay_path": path})
    assert response.status_code == 422
    assert "artifacts/grounding" in response.json()["detail"]
    assert contexts == []
    assert client.get("/api/investigations").json() == []


def test_replay_alternative_rejects_outside_path(api):
    client, contexts, _ = api
    state = client.post("/api/investigations", json={
        "request_text": REQUEST, "mode": "replay", "replay_path": "fake-replay.json"}).json()
    confirm(client, state)
    response = client.post(f"/api/investigations/{state['id']}/alternative",
                           json={"replay_path": "../outside.json"})
    assert response.status_code == 422
    assert contexts == [None]
    assert len(client.get(f"/api/investigations/{state['id']}").json()["attempts"]) == 1


def test_existing_outside_transcript_is_rejected_before_session_creation(tmp_path):
    directory = tmp_path / "grounding"
    directory.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"request_text": REQUEST, "model": "outside", "live": True}))
    def unexpected():
        pytest.fail("invalid replay path created a session")
    with TestClient(create_app(session_factory=unexpected, transcript_dir=directory)) as client:
        response = client.post("/api/investigations", json={
            "request_text": REQUEST, "mode": "replay", "replay_path": str(outside)})
        assert response.status_code == 422
        assert client.get("/api/transcripts").json() == []


def test_picker_with_real_replay_parser(api, tmp_path):
    client, _, original_app = api
    initial = create(client)
    session = original_app.state.investigations[initial["id"]].session
    directory = tmp_path / "real-grounding"
    directory.mkdir()
    args = {"question": "Which basket change?", "unresolved": ["basket"], "citations": []}
    response = {"candidates": [{"content": {"parts": [{"functionCall": {
        "name": "ask_clarification", "args": args}}]}}]}
    transcript = {"request_text": REQUEST, "alternative_context": None, "model": "recorded-model",
        "result": {"model": "recorded-model", "live": True},
        "events": [{"type": "model", "response": response},
                   {"type": "terminal", "name": "ask_clarification", "args": args}]}
    path = directory / "recorded.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")
    app = create_app(session_factory=lambda: session, transcript_dir=directory)
    with TestClient(app) as replay_client:
        selected = replay_client.get("/api/transcripts").json()[0]
        # Absolute paths inside the configured directory also remain valid.
        result = replay_client.post("/api/investigations", json={
            "request_text": selected["request_text"], "mode": "replay", "replay_path": str(path)})
        assert result.status_code == 200, result.text
        state = result.json()
        assert state["grounding"]["live"] is False
        assert state["grounding"]["model"] == "replay:recorded.json"
        assert state["clarification"]["question"] == "Which basket change?"
        assert state["plan"] is None


def test_list_investigations_tracks_latest_plan_disposition(api):
    client, _, _ = api
    assert client.get("/api/investigations").json() == []
    first = create(client)
    second = create(client)

    def listing():
        response = client.get("/api/investigations")
        assert response.status_code == 200
        return {row["id"]: row for row in response.json()}

    rows = listing()
    assert set(rows) == {first["id"], second["id"]}
    assert rows[first["id"]]["request_text"] == REQUEST
    assert rows[first["id"]]["latest_disposition"] is None
    confirm(client, first)
    assert listing()[first["id"]]["latest_disposition"] == "BLOCKED"
    alternative = client.post(f"/api/investigations/{first['id']}/alternative").json()
    assert listing()[first["id"]]["latest_disposition"] is None
    confirm(client, alternative)
    assert listing()[first["id"]]["latest_disposition"] == "BOUNDED_PASS"
    assert listing()[second["id"]]["latest_disposition"] is None
