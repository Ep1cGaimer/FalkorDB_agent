"""Deterministic repository investigation; prints RepoFindings.to_dict() as JSON.

  .venv/Scripts/python.exe scripts/repo_investigate.py --repo NAME --rev REF [--config PATH] [--graph NAME] "question"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rw.repo.investigate import investigate  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--rev")
    ap.add_argument("--config")
    ap.add_argument("--graph")
    ap.add_argument("question")
    a = ap.parse_args(argv)
    res = investigate(a.repo, a.rev, a.question, graph_name=a.graph,
                      config=Path(a.config) if a.config else None)
    print(json.dumps(res.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
