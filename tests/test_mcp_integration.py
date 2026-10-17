"""The bridge and human console share exactly one API registry and real FalkorDB evidence."""
from copy import deepcopy
import json

import pytest
pytest.importorskip("mcp", reason="optional MCP extra is not installed")

import anyio
import httpx

from rw.contracts import Disposition, ProbeResult, VerificationResult
from rw.mcp_client import BridgeClient, BridgeError
from rw.mcp_server import create_mcp_server
from rw.verification import dispose
from test_api import api, clarifying_api, confirm, plan_url, REQUEST


def test_real_agent_human_shared_workflow(api):
    human, _, app=api
    async def check():
        bridge=BridgeClient(transport=httpx.ASGITransport(app=app))
        server=create_mcp_server(client=bridge)
        try:
            started=await server.call_tool("rw_start_investigation",{"request_text":REQUEST})
            assert not started.is_error
            initial=started.structured_content
            state=human.get(f"/api/investigations/{initial['investigation_id']}").json()
            assert state["id"]==initial["data"]["id"] and initial["next_action"]=="human_confirm_scope"
            assert human.post(plan_url(state)+"/approve",json={"approved_by":"alice"}).status_code==409
            report=confirm(human,state)
            assert report["verification"]["disposition"]=="BLOCKED"
            stored=await bridge.invoke("rw_get_investigation",{"investigation_id":state["id"]})
            assert stored.next_action=="request_alternative"
            assert stored.verification_hash==report["verification_hash"]
            assert stored.data.report.verification.obligations[0].witness_path
            assert "reader_codec_path" not in stored.model_dump_json()
            alt=await bridge.invoke("rw_request_alternative",{"investigation_id":state["id"]})
            assert alt.plan_hash!=initial["plan_hash"] and alt.data.report is None
            assert alt.data.approval is None and alt.next_action=="human_confirm_scope"
            alternate=human.get(f"/api/investigations/{state['id']}").json()
            passing=confirm(human,alternate)
            assert passing["verification"]["disposition"]=="BOUNDED_PASS"
            approval=human.post(plan_url(alternate)+"/approve",json={"approved_by":"alice"})
            assert approval.status_code==200
            first=human.post(plan_url(alternate)+"/simulate").json()
            second=human.post(plan_url(alternate)+"/simulate").json()
            assert first["applied"] and not second["applied"]
            assert first["idempotency_key"]==second["idempotency_key"]
            final=await bridge.invoke("rw_get_investigation",{"investigation_id":state["id"]})
            assert final.next_action=="none" and len(final.data.attempts)==2
            assert final.data.simulation.idempotency_key==first["idempotency_key"]
            listed=await bridge.invoke("rw_list_investigations",{})
            assert [item.id for item in listed.items]==[state["id"]]
            # A new bridge reconnects to the same registry, with no Session/import/reset.
            reconnected=BridgeClient(transport=httpx.ASGITransport(app=app))
            try:
                assert (await reconnected.invoke("rw_get_investigation",{"investigation_id":state["id"]})).plan_hash==alt.plan_hash
            finally:
                await reconnected.aclose()
        finally:
            await bridge.aclose()
    anyio.run(check)


@pytest.mark.parametrize("corruption", ["plan_hash","verification_hash","snapshot","disposition","obligation", "receipt_ref", "duplicate_obligation", "duplicate_receipt", "confirmation", "alias"])
def test_tampered_evidence_is_not_projected(api,corruption):
    human,_,app=api
    initial=human.post("/api/investigations",json={"request_text":REQUEST}).json()
    confirm(human,initial)
    state=human.get(f"/api/investigations/{initial['id']}").json()
    report=state["attempts"][0]["report"]
    v=report["verification"]
    if corruption=="plan_hash":
        state["attempts"][0]["plan"]["fleet"][0]["flags"]={"injected":True}
    elif corruption=="verification_hash": report["verification_hash"]="sha256:"+"0"*64
    elif corruption=="snapshot": v["snapshot_id"]="snapshot:snap-002-partial"
    elif corruption=="disposition":
        v["disposition"]="BOUNDED_PASS"
        report["verification_hash"]=VerificationResult.model_validate(v).verification_hash()
    elif corruption=="obligation": v["obligations"][0]["tuple"]["payload_hash"]="sha256:"+"0"*64
    elif corruption=="receipt_ref": v["receipts"][0]["obligation_hash"]="sha256:"+"0"*64
    elif corruption=="duplicate_obligation": v["obligations"].append(deepcopy(v["obligations"][0]))
    elif corruption=="duplicate_receipt": v["receipts"].append(deepcopy(v["receipts"][0]))
    elif corruption=="confirmation": report["scope_confirmation"]["plan_hash"]="sha256:"+"0"*64
    if corruption!="alias":
        for key,value in state["attempts"][0].items(): state[key]=deepcopy(value)
    else: state["plan_hash"]="sha256:"+"0"*64
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=state)))
        try:
            with pytest.raises(BridgeError,match="invalid_backend_response"):
                await bridge.invoke("rw_get_investigation",{"investigation_id":initial["id"]})
        finally: await bridge.aclose()
    anyio.run(check)


def test_multiple_distinct_receipts_preserve_fail_dominance(api):
    human,_,app=api
    initial=human.post("/api/investigations",json={"request_text":REQUEST}).json()
    confirm(human,initial)
    state=human.get(f"/api/investigations/{initial['id']}").json()
    report=state["attempts"][0]["report"]
    v=VerificationResult.model_validate(report["verification"])
    failed=next(r for r in v.receipts if r.result==ProbeResult.FAIL)
    extra=failed.model_copy(update={"result":ProbeResult.PASS})
    v=v.model_copy(update={"receipts":[*v.receipts,extra]})
    report["verification"]=v.model_dump(mode="json")
    report["verification_hash"]=v.verification_hash()
    state["report"]=deepcopy(report)
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=state)))
        try:
            result=await bridge.invoke("rw_get_investigation",{"investigation_id":initial["id"]})
            assert result.data.report.verification.disposition.value=="BLOCKED"
            assert len(result.data.report.verification.receipts)==len(v.receipts)
        finally: await bridge.aclose()
    anyio.run(check)


@pytest.mark.parametrize("snapshot", ["snap-002-partial","snap-003-orphan"])
def test_negative_snapshots_keep_missing_evidence_and_scope_binding(api,tmp_path,snapshot):
    from fastapi.testclient import TestClient
    from rw.api import create_app
    from rw import graph
    from rw.pipeline import Session
    from rw.contracts import Citation,FleetEntry,GroundingProposal,GroundingResult
    human,_,base=api
    initial=human.post("/api/investigations",json={"request_text":REQUEST}).json()
    session=base.state.investigations[initial["id"]].session
    rows,_=graph.releases_for_service(session.g,"cart")
    release=next(r for r in rows if r["version"]=="1.5")
    history,_=graph.release_history(session.g,session.snapshot_id,"cart")
    excerpt=next(ex for row in history if row["release_id"]==release["release_id"]
                 for ex in row["excerpts"] if ex["kind"]=="changelog")
    citation=Citation(excerpt_id=excerpt["excerpt_id"],content_hash=excerpt["content_hash"],quote=excerpt["text"])
    def ground(request,tools,alternative_context=None):
        return GroundingResult(request_text=request,result=GroundingProposal(changes=[FleetEntry(service="cart",
            release_id=release["release_id"],flags={"basket_v2":False})],citations=[citation],rationale="deterministic"),model="test",live=False),None
    app=create_app(session_factory=lambda snapshot:Session(snapshot=snapshot,graph_name=session.graph_name,reimport=False),
        ground_function=ground,db_path=tmp_path/"negative.sqlite")
    with TestClient(app) as console:
        async def check():
            bridge=BridgeClient(transport=httpx.ASGITransport(app=app))
            try:
                started=await bridge.invoke("rw_start_investigation",{"request_text":REQUEST,"snapshot":snapshot})
                state=console.get(f"/api/investigations/{started.investigation_id}").json()
                report=confirm(console,state)
                assert report["verification"]["disposition"]=="NEEDS_EVIDENCE"
                result=await bridge.invoke("rw_get_investigation",{"investigation_id":started.investigation_id})
                assert result.snapshot_id=="snapshot:"+snapshot
                assert result.data.report.verification.gaps and result.next_action=="request_alternative"
            finally: await bridge.aclose()
        anyio.run(check)


def test_replay_metadata_and_labeling_are_preserved(api):
    _,_,app=api
    async def check():
        bridge=BridgeClient(transport=httpx.ASGITransport(app=app))
        try:
            listed=await bridge.invoke("rw_list_transcripts",{})
            assert listed.items[0].replay_path=="fake-replay.json"
            result=await bridge.invoke("rw_start_investigation",{"request_text":REQUEST,"mode":"replay","replay_path":"fake-replay.json"})
            assert not result.live and result.model=="replay:fake-replay.json"
            assert result.data.transcript=="fake-replay.json"
        finally: await bridge.aclose()
    anyio.run(check)


def test_clarification_answer_has_exact_binding_and_one_round(clarifying_api):
    human,calls,question,with_answer=clarifying_api
    async def check():
        # Same ASGI application as the human TestClient, with real Session and probes.
        bridge=BridgeClient(transport=httpx.ASGITransport(app=human.app))
        try:
            state=await bridge.invoke("rw_start_investigation",{"request_text":REQUEST})
            assert state.next_action=="answer_clarification" and state.plan_hash is None
            answered=await bridge.invoke("rw_answer_clarification",{"investigation_id":state.investigation_id,"answer":"  yes π  "})
            assert answered.data.request_text==with_answer(REQUEST,question,"yes π")
            assert answered.data.original_request_text==REQUEST and answered.data.answered
            assert len(answered.data.attempts)==2 and answered.next_action=="human_confirm_scope"
            with pytest.raises(BridgeError,match="state_conflict"):
                await bridge.invoke("rw_answer_clarification",{"investigation_id":state.investigation_id,"answer":"again"})
            assert len(calls)==2
        finally: await bridge.aclose()
    anyio.run(check)


def test_zero_obligation_report_retains_bindings(api):
    human,_,_=api
    initial=human.post("/api/investigations",json={"request_text":REQUEST}).json()
    confirm(human,initial)
    state=human.get(f"/api/investigations/{initial['id']}").json()
    report=state["attempts"][0]["report"]
    v=VerificationResult.model_validate(report["verification"])
    v=v.model_copy(update={"obligations":[],"receipts":[],"gaps":[],"blocking_receipts":[],"disposition":Disposition.BOUNDED_PASS})
    report["verification"]=v.model_dump(mode="json");report["verification_hash"]=v.verification_hash()
    state["report"]=deepcopy(report)
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=state)))
        try:
            result=await bridge.invoke("rw_get_investigation",{"investigation_id":initial["id"]})
            assert result.data.report.verification.obligations==[]
            assert result.data.report.verification.snapshot_id==state["snapshot_id"]
            assert result.plan_hash==state["plan_hash"]
        finally: await bridge.aclose()
    anyio.run(check)
