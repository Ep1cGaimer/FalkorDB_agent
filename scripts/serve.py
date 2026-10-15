"""Serve the RollbackWitness console on http://127.0.0.1:8000 (synthetic fixture; local simulation only).

  .venv/Scripts/python.exe scripts/serve.py

Grounding is live by default; set RW_GROUNDING_MODEL to choose the model. Replay mode in the UI
reads a saved transcript and is always labeled "REPLAY — not live".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rw import config  # noqa: E402

config.load_env()  # .env before the app (and any grounding call) reads the environment

import uvicorn  # noqa: E402

from rw.api import create_app  # noqa: E402

HOST, PORT = "127.0.0.1", 8000

if __name__ == "__main__":
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")
