"""Bounded allowlisted HTTP adapter. No application, graph or provider initialization here."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from pydantic import TypeAdapter, ValidationError

from .api_contracts import (DetailError, InvestigationSummary, InvestigationView,
                            RefusalError, TranscriptSummary, ValidationErrorView)
from .contracts import (SCOPE_ID, CandidatePlan, FleetEntry, GraphEvidence, VerificationResult, h)
from .grounding import LIVE_PROVIDER_PREFIXES
from .mcp_contracts import (INPUTS, InvestigationID, InvestigationList, InvestigationResult,
                            TranscriptList, picker_filename)
from .verification import dispose
from .pipeline import ALL_SNAPSHOTS

log = logging.getLogger("rw.mcp")
MAX_HTTP_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 128 * 1024
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
RELEASE = re.compile(r"^release:[^:\s/\\]+:[0-9a-f]{16}$")


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


def base_url(value: str) -> str:
    if not re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?/?", value):
        raise ValueError("RW_MCP_API_BASE_URL must be a literal loopback HTTP origin")
    parts = urlsplit(value)
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("invalid API port")
    return value.rstrip("/")


def require(condition):
    if not condition:
        raise ValueError("inconsistent backend evidence")


def _canonical_plan(view):
    data = {name: getattr(view, name) for name in CandidatePlan.model_fields}
    data["fleet"] = [FleetEntry(**{name: getattr(row, name) for name in FleetEntry.model_fields})
                     for row in view.fleet]
    return CandidatePlan.model_validate(data)


def _hash(value):
    require(isinstance(value, str) and HASH.fullmatch(value) is not None)


def _time(value):
    require(datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None)


def validate_state(state: InvestigationView, expected_id: str | None = None):
    """Check transport integrity using canonical domain fields and the trusted disposition rules.

    This does not execute probes or claim that stored evidence is still fresh.
    """
    TypeAdapter(InvestigationID).validate_python(state.id)
    require(expected_id is None or state.id == expected_id)
    require(state.attempts[0].grounding.request_text == state.original_request_text)
    require(sum(a.plan is not None for a in state.attempts) <= 2)
    require(state.snapshot_id in {f"snapshot:{name}" for name in ALL_SNAPSHOTS})
    _hash(state.snapshot_manifest_hash)
    for attempt in state.attempts:
        if state.mode == "replay":
            require(not attempt.grounding.live and attempt.grounding.model.startswith("replay:"))
        require(attempt.is_live_provider == bool(attempt.grounding.live and attempt.grounding.model.startswith(LIVE_PROVIDER_PREFIXES)))
        require(attempt.citations == attempt.grounding.result.citations)
        result = attempt.grounding.result
        require(attempt.clarification == result if result.kind == "CLARIFICATION" else attempt.clarification is None)
        require(attempt.grounding.request_text in {state.original_request_text, state.request_text})
        require(set(attempt.grounding.validation_errors) <= set(attempt.validation_errors))
        require(attempt.plan is None or result.kind == "PROPOSAL")
        if attempt.plan is None:
            require(attempt.plan_hash is None and attempt.report is None
                    and attempt.approval is None and attempt.simulation is None)
            require(attempt.clarification is not None or bool(attempt.validation_errors))
            continue
        plan = _canonical_plan(attempt.plan)
        _hash(attempt.plan_hash)
        require(plan.plan_hash() == attempt.plan_hash)
        require(plan.snapshot_id == state.snapshot_id and plan.snapshot_manifest_hash == state.snapshot_manifest_hash)
        require(plan.request_text_hash == h(attempt.grounding.request_text))
        require(len({row.service for row in plan.fleet}) == len(plan.fleet))
        require(plan.scope_id == SCOPE_ID)
        require(plan.source_hashes == sorted({c.content_hash for c in attempt.citations}))
        for value in [plan.snapshot_manifest_hash, plan.request_text_hash, *plan.source_hashes]:
            _hash(value)
        require(all(RELEASE.fullmatch(row.release_id) for row in plan.fleet))
        require(attempt.plan.citations == attempt.citations and not attempt.validation_errors)
        report = attempt.report
        if report is None:
            require(attempt.approval is None and attempt.simulation is None)
            continue
        verification = VerificationResult.model_validate(report.verification.model_dump())
        _hash(report.verification_hash)
        require(_canonical_plan(report.plan) == plan)
        require(report.plan_id == plan.plan_id() and report.plan_hash == attempt.plan_hash)
        require(report.scope_confirmation.plan_hash == attempt.plan_hash)
        _time(report.scope_confirmation.confirmed_at)
        require(verification.plan_hash == attempt.plan_hash and verification.snapshot_id == plan.snapshot_id
                and verification.snapshot_manifest_hash == plan.snapshot_manifest_hash)
        require(verification.semantic_scope == "BYTE_SHAPE_ONLY")
        require(verification.verification_hash() == report.verification_hash)
        _time(verification.computed_at)
        obligations = {ob.obligation_hash: ob for ob in verification.obligations}
        require(len(obligations) == len(verification.obligations))
        require(len({receipt.receipt_hash() for receipt in verification.receipts}) == len(verification.receipts))
        fleet = {row.service: row.release_id for row in plan.fleet}
        for ob in verification.obligations:
            require(fleet.get(ob.tuple.service) == ob.tuple.release_id)
            require(ob.obligation_hash == ob.tuple.obligation_hash())
            require(ob.tuple.plan_hash == attempt.plan_hash and ob.tuple.snapshot_id == plan.snapshot_id
                    and ob.tuple.snapshot_manifest_hash == plan.snapshot_manifest_hash
                    and ob.tuple.scope_id == plan.scope_id and ob.tuple.semantic_scope == "BYTE_SHAPE_ONLY")
        for receipt in verification.receipts:
            require(receipt.obligation_hash in obligations)
            require(receipt.duration_ms >= 0)
            _time(receipt.executed_at)
        # Hash-shaped fields inside canonical verification, including receipt tuples and blockers.
        def hashes(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.endswith("_hash"):
                        _hash(child)
                    hashes(child)
            elif isinstance(value, list):
                for child in value:
                    hashes(child)
        hashes(verification.model_dump(mode="json"))
        for value in verification.blocking_receipts:
            _hash(value)
        evidence = GraphEvidence(plan_hash=plan.plan_hash(), obligations=verification.obligations,
            gaps=verification.gaps, queries=[], snapshot_id=plan.snapshot_id,
            snapshot_manifest_hash=plan.snapshot_manifest_hash, dependencies=verification.dependencies)
        checked = dispose(evidence, verification.receipts)
        require(checked.disposition == verification.disposition
                and checked.blocking_receipts == verification.blocking_receipts)
        if attempt.approval:
            approval = attempt.approval
            require(verification.disposition.value == "BOUNDED_PASS")
            require(approval.plan_hash == attempt.plan_hash and approval.verification_hash == report.verification_hash
                    and approval.snapshot_manifest_hash == plan.snapshot_manifest_hash)
            _time(approval.approved_at)
        if attempt.simulation:
            receipt = attempt.simulation
            require(attempt.approval is not None and receipt.plan_hash == attempt.plan_hash
                    and receipt.idempotency_key == attempt.approval.idempotency_key())
            for value in [receipt.idempotency_key, receipt.previous_fleet_hash, receipt.new_fleet_hash]:
                _hash(value)
            _time(receipt.applied_at)
    require(state.grounding.request_text == state.request_text)


def project_state(state: InvestigationView, origin: str) -> InvestigationResult:
    data = state.model_dump(mode="json", exclude_unset=True)
    # Only omit explicitly internal fields. Evidence, witness paths and gaps remain complete.
    def sanitize(attempt):
        attempt["grounding"].pop("tool_calls")
        if attempt["transcript"]:
            selector = re.split(r"[/\\]", attempt["transcript"])[-1]
            attempt["transcript"] = picker_filename(selector)
        if attempt["report"]:
            for startup in attempt["report"]["startup_checks"].values():
                startup.pop("codec_path")
            for ob in attempt["report"]["verification"]["obligations"]:
                ob.pop("reader_codec_path")
    for attempt in data["attempts"]:
        sanitize(attempt)
    sanitize(data)
    if state.validation_errors:
        action = "resolve_validation_errors"
    elif state.clarification is not None:
        action = "none" if state.answered else "answer_clarification"
    elif state.plan is not None and state.report is None:
        action = "human_confirm_scope"
    elif state.report and state.report.verification.disposition.value in {"BLOCKED", "NEEDS_EVIDENCE"}:
        action = "request_alternative" if sum(a.plan is not None for a in state.attempts) < 2 else "none"
    elif state.report and state.report.verification.disposition.value == "BOUNDED_PASS":
        action = "none" if state.simulation else "human_review"
    else:
        action = "none"
    return InvestigationResult(investigation_id=state.id, snapshot_id=state.snapshot_id,
        snapshot_manifest_hash=state.snapshot_manifest_hash, plan_hash=state.plan_hash,
        verification_hash=state.report.verification_hash if state.report else None,
        mode=state.mode, model=state.grounding.model, live=state.grounding.live, data=data,
        next_action=action, review_url=f"{origin}/?investigation={state.id}")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite JSON number")
    return parsed


def _nonfinite(_):
    raise ValueError("nonfinite JSON number")


class BridgeClient:
    def __init__(self, origin="http://127.0.0.1:8000", *, transport=None, mutation_deadline=600.0):
        self.origin = base_url(origin)
        if not math.isfinite(mutation_deadline) or not 0 < mutation_deadline <= 3600:
            raise ValueError("mutation deadline must be greater than zero and at most 3600 seconds")
        self.mutation_deadline = mutation_deadline
        self.http = httpx.AsyncClient(base_url=self.origin, transport=transport, trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(15, connect=3),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        self._inflight = 0
        self._mutations: set[str] = set()
        self._recent: deque[float] = deque()

    async def aclose(self):
        await self.http.aclose()

    @contextmanager
    def _gate(self, mutation_key):
        now = monotonic()
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if self._inflight >= 4 or (mutation_key is not None and
                (mutation_key in self._mutations or len(self._recent) >= 10)):
            raise BridgeError("busy", "No mutation was submitted; an explicit later retry is safe.")
        self._inflight += 1
        if mutation_key is not None:
            self._mutations.add(mutation_key)
            self._recent.append(now)
        try:
            yield
        finally:
            self._inflight -= 1
            if mutation_key is not None:
                self._mutations.remove(mutation_key)

    async def invoke(self, name, arguments):
        if name not in INPUTS:
            raise BridgeError("invalid_input", "Unknown operation.")
        try:
            args = INPUTS[name].model_validate(arguments).model_dump()
        except ValidationError:
            raise BridgeError("invalid_input", "Arguments do not match the published schema.") from None
        mutation = name in {"rw_start_investigation", "rw_answer_clarification", "rw_request_alternative"}
        identifier = args.pop("investigation_id", None)
        method, path, body, params = "GET", "/api/investigations", None, None
        if name == "rw_start_investigation":
            method, body = "POST", args
        elif name in {"rw_list_investigations", "rw_list_transcripts"}:
            path = "/api/transcripts" if name == "rw_list_transcripts" else path
            params = {k: v for k, v in args.items() if v is not None}
        else:
            path += "/" + identifier
            if mutation:
                path += "/answer" if name == "rw_answer_clarification" else "/alternative"
                method, body = "POST", args
        correlation, started, status = uuid4().hex, monotonic(), "unknown"
        try:
            with self._gate((identifier or "start") if mutation else None):
                with anyio.fail_after(self.mutation_deadline if mutation else 15):
                    raw, cursor = await self._request(method, path, body, params, mutation)
            if name in {"rw_list_investigations", "rw_list_transcripts"}:
                model = TranscriptSummary if name == "rw_list_transcripts" else InvestigationSummary
                items = TypeAdapter(list[model]).validate_json(raw, strict=True)
                require(len(items) <= args["limit"])
                if model is InvestigationSummary:
                    for item in items:
                        TypeAdapter(InvestigationID).validate_python(item.id)
                else:
                    for item in items:
                        picker_filename(item.replay_path)
                        _time(item.mtime)
                result = (TranscriptList if model is TranscriptSummary else InvestigationList)(items=items, next_cursor=cursor)
            else:
                require(cursor is None)
                state = InvestigationView.model_validate_json(raw, strict=True)
                validate_state(state, identifier)
                if name == "rw_start_investigation":
                    require(state.original_request_text == args["request_text"] and state.request_text == args["request_text"])
                    require(state.mode == args["mode"] and state.snapshot_id == "snapshot:" + args["snapshot"])
                result = project_state(state, self.origin)
            encoded = result.model_dump_json(exclude_unset=False).encode()
            if len(encoded) > MAX_RESULT_BYTES:
                raise BridgeError("response_too_large", "Complete evidence exceeds the MCP result budget; no partial result returned.")
            # Validate the exact outgoing representation, including nested projections.
            result = type(result).model_validate_json(encoded, strict=True)
            status = "ok"
            return result
        except BridgeError as exc:
            status = exc.code
            raise
        except (TimeoutError, httpx.TimeoutException, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError):
            status = "outcome_unknown" if mutation else "backend_unavailable"
            message = ("The API may still finish. Do not resubmit automatically. "
                       + ("List investigations and ask the user to identify the run if ambiguous." if identifier is None
                          else "Fetch the known investigation to reconcile before another mutation.")) if mutation else "The API did not complete the read."
            raise BridgeError(status, message) from None
        except (httpx.ConnectError, httpx.NetworkError):
            status = "backend_unavailable"
            raise BridgeError(status, "Start the existing HTTP server separately; the bridge never starts an API.") from None
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError, httpx.DecodingError):
            status = "invalid_backend_response"
            raise BridgeError(status, "Backend evidence failed response validation; no verified result returned.") from None
        finally:
            log.info("tool=%s correlation=%s investigation=%s duration_ms=%d status=%s", name,
                     correlation, identifier or "-", int((monotonic() - started) * 1000), status)

    async def _request(self, method, path, body, params, mutation):
        deadline = self.mutation_deadline if mutation else 15
        async with self.http.stream(method, path, json=body, params=params,
                timeout=httpx.Timeout(deadline, connect=3)) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > MAX_HTTP_BYTES:
                    raise BridgeError("response_too_large", "Backend response exceeds 1 MiB; no partial evidence returned.")
                raw.extend(chunk)
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise BridgeError("invalid_backend_response", "Backend did not return JSON.")
            data = json.loads(raw, parse_constant=_nonfinite, parse_float=_finite_float, object_pairs_hook=_no_duplicates)
            status = response.status_code
            if status in {404, 409, 422, 502}:
                error_model = ({404: DetailError, 409: RefusalError | DetailError,
                                422: ValidationErrorView | DetailError, 502: DetailError})[status]
                TypeAdapter(error_model).validate_json(raw, strict=True)
            if status == 404:
                raise BridgeError("not_found", "Investigation not found; API restart loses in-memory investigations.")
            if status == 422:
                raise BridgeError("invalid_input", "The API rejected the input or replay selector.")
            if status == 409:
                # No arbitrary refusal/provider text (which may contain paths or request data).
                reason = data.get("reason", data.get("detail")) if isinstance(data, dict) else None
                safe = {
                    "plan limit reached": "The two-plan limit has been reached.",
                    "alternative requires a BLOCKED or NEEDS_EVIDENCE verification": "A human must confirm the prior plan, yielding BLOCKED or NEEDS_EVIDENCE, before an alternative.",
                    "the agent has no open question": "There is no open clarification.",
                    "the one clarification round was already used": "The one clarification round was already used.",
                    "alternative must be a different plan": "The alternative duplicated the existing plan.",
                    "a separate replay_path is required for the alternative": "Select a separate saved replay for the alternative.",
                    "grounding request does not match this investigation": "Replay or grounding request does not match the bound request.",
                }
                raise BridgeError("state_conflict", safe.get(reason if isinstance(reason, str) else None, "The operation conflicts with current evidence or state. Retrieve the investigation and review it with the human."))
            if status == 502:
                detail = data.get("detail", {}) if isinstance(data, dict) else {}
                code = detail.get("code") if isinstance(detail, dict) else None
                if code not in {"provider_quota", "provider_unavailable", "provider_error"}:
                    code = "provider_error"
                raise BridgeError(code, "Live grounding could not complete. Use replay or try later with the user.")
            if status != 200:
                raise BridgeError("invalid_backend_response", "Unexpected backend HTTP status.")
            return bytes(raw), response.headers.get("X-Next-Cursor")
