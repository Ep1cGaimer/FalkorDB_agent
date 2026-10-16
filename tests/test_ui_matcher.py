"""Run the extracted UI replay matcher under `node --test` (skipped when node is absent).

The matcher and its `withAnswer` mirror live between markers in src/rw/static/index.html so this
test exercises the real shipped source, not a copy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ui_replay_matcher_under_node():
    test_file = ROOT / "tests" / "js" / "replay_matcher.test.mjs"
    assert test_file.is_file()
    proc = subprocess.run(["node", "--test", str(test_file)], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
