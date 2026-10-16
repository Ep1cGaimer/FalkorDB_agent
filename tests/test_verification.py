"""Disposition/completeness rules of the trusted checker, on hand-built graph rows.

The F4 revalidation tests use a real pipeline verification on a temporary graph plus private copies
of the fixture: obligation codec paths are repo-relative, so the same verification can be
revalidated against a copy whose bytes are then mutated one fact at a time.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from rw import probes as P
from rw.contracts import (
    Citation,
    Disposition,
    FleetEntry,
    GapKind,
    GroundingProposal,
    ProbeReceipt,
    ProbeResult,
    ScopeConfirmation,
    VerificationResult,
    bh,
    h,
    short,
)
from rw.pipeline import FIXTURE_ROOT, Session
from rw.verification import (
    REPO_ROOT,
    build_evidence,
    dispose,
    fixture_file,
    load_release_declarations,
    materialize_plan,
    revalidate,
    validate_citations,
)

SNAP = "snapshot:snap-x"
MHASH = "sha256:manifest"
ENV = "sha256:env"

CURRENT = [
    {"service": "cart", "release_id": "release:cart:new", "flags": {"v2": True}},
    {"service": "checkout", "release_id": "release:checkout:b", "flags": {}},
]
RELEASES = {
    "cart": [
        {"release_id": "release:cart:new", "declared_flags": [{"name": "v2", "default": True}]},
        {"release_id": "release:cart:old", "declared_flags": []},
    ],
    "checkout": [{"release_id": "release:checkout:b", "declared_flags": []}],
}

# the shipped declaration of every hand-built release: one reader route over "kv"
ROUTE = {"name": "read", "reads_from": "kv", "entry": "read", "read_domain": "ALL_KEYS", "contract": "c"}
DECL = {
    "release:cart:new": {"service": "cart", "version": "1.5", "routes": [ROUTE]},
    "release:cart:old": {"service": "cart", "version": "1.4", "routes": [ROUTE]},
    "release:checkout:b": {"service": "checkout", "version": "2.0", "routes": [ROUTE]},
}


def manifest(coverage="COMPLETE", records=("r1", "r2"), writer=("cart", "1.5"), fmt="f1"):
    """An independently parsed manifest; ``writer``/``fmt`` default to what the hand-built graph says."""
    def record(rid):
        rec = {"record_id": rid, "payload_hash": f"ph-{rid}"}
        if writer is not None:
            rec["writer"] = {"service": writer[0], "version": writer[1]}
        if fmt is not None:
            rec["format"] = fmt
        return rec

    return {
        "snapshot": "snap-x",
        "deployments": [{"service": "cart"}, {"service": "checkout"}],
        "stores": [{"name": "kv", "coverage": coverage, "records": [record(r) for r in records]}],
    }


def declarations(spec=None):
    """The independently loaded declaration dict for these hand-built releases."""
    return {
        rid: {
            "service": s["service"],
            "version": s["version"],
            "artifact_hash": f"ah-{rid}",
            "codec_path": f"{rid}.py",
            "codec_hash": f"codec-{rid}",
            "routes": {f"route:{rid}:{r['name']}": dict(r) for r in s["routes"]},
            "no_state_read": bool(s.get("no_state_read", False)),
        }
        for rid, s in (spec or DECL).items()
    }


def plan_for(cart_release="release:cart:old", flags=None):
    prop = GroundingProposal(
        changes=[FleetEntry(service="cart", release_id=cart_release, flags=flags or {})],
        citations=[], rationale="t")
    plan, errors = materialize_plan(prop, CURRENT, RELEASES, SNAP, MHASH, "req", "agent")
    assert not errors, errors
    return plan


def route_rows(plan, checkout_routes=True, decls=None):
    """Graph rows as the importer would write them from the given declarations."""
    decls = decls if decls is not None else declarations()
    rows = []
    for f in plan.fleet:
        dep = f"deployment:{plan.plan_id()}:{f.service}"
        decl = decls[f.release_id]
        routes = [] if (f.service == "checkout" and not checkout_routes) else list(decl["routes"].values())
        if not routes:
            rows.append({"service": f.service, "deployment_id": dep, "release_id": f.release_id,
                         "codec_hash": decl["codec_hash"], "codec_path": decl["codec_path"],
                         "no_state_read": decl["no_state_read"], "route_id": None, "route_name": None,
                         "entry": None, "read_domain": None, "route_contract_hash": None, "store_id": None})
            continue
        for route in routes:
            rows.append({"service": f.service, "deployment_id": dep, "release_id": f.release_id,
                         "codec_hash": decl["codec_hash"], "codec_path": decl["codec_path"],
                         "no_state_read": decl["no_state_read"],
                         "route_id": f"route:{f.release_id}:{route['name']}", "route_name": route["name"],
                         "entry": route.get("entry"), "read_domain": route.get("read_domain"),
                         "route_contract_hash": h(route),
                         "store_id": "store:" + route["reads_from"]})
    return rows


def inventory(records=("r1", "r2"), status="COMPLETE", writer=True, in_store=True, truncated=False, fmt="f1"):
    batches = [{"batch_id": f"batch:{r}", "record_id": r, "payload_hash": f"ph-{r}", "payload_path": "x",
                "format_id": fmt, "in_store": in_store,
                "writer_release_id": "release:cart:new" if writer else None} for r in records]
    cov = {"coverage_id": "cov", "status": status, "inventory_id_hash": "i"} if status else None
    return {"store:kv": (cov, batches, {"name": "store_inventory", "params": {}, "rows": len(batches),
                                        "truncated": truncated})}


def path_rows(routes, records=("r1", "r2"), skip=()):
    rows = []
    for r in routes:
        if not r["route_id"]:
            continue
        for rid in records:
            if (r["service"], rid) in skip:
                continue
            rows.append({"plan_id": "p", "deployment_id": r["deployment_id"], "service": r["service"],
                         "release_id": r["release_id"], "codec_hash": r["codec_hash"], "route_id": r["route_id"],
                         "store_id": "store:kv", "batch_id": f"batch:{rid}", "record_id": rid,
                         "payload_hash": f"ph-{rid}", "format_id": "f1",
                         "writer_release_id": "release:cart:new", "writer_version": "new"})
    return rows


def evidence(plan, *, man=None, routes=None, inv=None, paths=None, path_truncated=False, decls=None):
    decls = decls if decls is not None else declarations()
    routes = routes if routes is not None else route_rows(plan, decls=decls)
    return build_evidence(
        plan, man or manifest(), MHASH, routes, {"name": "plan_reader_routes", "params": {}, "rows": 0},
        inv or inventory(), paths if paths is not None else path_rows(routes),
        {"name": "obligation_paths", "params": {}, "rows": 0, "truncated": path_truncated},
        lambda entry: f"spec-{entry}", ENV, declarations=decls)


def receipt(ob, result, **tuple_changes):
    t = ob.tuple.model_copy(update=tuple_changes) if tuple_changes else ob.tuple
    return ProbeReceipt(obligation_hash=ob.obligation_hash, tuple=t, result=result, harness_exit=0,
                        stdout_excerpt="", evidence_hash="e", executed_at="t", duration_ms=1)


def kinds(result):
    return {g.kind for g in result.gaps}


# ---------------------------------------------------------------------------

def test_all_applicable_passes_is_bounded_pass():
    plan = plan_for()
    ev = evidence(plan)
    assert len(ev.obligations) == 4 and not ev.gaps
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.BOUNDED_PASS
    assert res.semantic_scope == "BYTE_SHAPE_ONLY"


def test_fail_dominates_partial_coverage():
    plan = plan_for()
    ev = evidence(plan, man=manifest(coverage="PARTIAL"), inv=inventory(status="PARTIAL"))
    rs = [receipt(o, ProbeResult.FAIL if i == 0 else ProbeResult.PASS) for i, o in enumerate(ev.obligations)]
    res = dispose(ev, rs)
    assert res.disposition == Disposition.BLOCKED
    assert GapKind.COVERAGE_INCOMPLETE in kinds(res)  # gap still reported alongside the witness
    assert res.blocking_receipts == [ev.obligations[0].obligation_hash]


def test_partial_coverage_without_fail_needs_evidence():
    plan = plan_for()
    ev = evidence(plan, man=manifest(coverage="PARTIAL"), inv=inventory(status="PARTIAL"))
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE


def test_missing_receipt_and_unknown_receipt_never_pass():
    plan = plan_for()
    ev = evidence(plan)
    rs = [receipt(o, ProbeResult.PASS) for o in ev.obligations[:2]]
    rs.append(receipt(ev.obligations[2], ProbeResult.UNKNOWN))
    res = dispose(ev, rs)
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert {GapKind.RECEIPT_MISSING, GapKind.RECEIPT_UNKNOWN} <= kinds(res)


def test_receipt_for_mutated_payload_is_inapplicable():
    plan = plan_for()
    ev = evidence(plan)
    rs = [receipt(o, ProbeResult.PASS) for o in ev.obligations[1:]]
    rs.append(receipt(ev.obligations[0], ProbeResult.FAIL, payload_hash="ph-other"))
    res = dispose(ev, rs)
    # the FAIL is bound to different bytes, so it neither blocks nor passes this obligation
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert GapKind.RECEIPT_INAPPLICABLE in kinds(res)


def test_missing_graph_path_is_a_gap_not_a_silent_omission():
    plan = plan_for()
    routes = route_rows(plan)
    ev = evidence(plan, routes=routes, paths=path_rows(routes, skip={("cart", "r2")}))
    assert len(ev.obligations) == 3
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and "r2" in g.subject for g in res.gaps)


def test_equal_count_wrong_ids_detected():
    plan = plan_for()
    ev = evidence(plan, man=manifest(records=("r1", "r9")))
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and "r9" in g.detail for g in ev.gaps)


# --------------------------------------------------------------------------- C1: conflicting batches

def conflict_gaps(gaps):
    return [g for g in gaps if g.kind == GapKind.INVENTORY_MISMATCH
            and "conflicting batches for one record" in g.detail]


def test_conflicting_graph_batches_for_one_record_are_a_gap():
    """C1(a): two Batch rows claiming one record_id must never be collapsed silently."""
    plan = plan_for()
    routes = route_rows(plan)
    cov, batches, log = inventory()["store:kv"]
    batches.append({**batches[0], "batch_id": "batch:r1-conflict", "payload_hash": "ph-other"})
    ev = evidence(plan, routes=routes, inv={"store:kv": (cov, batches, log)},
                  paths=path_rows(routes))
    found = conflict_gaps(ev.gaps)
    assert found, [g.detail for g in ev.gaps]
    assert found[0].subject == "store:kv|r1"
    assert "batch:r1-conflict" in found[0].detail and "batch:r1" in found[0].detail
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition != Disposition.BOUNDED_PASS


def test_path_row_whose_batch_is_not_the_manifest_match_is_a_gap():
    """C1(b): a path row that does not match the manifest batch never becomes an obligation."""
    plan = plan_for()
    routes = route_rows(plan)
    paths = path_rows(routes)
    paths.append({**paths[0], "batch_id": "batch:r1-conflict", "payload_hash": "ph-other"})
    ev = evidence(plan, routes=routes, paths=paths)
    assert len(ev.obligations) == 4  # the extra path row adds no obligation
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and g.subject == "batch:r1-conflict"
               for g in ev.gaps)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE


def test_path_row_payload_hash_disagreeing_with_the_manifest_is_a_gap():
    """C1(b): the obligation's payload hash must equal the manifest record's, not the graph's."""
    plan = plan_for()
    routes = route_rows(plan)
    paths = path_rows(routes)
    for row in paths:
        if row["service"] == "cart" and row["record_id"] == "r1":
            row["payload_hash"] = "ph-tampered"
    ev = evidence(plan, routes=routes, paths=paths)
    assert len(ev.obligations) == 3
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and g.subject == "batch:r1" for g in ev.gaps)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE


def test_path_row_for_a_record_the_manifest_does_not_carry_is_a_gap():
    plan = plan_for()
    routes = route_rows(plan)
    paths = path_rows(routes)
    paths.append({**paths[0], "record_id": "r9", "batch_id": "batch:r9", "payload_hash": "ph-r9"})
    ev = evidence(plan, routes=routes, paths=paths)
    assert len(ev.obligations) == 4
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and "r9" in g.subject for g in ev.gaps)


def test_path_row_for_a_store_without_manifest_inventory_is_a_gap():
    plan = plan_for()
    routes = route_rows(plan)
    paths = path_rows(routes)
    paths.append({**paths[0], "store_id": "store:ghost", "batch_id": "batch:ghost"})
    ev = evidence(plan, routes=routes, paths=paths)
    assert len(ev.obligations) == 4
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and g.subject == "batch:ghost"
               and "store:ghost" in g.detail for g in ev.gaps)


# --------------------------------------------------------------------------- declaration vs graph

LEGACY = {"name": "legacy", "reads_from": "kv", "entry": "read_legacy",
          "read_domain": "ALL_KEYS", "contract": "c"}
LEGACY_ID = "route:release:cart:old:legacy"
CART_OLD_ID = "route:release:cart:old:read"


def two_route_declarations():
    return declarations({**DECL, "release:cart:old": {**DECL["release:cart:old"], "routes": [ROUTE, LEGACY]}})


def test_declared_route_missing_from_graph_is_a_gap():
    """F1: dropping one of two EXECUTES_ROUTE edges must not hide the lost reader's pairs."""
    decls = two_route_declarations()
    plan = plan_for()
    routes = [r for r in route_rows(plan, decls=decls) if r["route_id"] != LEGACY_ID]
    ev = evidence(plan, routes=routes, decls=decls)
    assert any(g.kind == GapKind.ROUTE_DECLARATION_MISMATCH and g.subject == LEGACY_ID
               and g.detail == "declared route missing from graph" for g in ev.gaps)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert len(res.obligations) == 4
    assert any(g.kind == GapKind.INVENTORY_MISMATCH and g.subject == f"{LEGACY_ID}|r2" for g in res.gaps)


def test_graph_entry_cannot_override_the_declared_reader():
    """F3: a graph route renamed to `health` must not change the entry the probe runs."""
    declared = {**ROUTE, "entry": "read_cart"}
    decls = declarations({**DECL, "release:cart:old": {**DECL["release:cart:old"], "routes": [declared]}})
    plan = plan_for()
    routes = route_rows(plan, decls=decls)
    for r in routes:
        if r["route_id"] == CART_OLD_ID:
            r["entry"] = "health"
    ev = evidence(plan, routes=routes, decls=decls)
    assert any(g.kind == GapKind.ROUTE_DECLARATION_MISMATCH and "entry differs" in g.detail for g in ev.gaps)
    cart = [o for o in ev.obligations if o.tuple.service == "cart"]
    assert cart and all(o.reader_entry == "read_cart" for o in cart)
    assert all(o.tuple.probe_spec_hash == "spec-read_cart" for o in cart)


def test_tampered_route_contract_hash_is_a_gap():
    decls = declarations()
    plan = plan_for()
    routes = route_rows(plan, decls=decls)
    for r in routes:
        if r["route_id"] == CART_OLD_ID:
            r["route_contract_hash"] = "sha256:tampered"
    ev = evidence(plan, routes=routes, decls=decls)
    assert any(g.kind == GapKind.ROUTE_DECLARATION_MISMATCH and "route_contract_hash differs" in g.detail
               for g in ev.gaps)
    cart = [o for o in ev.obligations if o.tuple.service == "cart"]
    assert cart and all(o.tuple.route_contract_hash == h(ROUTE) for o in cart)


def test_release_without_declaration_is_invalid_fleet():
    full = declarations()
    plan = plan_for()
    routes = route_rows(plan, decls=full)
    ev = evidence(plan, routes=routes, decls=declarations({"release:checkout:b": DECL["release:checkout:b"]}))
    assert any(g.kind == GapKind.INVALID_FLEET and g.subject == "release:cart:old"
               and g.detail == "no independently loaded declaration for this release" for g in ev.gaps)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE and len(res.obligations) == 2


def test_real_fixture_declarations_match_the_imported_graph():
    """The loader's release IDs must equal the IDs the importer actually wrote."""
    from rw import graph as G

    decls = load_release_declarations(REPO_ROOT / "fixtures" / "shop")
    assert len(decls) == 4
    db = G.connect(host="127.0.0.1", port=6379)
    name = f"rw_test_{uuid.uuid4().hex[:8]}"
    try:
        G.reset_and_import(db, name, REPO_ROOT / "fixtures" / "shop", ["snap-001"])
        g = db.select_graph(name)
        graph_ids = set()
        for service in sorted({d["service"] for d in decls.values()}):
            rows, _ = G.releases_for_service(g, service)
            graph_ids |= {r["release_id"] for r in rows}
        assert graph_ids == set(decls)
    finally:
        try:
            db.select_graph(name).delete()
        except Exception:
            pass
        db.close()


def test_conflicting_batch_row_cannot_be_hidden_for_a_real_plan():
    """C1 on the real server: a second Batch row for one record must surface as a conflict gap.

    The graph keeps the legitimate cart/v2 batch for ``saved-cart-2002`` and gets a second Batch
    node claiming the same record with readable cart/v1 bytes; the conflict must be reported and the
    disposition must never be BOUNDED_PASS.
    """
    from rw import graph as G

    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.4")
        plan, errors = session.plan_from_proposal(
            GroundingProposal(changes=[FleetEntry(service="cart", release_id=release["release_id"])],
                              citations=[], rationale="roll back to cart 1.4"),
            "roll cart back to the previous build", origin="fixture")
        assert not errors and plan is not None

        v1 = (REPO_ROOT / "fixtures" / "shop" / "payloads" / "saved-cart-1001.bin").read_bytes()
        injected = "batch:cart-cache:snap-001:saved-cart-2002:" + short(bh(v1))
        session.g.query(
            "MATCH (st:StateStore {id: $store_id}), (w:Release {id: $release_id}) "
            "CREATE (b:Batch {id: $batch_id, scope_id: $scope_id, store_id: $store_id, "
            "snapshot_id: $snapshot_id, record_id: $record_id, payload_hash: $payload_hash, "
            "payload_path: $payload_path, format_id: $format_id}) "
            "CREATE (b)-[:IN_STORE]->(st) CREATE (b)-[:WRITTEN_BY]->(w)",
            {"store_id": "store:cart-cache", "release_id": release["release_id"], "batch_id": injected,
             "scope_id": "fixture-shop", "snapshot_id": "snapshot:snap-001",
             "record_id": "saved-cart-2002", "payload_hash": bh(v1),
             "payload_path": "fixtures/shop/payloads/saved-cart-1001.bin", "format_id": "cart/v1"})

        report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(),
                                                        confirmed_by="test-operator",
                                                        confirmed_at="2026-10-16T00:00:00Z"))
        v = report["verification"]
        conflict = [g for g in v["gaps"] if g["kind"] == "INVENTORY_MISMATCH"
                    and "conflicting batches for one record" in g["detail"]]
        assert conflict, v["gaps"]
        assert conflict[0]["subject"] == "store:cart-cache|saved-cart-2002"
        assert injected in conflict[0]["detail"]
        assert v["disposition"] != "BOUNDED_PASS"
        assert v["disposition"] in ("NEEDS_EVIDENCE", "BLOCKED")
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


def test_truncation_and_orphan_writer_are_gaps():
    plan = plan_for()
    ev = evidence(plan, inv=inventory(writer=False), path_truncated=True)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert {GapKind.TRUNCATED, GapKind.WRITER_UNKNOWN} <= kinds(res)


def test_missing_route_evidence_vs_declared_no_read():
    plan = plan_for()
    no_routes = {**DECL, "release:checkout:b": {**DECL["release:checkout:b"], "routes": []}}
    decls = declarations(no_routes)
    routes = route_rows(plan, checkout_routes=False, decls=decls)
    ev = evidence(plan, routes=routes, decls=decls)
    assert GapKind.ROUTE_EVIDENCE_MISSING in {g.kind for g in ev.gaps}
    stateless = {**no_routes, "release:checkout:b": {**no_routes["release:checkout:b"], "no_state_read": True}}
    decls = declarations(stateless)
    routes = route_rows(plan, checkout_routes=False, decls=decls)
    ev = evidence(plan, routes=routes, decls=decls)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.BOUNDED_PASS and len(res.obligations) == 2


def test_stale_manifest_is_a_gap():
    plan = plan_for()
    routes = route_rows(plan)
    ev = build_evidence(plan, manifest(), "sha256:changed", routes, {"name": "r"}, inventory(),
                        path_rows(routes), {"name": "p"}, lambda e: "s", ENV, declarations=declarations())
    assert GapKind.STALE_SNAPSHOT in {g.kind for g in ev.gaps}


def test_materialize_rejects_invented_artifacts_and_flags():
    bad = GroundingProposal(changes=[FleetEntry(service="cart", release_id="release:cart:hybrid")],
                            citations=[], rationale="")
    plan, errors = materialize_plan(bad, CURRENT, RELEASES, SNAP, MHASH, "r", "agent")
    assert plan is None and "not an existing" in errors[0]
    bad = GroundingProposal(changes=[FleetEntry(service="cart", release_id="release:cart:old",
                                                flags={"v2": False})], citations=[], rationale="")
    plan, errors = materialize_plan(bad, CURRENT, RELEASES, SNAP, MHASH, "r", "agent")
    assert plan is None and "not declared" in errors[0]


def test_materialize_completes_fleet_and_flags_change_plan_hash():
    a = plan_for("release:cart:new", {"v2": False})
    b = plan_for("release:cart:new", {"v2": True})
    assert [f.service for f in a.fleet] == ["cart", "checkout"]
    assert a.fleet[0].changed and not b.fleet[0].changed and not a.fleet[1].changed
    assert a.plan_hash() != b.plan_hash()


def test_citation_quotes_must_be_real():
    rows = [{"excerpt_id": "x1", "content_hash": "c1", "text": "Turning basket_v2 off restores the cart."}]
    ok = Citation(excerpt_id="x1", content_hash="c1", quote="basket_v2 off restores")
    fake = Citation(excerpt_id="x1", content_hash="c1", quote="basket_v2 is safe to roll back")
    assert validate_citations([ok], rows) == []
    assert validate_citations([fake], rows)
    assert validate_citations([Citation(excerpt_id="nope", content_hash="c", quote="a")], rows)


# --------------------------------------------------------------------------- manifest reconciliation (F6)

def writers(ev):
    return [g for g in ev.gaps if g.kind == GapKind.WRITER_UNKNOWN]


def formats(ev):
    return [g for g in ev.gaps if g.kind == GapKind.FORMAT_UNKNOWN]


def test_null_manifest_writer_is_a_gap_even_with_a_graph_edge():
    """A graph WRITTEN_BY edge can never stand in for a null manifest writer."""
    plan = plan_for()
    ev = evidence(plan, man=manifest(writer=None))
    assert len(writers(ev)) == 2  # one per batch, never more
    assert all(g.detail == "manifest writer is unknown" for g in writers(ev))


def test_manifest_writer_contradicting_the_graph_writer_is_a_gap():
    plan = plan_for()
    ev = evidence(plan, man=manifest(writer=("cart", "1.4")))  # resolves to release:cart:old
    assert len(writers(ev)) == 2
    assert all(g.detail == "writer contradiction: graph=release:cart:new manifest=release:cart:old"
               for g in writers(ev))
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE


def test_manifest_writer_that_resolves_to_no_declared_release_is_a_gap():
    plan = plan_for()
    ev = evidence(plan, man=manifest(writer=("cart", "9.9")))
    assert len(writers(ev)) == 2
    assert all("does not resolve to a declared release" in g.detail for g in writers(ev))


def test_unknown_format_on_either_side_is_a_gap():
    plan = plan_for()
    ev = evidence(plan, man=manifest(fmt=None))
    assert len(formats(ev)) == 2
    assert all(g.detail == "manifest format is unknown" for g in formats(ev))
    for graph_format in ("UNKNOWN", ""):
        ev = evidence(plan, inv=inventory(fmt=graph_format))
        assert len(formats(ev)) == 2
        assert all(g.detail == "record format not established" for g in formats(ev))


def test_manifest_format_contradicting_the_graph_format_is_a_gap():
    plan = plan_for()
    ev = evidence(plan, man=manifest(fmt="cart/v1"))
    assert len(formats(ev)) == 2
    assert all(g.detail == "format contradiction: graph=f1 manifest=cart/v1" for g in formats(ev))


def test_consistent_manifest_and_graph_metadata_has_no_writer_or_format_gap():
    plan = plan_for()
    ev = evidence(plan, man=manifest(writer=("cart", "1.5"), fmt="f1"))
    assert not writers(ev) and not formats(ev)


# --------------------------------------------------------------------------- snapshot binding (F8)

def test_zero_obligation_evidence_keeps_the_snapshot_binding():
    """F8: a stateless fleet passes with no obligations; the plan binding must survive dispose."""
    stateless = {rid: {**spec, "routes": [], "no_state_read": True} for rid, spec in DECL.items()}
    plan = plan_for()
    ev = evidence(plan, decls=declarations(stateless))
    assert not ev.obligations and not ev.gaps
    assert ev.snapshot_id == SNAP and ev.snapshot_manifest_hash == MHASH
    res = dispose(ev, [])
    assert res.disposition == Disposition.BOUNDED_PASS
    assert res.snapshot_id == SNAP
    assert res.snapshot_manifest_hash == MHASH


# --------------------------------------------------------------------------- F4: revalidation

def test_evidence_dependencies_cover_the_fleet_and_resolved_writers():
    """C2: dependencies are every fleet release plus every writer release the manifest resolves."""
    plan = plan_for()
    ev = evidence(plan)
    assert ev.dependencies == sorted(["release:cart:old", "release:checkout:b", "release:cart:new"])
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.dependencies == ev.dependencies


def test_dependencies_drop_a_writer_the_manifest_cannot_resolve():
    plan = plan_for()
    ev = evidence(plan, man=manifest(writer=("cart", "9.9")))
    assert ev.dependencies == sorted(["release:cart:old", "release:checkout:b"])


def test_fixture_file_maps_repo_relative_paths_into_the_real_fixture_and_a_copy(tmp_path):
    """The stored path is repo-relative; the same path must resolve inside a copy of the fixture."""
    relative = "fixtures/shop/releases/cart-1.5/codec.py"
    real = fixture_file(relative, FIXTURE_ROOT)
    assert real == REPO_ROOT / "fixtures" / "shop" / "releases" / "cart-1.5" / "codec.py" and real.is_file()

    copy = tmp_path / "shop"
    shutil.copytree(FIXTURE_ROOT, copy)
    copied = fixture_file(relative, copy)
    assert copied == copy / "releases" / "cart-1.5" / "codec.py"
    assert copied.read_bytes() == real.read_bytes()
    # manifest record paths are already fixture-relative and must not be re-prefixed
    assert fixture_file("payloads/saved-cart-1001.bin", copy) == copy / "payloads" / "saved-cart-1001.bin"


@pytest.fixture(scope="module")
def verified_pass():
    """A real BOUNDED_PASS verification of snap-001, produced by the pipeline on a temporary graph.

    Its snapshot bytes are the shipped fixture's, so it can be revalidated against a private copy.
    """
    from rw import graph as G

    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        plan, errors = session.plan_from_proposal(
            GroundingProposal(changes=[FleetEntry(service="cart", release_id=release["release_id"],
                                                  flags={"basket_v2": False})],
                              citations=[], rationale="keep 1.5 with the basket rollout off"),
            "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="test-operator",
                                                        confirmed_at="2026-10-16T00:00:00Z"))
        result = VerificationResult.model_validate(report["verification"])
        assert result.disposition == Disposition.BOUNDED_PASS and not result.gaps
        assert len(result.obligations) == 4
        for obligation in result.obligations:
            assert obligation.reader_codec_path.startswith("fixtures/shop/")  # repo-relative, as stored
        yield result
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


@pytest.fixture
def fixture_copy(tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


@pytest.fixture(scope="module")
def empty_inventory_pass(tmp_path_factory):
    """A real BOUNDED_PASS verification of snap-001 whose store carries no records (C2 case 2)."""
    from rw import graph as G

    root = tmp_path_factory.mktemp("empty-inventory") / "shop"
    shutil.copytree(FIXTURE_ROOT, root)
    path = root / "snapshots" / "snap-001" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for store in manifest["stores"]:
        store["records"] = []
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    name = "rw_test_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=root)
    try:
        rows, _ = G.releases_for_service(session.g, "cart")
        release = next(r for r in rows if r["version"] == "1.5")
        plan, errors = session.plan_from_proposal(
            GroundingProposal(changes=[FleetEntry(service="cart", release_id=release["release_id"],
                                                  flags={"basket_v2": False})],
                              citations=[], rationale="empty inventory control"),
            "undo the basket rollout", origin="fixture")
        assert not errors and plan is not None
        report = session.verify(plan, ScopeConfirmation(plan_hash=plan.plan_hash(),
                                                       confirmed_by="test-operator",
                                                       confirmed_at="2026-10-16T00:00:00Z"))
        result = VerificationResult.model_validate(report["verification"])
        assert result.disposition == Disposition.BOUNDED_PASS and not result.obligations and not result.gaps
        yield result, root
    finally:
        try:
            session.g.delete()
        except Exception:
            pass


def release_id_for(verified: VerificationResult, codec_fragment: str) -> str:
    """The exact release id a reader's obligations carry (ids embed the artifact hash)."""
    return next(o.tuple.release_id for o in verified.obligations if codec_fragment in o.reader_codec_path)


def test_revalidate_accepts_unchanged_evidence(verified_pass, fixture_copy):
    assert revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash) == []


def test_revalidate_flags_changed_payload_bytes(verified_pass, fixture_copy):
    payload = fixture_copy / "payloads" / "saved-cart-1001.bin"
    payload.write_bytes(payload.read_bytes() + b"\x00")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert errors and all("saved-cart-1001" in e for e in errors)  # named per drifted record, deduped
    assert not any("saved-cart-2002" in e for e in errors)


def test_revalidate_flags_a_missing_payload_as_drift_not_an_exception(verified_pass, fixture_copy):
    (fixture_copy / "payloads" / "saved-cart-2002.bin").unlink()
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("saved-cart-2002" in e and "unreadable" in e for e in errors)


def test_revalidate_flags_changed_reader_codec(verified_pass, fixture_copy):
    codec = fixture_copy / "releases" / "cart-1.5" / "codec.py"
    codec.write_bytes(codec.read_bytes() + b"\n# drift\n")
    release_id = release_id_for(verified_pass, "cart-1.5")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("codec.py" in e and release_id in e and "changed" in e for e in errors), errors
    # changing a file of the release also changes its artifact-derived release id
    assert any(e == f"release {release_id} is no longer declared by the fixture" for e in errors), errors


def test_revalidate_flags_a_missing_reader_codec(verified_pass, fixture_copy):
    (fixture_copy / "releases" / "checkout-2.1" / "codec.py").unlink()
    release_id = release_id_for(verified_pass, "checkout-2.1")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("codec.py" in e and release_id in e and "unreadable" in e for e in errors), errors


def test_revalidate_flags_changed_manifest_bytes(verified_pass, fixture_copy):
    path = fixture_copy / "snapshots" / "snap-001" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["environment"] = "drifted"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("snapshot manifest changed" in e and verified_pass.snapshot_manifest_hash in e for e in errors)


def test_revalidate_flags_a_missing_manifest(verified_pass, fixture_copy):
    (fixture_copy / "snapshots" / "snap-001" / "manifest.json").unlink()
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("manifest" in e and "cannot be read" in e for e in errors)


def test_revalidate_flags_a_changed_environment(verified_pass, fixture_copy):
    errors = revalidate(verified_pass, fixture_copy, lambda: "sha256:other-environment", P.probe_spec_hash)
    environment_errors = [e for e in errors if "environment" in e]
    assert len(environment_errors) == 1  # identical for every obligation, reported once
    assert "sha256:other-environment" in environment_errors[0]


def test_revalidate_flags_a_changed_probe_spec(verified_pass, fixture_copy):
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, lambda entry: f"spec-{entry}")
    assert {e for e in errors} == {f"probe spec for entry {o.reader_entry!r} changed: fresh=spec-{o.reader_entry} "
                                  f"verified={o.tuple.probe_spec_hash}" for o in verified_pass.obligations}


def test_revalidate_flags_a_release_that_is_no_longer_declared(verified_pass, fixture_copy):
    release_id = release_id_for(verified_pass, "checkout-2.1")
    shutil.rmtree(fixture_copy / "releases" / "checkout-2.1")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert f"release {release_id} is no longer declared by the fixture" in errors, errors


def test_revalidate_flags_a_changed_route_contract(verified_pass, fixture_copy):
    first = verified_pass.obligations[0]
    tampered = first.model_copy(update={"tuple": first.tuple.model_copy(
        update={"route_contract_hash": "sha256:tampered"})})
    drifted = verified_pass.model_copy(update={"obligations": [tampered] + list(verified_pass.obligations[1:])})
    errors = revalidate(drifted, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("route contract" in e and first.tuple.route_id in e and "sha256:tampered" in e for e in errors)


def test_revalidate_flags_a_changed_writer_only_release(verified_pass, fixture_copy):
    """C2: a release that only wrote retained state is still evidence the rollback depends on."""
    changelog = fixture_copy / "releases" / "cart-1.4" / "CHANGELOG.md"
    changelog.write_bytes(changelog.read_bytes() + b"\n- extra note\n")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert errors, "changing the writer-only cart 1.4 artifact must be drift"
    assert any("is no longer declared by the fixture" in e for e in errors), errors
    # it is neither a fleet release nor an obligation's release, so only the dependency set can see it
    assert not any("cart-1.4" in o.reader_codec_path for o in verified_pass.obligations)


def test_revalidate_flags_a_changed_writer_resolution(verified_pass, fixture_copy):
    """C2: each read store's manifest writer must still resolve the way it did at verification."""
    path = fixture_copy / "snapshots" / "snap-001" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = manifest["stores"][0]["records"]
    record = next(r for r in records if r["record_id"] == "saved-cart-1001")
    record["writer"] = {"service": "cart", "version": "1.5"}
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    errors = revalidate(verified_pass, fixture_copy, P.environment_hash, P.probe_spec_hash)
    assert any("writer resolution for record saved-cart-1001" in e for e in errors), errors


def test_revalidate_flags_a_changed_fleet_release_with_no_obligations(empty_inventory_pass, tmp_path):
    """C2: even a zero-obligation verification depends on the fleet's release bytes."""
    verification, root = empty_inventory_pass
    assert not verification.obligations
    copy = tmp_path / "shop"
    shutil.copytree(root, copy)
    assert revalidate(verification, copy, P.environment_hash, P.probe_spec_hash) == []
    changelog = copy / "releases" / "cart-1.5" / "CHANGELOG.md"
    changelog.write_bytes(changelog.read_bytes() + b"\n- extra note\n")
    errors = revalidate(verification, copy, P.environment_hash, P.probe_spec_hash)
    assert any("is no longer declared by the fixture" in e for e in errors), errors
