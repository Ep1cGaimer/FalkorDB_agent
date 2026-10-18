"""Equal-information plain-agent baseline, shown beside a verification in the console.

The same model as the grounding agent gets every release file and every retained record of the
snapshot as plain text (decoded where a release codec can decode it, with writer, format and lineage),
plus the proposed fleet, and answers in one call. No graph, no probes. Generalized from
evals/plaintext_vs_graph.py, which stays unchanged so its recorded astronomy-shop results keep meaning.

Its claims are then checked against the plan's own probe receipts, never against an oracle: trusted
code reports which claimed failures receipts confirm, which failing reads it missed, and which
claimed failures actually passed.
"""
from __future__ import annotations

import importlib.util
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

SYSTEM = """You review proposed rollbacks of microservices before they are approved.
Rolling back code does not roll back data that newer versions already stored. Decide whether every
service in the proposed fleet can read every retained record it would read.
Answer with ONLY a JSON object:
{"disposition": "BLOCKED" | "BOUNDED_PASS" | "NEEDS_EVIDENCE",
 "failing": {"<service>": ["<record_id>", ...]},
 "reason": "one or two sentences"}
BLOCKED = at least one reader in the fleet would fail on a retained record (list every failing record id under each failing service).
BOUNDED_PASS = every reader in the fleet reads every retained record and the evidence is complete.
NEEDS_EVIDENCE = you cannot establish safety from the evidence (e.g. incomplete inventory or a record
whose writer or format is unknown) and nothing is known to fail."""

WIRE = re.compile(r"\nclass _(Wire|Encode):\n.*?(?=\n\n\n)", re.S)
DOCSTRING = re.compile(r'^\s*"""(?:.|\n)*?"""\n', re.M)
MAX_COMPLETION_TOKENS = 4096


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"rw_baseline_{uuid.uuid4().hex}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _money(m: dict | None) -> str:
    return f"{m['units'] + m['nanos'] / 1e9:.2f} {m['currency_code']}" if m else "-"


def _decoders(fixture_root: Path) -> list[Any]:
    """Codecs able to decode payloads in full: any release codec exposing a protobuf `_Wire` decoder."""
    out = []
    for release in sorted((fixture_root / "releases").iterdir(), reverse=True):
        text = (release / "codec.py").read_text(encoding="utf-8")
        if "class _Wire" in text:
            out.append(_load(release / "codec.py"))
            break
    return out


def _render(data: bytes, decoders: list[Any]) -> str:
    try:
        return json.dumps(json.loads(data.decode("utf-8")), sort_keys=True, separators=(",", ":"))
    except (UnicodeDecodeError, ValueError):
        pass
    for codec in decoders:
        try:
            order = codec._Wire.order_result(data)
        except Exception:
            continue
        if order.get("order_id") and order.get("items"):
            items = "; ".join(f"{i['product_id']} x{i['quantity']} @{_money(i['cost'])}" for i in order["items"])
            country = (order["shipping_address"] or {}).get("country") or "no address"
            return f"order {order['order_id']} ship {country} {_money(order['shipping_cost'])} | {items}"
    return "bytes " + data.hex()


def plaintext_context(fixture_root: Path, snapshot: str) -> str:
    """Every release (declaration, changelog, codec without wire boilerplate) and every retained record."""
    fixture_root = Path(fixture_root)
    parts = []
    for release in sorted((fixture_root / "releases").iterdir()):
        declared = json.loads((release / "release.json").read_text(encoding="utf-8"))
        parts.append(f"=== releases/{release.name}/release.json ===\n{json.dumps(declared, separators=(',', ':'))}")
        changelog = (release / "CHANGELOG.md").read_text(encoding="utf-8").strip().splitlines()[2:]
        parts.append(f"=== releases/{release.name}/CHANGELOG.md ===\n" + "\n".join(changelog))
        code = WIRE.sub("\n# class _Wire/_Encode: standard protobuf wire-format codec (elided)",
                        (release / "codec.py").read_text(encoding="utf-8"))
        code = re.sub(r"\n{3,}", "\n\n", DOCSTRING.sub("", code)).strip()
        parts.append(f"=== releases/{release.name}/codec.py ===\n{code}")
    manifest = json.loads((fixture_root / "snapshots" / snapshot / "manifest.json").read_text(encoding="utf-8"))
    summary = {"snapshot": manifest["snapshot"], "deployments": manifest["deployments"],
               "stores": [{"name": s["name"], "kind": s.get("kind"), "coverage": s.get("coverage"),
                           "record_count": len(s.get("records", []))} for s in manifest["stores"]]}
    parts.append(f"=== snapshots/{snapshot}/manifest.json (summary) ===\n{json.dumps(summary, separators=(',', ':'))}")
    decoders = _decoders(fixture_root)
    for store in manifest["stores"]:
        lines = []
        for rec in store.get("records", []):
            writer = rec.get("writer")
            writer_text = f"{writer['service']} {writer['version']}" if writer else "UNKNOWN"
            data = (fixture_root / rec["payload"]).read_bytes()
            derived = f" | derived_from {','.join(rec['derived_from'])}" if rec.get("derived_from") else ""
            lines.append(f"{rec['record_id']} | writer {writer_text} | format {rec.get('format') or 'UNKNOWN'}"
                         f"{derived} | {_render(data, decoders)}")
        parts.append(f"=== retained records in `{store['name']}` (record | writer | format | lineage | content) ===\n"
                     + "\n".join(lines))
    return "\n\n".join(parts)


def request_text(fleet: list[dict]) -> str:
    """The proposed fleet in words: every service, its version and any flag settings."""
    entries = []
    for e in sorted(fleet, key=lambda e: e["service"]):
        flags = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in sorted((e.get("flags") or {}).items()))
        entries.append(f"{e['service']} {e['version']}" + (f" ({flags})" if flags else ""))
    return ("Proposed fleet after the rollback: " + "; ".join(entries)
            + ". Is this rollback safe for the retained data?")


def ask(transport: Callable[[dict], dict], context: str, fleet: list[dict]) -> dict:
    """One plain chat call through an OpenAI-compatible product transport; the answer is parsed, not judged."""
    if hasattr(transport, "settings"):
        transport.settings["max_completion_tokens"] = MAX_COMPLETION_TOKENS
    response = transport({"temperature": 0, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": context + "\n\n" + request_text(fleet)}]})
    choice = (response.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    if choice.get("finish_reason") == "length":
        return {"raw": text, "disposition": "TRUNCATED", "failing": {}, "reason": ""}
    match = re.search(r"\{.*\}", text, re.S)
    try:
        parsed = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return {"raw": text, "disposition": "UNPARSEABLE", "failing": {}, "reason": ""}
    failing = parsed.get("failing") if isinstance(parsed.get("failing"), dict) else {}
    return {"raw": text, "disposition": str(parsed.get("disposition", "UNPARSEABLE")),
            "failing": failing, "reason": str(parsed.get("reason", ""))[:600]}


def claim_check(answer: dict, verification: dict) -> dict:
    """Compare the baseline's claimed failing reads with this plan's own receipts, keyed by (service, record)."""
    receipts = verification.get("receipts", [])
    failed = {(r["tuple"]["service"], r["tuple"]["record_id"]) for r in receipts if r["result"] == "FAIL"}
    passed = {(r["tuple"]["service"], r["tuple"]["record_id"]) for r in receipts if r["result"] == "PASS"} - failed
    claimed = {(service, rid) for service, ids in (answer.get("failing") or {}).items()
               if isinstance(ids, list) for rid in ids if isinstance(rid, str)}
    return {"confirmed": len(claimed & failed), "missed": len(failed - claimed),
            "claimed_but_passed": len(claimed & passed), "unverifiable": len(claimed - failed - passed),
            "expected_failing": len(failed), "probes_run": 0,
            "claimed_failing": [{"service": s, "record_id": r} for s, r in sorted(claimed)]}
