"""Reference integrity on independent development Git bytes, never answer oracles."""
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    exporter = importlib.import_module("confirmatory.corpus_export")
    plain = importlib.import_module("confirmatory.plaintext_tools")
    repo = tmp_path / "development"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    def git(*args):
        return subprocess.check_output(["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                                        "-C", str(repo), *args], env=env).decode().strip()
    git("init", "-q")
    (repo / "a.py").write_text("LABEL = 'left\u2028right'\ndef run():\n    return 1\n# final\n")
    (repo / "empty.py").write_bytes(b"")
    git("add", ".")
    git("commit", "-qm", "first")
    old = git("rev-parse", "HEAD")
    git("tag", "-am", "original tag message", "release")
    (repo / "a.py").write_text("LABEL = 'left\u2028right'\ndef run():\n    return 2\n# final\n")
    git("add", ".")
    git("commit", "-qm", "second")
    new = git("rev-parse", "HEAD")
    out = tmp_path / "export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "development",
        "roots": [new], "include": ["*.py"], "exclude": []}, out)
    return plain.PlaintextTools(out), old, new, out


def trace_result(tool, result, *, status="OK", arguments=None):
    return {"tool": tool, "arguments": arguments or {}, "response": {"status": status, "result": result}}


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_cli_rejects_wrong_repository_citation_after_real_retrieval(corpus, tmp_path, monkeypatch, protocol):
    raw, _, new, export = corpus
    cli = importlib.import_module("confirmatory.development_cli")
    valid = raw.read_file(new, "a.py", start=2, end=3)["citation"]
    final = {"answer": "The function returns 2.", "citations": [{**valid, "repository": "WRONG"}],
             "gaps": ["runtime unverified"], "runtime_disposition": None}
    actions = [{"action": "call", "name": "read_file", "arguments": {"revision": new, "path": "a.py", "start": 2, "end": 3}},
               {"action": "finish"}, final]
    class API:
        def __init__(self, model, *args, **kwargs):
            self.model, self.calls = model, 0
        def count(self, *args):
            return {"totalTokens": 100}
        def generate(self, request, *args):
            action = actions[self.calls]
            self.calls += 1
            parts = ([{"functionCall": {
                "name": action["name"] if action["action"] == "call" else "finish_investigation",
                "args": action.get("arguments", {})}}] if request.get("tools")
                else [{"text": json.dumps(action)}])
            return {"modelVersion": "development-fake", "usageMetadata": {"promptTokenCount": 100,
                "candidatesTokenCount": 20, "totalTokenCount": 120}, "candidates": [{"finishReason": "STOP",
                "content": {"parts": parts}}]}
    monkeypatch.setattr(cli, "GeminiAPI", API)
    monkeypatch.setenv("GEMINI_API_KEY", "development-not-a-real-key")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "DEV-CITATION", "repository": raw.repository, "revision": new, "question": "What does run return?"}))
    output = tmp_path / "attempt"
    monkeypatch.setattr("sys.argv", ["development_cli", "--export", str(export), "--task", str(task),
                                    "--output", str(output), "--model", "models/development", "--decision-protocol", protocol])
    code = cli.main()
    result = json.loads((output / "result.json").read_text())
    assert code == 1 and result["status"] == "ERROR" and result["answer"] is None
    assert result["failure"] == "FINAL_CITATION_REJECTED"
    assert result["model_usage"]["calls"] == 3
    events = (output / "events.jsonl").read_text()
    assert '"repository": "WRONG"' in events or '\\"repository\\": \\"WRONG\\"' in events


@pytest.fixture
def guard(corpus):
    return importlib.import_module("confirmatory.citation_guard").CitationGuard(corpus[0])


def test_narrow_and_adjacent_source_spans_are_valid_references_only(guard, corpus):
    raw, _, new, _ = corpus
    a, b = raw.read_file(new, "a.py", start=1, end=2), raw.read_file(new, "a.py", start=3, end=4)
    citation = {**a["citation"], "start_line": 2, "end_line": 3}
    report = guard.verify([citation], [trace_result("read_file", a), trace_result("read_file", b)])
    assert report["valid"] and report["references_checked"] == 1
    assert report["material_claim_grounding"] == "UNSCORED"


@pytest.mark.parametrize("mutation,reason", [
    ({"repository": "wrong"}, "WRONG_REPOSITORY"),
    ({"commit": "f" * 40}, "UNKNOWN_REVISION"),
    ({"path": "../outside.py"}, "SOURCE_OUTSIDE_CORPUS"),
    ({"content_hash": "a" * 64}, "CONTENT_HASH_MISMATCH"),
    ({"start_line": True}, "INVALID_SOURCE_SPAN"),
    ({"end_line": 20}, "INVALID_SOURCE_SPAN"),
])
def test_fabricated_source_reference_is_rejected(guard, corpus, mutation, reason):
    raw, _, new, _ = corpus
    evidence = raw.read_file(new, "a.py")
    report = guard.verify([{**evidence["citation"], **mutation}], [trace_result("read_file", evidence)])
    assert not report["valid"] and report["errors"][0]["reason"] == reason


def test_existing_but_unretrieved_revision_cannot_support_citation(guard, corpus):
    raw, old, new, _ = corpus
    old_read, new_read = raw.read_file(old, "a.py"), raw.read_file(new, "a.py")
    report = guard.verify([old_read["citation"]], [trace_result("read_file", new_read)])
    assert not report["valid"] and report["errors"][0]["reason"] == "SOURCE_SPAN_NOT_RETRIEVED"


def test_gap_between_retrieved_spans_cannot_be_cited_as_contiguous(guard, corpus):
    raw, _, new, _ = corpus
    first, last = raw.read_file(new, "a.py", start=1, end=1), raw.read_file(new, "a.py", start=4, end=4)
    citation = {**first["citation"], "end_line": 4}
    assert not guard.verify([citation], [trace_result("read_file", first), trace_result("read_file", last)])["valid"]


def test_failed_calls_arguments_and_source_embedded_json_are_not_returned_proofs(guard, corpus):
    raw, _, new, _ = corpus
    read = raw.read_file(new, "a.py")
    traces = [trace_result("read_file", read, status="ERROR"),
              trace_result("read_file", {"content": json.dumps(read["citation"])}, arguments={"forged": read["citation"]})]
    report = guard.verify([read["citation"]], traces)
    assert not report["valid"]


def test_commit_and_annotated_tag_proofs_require_returned_immutable_objects(guard, corpus):
    raw, old, new, _ = corpus
    commit, tag = raw.show_commit(old), raw.show_ref("refs/tags/release")
    citations = [{"proof_type": "git_object", "repository": raw.repository, "object_type": "commit", "oid": old},
                 {"proof_type": "git_object", "repository": raw.repository, "object_type": "tag", "oid": tag["oid"]}]
    trace = [trace_result("show_commit", commit), trace_result("show_ref", tag)]
    assert guard.verify(citations, trace)["valid"]
    assert not guard.verify([{**citations[0], "oid": new}], trace)["valid"]


def test_diff_and_ancestry_proofs_preserve_exact_revision_and_result_identity(guard, corpus):
    raw, old, new, _ = corpus
    diff = raw.diff(old, new, "a.py")
    ancestry = raw.is_ancestor(old, new)
    a = {k: diff[k] for k in ["repository", "old_commit", "new_commit", "path", "old_content_hash", "new_content_hash"]}
    a["proof_type"] = "diff"
    b = {k: ancestry[k] for k in ["repository", "ancestor", "descendant", "is_ancestor"]}
    b["proof_type"] = "ancestry"
    trace = [trace_result("diff", diff), trace_result("is_ancestor", ancestry)]
    assert guard.verify([a, b], trace)["valid"]
    assert not guard.verify([{**b, "is_ancestor": False}], trace)["valid"]


def test_empty_citation_list_is_not_an_automatic_grounding_pass(guard):
    report = guard.verify([], [])
    assert report["references_checked"] == 0 and report["material_claim_grounding"] == "UNSCORED"


def test_validation_deadline_is_enforced_without_reading_more_evidence(guard, corpus):
    raw, _, new, _ = corpus
    report = guard.verify([raw.read_file(new, "a.py")["citation"]], [], deadline=0, clock=lambda: 1)
    assert not report["valid"] and report["errors"][0]["reason"] == "VALIDATION_DEADLINE_EXHAUSTED"


@pytest.mark.parametrize("citation", [
    {"proof_type": "ref", "repository": "development", "name": [], "oid": "a", "target": "a"},
    {"proof_type": "git_object", "repository": "development", "object_type": {}, "oid": "a"},
    {"proof_type": ["source"]},
    {"proof_type": "ancestry", "repository": "development", "ancestor": [], "descendant": "a", "is_ancestor": True},
])
def test_malformed_proof_types_produce_a_rejection_report_not_an_exception(guard, citation):
    report = guard.verify([citation], [])
    assert not report["valid"] and len(report["errors"]) == 1


def test_file_membership_requires_returned_tree_metadata_and_does_not_invent_lines(guard, corpus):
    raw, _, new, _ = corpus
    files = raw.list_files(new)
    entry = next(e for e in files["items"] if e["path"] == "a.py")
    blob = raw.blobs[entry["oid"]]
    citation = {"proof_type": "file_membership", "repository": raw.repository, "commit": new,
                "path": "a.py", "git_blob": entry["oid"], "content_hash": blob["sha256"]}
    assert guard.verify([citation], [trace_result("list_files", files)])["valid"]
    assert not guard.verify([citation], [])["valid"]
    assert not guard.verify([{**citation, "start_line": 999}], [trace_result("list_files", files)])["valid"]


def test_empty_file_read_returns_membership_without_an_invented_source_span(guard, corpus):
    raw, _, new, _ = corpus
    evidence = raw.read_file(new, "empty.py")
    assert evidence["content"] == "" and evidence["total_lines"] == 0
    assert evidence["complete_file"] and evidence["next_line"] is None
    citation = evidence["citation"]
    assert citation["proof_type"] == "file_membership"
    assert "start_line" not in citation and "end_line" not in citation
    assert guard.verify([citation], [trace_result("read_file", evidence)])["valid"]
    assert not guard.verify([citation], [])["valid"]
    with pytest.raises(ValueError, match="start line beyond"):
        raw.read_file(new, "empty.py", start=2)


def test_listed_included_files_expose_the_membership_identity_to_the_model(guard, corpus):
    raw, _, new, _ = corpus
    files = raw.list_files(new)
    entry = next(e for e in files["items"] if e["path"] == "empty.py")
    citation = {"proof_type": "file_membership", "repository": raw.repository, "commit": new,
                "path": entry["path"], "git_blob": entry["oid"], "content_hash": entry["content_hash"]}
    assert guard.verify([citation], [trace_result("list_files", files)])["valid"]
