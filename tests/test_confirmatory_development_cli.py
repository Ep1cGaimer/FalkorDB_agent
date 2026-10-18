"""Public-input and capability boundaries for the development command."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("confirmatory.development_cli")


def arguments(monkeypatch, task, export, output):
    monkeypatch.setattr("sys.argv", ["development_cli", "--task", str(task), "--export", str(export),
                                   "--output", str(output), "--model", "models/development"])


def test_capability_map_exposes_only_declared_read_operations(module):
    names = {"search", "read_file", "list_files", "show_commit", "log", "is_ancestor", "diff", "list_refs", "show_ref"}
    calls = []
    source = SimpleNamespace(**{name: (lambda *a, _name=name, **kw: calls.append((_name, a, kw))) for name in names},
                             secret_method=lambda: (_ for _ in ()).throw(AssertionError("must not expose")))
    capabilities, descriptions = module.plaintext_capabilities(source)
    assert set(capabilities) == set(descriptions) == names
    capabilities["read_file"]("sha", "a.py", start=1, end=2)
    assert calls == [("read_file", ("sha", "a.py"), {"start": 1, "end": 2})]


def test_model_read_labels_physical_lines_without_changing_source_identity(module):
    names = {"search", "list_files", "show_commit", "log", "is_ancestor", "diff", "list_refs", "show_ref"}
    raw = {"citation": {"start_line": 101, "end_line": 102, "content_hash": "a" * 64},
           "content": "left\u2028right\r\nlast", "next_line": 103}
    source = SimpleNamespace(**{name: lambda **kw: None for name in names}, read_file=lambda **kw: raw)
    tools, _ = module.plaintext_capabilities(source)
    value = tools["read_file"](revision="sha", path="a.py", start=101)
    assert value["content"] == "101 | left\u2028right\r\n102 | last"
    assert value["citation"] == raw["citation"] and value["next_line"] == 103
    assert raw["content"] == "left\u2028right\r\nlast"


def test_sealed_task_path_is_rejected_before_any_read(module, monkeypatch, tmp_path):
    task = tmp_path / "sealed" / "oracle.json"
    arguments(monkeypatch, task, tmp_path / "export", tmp_path / "output")
    with pytest.raises(ValueError, match="sealed"):
        module.main()
    assert not (tmp_path / "output").exists()


def test_symlink_to_sealed_data_is_rejected_before_read(module, monkeypatch, tmp_path):
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    target = sealed / "oracle.json"
    target.write_text("This is not allowed runner input")
    link = tmp_path / "public-link.json"
    link.symlink_to(target)
    arguments(monkeypatch, link, tmp_path / "export", tmp_path / "output")
    with pytest.raises(ValueError, match="sealed"):
        module.main()


def test_confirmatory_task_is_rejected_before_loading_export_or_credentials(module, monkeypatch, tmp_path):
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "CF-REQ-DEP-01", "repository": "unused", "revision": None, "question": "unused"}))
    arguments(monkeypatch, task, tmp_path / "missing-export", tmp_path / "output")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="confirmatory"):
        module.main()
    assert not (tmp_path / "output").exists()
