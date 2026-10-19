"""Rehearse the incident investigation and validate genuine saved replays.

No simulation approval or deployment is performed. --live makes real configured model calls;
without it, --replay-dir validates a previously prepared bundle with fresh graph/probe checks.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
REQUEST = ("Japanese shoppers are seeing wrong totals since 3.2.0. Roll back accounting and "
           "fraud-detection to 3.1.0, their currency conversion is the suspect. Leave checkout alone.")
ANSWER = ("Yes, you may change checkout's declared localCurrencyCheckout flag to false. "
          "Keep the newer readers so they can still read the retained orders and ledger rows.")


def run_once(directory: Path, replay_paths: list[Path] | None = None, *, answer_text: str = ANSWER) -> dict:
    from rw import grounding
    from rw.contracts import ScopeConfirmation
    from rw.pipeline import Session, run_investigation

    session = Session(graph_name=f"rw_rehearsal_{uuid4().hex}", fixture_root=ROOT / "fixtures" / "astronomy-incident")
    paths = iter(replay_paths or [])
    def ground(request, tools, alternative_context=None):
        if replay_paths is not None:
            path = next(paths)
            return grounding.replay(path), path
        return grounding.ground(request, tools, alternative_context=alternative_context, artifact_dir=directory)
    def confirm(plan):
        return ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="demo rehearsal: checks only",
                                 confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        result = run_investigation(REQUEST, ground=ground, confirm=confirm, answer=lambda _: answer_text, session=session)
        (directory / "investigation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        attempts = result["attempts"]
        reports = [a["report"] for a in attempts if a.get("report")]
        summary = {"mode": "replay" if replay_paths is not None else "live", "outcomes": [a["outcome"] for a in attempts],
                   "checks": [len(r["verification"]["obligations"]) for r in reports],
                   "failures": [sum(x["result"] == "FAIL" for x in r["verification"]["receipts"]) for r in reports],
                   "transcripts": [a["transcript"] for a in attempts if a.get("transcript")],
                   "plan_hashes": [r["plan_hash"] for r in reports]}
        summary["ready"] = (summary["outcomes"][0] == "BLOCKED" and summary["outcomes"][-1] == "BOUNDED_PASS"
                            and summary["checks"] == [137, 137] and summary["failures"] == [48, 0])
        return summary
    finally:
        session.g.delete()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay-dir", type=Path)
    parser.add_argument("--runs", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--env-file", type=Path, help="optional local environment file; values are never printed")
    args = parser.parse_args()
    from rw import config
    if args.env_file:
        config.load_env(args.env_file)
    config.load_env()
    output = ROOT / "artifacts" / "demo-readiness" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True)
    summaries = []
    for number in range(args.runs):
        directory = output / f"run-{number + 1}"
        directory.mkdir()
        try:
            if args.live:
                summary = run_once(directory)
                if summary["ready"]:
                    replay_dir = directory / "validated-replay"
                    replay_dir.mkdir()
                    replayed = run_once(replay_dir, [Path(p) for p in summary["transcripts"]])
                    summary["replay_ready"] = replayed["ready"] and replayed["plan_hashes"] == summary["plan_hashes"]
                    if summary["replay_ready"]:
                        bundle = ROOT / "artifacts" / "demo" / "replays"
                        bundle.mkdir(parents=True, exist_ok=True)
                        copied = []
                        for index, path in enumerate(summary["transcripts"]):
                            destination = bundle / f"run-{number + 1}-{index + 1}-{Path(path).name}"
                            shutil.copy2(path, destination)
                            copied.append(destination.name)
                        (bundle / f"bundle-{number + 1}.json").write_text(json.dumps({
                            "fixture": "astronomy-incident", "request": REQUEST, "answer": ANSWER,
                            "transcripts": copied, "outcomes": summary["outcomes"],
                            "expected_plan_hashes": summary["plan_hashes"]}, indent=2), encoding="utf-8")
            else:
                manifests = sorted(args.replay_dir.glob("bundle-*.json"))
                if not manifests:
                    raise ValueError("no prepared replay bundle")
                bundle = json.loads(manifests[number % len(manifests)].read_text(encoding="utf-8"))
                summary = run_once(directory, [args.replay_dir / p for p in bundle["transcripts"]],
                                   answer_text=bundle["answer"])
                if bundle.get("expected_plan_hashes"):
                    summary["expected_plan_hashes_match"] = summary["plan_hashes"] == bundle["expected_plan_hashes"]
                    summary["ready"] = summary["ready"] and summary["expected_plan_hashes_match"]
        except Exception as exc:
            # Provider exception text may contain local connection details. Keep console output clean.
            summary = {"mode": "live" if args.live else "replay", "ready": False, "error_type": type(exc).__name__}
            from rw.grounding import GroundingError, provider_error_details
            if isinstance(exc, GroundingError):
                summary["provider_error"] = provider_error_details(exc)
        summaries.append(summary)
        print(json.dumps({k: v for k, v in summary.items() if k not in ("transcripts", "plan_hashes")}), flush=True)
        (output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"Readiness evidence: {output}")
    return 0 if all(s.get("ready") and (not args.live or s.get("replay_ready")) for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
