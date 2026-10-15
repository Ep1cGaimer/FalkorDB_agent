"""Disposition/completeness rules of the trusted checker, on hand-built graph rows."""
from __future__ import annotations

from rw.contracts import (
    Citation,
    Disposition,
    FleetEntry,
    GapKind,
    GroundingProposal,
    ProbeReceipt,
    ProbeResult,
)
from rw.verification import build_evidence, dispose, materialize_plan, validate_citations

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


def manifest(coverage="COMPLETE", records=("r1", "r2")):
    return {
        "snapshot": "snap-x",
        "deployments": [{"service": "cart"}, {"service": "checkout"}],
        "stores": [{"name": "kv", "coverage": coverage,
                    "records": [{"record_id": r, "payload_hash": f"ph-{r}"} for r in records]}],
    }


def plan_for(cart_release="release:cart:old", flags=None):
    prop = GroundingProposal(
        changes=[FleetEntry(service="cart", release_id=cart_release, flags=flags or {})],
        citations=[], rationale="t")
    plan, errors = materialize_plan(prop, CURRENT, RELEASES, SNAP, MHASH, "req", "agent")
    assert not errors, errors
    return plan


def route_rows(plan, checkout_routes=True, no_state_read=False):
    rows = []
    for f in plan.fleet:
        dep = f"deployment:{plan.plan_id()}:{f.service}"
        if f.service == "checkout" and not checkout_routes:
            rows.append({"service": f.service, "deployment_id": dep, "release_id": f.release_id,
                         "codec_hash": "c", "codec_path": "p", "no_state_read": no_state_read,
                         "route_id": None, "route_name": None, "entry": None, "read_domain": None,
                         "route_contract_hash": None, "store_id": None})
            continue
        rows.append({"service": f.service, "deployment_id": dep, "release_id": f.release_id,
                     "codec_hash": f"codec-{f.release_id}", "codec_path": f"{f.release_id}.py",
                     "no_state_read": False, "route_id": f"route:{f.release_id}:read",
                     "route_name": "read", "entry": "read", "read_domain": "ALL_KEYS",
                     "route_contract_hash": "rc", "store_id": "store:kv"})
    return rows


def inventory(records=("r1", "r2"), status="COMPLETE", writer=True, in_store=True, truncated=False):
    batches = [{"batch_id": f"batch:{r}", "record_id": r, "payload_hash": f"ph-{r}", "payload_path": "x",
                "format_id": "f1", "in_store": in_store,
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


def evidence(plan, *, man=None, routes=None, inv=None, paths=None, path_truncated=False):
    routes = routes if routes is not None else route_rows(plan)
    return build_evidence(
        plan, man or manifest(), MHASH, routes, {"name": "plan_reader_routes", "params": {}, "rows": 0},
        inv or inventory(), paths if paths is not None else path_rows(routes),
        {"name": "obligation_paths", "params": {}, "rows": 0, "truncated": path_truncated},
        lambda entry: f"spec-{entry}", ENV)


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


def test_truncation_and_orphan_writer_are_gaps():
    plan = plan_for()
    ev = evidence(plan, inv=inventory(writer=False), path_truncated=True)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.NEEDS_EVIDENCE
    assert {GapKind.TRUNCATED, GapKind.WRITER_UNKNOWN} <= kinds(res)


def test_missing_route_evidence_vs_declared_no_read():
    plan = plan_for()
    routes = route_rows(plan, checkout_routes=False, no_state_read=False)
    ev = evidence(plan, routes=routes)
    assert GapKind.ROUTE_EVIDENCE_MISSING in {g.kind for g in ev.gaps}
    routes = route_rows(plan, checkout_routes=False, no_state_read=True)
    ev = evidence(plan, routes=routes)
    res = dispose(ev, [receipt(o, ProbeResult.PASS) for o in ev.obligations])
    assert res.disposition == Disposition.BOUNDED_PASS and len(res.obligations) == 2


def test_stale_manifest_is_a_gap():
    plan = plan_for()
    routes = route_rows(plan)
    ev = build_evidence(plan, manifest(), "sha256:changed", routes, {"name": "r"}, inventory(),
                        path_rows(routes), {"name": "p"}, lambda e: "s", ENV)
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
