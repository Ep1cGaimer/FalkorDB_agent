import hashlib,json,os,time
from pathlib import Path
import httpx
from rw.config import load_env
from rw.grounding import _tls_context
from confirmatory.corpus_export import canonical
from confirmatory.gemini_meter import GeminiAPI,ModelFailure
p=Path('artifacts/model-development/citation-pilot-001/graph/events.jsonl')
request=next(e['request'] for e in map(json.loads,p.read_text().splitlines()) if e['kind']=='token_count_started')
request['toolConfig']={'functionCallingConfig':{'mode':'NONE'}}
out=Path('artifacts/model-development/native-none-probe-001.json')
with out.open('xb') as stream:stream.write(canonical({'status':'STARTED'}))
record={'classification':'DEVELOPMENT_FIRST_ACTION_CONFIGURATION_PROBE_ONLY','acceptance_validated':False,
 'not_an_investigation':True,'model':'models/gemini-3.8-flash','deadline_seconds':30,'retries':0,
 'request':request,'request_sha256':hashlib.sha256(canonical(request)).hexdigest()}
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
started=time.monotonic()
try:
 with httpx.Client(verify=_tls_context(),follow_redirects=False) as client:
  api=GeminiAPI(record['model'],os.environ['GEMINI_API_KEY'],client=client)
  record['count']=api.count(request,30-(time.monotonic()-started))
  record['response']=api.generate(request,30-(time.monotonic()-started))
  record['status']='RESPONSE_RECORDED'
except ModelFailure as exc:record.update(status='ERROR',failure=exc.code,http_status=exc.status)
except Exception as exc:record.update(status='ERROR',failure=type(exc).__name__)
record['elapsed_seconds']=time.monotonic()-started
out.write_bytes(canonical(record))
print(json.dumps({k:record.get(k) for k in ['status','failure','http_status','elapsed_seconds']}))
