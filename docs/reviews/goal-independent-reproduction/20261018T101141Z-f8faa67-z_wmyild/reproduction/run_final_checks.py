"""Adopt only owned setup containers; run only an explicitly approved source pin."""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

BASE=pathlib.Path(__file__).resolve().parent
REPO=BASE/'repo'
OUT=BASE/'artifacts'
RUN=json.loads((BASE/'run-attempt2.json').read_text())
ENV=os.environ.copy()
for key in ['GEMINI_API_KEY','GOOGLE_API_KEY','GROQ_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY']:
    ENV.pop(key,None)
ENV.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',GIT_TERMINAL_PROMPT='0')
PYTHON=BASE/'linux-venv-attempt2/bin/python'
SEQUENCE=max(json.loads(line)['sequence'] for line in (OUT/'commands.jsonl').read_text().splitlines())

def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def command(label,args,*,cwd=BASE,timeout=1200,required=True):
    global SEQUENCE
    SEQUENCE+=1
    log=OUT/f'{SEQUENCE:02d}-{label}.log'
    item={'sequence':SEQUENCE,'label':label,'command':list(map(str,args)),'cwd':str(cwd),'started_at':stamp(),'log':str(log),'timeout_seconds':timeout}
    start=time.monotonic()
    with log.open('xb') as f:
        try:
            result=subprocess.run(list(map(str,args)),cwd=cwd,env=ENV,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            item['returncode']=result.returncode
        except Exception as exc:item.update(returncode=None,error=type(exc).__name__+': '+str(exc))
    item.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-start)
    with (OUT/'commands.jsonl').open('a') as f:f.write(json.dumps(item)+'\n')
    print(json.dumps(item),flush=True)
    if required and item['returncode']!=0:raise RuntimeError(label+' failed; see '+str(log))
    return item

def inside(label,args,**options):return command(label,['docker','exec',RUN['python_container'],*args],**options)

def check_manifest(label,manifest,target):
    data=pathlib.Path(manifest).read_bytes()
    original=json.loads(data)
    checked={};mismatches=[]
    for rel,expected in original['files'].items():
        path=REPO/rel
        actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        checked[rel]=actual
        if actual!=expected:mismatches.append({'path':rel,'expected':expected,'actual':actual})
    result={'at':stamp(),'target_commit':target,'source_manifest':manifest,'source_manifest_sha256':hashlib.sha256(data).hexdigest(),'files_checked':len(checked),'mismatches':mismatches,'actual_hashes':checked}
    path=OUT/f'target-{target[:7]}-manifest-{label}.json'
    with path.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'manifest_phase':label,'target':target,'files':len(checked),'mismatches':len(mismatches)}),flush=True)
    return result

def cleanup():
    for key in ['python_container','container']:
        name=RUN[key];expected=RUN['python_container_id' if key=='python_container' else 'container_id']
        actual=subprocess.check_output(['docker','inspect','--format','{{.Id}}',name]).decode().strip()
        if actual!=expected:raise RuntimeError('Refusing cleanup: owned container identity mismatch')
        command('logs-'+name,['docker','logs',name],required=False)
        command('inspect-'+name,['docker','inspect',name],required=False)
        command('stop-'+name,['docker','stop',name],timeout=30,required=False)
        command('remove-'+name,['docker','rm',name],timeout=30,required=False)

def main(approval_path):
    approval=json.loads(pathlib.Path(approval_path).read_text())
    if not approval.get('authorized_to_start_tests') or not approval.get('commit') or not approval.get('manifest_path'):raise RuntimeError('Explicit parent source-pin approval is missing')
    target=approval['commit'];manifest=pathlib.Path(approval['manifest_path'])
    expected_digest=approval['manifest_sha256']
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=expected_digest:raise RuntimeError('Approved manifest byte hash changed')
    for key in ['python_container','container']:
        actual=subprocess.check_output(['docker','inspect','--format','{{.Id}}',RUN[key]]).decode().strip()
        if actual!=RUN['python_container_id' if key=='python_container' else 'container_id']:raise RuntimeError('Owned container identity mismatch')
    namespace=subprocess.check_output(['docker','inspect','--format','{{.HostConfig.NetworkMode}}',RUN['python_container']]).decode().strip()
    if namespace!='container:'+RUN['container_id']:raise RuntimeError('Runner namespace is not the owned DB namespace')
    current=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO).decode().strip()
    if current!=target:
        command('fetch-approved-pin',['git','fetch',approval['parent_repo'],target],cwd=REPO)
        command('checkout-approved-pin',['git','checkout','--detach',target],cwd=REPO)
    command('git-approved-before',['git','status','--porcelain=v1'],cwd=REPO)
    source_snapshot=OUT/f'approved-source-manifest-{target[:7]}.json'
    with source_snapshot.open('xb') as f:f.write(manifest.read_bytes())
    before=check_manifest('before',str(source_snapshot),target)
    if before['mismatches']:raise RuntimeError('Approved source does not match manifest')
    try:
        inside('linux-tools-readiness',[str(PYTHON),'-c','import pathlib,subprocess,json; active=[p.name for p in pathlib.Path("/proc").iterdir() if p.name.isdigit() and (p/"comm").exists() and (p/"comm").read_text().strip() in ("apt-get","dpkg","dpkg-deb")]; assert not active, active; print(json.dumps({"git":subprocess.check_output(["git","--version"],text=True).strip(),"node":subprocess.check_output(["node","--version"],text=True).strip()}))'])
        inside('linux-env-final',[str(PYTHON),'-c','import sys,platform,importlib.metadata,json;print(json.dumps({"python":sys.version,"platform":platform.platform(),"machine":platform.machine(),"executable":sys.executable,"packages":{d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}},indent=2,sort_keys=True))'])
        inside('linux-freeze-final',[str(PYTHON),'-m','pip','freeze'])
        command('owned-redis-info-final',['docker','exec',RUN['container'],'redis-cli','INFO','server'])
        command('owned-redis-modules-final',['docker','exec',RUN['container'],'redis-cli','MODULE','LIST'])
        command('owned-redis-config-final',['docker','exec',RUN['container'],'redis-cli','GRAPH.CONFIG','GET','RESULTSET_SIZE'])
        metadata={'created_at':stamp(),'source_commit':target,'initial_setup_commit':'812ecf7e2153d7662f6523a80365b0622cf92ceb','source_change_reason':approval['reason'],'manifest_sha256':expected_digest,'run':RUN,'runtime_env':{'RW_FALKORDB_HOST':'127.0.0.1','RW_FALKORDB_PORT':'6379','RW_REALREPO':'1','RW_REALREPO_SMOKE':'1'},'secrets_policy':'No provider keys or .env copied into runner','scope':'Development deterministic reproduction only; no Click/confirmatory tasks or live generation; no source/test expectation edits'}
        with (OUT/'final-run-environment.json').open('x') as f:json.dump(metadata,f,indent=2,sort_keys=True);f.write('\n')
        results=[]
        results.append(inside('pytest-final',[str(PYTHON),'-m','pytest','-q','-m','not live','-rA','--junitxml='+str(OUT/'pytest.xml'),'--basetemp='+str(BASE/'pytest-tmp')],timeout=2400,required=False))
        js_receipt=OUT/'javascript-approved-receipt.json'
        if js_receipt.exists():
            completed_js=json.loads(js_receipt.read_text())
            if completed_js['source_commit']!=target:raise RuntimeError('JS check was for another source commit')
            results.append(completed_js['result'])
        else:
            results.append(command('javascript-host-final',['node','--test',*sorted(REPO.glob('tests/js/*.test.mjs'))],cwd=REPO,timeout=120,required=False))
        results.append(inside('deterministic-smoke-final',[str(PYTHON),'scripts/smoke.py'],timeout=180,required=False))
        with (OUT/'check-results.json').open('x') as f:json.dump(results,f,indent=2,sort_keys=True);f.write('\n')
    finally:
        check_manifest('after',str(source_snapshot),target)
        command('git-approved-after',['git','status','--porcelain=v1'],cwd=REPO,required=False)
        cleanup()
    print(json.dumps({'completed_at':stamp(),'source_commit':target,'artifacts':str(OUT),'scope':'Development deterministic reproduction, not T11 validation'}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--approval',required=True)
    args=parser.parse_args()
    try:main(args.approval)
    except Exception as exc:
        path=OUT/('final-driver-error-'+datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')+'.json')
        with path.open('x') as f:json.dump({'at':stamp(),'error':type(exc).__name__+': '+str(exc)},f,indent=2);f.write('\n')
        raise
