"""Independent deterministic reproduction driver; no confirmatory corpus access."""
import datetime
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import tomllib

BASE=pathlib.Path(__file__).resolve().parent
RUN=json.loads((BASE/'run.json').read_text())
OUT=BASE/'artifacts'
REPO=BASE/'repo'
ENV=os.environ.copy()
for key in ['GEMINI_API_KEY','GOOGLE_API_KEY','GROQ_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY']:
    ENV.pop(key,None)
ENV.update(PYTHONDONTWRITEBYTECODE='1',GIT_TERMINAL_PROMPT='0',PYTHONUNBUFFERED='1')
NUMBER=0

def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def command(label,args,*,cwd=BASE,env=None,timeout=1200,required=True):
    global NUMBER
    NUMBER+=1
    log=OUT/f'{NUMBER:02d}-{label}.log'
    record={'sequence':NUMBER,'label':label,'command':list(map(str,args)),'cwd':str(cwd),'started_at':stamp(),'log':str(log),'timeout_seconds':timeout}
    start=time.monotonic()
    try:
        with log.open('wb') as handle:
            completed=subprocess.run(list(map(str,args)),cwd=cwd,env=env or ENV,stdout=handle,stderr=subprocess.STDOUT,timeout=timeout)
        record['returncode']=completed.returncode
    except Exception as exc:
        record.update(returncode=None,error=type(exc).__name__+': '+str(exc))
    record.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-start)
    with (OUT/'commands.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
    print(json.dumps(record),flush=True)
    if required and record['returncode']!=0:raise RuntimeError(label+' failed; see '+str(log))
    return record

def manifest_check(label):
    original=pathlib.Path(RUN['parent'])/'docs/reviews/goal-control-flags-evidence/implementation-manifest.json'
    snapshot=OUT/'source-manifest.json'
    if label=='before':snapshot.write_bytes(original.read_bytes())
    data=snapshot.read_bytes()
    expected=json.loads(data)
    checked={};mismatches=[]
    for rel,digest in expected['files'].items():
        path=REPO/rel
        current=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        checked[rel]=current
        if current!=digest:mismatches.append({'path':rel,'expected':digest,'actual':current})
    body={'label':label,'recorded_at':stamp(),'manifest_source':str(original),'manifest_sha256':hashlib.sha256(data).hexdigest(),'expected_implementation_commit':expected.get('implementation_commit'),'files_checked':len(checked),'mismatches':mismatches,'actual_hashes':checked}
    (OUT/f'manifest-{label}.json').write_text(json.dumps(body,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'manifest_check':label,'files':len(checked),'mismatches':len(mismatches)}),flush=True)
    return body

def setup():
    command('clone',['git','clone','--no-hardlinks',RUN['parent'],REPO])
    command('checkout',['git','checkout','--detach',RUN['commit']],cwd=REPO)
    command('git-before',['git','status','--porcelain=v1'],cwd=REPO)
    result=manifest_check('before')
    if result['mismatches']:raise RuntimeError('Source bytes differ from pinned implementation manifest')
    command('venv',['uv','venv','--python','3.12',BASE/'venv'])
    python=BASE/'venv/bin/python'
    pyproject=tomllib.loads((REPO/'pyproject.toml').read_text())
    packages=pyproject['project']['dependencies']+pyproject['project']['optional-dependencies']['mcp']+['pytest==9.1.1']
    command('install',['uv','pip','install','--python',python,*packages],timeout=1200)
    command('freeze',['uv','pip','freeze','--python',python])
    for name in ['requests','itsdangerous']:
        target=REPO/'artifacts/repos'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        command('clone-dev-'+name,['git','clone','--bare','--no-hardlinks',pathlib.Path(RUN['parent'])/'artifacts/repos'/name,target])
        command('dev-metadata-'+name,['git',f'--git-dir={target}','show','-s','--format=%H %P %s','HEAD'])
    command('docker-start',['docker','run','-d','--name',RUN['container'],'--publish','127.0.0.1::6379',RUN['image']],timeout=120)
    command('docker-inspect',['docker','inspect',RUN['container']])
    inspect=json.loads((OUT/'12-docker-inspect.log').read_text()) if (OUT/'12-docker-inspect.log').exists() else json.loads(subprocess.check_output(['docker','inspect',RUN['container']]))
    binding=inspect[0]['NetworkSettings']['Ports']['6379/tcp'][0]
    if binding['HostIp']!='127.0.0.1':raise RuntimeError('non-loopback Docker binding')
    RUN['database_host']='127.0.0.1';RUN['database_port']=int(binding['HostPort'])
    RUN['container_id']=inspect[0]['Id']
    (BASE/'run.json').write_text(json.dumps(RUN,indent=2)+'\n')
    for _ in range(60):
        try:
            socket.create_connection(('127.0.0.1',RUN['database_port']),timeout=1).close();break
        except OSError:time.sleep(0.5)
    else:raise RuntimeError('Owned database did not become reachable')
    print(json.dumps({'setup':'READY','database_host':RUN['database_host'],'database_port':RUN['database_port'],'python':str(python)}),flush=True)

if __name__=='__main__':
    try:
        setup()
    except Exception as exc:
        (OUT/'setup-error.json').write_text(json.dumps({'at':stamp(),'error':type(exc).__name__+': '+str(exc)},indent=2)+'\n')
        raise
