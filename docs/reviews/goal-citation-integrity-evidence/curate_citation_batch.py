import datetime,gzip,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
root=Path.cwd(); out=root/'docs/reviews/goal-citation-integrity-evidence';out.mkdir(exist_ok=False)
def copy(source, dest):
 p=out/dest;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/source,p)
for pattern in ['goal-citation*.xml','goal-empty-source*.xml','goal-direct-context-tests-*.xml']:
 for p in (root/'artifacts').glob(pattern):copy(p.relative_to(root),'tests/'+p.name)
for p in (root/'artifacts/goal-current-qa/full-002').iterdir():
 if p.is_file():copy(p.relative_to(root),'full-qa-002/'+p.name)
copy('artifacts/goal-current-qa/run-002.py','full-qa-002/run.py')
for source in ['run-current-pilot.py','probe_current_references.py','probe_native_none.py','native-none-probe-001.json']:
 copy('artifacts/model-development/'+source,source)
for name in ['citation-pilot-001','real-reference-probes-001']:
 with tarfile.open(out/(name+'.tar.gz'),'w:gz') as archive:
  archive.add(root/'artifacts/model-development'/name,arcname=name)
for name in ['itsdangerous','requests']:
 directory='artifacts/corpus-development/'+name+'-direct-context-001'
 for f in ['receipt.json','provider-count-001.json']:copy(directory+'/'+f,'direct-context/'+name+'-'+f)
 with (root/directory/'context.txt').open('rb') as source,(out/'direct-context'/ (name+'-context.txt.gz')).open('wb') as dest:
  with gzip.GzipFile(fileobj=dest,mode='wb',mtime=0) as compressed:shutil.copyfileobj(source,compressed)
 for_doc=json.loads((root/directory/'receipt.json').read_text())
 with gzip.open(out/'direct-context'/(name+'-context.txt.gz'),'rb') as compressed:
  assert hashlib.sha256(compressed.read()).hexdigest()==for_doc['context_sha256']
for f in ['count_direct_context.py','count_requests_direct_context.py']:
 copy('artifacts/corpus-development/'+f,'direct-context/'+f)
qa=json.loads((out/'full-qa-002/source-before.json').read_text())['files']
for p,h in qa.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==h,p
paths=set(qa)|{'evals/confirmatory/direct_context.py','tests/test_confirmatory_direct_context.py'}
manifest={'schema':'development-implementation-capture/v1','base_commit':'d7cf693e26073c825f0b6a2bd741ce5d05752f72','parent_commit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),'branch':subprocess.check_output(['git','branch','--show-current']).decode().strip(),'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'classification':'post-run working-source capture;192-file full parent QA plus2 separately tested direct-context files;not T0 freeze','acceptance_validated':False,'files':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sorted(paths)}}
(out/'implementation-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with tarfile.open(out/'source-snapshot.tar.gz','w:gz') as archive:
 for p in sorted(paths):
  assert 'sealed' not in Path(p).parts and (Path(p).name=='.env.example' or not Path(p).name.startswith('.env'))
  archive.add(root/p,arcname=p)
summary={'schema':'development-citation-batch/v1','acceptance_validated':False,'heldout_questions_run':0,'full_qa':json.loads((out/'full-qa-002/summary.json').read_text()),'current_source_files':len(paths),'separately_tested_direct_context':{'tests':3,'failures':0},'direct_context_counts':{n:json.loads((out/'direct-context'/(n+'-provider-count-001.json')).read_text()) for n in ['requests','itsdangerous']},'live_attempts':{n:json.loads((root/'artifacts/model-development/citation-pilot-001'/n/'result.json').read_text()) for n in ['plaintext','graph']},'real_references':json.loads((root/'artifacts/model-development/real-reference-probes-001/summary.json').read_text())}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
(out/'bundle-manifest.json').write_text(json.dumps({'schema':'development-evidence-files/v1','acceptance_validated':False,'files':files},indent=2)+'\n')
print(json.dumps({'evidence_files':len(files),'source_files':len(paths),'new_bundle':str(out.relative_to(root))}))
