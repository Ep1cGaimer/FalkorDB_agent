import dataclasses,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
from rw.config import load_env
from confirmatory.plaintext_tools import PlaintextTools
from confirmatory.graph_tools import config_for_export
from rw.repo.index import index_repository
root=Path.cwd()
out=root/'artifacts/model-protocol-development/native-pilot-003'
out.mkdir(exist_ok=False)
record={'classification':'UNSCORED_DEVELOPMENT_TWO_ARMS_NOT_CONFIRMATORY','acceptance_validated':False,'retries':0,'planned_order':['graph','plaintext'],'commands':[]}
paths=json.loads((root/'docs/reviews/goal-hackathon-delivery-evidence/implementation-manifest.json').read_text())['files']
paths=set(paths)|{'evals/confirmatory/citation_guard.py','tests/test_confirmatory_citation_guard.py','tests/repo/test_empty_source_evidence.py','tests/test_confirmatory_native_decisions.py'}
(out/'source-before.json').write_text(json.dumps({'files':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sorted(paths)}},indent=2)+'\n')
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
db='rw-goal-native-pilot-003-20261018'
subprocess.run(['docker','run','-d','--name',db,'--memory=1g','-p','127.0.0.1::6379','falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6'],check=True,stdout=subprocess.DEVNULL)
port=json.loads(subprocess.check_output(['docker','inspect',db,'--format','{{json .NetworkSettings.Ports}}']))['6379/tcp'][0]['HostPort']
os.environ['RW_FALKORDB_PORT']=port
record['owned_database']={'container':db,'port':port,'no_restart':True}
export='artifacts/corpus-development/itsdangerous-full-001'
raw=PlaintextTools(Path(export))
record['corpus_sha256']=raw.corpus_hash
# New simple development question, same question for both arms; no answer input.
task=str(out/'task.json')
Path(task).write_text(json.dumps({'id':'DEV-ITS-SIGNATURE-001','question':'At this revision, what is the declared class signature of Signer? Locate its definition, cite exact physical source lines, and leave runtime behavior unverified.','repository':raw.repository,'revision':raw.spec['roots'][0]},indent=2)+'\n')
for arm in record['planned_order']:
 if arm=='graph':
  started=time.monotonic()
  graph_name='rw_goal_native_pilot_003'
  try:
   report=index_repository(config_for_export(raw,root/'artifacts/repos/itsdangerous'),graph_name)
   record['index']={'seconds':time.monotonic()-started,'report':dataclasses.asdict(report)}
  except Exception as exc:
   record['index']={'status':'ERROR','type':type(exc).__name__,'seconds':time.monotonic()-started}
   (out/'index-error.txt').write_text(traceback.format_exc())
   continue
 args=[sys.executable,'-m','confirmatory.development_cli','--export',export,'--task',task,'--output',str(out/arm),'--model','models/gemini-3.8-flash','--tls-max12','--decision-protocol','native','--arm',arm]
 if arm=='graph':args.extend(['--graph',graph_name])
 started=time.monotonic()
 with (out/(arm+'.log')).open('wb') as stream:
  p=subprocess.run(args,stdout=stream,stderr=subprocess.STDOUT)
 record['commands'].append({'command':args,'exit_code':p.returncode,'seconds':time.monotonic()-started})
 (out/'progress.json').write_text(json.dumps(record,indent=2)+'\n')
record['source_mismatches']=[p for p,h in json.loads((out/'source-before.json').read_text())['files'].items() if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
(out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'arms':[c['exit_code'] for c in record['commands']],'source_mismatches':record['source_mismatches']}))

r=subprocess.run(['docker','rm','-f','rw-goal-native-pilot-003-20261018'],capture_output=True)
(out/'cleanup.json').write_text(json.dumps({'owned_container':'rw-goal-native-pilot-003-20261018','remove_exit_code':r.returncode,'remaining':subprocess.check_output(['docker','ps','-a','--filter','name=rw-goal-native-pilot-003-20261018','--format','{{.Names}}']).decode().splitlines()},indent=2)+'\n')
