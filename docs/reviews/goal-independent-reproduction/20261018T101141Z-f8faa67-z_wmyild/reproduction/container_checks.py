"""Owned Linux network namespace avoids two hardcoded host-port fixtures."""
import json
import pathlib
import subprocess
import sys
from reproduce import BASE,OUT,REPO,RUN,ENV,command,manifest_check,stamp
import reproduce

reproduce.NUMBER=max(json.loads(line)['sequence'] for line in (OUT/'commands.jsonl').read_text().splitlines())
setup_inspect=json.loads((OUT/'12-docker-inspect.log').read_text())
started=(OUT/'11-docker-start.log').read_text().strip()
if setup_inspect[0]['Id']!=started:raise RuntimeError('DB ownership mismatch')
RUN['container_id']=started
PYNAME=RUN['container']+'-python'
PYIMAGE='python:3.12.9-slim-bookworm'
VENV=BASE/'linux-venv'
PYTHON=VENV/'bin/python'
if not (OUT/'source-manifest.json').exists():
    import hashlib
    original=pathlib.Path(RUN['parent'])/'docs/reviews/goal-control-flags-evidence/implementation-manifest.json'
    if hashlib.sha256(original.read_bytes()).hexdigest()!=json.loads((OUT/'manifest-before.json').read_text())['manifest_sha256']:raise RuntimeError('Source manifest changed')
    (OUT/'source-manifest.json').write_bytes(original.read_bytes())

def inside(label,args,**options):
    return command(label,['docker','exec',PYNAME,*args],**options)

def cleanup():
    for name,expected in [(PYNAME,RUN.get('python_container_id')),(RUN['container'],RUN['container_id'])]:
        if not expected:continue
        result=subprocess.run(['docker','inspect','--format','{{.Id}}',name],capture_output=True,text=True)
        if result.returncode or result.stdout.strip()!=expected:
            print(json.dumps({'cleanup_refused':name,'reason':'identity unavailable/mismatch'}),flush=True);continue
        command('logs-'+name,['docker','logs',name],required=False)
        command('inspect-'+name,['docker','inspect',name],required=False)
        command('stop-'+name,['docker','stop',name],timeout=30,required=False)
        command('remove-'+name,['docker','rm',name],timeout=30,required=False)

def main():
    command('python-image',['docker','image','inspect',PYIMAGE])
    image=json.loads((OUT/f'{reproduce.NUMBER:02d}-python-image.log').read_text())[0]
    image_id=image['Id']
    record=command('python-start',['docker','run','-d','--name',PYNAME,'--network','container:'+RUN['container'],'--mount',f'type=bind,source={BASE},target={BASE}','--workdir',str(REPO),'-e','RW_FALKORDB_HOST=127.0.0.1','-e','RW_FALKORDB_PORT=6379','-e','RW_REALREPO=1','-e','RW_REALREPO_SMOKE=1','-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONUNBUFFERED=1','-e','GIT_TERMINAL_PROMPT=0','-e','PYTHONPATH='+str(REPO/'src'),image_id,'sleep','infinity'])
    RUN.update(python_container=PYNAME,python_image_id=image_id,python_image_digests=image.get('RepoDigests'),python_container_id=pathlib.Path(record['log']).read_text().strip(),linux_venv=str(VENV),namespace_endpoint={'host':'127.0.0.1','port':6379},host_endpoint={'host':'127.0.0.1','port':RUN['database_port']})
    (BASE/'run.json').write_text(json.dumps(RUN,indent=2)+'\n')
    try:
        inside('linux-tools',['sh','-c','apt-get update && apt-get install -y --no-install-recommends git nodejs ca-certificates'],timeout=1200)
        inside('linux-venv',['python','-m','venv',str(VENV)])
        pins=(OUT/'06-freeze.log').read_text()
        requirements=BASE/'exact-requirements.txt'
        requirements.write_text(pins)
        inside('linux-install',[str(PYTHON),'-m','pip','install','--disable-pip-version-check','-r',str(requirements)],timeout=1200)
        inside('linux-freeze',[str(PYTHON),'-m','pip','freeze'])
        inside('linux-environment',[str(PYTHON),'-c','import sys,platform,importlib.metadata,json;print(json.dumps({"python":sys.version,"platform":platform.platform(),"machine":platform.machine(),"executable":sys.executable,"packages":{d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}},indent=2,sort_keys=True))'])
        command('owned-redis-ping',['docker','exec',RUN['container'],'redis-cli','PING'])
        command('owned-redis-info',['docker','exec',RUN['container'],'redis-cli','INFO','server'])
        command('owned-redis-modules',['docker','exec',RUN['container'],'redis-cli','MODULE','LIST'])
        command('owned-redis-config',['docker','exec',RUN['container'],'redis-cli','GRAPH.CONFIG','GET','RESULTSET_SIZE'])
        inside('pytest',[str(PYTHON),'-m','pytest','-q','-m','not live','-rA','--junitxml='+str(OUT/'pytest.xml'),'--basetemp='+str(BASE/'pytest-tmp')],timeout=2400,required=False)
        command('javascript-host',['node','--test',*sorted(REPO.glob('tests/js/*.test.mjs'))],cwd=REPO,timeout=120,required=False)
        inside('deterministic-smoke',[str(PYTHON),'scripts/smoke.py'],timeout=180,required=False)
    finally:
        manifest_check('after')
        command('git-after',['git','status','--porcelain=v1'],cwd=REPO,required=False)
        cleanup()
    print(json.dumps({'completed_at':stamp(),'artifacts':str(OUT),'scope':'Development deterministic reproduction only'}),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        (OUT/'container-error.json').write_text(json.dumps({'at':stamp(),'error':type(exc).__name__+': '+str(exc)},indent=2)+'\n')
        raise
