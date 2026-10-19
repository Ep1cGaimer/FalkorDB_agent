"""SYNTHETIC FIXTURE — tests for fixtures/astronomy-incident (orders -> ledger lineage, three stores).

Codec tests run the real trusted harness on stored bytes; graph/pipeline/API tests need FalkorDB on
127.0.0.1:6379 like the other integration tests. Expected outcomes come from the fixture design
(fixtures/astronomy-incident/DESIGN.md), never from runtime output.
"""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "astronomy-incident"
RELEASES = FIXTURES / "releases"
SNAPSHOTS = FIXTURES / "snapshots"
HARNESS = ROOT / "fixtures" / "shop" / "harness" / "run_reader.py"
BUILDER = ROOT / "scripts" / "build_incident_fixture.py"

LOCAL, LEDGER_V1, LEDGER_V2 = "OrderResult/local-currency", "ledger/v1", "ledger/v2"
STATELESS = {"ad", "checkout", "currency", "email", "frontend", "payment", "quote", "recommendation", "shipping"}
INCIDENT_REQUEST = ("Japanese shoppers are seeing wrong totals since 3.2.0. Roll back accounting and "
                    "fraud-detection to 3.1.0, their currency conversion is the suspect. Leave checkout alone.")

sys.dont_write_bytecode = True


def manifest(snapshot):
    return json.loads((SNAPSHOTS / snapshot / "manifest.json").read_text(encoding="utf-8"))


def store(snapshot, name):
    return next(s for s in manifest(snapshot)["stores"] if s["name"] == name)


def probe(release_dir, entry, data):
    nonce = secrets.token_hex(16)
    proc = subprocess.run(
        [sys.executable, "-I", str(HARNESS), str(RELEASES / release_dir / "codec.py"), entry],
        input=data, capture_output=True,
        env={"RW_PROBE_NONCE": nonce, "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("PATH", "")})
    result = json.loads(proc.stdout.decode("utf-8").strip())
    assert result.pop("nonce") == nonce
    return proc.returncode, result


# --------------------------------------------------------------------------- fixture bytes

def test_builder_is_deterministic():
    files = lambda: {p: p.read_bytes() for p in sorted(FIXTURES.rglob("*")) if p.is_file()}  # noqa: E731
    before = files()
    proc = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    after = files()
    assert before.keys() == after.keys()
    assert [p for p in before if before[p] != after[p]] == []


def test_orders_match_the_astronomy_shop_bytes():
    for rec in store("snap-001", "orders")["records"]:
        assert (FIXTURES / rec["payload"]).read_bytes() == (ROOT / "fixtures" / "astronomy-shop" / rec["payload"]).read_bytes()


def test_manifest_shape_and_lineage():
    m = manifest("snap-001")
    assert len(m["deployments"]) == 12 and {d["version"] for d in m["deployments"]} == {"3.2.0"}
    orders, ledger, carts = (store("snap-001", n)["records"] for n in ("orders", "ledger", "cart-cache"))
    assert (len(orders), len(ledger), len(carts)) == (40, 37, 20)
    order_by_id = {r["record_id"]: r for r in orders}
    for rec in orders + ledger + carts:
        assert rec["payload_hash"] == "sha256:" + hashlib.sha256((FIXTURES / rec["payload"]).read_bytes()).hexdigest()
    v2 = [r for r in ledger if r["format"] == LEDGER_V2]
    assert len(v2) == 16
    for row in ledger:  # every ledger row names exactly one order of the same snapshot
        (source,) = row["derived_from"]
        assert source in order_by_id
        if row["format"] == LEDGER_V2:  # converted rows: booked by accounting 3.2.0 from checkout 3.2.0 orders
            assert row["writer"] == {"service": "accounting", "version": "3.2.0"}
            assert order_by_id[source]["format"] == LOCAL
            assert order_by_id[source]["writer"] == {"service": "checkout", "version": "3.2.0"}
        else:
            assert row["writer"] == {"service": "accounting", "version": "3.1.0"}
    orphans = [r for r in store("snap-003-orphan", "ledger")["records"] if r["writer"] is None]
    assert len(orphans) == 1 and orphans[0]["format"] is None and "derived_from" not in orphans[0]
    assert store("snap-002-partial", "ledger")["coverage"] == "PARTIAL"


def test_ledger_readers_old_fails_on_v2_new_reads_both():
    ledger = store("snap-001", "ledger")["records"]
    v1 = next(r for r in ledger if r["format"] == LEDGER_V1)
    v2 = next(r for r in ledger if r["format"] == LEDGER_V2)
    code, result = probe("accounting-3.1.0", "read_ledger_row", (FIXTURES / v2["payload"]).read_bytes())
    assert (code, result["status"], result["error_type"]) == (10, "FAIL", "UnsupportedLedgerRowError")
    assert probe("accounting-3.1.0", "read_ledger_row", (FIXTURES / v1["payload"]).read_bytes())[0] == 0
    for rec in (v1, v2):
        assert probe("accounting-3.2.0", "read_ledger_row", (FIXTURES / rec["payload"]).read_bytes())[0] == 0


def test_stateless_services_declare_no_reads():
    for release in RELEASES.iterdir():
        decl = json.loads((release / "release.json").read_text(encoding="utf-8"))
        assert decl["no_state_read"] == (decl["service"] in STATELESS)
        assert bool(decl["routes"]) == (decl["service"] not in STATELESS)


# --------------------------------------------------------------------------- FalkorDB

@pytest.fixture(scope="module")
def sessions():
    from rw.pipeline import Session

    name = f"rw_test_incident_{uuid.uuid4().hex[:8]}"
    made = {}

    def get(snapshot):
        if snapshot not in made:
            made[snapshot] = Session(snapshot=snapshot, graph_name=name, reimport=not made, fixture_root=FIXTURES)
        return made[snapshot]

    yield get
    if made:
        try:
            next(iter(made.values())).g.delete()
        except Exception:
            pass


def fleet_entries(session, fleet):
    from rw import graph as G
    from rw.contracts import FleetEntry

    entries = []
    for service, version, flags in fleet:
        rows, _ = G.releases_for_service(session.g, service)
        (release,) = [r for r in rows if r["version"] == version]
        entries.append(FleetEntry(service=service, release_id=release["release_id"], flags=flags))
    return entries


def verify(session, fleet, origin="fixture"):
    from rw.contracts import GroundingProposal, ScopeConfirmation

    plan, errors = session.plan_from_proposal(
        GroundingProposal(changes=fleet_entries(session, fleet), citations=[], rationale="test"), "incident test",
        origin=origin)
    assert plan is not None and not errors, errors
    confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="pytest",
                                     confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return session.verify(plan, confirmation)


CONSUMERS_BACK = [("accounting", "3.1.0", {}), ("fraud-detection", "3.1.0", {})]
FLAG_OFF = [("checkout", "3.2.0", {"localCurrencyCheckout": False})]
CASES = [
    ("snap-001", CONSUMERS_BACK, "BLOCKED", set()),
    ("snap-001", [("checkout", "3.1.0", {})] + CONSUMERS_BACK, "BLOCKED", set()),
    ("snap-001", FLAG_OFF, "BOUNDED_PASS", set()),
    ("snap-002-partial", FLAG_OFF, "NEEDS_EVIDENCE", {"COVERAGE_INCOMPLETE"}),
    ("snap-003-orphan", FLAG_OFF, "NEEDS_EVIDENCE", {"WRITER_UNKNOWN", "FORMAT_UNKNOWN"}),
]


@pytest.mark.parametrize("snapshot,fleet,disposition,gaps", CASES,
                         ids=[f"{c[0]}-{'+'.join(s + '=' + v for s, v, _ in c[1])}" for c in CASES])
def test_dispositions_on_falkordb(sessions, snapshot, fleet, disposition, gaps):
    v = verify(sessions(snapshot), fleet)["verification"]
    assert v["disposition"] == disposition
    assert {g["kind"] for g in v["gaps"]} == gaps
    if snapshot == "snap-001":
        assert len(v["obligations"]) == 40 + 37 + 40 + 20
    failing = {(r["tuple"]["service"], r["tuple"]["store_id"], r["tuple"]["record_id"])
               for r in v["receipts"] if r["result"] == "FAIL"}
    if disposition != "BLOCKED":
        assert not failing
        return
    local = {r["record_id"] for r in store(snapshot, "orders")["records"] if r["format"] == LOCAL}
    v2 = {r["record_id"] for r in store(snapshot, "ledger")["records"] if r["format"] == LEDGER_V2}
    assert failing == ({("accounting", "store:orders", r) for r in local}
                       | {("fraud-detection", "store:orders", r) for r in local}
                       | {("accounting", "store:ledger", r) for r in v2})


def test_lineage_import_and_origins(sessions):
    from rw import graph as G

    session = sessions("snap-001")
    v2 = sorted(r["record_id"] for r in store("snap-001", "ledger")["records"] if r["format"] == LEDGER_V2)
    rows, log = G.record_origins(session.g, session.snapshot_id, v2 + ["orders-0@1040", "no-such-record"])
    assert not log["truncated"] and log["rows"] == len(v2) + 1
    by_record = {r["record_id"]: r for r in rows}
    for rid in v2:  # one DERIVED_FROM hop to an order written by checkout 3.2.0
        row = by_record[rid]
        assert row["hops"] == 1 and len(row["chain"]) == 2 and row["origin_store_id"] == "store:orders"
        assert (row["origin_service"], row["origin_version"]) == ("checkout", "3.2.0")
    own = by_record["orders-0@1040"]  # no lineage: a record is its own origin
    assert own["hops"] == 0 and own["chain"] == ["orders-0@1040"] and own["origin_version"] == "3.1.0"
    assert "record_origins" in G.QUERY_TEXT


def test_orphan_origin_is_unknown_not_dropped(sessions):
    from rw import graph as G

    session = sessions("snap-003-orphan")
    orphan = next(r["record_id"] for r in store("snap-003-orphan", "ledger")["records"] if r["writer"] is None)
    (row,) = G.record_origins(session.g, session.snapshot_id, [orphan])[0]
    assert row["hops"] == 0 and row["origin_release_id"] is None and row["origin_service"] is None


def test_missing_lineage_source_is_reported(tmp_path):
    from rw import graph as G

    root = tmp_path / "fixture"
    shutil.copytree(FIXTURES, root)
    path = root / "snapshots" / "snap-001" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    ledger = next(s for s in data["stores"] if s["name"] == "ledger")
    ledger["records"][0]["derived_from"] = ["orders-9@9999"]
    path.write_text(json.dumps(data), encoding="utf-8")
    db = G.connect()
    name = f"rw_test_lineage_gap_{uuid.uuid4().hex[:8]}"
    try:
        report = G.reset_and_import(db, name, root, ["snap-001"])
        (gap,) = report["lineage_gaps"]["snap-001"]
        assert gap["source"] == "orders-9@9999" and gap["reason"] == "source record not in snapshot"
        assert report["edges"]["DERIVED_FROM"] == 36
    finally:
        db.select_graph(name).delete()


def test_agent_plan_equal_to_current_fleet_is_rejected(sessions):
    from rw.contracts import GroundingProposal

    session = sessions("snap-001")
    proposal = GroundingProposal(changes=fleet_entries(session, [("accounting", "3.2.0", {})]), citations=[],
                                 rationale="keep everything")
    plan, errors = session.plan_from_proposal(proposal, "incident test", origin="agent")
    assert plan is None and any(e.startswith("NO_CHANGE") for e in errors)


def test_summary_names_every_failing_reader(sessions):
    from rw.pipeline import summarize_for_agent

    text = summarize_for_agent(verify(sessions("snap-001"), CONSUMERS_BACK))
    groups = [line for line in text.splitlines() if line.startswith("* reader ")]
    assert len(groups) == 3
    assert any(line.startswith("* reader fraud-detection 3.1.0 (consume_orders) fails on 16 record(s)") for line in groups)
    assert any("store:ledger, format ledger/v2, written by accounting 3.2.0" in line for line in groups)
    assert "trace_data_origin" in text and text.splitlines()[-1] == "PASS: 89 obligations"


def test_relationship_removal_on_a_disposable_copy(sessions):
    from rw import graph as G
    from rw.pipeline import ablate

    session = sessions("snap-001")
    fleet = [e.model_dump(mode="json") for e in fleet_entries(session, CONSUMERS_BACK)]
    before = session.g.ro_query("MATCH ()-[e:DERIVED_FROM]->() RETURN count(e)").result_set[0][0]
    cut_lineage = ablate(session, fleet, ["DERIVED_FROM"])
    assert cut_lineage["disposition"] == "BLOCKED" and cut_lineage["failures_found"] == 48
    assert cut_lineage["origins_found"] == 0
    cut_reads = ablate(session, fleet, ["EXECUTES_ROUTE", "IN_STORE", "READS_FROM"])
    assert cut_reads["disposition"] == "NEEDS_EVIDENCE" and cut_reads["obligations"] == 0
    assert session.g.ro_query("MATCH ()-[e:DERIVED_FROM]->() RETURN count(e)").result_set[0][0] == before
    with pytest.raises(ValueError):
        ablate(session, fleet, ["RUNS"])


def test_trace_data_origin_tool(sessions):
    from rw import grounding

    session = sessions("snap-001")
    tools = grounding.GroundingTools(session.g, session.snapshot_id)
    rows, log = grounding._DISPATCH["trace_data_origin"](tools, {"record_ids": ["ledger-1022"]})
    assert rows[0]["origin_service"] == "checkout" and log["name"] == "record_origins"
    assert "cypher" not in log  # the model sees the log, never query text
    for bad in ([], ["x" * 200], "ledger-1022", [1]):
        with pytest.raises(ValueError):
            tools.trace_data_origin(bad)


# --------------------------------------------------------------------------- baseline helpers

def test_baseline_context_has_equal_information():
    from rw.baseline import plaintext_context

    text = plaintext_context(FIXTURES, "snap-001")
    for rec in store("snap-001", "ledger")["records"][:3] + store("snap-001", "orders")["records"][:3]:
        assert rec["record_id"] in text
    assert "derived_from orders-" in text and "localCurrencyCheckout" in text
    assert "retained records in `cart-cache`" in text


def test_baseline_claim_check_against_receipts():
    from rw.baseline import claim_check

    from rw.contracts import h
    def receipt(service, rid, result):
        t = {"service": service, "record_id": rid}
        return {"tuple": t, "obligation_hash": h(t), "result": result}
    receipts = [receipt("a", "r1", "FAIL"), receipt("a", "r2", "FAIL"), receipt("b", "r3", "PASS")]
    verification = {"receipts": receipts, "obligations": [{"tuple": r["tuple"], "obligation_hash": r["obligation_hash"]} for r in receipts]}
    check = claim_check({"failing": {"a": ["r1"], "b": ["r3", "r9"]}}, verification)
    assert {k: check[k] for k in ("confirmed", "missed", "claimed_but_passed", "unverifiable", "expected_failing")} == \
        {"confirmed": 1, "missed": 1, "claimed_but_passed": 1, "unverifiable": 1, "expected_failing": 2}
    assert check["probes_run"] == 0


# --------------------------------------------------------------------------- API endpoints

@pytest.fixture
def incident_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from rw import graph
    from rw.api import create_app
    from rw.contracts import Citation, GroundingProposal, GroundingResult
    from rw.pipeline import Session

    name = "rw_test_incident_api_" + uuid.uuid4().hex[:8]
    session = Session(snapshot="snap-001", graph_name=name, fixture_root=FIXTURES)

    def fake_ground(request, tools, alternative_context=None):
        fleet = FLAG_OFF if alternative_context else CONSUMERS_BACK
        changes = fleet_entries(session, fleet)
        citations = []
        for entry in changes:
            history, _ = tools.release_history(entry.service)
            ex = next(ex for row in history if row["release_id"] == entry.release_id
                      for ex in row["excerpts"] if ex["kind"] == "changelog")
            citations.append(Citation(excerpt_id=ex["excerpt_id"], content_hash=ex["content_hash"], quote=ex["text"]))
        return GroundingResult(request_text=request, result=GroundingProposal(
            changes=changes, citations=citations, rationale="fixed test proposal"), model="groq:fake", live=True), None

    app = create_app(session_factory=lambda: Session(snapshot="snap-001", graph_name=name, reimport=False,
                                                     fixture_root=FIXTURES),
                     ground_function=fake_ground, db_path=tmp_path / "sim.sqlite", transcript_dir=tmp_path)
    try:
        with TestClient(app) as client:
            state = client.post("/api/investigations", json={"request_text": INCIDENT_REQUEST, "mode": "live"}).json()
            url = f"/api/investigations/{state['id']}/plans/{state['plan_hash']}"
            yield client, url
    finally:
        session.g.delete()


def test_origins_endpoint_requires_verification_then_traces(incident_api):
    client, url = incident_api
    assert client.get(url + "/origins").status_code == 409
    report = client.post(url + "/confirm-scope", json={"confirmed_by": "oncall:alice"}).json()
    assert report["verification"]["disposition"] == "BLOCKED"
    assert all(q.get("cypher") for q in report["queries"] if q["name"] != "receipts_by_id")
    body = client.get(url + "/origins").json()
    ledger = [o for o in body["origins"] if o["store_id"] == "store:ledger"]
    assert len(ledger) == 16 and {o["origin_service"] for o in ledger} == {"checkout"}
    assert body["query"]["name"] == "record_origins" and "DERIVED_FROM" in body["query"]["cypher"]


def test_baseline_endpoint_reports_answer_and_claim_check(incident_api, monkeypatch):
    from rw import grounding

    client, url = incident_api
    client.post(url + "/confirm-scope", json={"confirmed_by": "oncall:alice"})
    sent = {}

    def fake_transport(spec):
        def transport(body):
            sent["spec"], sent["body"] = spec, body
            answer = {"disposition": "BLOCKED", "failing": {"fraud-detection": ["orders-0@1048", "orders-0@1040"]},
                      "reason": "non-USD orders"}
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}
        transport.settings = {}
        return transport

    monkeypatch.setattr(grounding, "make_transport", fake_transport)
    body = client.post(url + "/baseline").json()
    assert sent["spec"] == "groq:fake" and "derived_from" in sent["body"]["messages"][1]["content"]
    assert body["disposition"] == "BLOCKED" and body["check"]["confirmed"] == 1
    assert body["check"]["claimed_but_passed"] == 1 and body["check"]["missed"] == 47
    assert body["check"]["probes_run"] == 0


def test_ablation_endpoint_validates_and_runs(incident_api):
    client, url = incident_api
    client.post(url + "/confirm-scope", json={"confirmed_by": "oncall:alice"})
    assert client.post(url + "/ablation", json={"remove": ["RUNS"]}).status_code == 422
    body = client.post(url + "/ablation", json={"remove": ["DERIVED_FROM"]}).json()
    assert body["disposition"] == "BLOCKED" and body["origins_found"] == 0 and body["edges_deleted"] == 3 * 37
