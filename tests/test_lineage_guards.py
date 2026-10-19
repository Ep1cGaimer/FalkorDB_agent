"""Completeness and exact identity guards for explanatory provenance views."""
import json
from types import SimpleNamespace

from rw import graph
from rw.baseline import claim_check
from rw.contracts import h
from rw.verification import applicable_receipts


def origin_row(*, batch="b", node="b", parent=None, valid=True, parents=(), chain=None, hops=0):
    chain = chain or [batch]
    return [batch, "record", "store:ledger", "release:accounting:x", ["record"] * len(chain),
            "origin", "store:orders", "release:checkout:x", "checkout", "3.2.0", hops, node,
            chain, ["snapshot:s"] * len(chain), valid, json.dumps(list(parents)), parent]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def ro_query(self, query, params):
        self.params = params
        return SimpleNamespace(result_set=self.rows[:params["limit"]])


def test_deleted_lineage_edge_cannot_make_a_false_root():
    rows, log = graph.record_origins(Rows([origin_row(parents=["source"])]), "snapshot:s", ["record"])
    assert rows == [] and not log["complete"]
    assert "missing" in log["gaps"][0]["reason"]


def test_invalid_source_declaration_is_not_a_root():
    rows, log = graph.record_origins(Rows([origin_row(valid=False)]), "snapshot:s", ["record"])
    assert rows == [] and not log["complete"]
    assert "unresolved" in log["gaps"][0]["reason"]


def test_cycle_and_depth_limit_are_explicit():
    for path, hops, reason in ((["b", "other", "b"], 2, "cycle"),
                               (["b", "c", "d", "e", "f"], 4, "depth cap")):
        rows, log = graph.record_origins(Rows([origin_row(node=path[-1], parent="next", parents=["next"],
                                                        chain=path, hops=hops)]), "snapshot:s", ["record"])
        assert not rows and not log["complete"]
        assert any(reason in gap["reason"] for gap in log["gaps"])


def test_row_cap_and_missing_requested_batch_stay_incomplete():
    source = Rows([origin_row(), origin_row(batch="other", node="other")])
    rows, log = graph.record_origins(source, "snapshot:s", ["record"], cap=1, batch_ids=["b", "missing"])
    assert source.params["batch_ids"] == ["b", "missing"] and not source.params["all_batches"]
    assert log["truncated"] and not log["complete"] and not rows[0]["lineage_complete"]
    assert any(g["batch_id"] == "missing" for g in log["gaps"])


def test_multiple_root_paths_keep_exact_batch_identity():
    source = Rows([origin_row(node="root-a", chain=["b", "root-a"], hops=1),
                   origin_row(node="root-b", chain=["b", "root-b"], hops=1)])
    rows, log = graph.record_origins(source, "snapshot:s", ["record"], batch_ids=["b"])
    assert log["complete"] and len(rows) == 2
    assert {r["origin_batch_id"] for r in rows} == {"root-a", "root-b"}
    assert {r["batch_id"] for r in rows} == {"b"}


def test_receipts_require_current_hash_and_exact_tuple():
    t = {"service": "a", "record_id": "same", "store_id": "store:a"}
    ob = {"tuple": t, "obligation_hash": h(t)}
    good = {**ob, "result": "PASS"}
    stale = {**ob, "tuple": {**t, "store_id": "store:b"}, "result": "FAIL"}
    fabricated = {**good, "obligation_hash": "forged", "result": "FAIL"}
    verification = {"obligations": [ob], "receipts": [good, stale, fabricated]}
    assert applicable_receipts(verification) == [good]
    assert claim_check({"failing": {"a": ["same"]}}, verification)["claimed_but_passed"] == 1


def test_coarse_baseline_claim_does_not_guess_between_two_stores():
    tuples = [{"service": "a", "record_id": "same", "store_id": store} for store in ("one", "two")]
    obligations = [{"tuple": t, "obligation_hash": h(t)} for t in tuples]
    v = {"obligations": obligations, "receipts": [{**o, "result": "FAIL"} for o in obligations]}
    check = claim_check({"failing": {"a": ["same"]}}, v)
    assert check["confirmed"] == 0 and check["unverifiable"] == 1
    assert check["expected_failing"] == check["missed"] == 2
