"""Run the real live control test and product in same-model pairs, then save honest scores.

Usage: .venv/bin/python evals/run_comparison.py --runs 3
Uses the ignored .env, one pinned model, unique disposable graphs, and no action approval/simulation.
Stops after a failed pair, retaining its evidence. It never retries whole experiments until they pass.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from rw import config, grounding  # noqa: E402
from rw.contracts import ScopeConfirmation  # noqa: E402
from rw.pipeline import Session, run_investigation  # noqa: E402
import score_controls  # noqa: E402

REQUEST = "Undo the basket rollout, but keep the receipt correction."


def source_hashes() -> dict[str, str]:
    paths = [ROOT / "pyproject.toml"]
    for directory in ("src", "tests", "evals", "fixtures", "scripts"):
        paths.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts
                     and p.suffix in {".py", ".html", ".json", ".mjs"}
                     and "results" not in p.relative_to(ROOT).parts)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", help="exactly one provider:model; defaults to configured single model")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    models = [args.model] if args.model else grounding.configured_models()
    if args.runs < 1 or len(models) != 1 or "," in models[0]:
        parser.error("use a positive run count and exactly one model; fallback would invalidate pairing")
    model = ":".join(grounding.split_model(models[0]))
    if not grounding.has_credentials(model):
        parser.error("the selected provider's API key is not configured")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = (args.out or ROOT / "artifacts" / "issue-3" / f"comparison-{stamp}").resolve()
    out.mkdir(parents=True, exist_ok=False)  # Do not mix a new trial with older artifacts.
    for directory in ("controls", "reports", "logs", "pytest", "grounding"):
        (out / directory).mkdir()
    env = {**os.environ, "RW_GROUNDING_MODEL": model, "PYTHONUNBUFFERED": "1"}
    os.environ["RW_GROUNDING_MODEL"] = model
    metadata = {"started_at": stamp, "model": model, "request": REQUEST, "snapshot": "snap-001",
                "requested_pairs": args.runs, "source_hashes": source_hashes(), "pairs": [],
                "transport_settings": getattr(grounding.make_transport(model), "settings", {})}
    print(f"Live comparison: {model}; output={out}", flush=True)

    for index in range(1, args.runs + 1):
        print(f"Pair {index}/{args.runs}: running live control test", flush=True)
        log_path, junit = out / "logs" / f"control-{index}.log", out / "logs" / f"control-{index}.xml"
        base = out / "pytest" / str(index)
        with log_path.open("w") as log:
            os.chmod(log_path, 0o600)
            try:
                exit_code = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "-s", "-m", "live",
                     "tests/test_llm_control.py::test_live_control_runs_once", "--basetemp", str(base),
                     "--junitxml", str(junit)], cwd=ROOT, env=env, stdout=log,
                    stderr=subprocess.STDOUT, timeout=900).returncode
            except subprocess.TimeoutExpired:
                exit_code = 124
        totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        if junit.exists():
            for suite in ET.parse(junit).getroot().iter("testsuite"):
                for key in totals:
                    totals[key] += int(suite.get(key, 0))
        control_passed = exit_code == 0 and totals == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}
        files = sorted(base.rglob("llm_flat_*.json"))
        correct_model = len(files) == 1 and json.loads(files[0].read_text())["model"] == model
        for path in files:
            shutil.copy2(path, out / "controls" / path.name)

        print(f"Pair {index}: control passed={control_passed}; running product", flush=True)
        session = Session(graph_name="rw_issue3_" + uuid.uuid4().hex)
        try:
            def ground(request, tools, alternative_context=None):
                return grounding.ground(request, tools, alternative_context=alternative_context,
                                        models=[model], artifact_dir=out / "grounding")

            def confirm(plan):
                return ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="evaluation-scope",
                                         confirmed_at=datetime.now(timezone.utc).isoformat())

            try:
                report = run_investigation(REQUEST, ground=ground, confirm=confirm, session=session,
                                           allow_alternative=False)
            except grounding.GroundingError as exc:
                transcript = getattr(exc, "transcript_path", None)
                failure = json.loads(transcript.read_text()) if transcript else {}
                report = {"request": REQUEST, "snapshot": "snap-001", "attempts": [{
                    "outcome": "PROVIDER_ERROR", "error": str(exc),
                    "transcript": str(transcript) if transcript else None,
                    "grounding": {"model": model, "live": failure.get("live", False), "result": {}},
                    "provider_failed": True}]}
            (out / "reports" / f"product-{index}.json").write_text(json.dumps(report, indent=2))
        finally:
            session.g.delete()
        product_model = all(a["grounding"]["model"] == model and a["grounding"]["live"]
                            for a in report["attempts"])
        pair = {"index": index, "control_passed": control_passed, "control_junit": totals,
                "control_exit_code": exit_code, "same_model": correct_model and product_model,
                "product_outcomes": [a["outcome"] for a in report["attempts"]]}
        metadata["pairs"].append(pair)
        (out / "manifest.json").write_text(json.dumps(metadata, indent=2))
        print(json.dumps(pair), flush=True)
        if not control_passed or not pair["same_model"]:
            break

    output = io.StringIO()
    with redirect_stdout(output):
        score_controls.main(["--controls", str(out / "controls"), "--reports", str(out / "reports"),
                             "--json", str(out / "scores.json")])
    comparison = output.getvalue()
    (out / "comparison.md").write_text(comparison)
    metadata["source_unchanged_during_run"] = source_hashes() == metadata["source_hashes"]
    metadata["requested_pairs_complete"] = (len(metadata["pairs"]) == args.runs
                                            and all(p["control_passed"] and p["same_model"] for p in metadata["pairs"])
                                            and metadata["source_unchanged_during_run"])
    metadata["issue_3_complete"] = metadata["requested_pairs_complete"] and args.runs >= 3
    (out / "manifest.json").write_text(json.dumps(metadata, indent=2))
    print(comparison, flush=True)
    print(f"Requested pairs complete={metadata['requested_pairs_complete']}; "
          f"issue #3 complete={metadata['issue_3_complete']}; evidence={out}", flush=True)
    return 0 if metadata["requested_pairs_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
