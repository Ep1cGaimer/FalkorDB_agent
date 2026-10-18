import dataclasses,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
from rw.config import load_env
from confirmatory.plaintext_tools import PlaintextTools
from confirmatory.graph_tools import config_for_export
from rw.repo.index import index_repository
root=Path.cwd()
out=root/'artifacts/model-development/citation-pilot-001'
out.mkdir(exist_ok=False)
record={'classification':'UNSCORED_DEVELOPMENT_TWO_ARMS_NOT_CONFIRMATORY','acceptance_validated':False,'retries':0,'planned_order':['plaintext','graph'],'commands':[]}
paths=json.loads((root/'docs/reviews/goal-corpus-token-evidence/implementation-manifest.json').read_text())['files']
paths=set(paths)|{'evals/confirmatory/citation_guard.py','tests/test_confirmatory_citation_guard.py','tests/repo/test_empty_source_evidence.py'}
(out/'source-before.json').write_text(json.dumps({'files':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sorted(paths)}},indent=2)+'\n')
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
os.environ['RW_FALKORDB_PORT']='51733'
export='artifacts/corpus-development/requests-full-002'
raw=PlaintextTools(Path(export))
record['corpus_sha256']=raw.corpus_hash
# Same public development question as earlier failures; no expected-answer input.
task='artifacts/model-development/requests-development-task.json'
for arm in record['planned_order']:
 if arm=='graph':
  started=time.monotonic()
  graph_name='rw_goal_citation_pilot_001'
  try:
   report=index_repository(config_for_export(raw,root/'artifacts/repos/requests'),graph_name)
   record['index']={'seconds':time.monotonic()-started,'report':dataclasses.asdict(report)}
  except Exception as exc:
   record['index']={'status':'ERROR','type':type(exc).__name__,'seconds':time.monotonic()-started}
   (out/'index-error.txt').write_text(traceback.format_exc())
   continue
 args=[sys.executable,'-m','confirmatory.development_cli','--export',export,'--task',task,'--output',str(out/arm),'--model','models/gemini-3.8-flash','--tls-max12','--arm',arm]
 if arm=='graph':args.extend(['--graph',graph_name])
 started=time.monotonic()
 with (out/(arm+'.log')).open('wb') as stream:
  p=subprocess.run(args,stdout=stream,stderr=subprocess.STDOUT)
 record['commands'].append({'command':args,'exit_code':p.returncode,'seconds':time.monotonic()-started})
 (out/'progress.json').write_text(json.dumps(record,indent=2)+'\n')
record['source_mismatches']=[p for p,h in json.loads((out/'source-before.json').read_text())['files'].items() if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
(out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'arms':[c['exit_code'] for c in record['commands']],'source_mismatches':record['source_mismatches']}))
