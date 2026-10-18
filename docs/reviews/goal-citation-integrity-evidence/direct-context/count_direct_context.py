import hashlib,json,os,time
from pathlib import Path
import httpx
from rw.config import load_env
from rw.grounding import _tls_context
from confirmatory.corpus_export import canonical
from confirmatory.gemini_meter import GeminiAPI,ModelFailure
source=Path('artifacts/corpus-development/itsdangerous-direct-context-001/context.txt')
receipt=json.loads((source.parent/'receipt.json').read_text())
text=source.read_text(newline='') if False else source.read_bytes().decode('utf-8')
assert hashlib.sha256(text.encode()).hexdigest()==receipt['context_sha256']
out=source.parent/'provider-count-001.json'
with out.open('xb') as stream:stream.write(canonical({'status':'STARTED'}))
record={'schema':'development-direct-context-provider-count/v1','acceptance_validated':False,'heldout':False,
 'repository':'itsdangerous-development','model':'models/gemini-3.8-flash','corpus_sha256':receipt['corpus_sha256'],
 'context_sha256':receipt['context_sha256'],'renderer_sha256':receipt['renderer_sha256'],'bytes':len(text.encode()),
 'request_scope':'Entire factored context; one user text part; no answer prompt, output or tool reserve',
 'tokenizer':'provider countTokens complete generateContentRequest; not a local estimate'}
request={'contents':[{'role':'user','parts':[{'text':text}]}]}
record['request_sha256']=hashlib.sha256(canonical(request)).hexdigest()
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
started=time.monotonic()
try:
 with httpx.Client(verify=_tls_context(),follow_redirects=False) as client:
  api=GeminiAPI(record['model'],os.environ['GEMINI_API_KEY'],client=client)
  result=api.count(request,120)
  record.update(status='PASS',response=result)
except ModelFailure as exc:
 record.update(status='ERROR',failure=exc.code,http_status=exc.status)
except Exception as exc:record.update(status='ERROR',failure=type(exc).__name__)
record['elapsed_seconds']=time.monotonic()-started
out.write_bytes(canonical(record))
print(json.dumps(record,sort_keys=True))
