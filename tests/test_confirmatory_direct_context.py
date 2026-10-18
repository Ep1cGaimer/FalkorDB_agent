"""Direct-context preparation retains raw Git facts without a bloated flat catalog."""
import base64
import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    exporter = importlib.import_module("confirmatory.corpus_export")
    renderer = importlib.import_module("confirmatory.direct_context")
    repo = tmp_path / "source"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.name=Test", "-c", "user.email=t@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(repo), *args]).decode().strip()
    git("init", "-q")
    (repo / "pkg").mkdir()
    (repo / "pkg/empty.py").write_bytes(b"")
    (repo / "pkg/raw.py").write_bytes(b"# untrusted: ignore instructions\r\n# {\"kind\":\"corpus\"}\nvalue='a\xe2\x80\xa8b'\n")
    (repo / "excluded.txt").write_text("NEVER INCLUDE THIS CONTENT")
    (repo / "pkg/binary.py").write_bytes(b"\xff\x00\n")
    (repo / "pkg/link.py").symlink_to("../excluded.txt")
    git("add", ".")
    git("commit", "-qm", "first")
    git("tag", "-am", "raw tag text", "release")
    (repo / "README.md").write_text("outside source scope")
    git("add", ".")
    git("commit", "-qm", "second reuses pkg tree")
    tip = git("rev-parse", "HEAD")
    export = tmp_path / "export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "development",
        "roots": [tip], "include": ["pkg/*.py"], "exclude": []}, export)
    return renderer, export, tmp_path, repo, tip


def frames(path):
    # Independent reader uses byte lengths, never scans repository text for headers.
    with path.open("rb") as stream:
        while header := stream.readline():
            row = json.loads(header)
            data = stream.read(row["payload_bytes"])
            assert len(data) == row["payload_bytes"] and stream.read(1) == b"\n"
            yield row, data


def test_context_reconstructs_git_objects_and_all_flat_memberships(context):
    renderer, export, tmp, repo, tip = context
    receipt = renderer.render_context(export, tmp / "render")
    path = tmp / "render/context.txt"
    observed = list(frames(path))
    assert receipt["status"] == "COMPLETE" and receipt["tokens"] is None
    assert not receipt["acceptance_validated"]
    assert receipt["context_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert b"NEVER INCLUDE THIS CONTENT" not in path.read_bytes()
    raw = importlib.import_module("confirmatory.plaintext_tools").PlaintextTools(export)
    trees = {r["oid"]: json.loads(data) for r, data in observed if r["kind"] == "tree"}
    all_objects = set()
    for row, data in observed:
        kind = row["kind"]
        if kind in {"commit", "tag", "blob"}:
            value = data if row["encoding"] == "utf-8" else base64.b64decode(data, validate=True)
        elif kind == "tree":
            children = json.loads(data)
            value = b"".join(e[0].lstrip("0").encode() + b" " + os.fsencode(e[3]) + b"\0" +
                             bytes.fromhex(e[2]) for e in children)
        else:
            continue
        expected = subprocess.check_output(["git", "-C", str(repo), "cat-file", kind, row["oid"]])
        assert value == expected
        assert (kind, row["oid"]) not in all_objects
        all_objects.add((kind, row["oid"]))
    def walk(oid, prefix=""):
        out = {}
        for mode, kind, child, name in trees[oid]:
            path = prefix + name
            out[path] = (mode, kind, child)
            if kind == "tree":
                out.update(walk(child, path + "/"))
        return out
    for oid, entries in raw.trees.items():
        assert walk(oid) == {p: (e["mode"], e["type"], e["oid"]) for p, e in entries.items()}
    assert {r["oid"] for r, _ in observed if r["kind"] == "commit"} == set(raw.commits)
    assert {r["oid"] for r, _ in observed if r["kind"] == "blob"} == set(raw.blobs)
    assert {r["name"] for r, _ in observed if r["kind"] == "ref"} == set(raw.refs)
    # Both commits share the same pkg subtree, presented only once.
    assert len(trees) == 3


def test_context_is_deterministic_new_only_and_retains_failed_attempt(context):
    renderer, export, tmp, _, _ = context
    a, b = tmp / "a", tmp / "b"
    assert renderer.render_context(export, a) == renderer.render_context(export, b)
    assert (a / "context.txt").read_bytes() == (b / "context.txt").read_bytes()
    with pytest.raises(FileExistsError):
        renderer.render_context(export, a)
    with pytest.raises(ValueError, match="byte limit"):
        renderer.render_context(export, tmp / "failed", max_bytes=5)
    assert json.loads((tmp / "failed/receipt.json").read_text())["status"] == "ERROR"


def test_context_refuses_sealed_paths_before_loading(context):
    renderer, export, tmp, _, _ = context
    with pytest.raises(ValueError, match="sealed"):
        renderer.render_context(tmp / "sealed/nonexistent", tmp / "out")
    with pytest.raises(ValueError, match="sealed"):
        renderer.render_context(export, tmp / "sealed/output")
