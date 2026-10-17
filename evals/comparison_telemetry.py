"""Evaluation-local accounting around the unchanged product transport."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from rw import grounding as g
from rw.contracts import h


def utc():
    return datetime.now(timezone.utc).isoformat()


class MeasuredTransport:
    def __init__(self, transport, model, clock=time.monotonic):
        self.transport, self.model_used, self.clock = transport, model, clock
        self.provider = transport.provider
        self.settings = {**getattr(transport, 'settings', {}), 'temperature': 0,
                         'max_turns': g.MAX_TURNS, 'timeout_s': 90,
                         'transport_attempt_cap': g.configured_retries()}
        self.calls = []
        self.model_mismatch = False

    def __call__(self, body):
        start = self.clock()
        trace = getattr(self.transport, 'trace', [])
        offset = len(trace)
        wire = {**body, **getattr(self.transport, 'settings', {})}
        if self.provider == 'groq':
            wire['model'] = g.split_model(self.model_used)[1]
        event = {'started_at': utc(), 'requested_model': self.model_used, 'request': wire,
                 'request_hash': h(wire), 'prompt_tools_hash': h(body)}
        self.calls.append(event)
        try:
            response = self.transport(body)
            returned = response.get('model') or response.get('modelVersion')
            event['returned_model'] = returned
            # No unverified aliases or fallback models are accepted.
            if returned != g.split_model(self.model_used)[1]:
                self.model_mismatch = True
                raise g.GroundingError('returned model does not match pinned model', code='model_mismatch')
            adapter = g._adapter_for(self)
            text, calls, _ = adapter.parse(response)
            event['response'] = {'text': text, 'calls': [{'name': c.name, 'args': c.args} for c in calls]}
            usage = response.get('usage', response.get('usageMetadata'))
            allowed = g._allowlisted_usage(usage)
            if self.provider == 'gemini' and isinstance(usage, dict):
                allowed = {k: v for k, v in usage.items() if k in
                           ('promptTokenCount', 'candidatesTokenCount', 'totalTokenCount', 'thoughtsTokenCount')
                           and isinstance(v, (int, float)) and not isinstance(v, bool)}
            event['response_hash'] = h(event['response'])
            event['usage'] = {k: v for k, v in allowed.items()
                              if math.isfinite(v)} or None
            event['outcome'] = 'response'
            return response
        except g.GroundingError as exc:
            event['error'] = g.provider_error_details(exc)
            event['outcome'] = 'rejected_generation' if isinstance(exc, g.ToolCallRejected) else 'provider_error'
            raise
        finally:
            event['elapsed_s'] = self.clock() - start
            event['finished_at'] = utc()
            event['transport_trace'] = trace[offset:]

    def summary(self):
        totals = {}
        for call in self.calls:
            for key, value in (call.get('usage') or {}).items():
                totals[key] = totals.get(key, 0) + value
        traces = [t for call in self.calls for t in call.get('transport_trace', [])]
        return {'model_calls': len(self.calls), 'http_attempts': sum('status' in t for t in traces),
                'reported_usage_totals': totals, 'usage_unknown_calls': sum(
                    c.get('usage') is None for c in self.calls),
                'model_elapsed_s': sum(c['elapsed_s'] for c in self.calls),
                'pacing_wait_s': sum(t.get('pacing_wait_s', 0) for t in traces),
                'retry_wait_accounting': 'included in model elapsed; individual backoff durations unavailable'}
