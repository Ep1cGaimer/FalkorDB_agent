"""Capture the repaired build and scoped secondary evidence, retaining old bundles."""
import datetime,gzip,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
root=Path.cwd();out=root/'docs/reviews/goal-source-budget-evidence';out.mkdir(exist_ok=False)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,r):p.write_text(json.dumps(r,indent=2,default=str)+'\n')
pin=json.loads((root/'artifacts/goal-source-preflight/implementation-manifest.json').read_text())
assert all(digest(root/p)==h for p,h in pin['files'].items())
pin['classification']='199-file source-byte repair;full0041234+10passed;independent8casepreflight;not signedT0'
pin['recorded_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
write(out/'implementation-manifest.json',pin)
with tarfile.open(out/'implementation-source.tar.gz','w:gz') as archive:
    for p in sorted(pin['files']):archive.add(root/p,arcname=p)
shutil.copytree(root/'artifacts/goal-current-qa/full-004',out/'full-qa-004')
for p in root.glob('artifacts/goal-source-preflight-*.xml'):shutil.copy2(p,out/p.name)
shutil.copy2(root/'artifacts/goal-source-preflight/demo-recheck.json',out/'demo-recheck.json')
shutil.copy2(Path(__file__),out/'curate.py')
sources={
 'index-recovery.tar.gz':'artifacts/goal-index-recovery',
 'bounded-retrieval-all-attempts.tar.gz':'artifacts/goal-bounded-retrieval-audit',
 'fresh-flask-onboarding.tar.gz':'artifacts/goal-fresh-onboarding-199',
 'contract-readiness.tar.gz':'artifacts/goal-contract-readiness',
}
for name,source in sources.items():
    with tarfile.open(out/name,'w:gz') as archive:
        def keep(info):
            # Existing repositories.tar.gz / flask-bare.git.tar.gz preserve exact Git data.
            return None if info.isdir() and Path(info.name).name in {'repositories','repository','flask.git','__pycache__'} else info
        archive.add(root/source,arcname=source,filter=keep)
for rel in ['docs/reviews/goal-index-recovery.md','docs/reviews/goal-bounded-retrieval-audit.md',
            'docs/reviews/goal-bounded-retrieval-source-revalidation.md','docs/reviews/goal-source-budget-repair.md']:
    shutil.copy2(root/rel,out/Path(rel).name)
with (out/'working-source.diff').open('wb') as stream:
    subprocess.run(['git','diff','--binary','HEAD','--','src','tests','evals','scripts','repos','goal.md','pyproject.toml'],stdout=stream,check=True)
write(out/'summary.json',{'classification':'CURRENT_SOURCE_BUDGET_REPAIR_AND_SCOPED_SECONDARY_EVIDENCE',
 'acceptance_validated':False,'primary_deadline':'Supported scoped demo ready before18:45 IST',
 'secondary_deadline':'Missed19:30 IST;fullacceptance remains required',
 'current_qa':{'passed':1244,'failed':0,'errors':0,'skipped':6,'live_excluded':3,'seconds':250.75,'source_files':199,'source_mismatches':[]},
 'source_preflight':{'red_failures':5,'red_passes':2,'final_targeted_passes':10,'independent_passes':8,'oversized_payload_bytes_after_repair':0},
 'flask_onboarding':json.loads((root/'artifacts/goal-fresh-onboarding-199/summary.json').read_text()),
 'historical198_index_recovery':{'fresh_trial_passes':275,'supplement_passes':9,'fault_trials':52,'actual_mutating_write_boundaries':21,'full_T4_validated':False},
 'historical198_bounded_retrieval':{'distinct_passes':38,'source_byte_fail':'159984>1 retained then independently revalidated on199','fullproductionunion':'INTERRUPTED_NOT_COMPLETE','full_T5_validated':False},
 'corpus_readiness':'Two five-root raw corpora prepared;exactmodeltokens/signature pending;noquestion/oracle read',
 'heldout_questions_run':0,'advantage_validated':False,'working_source_committed':False})
write(out/'bundle-manifest.json',{'schema':'development-evidence-files/v1','acceptance_validated':False,
 'files':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
print(json.dumps({'output':str(out.relative_to(root)),'files':len(json.loads((out/'bundle-manifest.json').read_text())['files']),'source_files':len(pin['files'])}))
