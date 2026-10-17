"""The modular workspace serves without a model key or graph initialization."""
from pathlib import Path
import mimetypes

from fastapi.testclient import TestClient
import pytest

from rw.api import create_app
from rw.contracts import bh


@pytest.mark.parametrize(("path", "content_type"), [
    ("/static/styles.css", "text/css"),
    ("/static/app.mjs", "javascript"),
    ("/static/views.mjs", "javascript"),
    ("/static/evidence.mjs", "javascript"),
    ("/static/explanations.mjs", "javascript"),
    ("/static/model.mjs", "javascript"),
    ("/static/api.mjs", "javascript"),
    ("/static/dom.mjs", "javascript"),
    ("/static/favicon.svg", "image/svg+xml"),
])
def test_workspace_assets_are_served_with_browser_content_types(path, content_type):
    with TestClient(create_app()) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]


def test_workspace_overrides_windows_plain_text_module_association(monkeypatch):
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, ".mjs", "text/plain")
    with TestClient(create_app()) as client:
        for path in (Path(__file__).resolve().parents[1] / "src/rw/static").glob("*.mjs"):
            response = client.get(f"/static/{path.name}")
            assert response.status_code == 200
            assert response.headers["content-type"].split(";")[0] == "text/javascript"


def test_snapshot_context_reads_actual_manifests_without_creating_an_investigation():
    def unexpected_session():
        raise AssertionError("Opening the workspace must not initialize a graph")

    root = Path(__file__).resolve().parents[1] / "fixtures" / "shop" / "snapshots"
    with TestClient(create_app(session_factory=unexpected_session)) as client:
        snapshots = client.get("/api/snapshots").json()
        assert [s["snapshot"] for s in snapshots] == ["snap-001", "snap-002-partial", "snap-003-orphan"]
        for snapshot in snapshots:
            assert snapshot["data_origin"] == "synthetic_fixture"
            assert snapshot["manifest_hash"] == bh((root / snapshot["snapshot"] / "manifest.json").read_bytes())
        assert snapshots[0]["deployments"][0]["version"] == "1.5"
        assert snapshots[0]["stores"][0]["coverage"] == "COMPLETE"
        assert snapshots[1]["stores"][0]["coverage"] == "PARTIAL"
        assert any(r["writer"] is None for r in snapshots[2]["stores"][0]["records"])
        assert client.get("/api/investigations").json() == []
