"""Official SDK host against the actual launcher; both protocol eras and raw stdout framing."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread

import pytest
pytest.importorskip("mcp", reason="optional MCP extra is not installed")

import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import PROTOCOL_VERSION_META_KEY, CLIENT_INFO_META_KEY, CLIENT_CAPABILITIES_META_KEY

from rw.mcp_contracts import INPUTS
from test_mcp_client import ID, clarification_state

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/serve_mcp.py"


@contextmanager
def backend():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            calls.append(("GET",self.path))
            data=[] if self.path.startswith("/api/transcripts") or "?" in self.path else clarification_state()
            raw=json.dumps(data).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(raw)
    httpd=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=httpd.serve_forever,daemon=True);thread.start()
    try: yield f"http://127.0.0.1:{httpd.server_port}",calls
    finally:
        httpd.shutdown();httpd.server_close();thread.join(timeout=5)


@pytest.mark.parametrize("era", ["modern","legacy"])
def test_official_sdk_discovery_call_schema_errors_and_shutdown(tmp_path,era):
    with backend() as (origin,calls):
        async def check():
            with (tmp_path/"stderr.log").open("w+") as stderr:
                parameters=StdioServerParameters(command=sys.executable,args=[str(LAUNCHER)],cwd=tmp_path,
                    env={"RW_MCP_API_BASE_URL":origin})
                async with stdio_client(parameters,errlog=stderr) as (read,write):
                    async with ClientSession(read,write,read_timeout_seconds=10) as session:
                        if era=="modern":
                            await session.discover()
                            assert session.protocol_version=="2026-07-28"
                        else:
                            initialized=await session.initialize()
                            assert initialized.protocol_version=="2025-11-25"
                        tools=(await session.list_tools()).tools
                        assert [tool.name for tool in tools]==list(INPUTS)
                        assert calls==[]  # discovery does not touch HTTP/graph
                        result=await session.call_tool("rw_get_investigation",{"investigation_id":ID})
                        assert not result.is_error
                        assert json.loads(result.content[0].text)==result.structured_content
                        Draft202012Validator(tools[1].output_schema).validate(result.structured_content)
                        invalid=await session.call_tool("rw_list_investigations",{"limit":"20","private-value":"sensitive"})
                        assert invalid.is_error and invalid.structured_content is None
                        assert "invalid_input" in invalid.content[0].text and "sensitive" not in invalid.content[0].text
                        with pytest.raises(MCPError) as error:
                            await session.call_tool("rw_approve",{"investigation_id":ID})
                        assert error.value.code==-32602
                        assert len(calls)==1
                stderr.seek(0)
                assert "sensitive" not in stderr.read()
        anyio.run(check)


def test_every_stdout_line_is_protocol_json_and_eof_exits_cleanly(tmp_path):
    message={"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{PROTOCOL_VERSION_META_KEY:"2026-07-28", CLIENT_INFO_META_KEY:{"name":"raw-test","version":"1"}, CLIENT_CAPABILITIES_META_KEY:{}}}}
    proc=subprocess.run([sys.executable,str(LAUNCHER)],input=json.dumps(message)+"\n",text=True,
        capture_output=True,cwd=tmp_path,timeout=15)
    assert proc.returncode==0,proc.stderr
    lines=proc.stdout.splitlines()
    assert lines
    messages=[json.loads(line) for line in lines]
    assert all(msg["jsonrpc"]=="2.0" for msg in messages)
    assert any(msg.get("id")==1 and "result" in msg for msg in messages)
    assert "Traceback" not in proc.stderr


def test_missing_backend_is_tool_error_without_autostart(tmp_path):
    # Reserve a port while choosing it; release immediately before a connect-refused request.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    async def check():
        with (tmp_path/"stderr.log").open("w") as stderr:
            parameters=StdioServerParameters(command=sys.executable,args=[str(LAUNCHER)],cwd=tmp_path,
                env={"RW_MCP_API_BASE_URL":f"http://127.0.0.1:{port}"})
            async with stdio_client(parameters,errlog=stderr) as (read,write):
                async with ClientSession(read,write,read_timeout_seconds=10) as session:
                    await session.discover()
                    result=await session.call_tool("rw_list_investigations",{})
                    assert result.is_error and result.structured_content is None
                    assert result.content[0].text.startswith("[backend_unavailable]")
    anyio.run(check)


def test_missing_optional_sdk_has_stderr_setup_guidance(tmp_path):
    # -S omits site-packages, including MCP, without changing the host environment.
    proc=subprocess.run([sys.executable,"-S",str(LAUNCHER)],capture_output=True,text=True,cwd=tmp_path,timeout=10)
    assert proc.returncode!=0 and not proc.stdout
    assert "setup.sh --mcp" in proc.stderr and "-Mcp" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_invalid_startup_configuration_never_prints_secret_value(tmp_path):
    env={**os.environ,"RW_MCP_API_BASE_URL":"http://private-token@remote.invalid/path"}
    proc=subprocess.run([sys.executable,str(LAUNCHER)],capture_output=True,text=True,cwd=tmp_path,env=env,timeout=10)
    assert proc.returncode==2 and not proc.stdout
    assert "Invalid MCP startup configuration" in proc.stderr and "private-token" not in proc.stderr
