"""Run the actual browser data helpers under Node; skip when Node is absent."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ui_replay_matcher_under_node():
    test_files = sorted((ROOT / "tests" / "js").glob("*.test.mjs"))
    assert test_files
    proc = subprocess.run(["node", "--test", *map(str, test_files)], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
