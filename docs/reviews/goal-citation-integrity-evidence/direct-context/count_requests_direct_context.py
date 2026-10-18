import base64,hashlib,json,os,time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from rw.config import load_env
from rw.grounding import _tls_context
from confirmatory.corpus_export import canonical
from confirmatory.gemini_meter import GeminiAPI,ModelFailure
from confirmatory.file_identity import verify_file_identity
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
source=Path('artifacts/corpus-development/requests-direct-context-001/context.txt')
receipt=json.loads((source.parent/'receipt.json').read_text())
data_hash=hashlib.sha256(source.read_bytes()).hexdigest()
assert data_hash==receipt['context_sha256']
out=source.parent/'provider-count-001.json'
if out.exists():raise FileExistsError(out)
record={'schema':'development-full-corpus-provider-token-count/v1','classification':'full factored development direct context via text/plain file; count only; no answer generation','model':'models/gemini-3.8-flash','context_sha256':data_hash,'corpus_sha256':receipt['corpus_sha256'],'renderer_sha256':receipt['renderer_sha256'],'corpus_bytes':source.stat().st_size,'repository':'requests-development','heldout':False,'acceptance_validated':False,'events':[],'reference':'https://ai.google.dev/gemini-api/docs/files'}
def event(stage,**fields):
 record['events'].append({'stage':stage,**fields})
 out.write_bytes(canonical(record))
key=os.environ['GEMINI_API_KEY'];name=None
base='https://generativelanguage.googleapis.com'
started=time.monotonic()
with httpx.Client(verify=_tls_context(),follow_redirects=False,timeout=120) as client:
 try:
  response=client.post(base+'/upload/v1beta/files',headers={'x-goog-api-key':key,'X-Goog-Upload-Protocol':'resumable','X-Goog-Upload-Command':'start','X-Goog-Upload-Header-Content-Length':str(source.stat().st_size),'X-Goog-Upload-Header-Content-Type':'text/plain'},json={'file':{'display_name':'rw-development-requests-corpus-'+data_hash[:12]}})
  event('upload_started',http_status=response.status_code)
  if response.status_code!=200:raise ModelFailure('FILE_UPLOAD_START_FAILED',status=response.status_code)
  upload_url=response.headers.get('x-goog-upload-url','')
  parsed=urlparse(upload_url)
  if parsed.scheme!='https' or parsed.hostname!='generativelanguage.googleapis.com':raise ModelFailure('UNEXPECTED_UPLOAD_HOST')
  event('upload_route',host=parsed.hostname,session_url_sha256=hashlib.sha256(upload_url.encode()).hexdigest())
  def chunks():
   with source.open('rb') as stream:
    while chunk:=stream.read(1024*1024):yield chunk
  response=client.post(upload_url,headers={'Content-Length':str(source.stat().st_size),'X-Goog-Upload-Offset':'0','X-Goog-Upload-Command':'upload, finalize'},content=chunks())
  event('upload_completed',http_status=response.status_code)
  if response.status_code!=200:raise ModelFailure('FILE_UPLOAD_FAILED',status=response.status_code)
  meta=response.json()['file'];name=meta['name']
  if not name.startswith('files/') or '/' in name[len('files/'):]:raise ModelFailure('UNEXPECTED_FILE_NAME')
  for attempt in range(31):
   state=meta.get('state')
   if state=='ACTIVE':break
   if state!='PROCESSING' or attempt==30:raise ModelFailure('FILE_NOT_ACTIVE')
   time.sleep(1)
   response=client.get(base+'/v1beta/'+name,headers={'x-goog-api-key':key})
   if response.status_code!=200:raise ModelFailure('FILE_METADATA_FAILED',status=response.status_code)
   meta=response.json()
  identity=verify_file_identity(meta,expected_sha256=data_hash,expected_bytes=source.stat().st_size)
  event('file_identity_verified',name=name,identity=identity,state=meta['state'])
  request={'contents':[{'role':'user','parts':[{'fileData':{'mimeType':'text/plain','fileUri':meta['uri']}}]}]}
  record['request']=request;record['request_sha256']=hashlib.sha256(canonical(request)).hexdigest()
  api=GeminiAPI(record['model'],key,client=client)
  result=api.count(request,120)
  record.update(status='PASS',response=result)
  event('token_count_completed',response=result)
 except ModelFailure as exc:
  record.update(status='ERROR',failure_code=exc.code,http_status=exc.status)
 except Exception as exc:
  record.update(status='ERROR',failure_code=type(exc).__name__)
 finally:
  if name:
   response=client.delete(base+'/v1beta/'+name,headers={'x-goog-api-key':key})
   record['uploaded_file_delete_status']=response.status_code
  record['elapsed_seconds']=time.monotonic()-started
  out.write_bytes(canonical(record))
  print(json.dumps({k:record.get(k) for k in ['status','failure_code','http_status','response','corpus_bytes','elapsed_seconds','uploaded_file_delete_status']}))
