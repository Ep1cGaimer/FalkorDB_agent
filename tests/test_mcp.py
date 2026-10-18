"""Published SDK schemas, strict public adapter, output parity and privilege surface."""
import json

import pytest
pytest.importorskip("mcp", reason="optional MCP extra is not installed")

import anyio
import httpx
from jsonschema import Draft202012Validator
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from rw.mcp_client import BridgeClient
from rw.mcp_contracts import INPUTS
from rw.mcp_server import create_mcp_server
from test_mcp_client import ID, clarification_state


def test_tools_schemas_output_refs_annotations_and_parity():
    async def check():
        bridge = BridgeClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=clarification_state())))
        server = create_mcp_server(client=bridge)
        try:
            tools = await server.list_tools()
            assert [t.name for t in tools] == list(INPUTS)
            for tool in tools:
                Draft202012Validator.check_schema(tool.input_schema)
                Draft202012Validator.check_schema(tool.output_schema)
                assert tool.input_schema["additionalProperties"] is False
                assert tool.annotations.read_only_hint == (tool.name in {
                    "rw_get_investigation","rw_list_investigations","rw_list_transcripts",
                    "repo_investigate"})  # repository retrieval (S5) is read-only
                assert tool.annotations.idempotent_hint == tool.annotations.read_only_hint
            result = await server.call_tool("rw_get_investigation",{"investigation_id":ID})
            assert not result.is_error
            assert json.loads(result.content[0].text) == result.structured_content
            tool = next(t for t in tools if t.name == "rw_get_investigation")
            Draft202012Validator(tool.output_schema).validate(result.structured_content)
            serialized=result.model_dump_json(by_alias=True)
            assert "structuredContent" in serialized
            assert len(serialized.encode()) < 2 * 128 * 1024 + 4096
            assert "reader_codec_path" not in json.dumps(tool.output_schema)
            assert "tool_calls" not in json.dumps(tool.output_schema)
        finally:
            await bridge.aclose()
    anyio.run(check)


@pytest.mark.parametrize("name,args", [
    ("rw_list_investigations",{"limit":"20"}),
    ("rw_list_investigations",{"limit":True}),
    ("rw_start_investigation",{"request_text":"ok","approved_by":"model"}),
    ("rw_answer_clarification",{"investigation_id":ID,"answer":" "}),
    ("rw_request_alternative",{"investigation_id":ID,"report":{}}),
])
def test_public_call_validates_before_sdk_coercion(name,args):
    async def check():
        calls=[]
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r: calls.append(r)))
        server=create_mcp_server(client=bridge)
        try:
            with pytest.raises(ToolError, match="invalid_input"):
                await server.call_tool(name,args)
            assert not calls
        finally:
            await bridge.aclose()
    anyio.run(check)


@pytest.mark.parametrize("name", ["rw_approve", "rw_confirm_scope", "rw_simulate", "rw_verify", "call_endpoint", "shell", "rw_reset"])
def test_unknown_tools_are_protocol_errors(name):
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r: pytest.fail("unexpected HTTP")))
        server=create_mcp_server(client=bridge)
        try:
            with pytest.raises(MCPError) as error:
                await server.call_tool(name,{"investigation_id":ID})
            assert error.value.code == -32602
        finally:
            await bridge.aclose()
    anyio.run(check)


def test_near_limit_output_counts_sdk_text_copy_and_wire_escaping():
    # Audit-free state just below the data cap, with chars requiring wire escaping.
    state=clarification_state('r"\\π'*3500)
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=state)))
        server=create_mcp_server(client=bridge)
        try:
            result=await server.call_tool("rw_get_investigation",{"investigation_id":ID})
            data=json.dumps(result.structured_content,ensure_ascii=False,separators=(",",":")).encode()
            wire=result.model_dump_json(by_alias=True).encode()
            assert 60000 < len(data) <= 128*1024
            assert len(wire)>2*len(data)  # text duplication plus JSON escaping
            assert len(wire)<512*1024
            assert json.loads(result.content[0].text)==result.structured_content
        finally: await bridge.aclose()
    anyio.run(check)


def test_sdk_does_not_reinterpret_opaque_null_string_cursor():
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(422,json={"detail":"invalid pagination cursor"})
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(handle))
        server=create_mcp_server(client=bridge)
        try:
            with pytest.raises(ToolError) as error:
                await server.call_tool("rw_list_investigations",{"cursor":"null"})
            assert str(error.value).startswith("[invalid_input]")
            assert calls[0].url.params["cursor"]=="null"
        finally: await bridge.aclose()
    anyio.run(check)


def test_lifespan_closes_http_client_on_cancellation():
    async def check():
        bridge=BridgeClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=[])))
        server=create_mcp_server(client=bridge)
        with anyio.CancelScope() as scope:
            async with server.settings.lifespan(server):
                scope.cancel()
                await anyio.sleep(0)
        assert bridge.http.is_closed
    anyio.run(check)
