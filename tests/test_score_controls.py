"""Full identity regressions, including real graph reports and offline provider transcripts."""
from copy import deepcopy
import json
import os
import secrets
import subprocess
import sys

import pytest

from evals import llm_control as control, relational_control as sql, score_controls as scoring
from evals.obligation_identity import FIELDS, obligation_key, oracle_obligations
from rw.pipeline import Session

ORACLE_PATH = scoring.REPO_ROOT / "evals/expected/obligation_identity.json"


@pytest.fixture(scope="module")
def identity_indices(identity_fixture_root):
    fixtures = scoring.fixture_index(identity_fixture_root)
    manifests = {name: scoring.manifest_index(identity_fixture_root, name)
                 for name in ("snap-001", "snap-002-partial", "snap-003-orphan")}
    oracle = scoring.load_oracle(ORACLE_PATH)
    return fixtures, manifests, oracle, scoring.oracle_index(oracle, fixtures, manifests)


def scripted_transport(case, provider):
    """Provider-native calls with exact authored identities; tools still execute real probes."""
    calls = [{"name": control.PROBE_TOOL, "args": {field: ob[field] for field in FIELDS}}
             for ob in case["obligations"]]
    terminal = {"name": control.TERMINAL_TOOL,
                "args": {"fleet": case["fleet"], "disposition": case["disposition"],
                         "evidence": ["scripted fixture experiment; probe results in transcript"]}}
    script = [calls, [terminal]]
    bodies = []

    def transport(body):
        bodies.append(body)
        batch = script.pop(0)
        if provider == "gemini":
            return {"candidates": [{"content": {"role": "model", "parts": [
                {"functionCall": item} for item in batch]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call-{len(bodies)}-{index}", "type": "function",
             "function": {"name": item["name"], "arguments": json.dumps(item["args"])}}
            for index, item in enumerate(batch)]}}]}

    transport.provider = provider
    transport.model_used = "offline-scripted-identity"
    transport.bodies = bodies
    return transport


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize("case_index", [0, 1], ids=["blocked", "passing"])
def test_full_pipeline_sql_and_control_score(identity_fixture_root, identity_indices, oracle_graphs,
                                            tmp_path, provider, case_index):
    fixtures, manifests, oracle, oi = identity_indices
    case = oracle["cases"][case_index]
    manifest = manifests[case["snapshot"]]
    expected = oracle_obligations(case)
    required, gaps = scoring.reader_obligations(fixtures, manifest, case["fleet"])
    assert len(required) == 7 and set(required) == set(expected) and gaps == []
    assert scoring.derived_disposition(required, oi["predictions"], gaps)[0] == case["disposition"]

    # Run the real graph materializer and trusted checker against the SAME copied fixture.
    import uuid
    state = oracle_graphs.setdefault(identity_fixture_root,
                                    {"name": f"rw_test_{uuid.uuid4().hex[:12]}", "imported": False})
    session = Session(fixture_root=identity_fixture_root, graph_name=state["name"],
                      reimport=not state["imported"])
    state["imported"] = True
    verification = sql.graph_obligations(session, {s: spec["version"] for s, spec in case["fleet"].items()},
                                         {s: spec["flags"] for s, spec in case["fleet"].items()})
    ids = sql.release_ids(identity_fixture_root)
    with sql.load_facts(identity_fixture_root) as conn:
        rows = sql.obligations(conn, case["snapshot"], {s: spec["version"] for s, spec in case["fleet"].items()})
    assert sql.sql_keys(rows, ids) == sql.graph_keys(verification, ids) == set(expected)
    assert len(rows) == len(verification["obligations"]) == 7
    assert verification["disposition"] == case["disposition"]
    report = {"snapshot": case["snapshot"], "attempts": [{"report": {
        "plan": {"fleet": [{"service": service,
                              "release_id": fixtures["by_service_version"][(service, spec["version"])]["release_id"],
                              "flags": spec["flags"]} for service, spec in case["fleet"].items()]},
        "verification": verification}}]}
    product_run, = scoring.runs_from_report(report, fixtures, manifest)
    assert product_run["probed"] == expected
    product_row = scoring.score_run(product_run, oi, fixtures, manifests)
    assert product_row["recall"] == "7/7" and scoring.consistent(product_row)

    transport = scripted_transport(case, provider)
    transcript, path = control.run_control(transport=transport, fixture_root=identity_fixture_root,
                                          artifact_dir=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["control_version"] == 5
    assert all(obligation_key(call) in expected for call in saved["probe_calls"])
    assert all(item["sha256"].startswith("sha256:") for item in saved["context_files"])
    context = (transport.bodies[0]["contents"][0]["parts"][0]["text"] if provider == "gemini"
               else transport.bodies[0]["messages"][1]["content"])
    for key in expected:
        assert key[2] in context and key[3] in context
    assert "archived-cart-2002.bin" in context
    assert '{"archived":true,' not in context  # payload bytes remain behind the probe
    control_run = scoring.run_from_control(saved, fixtures, manifest)
    assert control_run["probed"] == expected
    assert all(call["result"]["status"] == expected[obligation_key(call)] for call in transcript["probe_calls"])
    row = scoring.score_run(control_run, oi, fixtures, manifests)
    assert row["recall"] == "7/7" and scoring.consistent(row)
    assert row["critical_probed"] and row["critical_required"] == row["critical_probed_count"] == 3

    # Remove each individual route/store observation: no other result can discharge it.
    for missing in expected:
        incomplete = deepcopy(control_run)
        del incomplete["probed"][missing]
        partial = scoring.score_run(incomplete, oi, fixtures, manifests)
        assert partial["recall"] == "6/7" and not scoring.consistent(partial)
        incomplete_product = deepcopy(report)
        incomplete_product["attempts"][0]["report"]["verification"]["obligations"] = [
            ob for ob in verification["obligations"]
            if obligation_key({**ob["tuple"], "version": missing[1]}) != missing]
        run, = scoring.runs_from_report(incomplete_product, fixtures, manifest)
        assert scoring.score_run(run, oi, fixtures, manifests)["recall"] == "6/7"

    if case["disposition"] == "BLOCKED":
        failed, = [key for key, result in expected.items() if result == "FAIL"]
        assert any(key[0:2] == failed[0:2] and key[3:] == failed[3:] and result == "PASS"
                   for key, result in expected.items())
        incomplete = deepcopy(control_run)
        del incomplete["probed"][failed]
        incomplete["disposition"] = "BOUNDED_PASS"
        partial = scoring.score_run(incomplete, oi, fixtures, manifests)
        assert partial["false_pass"] and not partial["critical_probed"]
        assert partial["critical_probed_count"] == 2


def test_explicit_route_store_validation_before_subprocess(identity_fixture_root, identity_indices, monkeypatch):
    fixtures, _manifests, oracle, _oi = identity_indices
    tools = control.FlatControlTools(identity_fixture_root)
    ob = oracle["cases"][0]["obligations"][0]
    valid = {field: ob[field] for field in FIELDS}

    def forbidden(*args):
        pytest.fail("invalid identity reached the subprocess")

    monkeypatch.setattr(control, "_run_harness", forbidden)
    foreign = fixtures["by_service_version"][("cart", "1.5")]["routes"][0]["route_id"]
    for change in ({"route_id": "unknown"}, {"route_id": foreign}, {"store_id": "store:cart-archive"},
                   {"store_id": "cart-cache"}, {"record_id": "absent"}, {"route_id": None},
                   {"service": "checkout"}, {"version": "1.5"}):
        with pytest.raises(ValueError):
            tools.run_reader_probe(**{**valid, **change})
    with pytest.raises(TypeError):
        tools.run_reader_probe(service="cart", version="1.4", record_id="saved-cart-2002")


def test_duplicate_record_ids_dispatch_different_store_bytes(identity_fixture_root, identity_indices):
    _fixtures, _manifests, oracle, _oi = identity_indices
    tools = control.FlatControlTools(identity_fixture_root)
    obs = [ob for ob in oracle["cases"][0]["obligations"]
           if ob["service"] == "cart" and ob["record_id"] == "saved-cart-2002"]
    assert len(obs) == 3
    assert tools.records[("store:cart-cache", "saved-cart-2002")]["payload_hash"] != \
        tools.records[("store:cart-archive", "saved-cart-2002")]["payload_hash"]
    assert [tools.run_reader_probe(**{f: ob[f] for f in FIELDS})["status"] for ob in obs] == ["FAIL", "PASS", "PASS"]


def test_authored_predictions_against_direct_harness(identity_fixture_root, identity_indices):
    """Check predictions outside both the graph checker and the control dispatcher."""
    _fixtures, _manifests, oracle, _oi = identity_indices
    manifest = json.loads((identity_fixture_root / "snapshots/snap-001/manifest.json").read_text())
    records = {("store:" + store["name"], rec["record_id"]): rec
               for store in manifest["stores"] for rec in store["records"]}
    for case in oracle["cases"]:
        for ob in case["obligations"]:
            directory = identity_fixture_root / "releases" / f"{ob['service']}-{ob['version']}"
            declaration = json.loads((directory / "release.json").read_text())
            route = next(route for route in declaration["routes"]
                         if ob["route_id"].endswith(":" + route["name"]))
            rec = records[(ob["store_id"], ob["record_id"])]
            payload = (identity_fixture_root / rec["payload"]).read_bytes()
            assert scoring._bh(payload) == rec["payload_hash"]
            nonce = secrets.token_hex(16)
            proc = subprocess.run([sys.executable, "-I", str(identity_fixture_root / "harness/run_reader.py"),
                                   str(directory / "codec.py"), route["entry"]], input=payload,
                                  capture_output=True, timeout=10,
                                  env={"RW_PROBE_NONCE": nonce, "PATH": os.environ.get("PATH", ""),
                                       "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
            result = json.loads(proc.stdout)
            assert result["nonce"] == nonce
            assert result["status"] == ob["expected_probe"]
            assert proc.returncode == (10 if ob["expected_probe"] == "FAIL" else 0)


def test_legacy_inference_is_unique_and_never_expands(identity_indices):
    fixtures, manifests, oracle, _oi = identity_indices
    legacy = {"snapshot": "snap-001", "result": {"fleet": oracle["cases"][0]["fleet"]},
              "probe_calls": [{"service": "cart", "version": "1.4", "record_id": "saved-cart-2002",
                               "result": {"status": "PASS"}},
                              {"service": "checkout", "version": "2.1", "record_id": "saved-cart-2002",
                               "result": {"status": "PASS"}}]}
    run = scoring.run_from_control(legacy, fixtures, manifests["snap-001"])
    assert len(run["probed"]) == 1
    assert next(iter(run["probed"]))[0] == "checkout"
    assert any("ambiguous or invalid legacy" in note for note in run["fleet_notes"])
    assert any("inferred unique legacy" in note for note in run["fleet_notes"])
    legacy["control_version"] = 5
    assert not scoring.run_from_control(legacy, fixtures, manifests["snap-001"])["probed"]


def test_wrong_store_and_missing_identity_receive_no_credit(identity_indices):
    fixtures, manifests, oracle, _oi = identity_indices
    ob = oracle["cases"][0]["obligations"][0]
    for change in ({"store_id": "store:cart-archive"}, {"route_id": "route:foreign"}, {"store_id": None}):
        call = {**{f: ob[f] for f in FIELDS}, **change, "result": {"status": "PASS"}}
        run = scoring.run_from_control({"probe_calls": [call]}, fixtures, manifests["snap-001"])
        assert run["probed"] == {}


def test_retries_deduplicate_only_the_complete_identity(identity_indices):
    fixtures, manifests, oracle, _oi = identity_indices
    calls = [{**{f: ob[f] for f in FIELDS}, "result": {"status": ob["expected_probe"]}}
             for ob in oracle["cases"][0]["obligations"]]
    transcript = {"control_version": 5, "probe_calls": [*calls, calls[0], calls[1]]}
    run = scoring.run_from_control(transcript, fixtures, manifests["snap-001"])
    assert run["probed"] == oracle_obligations(oracle["cases"][0])
    assert len(run["probed"]) == 7


def test_oracle_rejects_duplicates_missing_fields_and_prediction_conflicts(identity_indices):
    fixtures, manifests, oracle, _oi = identity_indices
    for change in ("duplicate", "missing"):
        altered = deepcopy(oracle)
        case = altered["cases"][0]
        if change == "duplicate":
            case["obligations"].append(deepcopy(case["obligations"][0]))
        else:
            del case["obligations"][0]["store_id"]
        with pytest.raises(ValueError):
            scoring.oracle_index(altered, fixtures, manifests)
    conflict = deepcopy(oracle["cases"][0])
    conflict["id"] = "conflict"
    conflict["obligations"][0]["expected_probe"] = "FAIL"
    with pytest.raises(ValueError, match="conflicting oracle predictions"):
        scoring.oracle_index({"cases": [oracle["cases"][0], conflict]}, fixtures, manifests)
    conflict["snapshot"] = "snap-002-partial"
    indexed = scoring.oracle_index({"cases": [oracle["cases"][0], conflict]}, fixtures, manifests)
    key = obligation_key(conflict["obligations"][0])
    assert indexed["predictions"][("snap-001", *key)] == "PASS"
    assert indexed["predictions"][("snap-002-partial", *key)] == "FAIL"


def test_unpredicted_and_unknown_obligations_remain_unresolved(identity_indices):
    fixtures, manifests, oracle, oi = identity_indices
    required, gaps = scoring.reader_obligations(fixtures, manifests["snap-001"], oracle["cases"][1]["fleet"])
    predictions = deepcopy(oi["predictions"])
    key = next(iter(required))
    del predictions[("snap-001", *key)]
    assert scoring.derived_disposition(required, predictions, gaps)[0] == "NEEDS_EVIDENCE"
    predictions[("snap-001", *key)] = "UNKNOWN"
    assert scoring.derived_disposition(required, predictions, gaps)[0] == "NEEDS_EVIDENCE"


def test_both_provider_schemas_require_complete_probe_identity():
    gemini = control._declarations()[0]["functionDeclarations"][0]["parameters"]
    groq = control._openai_tools()[0]["function"]["parameters"]
    assert set(gemini["required"]) == set(groq["required"]) == set(FIELDS)
