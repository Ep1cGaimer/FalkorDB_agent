"""Browser QA server: deterministic, visibly labeled grounding; real graph and reader probes.

Run only for UI checks: .venv/Scripts/python.exe tests/ui/serve_fixture.py
Uses its own graph, a temporary simulation ledger, and port 8002. Calls no model.
"""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import uvicorn
from rw.api import create_app
from rw.contracts import Citation, FleetEntry, GroundingClarification, GroundingProposal, GroundingResult
from rw.pipeline import Session


def main():
    graph_name = "rw_ui_check_" + uuid4().hex
    initial = Session(graph_name=graph_name)
    print(f"Browser QA graph={graph_name}", flush=True)

    def ground(request, tools, alternative_context=None):
        history, _ = tools.release_history("cart")
        version = "1.5" if alternative_context else "1.4"
        release = next(row for row in history if row["version"] == version)
        excerpt = next(ex for ex in release["excerpts"] if ex["kind"] == "changelog")
        citation = Citation(excerpt_id=excerpt["excerpt_id"], content_hash=excerpt["content_hash"], quote=excerpt["text"])
        if request.startswith("Clarify") and "Operator answered:" not in request:
            result = GroundingClarification(question="Keep Checkout 2.1 and its receipt correction while changing Cart only?",
                                            unresolved=["checkout scope"], citations=[citation])
        else:
            result = GroundingProposal(changes=[FleetEntry(service="cart", release_id=release["release_id"],
                flags={"basket_v2": False} if alternative_context else {})], citations=[citation],
                rationale="Browser QA fixture: retain Checkout 2.1; " + ("keep Cart's newer reader and disable basket_v2." if alternative_context else "select the earlier Cart build."))
        return GroundingResult(request_text=request, result=result, model="deterministic-ui-check", live=False), None

    with TemporaryDirectory(prefix="rw-ui-ledger-") as temporary:
        app = create_app(session_factory=lambda snapshot="snap-001": Session(snapshot=snapshot, graph_name=graph_name, reimport=False),
                         ground_function=ground, db_path=Path(temporary) / "sim.sqlite",
                         transcript_dir=Path(temporary) / "replays")
        try:
            uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")
        finally:
            initial.g.delete()


if __name__ == "__main__":
    main()
