"""Index a configured repository into FalkorDB; prints the IndexReport as JSON.

  .venv/Scripts/python.exe scripts/repo_index.py --config repos/<name>.json [--graph NAME]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rw.repo.config import load_config  # noqa: E402
from rw.repo.index import index_repository  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--graph")
    a = ap.parse_args(argv)
    report = index_repository(load_config(Path(a.config)), graph_name=a.graph)
    print(json.dumps(asdict(report), default=str))
    return 0 if report.status == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
