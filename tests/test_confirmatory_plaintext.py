"""Baseline capabilities and isolation using development source only."""
import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return (importlib.import_module("confirmatory.corpus_export"),
            importlib.import_module("confirmatory.plaintext_tools"))


@pytest.fixture
def source(tmp_path, modules):
    exporter, baseline = modules
    repo = tmp_path / "development"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env).decode().strip()
    git("init", "-q")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.py").write_text("def alpha():\n    return 1\n# alpha calls beta\n")
    (repo / "skip.txt").write_text("DO-NOT-RETURN-EXCLUDED-CONTENT")
    git("add", ".")
    git("commit", "-qm", "initial version")
    old = git("rev-parse", "HEAD")
    git("tag", "release", old)
    (repo / "pkg" / "a.py").write_text("def alpha():\n    return 2\n# alpha calls gamma\n")
    (repo / "pkg" / "b.py").write_text("def beta():\n    return alpha()\n")
    git("add", ".")
    git("commit", "-qm", "change alpha and add beta")
    new = git("rev-parse", "HEAD")
    out = tmp_path / "export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "dev",
        "roots": [new], "include": ["pkg/*.py"], "exclude": []}, out)
    return baseline.PlaintextTools(out), old, new, out


def test_followup_read_can_use_returned_next_line_without_repeating_end(modules, tmp_path):
    exporter, baseline = modules
    repo = tmp_path / "followup"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "-C", str(repo), *args]).decode().strip()
    git("init", "-q")
    expected = [f"# line {i}\n" for i in range(1, 252)]
    (repo / "long.py").write_text("".join(expected))
    git("add", "."); git("commit", "-qm", "source")
    sha = git("rev-parse", "HEAD")
    export = tmp_path / "followup-export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "followup",
        "roots": [sha], "include": ["*.py"], "exclude": []}, export)
    tools = baseline.PlaintextTools(export)
    pages, start = [], 1
    while start is not None:
        page = tools.read_file(sha, "long.py", start=start)
        pages.append(page)
        start = page["next_line"]
    assert "".join(p["content"] for p in pages) == "".join(expected)
    assert [(p["citation"]["start_line"], p["citation"]["end_line"]) for p in pages] == [(1,100),(101,200),(201,251)]


def test_explicit_reversed_followup_bounds_remain_invalid(source, modules):
    tools, old, _new, _out = source
    with pytest.raises(modules[1].CorpusError):
        tools.read_file(old, "pkg/a.py", start=2, end=1)


def test_empty_directories_and_git_name_order_reconstruct_exact_tree_id(modules, tmp_path):
    exporter, baseline = modules
    repo = tmp_path / "trees"
    repo.mkdir()
    subprocess.check_call(["git", "-C", str(repo), "init", "-q"])
    def plumbing(*args, data=None):
        return subprocess.check_output(["git", "-C", str(repo), "-c", "user.name=Test",
                                        "-c", "user.email=test@example.invalid", *args], input=data).strip()
    empty_tree = plumbing("mktree", data=b"")
    blob = plumbing("hash-object", "-w", "--stdin", data=b"text\n")
    # These names test Git's directory sorting rule: a. sorts before a/.
    tree = plumbing("mktree", data=b"040000 tree " + empty_tree + b"\ta\n100644 blob " + blob + b"\ta.\n")
    commit = plumbing("commit-tree", tree.decode(), data=b"empty directory\n").decode()
    out = tmp_path / "export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "dev",
        "roots": [commit], "include": ["*"], "exclude": []}, out)
    tools = baseline.PlaintextTools(out)
    assert [e["path"] for e in tools.list_files(commit)["items"]] == ["a."]
    assert tools.search(commit, "text")["total"] == 1


def test_iterative_search_source_read_and_revision_specific_provenance(source):
    tools, old, new, _ = source
    page = tools.search("release", "alpha", limit=1)
    assert page["commit"] == old and page["truncated"] and not page["complete"]
    second = tools.search(old, "alpha", limit=1, cursor=page["next_cursor"])
    assert not second["truncated"] and second["complete"]
    assert [p["items"][0]["citation"]["start_line"] for p in [page, second]] == [1, 3]
    before = tools.read_file(old, "pkg/a.py", start=2, end=2)
    after = tools.read_file(new, "pkg/a.py", start=2, end=2)
    assert before["content"] == "    return 1\n" and after["content"] == "    return 2\n"
    assert before["citation"]["content_hash"] != after["citation"]["content_hash"]
    assert before["citation"]["commit"] == old and after["citation"]["commit"] == new


def test_history_ancestry_and_diff_have_no_present_fix_inference(source):
    tools, old, new, _ = source
    history = tools.log(new)
    assert [x["oid"] for x in history["items"]] == [new, old]
    assert tools.log(old, text="change")["total"] == 0
    assert tools.is_ancestor(old, new)["is_ancestor"]
    assert not tools.is_ancestor(new, old)["is_ancestor"]
    assert "fix is present" in tools.is_ancestor(old, new)["limitation"]
    patch = tools.diff(old, new, "pkg/a.py")
    assert "-    return 1" in patch["patch"] and "+    return 2" in patch["patch"]
    assert tools.diff(old, new, "pkg/b.py")["old_blob"] is None
    assert tools.diff(new, old, "pkg/b.py")["new_blob"] is None


def test_cursor_rejects_revision_query_and_corpus_switches(source, modules):
    tools, old, new, _ = source
    _, baseline = modules
    cursor = tools.search(old, "alpha", limit=1)["next_cursor"]
    for sha, query in [(new, "alpha"), (old, "beta")]:
        with pytest.raises(baseline.CorpusError, match="cursor"):
            tools.search(sha, query, cursor=cursor)
    tools.corpus_hash = "f" * 64
    with pytest.raises(baseline.CorpusError, match="cursor"):
        tools.search(old, "alpha", cursor=cursor)


def test_excluded_missing_and_path_traversal_reads_cannot_escape_export(source, modules):
    tools, old, _, _ = source
    _, baseline = modules
    for path in ["skip.txt", "../receipt.json", "/etc/passwd", "pkg/b.py"]:
        with pytest.raises(baseline.CorpusError):
            tools.read_file(old, path)
    result = tools.search(old, "DO-NOT-RETURN")
    assert result["items"] == [] and result["coverage_gaps"]
    assert result["coverage_gaps"][0]["reason"] == "outside_include_rules"


def test_load_rejects_corrupted_corpus(source, modules):
    _, _, _, out = source
    _, baseline = modules
    with (out / "corpus.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(baseline.CorpusError, match="hash"):
        baseline.PlaintextTools(out)


@pytest.mark.parametrize("field", ["parent", "tree_path", "blob"])
def test_object_provenance_checked_even_if_outer_receipt_is_recomputed(source, modules, field):
    _, _, _, out = source
    exporter, baseline = modules
    rows = [json.loads(x) for x in (out / "corpus.jsonl").read_bytes().splitlines()]
    if field == "parent":
        next(x for x in rows if x.get("kind") == "commit")["parents"] = ["f" * 40]
    elif field == "tree_path":
        next(x for x in rows if x.get("kind") == "tree")["entries"][0]["path"] = "forged.py"
    else:
        next(x for x in rows if x.get("kind") == "blob")["content"] = "forged source"
    data = b"".join(exporter.canonical(x) for x in rows)
    (out / "corpus.jsonl").write_bytes(data)
    receipt = json.loads((out / "receipt.json").read_text())
    receipt["corpus_sha256"] = hashlib.sha256(data).hexdigest()
    (out / "receipt.json").write_bytes(exporter.canonical(receipt))
    with pytest.raises(baseline.CorpusError, match="immutable|digest"):
        baseline.PlaintextTools(out)


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1, 201), (True, 2), (2000, 2001)])
def test_invalid_or_unbounded_source_spans_are_visible_errors(source, modules, start, end):
    tools, old, _, _ = source
    _, baseline = modules
    with pytest.raises(baseline.CorpusError):
        tools.read_file(old, "pkg/a.py", start=start, end=end)


@pytest.fixture
def reviewed_source(tmp_path, modules):
    """Independent review's five counterexamples, using Git objects only."""
    exporter, baseline = modules
    repo = tmp_path / "review-patterns"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
    def git(*args, data=None):
        return subprocess.check_output(["git", "-C", str(repo), *args], input=data, env=env).strip()
    git("init", "-q")
    (repo / "unicode.py").write_bytes("x = 'left\u2028right\u0085tail\v'\r\nneedle = 2\n".encode())
    (repo / "long.py").write_text("#" + "a" * 300000 + "\n")
    (repo / "no_newline.py").write_bytes(b"a")
    git("add", ".")
    tree = git("write-tree").decode()
    old = git("-c", "i18n.commitEncoding=ISO-8859-1", "commit-tree", tree,
              data=b"plain-ascii-subject\n\nnon-UTF8 byte: \xff\n").decode()
    git("update-ref", "refs/heads/main", old)
    git("tag", "-am", "ANNOTATED_TAG_ONLY_EVIDENCE", "release", old)
    git("-c", "advice.nestedTag=false", "tag", "-am", "NESTED_TAG_MESSAGE", "nested", "release")
    (repo / "no_newline.py").write_bytes(b"b")
    git("add", ".")
    new = git("commit-tree", git("write-tree").decode(), "-p", old, data=b"new state\n").decode()
    git("update-ref", "refs/heads/main", new)
    out = tmp_path / "review-export"
    exporter.export_corpus(repo, {"schema": "source-corpus-spec/v1", "repository": "dev",
        "roots": [new], "include": ["*.py"], "exclude": []}, out)
    return baseline.PlaintextTools(out), old, new, git, out


def test_source_citations_follow_physical_lf_lines_with_unicode_and_crlf(reviewed_source):
    tools, _, new, _, _ = reviewed_source
    found = tools.search(new, "needle")["items"][0]
    assert found["citation"]["start_line"] == 2
    span = tools.read_file(new, "unicode.py", start=2, end=2)
    assert span["content"] == "needle = 2\n" and span["total_lines"] == 2
    assert tools.read_file(new, "unicode.py", start=1, end=1)["content"].endswith("\r\n")


def test_log_search_decodes_declared_commit_encoding(reviewed_source):
    tools, old, new, _, _ = reviewed_source
    found = tools.log(new, text="plain-ascii-subject")
    assert found["total"] == 1 and found["items"][0]["oid"] == old
    shown = tools.show_commit(old)
    assert shown["text_encoding"].lower() == "iso-8859-1"
    assert "non-UTF8 byte: ÿ" in shown["decoded_text"]


def test_annotated_and_nested_tag_metadata_are_retrievable_and_hash_checked(reviewed_source):
    tools, old, _, _, _ = reviewed_source
    refs = tools.list_refs(text="ANNOTATED_TAG_ONLY_EVIDENCE")
    assert {x["name"] for x in refs["items"]} == {"refs/tags/release", "refs/tags/nested"}
    shown = tools.show_ref("refs/tags/nested")
    assert shown["target"] == old and len(shown["tag_chain"]) == 2
    assert shown["tag_chain"][0]["oid"] == shown["oid"]
    assert "NESTED_TAG_MESSAGE" in shown["tag_chain"][0]["decoded_text"]


def test_missing_terminal_newline_diff_is_accepted_by_git(reviewed_source):
    tools, old, new, git, _ = reviewed_source
    patch = tools.diff(old, new, "no_newline.py")["patch"]
    assert "\\ No newline at end of file" in patch
    assert git("apply", "--numstat", "-", data=patch.encode()).decode().startswith("1\t1\t")


def test_one_line_cannot_bypass_output_byte_limit(reviewed_source, modules):
    tools, _, new, _, _ = reviewed_source
    _, baseline = modules
    with pytest.raises(baseline.ToolBudgetExceeded, match="output_bytes"):
        tools.read_file(new, "long.py", start=1, end=1)
    with pytest.raises(baseline.ToolBudgetExceeded, match="output_bytes"):
        tools.search(new, "aaa", limit=1)


def test_coverage_metadata_cannot_admit_excluded_content_after_receipt_rehash(source, modules):
    _, _, _, out = source
    exporter, baseline = modules
    rows = [json.loads(x) for x in (out / "corpus.jsonl").read_bytes().splitlines()]
    entry = next(e for row in rows if row["kind"] == "tree" for e in row["entries"] if e["path"] == "skip.txt")
    entry["coverage"] = "included"
    data = b"".join(exporter.canonical(row) for row in rows)
    (out / "corpus.jsonl").write_bytes(data)
    receipt = json.loads((out / "receipt.json").read_text())
    receipt["corpus_sha256"] = hashlib.sha256(data).hexdigest()
    (out / "receipt.json").write_bytes(exporter.canonical(receipt))
    with pytest.raises(baseline.CorpusError, match="coverage"):
        baseline.PlaintextTools(out)
