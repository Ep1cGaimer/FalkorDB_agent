"""Seven explicitly registered stdio tools (six bridge tools + local read-only repo_investigate). Human confirmation/actions remain in the console."""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
import logging
import os

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import ToolAnnotations
import anyio
import httpx
from pydantic import ValidationError

from .mcp_client import MAX_RESULT_BYTES, BridgeClient, BridgeError
from .mcp_contracts import (INPUTS, InvestigationList, InvestigationResult, TranscriptList,
                            VerdictSummary)
from .repo.contracts import RepoInvestigationResult


_RAW_ARGUMENTS: ContextVar[dict | None] = ContextVar("rw_mcp_raw_arguments", default=None)


class StrictMCPServer(MCPServer):
    """Public SDK extension points; reject raw inputs before SDK convenience coercion."""

    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema = INPUTS[tool.name].model_json_schema()
        return tools

    async def call_tool(self, name, arguments, context=None):
        if name not in INPUTS:
            raise MCPError(code=-32602, message="Unknown tool")
        try:
            INPUTS[name].model_validate(arguments)
        except ValidationError:
            # Field names and rejected values can both be attacker-controlled. Fixed text only.
            raise ToolError("[invalid_input] Arguments do not match the published schema.") from None
        token = _RAW_ARGUMENTS.set(arguments.copy())
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            # 2.3.0 adds an execution label around handler ToolError. Keep our stable code first.
            if isinstance(exc.__cause__, ToolError):
                raise exc.__cause__ from None
            raise
        finally:
            _RAW_ARGUMENTS.reset(token)


def create_mcp_server(*, client: BridgeClient | None = None) -> MCPServer:
    bridge = client or BridgeClient(
        os.environ.get("RW_MCP_API_BASE_URL", "http://127.0.0.1:8000"),
        mutation_deadline=float(os.environ.get("RW_MCP_MUTATION_DEADLINE_SECONDS", "600")))

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield bridge
        finally:
            with anyio.CancelScope(shield=True):
                await bridge.aclose()

    server = StrictMCPServer("RollbackWitness", version="1", lifespan=lifespan,
        instructions=("Synthetic fixture; BYTE_SHAPE_ONLY; local simulation only. Tools orchestrate an existing "
            "single-worker local HTTP server. Give the human the review_url to confirm exact plan scope, then "
            "approve/simulate in the console. The bridge cannot confirm, verify, approve or simulate. "
            "Use only the user's clarification answer. One clarification round, at most two materialized plans. "
            "Live grounding uses the API's model and credentials; replay is saved evidence, never live. "
            "API restart loses investigations; MCP restart reconnects without resetting state. Stored reports "
            "do not assert current byte freshness. After evidence drift start a new investigation. "
            "Mutation deadlines do not cancel backend work. Never automatically retry mutations."))

    async def invoke(name, arguments):
        try:
            # Preserve validated raw strings: SDK convenience parsing turns cursor="null" into None.
            raw = _RAW_ARGUMENTS.get()
            return await bridge.invoke(name, raw if raw is not None else arguments)
        except BridgeError as exc:
            raise ToolError(str(exc)) from None

    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
    mutation = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

    @server.tool(name="rw_start_investigation", annotations=mutation)
    async def start(request_text: str, mode: str = "live", replay_path: str | None = None,
                    snapshot: str = "snap-001") -> InvestigationResult:
        """Start on the existing API (may initialize/reset fixture graph and incur model cost).

        Live uses the API's provider; replay requires a saved filename and is visibly labeled.
        Return review_url for human scope confirmation and separate human approval/simulation.
        One clarification round and at most two plans. API restart loses state. Never auto-retry.
        """
        return await invoke("rw_start_investigation", dict(request_text=request_text, mode=mode,
            replay_path=replay_path, snapshot=snapshot))

    @server.tool(name="rw_get_investigation", annotations=read)
    async def get(investigation_id: str) -> InvestigationResult:
        """Read all stored attempts/evidence, with replay/live labels and a human review URL.

        Does not verify or recheck freshness. API restart loses investigations; MCP restart does not.
        """
        return await invoke("rw_get_investigation", dict(investigation_id=investigation_id))

    @server.tool(name="rw_list_investigations", annotations=read)
    async def investigations(limit: int = 20, cursor: str | None = None) -> InvestigationList:
        """List process-local summaries; weakly consistent pagination. API restart loses this list."""
        return await invoke("rw_list_investigations", dict(limit=limit, cursor=cursor))

    @server.tool(name="rw_list_transcripts", annotations=read)
    async def transcripts(limit: int = 20, cursor: str | None = None) -> TranscriptList:
        """List saved replay metadata, not contents. Files over 1 MiB are skipped.

        Picker presence does not prove replay validity; replay never calls a live model.
        """
        return await invoke("rw_list_transcripts", dict(limit=limit, cursor=cursor))

    @server.tool(name="rw_answer_clarification", annotations=mutation)
    async def answer(investigation_id: str, answer: str, replay_path: str | None = None) -> InvestigationResult:
        """Supply the user's actual answer to the one open clarification; never invent a preference.

        Replay needs a saved answered-request filename; live uses the API's model. Human confirms
        resulting scope separately. API restart loses state. On timeout fetch state; never auto-retry.
        """
        return await invoke("rw_answer_clarification", dict(investigation_id=investigation_id,
            answer=answer, replay_path=replay_path))

    @server.tool(name="rw_request_alternative", annotations=mutation)
    async def alternative(investigation_id: str, replay_path: str | None = None) -> InvestigationResult:
        """Request an alternative after a human-confirmed BLOCKED/NEEDS_EVIDENCE report (two plans max).

        Replay requires a separate saved filename; live calls the API's provider. New scope needs human
        confirmation; approval never carries over. API restart loses state. Never automatically retry.
        """
        return await invoke("rw_request_alternative", dict(investigation_id=investigation_id, replay_path=replay_path))

    @server.tool(name="repo_investigate", annotations=read)
    async def repo_investigate_tool(repo: str, revision: str, question: str) -> RepoInvestigationResult:
        """Deterministic code/history retrieval over an indexed repository (rw.repo.mcp.repo_investigate).

        Returns source-backed findings with citations and explicit gaps; no compatibility disposition.
        """
        from rw.repo.mcp import repo_investigate
        data = await anyio.to_thread.run_sync(repo_investigate, repo, revision, question)
        return RepoInvestigationResult.model_validate(data)

    @server.tool(name="rw_get_verdict", annotations=read)
    async def verdict(investigation_id: str) -> VerdictSummary:
        """Read a short verdict per attempt: proposed fleet, disposition, check counts, first failures, gaps.

        Use this to explain a result; rw_get_investigation returns every receipt and can exceed the result
        budget. Full evidence stays at review_url. Does not verify or recheck freshness.
        """
        try:
            response = await bridge.http.get(f"/api/investigations/{investigation_id}/summary", timeout=15)
        except httpx.HTTPError:
            raise ToolError("[backend_unavailable] The RollbackWitness API could not be reached.") from None
        if response.status_code == 404:
            raise ToolError("[not_found] Investigation not found.")
        if response.status_code != 200 or len(response.content) > MAX_RESULT_BYTES:
            raise ToolError("[invalid_backend_response] The verdict summary could not be read.")
        data = response.json()
        return VerdictSummary.model_validate({**data, "review_url": f"{bridge.origin}/?investigation={investigation_id}"})

    return server


def main():
    logging.basicConfig(level=logging.INFO)  # logging's default stream is stderr, never stdout
    try:
        server = create_mcp_server()
    except (ValueError, TypeError):
        logging.error("Invalid MCP startup configuration; check loopback origin and mutation deadline.")
        raise SystemExit(2) from None
    server.run(transport="stdio")
