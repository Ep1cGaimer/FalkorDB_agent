"""Portable allowlist export, strict validation, and deterministic offline scoring for issue #22."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from evals import score_controls as score
from rw.contracts import h
from evals.run_comparison import ARMS, PROTOCOL_VERSION, schedule, source_hashes, write_json

OBSERVATION_FIELDS = {'block', 'arm', 'status', 'model', 'request', 'snapshot', 'case', 'outcome',
                      'started_at', 'finished_at', 'elapsed_s', 'checker_elapsed_s', 'grounding_elapsed_s', 'server', 'control', 'report',
                      'calls', 'telemetry', 'settings', 'cleanup', 'error', 'source_drift', 'grounding_events'}
CONTROL_FIELDS = {'control', 'control_version', 'request_text', 'snapshot', 'model', 'provider', 'live',
                  'temperature', 'max_turns', 'system_prompt', 'context_files', 'transport_settings',
                  'transport_trace', 'tool_calls', 'model_turns', 'tool_call_count', 'probe_calls',
                  'result', 'validation_errors', 'abandoned', 'aborted', 'started_at'}
SECRET = re.compile(r'(?:gsk_|sk-|org_)[A-Za-z0-9_-]+|Bearer\s+\S+', re.I)
DROP = {'authorization', 'cookie', 'headers', 'api_key', 'account_id', 'organization_id', 'request_id',
        'x_groq', 'raw_error', 'raw_body', 'error_body', 'system_fingerprint'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sanitize(value, counts, key='', tuple_field=False):
    """Known observation fields only; provider envelopes are reduced before export."""
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k.lower() in DROP and not tuple_field:
                counts['dropped_fields'] += 1
                continue
            if k in ('transcript', '_path', 'root'):
                counts['paths'] += 1
                result[k] = None
                continue
            result[k] = sanitize(v, counts, k, tuple_field or k == 'tuple')
        return result
    if isinstance(value, list):
        return [sanitize(v, counts, key, tuple_field) for v in value]
    if isinstance(value, str):
        clean = SECRET.sub('[REDACTED]', value)
        if value.startswith(('/Users/', '/private/', '/tmp/', 'C:\\')):
            clean = '[local-path]'
        if clean != value:
            if tuple_field:
                raise ValueError('export would alter a canonical evidence tuple')
            counts['redacted_strings'] += 1
        return clean
    return value


def safe_path(bundle, name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name:
        raise ValueError('unsafe artifact path')
    target = bundle / name
    if any(p.is_symlink() for p in [target, *target.parents] if p != bundle.parent):
        raise ValueError('symlink in bundle')
    if not target.resolve().is_relative_to(bundle.resolve()):
        raise ValueError('artifact escapes bundle')
    return target


def verify(bundle):
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('protocol_version') != PROTOCOL_VERSION or manifest.get('bundle_version') != 1:
        raise ValueError('unknown bundle protocol/version')
    index = manifest['artifacts']
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if actual != set(index) | {'manifest.json'}:
        raise ValueError('missing or unindexed bundle artifact')
    for name, expected in index.items():
        if digest(safe_path(bundle, name)) != expected:
            raise ValueError(f'artifact hash mismatch: {name}')
    slots = manifest['slots']
    expected = schedule(manifest['requested_blocks'])
    if [(s['block'], s['arm'], s['path']) for s in slots] != [(s['block'], s['arm'], s['path']) for s in expected]:
        raise ValueError('missing, duplicate or unknown observation slot')
    for slot in slots:
        if slot['status'] not in ('completed', 'failed', 'unrun'):
            raise ValueError('unknown observation status')
        if slot['status'] == 'unrun':
            if slot['path'] in index:
                raise ValueError('unrun slot has an observation')
            continue
        observation = json.loads(safe_path(bundle, slot['path']).read_text())
        if any(observation[k] != slot[k] for k in ('block', 'arm', 'status')):
            raise ValueError('observation identity/status mismatch')
        if observation['model'] != manifest['model']:
            raise ValueError('observation model mismatch')
        if 'control' in observation and observation['control'].get('control_version', 6) not in (4, 5, 6):
            raise ValueError('unknown control transcript version')
        for call in observation.get('calls', []):
            if call.get('request_hash') != h(call['request']):
                raise ValueError('request hash mismatch')
            if 'response' in call and call.get('response_hash') != h(call['response']):
                raise ValueError('response hash mismatch')
            if slot['status'] == 'completed' and 'response' in call and call['returned_model'] != manifest['model'].split(':', 1)[1]:
                raise ValueError('returned model mismatch')
        if len(observation.get('calls', [])) > 8:
            raise ValueError('model turn budget exceeded')
    if manifest['complete'] and (not all(s['status'] == 'completed' for s in slots) or not manifest['source_unchanged']):
        raise ValueError('invalid completion claim')
    protocol = json.loads((bundle / 'protocol.json').read_text())
    if protocol.get('version') != PROTOCOL_VERSION:
        raise ValueError('unknown protocol')
    if manifest.get('acceptance_complete'):
        if not manifest['complete'] or manifest['requested_blocks'] < 3:
            raise ValueError('acceptance requires three completed blocks')
        for case in ('A', 'B'):
            ablation = json.loads((bundle / 'ablation' / f'{case}.json').read_text())
            before, after, restored = (ablation[k] for k in ('before', 'after', 'restored_structure'))
            removed = ablation['removed_edges']
            if (len(removed) != 2 or before['nodes'] != after['nodes'] or before != restored or
                after['edges'] != [e for e in before['edges'] if e not in removed] or
                h(before['nodes']) != ablation['node_digest'] or len(ablation['paths_before']) != 4 or
                ablation['paths_after'] or ablation['cleanup'] != 'verified_absent' or
                ablation['ablated']['verification']['disposition'] != 'NEEDS_EVIDENCE' or
                not ablation['fixtures_unchanged']):
                raise ValueError('ablation evidence does not establish the recorded delta')
    return manifest


def rescore(bundle):
    bundle = Path(bundle)
    manifest = verify(bundle)
    fixture_root = bundle / 'scoring-inputs/fixtures/shop'
    fixtures = score.fixture_index(fixture_root)
    manifests = {name: score.manifest_index(fixture_root, name)
                 for name in ('snap-001', 'snap-002-partial', 'snap-003-orphan')}
    oracle = score.load_oracle(bundle / 'scoring-inputs/expected/dispositions.json')
    oi = score.oracle_index(oracle, fixtures, manifests)
    rows = []
    for slot in manifest['slots']:
        row = {'block': slot['block'], 'arm': slot['arm'], 'status': slot['status'], 'outcome': slot.get('outcome', 'UNRUN')}
        if slot['status'] != 'unrun':
            obs = json.loads((bundle / slot['path']).read_text())
            if 'control' in obs:
                run = score.run_from_control(obs['control'], fixtures, manifests['snap-001'])
            elif 'report' in obs:
                runs = score.runs_from_report(obs['report'], fixtures, manifests['snap-001'])
                if len(runs) != 1:
                    raise ValueError('matched arm must have exactly one attempt')
                run = runs[0]
            else:
                run = None
            if run:
                scored = score.score_run(run, oi, fixtures, manifests)
                scored['turns'] = len(obs.get('calls', []))
                row.update(scored)
                row['origin'] = slot['arm']
                case = oi['cases'].get(scored['case'])
                row['request_fit'] = case['request_fit'] if case else None
                row['consistent'] = score.consistent(scored)
            row['telemetry'] = obs.get('telemetry')
            row['elapsed_s'] = obs.get('elapsed_s')
        rows.append(row)
    aligned = [b for b in range(1, manifest['requested_blocks'] + 1)
               if all(any(r['block'] == b and r['arm'] == a and r['status'] == 'completed' for r in rows)
                      for a in ARMS[:2])]
    counts = {a: sum(bool(r.get('consistent')) for r in rows if r['arm'] == a and r['block'] in aligned)
              for a in ARMS[:2]}
    g, f = (counts[a] for a in ARMS[:2])
    verdict = ('incomplete: no aligned completed blocks' if not aligned else 'tie' if g == f else
               'flat control win' if f > g else 'graph grounding advantage')
    return {'protocol_version': PROTOCOL_VERSION, 'rows': rows, 'aligned_blocks': aligned,
            'consistent_counts': counts, 'verdict': verdict, 'complete': manifest['complete'],
            'denominator': len(aligned), 'interpretation':
            'Evidence consistency of grounding/retrieval with shared checker; request fit reported separately. '
            'Clarification semantics are ungraded. Byte/shape readability does not establish cross-service behavior.'}


def comparison_markdown(scores):
    lines = [f"Primary matched comparison: **{scores['verdict']}**; aligned blocks={scores['denominator']}.",
             '', scores['interpretation'], '']
    for arms, title in ((ARMS[:2], 'Matched grounding with shared checker'), (ARMS[2:], 'Legacy workflow')):
        lines += [f'### {title}', '', '| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |',
                  '|---|---|---|---|---|---|---|---|---|']
        for r in scores['rows']:
            if r['arm'] not in arms:
                continue
            usage = ((r.get('telemetry') or {}).get('reported_usage_totals') or {})
            fit = r.get('request_fit') or {}
            lines.append(f"| {r['block']} | {r['arm']} | {r['status']} | {r.get('disposition', r['outcome'])} | "
                         f"{r.get('recall', '—')} | {r.get('consistent', '—')} | "
                         f"basket={fit.get('basket_rollout_undone', 'ungraded')}, receipt={fit.get('receipt_correction_kept', 'ungraded')} | "
                         f"{usage.get('total_tokens', usage.get('totalTokenCount', 'unknown'))} | {round(r['elapsed_s'], 3) if r.get('elapsed_s') is not None else 'unknown'} |")
        lines.append('')
    return '\n'.join(lines)


def export(source, out):
    source, out = Path(source), Path(out)
    manifest = json.loads((source / 'manifest.json').read_text())
    # Collection must still match these fixture/expectation bytes, even after documentation changes.
    for key, expected in {**manifest['source_hashes'], **manifest['expectation_hashes']}.items():
        if key.startswith('fixtures/') or key.startswith('evals/expected/'):
            if digest(ROOT / key) != expected:
                raise ValueError('scoring inputs drifted since collection')
    out.mkdir(parents=True, exist_ok=False)
    counts = {'dropped_fields': 0, 'redacted_strings': 0, 'paths': 0}
    for slot in manifest['slots']:
        if slot['status'] == 'unrun':
            continue
        raw = json.loads((source / slot['path']).read_text())
        observation = {k: v for k, v in raw.items() if k in OBSERVATION_FIELDS}
        # Raw provider envelopes contain arbitrary account metadata; retain only parsed response data
        # and graph/tool/validation events. Exact delivered requests are in calls[].request.
        observation['grounding_events'] = [[e for e in t.get('events', []) if e.get('type') != 'model']
                                           for t in raw.get('grounding_transcripts', [])]
        if 'control' in observation:
            observation['control'] = {k: v for k, v in observation['control'].items() if k in CONTROL_FIELDS}
        write_json(out / slot['path'], sanitize(observation, counts))
    write_json(out / 'protocol.json', sanitize(json.loads((source / 'protocol.json').read_text()), counts))
    if (source / 'ablation').exists():
        for p in sorted((source / 'ablation').glob('*.json')):
            write_json(out / 'ablation' / p.name, sanitize(json.loads(p.read_text()), counts))
    for directory, destination in ((ROOT / 'fixtures/shop', out / 'scoring-inputs/fixtures/shop'),
                                    (ROOT / 'evals/expected', out / 'scoring-inputs/expected')):
        shutil.copytree(directory, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    manifest = sanitize(manifest, counts)
    manifest.update(bundle_version=1, redactions=counts,
                    acceptance_complete=bool(manifest['complete'] and manifest['requested_blocks'] >= 3
                        and all((out / 'ablation' / f'{case}.json').exists() for case in ('A', 'B'))))
    def index():
        manifest['artifacts'] = {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*'))
                                 if p.is_file() and p.name != 'manifest.json'}
        # Snapshot manifests are artifacts too; only the root manifest is excluded.
        for p in out.rglob('manifest.json'):
            if p != out / 'manifest.json':
                manifest['artifacts'][p.relative_to(out).as_posix()] = digest(p)
        write_json(out / 'manifest.json', manifest)
    (out / 'README.md').write_text('Synthetic fixture evidence for issue #22.\n\n'
        'Verify: `python evals/comparison_evidence.py verify BUNDLE`\n\n'
        'Rescore without network or credentials: `python evals/score_controls.py --bundle BUNDLE --json /tmp/scores.json`\n\n'
        'All scoring fixture bytes and expectations are included. Source hashes identify collection inputs; '
        'Git SHA plus dirty inventory records provenance. Exact model requests, parsed tool arguments and '
        'numeric usage are retained. Provider envelopes, account identifiers, credentials and local paths '
        'are excluded. Missing usage remains unknown. Clarification appropriateness is ungraded. '
        'The legacy arm compares broader workflows. SQL can independently reconstruct the ablated pairs.\n')
    index()
    scores = rescore(out)
    write_json(out / 'scores.json', scores)
    (out / 'comparison.md').write_text(comparison_markdown(scores))
    index()
    verify(out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('--input', type=Path, required=True)
    exp.add_argument('--out', type=Path, required=True)
    val = sub.add_parser('verify')
    val.add_argument('bundle', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'export':
        export(args.input, args.out)
    else:
        verify(args.bundle)
        saved = json.loads((args.bundle / 'scores.json').read_text())
        if saved != rescore(args.bundle) or (args.bundle / 'comparison.md').read_text() != comparison_markdown(saved):
            raise ValueError('saved scores/table differ from deterministic rescoring')
    print('Evidence validated')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
