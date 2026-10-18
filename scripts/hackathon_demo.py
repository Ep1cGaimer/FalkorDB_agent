"""Local live graph demo: setup, serve, and smoke; no model provider required.

RW_FALKORDB_PORT=<owned DB port> python scripts/hackathon_demo.py setup
RW_FALKORDB_PORT=<owned DB port> python scripts/hackathon_demo.py serve --port 8127
"""
from __future__ import annotations
import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rw.repo.config import RepoConfig
from rw.repo.index import index_repository
from rw.repo.query import RepoQuery
from rw.repo.source import source_lines
from rw.repo.budget import ReadLimits, active_budget, read_scope

DATA = ROOT / 'artifacts/hackathon-demo'
REAL_SHA = '096c8d42545d3b68ea21a4f890fb2b2d8979c0bd'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n')


def setup():
    DATA.mkdir(parents=True, exist_ok=True)
    repo = ROOT / 'artifacts/repos/itsdangerous'
    if not repo.exists():
        raise SystemExit('Missing development clone: git clone --bare https://github.com/pallets/itsdangerous.git artifacts/repos/itsdangerous')
    cfg = RepoConfig(name='hackathon-itsdangerous', path=repo.resolve(), revisions=[REAL_SHA],
                     tag_pattern=r'(?!)', include=['src/itsdangerous/*.py', 'itsdangerous/*.py'],
                     path_matching='path', regular_files_only=True)
    trap = DATA / 'revision-trap'
    if not trap.exists():
        trap.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-c', 'user.name=Demo', '-c', 'user.email=demo@example.invalid',
                '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', '-C', str(trap), *args]).decode().strip()
        git('init', '-q', '-b', 'main')
        p = trap / 'validation.py'
        p.write_text('def validate(amount):\n    return amount\n')
        git('add', '.'); git('commit', '-qm', 'original without negative amount guard'); git('tag', 'before-fix')
        p.write_text('def validate(amount):\n    if amount < 0:\n        raise ValueError("negative amount")\n    return amount\n')
        git('add', '.'); git('commit', '-qm', 'reject negative amounts'); git('tag', 'fixed')
        git('revert', '--no-edit', 'HEAD'); git('tag', 'reverted')
    cfg_trap = RepoConfig(name='hackathon-revision-trap', path=trap.resolve(),
                         revisions=['before-fix', 'fixed', 'reverted'], tag_pattern=r'^(before-fix|fixed|reverted)$',
                         include=['*.py'], regular_files_only=True)
    cases = {}
    for key, config, label, revision in [('real', cfg, 'ItsDangerous · real repository', REAL_SHA),
                                        ('trap', cfg_trap, 'Revision trap · synthetic Git history', 'fixed')]:
        started = time.monotonic()
        graph = 'rw_hackathon_demo_' + key
        report = index_repository(config, graph)
        if report.status != 'COMPLETE':
            raise RuntimeError('Demo index is incomplete')
        cases[key] = {'config': config.model_dump(mode='json'), 'graph': graph, 'label': label, 'revision': revision}
        save(DATA / (key + '-import.json'), {'seconds': time.monotonic() - started, 'report': dataclasses.asdict(report)})
    save(DATA / 'cases.json', cases)
    print('Setup complete. Real repository and synthetic revert trap indexed into owned demo graphs.')


def context(case):
    cases = json.loads((DATA / 'cases.json').read_text())
    if case not in cases:
        raise ValueError('Unknown demonstration repository')
    item = cases[case]
    cfg = RepoConfig.model_validate(item['config'])
    cfg = cfg.model_copy(update={'query_timeout_seconds': 10.0})
    return item, cfg


def investigate(*args, **kwargs):
    with read_scope(ReadLimits(seconds=10.0)) as budget:
        result = _investigate(*args, **kwargs)
        budget.remaining()
        return result


def _investigate(case='real', revision=None, operation='dependencies', symbol='URLSafeTimedSerializer', limit=30, question=None):
    item, cfg = context(case)
    revision = revision or item['revision']
    trace = []
    q = RepoQuery(item['graph'], cfg.name, trace=trace, limits=ReadLimits(seconds=10.0))
    started = time.monotonic()
    sha, gap = q.resolve(revision)
    if gap:
        raise ValueError(gap.detail)
    result = {'case': case, 'label': item['label'], 'mode': 'LIVE · deterministic graph retrieval · no LLM',
              'repository': cfg.name, 'revision': revision, 'commit': sha, 'operation': operation,
              'edges': [], 'citations': [], 'gaps': [], 'runtime': 'Unverified; source evidence only'}
    if question:
        from rw.repo.investigate import investigate as product_investigate
        findings = product_investigate(cfg.name, revision, question, config=cfg, graph_name=item['graph'], trace=trace)
        result['question'] = question
        result['product_findings'] = findings.to_dict()
        result['summary'] = findings.answer or '\n'.join(f.summary for f in findings.findings if f.summary) or findings.unresolved or 'The question needs clarification or a supported investigation shape.'
        result['citations'] = [dataclasses.asdict(c) for c in findings.citations]
        result['gaps'] = [g.detail for g in findings.gaps]
        # Supplement the existing product's one-hop answer with an explicit
        # two-hop graph view, bound to its uniquely resolved source symbol.
        definition = next((f for f in findings.findings if f.kind == 'definition' and f.facts.get('symbol')), None)
        if definition and definition.facts.get('targets') is not None:
            symbol = definition.facts['symbol']
            page = q.dependencies(sha, symbol, hops=2, limit=limit)
            result['edges'] = [dataclasses.asdict(e) for e in page.items]
            result['coverage'] = {'truncated': page.truncated, 'next_cursor': page.next_cursor, 'hops': 2}
            for edge in page.items:
                result['citations'].extend(dataclasses.asdict(c) for c in (edge.citation, edge.target_citation) if c)
            result['gaps'].extend(g.detail for g in page.coverage.get('gaps', []))
            if page.truncated:
                result['gaps'].append('The supplemental two-hop graph view is truncated; omitted dependencies remain unresolved.')
        operation = 'question_answered'
    if operation == 'dependencies':
        matches = q.symbols(sha, name=symbol)
        if len(matches.items) != 1:
            result['gaps'].append('Choose one exact symbol; no unique matching definition was retrieved.')
            result['summary'] = 'The requested symbol cannot be resolved uniquely.'
        else:
            chosen = matches.items[0]
            page = q.dependencies(sha, chosen.qualname, hops=2, limit=limit)
            result['edges'] = [dataclasses.asdict(x) for x in page.items]
            result['citations'] = [dataclasses.asdict(chosen.citation)]
            for edge in page.items:
                result['citations'].extend(dataclasses.asdict(c) for c in (edge.citation, edge.target_citation) if c)
            result['gaps'].extend(g.detail for g in page.coverage.get('gaps', []))
            if page.truncated:
                result['gaps'].append('Retrieval is truncated: additional relationships remain. No absence conclusion is supported.')
            result['coverage'] = {'truncated': page.truncated, 'next_cursor': page.next_cursor, 'hops': 2}
            result['summary'] = f'{chosen.qualname}: {len(page.items)} retrieved dependency relationships across up to two hops. Parsed relationships and static inferences are labeled separately; runtime dispatch is unverified.'
    elif operation == 'fix':
        status = q.fix_status(sha, 'fixed')
        result['fix_state'] = status.state
        result['summary'] = status.reason
        result['citations'] = [dataclasses.asdict(c) for c in status.citations]
        result['gaps'] = [g.detail for g in status.gaps]
        fix, _ = q.resolve('fixed')
        result['fix_commit'] = fix
        result['fix_is_ancestor'] = q._is_ancestor(fix, sha)
    elif operation != 'question_answered':
        raise ValueError('Unknown operation')
    result['citations'] = list({json.dumps(c, sort_keys=True): c for c in result['citations']}.values())
    result['gaps'].extend(g.detail for g in q._coverage_gaps(sha))
    result['seconds'] = round(time.monotonic() - started, 4)
    result['graph_queries'] = len([x for x in trace if x.get('kind') == 'falkordb_query'])
    result['index_generation'] = q._generation
    result['demo_budget'] = {'retrieval_seconds': 10, 'llm_tokens': 0, 'planned_walkthrough_seconds': 180}
    result['query_trace'] = trace
    result['retrieval_budget'] = active_budget().snapshot()
    run_id = uuid.uuid4().hex
    result['run_id'] = run_id
    save(DATA / 'runs' / (run_id + '.json'), {'result': result, 'trace': trace, 'classification': 'LIVE_DEVELOPMENT_DEMO_NOT_HELDOUT'})
    return result


def source(case, commit, path, content_hash):
    _, cfg = context(case)
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[0-9a-f]{64}', content_hash) or len(path) > 1024:
        raise ValueError('Invalid citation identity')
    item, _ = context(case)
    q = RepoQuery(item['graph'], cfg.name)
    sha, gap = q.resolve(commit)
    if gap:
        raise ValueError(gap.detail)
    data = q._source(sha, path, content_hash)
    return {'path': path, 'commit': commit, 'content_hash': hashlib.sha256(data).hexdigest(),
            'lines': source_lines(data.decode('utf-8', 'replace'))}


def app():
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse
    api = FastAPI(title='RollbackWitness · Live repository evidence')
    @api.get('/', response_class=HTMLResponse)
    def home():
        return (ROOT / 'src/rw/static/repository-demo.html').read_text()
    @api.get('/api/investigate')
    def ask(case: str = 'real', revision: str | None = None, operation: str = 'dependencies',
            symbol: str = Query('URLSafeTimedSerializer', max_length=256), limit: int = Query(30, ge=1, le=30),
            question: str | None = Query(None, max_length=2048)):
        try:
            return investigate(case, revision, operation, symbol, limit, question)
        except Exception as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else 'Graph/source operation failed: ' + type(exc).__name__) from None
    @api.get('/api/source')
    def read_source(case: str, commit: str, path: str, content_hash: str):
        try:
            return source(case, commit, path, content_hash)
        except Exception as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else 'Citation verification failed') from None
    @api.get('/api/replay')
    def replay():
        path = DATA / 'backup.json'
        if not path.is_file():
            raise HTTPException(404, 'No recorded backup has been prepared')
        result = json.loads(path.read_text())
        result['mode'] = 'REPLAY · recorded development run · NOT LIVE'
        return result
    return api


def smoke():
    natural = investigate(question='What does URLSafeTimedSerializer depend on?')
    assert natural['question'] and natural['citations'] and any(e['hops'] == 2 for e in natural['edges'])
    dependency = investigate()
    assert any(x['hops'] == 2 and not x['external'] for x in dependency['edges'])
    for c in dependency['citations']:
        value = source('real', c['commit'], c['path'], c['content_hash'])
        assert c['start_line'] is None or 1 <= c['start_line'] <= c['end_line'] <= len(value['lines'])
    fixed = investigate('trap', 'fixed', 'fix')
    reverted = investigate('trap', 'reverted', 'fix')
    assert fixed['fix_state'] == 'PRESENT' and reverted['fix_state'] == 'ABSENT' and reverted['fix_is_ancestor']
    bounded = investigate(limit=1)
    assert bounded['coverage']['truncated'] and any('truncated' in s for s in bounded['gaps'])
    missing = investigate(symbol='NoSuchDemoSymbol')
    assert missing['gaps'] and not missing['edges']
    receipt = {'status': 'PASS', 'mode': 'live deterministic; no generated model answer', 'checks': [
        'natural-language product investigation', 'real hop-2 graph retrieval', 'all returned citations bind to exact source', 'fixed state PRESENT',
        'reverted state ABSENT despite ancestry', 'truncation exposed', 'missing symbol exposes gap'],
        'run_ids': [r['run_id'] for r in [natural, dependency, fixed, reverted, bounded, missing]]}
    save(DATA / ('smoke-' + uuid.uuid4().hex + '.json'), receipt)
    dependency['recorded_sources'] = {json.dumps(c, sort_keys=True): source('real', c['commit'], c['path'], c['content_hash'])
                                      for c in dependency['citations']}
    save(DATA / 'backup.json', dependency)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'serve', 'smoke'])
    parser.add_argument('--port', type=int, default=8127)
    args = parser.parse_args()
    if args.command == 'setup': setup()
    elif args.command == 'smoke': smoke()
    else:
        import uvicorn
        uvicorn.run(app(), host='127.0.0.1', port=args.port)
