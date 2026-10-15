"""Integration tests for src/rw/graph.py against the live FalkorDB server.

Real server (docker container rw-falkordb, 127.0.0.1:6379) — no mock, no in-memory
graph. Each module run uses its own graph name ``rw_test_<8 hex>`` and deletes it in
teardown.

Expected values are parsed here independently from the fixture files with plain
``json``/``hashlib``/``ast`` (never from rw.graph helpers), so a bug in the importer
cannot silently satisfy the expectations.
"""
from __future__ import annotations

import ast
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from rw import graph as graph_module
from rw.contracts import (
    CandidatePlan,
    FleetEntry,
    ObligationTuple,
    ProbeReceipt,
    ProbeResult,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "shop"
RELEASES = FIXTURES / "releases"
SNAPSHOTS = FIXTURES / "snapshots"

SNAPSHOT_NAMES = ["snap-001", "snap-002-partial", "snap-003-orphan"]
STORE_NAME = "cart-cache"
STORE_ID = f"store:{STORE_NAME}"
SNAP_001 = "snapshot:snap-001"
ORPHAN_SNAPSHOT = "snapshot:snap-003-orphan"


# --------------------------------------------------------------------------- independent fixture parsing


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hh(obj) -> str:
    return digest(canon(obj))


def sh(hash_value: str) -> str:
    return hash_value[7:23]


def load_declarations() -> dict[tuple[str, str], dict]:
    declarations = {}
    for release_dir in sorted(RELEASES.iterdir()):
        decl_path = release_dir / "release.json"
        if not decl_path.is_file():
            continue
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
        files = [
            [path.relative_to(release_dir).as_posix(), digest(path.read_bytes())]
            for path in sorted(release_dir.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        ]
        artifact_hash = hh(files)
        declarations[(decl["service"], decl["version"])] = {
            "decl": decl,
            "dir": release_dir,
            "artifact_hash": artifact_hash,
            "release_id": f"release:{decl['service']}:{sh(artifact_hash)}",
        }
    return declarations


DECLS = load_declarations()
REL = {key: value["release_id"] for key, value in DECLS.items()}
MANIFESTS = {
    name: json.loads((SNAPSHOTS / name / "manifest.json").read_text(encoding="utf-8"))
    for name in SNAPSHOT_NAMES
}
MANIFEST_HASHES = {name: digest((SNAPSHOTS / name / "manifest.json").read_bytes()) for name in SNAPSHOT_NAMES}


def expected_batch_ids(snapshot_name: str) -> set[str]:
    ids = set()
    for store in MANIFESTS[snapshot_name]["stores"]:
        for record in store["records"]:
            payload_hash = record["payload_hash"]
            ids.add(
                f"batch:{store['name']}:{snapshot_name}:{record['record_id']}:"
                f"{sh(payload_hash) if payload_hash else 'UNKNOWN'}"
            )
    return ids


def expected_record_ids(snapshot_name: str) -> set[str]:
    return {
        str(record["record_id"])
        for store in MANIFESTS[snapshot_name]["stores"]
        for record in store["records"]
    }


def expected_route_ids() -> dict[str, str]:
    return {
        f"route:{info['release_id']}:{route['name']}": info["release_id"]
        for info in DECLS.values()
        for route in info["decl"].get("routes", [])
    }


def changelog_bullets(release_dir: Path) -> list[tuple[str, str]]:
    """(span, text) for every CHANGELOG bullet line, read straight from the file."""
    lines = (release_dir / "CHANGELOG.md").read_text(encoding="utf-8").split("\n")
    return [
        (f"{number}-{number}", line)
        for number, line in enumerate(lines, start=1)
        if line.startswith("- ")
    ]


def codec_def_spans(release_dir: Path) -> set[tuple[int, int]]:
    """(start, end) 1-based inclusive line spans of top-level defs, via ast."""
    source = (release_dir / "codec.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {
        (node.lineno, node.end_lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def graph_counts(graph) -> tuple[int, int]:
    nodes = graph.ro_query("MATCH (n) RETURN count(n) AS c").result_set[0][0]
    edges = graph.ro_query("MATCH ()-[e]->() RETURN count(e) AS c").result_set[0][0]
    return nodes, edges


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def client():
    db = graph_module.connect(host="127.0.0.1", port=6379)
    yield db
    db.close()


@pytest.fixture(scope="module")
def graph(client):
    name = f"rw_test_{uuid.uuid4().hex[:8]}"
    summary = graph_module.reset_and_import(client, name, FIXTURES, SNAPSHOT_NAMES)
    handle = client.select_graph(name)
    yield handle, summary
    try:
        handle.delete()
    except Exception:
        pass


# --------------------------------------------------------------------------- 1. import


def test_import_reports_exact_id_sets(graph):
    handle, summary = graph

    assert summary["graph"] == handle.name
    assert summary["snapshots"] == MANIFEST_HASHES

    release_ids = {row[0] for row in handle.ro_query("MATCH (r:Release) RETURN r.id AS id").result_set}
    assert release_ids == set(REL.values())

    for service in ("cart", "checkout"):
        rows, log = graph_module.releases_for_service(handle, service)
        assert log["truncated"] is False
        assert {row["release_id"] for row in rows} == {
            other["release_id"] for key, other in DECLS.items() if key[0] == service
        }
        assert {row["codec_hash"] for row in rows} == {
            digest((other["dir"] / "codec.py").read_bytes())
            for key, other in DECLS.items()
            if key[0] == service
        }

    for name in SNAPSHOT_NAMES:
        rows = handle.ro_query(
            "MATCH (b:Batch {snapshot_id: $snapshot_id}) RETURN b.id AS id, b.record_id AS record_id",
            {"snapshot_id": f"snapshot:{name}"},
        ).result_set
        assert {row[0] for row in rows} == expected_batch_ids(name)
        assert {row[1] for row in rows} == expected_record_ids(name)

    manifest = MANIFESTS["snap-001"]
    assert summary["snapshots"]["snap-001"] == MANIFEST_HASHES["snap-001"]
    rows = handle.ro_query(
        "MATCH (s:Snapshot {id: $sid})-[:HAS_DEPLOYMENT]->(d:Deployment) "
        "RETURN d.id AS id, d.service AS service, d.version AS version",
        {"sid": SNAP_001},
    ).result_set
    assert {(row[1], row[2]) for row in rows} == {
        (entry["service"], entry["version"]) for entry in manifest["deployments"]
    }
    assert {row[0] for row in rows} == {
        f"deployment:{SNAP_001}:{entry['service']}" for entry in manifest["deployments"]
    }

    # PREVIOUS follows the explicit previous_version build of the same service.
    previous = {
        row[0]: row[1]
        for row in handle.ro_query(
            "MATCH (a:Release)-[:PREVIOUS]->(b:Release) RETURN a.id AS newer, b.id AS older"
        ).result_set
    }
    assert previous == {
        REL[("cart", "1.5")]: REL[("cart", "1.4")],
        REL[("checkout", "2.1")]: REL[("checkout", "2.0")],
    }

    # No null placeholder survived: the orphan batch has no format_id property at all.
    stored = handle.ro_query(
        "MATCH (b:Batch {record_id: 'saved-cart-3003'}) "
        "RETURN b.format_id AS format_id, b.payload_hash AS payload_hash"
    ).result_set
    assert stored == [[None, digest((FIXTURES / "payloads" / "saved-cart-3003.bin").read_bytes())]]


# --------------------------------------------------------------------------- 2. current_fleet


def test_current_fleet_snap_001(graph):
    handle, _ = graph
    rows, log = graph_module.current_fleet(handle, SNAP_001)

    assert log == {
        "name": "current_fleet",
        "params": {"snapshot_id": SNAP_001, "limit": 201},
        "rows": 2,
        "truncated": False,
    }
    assert rows == [
        {
            "service": "cart",
            "deployment_id": f"deployment:{SNAP_001}:cart",
            "release_id": REL[("cart", "1.5")],
            "version": "1.5",
            "flags": {"basket_v2": True},
            "declared_flags": [{"name": "basket_v2", "default": True}],
            "bundle_id": "rollout-2026-10-basket",
            "built_at": "2026-10-06T09:00:00Z",
        },
        {
            "service": "checkout",
            "deployment_id": f"deployment:{SNAP_001}:checkout",
            "release_id": REL[("checkout", "2.1")],
            "version": "2.1",
            "flags": {},
            "declared_flags": [],
            "bundle_id": "rollout-2026-10-basket",
            "built_at": "2026-10-06T09:05:00Z",
        },
    ]


# --------------------------------------------------------------------------- 3. release_history


def test_release_history_walks_previous_edges(graph):
    handle, _ = graph
    rows, log = graph_module.release_history(handle, SNAP_001, "cart")

    assert log["truncated"] is False
    assert [row["version"] for row in rows] == ["1.5", "1.4"]
    assert [row["depth"] for row in rows] == [0, 1]

    head, older = rows
    assert head["release_id"] == REL[("cart", "1.5")]
    assert head["release_id"] != older["release_id"]
    assert older["release_id"] == REL[("cart", "1.4")]
    assert head["previous_release_id"] == REL[("cart", "1.4")]
    assert older["previous_release_id"] is None
    assert head["declared_flags"] == [{"name": "basket_v2", "default": True}]

    # The 1.5 changelog excerpt is what carries basket_v2.
    basket = [
        excerpt
        for excerpt in head["excerpts"]
        if excerpt["kind"] == "changelog" and "basket_v2" in excerpt["text"]
    ]
    assert basket, "expected a changelog excerpt mentioning basket_v2"

    expected_changelog = {
        (f"excerpt:{sh(DECLS[('cart', '1.5')]['artifact_hash'])}:CHANGELOG.md:{span}", span, text)
        for span, text in changelog_bullets(DECLS[("cart", "1.5")]["dir"])
    }
    actual_changelog = {
        (excerpt["excerpt_id"], excerpt["span"], excerpt["text"])
        for excerpt in head["excerpts"]
        if excerpt["kind"] == "changelog"
    }
    assert actual_changelog == expected_changelog

    # One excerpt per top-level def, with ast line spans and a content hash of the text.
    code = [excerpt for excerpt in head["excerpts"] if excerpt["kind"] == "code"]
    assert {(int(e["span"].split("-")[0]), int(e["span"].split("-")[1])) for e in code} == codec_def_spans(
        DECLS[("cart", "1.5")]["dir"]
    )
    for excerpt in code:
        assert excerpt["path"] == "codec.py"
        assert excerpt["content_hash"] == digest(excerpt["text"].encode("utf-8"))
        assert excerpt["excerpt_id"].startswith(f"excerpt:{sh(DECLS[('cart', '1.5')]['artifact_hash'])}:codec.py:")
    assert {excerpt["text"].split("(")[0] for excerpt in code} == {"def write_cart", "def read_cart", "def health"}

    # get_excerpts round-trips the same rows by id.
    ids = [excerpt["excerpt_id"] for excerpt in head["excerpts"]]
    fetched, fetch_log = graph_module.get_excerpts(handle, ids)
    assert fetch_log["truncated"] is False
    assert [row["excerpt_id"] for row in fetched] == sorted(ids)
    by_id = {row["excerpt_id"]: row for row in fetched}
    for excerpt in head["excerpts"]:
        assert by_id[excerpt["excerpt_id"]]["text"] == excerpt["text"]
        assert by_id[excerpt["excerpt_id"]]["content_hash"] == excerpt["content_hash"]
        assert by_id[excerpt["excerpt_id"]]["release_id"] == head["release_id"]
        assert by_id[excerpt["excerpt_id"]]["span"] == excerpt["span"]


# --------------------------------------------------------------------------- 4. store_readers


def test_store_readers_lists_all_four_releases(graph):
    handle, _ = graph
    rows, log = graph_module.store_readers(handle, STORE_ID)

    assert log["truncated"] is False
    expected = expected_route_ids()
    assert {(row["route_id"], row["release_id"]) for row in rows} == set(expected.items())
    assert {row["route_id"] for row in rows} == set(expected)

    by_release = {row["release_id"]: row for row in rows}
    assert by_release[REL[("cart", "1.4")]]["currently_deployed_in"] == []
    assert sorted(by_release[REL[("cart", "1.5")]]["currently_deployed_in"]) == [
        "snapshot:snap-001",
        "snapshot:snap-002-partial",
        "snapshot:snap-003-orphan",
    ]
    assert by_release[REL[("cart", "1.5")]]["entry"] == "read_cart"
    assert by_release[REL[("checkout", "2.0")]]["entry"] == "read_cart_for_pricing"


# --------------------------------------------------------------------------- 5. plan + obligation paths


def build_rollback_plan() -> CandidatePlan:
    return CandidatePlan(
        snapshot_id=SNAP_001,
        snapshot_manifest_hash=MANIFEST_HASHES["snap-001"],
        request_text_hash=digest(b"roll cart back to 1.4, keep checkout on 2.1"),
        fleet=[
            FleetEntry(service="cart", release_id=REL[("cart", "1.4")], flags={}, changed=True),
            FleetEntry(service="checkout", release_id=REL[("checkout", "2.1")], flags={}, changed=False),
        ],
        source_hashes=[],
        origin="fixture",
        label="test: roll cart back to 1.4",
    )


def test_write_plan_is_idempotent_and_obligation_paths_are_four(graph):
    handle, _ = graph
    plan = build_rollback_plan()

    plan_id = graph_module.write_plan(handle, plan)
    assert plan_id == plan.plan_id()
    after_first = graph_counts(handle)

    assert graph_module.write_plan(handle, plan) == plan_id
    assert graph_counts(handle) == after_first, "write_plan must not add nodes or edges twice"

    assert handle.ro_query(
        "MATCH (p:Plan {id: $plan_id})-[:BASED_ON]->(s:Snapshot {id: $snapshot_id}) "
        "RETURN count(p) AS c",
        {"plan_id": plan_id, "snapshot_id": SNAP_001},
    ).result_set == [[1]]

    rows, log = graph_module.obligation_paths(handle, plan_id, SNAP_001)
    assert log == {
        "name": "obligation_paths",
        "params": {"plan_id": plan_id, "snapshot_id": SNAP_001, "limit": 201},
        "rows": 4,
        "truncated": False,
    }
    expected_pairs = {
        (f"deployment:{plan_id}:{service}", record_id)
        for service in ("cart", "checkout")
        for record_id in ("saved-cart-1001", "saved-cart-2002")
    }
    assert {(row["deployment_id"], row["record_id"]) for row in rows} == expected_pairs

    writers = {row["record_id"]: row["writer_version"] for row in rows}
    assert writers == {"saved-cart-1001": "1.4", "saved-cart-2002": "1.5"}
    assert {row["writer_release_id"] for row in rows} == {REL[("cart", "1.4")], REL[("cart", "1.5")]}

    assert {row["plan_id"] for row in rows} == {plan_id}
    assert {row["store_id"] for row in rows} == {STORE_ID}
    declared_routes = expected_route_ids()
    for row in rows:
        assert declared_routes[row["route_id"]] == row["release_id"]
    manifest_hashes = {
        str(record["record_id"]): record["payload_hash"]
        for store in MANIFESTS["snap-001"]["stores"]
        for record in store["records"]
    }
    for row in rows:
        assert row["payload_hash"] == manifest_hashes[row["record_id"]]
    cart_rows = [row for row in rows if row["deployment_id"].endswith(":cart")]
    checkout_rows = [row for row in rows if row["deployment_id"].endswith(":checkout")]
    assert {row["release_id"] for row in cart_rows} == {REL[("cart", "1.4")]}
    assert {row["release_id"] for row in checkout_rows} == {REL[("checkout", "2.1")]}
    assert {row["batch_id"] for row in rows} == expected_batch_ids("snap-001")

    route_rows, route_log = graph_module.plan_reader_routes(handle, plan_id)
    assert route_log["truncated"] is False
    assert {row["service"] for row in route_rows} == {"cart", "checkout"}
    assert {row["deployment_id"] for row in route_rows} == {
        f"deployment:{plan_id}:cart",
        f"deployment:{plan_id}:checkout",
    }
    assert all(row["no_state_read"] is False for row in route_rows)
    cart_route = next(row for row in route_rows if row["service"] == "cart")
    assert cart_route["release_id"] == REL[("cart", "1.4")]
    assert cart_route["store_id"] == STORE_ID
    assert cart_route["read_domain"] == "ALL_KEYS"
    assert cart_route["codec_hash"] == digest((DECLS[("cart", "1.4")]["dir"] / "codec.py").read_bytes())
    assert cart_route["codec_path"] == "fixtures/shop/releases/cart-1.4/codec.py"
    assert cart_route["route_id"] == f"route:{REL[('cart', '1.4')]}:load_saved_cart"
    assert cart_route["route_contract_hash"] == hh(DECLS[("cart", "1.4")]["decl"]["routes"][0])


# --------------------------------------------------------------------------- 6. orphan record


def test_orphan_record_is_visible_with_unknown_writer_and_format(graph):
    handle, _ = graph
    coverage_row, batch_rows, log = graph_module.store_inventory(handle, ORPHAN_SNAPSHOT, STORE_ID)

    assert log["name"] == "store_inventory"
    assert log["truncated"] is False
    assert coverage_row == {
        "coverage_id": "coverage:snap-003-orphan:cart-cache",
        "status": "COMPLETE",
        "inventory_id_hash": hh(sorted(expected_record_ids("snap-003-orphan"))),
    }
    assert {row["batch_id"] for row in batch_rows} == expected_batch_ids("snap-003-orphan")
    assert {row["record_id"] for row in batch_rows} == expected_record_ids("snap-003-orphan")

    orphan = [row for row in batch_rows if row["record_id"] == "saved-cart-3003"]
    assert len(orphan) == 1
    assert orphan[0]["writer_release_id"] is None
    assert orphan[0]["format_id"] is None
    assert orphan[0]["in_store"] is True
    assert orphan[0]["payload_hash"] == digest(
        (FIXTURES / "payloads" / "saved-cart-3003.bin").read_bytes()
    )
    assert orphan[0]["payload_path"] == "fixtures/shop/payloads/saved-cart-3003.bin"

    assert handle.ro_query(
        "MATCH (b:Batch {id: $batch_id})-[:WRITTEN_BY]->(w:Release) RETURN count(w) AS c",
        {"batch_id": orphan[0]["batch_id"]},
    ).result_set == [[0]]

    writers = {row["record_id"]: row["writer_release_id"] for row in batch_rows}
    assert writers == {
        "saved-cart-1001": REL[("cart", "1.4")],
        "saved-cart-2002": REL[("cart", "1.5")],
        "saved-cart-3003": None,
    }

    # The partial snapshot reports its own coverage status honestly.
    partial_coverage, partial_rows, _ = graph_module.store_inventory(
        handle, "snapshot:snap-002-partial", STORE_ID
    )
    assert partial_coverage["status"] == "PARTIAL"
    assert len(partial_rows) == 2


# --------------------------------------------------------------------------- 7. truncation


def test_truncation_is_reported_at_cap_plus_one(graph):
    handle, _ = graph

    rows, log = graph_module.store_readers(handle, STORE_ID, cap=1)
    assert len(rows) == 1
    assert log["truncated"] is True
    assert log["params"]["limit"] == 2
    assert log["rows"] == 1

    coverage_row, batch_rows, log = graph_module.store_inventory(handle, SNAP_001, STORE_ID, cap=1)
    assert len(batch_rows) == 1
    assert log["truncated"] is True
    assert log["params"]["limit"] == 2

    rows, log = graph_module.current_fleet(handle, SNAP_001, cap=1)
    assert len(rows) == 1
    assert log["truncated"] is True

    # Exactly at the cap is not truncation.
    rows, log = graph_module.current_fleet(handle, SNAP_001, cap=2)
    assert len(rows) == 2
    assert log["truncated"] is False


# --------------------------------------------------------------------------- 8. receipts


def build_receipt() -> ProbeReceipt:
    cart_15 = DECLS[("cart", "1.5")]
    batch_id = next(
        batch
        for batch in expected_batch_ids("snap-001")
        if batch.endswith(sh(digest((FIXTURES / "payloads" / "saved-cart-2002.bin").read_bytes())))
    )
    obligation = ObligationTuple(
        scope_id="fixture-shop",
        plan_hash=hh({"synthetic": "test-plan"}),
        snapshot_id=SNAP_001,
        snapshot_manifest_hash=MANIFEST_HASHES["snap-001"],
        service="cart",
        deployment_id="deployment:plan:synthetic-cart",
        release_id=cart_15["release_id"],
        codec_hash=digest((cart_15["dir"] / "codec.py").read_bytes()),
        route_id=f"route:{cart_15['release_id']}:load_saved_cart",
        route_contract_hash=hh(cart_15["decl"]["routes"][0]),
        store_id=STORE_ID,
        batch_id=batch_id,
        record_id="saved-cart-2002",
        payload_hash=digest((FIXTURES / "payloads" / "saved-cart-2002.bin").read_bytes()),
        format_id="cart/v2",
        probe_spec_hash=hh({"family": "byte_shape_v1", "entry": "read_cart"}),
        environment_hash=hh({"python": [3, 12, 0], "platform": "win32"}),
    )
    stdout = b'{"status": "FAIL", "error_type": "ValueError", "message": "unsupported saved-cart format"}'
    return ProbeReceipt(
        obligation_hash=obligation.obligation_hash(),
        tuple=obligation,
        result=ProbeResult.FAIL,
        harness_exit=10,
        stdout_excerpt=stdout.decode(),
        evidence_hash=digest(stdout),
        error_type="ValueError",
        message="unsupported saved-cart format 'cart/v2'",
        executed_at="2026-10-15T09:00:00Z",
        duration_ms=42,
    )


def test_write_receipt_and_receipts_for_round_trip(graph):
    handle, _ = graph
    receipt = build_receipt()

    probe_id = graph_module.write_receipt(handle, receipt)
    assert probe_id.startswith("probe:")
    assert graph_module.write_receipt(handle, receipt) == probe_id, "same receipt must not duplicate"

    rows, log = graph_module.receipts_for(handle, [receipt.obligation_hash])
    assert log["truncated"] is False
    assert len(rows) == 1
    row = rows[0]
    assert row["probe_id"] == probe_id
    assert row["obligation_hash"] == receipt.obligation_hash
    assert row["result"] == "FAIL"
    assert json.loads(row["receipt_json"]) == json.loads(receipt.model_dump_json())
    assert ProbeReceipt.model_validate_json(row["receipt_json"]) == receipt

    assert handle.ro_query(
        "MATCH (pr:ProbeRun {id: $probe_id})-[:TESTS_READER]->(r:Release) RETURN r.id AS id",
        {"probe_id": probe_id},
    ).result_set == [[REL[("cart", "1.5")]]]
    assert handle.ro_query(
        "MATCH (pr:ProbeRun {id: $probe_id})-[:TESTS_BATCH]->(b:Batch) RETURN b.id AS id",
        {"probe_id": probe_id},
    ).result_set == [[receipt.tuple.batch_id]]

    unknown, log = graph_module.receipts_for(handle, ["sha256:no-such-obligation"])
    assert unknown == []
    assert log["truncated"] is False

    assert handle.ro_query("MATCH (pr:ProbeRun) RETURN count(pr) AS c").result_set == [[1]]
