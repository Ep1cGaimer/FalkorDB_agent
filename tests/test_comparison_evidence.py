"""Portable evidence, tamper rejection, paired denominators and sanitized failures."""
import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals import comparison_evidence as evidence, run_comparison as runner


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.grounding, 'make_transport', lambda model: SimpleNamespace(settings={}))
    source = tmp_path / 'raw'
    def execute(slot, model, out, port):
        return {**slot, 'model': model, 'status': 'completed', 'outcome': 'CLARIFICATION',
                'control': {'model': model, 'snapshot': 'snap-001', 'result': {'kind': 'CLARIFICATION',
                    'question': 'Which release?', 'unresolved': ['change']}, 'aborted': False,
                    'headers': {'authorization': 'Bearer FAKE_SECRET'}, 'account_id': 'account_FAKE',
                    'extra': 'gsk_FAKESECRET org_FAKESECRET', 'raw_body': 'RAW_FAKE_BODY',
                    '_path': '/Users/person/secret.json'}, 'calls': []}
    runner.collect(source, 3, 'groq:scripted', execute=execute)
    out = tmp_path / 'bundle'
    evidence.export(source, out)
    return out


def test_portable_offline_rescoring_and_secret_removal(bundle, tmp_path, monkeypatch):
    raw = '\n'.join(p.read_text() for p in bundle.rglob('*') if p.is_file() and p.suffix in ('.json', '.md'))
    for secret in ['FAKE_SECRET', 'account_FAKE', 'gsk_FAKESECRET', 'org_FAKESECRET', 'RAW_FAKE_BODY', '/Users/person']:
        assert secret not in raw
    moved = tmp_path / 'moved'
    shutil.move(bundle, moved)
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('rescoring opened a socket'))
    assert evidence.main(['verify', str(moved)]) == 0
    scores = evidence.rescore(moved)
    assert scores['verdict'] == 'tie' and scores['denominator'] == 3
    assert all(r['disposition'] == 'CLARIFICATION' for r in scores['rows'])


@pytest.mark.parametrize('tamper', ['edit', 'delete', 'add', 'path', 'version', 'duplicate', 'status'])
def test_rejects_corrupt_unknown_missing_duplicate_and_unsafe_bundle(bundle, tamper):
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if tamper == 'edit': (bundle / 'protocol.json').write_text('{}')
    if tamper == 'delete': (bundle / 'protocol.json').unlink()
    if tamper == 'add': (bundle / 'extra.json').write_text('{}')
    if tamper == 'path': manifest['artifacts']['../escape'] = 'hash'
    if tamper == 'version': manifest['protocol_version'] = 999
    if tamper == 'duplicate': manifest['slots'][1] = manifest['slots'][0]
    if tamper == 'status': manifest['slots'][0]['status'] = 'unrun'
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        evidence.verify(bundle)


def test_unequal_blocks_are_visible_and_not_pooled(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    slot = manifest['slots'][0]
    (bundle / slot['path']).unlink()
    manifest['artifacts'].pop(slot['path'])
    slot.update(status='unrun', outcome='UNRUN')
    manifest['complete'] = False
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    scores = evidence.rescore(bundle)
    assert scores['denominator'] == 2 and len(scores['rows']) == 9 and not scores['complete']


def test_canonical_tuple_is_never_redacted():
    with pytest.raises(ValueError, match='canonical'):
        evidence.sanitize({'tuple': {'path': '/Users/local/bytes'}}, {'dropped_fields': 0, 'redacted_strings': 0, 'paths': 0})


def test_portable_bundle_allows_symlink_ancestor_outside_bundle(bundle, tmp_path):
    alias = tmp_path / 'alias'
    alias.symlink_to(bundle.parent, target_is_directory=True)
    assert evidence.verify(alias / bundle.name)['complete']
    assert evidence.rescore(alias / bundle.name) == evidence.rescore(bundle)


def test_artifact_symlink_inside_bundle_is_rejected(bundle):
    artifact = bundle / 'protocol.json'
    copy = bundle.parent / 'external-protocol.json'
    artifact.rename(copy)
    artifact.symlink_to(copy)
    with pytest.raises(ValueError):
        evidence.verify(bundle)
