"""Schedule/checkpoint/failure-boundary tests without provider or database access."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals import run_comparison as runner
from evals.comparison_telemetry import MeasuredTransport
from rw import grounding as g

MODEL = 'groq:scripted'


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.grounding, 'make_transport', lambda model: SimpleNamespace(settings={}))
    return tmp_path / 'batch'


def observed(slot, model, out, port):
    return {**slot, 'status': 'completed', 'outcome': 'REJECTED_PROPOSAL', 'model': model}


def test_rotated_schedule_and_semantic_failures_complete(setup):
    manifest = runner.collect(setup, 3, MODEL, execute=observed)
    assert manifest['complete'] and len(manifest['slots']) == 9
    assert [s['arm'] for s in manifest['slots'][::3]] == list(runner.ARMS)
    assert all(s['status'] == 'completed' for s in manifest['slots'])


@pytest.mark.parametrize('failed_slot', [0, 1, 4, 8])
@pytest.mark.parametrize('failure', ['PROVIDER_ERROR', 'TIMEOUT', 'TURN_EXHAUSTION', 'MODEL_MISMATCH'])
def test_failure_preserved_and_remaining_slots_unrun(setup, failed_slot, failure):
    calls = []
    def execute(slot, *args):
        calls.append(slot)
        return {**observed(slot, *args), **({'status': 'failed', 'outcome': failure}
                                          if len(calls) == failed_slot + 1 else {})}
    manifest = runner.collect(setup, 3, MODEL, execute=execute)
    assert not manifest['complete']
    assert len(calls) == failed_slot + 1
    assert [s['status'] for s in manifest['slots']] == ['completed'] * failed_slot + ['failed'] + ['unrun'] * (8 - failed_slot)
    assert json.loads((setup / manifest['slots'][failed_slot]['path']).read_text())['outcome'] == failure


def test_source_drift_stops_and_preserves_observation(setup, monkeypatch):
    original = runner.source_hashes
    drift = False
    monkeypatch.setattr(runner, 'source_hashes', lambda *a, **kw: {'changed': 'hash'} if drift else original(*a, **kw))
    def execute(*args):
        nonlocal drift
        drift = True
        return observed(*args)
    manifest = runner.collect(setup, 3, MODEL, execute=execute)
    assert not manifest['complete'] and manifest['slots'][0]['status'] == 'failed'
    assert json.loads((setup / manifest['slots'][0]['path']).read_text())['source_drift']


@pytest.mark.parametrize('name', ['fixtures/shop/releases/new/CHANGELOG.md', 'fixtures/shop/payloads/record.bin'])
def test_source_inventory_detects_changes_additions_removals(tmp_path, name):
    p = tmp_path / name
    p.parent.mkdir(parents=True)
    initial = runner.source_hashes(tmp_path)
    p.write_bytes(b'first')
    added = runner.source_hashes(tmp_path)
    assert added != initial
    p.write_bytes(b'second')
    assert runner.source_hashes(tmp_path) != added
    p.unlink()
    assert runner.source_hashes(tmp_path) == initial


def test_inventory_excludes_outputs_but_separates_expectations(tmp_path):
    for name in ['evals/evidence/new.json', 'evals/results/new.json', 'artifacts/new.json',
                 'evals/expected/oracle.json', 'fixtures/results/retained.bin']:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'facts')
    assert set(runner.source_hashes(tmp_path)) == {'fixtures/results/retained.bin'}
    assert set(runner.source_hashes(tmp_path, expectations=True)) == {'evals/expected/oracle.json'}


@pytest.mark.parametrize('usage', [{'prompt_tokens': 0, 'completion_tokens': 2, 'total_tokens': 2}, None,
                                  {'prompt_tokens': True, 'total_tokens': '5', 'secret': 'gsk_FAKE'}])
def test_telemetry_usage_numbers_unknown_and_model_identity(usage):
    transport = SimpleNamespace(provider='groq', trace=[])
    class Underlying:
        provider = transport.provider
        trace = transport.trace
        def __call__(self, body):
            self.trace.append({'status': 200})
            return {'model': 'scripted', 'usage': usage, 'choices': [{'message': {'role': 'assistant', 'content': 'text'}}]}
    times = iter([10, 13])
    measured = MeasuredTransport(Underlying(), MODEL, clock=lambda: next(times))
    measured({'messages': [], 'tools': []})
    summary = measured.summary()
    assert summary['model_calls'] == 1 and summary['http_attempts'] == 1 and summary['model_elapsed_s'] == 3
    if usage and 'completion_tokens' in usage:
        assert summary['reported_usage_totals'] == usage and summary['usage_unknown_calls'] == 0
    else:
        assert summary['reported_usage_totals'] == {} and summary['usage_unknown_calls'] == 1


def test_telemetry_rejected_and_wrong_model():
    class Underlying:
        provider = 'groq'
        trace = []
        def __call__(self, body): return {'model': 'different'}
    measured = MeasuredTransport(Underlying(), MODEL)
    with pytest.raises(g.GroundingError): measured({})
    assert measured.model_mismatch and measured.summary()['usage_unknown_calls'] == 1


def test_cleanup_failure_does_not_hide_original_provider_failure(monkeypatch, tmp_path):
    class Underlying:
        provider = 'groq'
        def __call__(self, body): raise g.GroundingError('secret gsk_FAKE', code='quota')
    monkeypatch.setattr(runner.grounding, 'make_transport', lambda model: Underlying())
    monkeypatch.setattr(runner.G, 'connect', lambda **kw: SimpleNamespace(list_graphs=lambda: []))
    class Session:
        def __init__(self, **kwargs):
            self.g = None
            self.db = SimpleNamespace(list_graphs=lambda: (_ for _ in ()).throw(RuntimeError('cleanup error')))
        def verify(self): pass
    monkeypatch.setattr(runner, 'Session', Session)
    monkeypatch.setattr(runner, 'run_investigation', lambda *a, **kw: (_ for _ in ()).throw(g.GroundingError('gsk_SECRET')))
    result = runner.execute_arm(runner.schedule(1)[0], MODEL, tmp_path, 6382)
    assert result['status'] == 'failed' and 'cleanup' in result and 'error' in result
    assert 'gsk_SECRET' not in json.dumps(result)
