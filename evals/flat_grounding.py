"""Evaluation-only flat retrieval interface; the product owns validation and checking."""
from __future__ import annotations

import json
from pathlib import Path

from rw import graph as G, grounding as g
from rw.contracts import GroundingClarification, GroundingResult
from evals import llm_control as control

SYSTEM_PROMPT = g.SYSTEM_PROMPT + """
For this evaluation, all raw release files and the snapshot manifest are delivered in the first
message, followed by a trusted source catalog. Use the catalog's release_id and excerpt_id fields
where the instructions refer to tool results. No read tools are available. Finish with propose_fleet
or ask_clarification. The same trusted checker will check a validated proposal after this decision.
"""
TOOL_SPECS = [s for s in g.TOOL_SPECS if s['name'] in g.TERMINAL_TOOLS]


def source_catalog(fixture_root=control.FIXTURE_ROOT, snapshot=control.DEFAULT_SNAPSHOT):
    """Use the importer's pure extraction, without connecting to or traversing a graph."""
    releases, excerpts, _, ids, _, _, _ = G._collect_releases(Path(fixture_root))
    manifest = json.loads((Path(fixture_root) / 'snapshots' / snapshot.removeprefix('snapshot:') /
                           'manifest.json').read_text(encoding='utf-8'))
    rows = []
    for release in releases:
        rows.append({'release_id': release['id'], 'service': release['service'],
                     'version': release['version'], 'artifact_hash': release['artifact_hash'],
                     'declared_flags': json.loads(release['declared_flags_json']),
                     'excerpts': [{**ex, 'excerpt_id': ex['id'],
                                   'span': f"{ex['line_start']}-{ex['line_end']}"}
                                  for ex in excerpts if ex['release_id'] == release['id']]})
    return {'releases': rows, 'baseline': [{**dep, 'release_id': ids[(dep['service'], dep['version'])]}
                                          for dep in manifest['deployments']]}


def context(fixture_root=control.FIXTURE_ROOT, snapshot=control.DEFAULT_SNAPSHOT):
    return (control.flat_context(fixture_root, snapshot) + '\nTrusted citation addresses:\n' +
            json.dumps(source_catalog(fixture_root, snapshot), ensure_ascii=False))


class FlatGemini(g.GeminiProvider):
    def body(self, messages):
        body = super().body(messages)
        body['system_instruction'] = {'parts': [{'text': SYSTEM_PROMPT}]}
        body['tools'] = [{'functionDeclarations': [
            {**s, 'parameters': g._gemini_schema(s['parameters'])} for s in TOOL_SPECS]}]
        return body


class FlatGroq(g.GroqProvider):
    def body(self, messages):
        body = super().body(messages)
        body['messages'][0]['content'] = SYSTEM_PROMPT
        body['tools'] = [{'type': 'function', 'function': s} for s in TOOL_SPECS]
        return body


def ground(request_text, tools=None, alternative_context=None, *, transport,
           fixture_root=control.FIXTURE_ROOT, snapshot=control.DEFAULT_SNAPSHOT, artifact_dir):
    if alternative_context:
        raise ValueError('matched comparison permits one decision only')
    adapter = FlatGroq() if g._adapter_for(transport).name == 'groq' else FlatGemini()
    catalog = source_catalog(fixture_root, snapshot)
    excerpts, releases = {}, {}
    g._collect(catalog['releases'], excerpts, releases)
    messages = [{'role': 'user', 'text': f'Rollback request: {request_text}\n\n{context(fixture_root, snapshot)}'}]
    audit, events, state = [], [], {'citation_correction_used': False}
    result, errors = None, []
    for turn in range(g.MAX_TURNS):
        response = g.model_response(transport, adapter, messages, events, turn)
        if response is None:
            continue
        text, calls, native = adapter.parse(response)
        events.append({'type': 'model', 'turn': turn, 'response': response})
        if not calls:
            messages.append({'role': 'user', 'text': 'Respond only by calling a declared terminal tool.'})
            continue
        messages.append({'role': 'assistant', 'native': native, 'text': text})
        for call in calls:
            if call.name not in g.TERMINAL_TOOLS:
                payload, terminal = {'error': 'Only propose_fleet and ask_clarification are available'}, None
                events.append({'type': 'tool', 'name': str(call.name), 'error': payload['error']})
            elif (call.name == 'propose_fleet' and isinstance(call.args, dict) and
                  any(isinstance(ch, dict) and set(ch) - {'service', 'release_id', 'flags'}
                      for ch in call.args.get('changes', []) or [])):
                payload, terminal = {'error': 'unknown change fields; use service, release_id, flags'}, None
                events.append({'type': 'tool', 'name': call.name, 'args': call.args, 'error': payload['error']})
            else:
                payload, terminal = g._handle_call(call.name, call.args, None, excerpts, releases,
                                                    audit, events, state)
            if terminal is not None:
                result, errors = terminal
                break
            messages.append(adapter.tool_message(call, payload))
        if result is not None:
            break
    if result is None:
        result = GroundingClarification(question='Grounding aborted: turn exhaustion', unresolved=[])
        errors = ['GROUNDING_ABORTED: no terminal within eight model turns']
    gr = GroundingResult(request_text=request_text, result=result, model=transport.model_used,
                         live=True, tool_calls=audit, validation_errors=errors)
    path = g._save({'request_text': request_text, 'model': gr.model, 'provider': adapter.name,
                    'events': events, 'result': gr.model_dump(mode='json')}, Path(artifact_dir))
    return gr, path
