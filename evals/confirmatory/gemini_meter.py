"""Single-attempt Gemini transport and cumulative, provider-token metering.

This is development infrastructure. No byte/token estimates, implicit retries,
model fallback, oracle inputs or hidden response caches. API credentials travel
only in the request header and never enter the event journal.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import httpx

from .corpus_export import canonical


class ModelFailure(RuntimeError):
    def __init__(self, code, *, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ModelFailure("INVALID_TOKEN_METADATA")
    return value


@dataclasses.dataclass(frozen=True)
class ModelLimits:
    input_tokens: int = 24000
    output_tokens: int = 4000  # includes thinking and every planner/answer attempt
    context_tokens: int = 1048576
    per_call_output: int = 1000
    input_reserve: int = 64  # preflight/report discrepancy guard; not measured usage
    seconds: float = 120
    calls: int = 16

    def __post_init__(self):
        for name in ("input_tokens", "output_tokens", "context_tokens", "per_call_output", "calls"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("positive integer required: " + name)
        if type(self.input_reserve) is not int or self.input_reserve < 0:
            raise ValueError("input_reserve must be a nonnegative integer")
        if type(self.seconds) not in {int, float} or not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("seconds must be finite and positive")


class Journal:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory, self.sequence = directory, 0

    def append(self, kind, **fields):
        self.sequence += 1
        event = {"sequence": self.sequence, "kind": kind, **fields}
        with (self.directory / "events.jsonl").open("ab") as stream:
            stream.write(canonical(event))
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def write_new(self, name, value):
        with (self.directory / name).open("xb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())


class GeminiAPI:
    """Fixed official host, bounded response, TLS, header key, no redirects/retry."""
    def __init__(self, model: str, key: str, *, client=None, clock=time.monotonic):
        if not re.fullmatch(r"models/[A-Za-z0-9._-]+", model) or not key:
            raise ValueError("explicit model resource and credential required")
        self.model, self._key, self.clock = model, key, clock
        self.client = client or httpx.Client(follow_redirects=False)
        self.owns_client = client is None

    def close(self):
        if self.owns_client:
            self.client.close()

    def _request(self, operation, body, timeout):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ModelFailure("MODEL_DEADLINE_EXHAUSTED")
        url = "https://generativelanguage.googleapis.com/v1beta/" + self.model + ":" + operation
        deadline = self.clock() + timeout
        try:
            with self.client.stream("POST", url, json=body,
                                    headers={"x-goog-api-key": self._key, "content-type": "application/json"},
                                    timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
                                    follow_redirects=False) as response:
                if response.status_code != 200:
                    # Provider error bodies can echo request credentials; never journal them.
                    raise ModelFailure("PROVIDER_HTTP_ERROR", status=response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    if self.clock() >= deadline:
                        raise ModelFailure("MODEL_DEADLINE_EXHAUSTED")
                    if len(data) + len(chunk) > 4 * 1024 * 1024:
                        raise ModelFailure("PROVIDER_RESPONSE_TOO_LARGE")
                    data.extend(chunk)
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError()
                if "error" in value:
                    raise ModelFailure("PROVIDER_ERROR_ENVELOPE")
                if len(self._key) >= 8 and self._key.encode() in data:
                    raise ModelFailure("PROVIDER_CREDENTIAL_ECHO_REJECTED")
                return value
        except ModelFailure:
            raise
        except httpx.TimeoutException:
            raise ModelFailure("PROVIDER_TIMEOUT") from None
        except httpx.TransportError:
            raise ModelFailure("PROVIDER_TRANSPORT_ERROR") from None
        except (ValueError, UnicodeError):
            raise ModelFailure("PROVIDER_MALFORMED_JSON") from None

    def count(self, request, timeout):
        return self._request("countTokens", {"generateContentRequest": {"model": self.model, **request}}, timeout)

    def generate(self, request, timeout):
        return self._request("generateContent", request, timeout)


class MeteredModel:
    def __init__(self, api, journal: Journal, limits=ModelLimits(), *, generation=None,
                 expected_response_version=None, clock=time.monotonic, native_decision_tools=None,
                 native_tool_descriptions=None, reserve_final_answer=False):
        self.api, self.journal, self.limits, self.clock = api, journal, limits, clock
        if type(reserve_final_answer) is not bool:
            raise ValueError("reserve_final_answer must be boolean")
        self.reserve_final_answer = reserve_final_answer
        self.started = clock()
        self.generation = copy.deepcopy(generation or {})
        if set(self.generation) & {"candidateCount", "maxOutputTokens"}:
            raise ValueError("candidate/output bounds are owned by the shared meter")
        if native_decision_tools is not None and (
            not isinstance(native_decision_tools, (list, tuple)) or not 1 <= len(native_decision_tools) <= 100
            or any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", n)
                   for n in native_decision_tools) or len(set(native_decision_tools)) != len(native_decision_tools)
        ):
            raise ValueError("native_decision_tools requires a unique explicit tool allowlist")
        self.native_decision_tools = tuple(sorted(native_decision_tools)) if native_decision_tools is not None else None
        self.native_declarations = None
        if native_tool_descriptions is not None:
            if self.native_decision_tools is None or set(native_tool_descriptions) != set(self.native_decision_tools) or (
                "finish_investigation" in self.native_decision_tools
            ):
                raise ValueError("native tool descriptions must match the explicit allowlist")
            self.native_declarations = []
            for name in self.native_decision_tools:
                description = native_tool_descriptions[name]
                properties, required = {}, []
                for argument, detail in description.get("arguments", {}).items():
                    if not isinstance(detail, str) or not detail.startswith(("required", "optional")):
                        raise ValueError("native argument needs an explicit required/optional description")
                    kind = "integer" if argument in {"limit", "hops", "start", "end"} else (
                        "boolean" if argument == "case_sensitive" else "string")
                    properties[argument] = {"type": kind, "description": detail}
                    if detail.startswith("required"):
                        required.append(argument)
                self.native_declarations.append({"name": name, "description": description.get("description", name),
                    "parametersJsonSchema": {"type": "object", "properties": properties,
                        "required": required, "additionalProperties": False}})
            self.native_declarations.append({"name": "finish_investigation",
                "description": "Stop retrieval when supported evidence suffices or a specific gap prevents further progress; the application then generates the answer from locked evidence.",
                "parametersJsonSchema": {"type": "object", "properties": {}, "additionalProperties": False}})
        self._native_content = self._native_text = None
        self.expected_response_version = expected_response_version
        self.response_version = None
        self.input_charged = self.output_charged = self.actual_input = self.actual_output = self.calls = 0
        self.usage_unknown = False
        self.journal.write_new("model-setup.json", {
            "schema": "development-model-setup/v1", "model": self.api.model,
            "limits": dataclasses.asdict(limits), "generation": self.generation,
            "native_decision_tools": self.native_decision_tools,
            "native_declarations": self.native_declarations,
            "reserve_final_answer": self.reserve_final_answer,
            "final_reserve_policy": "Before a retrieval generation reserve another current-request input estimate plus1024 tokens, one generation call and one output cap; final actual count still enforced" if self.reserve_final_answer else None,
            "decision_protocol": "native-typed-tools/v3" if self.native_declarations else (
                "native-application-dispatch-continuation/v2" if self.native_decision_tools else "json-text/v1"),
            "expected_response_version": expected_response_version,
            "meter_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "unset_generation_parameters": "provider defaults; not a frozen decoding contract",
            "acceptance_validated": False})

    def remaining(self):
        value = self.limits.seconds - (self.clock() - self.started)
        if value <= 0:
            raise ModelFailure("MODEL_DEADLINE_EXHAUSTED")
        return value

    def summary(self):
        return {"model": self.api.model, "limits": dataclasses.asdict(self.limits),
                "calls": self.calls, "budget_input_tokens": self.input_charged,
                "budget_output_tokens": self.output_charged,
                "reported_input_tokens": self.actual_input, "reported_output_including_thinking": self.actual_output,
                "usage_unknown": self.usage_unknown, "response_model_version": self.response_version,
                "reported_token_counts_complete": not self.usage_unknown,
                "budget_charges_include_uncertain_reservations": self.usage_unknown,
                "elapsed_seconds": self.clock() - self.started,
                "cost_status": "UNMEASURED; token counts alone are not provider billing"}

    def model_message(self, text):
        """Preserve provider-native parts/signatures when continuing a tool turn."""
        if self._native_content is not None:
            if text != self._native_text:
                raise ValueError("native model message differs from validated decision")
            return copy.deepcopy(self._native_content)
        return {"role": "model", "parts": [{"text": text}]}

    def tool_message(self, name, response):
        if self._native_content is None:
            return {"role": "user", "parts": [{"text": canonical({"tool_result": response}).decode()}]}
        call = next(p["functionCall"] for p in self._native_content["parts"] if "functionCall" in p)
        selected = call["name"] if self.native_declarations else call["args"].get("name")
        if selected != name or (not self.native_declarations and call["args"].get("action") != "call"):
            raise ValueError("native function response does not match dispatched tool")
        reply = {"name": call["name"], "response": {"selected_tool": name, "tool_result": copy.deepcopy(response)}}
        if "id" in call:
            reply["id"] = call["id"]
        return {"role": "user", "parts": [{"functionResponse": reply}]}

    def ask(self, system: str, contents: list, *, phase: str, output_limit=None):
        self._native_content = self._native_text = None
        if self.usage_unknown:
            raise ModelFailure("USAGE_UNKNOWN_NO_FURTHER_GENERATION")
        if self.calls >= self.limits.calls:
            raise ModelFailure("MODEL_CALL_BUDGET_EXHAUSTED")
        cap = min(self.limits.per_call_output, self.limits.output_tokens - self.output_charged)
        if output_limit is not None:
            if type(output_limit) is not int or output_limit <= 0:
                raise ValueError("output_limit must be a positive integer")
            cap = min(cap, output_limit)
        if cap <= 0:
            raise ModelFailure("MODEL_OUTPUT_BUDGET_EXHAUSTED")
        request = {"systemInstruction": {"parts": [{"text": system}]}, "contents": copy.deepcopy(contents),
                   "generationConfig": {**self.generation, "candidateCount": 1, "maxOutputTokens": cap}}
        native = self.native_decision_tools is not None and phase == "retrieval"
        if native:
            request["systemInstruction"]["parts"][0]["text"] += (
                "\nTransport: call one declared retrieval function with its named arguments, or call finish_investigation with no arguments. Do not emit JSON text. "
                if self.native_declarations else
                "\nTransport: return the one decision as arguments of select_action instead of JSON text. "
                "For call use exactly action, name, arguments; for finish use only action. "
                "No function is executed by the provider; the application validates permissions before dispatch.")
            for name in ("responseMimeType", "responseSchema", "responseJsonSchema", "_responseJsonSchema", "responseFormat"):
                request["generationConfig"].pop(name, None)
            schema = {"type": "object", "properties": {"action": {"type": "string", "enum": ["call", "finish"]},
                "name": {"type": "string", "enum": list(self.native_decision_tools)},
                "arguments": {"type": "object", "additionalProperties": True}},
                "required": ["action"], "additionalProperties": False}
            request["tools"] = [{"functionDeclarations": [{"name": "select_action",
                "description": "Select a single retrieval action or finish; application validates permissions before dispatch.",
                "parametersJsonSchema": schema}]}]
            request["toolConfig"] = {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["select_action"]}}
            if self.native_declarations:
                request["tools"] = [{"functionDeclarations": copy.deepcopy(self.native_declarations)}]
                request["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] = [
                    declaration["name"] for declaration in self.native_declarations]
        request_hash = hashlib.sha256(canonical(request)).hexdigest()
        self.journal.append("token_count_started", phase=phase, request=request, request_sha256=request_hash)
        try:
            counted = self.api.count(copy.deepcopy(request), self.remaining())
            self.journal.append("token_count_completed", phase=phase, response=counted)
            count = nonnegative_int(counted.get("totalTokens"))
            if phase == "retrieval" and self.reserve_final_answer and (
                self.input_charged + 2 * count + 1024 + self.limits.input_reserve > self.limits.input_tokens
                or self.calls >= self.limits.calls - 1
                or self.output_charged + 2 * cap > self.limits.output_tokens
            ):
                raise ModelFailure("FINAL_ANSWER_RESERVE")
            if self.input_charged + count + self.limits.input_reserve > self.limits.input_tokens:
                raise ModelFailure("MODEL_INPUT_BUDGET_EXHAUSTED")
            if count + self.limits.input_reserve + cap > self.limits.context_tokens:
                raise ModelFailure("MODEL_CONTEXT_EXCEEDED")
            self.remaining()
        except Exception as exc:
            code = exc.code if isinstance(exc, ModelFailure) else "TOKEN_COUNT_FAILED"
            self.journal.append("token_count_failed", phase=phase, code=code,
                                http_status=getattr(exc, "status", None))
            raise ModelFailure(code) from None
        self.calls += 1
        self.journal.append("generation_started", phase=phase, request_sha256=request_hash,
                            call=self.calls, preflight_tokens=count, output_reservation=cap)
        # Reserve before making a potentially billed request. Reconcile only from
        # valid provider metadata; a transport failure cannot become free usage.
        self.input_charged += count + self.limits.input_reserve
        self.output_charged += cap
        try:
            response = self.api.generate(copy.deepcopy(request), self.remaining())
        except Exception as exc:
            self.usage_unknown = True
            code = exc.code if isinstance(exc, ModelFailure) else "GENERATION_FAILED"
            self.journal.append("generation_failed", phase=phase, code=code,
                                http_status=getattr(exc, "status", None), usage_unknown=True)
            raise ModelFailure(code) from None
        self.journal.append("generation_completed", phase=phase, response=response)
        try:
            usage = response["usageMetadata"]
            prompt = nonnegative_int(usage.get("promptTokenCount"))
            tool_prompt = nonnegative_int(usage.get("toolUsePromptTokenCount", 0))
            generated = nonnegative_int(usage.get("candidatesTokenCount", 0))
            thoughts = nonnegative_int(usage.get("thoughtsTokenCount", 0))
            total = nonnegative_int(usage.get("totalTokenCount"))
            actual_input, actual_output = prompt + tool_prompt, generated + thoughts
            if total != actual_input + actual_output:
                raise ModelFailure("INCONSISTENT_TOKEN_METADATA")
        except (KeyError, TypeError, AttributeError, ModelFailure):
            self.usage_unknown = True
            self.journal.append("usage_unavailable", phase=phase)
            raise ModelFailure("UNUSABLE_TOKEN_METADATA") from None
        self.actual_input += actual_input
        self.actual_output += actual_output
        candidates = response.get("candidates", [])
        parts = [part for candidate in candidates if isinstance(candidate, dict)
                 and isinstance(candidate.get("content"), dict)
                 and isinstance(candidate["content"].get("parts"), list)
                 for part in candidate["content"]["parts"] if isinstance(part, dict)] if isinstance(candidates, list) else []
        visible_output = any((isinstance(p.get("text"), str) and p["text"] and not p.get("thought"))
                             or p.get("functionCall") or p.get("inlineData") for p in parts)
        if generated == 0 and visible_output:
            # Some malformed provider responses emit text while reporting only
            # prompt usage. Preserve known subtotals, but never turn that text
            # into measured zero-cost output or release its reservation.
            self.usage_unknown = True
            self.journal.append("usage_unavailable", phase=phase,
                                reason="VISIBLE_OUTPUT_WITHOUT_CANDIDATE_TOKENS", reported_usage=usage)
            raise ModelFailure("UNUSABLE_TOKEN_METADATA")
        self.input_charged += max(count, actual_input) - count - self.limits.input_reserve
        self.output_charged += actual_output - cap
        self.journal.append("usage_reconciled", phase=phase, usage=usage, summary=self.summary(),
                            preflight_difference=actual_input - count)
        self.remaining()
        if actual_output > cap or self.output_charged > self.limits.output_tokens:
            raise ModelFailure("PROVIDER_EXCEEDED_OUTPUT_BUDGET")
        if self.input_charged > self.limits.input_tokens:
            raise ModelFailure("PROVIDER_EXCEEDED_INPUT_BUDGET")
        version = response.get("modelVersion")
        if not isinstance(version, str) or not version:
            raise ModelFailure("MODEL_VERSION_MISSING")
        if (self.expected_response_version and version != self.expected_response_version) or (
            self.response_version and version != self.response_version
        ):
            raise ModelFailure("MODEL_VERSION_CHANGED")
        self.response_version = version
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
            raise ModelFailure("MODEL_RESPONSE_INCOMPLETE")
        parts = candidates[0].get("content", {}).get("parts", [])
        if native:
            calls = []
            for part in parts:
                if not isinstance(part, dict):
                    raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
                if "functionCall" in part:
                    if set(part) - {"functionCall", "thoughtSignature"}:
                        raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
                    calls.append(part["functionCall"])
                elif set(part) - {"text", "thought", "thoughtSignature"} or (part.get("text") and not part.get("thought")):
                    raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
            allowed = (*self.native_decision_tools, "finish_investigation") if self.native_declarations else ("select_action",)
            if len(calls) != 1 or not isinstance(calls[0], dict) or calls[0].get("name") not in allowed or (
                not isinstance(calls[0].get("args"), dict)
            ):
                raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
            try:
                value = calls[0]["args"]
                if self.native_declarations:
                    if calls[0]["name"] == "finish_investigation":
                        if value:
                            raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
                        value = {"action": "finish"}
                    else:
                        value = {"action": "call", "name": calls[0]["name"], "arguments": value}
                text = canonical(value).decode().strip()
            except (ValueError, TypeError):
                raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR") from None
            content = candidates[0].get("content", {})
            if content.get("role") not in (None, "model"):
                raise ModelFailure("NATIVE_DECISION_SHAPE_ERROR")
            self._native_content = {"role": "model", "parts": copy.deepcopy(parts)}
            self._native_text = text
            return text
        text = "".join(p["text"] for p in parts if isinstance(p.get("text"), str) and not p.get("thought"))
        if not text:
            raise ModelFailure("MODEL_RESPONSE_EMPTY")
        return text
