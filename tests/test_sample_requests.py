"""Sample requests are read from the fixture's sample_requests.json; a fixture without one shows none."""
import json

from fastapi.testclient import TestClient

from rw import pipeline
from rw.api import create_app

ASTRONOMY = pipeline.REPO_ROOT / "fixtures" / "astronomy-shop"


def samples(monkeypatch, root):
    monkeypatch.setattr(pipeline, "FIXTURE_ROOT", root)
    with TestClient(create_app(session_factory=lambda **_: None)) as client:
        return client.get("/api/samples").json()


def test_astronomy_shop_ships_sample_requests(monkeypatch):
    rows = samples(monkeypatch, ASTRONOMY)
    shipped = json.loads((ASTRONOMY / "sample_requests.json").read_text(encoding="utf-8"))
    assert [r["request"] for r in rows] == [r["request"] for r in shipped] and len(rows) >= 2


def test_fixture_without_samples_returns_none(monkeypatch, tmp_path):
    assert samples(monkeypatch, tmp_path) == []
