"""Collect three rotated arms with a pinned model, checkpointing every observation.

Export: python evals/comparison_evidence.py export --input artifacts/issue-22/BATCH --out evals/evidence/issue-22/BATCH
Verify: python evals/comparison_evidence.py verify BUNDLE
Rescore: python evals/score_controls.py --bundle BUNDLE --json /tmp/scores.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from rw import config, grounding, graph as G
from rw.contracts import ScopeConfirmation
from rw.pipeline import Session, run_investigation
from evals import flat_grounding, llm_control
from evals.comparison_telemetry import MeasuredTransport, utc

REQUEST = llm_control.REQUEST
ARMS = ('graph_grounding_checker', 'flat_grounding_checker', 'flat_assessment')
PROTOCOL_VERSION = 1


def source_hashes(root=ROOT, *, expectations=False):
    paths = [root / 'pyproject.toml']
    for directory in ('src', 'tests', 'evals', 'fixtures', 'scripts'):
        for path in (root / directory).rglob('*'):
            parts = path.relative_to(root).parts
            if (not path.is_file() or any(p in parts for p in ('__pycache__', '.pytest_cache', 'node_modules'))
                or path.suffix == '.pyc' or (directory == 'evals' and parts[1] in ('results', 'evidence'))):
                continue
            is_expectation = directory == 'evals' and parts[1] in ('expected', 'grounding_cases')
            if is_expectation == expectations:
                paths.append(path)
    if expectations:
        paths = [p for p in paths if p.name != 'pyproject.toml']
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def schedule(runs):
    return [{'block': block + 1, 'arm': arm, 'status': 'unrun',
             'path': f'observations/{block+1}-{arm}.json'}
            for block in range(runs) for arm in ARMS[block % 3:] + ARMS[:block % 3]]


def execute_arm(slot, model, out, db_port):
    started = time.monotonic()
    observation = {**slot, 'started_at': utc(), 'model': model, 'request': REQUEST,
                   'snapshot': 'snap-001', 'case': 'main', 'status': 'failed'}
    measured = None
    session = None
    graph_owned = False
    name = 'rw_issue22_' + uuid.uuid4().hex
    observation['graph_name'] = name if slot['arm'] != 'flat_assessment' else None
    check_s = 0.0
    ground_s = 0.0
    try:
        measured = MeasuredTransport(grounding.make_transport(model), model)
        if slot['arm'] == 'flat_assessment':
            transcript, _ = llm_control.run_control(REQUEST, transport=measured, save=False)
            ground_s = time.monotonic() - started
            observation['control'] = transcript
            observation['outcome'] = ('TURN_EXHAUSTION' if transcript['aborted'] else
                                      transcript['result'].get('kind', 'FINAL'))
            observation['status'] = 'failed' if transcript['aborted'] else 'completed'
        else:
            db = G.connect(port=db_port)
            if name in db.list_graphs():
                raise RuntimeError('disposable graph namespace already exists')
            graph_owned = True
            session = Session(graph_name=name, port=db_port)
            modules = [dict(zip(row[::2], row[1::2]))
                       for row in session.db.connection.execute_command('MODULE', 'LIST')]
            observation['server'] = {'redis_version': session.db.connection.info('server')['redis_version'],
                                      'modules': [{'name': m['name'], 'version': m['ver']}
                                                  for m in modules]}
            verify = session.verify
            def timed_verify(*args, **kwargs):
                nonlocal check_s
                start = time.monotonic()
                try:
                    return verify(*args, **kwargs)
                finally:
                    check_s += time.monotonic() - start
            session.verify = timed_verify
            def ground(request, tools, alternative_context=None):
                nonlocal ground_s
                start = time.monotonic()
                try:
                    if slot['arm'] == 'flat_grounding_checker':
                        return flat_grounding.ground(request, transport=measured, artifact_dir=out / 'grounding')
                    return grounding.ground(request, tools, transport=measured, artifact_dir=out / 'grounding')
                finally:
                    ground_s += time.monotonic() - start
            def confirm(plan):
                return ScopeConfirmation(plan_hash=plan.plan_hash(), confirmed_by='evaluation-scope',
                                         confirmed_at=utc())
            report = run_investigation(REQUEST, ground=ground, confirm=confirm, session=session,
                                       allow_alternative=False)
            observation['report'] = report
            attempts = report['attempts']
            aborted = any(any(e.startswith('GROUNDING_ABORTED') for e in a['grounding']['validation_errors'])
                          for a in attempts)
            observation['outcome'] = 'TURN_EXHAUSTION' if aborted else attempts[-1]['outcome']
            observation['status'] = 'failed' if aborted else 'completed'
            # Preserve graph tool results and validation events as well as the exact wire requests.
            observation['grounding_transcripts'] = [json.loads(Path(a['transcript']).read_text()) for a in attempts]
    except (Exception, KeyboardInterrupt) as exc:
        observation['outcome'] = 'MODEL_MISMATCH' if measured and measured.model_mismatch else 'OPERATIONAL_ERROR'
        observation['error'] = (grounding.provider_error_details(exc) if isinstance(exc, grounding.GroundingError)
                                else {'category': type(exc).__name__})
    finally:
        if graph_owned:
            try:
                db = session.db if session else G.connect(port=db_port)
                if name in db.list_graphs():
                    db.select_graph(name).delete()
                if name in db.list_graphs():
                    raise RuntimeError('owned graph still present')
                observation['cleanup'] = 'verified_absent'
            except Exception as exc:
                observation['cleanup'] = {'error_category': type(exc).__name__}
                observation['status'] = 'failed'
        if measured:
            observation['calls'] = measured.calls
            observation['telemetry'] = measured.summary()
            observation['settings'] = measured.settings
        observation['checker_elapsed_s'] = check_s
        observation['grounding_elapsed_s'] = ground_s
        observation['elapsed_s'] = time.monotonic() - started
        observation['finished_at'] = utc()
    return observation


def collect(out, runs, model, db_port=6382, execute=execute_arm):
    out.mkdir(parents=True, exist_ok=False)
    slots = schedule(runs)
    sources = source_hashes()
    manifest = {'protocol_version': PROTOCOL_VERSION, 'batch_id': out.name, 'started_at': utc(),
                'requested_blocks': runs, 'model': model, 'request': REQUEST, 'snapshot': 'snap-001',
                'slots': slots, 'source_hashes': sources, 'expectation_hashes': source_hashes(expectations=True),
                'complete': False, 'python': platform.python_version(),
                'dependencies': {n: version(n) for n in ('falkordb', 'redis', 'pydantic', 'httpx')},
                'git_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'git_dirty': subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).splitlines()}
    write_json(out / 'protocol.json', {'version': PROTOCOL_VERSION, 'arms': ARMS, 'request': REQUEST,
               'snapshot': 'snap-001', 'temperature': 0, 'max_turns': 8,
               'completion_cap': getattr(grounding.make_transport(model), 'settings', {}).get('max_completion_tokens'),
               'allow_alternative': False, 'clarification_answer': None,
               'tool_result_character_cap': grounding.MAX_RESULT_CHARS, 'context_cap': None,
               'prompts_tools': 'observations/*: calls[].request (hashed); exact delivered history per call',
               'retry_backoff_min_s': grounding.RETRY_MIN_S, 'retry_backoff_max_s': grounding.RETRY_MAX_S,
               'model_alias_policy': 'exact returned identity required', 'db_port': db_port,
               'interpretation': 'grounding/retrieval interface with shared checker; legacy workflow separate'})
    write_json(out / 'manifest.json', manifest)
    for slot in slots:
        if source_hashes() != sources or source_hashes(expectations=True) != manifest['expectation_hashes']:
            manifest['stop_reason'] = 'source_drift_before_arm'
            break
        print(f"Block {slot['block']}/{runs}: {slot['arm']}", flush=True)
        try:
            observation = execute(slot, model, out, db_port)
        except (Exception, KeyboardInterrupt) as exc:
            observation = {**slot, 'model': model, 'status': 'failed', 'outcome': 'OPERATIONAL_ERROR',
                           'error': {'category': type(exc).__name__}}
        if source_hashes() != sources or source_hashes(expectations=True) != manifest['expectation_hashes']:
            observation['status'] = 'failed'
            observation['source_drift'] = True
        write_json(out / slot['path'], observation)
        slot['status'] = observation['status']
        slot['outcome'] = observation['outcome']
        write_json(out / 'manifest.json', manifest)
        if observation['status'] != 'completed':
            manifest['stop_reason'] = observation['outcome']
            break
    manifest['finished_at'] = utc()
    manifest['source_unchanged'] = source_hashes() == sources
    manifest['complete'] = all(s['status'] == 'completed' for s in slots) and manifest['source_unchanged']
    write_json(out / 'manifest.json', manifest)
    return manifest


def main(argv=None):
    config.load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--model', required=True, help='one explicit provider:model, no fallback')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--db-port', type=int, default=6382, help='dedicated evaluation server')
    args = parser.parse_args(argv)
    if args.runs < 1 or ',' in args.model or ':' not in args.model:
        parser.error('use a positive run count and one explicit provider:model')
    model = ':'.join(grounding.split_model(args.model))
    if not grounding.has_credentials(model):
        parser.error('selected provider credentials are unavailable')
    out = args.out.resolve()
    if out.exists() or any(out.is_relative_to(ROOT / d) for d in ('src', 'tests', 'fixtures', 'scripts', 'evals')):
        parser.error('use a new output directory outside source trees (for example artifacts/issue-22/BATCH)')
    manifest = collect(out, args.runs, model, args.db_port)
    print(f"Completed={manifest['complete']}; evidence={out}")
    return 0 if manifest['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
