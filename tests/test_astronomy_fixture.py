"""SYNTHETIC FIXTURE — tests for fixtures/astronomy-shop (OpenTelemetry Demo `orders` topic).

Codec tests run the real trusted harness on the stored bytes; the pipeline test needs FalkorDB on
127.0.0.1:6379 like the other graph integration tests. Expected outcomes are written here from the
fixture design (docs/plans/astronomy-shop-fixture.md), not read back from runtime output.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "astronomy-shop"
RELEASES = FIXTURES / "releases"
PAYLOADS = FIXTURES / "payloads"
SNAPSHOTS = FIXTURES / "snapshots"
HARNESS = ROOT / "fixtures" / "shop" / "harness" / "run_reader.py"
BUILDER = ROOT / "scripts" / "build_astronomy_fixture.py"

USD, LOCAL = "OrderResult/USD", "OrderResult/local-currency"
USD_ONLY = "this build only handles USD."

sys.dont_write_bytecode = True


def fixture_files():
    return sorted(PAYLOADS.glob("*.bin")) + sorted(SNAPSHOTS.glob("*/manifest.json"))


def records(snapshot):
    manifest = json.loads((SNAPSHOTS / snapshot / "manifest.json").read_text(encoding="utf-8"))
    (store,) = manifest["stores"]
    return store["records"]


def probe(release_dir, entry, data):
    nonce = secrets.token_hex(16)
    proc = subprocess.run(
        [sys.executable, "-I", str(HARNESS), str(RELEASES / release_dir / "codec.py"), entry],
        input=data, capture_output=True,
        env={"RW_PROBE_NONCE": nonce, "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
             "PATH": os.environ.get("PATH", "")},
    )
    result = json.loads(proc.stdout.decode("utf-8").strip())
    assert result.pop("nonce") == nonce
    return proc.returncode, result


def test_builder_is_deterministic():
    before = {p: p.read_bytes() for p in fixture_files()}
    proc = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    after = {p: p.read_bytes() for p in fixture_files()}
    assert before.keys() == after.keys()
    for path, data in before.items():
        assert after[path] == data, f"rebuild changed {path}"


def test_manifests_bind_payload_bytes_and_shape():
    main = records("snap-001")
    assert [r["format"] for r in main].count(USD) == 24
    assert [r["format"] for r in main].count(LOCAL) == 16
    for snapshot in ("snap-001", "snap-002-partial", "snap-003-orphan"):
        for rec in records(snapshot):
            data = (FIXTURES / rec["payload"]).read_bytes()
            assert rec["payload_hash"] == "sha256:" + hashlib.sha256(data).hexdigest()
            if rec["format"] == LOCAL:
                assert b"USD" not in data and rec["writer"] == {"service": "checkout", "version": "3.2.0"}
            elif rec["format"] == USD:
                assert b"USD" in data and rec["writer"] == {"service": "checkout", "version": "3.1.0"}
    orphans = [r for r in records("snap-003-orphan") if r["writer"] is None]
    assert len(orphans) == 1 and orphans[0]["format"] is None


@pytest.mark.parametrize("service", ["accounting", "fraud-detection"])
def test_3_1_reader_fails_on_local_currency_and_3_2_reads_both(service):
    local = next(r for r in records("snap-001") if r["format"] == LOCAL)
    usd = next(r for r in records("snap-001") if r["format"] == USD)
    local_bytes = (FIXTURES / local["payload"]).read_bytes()
    usd_bytes = (FIXTURES / usd["payload"]).read_bytes()

    code, result = probe(f"{service}-3.1.0", "read_order", local_bytes)
    assert (code, result["status"], result["error_type"]) == (10, "FAIL", "UnsupportedCurrencyError")
    assert result["message"].endswith(USD_ONLY)
    assert probe(f"{service}-3.1.0", "read_order", usd_bytes)[0] == 0
    assert probe(f"{service}-3.2.0", "read_order", usd_bytes)[0] == 0
    assert probe(f"{service}-3.2.0", "read_order", local_bytes)[0] == 0
    assert probe(f"{service}-3.1.0", "health", b"")[0] == 0  # startup stays GREEN


def test_truncated_message_is_a_protobuf_failure():
    usd = next(r for r in records("snap-001") if r["format"] == USD)
    data = (FIXTURES / usd["payload"]).read_bytes()
    code, result = probe("accounting-3.2.0", "read_order", data[:-3])
    assert code == 10 and result["error_type"] == "InvalidProtocolBufferException"


# --------------------------------------------------------------------------- pipeline on FalkorDB

CASES = [
    ("snap-001", [("checkout", "3.1.0", {}), ("fraud-detection", "3.1.0", {})], "BLOCKED", set()),
    ("snap-001", [("accounting", "3.1.0", {})], "BLOCKED", set()),
    ("snap-001", [("checkout", "3.1.0", {})], "BOUNDED_PASS", set()),
    ("snap-001", [("checkout", "3.2.0", {"localCurrencyCheckout": False})], "BOUNDED_PASS", set()),
    ("snap-001", [("recommendation", "3.1.0", {})], "BOUNDED_PASS", set()),
    ("snap-002-partial", [("checkout", "3.1.0", {})], "NEEDS_EVIDENCE", {"COVERAGE_INCOMPLETE"}),
    ("snap-003-orphan", [("checkout", "3.1.0", {})], "NEEDS_EVIDENCE", {"WRITER_UNKNOWN", "FORMAT_UNKNOWN"}),
]


@pytest.fixture(scope="module")
def sessions():
    from rw.pipeline import Session

    name = f"rw_test_astro_{uuid.uuid4().hex[:8]}"
    made = {}

    def get(snapshot):
        if snapshot not in made:
            made[snapshot] = Session(snapshot=snapshot, graph_name=name, reimport=not made,
                                     fixture_root=FIXTURES)
        return made[snapshot]

    yield get
    if made:
        try:
            next(iter(made.values())).g.delete()
        except Exception:
            pass


@pytest.mark.parametrize("snapshot,fleet,disposition,gaps", CASES,
                         ids=[f"{c[0]}-{'+'.join(s + '=' + v for s, v, _ in c[1])}" for c in CASES])
def test_dispositions_on_falkordb(sessions, snapshot, fleet, disposition, gaps):
    from rw import graph as G
    from rw.contracts import FleetEntry, GroundingProposal, ScopeConfirmation

    session = sessions(snapshot)
    changes = []
    for service, version, flags in fleet:
        rows, _ = G.releases_for_service(session.g, service)
        (release,) = [r for r in rows if r["version"] == version]
        changes.append(FleetEntry(service=service, release_id=release["release_id"], flags=flags))
    proposal = GroundingProposal(changes=changes, citations=[], rationale="test fleet")
    plan, errors = session.plan_from_proposal(proposal, "astronomy fixture test", origin="fixture")
    assert plan is not None and not errors, errors
    confirmation = ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by="pytest",
                                     confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    verification = session.verify(plan, confirmation)["verification"]

    assert verification["disposition"] == disposition
    assert {g["kind"] for g in verification["gaps"]} == gaps
    failing = {r["tuple"]["record_id"] for r in verification["receipts"] if r["result"] == "FAIL"}
    local = {r["record_id"] for r in records(snapshot) if r["format"] == LOCAL}
    if disposition == "BLOCKED":
        assert failing == local  # every non-USD order, and only those
    else:
        assert not failing


def test_graph_holds_only_modeled_services(sessions):
    """Services come only from releases and snapshots; no hand-written topology is imported."""
    from rw import graph as G

    session = sessions("snap-001")
    count = lambda q: session.g.ro_query(q).result_set[0][0]  # noqa: E731
    assert count("MATCH (s:Service) RETURN count(s)") == 4
    assert count("MATCH ()-[e:CALLS|USES_STORE]->() RETURN count(e)") == 0
    fleet, _ = G.current_fleet(session.g, session.snapshot_id)
    assert sorted(r["service"] for r in fleet) == ["accounting", "checkout", "fraud-detection", "recommendation"]
    readers, _ = G.store_readers(session.g, "store:orders")
    assert {r["service"] for r in readers} == {"accounting", "fraud-detection"}
