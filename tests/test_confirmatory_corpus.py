"""Source-only corpus invariants on development Git histories; no heldouts read."""
import base64
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("confirmatory.corpus_export")


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Development Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Development Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
           "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00"}
    return subprocess.check_output(["git", "-C", str(repo), *args], env=env).decode().strip()


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "source with spaces é"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "outside.txt").write_text("def repeated(): return 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "excluded source first")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.py").write_bytes((repo / "outside.txt").read_bytes())
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "included alias of same blob")
    middle = git(repo, "rev-parse", "HEAD")
    git(repo, "mv", "pkg/a.py", "pkg/moved.py")
    (repo / "pkg" / "moved.py").write_text("def repeated(): return 2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "rename with edit")
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "-am", "annotated release", "release", middle)
    return repo, [first, middle, tip]


def spec(roots):
    return {"schema": "source-corpus-spec/v1", "repository": "development",
            "roots": roots, "include": ["pkg/*.py"], "exclude": ["pkg/skip.py"]}


def records(out):
    return [json.loads(x) for x in (out / "corpus.jsonl").read_text().splitlines()]


def test_all_historical_memberships_and_alias_blobs_are_preserved(corpus, history, tmp_path):
    repo, shas = history
    out = tmp_path / "export"
    receipt = corpus.export_corpus(repo, spec([shas[-1]]), out)
    rows = records(out)
    assert receipt["commits"] == 3 and receipt["included_unique_blobs"] == 2
    assert receipt["tokens"] is None and not receipt["acceptance_validated"]
    commits = {x["oid"]: x for x in rows if x["kind"] == "commit"}
    trees = {x["oid"]: x["entries"] for x in rows if x["kind"] == "tree"}
    assert commits[shas[0]]["parents"] == []
    assert commits[shas[-1]]["parents"] == [shas[1]]
    assert [x["path"] for x in trees[commits[shas[1]]["tree"]] if x["coverage"] == "included"] == ["pkg/a.py"]
    assert [x["path"] for x in trees[commits[shas[2]]["tree"]] if x["coverage"] == "included"] == ["pkg/moved.py"]
    blobs = {x["oid"] for x in rows if x["kind"] == "blob"}
    first_alias = trees[commits[shas[0]]["tree"]][0]
    assert first_alias["coverage"] == "outside_include_rules" and first_alias["oid"] in blobs
    tag = next(x for x in rows if x.get("name") == "refs/tags/release")
    assert tag["target"] == shas[1] and "annotated release" in tag["tag_chain"][0]["content"]


def test_serialization_is_deterministic_and_never_overwritten(corpus, history, tmp_path):
    repo, shas = history
    a, b = tmp_path / "a", tmp_path / "b"
    ra = corpus.export_corpus(repo, spec([shas[-1], shas[0]]), a)
    rb = corpus.export_corpus(repo, spec([shas[0], shas[-1], shas[-1]]), b)
    assert ra == rb
    assert (a / "corpus.jsonl").read_bytes() == (b / "corpus.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        corpus.export_corpus(repo, spec([shas[-1]]), a)
    assert json.loads((a / "receipt.json").read_text())["status"] == "COMPLETE"


def test_symlinks_and_repository_programs_are_not_executed_or_followed(corpus, history, tmp_path):
    repo, _ = history
    marker = tmp_path / "execution-canary"
    secret = tmp_path / "outside-secret"
    secret.write_text("DO NOT INCLUDE THIS EXTERNAL FILE")
    (repo / "pkg" / "escape.py").symlink_to(secret)
    (repo / "pkg" / "skip.py").write_text("EXCLUDED-BY-RULE")
    (repo / "pkg" / "payload.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "adversarial source")
    (repo / ".git" / "hooks" / "post-checkout").write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    (repo / ".git" / "hooks" / "post-checkout").chmod(0o755)
    out = tmp_path / "export"
    corpus.export_corpus(repo, spec([git(repo, "rev-parse", "HEAD")]), out)
    text = (out / "corpus.jsonl").read_text()
    assert not marker.exists()
    assert secret.read_text() not in text and "EXCLUDED-BY-RULE" not in text
    assert any(x["coverage"] == "symlink_not_followed" for row in records(out)
               if row["kind"] == "tree" for x in row["entries"])


def test_binary_blob_and_non_utf8_path_round_trip(corpus, history, tmp_path):
    repo, _ = history
    name = b"pkg/nonutf8-\xff.py"
    raw = b"\xff\x00\xfe\n"
    # macOS cannot materialize this filename; Git's object database can. Build
    # the tree with plumbing so the same byte-preservation check runs everywhere.
    def plumbing(*args, data=None):
        return subprocess.check_output(["git", "-C", str(repo), "-c", "user.name=Test",
                                        "-c", "user.email=test@example.invalid", *args], input=data)
    blob_id = plumbing("hash-object", "-w", "--stdin", data=raw).strip()
    pkg_entries = plumbing("ls-tree", "-z", "HEAD:pkg")
    pkg_entries += b"100644 blob " + blob_id + b"\t" + name.split(b"/", 1)[1] + b"\0"
    pkg_tree = plumbing("mktree", "-z", data=pkg_entries).strip()
    root_entries = plumbing("ls-tree", "-z", "HEAD").split(b"\0")
    root_entries = [b"040000 tree " + pkg_tree + b"\tpkg" if x.endswith(b"\tpkg") else x
                    for x in root_entries if x]
    root = plumbing("mktree", "-z", data=b"\0".join(root_entries) + b"\0").decode().strip()
    tip = plumbing("commit-tree", root, "-p", "HEAD", data=b"raw bytes\n").decode().strip()
    out = tmp_path / "export"
    corpus.export_corpus(repo, spec([tip]), out)
    rows = records(out)
    blob = next(x for x in rows if x["kind"] == "blob" and x["encoding"] == "base64")
    assert base64.b64decode(blob["content"]) == raw
    paths = [x["path"] for row in rows if row["kind"] == "tree" for x in row["entries"]]
    assert name.decode("utf8", "surrogateescape") in paths


@pytest.mark.parametrize("roots", [["HEAD"], ["--all"], [], ["f" * 39]])
def test_mutable_or_invalid_roots_are_rejected_before_writing(corpus, history, tmp_path, roots):
    repo, _ = history
    out = tmp_path / "export"
    with pytest.raises(ValueError, match="immutable"):
        corpus.export_corpus(repo, spec(roots), out)
    assert not out.exists()


def test_shallow_history_is_not_published_as_complete(corpus, history, tmp_path):
    repo, shas = history
    shallow = tmp_path / "shallow"
    subprocess.check_call(["git", "clone", "-q", "--depth=1", repo.as_uri(), str(shallow)])
    out = tmp_path / "export"
    with pytest.raises(ValueError, match="shallow"):
        corpus.export_corpus(shallow, spec([shas[-1]]), out)
    assert not out.exists()


def test_failed_attempt_is_retained_without_completed_digest(corpus, history, tmp_path, monkeypatch):
    repo, shas = history
    def fail(*_):
        raise RuntimeError("injected unavailable object")
    monkeypatch.setattr(corpus.GitRepo, "blob", fail)
    out = tmp_path / "export"
    with pytest.raises(RuntimeError):
        corpus.export_corpus(repo, spec([shas[-1]]), out)
    receipt = json.loads((out / "receipt.json").read_text())
    assert receipt["status"] == "FAILED" and "corpus_sha256" not in receipt
    assert (out / "corpus.jsonl").stat().st_size > 0


def test_noncommit_tag_does_not_fail_export_or_expand_source_scope(corpus, history, tmp_path):
    repo, shas = history
    blob = git(repo, "rev-parse", "HEAD:pkg/moved.py")
    git(repo, "tag", "a-blob-tag", blob)
    git(repo, "tag", "-am", "tagged blob", "annotated-blob", blob)
    out = tmp_path / "export"
    receipt = corpus.export_corpus(repo, spec([shas[1]]), out)
    assert receipt["counts"]["refs_not_commits"] == 2
    assert receipt["counts"]["refs_outside_corpus"] >= 1
    assert {x["oid"] for x in records(out) if x["kind"] == "commit"} == set(shas[:2])
