"""Score saved RollbackWitness product reports and the flat-context LLM control transcripts.

Inputs (all read-only):

* ``artifacts/reports/*.json``        — product runs saved by ``scripts/investigate.py`` / the API;
* ``artifacts/controls/llm_flat_*.json`` — flat-context control runs (``evals/llm_control.py``);
* ``evals/expected/dispositions.json`` — the independent oracle (cases A..H).

For every run the table reports: the proposed fleet and whether it matches an oracle case; whether
the receipt correction is kept (from the oracle's ``request_fit`` for that fleet); exact obligation
recall = probed (service, record_id) pairs / the oracle obligation pairs for the proposed fleet;
whether the cart reader x saved-cart-2002 pair was actually probed; whether the claimed disposition
is *supported by the run's own evidence* — a BOUNDED_PASS claim needs a PASS on every required pair
(-reported separately as an unsupported pass), a BLOCKED claim needs an observed FAIL on the
proposed fleet, and NEEDS_EVIDENCE is supported only when the oracle disposition is also
NEEDS_EVIDENCE, never from a fabricated pass; whether a BOUNDED_PASS claim is false; whether the
claimed disposition equals the oracle disposition for that fleet; and the number
of model turns and tool calls. An oracle-consistent run additionally requires evidence-backed
claims: the right disposition without the evidence changes nothing.

Independence: the oracle file is the only source of expected outcomes. When a fleet matches an
oracle case exactly the case's own obligations and disposition are used. Otherwise the expected
disposition is *derived* from the oracle's per-(service, version, record) probe predictions plus
gaps read straight from the fixture manifest, and the row says so. Nothing here imports the runtime
pipeline, the graph, the probes or the control's own claims as an answer source; a fleet with no
oracle case is never silently passed.

Usage:
    .venv\\Scripts\\python.exe evals\\score_controls.py
    .venv\\Scripts\\python.exe evals\\score_controls.py --reports artifacts/reports --controls artifacts/controls
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "shop"
ORACLE_PATH = REPO_ROOT / "evals" / "expected" / "dispositions.json"
CONTROL_DIR = REPO_ROOT / "artifacts" / "controls"
REPORT_DIR = REPO_ROOT / "artifacts" / "reports"

DEFAULT_SNAPSHOT = "snap-001"
CRITICAL_RECORD = "saved-cart-2002"   # retained cart/v2 bytes: the older cart reader cannot read them


# --------------------------------------------------------------------------- fixture index

def _bh(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _h(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _short(hash_value: str) -> str:
    return hash_value[7:23]


def fixture_index(fixture_root: Path | str = FIXTURE_ROOT) -> dict[str, Any]:
    """Releases, their routes/declared flags, the snapshot manifest and the release-id rule.

    Release ids follow the frozen identity rule (docs/CONTRACTS.md):
    ``release:<service>:short(h([[relpath, bh(bytes)] for every file in the release dir, sorted]))``.
    That lets a saved report's ``release_id`` be resolved to a version without a live graph.
    """
    root = Path(fixture_root)
    releases: dict[str, dict[str, Any]] = {}
    by_release_id: dict[str, dict[str, Any]] = {}
    by_service_version: dict[tuple[str, str], dict[str, Any]] = {}
    for rel_dir in sorted((root / "releases").iterdir()):
        if not rel_dir.is_dir() or not (rel_dir / "release.json").is_file():
            continue
        decl = json.loads((rel_dir / "release.json").read_text(encoding="utf-8"))
        files = [[p.relative_to(rel_dir).as_posix(), _bh(p.read_bytes())]
                 for p in sorted(rel_dir.rglob("*")) if p.is_file()]
        release_id = f"release:{decl['service']}:{_short(_h(files))}"
        info = {
            "release_id": release_id,
            "service": decl["service"],
            "version": decl["version"],
            "declared_flags": {f["name"]: bool(f.get("default")) for f in (decl.get("flags") or [])},
            "routes": [{"store": str(r.get("reads_from") or "").removeprefix("store:"),
                        "entry": r.get("entry"), "read_domain": r.get("read_domain")} for r in (decl.get("routes") or [])],
            "no_state_read": bool(decl.get("no_state_read")),
        }
        releases[f"{decl['service']} {decl['version']}"] = info
        by_release_id[release_id] = info
        by_service_version[(decl["service"], decl["version"])] = info
    return {"root": root, "releases": releases, "by_release_id": by_release_id,
            "by_service_version": by_service_version}


def manifest_index(fixture_root: Path | str = FIXTURE_ROOT, snapshot: str = DEFAULT_SNAPSHOT) -> dict[str, Any]:
    raw = (Path(fixture_root) / "snapshots" / snapshot.removeprefix("snapshot:") / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    stores: dict[str, dict[str, Any]] = {}
    for store in manifest.get("stores") or []:
        records: dict[str, dict[str, Any]] = {}
        for rec in store.get("records") or []:
            writer = rec.get("writer") or {}
            records[rec["record_id"]] = {"writer": writer.get("version"), "format": rec.get("format"),
                                         "payload_hash": rec.get("payload_hash")}
        stores[store["name"]] = {"coverage": store.get("coverage"), "records": records}
    return {"snapshot": manifest["snapshot"], "manifest_hash": _bh(raw), "stores": stores,
            "deployments": {d["service"]: {"version": d["version"],
                                           "flags": {k: bool(v) for k, v in (d.get("flags") or {}).items()}}
                            for d in manifest.get("deployments") or []}}


# --------------------------------------------------------------------------- oracle index

def load_oracle(path: Path | str = ORACLE_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def oracle_index(oracle: dict, fixtures: dict, snapshots: dict[str, dict]) -> dict[str, Any]:
    """Cases by (snapshot, fleet key) plus every independent per-reader probe prediction."""
    cases: dict[str, dict] = {c["id"]: c for c in oracle["cases"]}
    by_fleet: dict[tuple, dict] = {}
    predictions: dict[tuple[str, str, str], str] = {}
    for case in oracle["cases"]:
        fleet, _ = canonical_fleet(case["fleet"], fixtures, snapshots.get(case["snapshot"]))
        by_fleet[(case["snapshot"], fleet_key(fleet))] = case
        for ob in case["obligations"]:
            predictions[(ob["service"], ob["version"], ob["record_id"])] = ob["expected_probe"]
    return {"cases": cases, "by_fleet": by_fleet, "predictions": predictions}


# --------------------------------------------------------------------------- fleet handling

def canonical_fleet(fleet: Any, fixtures: dict, manifest: dict | None) -> tuple[dict[str, dict], list[str]]:
    """Normalize a proposed fleet to ``{service: {"version": str, "flags": {name: bool}}}``.

    Flags missing from a proposal are filled with the release's declared defaults (the same rule the
    product's plan materialization uses: a changed release takes its defaults, an unchanged one keeps
    its deployed flags). Services the proposal omits at top level are left out here and reported.
    """
    notes: list[str] = []
    out: dict[str, dict] = {}
    if not isinstance(fleet, dict):
        return {}, ["fleet is not a mapping"]
    for service, spec in sorted(fleet.items()):
        if not isinstance(spec, dict):
            notes.append(f"{service}: not an object")
            continue
        version = spec.get("version")
        info = fixtures["by_service_version"].get((service, version))
        if info is None:
            notes.append(f"{service}: version {version!r} is not an existing artifact")
            out[service] = {"version": str(version), "flags": dict(spec.get("flags") or {})}
            continue
        declared = dict(info["declared_flags"])
        flags = {str(k): bool(v) for k, v in (spec.get("flags") or {}).items()}
        deployed = ((manifest or {}).get("deployments", {}).get(service) or {})
        if deployed.get("version") == version:
            for k, v in (deployed.get("flags") or {}).items():
                if k in declared:
                    declared[k] = bool(v)
        merged = dict(declared)
        merged.update({k: v for k, v in flags.items() if k in declared})
        out[service] = {"version": version, "flags": merged}
    return out, notes


def fleet_key(fleet: dict[str, dict]) -> tuple:
    return tuple(sorted((svc, spec.get("version"), tuple(sorted((spec.get("flags") or {}).items())))
                        for svc, spec in fleet.items()))


def describe_fleet(fleet: dict[str, dict] | None) -> str:
    if not fleet:
        return "—"
    parts = []
    for svc, spec in sorted(fleet.items()):
        flags = spec.get("flags") or {}
        on = ",".join(sorted(k for k, v in flags.items() if v))
        off = ",".join(sorted(k for k, v in flags.items() if not v))
        extra = f" [{'+'.join(filter(None, [on, ('-' + off) if off else '']))}]" if (on or off) else ""
        parts.append(f"{svc} {spec.get('version')}{extra}")
    return ", ".join(parts)


# --------------------------------------------------------------------------- obligations & gaps

def reader_obligations(fixtures: dict, manifest: dict, fleet: dict[str, dict]) -> tuple[dict[tuple[str, str, str], bool], list[dict]]:
    """``{(service, version, record_id): True}`` for every declared reader route x listed record.

    The key is the exact reader identity -- a probe of a *different* version of the service is not the
    obligation the proposed fleet carries. Mirrors the oracle's enumeration rule (declared routes x
    listed records in the read store) and also surfaces the fixture-side gaps the rule talks about.
    """
    pairs: dict[tuple[str, str, str], bool] = {}
    gaps: list[dict] = []
    stores = manifest["stores"]
    for service, spec in sorted(fleet.items()):
        version = spec.get("version")
        info = fixtures["by_service_version"].get((service, version))
        if info is None:
            gaps.append({"kind": "INVALID_FLEET", "subject": f"{service} {version}"})
            continue
        routes = info["routes"]
        if not routes:
            if not info["no_state_read"]:
                gaps.append({"kind": "ROUTE_EVIDENCE_MISSING", "subject": f"{service} {version}"})
            continue
        for route in routes:
            store = stores.get(route["store"])
            if store is None:
                gaps.append({"kind": "STORE_MISSING", "subject": route["store"]})
                continue
            if route.get("read_domain") not in (None, "ALL_KEYS"):
                gaps.append({"kind": "READ_DOMAIN_UNKNOWN", "subject": route["store"]})
            if store.get("coverage") != "COMPLETE":
                gaps.append({"kind": "COVERAGE_INCOMPLETE", "subject": f"{manifest['snapshot']}/{route['store']}"})
            for record_id, rec in sorted(store["records"].items()):
                pairs[(service, version, record_id)] = True
                if not rec.get("writer"):
                    gaps.append({"kind": "WRITER_UNKNOWN",
                                 "subject": f"{manifest['snapshot']}/{route['store']}/{record_id}"})
                if not rec.get("format"):
                    gaps.append({"kind": "FORMAT_UNKNOWN",
                                 "subject": f"{manifest['snapshot']}/{route['store']}/{record_id}"})
    # dedupe gaps, keeping order of first appearance
    seen, unique = set(), []
    for gap in gaps:
        key = (gap["kind"], gap["subject"])
        if key not in seen:
            seen.add(key)
            unique.append(gap)
    return pairs, unique


def derived_disposition(pairs: dict[tuple[str, str, str], bool], predictions: dict,
                        gaps: list[dict]) -> tuple[str, str]:
    """Apply the contract's precedence to oracle predictions + fixture gaps.

    Returns (disposition, source note). A pair the oracle does not predict is treated as unresolved
    evidence, never as a pass.
    """
    unknown = 0
    fails = 0
    for service, version, record_id in sorted(pairs):
        predicted = predictions.get((service, version, record_id))
        if predicted is None:
            unknown += 1
        elif predicted == "FAIL":
            fails += 1
    if fails:
        return "BLOCKED", f"derived: {fails} predicted FAIL(s) among {len(pairs)} obligations"
    if gaps or unknown:
        return "NEEDS_EVIDENCE", (f"derived: {len(gaps)} gap(s), {unknown} unpredicted pair(s)")
    return "BOUNDED_PASS", f"derived: all {len(pairs)} predicted obligations PASS, no gaps"


# --------------------------------------------------------------------------- run extraction

def run_from_control(transcript: dict, fixtures: dict, manifest: dict) -> dict:
    result = transcript.get("result")
    probes = transcript.get("probe_calls") or []
    executed: dict[tuple[str, str, str], list[str]] = {}
    for call in probes:
        res = call.get("result") or {}
        status = res.get("status")
        if status and call.get("service") and call.get("version") and call.get("record_id"):
            # a pair may be probed more than once (a retry): fold FAIL > unresolved > PASS
            executed.setdefault((call["service"], call["version"], call["record_id"]), []).append(status)
    probed = {pair: _dominant_result(statuses) for pair, statuses in executed.items()}
    fleet, notes = canonical_fleet((result or {}).get("fleet"), fixtures, manifest)
    return {
        "label": _control_label(transcript),
        "origin": "control",
        "model": transcript.get("model", "?"),
        "live": bool(transcript.get("live")),
        "snapshot": transcript.get("snapshot", DEFAULT_SNAPSHOT),
        "fleet": fleet or None,
        "fleet_notes": notes,
        "disposition": (result or {}).get("disposition"),
        "alternative": (result or {}).get("alternative"),
        "probed": probed,
        "model_turns": transcript.get("model_turns"),
        "tool_calls": transcript.get("tool_call_count", len(transcript.get("tool_calls") or [])),
        "aborted": bool(transcript.get("aborted") or result is None),
        "transcript": transcript.get("_path"),
    }


def _control_label(transcript: dict) -> str:
    path = str(transcript.get("_path") or "")
    match = re.search(r"llm_flat_(\d{8})T(\d{2})(\d{2})(\d{2})", path)
    if match:
        day, hour, minute, second = match.groups()
        return f"flat_control {day[4:6]}-{day[6:8]} {hour}:{minute}:{second}"
    return f"flat_control {transcript.get('model', '?')}"


def _turns_from_grounding_transcript(path: str | None) -> int | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    events = data.get("events") or []
    return sum(1 for e in events if e.get("type") in {"model", "model_error"}) or None


# --------------------------------------------------------------------------- receipt binding

def _dominant_result(statuses: list[str]) -> str:
    """Fold observable probe results for one pair: FAIL dominates, then any unresolved status over
    PASS — a pair probed PASS and UNKNOWN (or retried) on different runs was never established."""
    if "FAIL" in statuses:
        return "FAIL"
    non_pass = [s for s in statuses if s != "PASS"]
    return non_pass[0] if non_pass else statuses[0]


def _canonical_hash(obj: Any) -> str:
    """The documented canonical hash (CONTRACTS.md "Canonical hashing"): sha256 over sorted-key,
    compact, UTF-8 JSON. Re-stated here so the scorer stays independent of runtime code; a test pins
    it to the product's implementation."""
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _receipt_applies(receipt: dict, ob_tuple: dict) -> bool:
    """A product receipt is evidence for an obligation only when the tuple it binds equals the
    obligation's tuple exactly, the same rule the pipeline applies. Matching by obligation hash
    alone lets a stale or foreign receipt under the same hash discharge a pair its probe never
    ran on; a receipt with no bound tuple cannot be checked and is not evidence."""
    tup = receipt.get("tuple")
    return isinstance(tup, dict) and isinstance(ob_tuple, dict) and tup == ob_tuple


def runs_from_report(report: dict, fixtures: dict, manifest: dict) -> list[dict]:
    """One scored entry per product attempt that reached a plan (or one CLARIFICATION entry).

    Receipts are evidence for an obligation only when the tuple they bind matches that
    obligation's tuple on every field the report carries; a pair probed more than once folds
    FAIL > unresolved > PASS, so a last-passed retry can no longer hide an earlier FAIL.
    """
    runs: list[dict] = []
    name = Path(str(report.get("_path") or "report")).name
    for index, attempt in enumerate(report.get("attempts") or [], 1):
        grounding = attempt.get("grounding") or {}
        label = f"product {name[:12]}#{index}"
        detail = attempt.get("report")
        if not detail:
            kind = (grounding.get("result") or {}).get("kind")
            runs.append({"label": label, "origin": "product", "model": grounding.get("model", "?"),
                         "live": bool(grounding.get("live")), "snapshot": report.get("snapshot", DEFAULT_SNAPSHOT),
                         "fleet": None, "fleet_notes": [f"outcome={attempt.get('outcome')} kind={kind}"],
                         "disposition": None, "alternative": None, "probed": {},
                         "model_turns": _turns_from_grounding_transcript(attempt.get("transcript")),
                         "tool_calls": len(grounding.get("tool_calls") or []), "aborted": True,
                         "clarification": kind == "CLARIFICATION",
                         "outcome": attempt.get("outcome"), "transcript": attempt.get("transcript")})
            continue
        plan = detail.get("plan") or {}
        raw_fleet = {}
        version_of: dict[str, str] = {}
        for entry in plan.get("fleet") or []:
            info = fixtures["by_release_id"].get(entry.get("release_id"))
            version = info["version"] if info else f"?{entry.get('release_id')}"
            version_of[entry.get("release_id")] = info["version"] if info else "?"
            raw_fleet[entry["service"]] = {"version": version, "flags": entry.get("flags") or {}}
        fleet, notes = canonical_fleet(raw_fleet, fixtures, manifest)
        verification = detail.get("verification") or {}
        receipts_by_hash: dict[str, list[dict]] = {}
        for r in verification.get("receipts") or []:
            receipts_by_hash.setdefault(r.get("obligation_hash"), []).append(r)
        results_by_pair: dict[tuple[str, str, str], list[str]] = {}
        unbound = 0
        bad_obligations = 0
        for ob in verification.get("obligations") or []:
            tup = ob.get("tuple") or {}
            # An obligation whose hash is not the canonical hash of its own tuple is not a checkable
            # binding; nothing recorded under it is evidence.
            if not isinstance(tup, dict) or not tup or ob.get("obligation_hash") != _canonical_hash(tup):
                bad_obligations += 1
                continue
            candidates = receipts_by_hash.get(ob.get("obligation_hash")) or []
            applicable = [r for r in candidates if _receipt_applies(r, tup)]
            unbound += len(candidates) - len(applicable)
            version = version_of.get(tup.get("release_id"))
            if version is None:
                info = fixtures["by_release_id"].get(tup.get("release_id")) or {}
                version = info.get("version", "?")
            for receipt in applicable:
                results_by_pair.setdefault((tup.get("service"), version, tup.get("record_id")), []) \
                    .append(receipt.get("result"))
        probed = {pair: _dominant_result(list(results)) for pair, results in results_by_pair.items()}
        if unbound:
            notes.append(f"{unbound} saved probe receipt(s) did not bind to this plan's obligation "
                         "tuples exactly; they are not evidence for any pair")
        if bad_obligations:
            notes.append(f"{bad_obligations} saved obligation(s) have a hash that is not the canonical hash "
                         "of their tuple; they are not evidence for any pair")
        reported_gaps = [g for g in verification.get("gaps") or [] if g]
        if reported_gaps:
            notes.append(f"the report lists {len(reported_gaps)} evidence gap(s): "
                         + ", ".join(sorted({str((g or {}).get("kind", "?")) for g in reported_gaps})))
        runs.append({"label": label, "origin": "product", "model": grounding.get("model", "?"),
                     "live": bool(grounding.get("live")), "snapshot": (report.get("snapshot") or "").removeprefix("snapshot:"),
                     "fleet": fleet or None, "fleet_notes": notes, "disposition": verification.get("disposition"),
                     "alternative": None, "probed": probed, "reported_gaps": reported_gaps,
                     "model_turns": _turns_from_grounding_transcript(attempt.get("transcript")),
                     "tool_calls": len(grounding.get("tool_calls") or []),
                     "aborted": False, "outcome": attempt.get("outcome"), "transcript": attempt.get("transcript")})
    return runs


# --------------------------------------------------------------------------- scoring

def score_run(run: dict, oi: dict, fixtures: dict, manifests: dict[str, dict]) -> dict:
    """Score one run against the oracle. Never reads the run's own claims as an answer source."""
    manifest = manifests.get(run.get("snapshot") or "", manifests[DEFAULT_SNAPSHOT])
    row = {
        "run": run["label"], "origin": run["origin"], "model": run["model"], "live": run["live"],
        "fleet": describe_fleet(run.get("fleet")), "case": "—", "receipt_kept": None,
        "recall": "—", "required": 0, "probed_required": 0, "cards": "",
        "critical_probed": None, "observed_fails": 0, "false_pass": None, "disp_match": None,
        "established_passes": 0, "unknown_probes": 0,
        "evidence_supports_claim": None, "unsupported_pass": None,
        "disposition": run.get("disposition") or ("ABORTED" if run.get("aborted") else "—"),
        "expected_disposition": None, "expected_source": "—", "turns": run.get("model_turns"),
        "tool_calls": run.get("tool_calls"), "notes": list(run.get("fleet_notes") or []),
    }
    if run.get("aborted") or not run.get("fleet"):
        row["disposition"] = ("CLARIFICATION" if run.get("clarification")
                             else row["disposition"] if row["disposition"] not in (None, "—") else "ABORTED/NO PLAN")
        return row

    fleet = run["fleet"]
    case = oi["by_fleet"].get((run["snapshot"], fleet_key(fleet)))
    if case is not None:
        row["case"] = case["id"]
        row["receipt_kept"] = case["request_fit"]["receipt_correction_kept"]
        required = {(ob["service"], ob["version"], ob["record_id"]): True for ob in case["obligations"]}
        gaps = list(case["gaps"])
        expected, source = case["disposition"], f"oracle case {case['id']}"
    else:
        required, gaps = reader_obligations(fixtures, manifest, fleet)
        expected, source = derived_disposition(required, oi["predictions"], gaps)
        row["notes"].append("no oracle case for this fleet; expected disposition derived from the oracle's "
                            "per-reader predictions and the fixture manifest")
    row["expected_disposition"], row["expected_source"] = expected, source

    probed = run.get("probed") or {}
    hit = {pair for pair in probed if pair in required}
    row["required"] = len(required)
    row["probed_required"] = len(hit)
    row["recall"] = f"{len(hit)}/{len(required)}" if required else "n/a"
    established = sum(1 for pair in hit if probed[pair] == "PASS")
    row["established_passes"] = established
    row["observed_fails"] = sum(1 for pair in hit if probed[pair] == "FAIL")
    row["unknown_probes"] = sum(1 for pair in hit if probed[pair] not in ("PASS", "FAIL"))
    row["other_fails"] = sum(1 for pair, status in probed.items() if pair not in required and status == "FAIL")
    cart_version = (fleet.get("cart") or {}).get("version")
    checkout_version = (fleet.get("checkout") or {}).get("version")
    critical = ("cart", cart_version, CRITICAL_RECORD)
    if critical in required:
        row["critical_probed"] = critical in probed
        row["cards"] = "yes" if row["critical_probed"] else "no"
    else:
        row["cards"] = "not required"
    if ("checkout", checkout_version, CRITICAL_RECORD) in required \
            and ("checkout", checkout_version, CRITICAL_RECORD) not in probed:
        row["notes"].append(f"checkout {checkout_version} reader x {CRITICAL_RECORD} was never probed")

    claimed = run.get("disposition")
    # A claim is only as good as the run's own observed probe outcomes. BOUNDED_PASS needs a PASS on
    # *every* required obligation pair; BLOCKED needs at least one observed FAIL on the proposed
    # fleet; NEEDS_EVIDENCE never fabricates a pass and is supported only when the oracle says the
    # evidence really is unresolved. Any other value (or no claim at all) is not scored as supported.
    if claimed == "BOUNDED_PASS":
        # Any evidence gap the run itself reported (e.g. WRITER_UNKNOWN) also leaves a pass unsupported.
        row["unsupported_pass"] = bool(run.get("reported_gaps")) or not (
            required and all(probed.get(pair) == "PASS" for pair in required))
        supported = not row["unsupported_pass"]
        if row["unsupported_pass"]:
            row["notes"].append("claimed BOUNDED_PASS without a PASS on every required obligation pair "
                                "and no reported evidence gap")
    elif claimed == "BLOCKED":
        row["unsupported_pass"] = False
        supported = any(probed.get(pair) == "FAIL" for pair in required)
    elif claimed == "NEEDS_EVIDENCE":
        row["unsupported_pass"] = False
        supported = expected == "NEEDS_EVIDENCE"
    else:
        row["unsupported_pass"] = None
        supported = None
    row["evidence_supports_claim"] = supported
    row["false_pass"] = claimed == "BOUNDED_PASS" and expected != "BOUNDED_PASS"
    row["disp_match"] = claimed == expected if claimed else None
    if claimed == "BOUNDED_PASS" and not probed and expected == "BOUNDED_PASS":
        row["notes"].append("claimed BOUNDED_PASS without executing any obligation probe")
    return row


def consistent(row: dict) -> bool:
    """Oracle-consistent *with evidence*: a real fleet, an oracle case, the oracle's disposition for
    that fleet, no false pass, every oracle obligation pair for that fleet actually probed, and a
    claimed disposition the run's own probe evidence supports. A right answer without the evidence
    is not counted here (its recall is reported in the table).
    """
    return bool(row.get("case") != "—" and row.get("disp_match") and not row.get("false_pass")
                and row.get("evidence_supports_claim") is True
                and row.get("required") and row.get("probed_required") == row["required"])


def _unsafe(row: dict) -> bool:
    """A run that cleared a rollback the oracle says must not be applied (a false BOUNDED_PASS), or
    that cleared one the run's own probes never showed passing (an unsupported BOUNDED_PASS)."""
    return row.get("false_pass") is True or row.get("unsupported_pass") is True


def verdict(control_rows: list[dict], product_rows: list[dict]) -> str:
    if not control_rows and not product_rows:
        return "no runs scored"
    if not control_rows:
        return "no control run scored"
    def _count(rows, key: str) -> int:
        return sum(1 for r in rows if r.get(key) is True)

    c_ok = sum(1 for r in control_rows if consistent(r))
    p_ok = sum(1 for r in product_rows if consistent(r))
    c_bad = sum(1 for r in control_rows if _unsafe(r))
    p_bad = sum(1 for r in product_rows if _unsafe(r))
    safety = (f"false BOUNDED_PASS: control {_count(control_rows, 'false_pass')}/{len(control_rows)}, "
              f"product {_count(product_rows, 'false_pass')}/{len(product_rows)}; "
              f"unsupported BOUNDED_PASS: "
              f"control {_count(control_rows, 'unsupported_pass')}/{len(control_rows)}, "
              f"product {_count(product_rows, 'unsupported_pass')}/{len(product_rows)}")
    controls_line = (f"control: {c_ok}/{len(control_rows)} oracle-consistent runs "
                     f"(best: {max((r['case'] for r in control_rows if consistent(r)), default='none')})")
    if not product_rows:
        return f"control only — {controls_line}; no product report available to compare ({safety})"
    if c_ok == p_ok:
        return f"TIED on oracle-consistent runs — {controls_line}; product: {p_ok}/{len(product_rows)} ({safety})"
    if c_ok > p_ok:
        return (f"CONTROL WINS on oracle-consistent runs — {controls_line}; "
                f"product: {p_ok}/{len(product_rows)} ({safety})")
    return (f"product ahead on oracle-consistent runs — {controls_line}; "
            f"product: {p_ok}/{len(product_rows)} ({safety})")


# --------------------------------------------------------------------------- reporting

HEADER = ("| run | model (live) | proposed fleet | oracle case | receipt correction kept | probe recall "
          "| proposed cart reader x 2002 probed | established PASS | unknown probes | evidence supports claim "
          "| unsupported BOUNDED_PASS | false BOUNDED_PASS | disposition = oracle | model turns | tool calls |")
SEPARATOR = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def _yes_no(value: Any) -> str:
    if value is None:
        return "—"
    return "yes" if value else "no"


def markdown_row(row: dict) -> str:
    model = f"{row['model']}{'' if row['live'] else ' (not live)'}"
    recall = row["recall"]
    if row.get("observed_fails"):
        recall += f" ({row['observed_fails']} FAIL on the proposed fleet)"
    if row.get("other_fails"):
        recall += f" [{row['other_fails']} FAIL on other readers]"
    required = row.get("required")
    established = f"{row.get('established_passes', 0)}/{required if required else 0}"
    cells = [row["run"], model, row["fleet"], row["case"], _yes_no(row["receipt_kept"]), recall,
             _yes_no(row["critical_probed"]), established, str(row.get("unknown_probes", 0)),
             _yes_no(row.get("evidence_supports_claim")), _yes_no(row.get("unsupported_pass")),
             _yes_no(row["false_pass"]), _yes_no(row["disp_match"]),
             str(row["turns"] if row["turns"] is not None else "—"),
             str(row["tool_calls"] if row["tool_calls"] is not None else "—")]
    return "| " + " | ".join(cells) + " |"


def markdown_table(rows: list[dict]) -> str:
    lines = [HEADER, SEPARATOR] + [markdown_row(r) for r in rows]
    return "\n".join(lines)


def load_controls(directory: Path | str = CONTROL_DIR) -> list[dict]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("llm_flat_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["_path"] = str(path)
        out.append(data)
    return out


def load_reports(directory: Path | str = REPORT_DIR) -> list[dict]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["_path"] = str(path)
        out.append(data)
    return out


def collect(control_dir: Path | str = CONTROL_DIR, report_dir: Path | str = REPORT_DIR,
            oracle_path: Path | str = ORACLE_PATH) -> tuple[list[dict], list[dict]]:
    fixtures = fixture_index()
    manifests = {name: manifest_index(FIXTURE_ROOT, name)
                 for name in ("snap-001", "snap-002-partial", "snap-003-orphan")}
    oracle = load_oracle(oracle_path)
    oi = oracle_index(oracle, fixtures, manifests)
    control_rows = [score_run(run_from_control(t, fixtures, manifests[t.get("snapshot") or DEFAULT_SNAPSHOT]),
                              oi, fixtures, manifests)
                    for t in load_controls(control_dir)]
    product_rows: list[dict] = []
    for report in load_reports(report_dir):
        snapshot = str(report.get("snapshot") or DEFAULT_SNAPSHOT).removeprefix("snapshot:")
        for run in runs_from_report(report, fixtures, manifests.get(snapshot, manifests[DEFAULT_SNAPSHOT])):
            product_rows.append(score_run(run, oi, fixtures, manifests))
    return control_rows, product_rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score product reports and flat-context control runs against the oracle.")
    ap.add_argument("--controls", default=str(CONTROL_DIR))
    ap.add_argument("--reports", default=str(REPORT_DIR))
    ap.add_argument("--oracle", default=str(ORACLE_PATH))
    ap.add_argument("--json", help="also write the scored rows to this path")
    args = ap.parse_args(argv)

    control_rows, product_rows = collect(args.controls, args.reports, args.oracle)
    rows = product_rows + control_rows
    print("## Product vs flat-context control — scored against evals/expected/dispositions.json "
          "(synthetic fixture)\n")
    if not rows:
        print("No scored runs found: no `artifacts/reports/*.json` and no `artifacts/controls/llm_flat_*.json`.")
        print("\nScoring rules: probe recall = probed (service, record_id) pairs / oracle obligation pairs "
              "for the proposed fleet; false BOUNDED_PASS = claimed BOUNDED_PASS while the oracle (case "
              "match, or derived from the oracle's predictions plus fixture gaps) is not BOUNDED_PASS.")
        return 0
    print(markdown_table(rows))
    print()
    print(f"Outcome: {verdict(control_rows, product_rows)}")
    print()
    print("Breakdown (oracle case / claimed disposition):")
    for name, side in (("control", control_rows), ("product", product_rows)):
        pairs: dict[str, int] = {}
        for row in side:
            key = f"{row['case']}/{row['disposition']}"
            pairs[key] = pairs.get(key, 0) + 1
        summary = ", ".join(f"{key} x{count}" for key, count in sorted(pairs.items())) or "no runs"
        print(f"- {name}: {summary}")
    print()
    print("Notes:")
    print("- probe recall counts only probes that actually ran and compares exact reader identity "
          "(service, version, record_id); a probe of another version of the same service is not the "
          "obligation the proposed fleet carries, and a call rejected by the allowlist does not count.")
    print("- `established PASS` counts required obligation pairs probed with PASS; `unknown probes` "
          "counts required pairs probed with any other status (UNKNOWN, harness error, timeout).")
    print("- `evidence supports claim` says whether the run's claimed disposition is backed by its own "
          "observed probe outcomes: BOUNDED_PASS needs a PASS on every required pair; BLOCKED needs an "
          "observed FAIL on the proposed fleet; NEEDS_EVIDENCE is supported only when the expected "
          "disposition is also NEEDS_EVIDENCE. `unsupported BOUNDED_PASS` is reported separately from "
          "`false BOUNDED_PASS` (which keeps its meaning: claimed BOUNDED_PASS, oracle disagrees), and "
          "oracle-consistent runs additionally require a supported claim.")
    print("- a saved product receipt counts as evidence for an obligation only when the obligation's hash "
          "is the canonical hash of its tuple and the receipt carries exactly that tuple; anything else is "
          "reported as a note and is not evidence. A BOUNDED_PASS claim from a report that lists evidence "
          "gaps is unsupported. Where a pair was probed more than once (retries), the fold is "
          "FAIL > unresolved > PASS, so a later PASS never hides an earlier FAIL or UNKNOWN.")
    print("- `proposed cart reader x 2002 probed` is the cart reader of the proposed version on the "
          "retained cart/v2 bytes (saved-cart-2002).")
    print("- disposition for a fleet with no oracle case is derived from the oracle's per-reader predictions "
          "plus manifest gaps, and the row says so.")
    for row in rows:
        for note in row.get("notes") or []:
            print(f"- {row['run']}: {note}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows,
                                               "verdict": verdict(control_rows, product_rows)},
                                              indent=2, default=str, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
