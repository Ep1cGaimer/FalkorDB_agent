"""Terminal driver for one RollbackWitness investigation (synthetic fixture).

  .venv/Scripts/python.exe scripts/investigate.py "Undo the basket rollout, but keep the receipt correction."
  ... --confirm-as alice      # non-interactive: the operator named on the command line confirms scope
  ... --replay artifacts/grounding/<file>.json   # labeled replay of a saved live transcript

Scope confirmation is a human step; this script never approves or simulates an action.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rw import config, grounding  # noqa: E402
from rw.contracts import CandidatePlan, ScopeConfirmation  # noqa: E402
from rw.pipeline import Session, run_investigation, save_report  # noqa: E402


def _print_plan(plan: CandidatePlan, labels: dict[str, str]) -> None:
    print(f"\n  Proposed fleet ({plan.label}, plan {plan.plan_id()}):")
    for f in plan.fleet:
        mark = "CHANGE" if f.changed else "keep  "
        flags = f" flags={f.flags}" if f.flags else ""
        print(f"    [{mark}] {f.service:9s} {labels.get(f.release_id, f.release_id)}{flags}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config.load_env()  # .env before anything reads the environment; never prints a value
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--snapshot", default="snap-001")
    ap.add_argument("--confirm-as", help="operator name confirming scope without a prompt")
    ap.add_argument("--replay", help="saved grounding transcript (labeled replay, not live)")
    ap.add_argument("--no-alternative", action="store_true")
    ap.add_argument("--answer", help="operator's answer if the agent asks a clarification (one round)")
    args = ap.parse_args()

    session = Session(snapshot=args.snapshot)
    from rw import graph as G
    labels = {}
    for svc in ("cart", "checkout"):
        for r in G.releases_for_service(session.g, svc)[0]:
            labels[r["release_id"]] = f"{svc} {r['version']} ({r['release_id']})"

    replays = iter([args.replay]) if args.replay else None

    def ground(request, tools, alternative_context=None):
        if replays is not None:
            path = next(replays, None)
            if path is None:
                raise SystemExit("replay has no transcript for the alternative step")
            print(f"\n[REPLAY — not live] grounding from {path}")
            return grounding.replay(Path(path)), Path(path)
        chain = os.environ.get("RW_GROUNDING_MODEL", grounding.DEFAULT_MODEL_CHAIN)
        print(f"\n[LIVE, model chain {chain}] grounding{' an alternative' if alternative_context else ''} ...")
        return grounding.ground(request, tools, alternative_context=alternative_context)

    def confirm(plan: CandidatePlan):
        _print_plan(plan, labels)
        who = args.confirm_as or input("  Confirm this scope for checking? Type your name (blank = no): ").strip()
        if not who:
            return None
        return ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by=who,
                                 confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    print(f"Request: {args.request!r}   snapshot={session.snapshot_id}  (SYNTHETIC FIXTURE)")

    def answer(clar):
        print(f"\n  Agent asks: {clar.question}")
        reply = args.answer if args.answer is not None else input("  Your answer (blank = stop): ").strip()
        if reply:
            print(f"  Operator answers: {reply}")
        return reply or None

    result = run_investigation(args.request, ground=ground, confirm=confirm, answer=answer, session=session,
                               allow_alternative=not args.no_alternative)
    for i, att in enumerate(result["attempts"], 1):
        g = att["grounding"]
        print(f"\n== Attempt {i}: {att['outcome']}  (model={g['model']}, live={g['live']})")
        res = g["result"]
        if res["kind"] == "CLARIFICATION":
            print(f"  Clarification: {res['question']}")
        else:
            print(f"  Rationale: {res['rationale']}")
        for c in res.get("citations", []):
            print(f"    cite {c['excerpt_id']}: \"{c['quote']}\"")
        for e in att.get("validation_errors") or g.get("validation_errors") or []:
            print(f"  validation error: {e}")
        rep = att.get("report")
        if not rep:
            continue
        v = rep["verification"]
        by_hash = {r["obligation_hash"]: r for r in v["receipts"]}
        for ob in v["obligations"]:
            t = ob["tuple"]
            r = by_hash.get(ob["obligation_hash"])
            res_s = r["result"] if r else "NO RECEIPT"
            why = f"  <- {r['error_type']}: {r['message']}" if r and r["result"] == "FAIL" else ""
            print(f"    probe {labels.get(t['release_id'], t['release_id']):45s} x {t['record_id']} "
                  f"({t['format_id']}): {res_s}{why}")
        for gp in v["gaps"]:
            print(f"    gap {gp['kind']}: {gp['subject']} — {gp['detail']}")
        for h_ in v["blocking_receipts"][:1]:
            ob = next(o for o in v["obligations"] if o["obligation_hash"] == h_)
            print("    witness: " + " ".join(f"({hop['label']} {hop['display'] or hop['id']}){hop['rel_to_next'] or ''}"
                                         for hop in ob["witness_path"]))
        print(f"  DISPOSITION: {v['disposition']}"
              + ("  (byte/shape readability of modeled records only)" if v["disposition"] == "BOUNDED_PASS" else ""))
    path = save_report(result)
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
