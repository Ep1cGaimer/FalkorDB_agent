import datetime,hashlib,json,shutil,tarfile
from pathlib import Path
root=Path.cwd();out=root/'docs/reviews/goal-citation-integrity-evidence'
for f in ['goal-usage-visible-output-red-001.xml','goal-usage-visible-output-fixed-001.xml']:
 shutil.copyfile(root/'artifacts'/f,out/'tests'/f)
shutil.copytree(root/'artifacts/model-development/replay-current-usage-001',out/'replay-current-usage-001')
shutil.copyfile(root/'artifacts/model-development/replay_observed_usage.py',out/'replay_observed_usage.py')
manifest=json.loads((out/'implementation-manifest.json').read_text())
original=dict(manifest['files'])
manifest['files']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in manifest['files']}
manifest['recorded_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
manifest['classification']='post-run working-source capture v2;full-002 pin retained;2 later meter/test changes have71 affected checks plus exact-response replay;not T0 freeze'
manifest['changes_since_full_batch_capture']=[p for p in original if original[p]!=manifest['files'][p]]
assert set(manifest['changes_since_full_batch_capture'])=={'evals/confirmatory/gemini_meter.py','tests/test_confirmatory_model_meter.py'}
(out/'implementation-manifest-v2.json').write_text(json.dumps(manifest,indent=2)+'\n')
with tarfile.open(out/'source-snapshot-v2.tar.gz','w:gz') as archive:
 for p in manifest['files']:archive.add(root/p,arcname=p)
summary={'classification':'DEVELOPMENT_METER_FIDELITY_FOLLOWUP','acceptance_validated':False,'new_live_model_calls':0,'red_tests':4,'fixed_affected_tests':71,'changed_files':manifest['changes_since_full_batch_capture'],'replay':json.loads((out/'replay-current-usage-001/result.json').read_text()),'limitation':'Not a successful investigation, complete cost accounting, or full-suite run on the follow-up source'}
(out/'usage-followup.json').write_text(json.dumps(summary,indent=2)+'\n')
files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='bundle-manifest.json'}
(out/'bundle-manifest.json').write_text(json.dumps({'schema':'development-evidence-files/v1','acceptance_validated':False,'files':files},indent=2)+'\n')
print(json.dumps({'files':len(files),'changed_source_files':manifest['changes_since_full_batch_capture']}))
