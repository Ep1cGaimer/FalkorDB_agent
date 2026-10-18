"""Transport bounds, strict inputs, safe errors and backpressure without a socket or model."""
from copy import deepcopy
import json

import anyio
import httpx
import pytest

from rw.contracts import h
from rw.mcp_client import BridgeClient, BridgeError, base_url

ID = "a" * 32


def clarification_state(request="request"):
    clarification = {"kind": "CLARIFICATION", "question": "Which?", "unresolved": ["basket"], "citations": []}
    attempt = {"grounding": {"request_text": request, "result": clarification, "model": "fake", "live": True,
        "tool_calls": [{"provider_secret_payload": "private-audit"}], "validation_errors": []},
        "is_live_provider": False, "transcript": "/private/grounding/saved.json", "plan": None, "plan_hash": None,
        "citations": [], "validation_errors": [], "clarification": clarification, "report": None,
        "approval": None, "simulation": None, "release_labels": {}}
    return {"id": ID, "investigation_id": ID, "request_text": request, "original_request_text": request,
        "answered": False, "mode": "live", "snapshot_id": "snapshot:snap-001", "snapshot_manifest_hash": h("manifest"),
        "attempts": [deepcopy(attempt)], "release_labels": {}, **attempt}


def run(coro):
    return anyio.run(coro)


@pytest.mark.parametrize("url", ["https://127.0.0.1:8000", "http://localhost:8000", "http://example.com", "file:///tmp/api",
    "http://127.0.0.1.evil", "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://user@127.0.0.1:8000",
    "http://127.0.0.1:8000/path", "http://127.0.0.1:8000?", "http://127.0.0.1:8000#", "http://2130706433"])
def test_network_origin_is_literal_loopback_only(url):
    with pytest.raises(ValueError):
        base_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8123", "http://[::1]:8000/", "http://127.0.0.1"])
def test_valid_origins(url):
    assert base_url(url) == url.rstrip("/")


@pytest.mark.parametrize("name,args", [
    ("rw_start_investigation", {"request_text": " "}),
    ("rw_start_investigation", {"request_text": 1}),
    ("rw_start_investigation", {"request_text": "r", "mode": "replay"}),
    ("rw_start_investigation", {"request_text": "r", "replay_path": "saved.json"}),
    ("rw_start_investigation", {"request_text": "r", "approved_by": "agent"}),
    *[("rw_get_investigation", {"investigation_id": value}) for value in ["A"*32, "a"*31, "a/b", "%2f", "http://127.0.0.1", None, 123]],
    *[("rw_list_investigations", {"limit": value}) for value in [True, "20", 1.0, 0, 101]],
    *[("rw_answer_clarification", {"investigation_id": ID, "answer": value}) for value in ["", " ", None, 12, "a"*4001]],
    *[("rw_request_alternative", {"investigation_id": ID, "replay_path": value}) for value in ["", "../x.json", "a/b.json", "a\\b.json", "C:x.json", "x\x00.json", "x\n.json", "x.txt"]],
])
def test_invalid_input_never_submits_http(name, args):
    calls = []
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda request: calls.append(request)))
        try:
            with pytest.raises(BridgeError, match=r"\[invalid_input\]"):
                await bridge.invoke(name, args)
            assert calls == []
        finally:
            await bridge.aclose()
    run(check)


def test_request_text_preserved_and_projection_omits_only_internal_data():
    request_text = '  ["literal JSON-looking request"]\nπ  '
    state = clarification_state(request_text)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=state)
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(handle))
        try:
            result = await bridge.invoke("rw_start_investigation", {"request_text": request_text})
            assert calls[0].method == "POST" and calls[0].url.path == "/api/investigations"
            assert json.loads(calls[0].content)["request_text"] == request_text
            assert result.next_action == "answer_clarification"
            assert result.review_url == f"http://127.0.0.1:8000/?investigation={ID}"
            data = result.model_dump(mode="json")
            assert data["data"]["transcript"] == "saved.json"
            assert "private-audit" not in json.dumps(data) and "/private/" not in json.dumps(data)
            assert state["transcript"].startswith("/private/")  # projection did not change upstream data
        finally:
            await bridge.aclose()
        assert bridge.http.is_closed
    run(check)


@pytest.mark.parametrize("status,body,code", [
    (404, {"detail":"secret-path"}, "not_found"),
    (422, {"detail":"secret-input"}, "invalid_input"),
    (409, {"detail":"the agent has no open question", "reason":"the agent has no open question"}, "state_conflict"),
    (409, {"detail":"private provider token", "reason":"private provider token"}, "state_conflict"),
    *[(502,{"detail":{"code":c,"message":"private provider token"}},c) for c in ["provider_quota","provider_unavailable","provider_error"]],
    (500, {"detail":"private provider token"}, "invalid_backend_response"),
    (302, {}, "invalid_backend_response"),
])
def test_status_mapping_never_leaks_upstream_text(status, body, code):
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(status,json=body)))
        try:
            with pytest.raises(BridgeError) as error:
                await bridge.invoke("rw_get_investigation", {"investigation_id": ID})
            assert error.value.code == code
            assert not any(s in str(error.value) for s in ["secret", "private", "token"])
        finally:
            await bridge.aclose()
    run(check)


@pytest.mark.parametrize("content,headers", [
    (b"not-json", {"content-type":"application/json"}),
    (b"{}", {"content-type":"text/html"}),
    (b"[]", {"content-type":"application/json"}),
    (b'{"value":NaN}', {"content-type":"application/json"}),
    (b'{"value":Infinity}', {"content-type":"application/json"}),
    (b'{"id":"a","id":"b"}', {"content-type":"application/json"}),
])
def test_bad_json_content_type_and_shapes_fail_closed(content, headers):
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,content=content,headers=headers)))
        try:
            with pytest.raises(BridgeError, match="invalid_backend_response"):
                await bridge.invoke("rw_get_investigation", {"investigation_id": ID})
        finally:
            await bridge.aclose()
    run(check)


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(65):  # just over MAX_HTTP_BYTES (4 MiB)
            yield b" " * 65536


def test_streaming_size_bound_ignores_content_length():
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,stream=Chunks(),
            headers={"content-type":"application/json", "content-length":"1"})))
        try:
            with pytest.raises(BridgeError, match="response_too_large"):
                await bridge.invoke("rw_get_investigation", {"investigation_id": ID})
        finally:
            await bridge.aclose()
    run(check)


def test_result_size_fails_instead_of_truncating():
    state = clarification_state()
    for item in [state, state["attempts"][0]]:
        item["clarification"]["question"] = "q"*70000
        item["grounding"]["result"]["question"] = "q"*70000
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=state)))
        try:
            with pytest.raises(BridgeError, match="response_too_large") as error:
                await bridge.invoke("rw_get_investigation", {"investigation_id": ID})
            assert "rw_get_verdict" in str(error.value) and "/?investigation=" in str(error.value)
        finally:
            await bridge.aclose()
    run(check)


@pytest.mark.parametrize("field", ["id", "snapshot_manifest_hash", "request_text", "plan_hash"])
def test_inconsistent_aliases_ids_and_bindings_are_rejected(field):
    state = clarification_state()
    state[field] = "wrong"
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=state)))
        try:
            with pytest.raises(BridgeError, match="invalid_backend_response"):
                await bridge.invoke("rw_get_investigation", {"investigation_id": ID})
        finally:
            await bridge.aclose()
    run(check)


@pytest.mark.parametrize("name,args", [("rw_start_investigation",{"request_text":"request"}),
    ("rw_answer_clarification",{"investigation_id": ID,"answer":"yes"}),
    ("rw_request_alternative",{"investigation_id": ID}),
    ("rw_get_investigation",{"investigation_id": ID})])
def test_timeouts_do_not_retry_and_release_gate(name,args):
    calls=[]
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("private credentials",request=request)
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(timeout))
        try:
            with pytest.raises(BridgeError) as error:
                await bridge.invoke(name,args)
            assert error.value.code == ("backend_unavailable" if name=="rw_get_investigation" else "outcome_unknown")
            assert len(calls)==1 and bridge._inflight==0 and not bridge._mutations
            assert "private" not in str(error.value)
        finally:
            await bridge.aclose()
    run(check)


def test_concurrent_mutation_busy_and_cancellation_release_gate():
    async def check():
        entered, release=anyio.Event(),anyio.Event()
        calls=[]
        async def handle(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200,json=clarification_state())
        bridge=BridgeClient(transport=httpx.MockTransport(handle))
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(bridge.invoke,"rw_answer_clarification",{"investigation_id":ID,"answer":"yes"})
                await entered.wait()
                with pytest.raises(BridgeError,match="busy"):
                    await bridge.invoke("rw_request_alternative",{"investigation_id":ID})
                assert len(calls)==1
                group.cancel_scope.cancel()
            assert bridge._inflight==0 and not bridge._mutations
        finally:
            await bridge.aclose()
    run(check)


def test_four_inflight_limit_and_mutation_rate_bound():
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=clarification_state())))
        try:
            with bridge._gate(None), bridge._gate(None), bridge._gate(None), bridge._gate(None):
                with pytest.raises(BridgeError,match="busy"):
                    await bridge.invoke("rw_get_investigation",{"investigation_id":ID})
            for _ in range(10):
                await bridge.invoke("rw_start_investigation",{"request_text":"request"})
            with pytest.raises(BridgeError,match="busy"):
                await bridge.invoke("rw_start_investigation",{"request_text":"request"})
        finally:
            await bridge.aclose()
    run(check)


@pytest.mark.parametrize("name,path,method,args", [
    ("rw_get_investigation",f"/api/investigations/{ID}","GET",{"investigation_id":ID}),
    ("rw_answer_clarification",f"/api/investigations/{ID}/answer","POST",{"investigation_id":ID,"answer":"  user's actual answer  ","replay_path":"answer.json"}),
    ("rw_request_alternative",f"/api/investigations/{ID}/alternative","POST",{"investigation_id":ID,"replay_path":"alt.json"}),
    ("rw_list_investigations","/api/investigations","GET",{"limit":1,"cursor":"YWJj"}),
    ("rw_list_transcripts","/api/transcripts","GET",{"limit":100}),
])
def test_only_allowlisted_routes_bodies_and_queries(name,path,method,args):
    calls=[]
    def handle(request):
        calls.append(request)
        if name in {"rw_list_investigations","rw_list_transcripts"}:
            return httpx.Response(200,json=[],headers={"X-Next-Cursor":"YWJj"})
        return httpx.Response(200,json=clarification_state())
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(handle))
        try:
            result=await bridge.invoke(name,args)
            request=calls[0]
            assert len(calls)==1 and request.method==method and request.url.path==path
            if method=="POST":
                assert json.loads(request.content)=={k:v for k,v in args.items() if k!="investigation_id"}
            elif "list" in name:
                assert request.url.params["limit"]==str(args["limit"])
                assert result.next_cursor=="YWJj"
        finally: await bridge.aclose()
    run(check)


def test_overall_mutation_deadline_is_uncertain_and_not_retried():
    calls=[]
    async def handle(request):
        calls.append(request)
        await anyio.Event().wait()
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(handle),mutation_deadline=.01)
        try:
            with pytest.raises(BridgeError,match="outcome_unknown") as error:
                await bridge.invoke("rw_start_investigation",{"request_text":"request"})
            assert "List investigations" in str(error.value)
            assert len(calls)==1 and bridge._inflight==0 and not bridge._mutations
        finally: await bridge.aclose()
    run(check)


@pytest.mark.parametrize("body", [b'[]',b'{"detail": {"unknown":"secret"}}'])
def test_error_response_shapes_are_validated_before_mapping(body):
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(404,content=body,headers={"Content-Type":"application/json"})))
        try:
            with pytest.raises(BridgeError,match="invalid_backend_response"):
                await bridge.invoke("rw_get_investigation",{"investigation_id":ID})
        finally: await bridge.aclose()
    run(check)


def test_nonfinite_number_in_unprojected_audit_is_rejected():
    raw=json.dumps(clarification_state()).replace('"private-audit"','1e999')
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=raw,headers={"Content-Type":"application/json"})))
        try:
            with pytest.raises(BridgeError,match="invalid_backend_response"):
                await bridge.invoke("rw_get_investigation",{"investigation_id":ID})
        finally: await bridge.aclose()
    run(check)
