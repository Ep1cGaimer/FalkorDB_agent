"""Scripted provider decisions plus real importer/checker parity."""
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from rw import graph as G, grounding as g
from rw.contracts import ScopeConfirmation
from rw.pipeline import Session, run_investigation
from evals import flat_grounding as flat, llm_control as legacy


class Transport:
    def __init__(self, responses, provider='gemini'):
        self.responses = iter(responses)
        self.provider = provider
        self.model_used = provider + ':scripted'
        self.bodies = []
    def __call__(self, body):
        self.bodies.append(body)
        return next(self.responses)


def call(name, args, provider='gemini'):
    if provider == 'gemini':
        return {'candidates': [{'content': {'parts': [{'functionCall': {'name': name, 'args': args}}]}}]}
    return {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call_1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}


def proposal(version='1.4'):
    release = next(r for r in flat.source_catalog()['releases'] if r['service'] == 'cart' and r['version'] == version)
    ex = next(e for e in release['excerpts'] if e['kind'] == 'changelog')
    return {'changes': [{'service': 'cart', 'release_id': release['release_id'],
                        'flags': [] if version == '1.4' else [{'name': 'basket_v2', 'enabled': False}]}],
            'citations': [{'excerpt_id': ex['excerpt_id'], 'quote': ex['text']}], 'rationale': 'scripted'}


def test_source_catalog_matches_importer_and_full_raw_files():
    releases, excerpts, *_ = G._collect_releases(legacy.FIXTURE_ROOT)
    catalog = flat.source_catalog()
    assert {r['release_id'] for r in catalog['releases']} == {r['id'] for r in releases}
    delivered = {e['excerpt_id']: e for r in catalog['releases'] for e in r['excerpts']}
    assert set(delivered) == {e['id'] for e in excerpts}
    for ex in excerpts:
        release = next(r for r in catalog['releases'] if r['release_id'] == ex['release_id'])
        raw = legacy.FIXTURE_ROOT / 'releases' / f"{release['service']}-{release['version']}" / ex['path']
        assert ex['text'] in raw.read_text()
        assert all(delivered[ex['id']][k] == v for k, v in ex.items())
    context = flat.context()
    for path in legacy.context_files():
        assert path.read_text().rstrip() in context
    for release in catalog['releases']:
        for route in release['routes']:
            assert route['route_id'] in context and route['store_id'] in context
    assert 'expected_probe' not in context and 'expected_disposition' not in context


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
@pytest.mark.parametrize('terminal', ['propose_fleet', 'ask_clarification'])
def test_flat_terminal_has_no_graph_or_probes(monkeypatch, tmp_path, provider, terminal):
    def forbidden(*args, **kwargs):
        raise AssertionError('flat grounding touched graph/probes')
    for name in ('connect', 'current_fleet', 'release_history', 'get_excerpts', 'store_readers'):
        monkeypatch.setattr(G, name, forbidden)
    monkeypatch.setattr(legacy.FlatControlTools, 'run_reader_probe', forbidden)
    original = g._handle_call
    def terminal_validator(*args, **kwargs):
        assert args[7]['request_text'] == 'that change'
        return original(*args, **kwargs)
    monkeypatch.setattr(g, '_handle_call', terminal_validator)
    args = proposal() if terminal == 'propose_fleet' else {'question': 'Which behavior?', 'unresolved': ['that change']}
    transport = Transport([call(terminal, args, provider)], provider)
    result, _ = flat.ground('that change', transport=transport, artifact_dir=tmp_path)
    assert result.result.kind == ('PROPOSAL' if terminal == 'propose_fleet' else 'CLARIFICATION')
    assert not result.validation_errors
    specs = transport.bodies[0]['tools']
    names = [s['function']['name'] for s in specs] if provider == 'groq' else [s['name'] for s in specs[0]['functionDeclarations']]
    assert names == ['propose_fleet', 'ask_clarification']


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
@pytest.mark.parametrize('bad', ['question', 'unresolved', 'quote', 'excerpt'])
def test_legacy_clarification_validates_delivered_citations(tmp_path, provider, bad):
    args = {'question': 'Which change?', 'unresolved': ['change'], 'citations': proposal()['citations']}
    invalid = json.loads(json.dumps(args))
    if bad == 'question': invalid['question'] = ' '
    if bad == 'unresolved': invalid['unresolved'] = [7]
    if bad == 'quote': invalid['citations'][0]['quote'] = 'invented text'
    if bad == 'excerpt': invalid['citations'][0]['excerpt_id'] = 'unknown'
    tr = Transport([call('ask_clarification', invalid, provider), call('ask_clarification', args, provider)], provider)
    transcript, _ = legacy.run_control('ambiguous', transport=tr, save=False)
    assert transcript['result']['kind'] == 'CLARIFICATION'
    assert transcript['result']['raw_arguments'] == args
    assert not transcript['probe_calls'] and not transcript['aborted']
    assert any(e.get('error') for e in transcript['events'])


@pytest.mark.parametrize('mutation', ['release', 'flag', 'boolean', 'quote', 'citation', 'nested'])
def test_invalid_flat_proposals_never_reach_checker(tmp_path, mutation):
    args = proposal()
    if mutation == 'release': args['changes'][0]['release_id'] = 'release:invented'
    if mutation == 'flag': args['changes'][0]['flags'] = [{'name': 'unknown', 'enabled': True}]
    if mutation == 'boolean': args['changes'][0]['flags'] = [{'name': 'unknown', 'enabled': 'false'}]
    if mutation == 'quote': args['citations'][0]['quote'] = 'invented'
    if mutation == 'citation': args['citations'] = []
    if mutation == 'nested': args['changes'][0]['flags:'] = []
    tr = Transport([call('propose_fleet', args)] * 8)
    result, _ = flat.ground('request', transport=tr, artifact_dir=tmp_path)
    assert result.validation_errors
    session = SimpleNamespace(g=None, snapshot_id='snapshot:snap-001', manifest_hash='hash')
    report = run_investigation('request', ground=lambda *a, **kw: (result, None),
                              confirm=lambda plan: pytest.fail('invalid proposal confirmed'),
                              session=session, allow_alternative=False)
    assert 'report' not in report['attempts'][0]


@pytest.mark.parametrize('version', ['1.4', '1.5'])
@pytest.mark.parametrize('snapshot', ['snap-001', 'snap-002-partial', 'snap-003-orphan'])
def test_matched_checker_equivalence(tmp_path, version, snapshot):
    args = proposal(version)
    flat_result, _ = flat.ground('request', transport=Transport([call('propose_fleet', args)]), artifact_dir=tmp_path)
    # Graph arm receives the exact same delivered source rows and terminal via the product validator.
    ex, rel = {}, {}
    g._collect(flat.source_catalog()['releases'], ex, rel)
    graph_proposal, errors = g._finish('propose_fleet', args, ex, rel)
    assert not errors and graph_proposal == flat_result.result
    sessions = []
    try:
        for _ in range(2):
            sessions.append(Session(snapshot=snapshot, graph_name='rw_test_issue22_' + uuid.uuid4().hex))
        plans = [s.plan_from_proposal(p, 'request', origin='agent')[0]
                 for s, p in zip(sessions, [graph_proposal, flat_result.result])]
        assert plans[0].plan_hash() == plans[1].plan_hash()
        reports = [s.verify(p, ScopeConfirmation(plan_hash=p.plan_hash(), confirmed_by='test', confirmed_at='fixed'))
                   for s, p in zip(sessions, plans)]
        from evals.relationship_ablation import comparable
        assert comparable(reports[0]) == comparable(reports[1])
    finally:
        for s in sessions: s.g.delete()


@pytest.mark.parametrize('arm', ['graph_grounding_checker', 'flat_grounding_checker', 'flat_assessment'])
def test_runner_executes_real_checker_protocol_and_cleanup(monkeypatch, tmp_path, arm):
    from evals import run_comparison as runner
    response = call('ask_clarification', {'question': 'Which release?', 'unresolved': ['change']}, 'groq')
    response.update(model='scripted', usage={'prompt_tokens': 0, 'completion_tokens': 10, 'total_tokens': 10})
    transport = Transport([response], 'groq')
    monkeypatch.setattr(runner.grounding, 'make_transport', lambda model: transport)
    slot = next(s for s in runner.schedule(1) if s['arm'] == arm)
    observation = runner.execute_arm(slot, 'groq:scripted', tmp_path, 6379)
    assert observation['status'] == 'completed', observation.get('error')
    assert observation['outcome'] == 'CLARIFICATION'
    assert observation['telemetry']['reported_usage_totals']['total_tokens'] == 10
    assert observation['checker_elapsed_s'] == 0
    if arm != 'flat_assessment':
        assert observation['cleanup'] == 'verified_absent'
        assert {m['name']: m['version'] for m in observation['server']['modules']}['graph'] == 60002
