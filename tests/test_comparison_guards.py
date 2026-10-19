"""Comparison views must stay bound to the original evidence and the same live model.

Use copied synthetic bytes, real FalkorDB obligations and real reader receipts. Only the
model response is replaced; mutations happen at the query/provider boundaries under test.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from rw import baseline, graph, grounding, pipeline
from rw.api import create_app
from rw.contracts import Citation, FleetEntry, GroundingProposal, GroundingResult


@pytest.fixture
def comparison(tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(Path(__file__).resolve().parents[1] / "fixtures/shop", root)
    name = "rw_test_comparison_" + uuid4().hex
    session = pipeline.Session(snapshot="snap-001", graph_name=name, fixture_root=root)

    def ground(request, tools, alternative_context=None):
        releases, _ = graph.releases_for_service(session.g, "cart")
        release = next(r for r in releases if r["version"] == "1.4")
        history, _ = tools.release_history("cart")
        excerpt = next(e for r in history if r["release_id"] == release["release_id"]
                       for e in r["excerpts"] if e["kind"] == "changelog")
        proposal = GroundingProposal(
            changes=[FleetEntry(service="cart", release_id=release["release_id"], flags={})],
            citations=[Citation(excerpt_id=excerpt["excerpt_id"], content_hash=excerpt["content_hash"],
                                quote=excerpt["text"])], rationale="fixed comparison proposal")
        return GroundingResult(request_text=request, result=proposal, model="groq:fake", live=True), None

    app = create_app(session_factory=lambda: pipeline.Session(snapshot="snap-001", graph_name=name,
                          reimport=False, fixture_root=root), ground_function=ground,
                     db_path=tmp_path / "sim.sqlite", transcript_dir=tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post("/api/investigations", json={"request_text": "Undo the basket rollout",
                                                                  "mode": "live"})
            assert response.status_code == 200, response.text
            state = response.json()
            url = f"/api/investigations/{state['id']}/plans/{state['plan_hash']}"
            response = client.post(url + "/confirm-scope", json={"confirmed_by": "oncall:alice"})
            assert response.status_code == 200, response.text
            assert response.json()["verification"]["disposition"] == "BLOCKED"
            inv = app.state.investigations[state["id"]]
            yield client, url, inv, root
    finally:
        session.g.delete()


def change_payload(root):
    manifest = json.loads((root / "snapshots/snap-001/manifest.json").read_text(encoding="utf-8"))
    record = next(r for s in manifest["stores"] for r in s["records"]
                  if r["record_id"] == "saved-cart-2002")
    path = root / record["payload"]
    path.write_bytes(path.read_bytes() + b"\n")


def test_ablation_snapshot_change_during_copy_is_evidence_drift(comparison, monkeypatch):
    client, url, _inv, root = comparison
    original_session = pipeline.Session

    def changed_copy(**kwargs):
        manifest = root / "snapshots/snap-001/manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        return original_session(**kwargs)

    monkeypatch.setattr(pipeline, "Session", changed_copy)
    assert_drift(client.post(url + "/ablation", json={"remove": ["DERIVED_FROM"]}))


def assert_drift(response):
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["drift"]
    assert body["reason"] == "evidence changed since verification; re-verify and re-approve"


def transport_stub(monkeypatch, during=lambda: None):
    calls = []

    def make_transport(model):
        def transport(body):
            calls.append((model, body))
            during()
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "disposition": "BLOCKED", "failing": {"cart": ["saved-cart-2002"]},
                "reason": "retained v2 cart requires the new reader"})}}]}
        transport.settings = {}
        return transport

    monkeypatch.setattr(grounding, "make_transport", make_transport)
    return calls


@pytest.mark.parametrize("endpoint", ["origins", "baseline", "ablation"])
def test_stale_verification_is_refused_before_comparison(comparison, monkeypatch, endpoint):
    client, url, _, root = comparison
    calls = transport_stub(monkeypatch)
    monkeypatch.setattr(pipeline, "ablate", lambda *a: pytest.fail("stale ablation must not run"))
    monkeypatch.setattr(graph, "record_origins", lambda *a, **kw: pytest.fail("stale origins must not run"))
    change_payload(root)
    response = (client.get(url + "/origins") if endpoint == "origins" else
                client.post(url + "/" + endpoint, json={"remove": ["READS_FROM"]}))
    assert_drift(response)
    assert not calls


def test_origins_uses_only_applicable_failures_and_exact_batches(comparison, monkeypatch):
    client, url, inv, _ = comparison
    verification = inv.attempts[0].report["verification"]
    failure = next(r for r in verification["receipts"] if r["result"] == "FAIL")
    stale = deepcopy(failure)
    stale["tuple"]["record_id"] = "stale-unrelated-record"
    verification["receipts"].append(stale)
    passed = deepcopy(next(r for r in verification["receipts"] if r["result"] == "PASS"))
    passed.update(result="FAIL", obligation_hash="sha256:" + "0" * 64)
    verification["receipts"].append(passed)
    expected = {r["tuple"]["batch_id"] for r in verification["receipts"]
                if r["result"] == "FAIL" and r is not stale and r is not passed}
    original = graph.record_origins
    calls = []

    def origins(g, snapshot, records, **kwargs):
        calls.append((records, kwargs))
        return original(g, snapshot, records, **kwargs)

    monkeypatch.setattr(graph, "record_origins", origins)
    response = client.get(url + "/origins")
    assert response.status_code == 200, response.text
    assert calls == [(["saved-cart-2002"], {"batch_ids": sorted(expected)})]
    body = response.json()
    assert {r["record_id"] for r in body["origins"]} == {"saved-cart-2002"}
    assert body["query"]["name"] == "record_origins"
    assert "DERIVED_FROM" in body["query"]["cypher"]


def test_origins_revalidates_after_query(comparison, monkeypatch):
    client, url, _, root = comparison
    original = graph.record_origins

    def origins(*args, **kwargs):
        result = original(*args, **kwargs)
        change_payload(root)
        return result

    monkeypatch.setattr(graph, "record_origins", origins)
    assert_drift(client.get(url + "/origins"))


def test_baseline_uses_grounding_model_and_blocked_receipts(comparison, monkeypatch):
    client, url, _, _ = comparison
    calls = transport_stub(monkeypatch)
    monkeypatch.setattr(grounding, "configured_models", lambda: pytest.fail("must use the actual model"))
    response = client.post(url + "/baseline")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(calls) == 1 and calls[0][0] == body["model"] == "groq:fake"
    assert body["live"] is True and body["check"]["confirmed"] == 1


@pytest.mark.parametrize("model,live", [("gemini:fake", True), ("replay:saved.json", False),
                                         ("groq:fake", False)])
def test_baseline_refuses_model_substitution_or_replay(comparison, monkeypatch, model, live):
    client, url, inv, _ = comparison
    attempt = inv.attempts[0]
    attempt.grounding = attempt.grounding.model_copy(update={"model": model, "live": live})
    calls = transport_stub(monkeypatch)
    monkeypatch.setattr(grounding, "configured_models", lambda: ["groq:other-model"])
    response = client.post(url + "/baseline")
    assert response.status_code == 409, response.text
    assert "same live" in response.json()["reason"]
    assert not calls


def test_baseline_refuses_payload_drift_during_provider(comparison, monkeypatch):
    client, url, _, root = comparison
    calls = transport_stub(monkeypatch, lambda: change_payload(root))
    assert_drift(client.post(url + "/baseline"))
    assert len(calls) == 1


def test_baseline_refuses_non_obligation_context_drift(comparison, monkeypatch):
    client, url, inv, root = comparison
    reader_paths = {Path(o["reader_codec_path"]).resolve()
                    for o in inv.attempts[0].report["verification"]["obligations"]}
    # A historical codec is baseline input even when no proposed reader uses it.
    path = next(p for p in sorted((root / "releases").glob("*/codec.py"))
                if p.resolve() not in reader_paths and p.parent.name == "checkout-2.0")
    calls = transport_stub(monkeypatch, lambda: path.write_bytes(path.read_bytes() + b"\n# changed context\n"))
    response = client.post(url + "/baseline")
    assert_drift(response)
    assert len(calls) == 1
    assert response.json()["detail"]["drift"] == ["baseline plaintext context changed during the model call"]


def test_baseline_revalidates_after_initial_context_capture(comparison, monkeypatch):
    client, url, _, root = comparison
    original = baseline.plaintext_context

    def context(*args):
        text = original(*args)
        change_payload(root)
        return text

    monkeypatch.setattr(baseline, "plaintext_context", context)
    calls = transport_stub(monkeypatch)
    assert_drift(client.post(url + "/baseline"))
    assert not calls


def test_ablation_revalidates_original_after_disposable_run(comparison, monkeypatch):
    client, url, _, root = comparison

    def ablate(*args):
        change_payload(root)
        return {"disposition": "NEEDS_EVIDENCE"}

    monkeypatch.setattr(pipeline, "ablate", ablate)
    assert_drift(client.post(url + "/ablation", json={"remove": ["READS_FROM"]}))
