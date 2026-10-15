"""Trusted checker: plan materialization, obligation completeness, receipt applicability, disposition.

The graph supplies the multi-hop obligation paths; this module cross-checks them against an
independently parsed manifest so a missing edge or truncated query can never hide a required
obligation. Disposition precedence is fixed here and nowhere else (see docs/CONTRACTS.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .contracts import (
    SCOPE_ID,
    UNKNOWN,
    CandidatePlan,
    Citation,
    Coverage,
    Disposition,
    FleetEntry,
    Gap,
    GapKind,
    GraphEvidence,
    GroundingProposal,
    Obligation,
    ObligationTuple,
    ProbeReceipt,
    ProbeResult,
    VerificationResult,
    WitnessHop,
    bh,
    h,
    short,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- manifest

def load_manifest(fixture_root: Path, snapshot: str) -> tuple[dict, str]:
    """Parse a snapshot manifest straight from disk, independent of the graph."""
    name = snapshot.removeprefix("snapshot:")
    raw = (Path(fixture_root) / "snapshots" / name / "manifest.json").read_bytes()
    return json.loads(raw), bh(raw)


def snapshot_node_id(manifest: dict) -> str:
    return "snapshot:" + manifest["snapshot"]


# --------------------------------------------------------------------------- release declarations

def _release_dir_files(release_dir: Path) -> list[list[str]]:
    """Every file of a release dir as ``[posix relpath, byte hash]``, sorted by relpath."""
    return [
        [path.relative_to(release_dir).as_posix(), bh(path.read_bytes())]
        for path in sorted(release_dir.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_release_declarations(fixture_root: Path) -> dict[str, dict]:
    """Parse every release declaration straight from disk, independently of the graph.

    The artifact hash is recomputed exactly as docs/CONTRACTS.md "Identity rules" prescribes, so a
    graph row that no longer matches the shipped artifact cannot define a route for the checker.
    """
    declarations: dict[str, dict] = {}
    releases_dir = Path(fixture_root) / "releases"
    for release_dir in sorted(releases_dir.iterdir()):
        declaration_path = release_dir / "release.json"
        if not release_dir.is_dir() or not declaration_path.is_file():
            continue
        declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
        service = declaration["service"]
        artifact_hash = h(_release_dir_files(release_dir))
        release_id = f"release:{service}:{short(artifact_hash)}"
        codec = release_dir / "codec.py"
        declarations[release_id] = {
            "service": service,
            "version": declaration["version"],
            "artifact_hash": artifact_hash,
            "codec_path": _repo_rel(codec),
            "codec_hash": bh(codec.read_bytes()),
            "routes": {f"route:{release_id}:{route['name']}": route
                       for route in declaration.get("routes", [])},
            "no_state_read": bool(declaration.get("no_state_read", False)),
        }
    return declarations


# --------------------------------------------------------------------------- grounding validation

def _norm(text: str) -> str:
    return " ".join(text.split())


def validate_citations(citations: Iterable[Citation], excerpt_rows: Iterable[dict]) -> list[str]:
    """Each quote must be an exact (whitespace-normalized) substring of a real excerpt."""
    by_id = {r["excerpt_id"]: r for r in excerpt_rows}
    errors: list[str] = []
    for c in citations:
        row = by_id.get(c.excerpt_id)
        if row is None:
            errors.append(f"citation references unknown excerpt {c.excerpt_id!r}")
            continue
        if c.content_hash != row["content_hash"]:
            errors.append(f"citation {c.excerpt_id!r} content_hash does not match the stored excerpt")
        if not c.quote.strip() or _norm(c.quote) not in _norm(row["text"]):
            errors.append(f"quote is not present in excerpt {c.excerpt_id!r}: {c.quote[:80]!r}")
    return errors


def materialize_plan(
    proposal: GroundingProposal,
    current_fleet_rows: list[dict],
    release_rows_by_service: dict[str, list[dict]],
    snapshot_id: str,
    manifest_hash: str,
    request_text: str,
    origin: str,
    label: str = "",
) -> tuple[CandidatePlan | None, list[str]]:
    """Complete a proposal into an exact fleet of existing artifacts, or explain why it can't be."""
    errors: list[str] = []
    current = {r["service"]: r for r in current_fleet_rows}
    seen: set[str] = set()
    changes: dict[str, FleetEntry] = {}
    for ch in proposal.changes:
        if ch.service in seen:
            errors.append(f"service {ch.service!r} appears more than once in the proposal")
            continue
        seen.add(ch.service)
        if ch.service not in current:
            errors.append(f"service {ch.service!r} is not deployed in {snapshot_id}")
            continue
        releases = {r["release_id"]: r for r in release_rows_by_service.get(ch.service, [])}
        if ch.release_id not in releases:
            errors.append(f"release {ch.release_id!r} is not an existing {ch.service} artifact")
            continue
        declared = {f["name"]: f["default"] for f in releases[ch.release_id].get("declared_flags") or []}
        unknown_flags = sorted(set(ch.flags) - set(declared))
        if unknown_flags:
            errors.append(f"flags {unknown_flags} are not declared by {ch.release_id}")
            continue
        changes[ch.service] = ch
    if errors:
        return None, errors

    fleet: list[FleetEntry] = []
    for service in sorted(current):
        cur = current[service]
        ch = changes.get(service)
        release_id = ch.release_id if ch else cur["release_id"]
        rel = {r["release_id"]: r for r in release_rows_by_service.get(service, [])}.get(release_id)
        declared = {f["name"]: f["default"] for f in (rel or {}).get("declared_flags") or []}
        flags = dict(declared)
        if release_id == cur["release_id"]:
            flags.update({k: v for k, v in (cur.get("flags") or {}).items() if k in declared})
        if ch:
            flags.update(ch.flags)
        changed = release_id != cur["release_id"] or flags != (cur.get("flags") or {})
        fleet.append(FleetEntry(service=service, release_id=release_id, flags=flags, changed=changed))

    source_hashes = sorted({c.content_hash for c in proposal.citations})
    plan = CandidatePlan(
        scope_id=SCOPE_ID,
        snapshot_id=snapshot_id,
        snapshot_manifest_hash=manifest_hash,
        request_text_hash=h(request_text),
        fleet=fleet,
        source_hashes=source_hashes,
        origin=origin,  # type: ignore[arg-type]
        label=label,
    )
    return plan, []


# --------------------------------------------------------------------------- obligations

def build_evidence(
    plan: CandidatePlan,
    manifest: dict,
    manifest_hash: str,
    route_rows: list[dict],
    route_log: dict,
    inventories: dict[str, tuple[dict | None, list[dict], dict]],
    path_rows: list[dict],
    path_log: dict,
    probe_spec_for: Callable[[str], str],
    environment_hash: str,
    *,
    declarations: dict[str, dict],
) -> GraphEvidence:
    """Turn graph rows into canonical obligations plus every unresolved gap.

    ``declarations`` is the independently loaded output of :func:`load_release_declarations`; the
    graph's route set and route fields are only trusted insofar as they match it.
    """
    plan_hash = plan.plan_hash()
    plan_id = plan.plan_id()
    gaps: list[Gap] = []
    queries = [route_log, path_log] + [inv[2] for inv in inventories.values()]

    def gap(kind: GapKind, subject: str, detail: str) -> None:
        gaps.append(Gap(kind=kind, subject=subject, detail=detail))

    if plan.snapshot_manifest_hash != manifest_hash:
        gap(GapKind.STALE_SNAPSHOT, plan.snapshot_id, "plan was built against a different manifest")
    for q in queries:
        if q.get("truncated"):
            gap(GapKind.TRUNCATED, q.get("name", "?"), f"query returned more than its cap; params={q.get('params')}")

    manifest_services = {d["service"] for d in manifest["deployments"]}
    plan_services = {f.service for f in plan.fleet}
    if manifest_services != plan_services:
        gap(GapKind.INVALID_FLEET, plan_id,
            f"fleet services {sorted(plan_services)} != snapshot services {sorted(manifest_services)}")

    # --- executing readers per candidate deployment, checked against the shipped declarations
    by_deployment: dict[str, list[dict]] = {}
    for r in route_rows:
        by_deployment.setdefault(r["service"], []).append(r)
    routes: dict[str, dict] = {}  # route_id -> trusted, declaration-backed route facts
    declared_route_stores: dict[str, str] = {}  # every declared route -> its declared store
    stores_read: set[str] = set()
    for entry in plan.fleet:
        decl = declarations.get(entry.release_id)
        if decl is None:
            gap(GapKind.INVALID_FLEET, entry.release_id,
                "no independently loaded declaration for this release")
            continue
        rows = by_deployment.get(entry.service)
        if not rows:
            gap(GapKind.INVALID_FLEET, entry.service, "no candidate deployment found in the graph for this service")
            continue
        if any(r["release_id"] != entry.release_id for r in rows):
            gap(GapKind.INVALID_FLEET, entry.service, "graph deployment runs a different release than the plan")

        declared_routes: dict[str, dict] = decl["routes"]
        graph_routes = {r["route_id"]: r for r in rows if r.get("route_id")}
        for route_id in sorted(set(declared_routes) - set(graph_routes)):
            gap(GapKind.ROUTE_DECLARATION_MISMATCH, route_id, "declared route missing from graph")
        for route_id in sorted(set(graph_routes) - set(declared_routes)):
            gap(GapKind.ROUTE_DECLARATION_MISMATCH, route_id, "graph route not declared by the release")
        graph_codec_hashes = {r.get("codec_hash") for r in graph_routes.values()}
        for graph_codec_hash in sorted((v for v in graph_codec_hashes if v != decl["codec_hash"]), key=str):
            gap(GapKind.ROUTE_DECLARATION_MISMATCH, entry.release_id,
                f"codec_hash differs: graph={graph_codec_hash!r} declared={decl['codec_hash']!r}")

        for route_id, route in sorted(declared_routes.items()):
            declared_store = "store:" + route["reads_from"] if route.get("reads_from") else None
            if route.get("read_domain") != "ALL_KEYS":
                gap(GapKind.READ_DOMAIN_UNKNOWN, route_id, f"read_domain={route.get('read_domain')!r}")
            if not declared_store:
                gap(GapKind.STORE_MISSING, route_id, "route has no READS_FROM store")
            else:
                declared_route_stores[route_id] = declared_store
                stores_read.add(declared_store)

            row = graph_routes.get(route_id)
            if row is None:
                continue  # already reported as declared-but-missing
            for field, graph_value, declared_value in (
                ("entry", row.get("entry"), route.get("entry")),
                ("read_domain", row.get("read_domain"), route.get("read_domain")),
                ("store_id", row.get("store_id"), declared_store),
                ("route_name", row.get("route_name"), route.get("name")),
                ("route_contract_hash", row.get("route_contract_hash"), h(route)),
            ):
                if graph_value != declared_value:
                    gap(GapKind.ROUTE_DECLARATION_MISMATCH, route_id,
                        f"{field} differs: graph={graph_value!r} declared={declared_value!r}")
            routes[route_id] = {
                "route_id": route_id,
                "service": entry.service,
                "deployment_id": row["deployment_id"],
                "release_id": entry.release_id,
                "version": decl["version"],
                "codec_hash": decl["codec_hash"],
                "codec_path": decl["codec_path"],
                "store_id": declared_store,
                "route_name": route.get("name"),
                "entry": route.get("entry"),
                "read_domain": route.get("read_domain"),
                "route_contract_hash": h(route),
            }

        if not declared_routes and not decl["no_state_read"]:
            gap(GapKind.ROUTE_EVIDENCE_MISSING, entry.release_id,
                "release declares no reader routes and no no_state_read evidence")

    # --- retained state per read store, compared with the independent manifest
    manifest_stores = {"store:" + s["name"]: s for s in manifest["stores"]}
    expected_pairs: set[tuple[str, str]] = set()  # (route_id, record_id) from routes x graph inventory
    batches_by_store: dict[str, dict[str, dict]] = {}
    for store_id in sorted(stores_read):
        mstore = manifest_stores.get(store_id)
        if mstore is None:
            gap(GapKind.STORE_MISSING, store_id, "store is read by the fleet but absent from the snapshot manifest")
            continue
        if mstore.get("coverage") != Coverage.COMPLETE.value:
            gap(GapKind.COVERAGE_INCOMPLETE, store_id, f"manifest coverage={mstore.get('coverage')!r}")
        coverage_row, batch_rows, _ = inventories.get(store_id, (None, [], {}))
        if coverage_row is None:
            gap(GapKind.COVERAGE_INCOMPLETE, store_id, "graph has no Coverage node for this snapshot/store")
        elif coverage_row.get("status") != Coverage.COMPLETE.value:
            gap(GapKind.COVERAGE_INCOMPLETE, store_id, f"graph coverage={coverage_row.get('status')!r}")

        m_records = {r["record_id"]: r for r in mstore.get("records", [])}
        g_records = {r["record_id"]: r for r in batch_rows}
        missing = sorted(set(m_records) - set(g_records))
        extra = sorted(set(g_records) - set(m_records))
        if missing or extra:
            gap(GapKind.INVENTORY_MISMATCH, store_id, f"manifest-only={missing} graph-only={extra}")
        for rid in sorted(set(m_records) & set(g_records)):
            if m_records[rid]["payload_hash"] != g_records[rid]["payload_hash"]:
                gap(GapKind.INVENTORY_MISMATCH, rid, "payload hash differs between manifest and graph")
        for rid, b in sorted(g_records.items()):
            if not b.get("in_store"):
                gap(GapKind.INVENTORY_MISMATCH, b["batch_id"], "batch lacks its IN_STORE edge")
            if not b.get("writer_release_id"):
                gap(GapKind.WRITER_UNKNOWN, b["batch_id"], "no WRITTEN_BY writer release")
            if not b.get("format_id"):
                gap(GapKind.FORMAT_UNKNOWN, b["batch_id"], "record format not established")
        batches_by_store[store_id] = g_records
        for route_id, route_store_id in declared_route_stores.items():
            if route_store_id == store_id:
                for rid in set(m_records) | set(g_records):
                    expected_pairs.add((route_id, rid))

    # --- obligations come from the graph's multi-hop paths
    obligations: list[Obligation] = []
    seen_pairs: set[tuple[str, str]] = set()
    for p in path_rows:
        route = routes.get(p["route_id"])
        if route is None:
            continue  # path through a route not in this plan's fleet would be a graph inconsistency
        pair = (p["route_id"], p["record_id"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        t = ObligationTuple(
            scope_id=plan.scope_id,
            plan_hash=plan_hash,
            snapshot_id=plan.snapshot_id,
            snapshot_manifest_hash=manifest_hash,
            service=p["service"],
            deployment_id=p["deployment_id"],
            release_id=p["release_id"],
            codec_hash=route["codec_hash"],
            route_id=p["route_id"],
            route_contract_hash=route["route_contract_hash"],
            store_id=p["store_id"],
            batch_id=p["batch_id"],
            record_id=p["record_id"],
            payload_hash=p["payload_hash"],
            format_id=p.get("format_id") or UNKNOWN,
            probe_spec_hash=probe_spec_for(route["entry"]),
            environment_hash=environment_hash,
        )
        writer = p.get("writer_release_id")
        hops = [
            WitnessHop(label="Plan", id=plan_id, rel_to_next="-HAS_DEPLOYMENT->", display=plan.label),
            WitnessHop(label="Deployment", id=p["deployment_id"], rel_to_next="-RUNS->", display=p["service"]),
            WitnessHop(label="Release", id=p["release_id"], rel_to_next="-EXECUTES_ROUTE->",
                       display=f"{p['service']} {route.get('version', '')}".strip()),
            WitnessHop(label="ReaderRoute", id=p["route_id"], rel_to_next="-READS_FROM->",
                       display=route.get("route_name") or ""),
            WitnessHop(label="StateStore", id=p["store_id"], rel_to_next="<-IN_STORE-", display=p["store_id"]),
            WitnessHop(label="Batch", id=p["batch_id"], rel_to_next="-WRITTEN_BY->" if writer else None,
                       display=f"{p['record_id']} ({t.format_id})"),
        ]
        if writer:
            hops.append(WitnessHop(label="Release", id=writer,
                                   display=f"writer {p.get('writer_version') or ''}".strip()))
        obligations.append(Obligation(
            tuple=t,
            obligation_hash=t.obligation_hash(),
            writer_release_id=writer,
            witness_path=hops,
            reader_codec_path=route["codec_path"],
            reader_entry=route["entry"],
        ))

    for route_id, rid in sorted(expected_pairs - seen_pairs):
        gap(GapKind.INVENTORY_MISMATCH, f"{route_id}|{rid}",
            "reader/record pair expected from routes x inventory is missing from the graph path query")

    obligations.sort(key=lambda o: (o.tuple.service, o.tuple.route_id, o.tuple.record_id))
    return GraphEvidence(plan_hash=plan_hash, obligations=obligations, gaps=gaps, queries=queries)


# --------------------------------------------------------------------------- disposition

def receipt_applicable(receipt: ProbeReceipt, obligation: Obligation) -> bool:
    return (
        receipt.obligation_hash == obligation.obligation_hash
        and obligation.obligation_hash == obligation.tuple.obligation_hash()
        and receipt.tuple == obligation.tuple
    )


def dispose(evidence: GraphEvidence, receipts: list[ProbeReceipt]) -> VerificationResult:
    gaps = list(evidence.gaps)
    blocking: list[str] = []
    by_hash: dict[str, list[ProbeReceipt]] = {}
    for r in receipts:
        by_hash.setdefault(r.obligation_hash, []).append(r)

    plan_tuple = evidence.obligations[0].tuple if evidence.obligations else None
    for ob in evidence.obligations:
        candidates = by_hash.get(ob.obligation_hash, [])
        applicable = [r for r in candidates if receipt_applicable(r, ob)]
        results = {r.result for r in applicable}
        if ProbeResult.FAIL in results:
            blocking.append(ob.obligation_hash)
        elif ProbeResult.PASS in results:
            continue
        elif ProbeResult.UNKNOWN in results:
            gaps.append(Gap(kind=GapKind.RECEIPT_UNKNOWN, subject=ob.obligation_hash,
                            detail="probe ran but the harness could not establish a result"))
        elif candidates:
            gaps.append(Gap(kind=GapKind.RECEIPT_INAPPLICABLE, subject=ob.obligation_hash,
                            detail="receipt exists but its bound tuple differs from this obligation"))
        else:
            gaps.append(Gap(kind=GapKind.RECEIPT_MISSING, subject=ob.obligation_hash,
                            detail="no probe receipt for this obligation"))

    if blocking:
        disposition = Disposition.BLOCKED
    elif gaps:
        disposition = Disposition.NEEDS_EVIDENCE
    else:
        disposition = Disposition.BOUNDED_PASS

    snapshot_id = plan_tuple.snapshot_id if plan_tuple else ""
    manifest_hash = plan_tuple.snapshot_manifest_hash if plan_tuple else ""
    ob_hashes = {o.obligation_hash for o in evidence.obligations}
    return VerificationResult(
        plan_hash=evidence.plan_hash,
        snapshot_id=snapshot_id,
        snapshot_manifest_hash=manifest_hash,
        disposition=disposition,
        obligations=evidence.obligations,
        receipts=[r for r in receipts if r.obligation_hash in ob_hashes],
        gaps=gaps,
        blocking_receipts=sorted(blocking),
        computed_at=_now(),
    )
