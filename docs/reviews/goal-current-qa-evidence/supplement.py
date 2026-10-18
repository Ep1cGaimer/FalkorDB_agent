import hashlib,json,os,subprocess,time,uuid
from pathlib import Path
root=Path.cwd().resolve();out=root/'artifacts/goal-current-qa/full-001'
summary=json.loads((out/'summary.json').read_text());stage=Path(summary['stage'])
result={'classification':'parent staged deterministic supplement','acceptance_validated':False}
files=sorted((stage/'tests/js').glob('*.test.mjs'))
with (out/'javascript.log').open('wb') as log:
 p=subprocess.run(['node','--test',*map(str,files)],cwd=stage,stdout=log,stderr=subprocess.STDOUT)
result['javascript_exit_code']=p.returncode
name='rw-goal-smoke-'+uuid.uuid4().hex[:10]
try:
 subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1::6379','falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6'],check=True,capture_output=True)
 info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
 port=info['NetworkSettings']['Ports']['6379/tcp'][0]['HostPort'];result['owned_smoke_host_port']=port
 for _ in range(40):
  p=subprocess.run(['docker','exec',name,'redis-cli','PING'],capture_output=True)
  if p.returncode==0 and p.stdout.strip()==b'PONG':break
  time.sleep(.1)
 env={**os.environ,'RW_FALKORDB_HOST':'127.0.0.1','RW_FALKORDB_PORT':port}
 for k in ['GEMINI_API_KEY','GROQ_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY']:env.pop(k,None)
 with (out/'smoke.log').open('wb') as log:
  p=subprocess.run(['/tmp/rw-mcp-compat/bin/python','scripts/smoke.py'],cwd=stage,env=env,stdout=log,stderr=subprocess.STDOUT)
 result['smoke_exit_code']=p.returncode
finally:
 p=subprocess.run(['docker','rm','-f',name],capture_output=True)
 result['cleanup_exit_code']=p.returncode
 expected=json.loads((out/'source-before.json').read_text())['files']
 result['source_mismatches_after_supplement']=[rel for rel,h in expected.items() if hashlib.sha256((stage/rel).read_bytes()).hexdigest()!=h]
 (out/'supplement.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
