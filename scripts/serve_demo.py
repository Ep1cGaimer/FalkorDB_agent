"""Serve the incident demo with a fixture-specific replay directory.

    .venv/Scripts/python.exe scripts/serve_demo.py --port 8000
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--env-file", type=Path, help="optional local environment file; values are never printed")
    args = parser.parse_args()
    from rw import config
    if args.env_file:
        config.load_env(args.env_file)
    config.load_env()
    os.environ["RW_FIXTURE"] = "astronomy-incident"
    from rw import grounding
    from rw.api import create_app
    import uvicorn

    replays = ROOT / "artifacts" / "demo" / "replays"
    replays.mkdir(parents=True, exist_ok=True)
    def ground(request, tools, alternative_context=None):
        return grounding.ground(request, tools, alternative_context=alternative_context,
                                artifact_dir=replays)
    uvicorn.run(create_app(ground_function=ground, transcript_dir=replays,
                          db_path=ROOT / "artifacts" / "demo" / "simulation.sqlite"),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
