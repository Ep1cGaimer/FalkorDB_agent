"""Reject oversized immutable source inputs before fetching their payloads."""
import subprocess

import pytest

from rw.repo.budget import BudgetExhausted, ReadBudget, ReadLimits, read_scope
from rw.repo.git import GitRepo


def repository(tmp_path):
    path = tmp_path / "source limits"
    path.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.name=Source budget test",
            "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
            "-C", str(path), *args]).decode().strip()
    git("init", "-q")
    return path, git


@pytest.mark.parametrize("size", [207, 159984])
def test_oversized_blob_is_rejected_before_payload_command(tmp_path, monkeypatch, size):
    path, command = repository(tmp_path)
    (path / "a.py").write_bytes(b"x" * size)
    oid = command("hash-object", "-w", "a.py")
    git = GitRepo(path)
    seen = []
    original = git._proc
    def observed(*args, **kwargs):
        seen.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(git, "_proc", observed)
    with read_scope(ReadLimits(source_bytes=1)) as budget:
        with pytest.raises(BudgetExhausted, match="source_bytes"):
            git.blob(oid)
        assert budget.source_bytes <= 1
    assert ("cat-file", "blob", oid) not in seen


@pytest.mark.parametrize("data", [b"", b"x" * 128])
def test_empty_and_exact_fitting_blob_remain_available(tmp_path, data):
    path, command = repository(tmp_path)
    (path / "a.py").write_bytes(data)
    oid = command("hash-object", "-w", "a.py")
    with read_scope(ReadLimits(source_bytes=max(1, len(data)))):
        assert GitRepo(path).blob(oid) == data


@pytest.mark.parametrize("operation", ["patch", "patch_id"])
def test_diff_source_inputs_are_checked_before_patch_generation(tmp_path, monkeypatch, operation):
    path, command = repository(tmp_path)
    (path / "a.py").write_text("old value\n" * 200)
    command("add", "."); command("commit", "-qm", "before")
    parent = command("rev-parse", "HEAD")
    (path / "a.py").write_text("new value\n" * 200)
    command("add", "."); command("commit", "-qm", "after")
    child = command("rev-parse", "HEAD")
    git = GitRepo(path)
    original = git._proc
    seen = []
    def observed(*args, **kwargs):
        seen.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(git, "_proc", observed)
    with read_scope(ReadLimits(source_bytes=1)) as budget:
        with pytest.raises(BudgetExhausted, match="source_bytes"):
            git.patch(parent, child) if operation == "patch" else git.patch_id(child)
        assert budget.source_bytes <= 1
    assert not any("-p" in args for args in seen)


def test_declined_source_reservation_does_not_report_bytes_as_consumed():
    budget = ReadBudget(ReadLimits(source_bytes=4))
    budget.consume_source(2)
    with pytest.raises(BudgetExhausted):
        budget.consume_source(3)
    assert budget.source_bytes == 2


@pytest.mark.parametrize("operation", ["patch", "patch_id"])
def test_fitting_diff_preserves_output_and_shares_source_reservations(tmp_path, operation):
    path, command = repository(tmp_path)
    filename = "space\né.py"
    old, new = b"old content\n", b"new content\n"
    (path / filename).write_bytes(old)
    command("add", "."); command("commit", "-qm", "before")
    parent = command("rev-parse", "HEAD")
    (path / filename).write_bytes(new)
    command("add", "."); command("commit", "-qm", "after")
    child = command("rev-parse", "HEAD")
    git = GitRepo(path)
    def read():
        return git.patch(parent, child) if operation == "patch" else git.patch_id(child)
    expected = read()
    assert expected
    with read_scope(ReadLimits(source_bytes=len(old) + len(new))) as budget:
        assert read() == expected
        assert budget.source_bytes == len(old) + len(new)
        with pytest.raises(BudgetExhausted):
            read()
        assert budget.source_bytes == len(old) + len(new)


def test_root_and_deleted_diff_sources_have_exact_reservations(tmp_path):
    path, command = repository(tmp_path)
    data = b"root source\n"
    (path / "a.py").write_bytes(data)
    command("add", "."); command("commit", "-qm", "root")
    root = command("rev-parse", "HEAD")
    git = GitRepo(path)
    expected = git.patch_id(root)
    with read_scope(ReadLimits(source_bytes=len(data))) as budget:
        assert git.patch_id(root) == expected
        assert budget.source_bytes == len(data)
    command("rm", "a.py"); command("commit", "-qm", "delete")
    deleted = command("rev-parse", "HEAD")
    expected = git.patch(root, deleted)
    with read_scope(ReadLimits(source_bytes=len(data))) as budget:
        assert git.patch(root, deleted) == expected
        assert budget.source_bytes == len(data)
