"""Plain-text LLM vs graph checker on the Astronomy Shop fixture (rollback safety verdicts).

Both sides get the SAME request, which names the exact target versions, so only the safety verdict
is compared (not request interpretation):

* plaintext: one model call (Groq, the product's default model) with the fixture as plain text --
  every release.json, CHANGELOG.md and reader/writer code (the shared protobuf wire codec boilerplate
  is elided), the snapshot's deployments, store coverage and every retained order decoded to JSON
  with its writer. No graph, no tools, no code execution. It must answer with a disposition and the
  exact failing (service, record_id) pairs.
* graph: rw.pipeline.Session on FalkorDB with the same fleet: obligations from the graph, every
  reader run on the real bytes, disposition from trusted rules.

Variants are built in a temporary copy of fixtures/astronomy-shop; the shipped fixture is untouched.
Expected outcomes come from the fixture design (see CASES), not from either side's output.

    .venv\\Scripts\\python.exe evals\\plaintext_vs_graph.py --repeats 3
Writes artifacts/plaintext_vs_graph/<timestamp>.json and prints a table.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SOURCE = ROOT / "fixtures" / "astronomy-shop"
OUT = ROOT / "artifacts" / "plaintext_vs_graph"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"
LOCAL = "OrderResult/local-currency"

ALL_BACK = [("checkout", "3.1.0"), ("accounting", "3.1.0"), ("fraud-detection", "3.1.0")]
CHECKOUT_ONLY = [("checkout", "3.1.0")]

# name, variant, snapshot, fleet, expected disposition, what the case tests
CASES = [
    ("documented", "documented", "snap-001", ALL_BACK, "BLOCKED", "USD-only limit stated in changelogs"),
    ("code-only", "code-only", "snap-001", ALL_BACK, "BLOCKED", "limit only visible in reader code"),
    ("needle", "needle", "snap-001", ALL_BACK, "BLOCKED", "3 non-USD orders among 96, limit only in code"),
    ("partial", "documented", "snap-002-partial", CHECKOUT_ONLY, "NEEDS_EVIDENCE", "inventory coverage PARTIAL"),
    ("orphan", "documented", "snap-003-orphan", CHECKOUT_ONLY, "NEEDS_EVIDENCE", "one order with unknown writer"),
    ("safe", "documented", "snap-001", CHECKOUT_ONLY, "BOUNDED_PASS", "readers stay on 3.2.0"),
]

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


# --------------------------------------------------------------------------- fixture variants

def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bh(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


HINTS = [  # sentences that state the currency limit outright; removed in code-only variants
    re.compile(r"^- Consumers must be on 3\.2\.0.*\n", re.M),
    re.compile(r"; an order in another currency (is rejected|throws)[^\n]*", re.M),
    re.compile(r"^- (Fraud limits|Books every amount)[^\n]*\n", re.M),
    re.compile(r"^- Every price and shipping cost in the order is in USD\.\n", re.M),
]


def strip_hints(root: Path) -> None:
    for changelog in (root / "releases").glob("*/CHANGELOG.md"):
        text = changelog.read_text(encoding="utf-8")
        for pattern in HINTS:
            text = pattern.sub("", text)
        changelog.write_text(text, encoding="utf-8")


def build_needle(root: Path, total: int = 96, local: int = 3) -> None:
    """Replace snap-001 with `total` orders, of which `local` (spread out) are non-USD from checkout 3.2.0."""
    builder = load_module(ROOT / "scripts" / "build_astronomy_fixture.py", "astro_builder")
    c31 = builder.load_codec("checkout-3.1.0")
    c32 = builder.load_codec("checkout-3.2.0")
    import random
    rng = random.Random(7)
    payloads = root / "payloads"
    local_at = {total // 4, total // 2 + 5, total - 7}
    assert len(local_at) == local
    records, offsets = [], {p: 2000 + 31 * p for p in range(3)}
    for index in range(total):
        partition = index % 3
        record_id = f"orders-{partition}@{offsets[partition]}"
        offsets[partition] += 1
        if index in local_at:
            data = c32.write_order(builder.make_order(rng, index, abroad=True), {"localCurrencyCheckout": True})
            writer, fmt = {"service": "checkout", "version": "3.2.0"}, LOCAL
        else:
            data = c31.write_order(builder.make_order(rng, index), {})
            writer, fmt = {"service": "checkout", "version": "3.1.0"}, "OrderResult/USD"
        (payloads / f"{record_id}.bin").write_bytes(data)
        records.append({"record_id": record_id, "payload": f"payloads/{record_id}.bin",
                        "payload_hash": bh(data), "writer": writer, "format": fmt})
    path = root / "snapshots" / "snap-001" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["stores"][0]["records"] = records
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_variant(name: str, base: Path) -> Path:
    root = base / "fixtures" / f"astro-{name}"
    shutil.copytree(SOURCE, root)
    if name in ("code-only", "needle"):
        strip_hints(root)
    if name == "needle":
        build_needle(root)
    return root


# --------------------------------------------------------------------------- plaintext side

WIRE = re.compile(r"\nclass _(Wire|Encode):\n.*?(?=\n\n\n)", re.S)


DOCSTRING = re.compile(r'^\s*"""(?:.|\n)*?"""\n', re.M)


def money(m: dict | None) -> str:
    return f"{m['units'] + m['nanos'] / 1e9:.2f} {m['currency_code']}" if m else "-"


def decoded_orders(root: Path, manifest: dict) -> list[str]:
    """Each retained order decoded with the 3.2.0 reader's wire decoder (it parses every order), one line each."""
    codec = load_module(root / "releases" / "accounting-3.2.0" / "codec.py", f"dec_{uuid.uuid4().hex}")
    rows = []
    for rec in manifest["stores"][0]["records"]:
        order = codec._Wire.order_result((root / rec["payload"]).read_bytes())
        writer = f"{rec['writer']['service']} {rec['writer']['version']}" if rec["writer"] else "UNKNOWN"
        items = "; ".join(f"{i['product_id']} x{i['quantity']} @{money(i['cost'])}" for i in order["items"])
        country = (order["shipping_address"] or {}).get("country") or "no address"
        rows.append(f"{rec['record_id']} | writer {writer} | format {rec['format']} | ship {country} "
                    f"{money(order['shipping_cost'])} | {items}")
    return rows


def plaintext_context(root: Path, snapshot: str) -> str:
    """Compact plain text (Groq free tier allows ~6k input tokens): every release,
    code without docstrings, one line per retained record."""
    parts = []
    for release in sorted((root / "releases").iterdir()):
        declared = json.loads((release / "release.json").read_text(encoding="utf-8"))
        parts.append(f"=== releases/{release.name}/release.json ===\n{json.dumps(declared, separators=(',', ':'))}")
        changelog = (release / "CHANGELOG.md").read_text(encoding="utf-8").strip().splitlines()[2:]
        parts.append(f"=== releases/{release.name}/CHANGELOG.md ===\n" + "\n".join(changelog))
        code = WIRE.sub("\n# class _Wire/_Encode: standard protobuf wire-format codec for OrderResult (elided)",
                        (release / "codec.py").read_text(encoding="utf-8"))
        code = re.sub(r"\n{3,}", "\n\n", DOCSTRING.sub("", code)).strip()
        parts.append(f"=== releases/{release.name}/codec.py ===\n{code}")
    manifest = json.loads((root / "snapshots" / snapshot / "manifest.json").read_text(encoding="utf-8"))
    store = manifest["stores"][0]
    summary = {"snapshot": manifest["snapshot"], "deployments": manifest["deployments"],
               "store": {"name": store["name"], "kind": store["kind"], "coverage": store["coverage"],
                         "record_count": len(store["records"])}}
    parts.append(f"=== snapshots/{snapshot}/manifest.json (summary) ===\n{json.dumps(summary, separators=(',', ':'))}")
    parts.append("=== retained records in `orders`, decoded (record | writer | format | shipping | items) ===\n"
                 + "\n".join(decoded_orders(root, manifest)))
    return "\n\n".join(parts)


def request_text(fleet) -> str:
    return "Proposed rollback: " + ", ".join(f"{s} to {v}" for s, v in fleet) + \
        ". Every other service keeps its current version. Is this rollback safe?"


def ask(context: str, fleet, key: str) -> dict:
    body = {"model": MODEL, "temperature": 0, "max_completion_tokens": 2500,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": context + "\n\n" + request_text(fleet)}]}
    for attempt in range(8):
        r = httpx.post(GROQ_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("retry-after") or 20 * (attempt + 1))
            time.sleep(min(wait, 90))
            continue
        if r.status_code == 413:
            return {"raw": r.text, "disposition": "TOO_LARGE"}
        r.raise_for_status()
        choice = r.json()["choices"][0]
        text = choice["message"]["content"] or ""
        if choice.get("finish_reason") == "length":
            return {"raw": text, "disposition": "TRUNCATED"}
        match = re.search(r"\{.*\}", text, re.S)
        try:
            return {"raw": text, **json.loads(match.group(0))} if match else {"raw": text, "disposition": "UNPARSEABLE"}
        except json.JSONDecodeError:
            return {"raw": text, "disposition": "UNPARSEABLE"}
    return {"raw": "", "disposition": "RATE_LIMITED"}


# --------------------------------------------------------------------------- graph side

def graph_verdict(root: Path, snapshot: str, fleet) -> dict:
    from rw import graph as G
    from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation
    from rw.pipeline import Session

    session = Session(snapshot=snapshot, graph_name=f"rw_cmp_{uuid.uuid4().hex[:8]}", fixture_root=root)
    try:
        changes = []
        for service, version in fleet:
            rows, _ = G.releases_for_service(session.g, service)
            (release,) = [r for r in rows if r["version"] == version]
            changes.append(FleetEntry(service=service, release_id=release["release_id"], flags={}))
        plan, errors = session.plan_from_proposal(
            GroundingProposal(changes=changes, citations=[], rationale="comparison"), request_text(fleet), origin="fixture")
        assert plan is not None and not errors, errors
        confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="eval",
                                         confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        v = session.verify(plan, confirmation)["verification"]
        failing = sorted({(r["tuple"]["service"], r["tuple"]["record_id"]) for r in v["receipts"] if r["result"] == "FAIL"})
        return {"disposition": v["disposition"], "failing": [list(f) for f in failing],
                "gaps": sorted({g["kind"] for g in v["gaps"]}), "probes": len(v["receipts"])}
    finally:
        session.g.delete()


# --------------------------------------------------------------------------- scoring

def expected_failing(root: Path, snapshot: str, fleet, disposition: str) -> set:
    if disposition != "BLOCKED":
        return set()
    readers = {s for s, v in fleet if s in ("accounting", "fraud-detection") and v == "3.1.0"}
    manifest = json.loads((root / "snapshots" / snapshot / "manifest.json").read_text(encoding="utf-8"))
    return {(s, r["record_id"]) for r in manifest["stores"][0]["records"] if r["format"] == LOCAL for s in readers}


def score(answer: dict, expected_disp: str, expected_fail: set) -> dict:
    failing = answer.get("failing") or {}
    if isinstance(failing, list):  # the graph side reports pairs
        got = {(f.get("service"), f.get("record_id")) for f in failing if isinstance(f, dict)}
    else:
        got = {(service, rid) for service, ids in failing.items() if isinstance(ids, list) for rid in ids}
    return {"disposition": answer.get("disposition"), "verdict_ok": answer.get("disposition") == expected_disp,
            "failing_found": len(got & expected_fail), "failing_expected": len(expected_fail),
            "false_failing": len(got - expected_fail), "exact": answer.get("disposition") == expected_disp and got == expected_fail}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--cases", nargs="*")
    args = ap.parse_args()
    key = os.environ.get("GROQ_API_KEY") or next(
        (line.split("=", 1)[1].strip() for line in (ROOT / ".env").read_text().splitlines() if line.startswith("GROQ_API_KEY=")), None)
    assert key, "GROQ_API_KEY missing"

    tmp = Path(tempfile.mkdtemp(prefix="rw_cmp_", dir=ROOT / "artifacts"))
    variants = {}
    results = []
    try:
        for name, variant, snapshot, fleet, expected, about in CASES:
            if args.cases and name not in args.cases:
                continue
            if variant not in variants:
                variants[variant] = make_variant(variant, tmp)
            root = variants[variant]
            want = expected_failing(root, snapshot, fleet, expected)
            graph = graph_verdict(root, snapshot, fleet)
            row = {"case": name, "about": about, "expected": expected, "expected_failing": len(want),
                   "graph": {**graph, **score(graph | {"failing": [dict(service=s, record_id=r) for s, r in graph["failing"]]}, expected, want)},
                   "plaintext": []}
            context = plaintext_context(root, snapshot)
            row["context_chars"] = len(context)
            for i in range(args.repeats):
                answer = ask(context, fleet, key)
                time.sleep(40)  # free tier: about one ~7k-token request per minute
                row["plaintext"].append({**score(answer, expected, want), "reason": answer.get("reason"), "raw": answer.get("raw")})
                print(f"{name} run {i + 1}: {row['plaintext'][-1]['disposition']} "
                      f"found {row['plaintext'][-1]['failing_found']}/{len(want)} false {row['plaintext'][-1]['false_failing']}", flush=True)
            print(f"{name} graph: {graph['disposition']} found {row['graph']['failing_found']}/{len(want)} gaps {graph['gaps']}", flush=True)
            results.append(row)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps({"model": MODEL, "cases": results}, indent=2), encoding="utf-8")
    print(f"\n{'case':<11}{'expected':<16}{'graph':<26}plaintext runs")
    for row in results:
        g = row["graph"]
        runs = "  ".join(f"{p['disposition']}({p['failing_found']}/{row['expected_failing']},+{p['false_failing']})"
                         for p in row["plaintext"])
        print(f"{row['case']:<11}{row['expected']:<16}{g['disposition'] + '(' + str(g['failing_found']) + '/' + str(row['expected_failing']) + ')':<26}{runs}")
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
