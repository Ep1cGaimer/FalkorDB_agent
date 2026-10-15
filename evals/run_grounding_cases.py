"""Repeatable grounding eval: run every request in ``evals/grounding_cases/requests.json`` N times
through the REAL grounding loop and print the observed outcomes as a markdown table.

Each run happens against a temporary FalkorDB graph freshly imported from ``fixtures/shop``
(``snap-001``) and deleted afterwards, so every case starts from the same fleet and releases. The
loop is the product's own: ``rw.grounding.ground`` over the configured ``RW_GROUNDING_MODEL`` chain
with the shared provider transports. Each transcript is saved by ``ground()`` under
``artifacts/grounding/``; the table (plus its metadata) is written to
``evals/results/grounding_<timestamp>.md`` (git-ignored) and printed.

The expected kinds in ``evals/grounding_cases/expected.json`` are independent documentation, written
by hand: they are never imported by ``src/`` and are never a gate on the model — the table only
reports whether the observed kind matched. ``ABORTED`` (no terminal call within MAX_TURNS) and
``ERROR`` (every provider attempt failed) are recorded as observed, never as a pass.

Usage (live; ``.env`` supplies ``GROQ_API_KEY``):
    .venv\\Scripts\\python.exe evals\\run_grounding_cases.py --runs 2
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from rw import config, grounding  # noqa: E402

CASES_DIR = REPO_ROOT / "evals" / "grounding_cases"
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "shop"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
SNAPSHOT = "snap-001"
GRAPH_PREFIX = "rw_test_grounding_eval_"   # unique temp graph; deleted at the end
OUTER_ATTEMPTS = 3                          # the provider is flaky (503 / TLS resets), on top of the transport's own retries

COLUMNS = ("case", "run", "model", "kind", "proposed fleet", "citations", "validation errors", "matches expected")


# --------------------------------------------------------------------------- case files

def load_cases(cases_dir: Path | str = CASES_DIR) -> list[dict]:
    """The request cases, in file order; every case needs a string id and text."""
    raw = json.loads((Path(cases_dir) / "requests.json").read_text(encoding="utf-8"))
    cases = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            raise ValueError(f"malformed case in requests.json: {item!r}")
        cases.append({"id": item["id"], "text": item["text"]})
    if not cases:
        raise ValueError("requests.json has no cases")
    return cases


def load_expected(cases_dir: Path | str = CASES_DIR) -> dict[str, str]:
    """case id -> expected kind (documentation only; never read by ``src/``)."""
    raw = json.loads((Path(cases_dir) / "expected.json").read_text(encoding="utf-8"))
    return {k: v.get("kind") for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict) and isinstance(v.get("kind"), str)}


# --------------------------------------------------------------------------- transcript facts

def excerpt_kinds(events: list[dict]) -> dict[str, str]:
    """excerpt_id -> kind (changelog/code) for every excerpt row a tool actually returned."""
    kinds: dict[str, str] = {}
    for event in events or []:
        if not isinstance(event, dict) or event.get("type") != "tool":
            continue
        for row in event.get("rows") or []:
            if not isinstance(row, dict):
                continue
            if row.get("excerpt_id"):
                kinds[row["excerpt_id"]] = row.get("kind")
            for ex in row.get("excerpts") or []:
                if isinstance(ex, dict) and ex.get("excerpt_id"):
                    kinds[ex["excerpt_id"]] = ex.get("kind")
    return kinds


def release_versions(events: list[dict]) -> dict[str, str]:
    """release_id -> human version label, learned only from trusted tool rows."""
    out: dict[str, str] = {}
    for event in events or []:
        if not isinstance(event, dict) or event.get("type") != "tool":
            continue
        for row in event.get("rows") or []:
            if isinstance(row, dict) and row.get("release_id") and row.get("version"):
                out[row["release_id"]] = row["version"]
    return out


# --------------------------------------------------------------------------- table (pure)

def _cell(value: Any) -> str:
    """One markdown table cell: no pipes, no newlines, empty reads as an em dash."""
    text = "" if value is None else str(value)
    text = " ".join(text.split()).replace("|", "\\|")
    return text or "—"


def fleet_cell(fleet: dict[str, Any], versions: dict[str, str] | None = None) -> str:
    """`service=version{flag=on,other=off}; ...` for {service: {"version"|"release_id", "flags"}}."""
    versions = versions or {}
    parts = []
    for service in sorted(fleet or {}):
        spec = fleet[service] or {}
        version = spec.get("version") or versions.get(spec.get("release_id"), spec.get("release_id"))
        flags = spec.get("flags") or {}
        suffix = "{" + ",".join(f"{name}={'on' if on else 'off'}" for name, on in sorted(flags.items())) + "}" \
            if flags else ""
        parts.append(f"{service}={version or '?'}{suffix}")
    return "; ".join(parts) or "—"


def build_table(rows: list[dict]) -> str:
    """Markdown table with one line per run. Pure: it only formats the summary rows it is given."""
    header = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in COLUMNS) + "|"
    lines = [header, rule]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(key)) for key in
                                       ("case", "run", "model", "kind", "fleet", "citations", "errors", "match")) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- live runs

def summarize(case_id: str, run_index: int, gr: Any, events: list[dict], expected_kind: str | None,
              transcript_path: str = "") -> dict:
    """One table row from a finished ``ground()`` result and its saved transcript events."""
    kinds = excerpt_kinds(events)
    versions = release_versions(events)
    result = gr.result
    if grounding.is_aborted(gr):
        kind, fleet = "ABORTED", "—"
    elif getattr(result, "kind", None) == "PROPOSAL":
        kind = "PROPOSAL"
        fleet = fleet_cell({c.service: {"release_id": c.release_id, "flags": dict(c.flags)}
                            for c in result.changes}, versions)
    else:
        kind, fleet = "CLARIFICATION", "—"
    counts: dict[str, int] = {}
    for citation in getattr(result, "citations", []) or []:
        name = kinds.get(citation.excerpt_id) or "unknown"
        counts[name] = counts.get(name, 0) + 1
    citations = ", ".join(f"{name} x{count}" for name, count in sorted(counts.items())) or "—"
    return {
        "case": case_id,
        "run": run_index,
        "model": gr.model,
        "kind": kind,
        "fleet": fleet,
        "citations": citations,
        "errors": "; ".join(gr.validation_errors) or "—",
        "expected": expected_kind or "—",
        "match": ("yes" if kind == expected_kind else "no") if expected_kind else "—",
        "transcript": transcript_path,
    }


def run_case(case: dict, run_index: int, tools: Any, expected_kind: str | None,
             models: list[str] | None = None, artifact_dir: Path | None = None) -> dict:
    """Run one case once through ``grounding.ground``; provider failures are retried, then recorded."""
    last: Exception | None = None
    for attempt in range(OUTER_ATTEMPTS):
        try:
            gr, path = grounding.ground(case["text"], tools, models=models, artifact_dir=artifact_dir)
        except grounding.GroundingError as exc:
            last = exc
            print(f"  {case['id']} run {run_index} attempt {attempt + 1}/{OUTER_ATTEMPTS} failed: {exc}",
                  file=sys.stderr)
            continue
        events = json.loads(Path(path).read_text(encoding="utf-8")).get("events") or []
        return summarize(case["id"], run_index, gr, events, expected_kind, str(path))
    kind = f"ERROR after {OUTER_ATTEMPTS} provider attempts"
    return {"case": case["id"], "run": run_index, "model": "—", "kind": kind, "fleet": "—", "citations": "—",
            "errors": str(last), "expected": expected_kind or "—",
            "match": "no" if expected_kind else "—", "transcript": ""}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def report_markdown(rows: list[dict], meta: dict) -> str:
    """Metadata + the table, exactly as printed and saved to ``evals/results/``."""
    lines = [
        f"# Grounding cases — {meta['stamp']}",
        "",
        f"- chain: `{meta['chain']}`",
        f"- fixture: `{meta['fixture']}` snapshot `{meta['snapshot']}` (temp graph `{meta['graph']}`, deleted after)",
        f"- runs per case: {meta['runs']} · turns cap: {grounding.MAX_TURNS} · temperature 0 (product loop)",
        f"- models that answered: {meta['models']}",
        f"- expected kinds (independent documentation, never imported by `src/`): {meta['expected']}",
        "",
        build_table(rows),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the grounding cases live and print a markdown table.")
    ap.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    ap.add_argument("--out", default=str(RESULTS_DIR), help="directory for the saved table")
    args = ap.parse_args(argv)
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2

    config.load_env()  # GROQ_API_KEY from the git-ignored .env; never printed
    chain = grounding.configured_models()
    cases = load_cases()
    expected = load_expected()
    stamp = _stamp()
    graph_name = f"{GRAPH_PREFIX}{uuid.uuid4().hex[:8]}"
    print(f"grounding eval: {len(cases)} cases x {args.runs} runs | chain={chain} | graph={graph_name}",
          file=sys.stderr)

    from rw import graph as graph_mod  # lazy: the table builder needs no database

    db = graph_mod.connect()
    try:
        graph_mod.reset_and_import(db, graph_name, FIXTURE_ROOT, [SNAPSHOT])
        tools = grounding.GroundingTools(db.select_graph(graph_name))
        rows: list[dict] = []
        for case in cases:
            for run_index in range(1, args.runs + 1):
                row = run_case(case, run_index, tools, expected.get(case["id"]))
                rows.append(row)
                print(f"  {row['case']} run {row['run']}: {row['kind']} "
                      f"(model={row['model']}, fleet={row['fleet']})", file=sys.stderr)
    finally:
        try:
            db.select_graph(graph_name).delete()
        except Exception:
            pass

    meta = {
        "stamp": stamp,
        "chain": ",".join(chain),
        "fixture": FIXTURE_ROOT.relative_to(REPO_ROOT).as_posix(),
        "snapshot": SNAPSHOT,
        "graph": graph_name,
        "runs": args.runs,
        "models": ", ".join(sorted({r["model"] for r in rows})) or "—",
        "expected": ", ".join(f"{c['id']}={expected.get(c['id'], '—')}" for c in cases),
    }
    text = report_markdown(rows, meta)
    print(text)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"grounding_{stamp}.md"
    path.write_text(text, encoding="utf-8")
    print(f"table written to {path}")

    errored = [r for r in rows if r["kind"].startswith("ERROR")]
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
