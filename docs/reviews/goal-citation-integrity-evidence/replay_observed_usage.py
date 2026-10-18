"""Replay recorded provider bytes through current metering; no network calls."""
import hashlib,json,sys,tarfile
from pathlib import Path
from confirmatory.corpus_export import canonical
from confirmatory.gemini_meter import Journal,MeteredModel,ModelFailure
archive,output=Path(sys.argv[1]),Path(sys.argv[2])
with tarfile.open(archive,'r:gz') as stream:
 events=[json.loads(line) for line in stream.extractfile('citation-pilot-001/graph/events.jsonl').read().splitlines()]
request=next(e['request'] for e in events if e['kind']=='token_count_started')
count=next(e['response'] for e in events if e['kind']=='token_count_completed')
response=next(e['response'] for e in events if e['kind']=='generation_completed')
class Replay:
 model='models/gemini-3.8-flash'
 def count(self,value,timeout):
  assert canonical(value)==canonical(request)
  return count
 def generate(self,value,timeout):
  assert canonical(value)==canonical(request)
  return response
model=MeteredModel(Replay(),Journal(output),generation={'responseMimeType':'application/json'})
try:
 model.ask(request['systemInstruction']['parts'][0]['text'],request['contents'],phase='retrieval')
 raise AssertionError('invalid metering response was accepted')
except ModelFailure as exc:
 assert exc.code=='UNUSABLE_TOKEN_METADATA' and model.usage_unknown and model.output_charged==1000
 result={'classification':'REPLAY_NOT_FRESH_MODEL_RUN','status':'PASS','acceptance_validated':False,
         'source_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
         'original_request_sha256':hashlib.sha256(canonical(request)).hexdigest(),
         'expected_rejection':exc.code,'model_usage':model.summary()}
 model.journal.write_new('result.json',result)
 print(json.dumps(result,sort_keys=True))
