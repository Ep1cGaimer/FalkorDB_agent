"""Capture current development evidence without touching sealed evaluation data."""
import datetime, hashlib, json, os, shutil, subprocess, tarfile
from pathlib import Path

root=Path.cwd()
out=root/'docs/reviews/goal-hackathon-delivery-evidence'
out.mkdir(exist_ok=False)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data): p.write_text(json.dumps(data,indent=2,default=str)+'\n')
qa=root/'artifacts/goal-current-qa/full-003'
pin=json.loads((qa/'source-before.json').read_text())['files']
assert all(digest(root/p)==h for p,h in pin.items())
manifest={'schema':'development-implementation-capture/v1',
          'classification':'198-file working-source pin covered by full-003; not T0 freeze or independent reproduction',
          'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'parent_commit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),
          'base_commit':'d7cf693e26073c825f0b6a2bd741ce5d05752f72','branch':'fix/goal-acceptance',
          'acceptance_validated':False,'files':pin}
write(out/'implementation-manifest.json',manifest)
with tarfile.open(out/'implementation-source.tar.gz','w:gz') as archive:
    for p in sorted(pin): archive.add(root/p,arcname=p)
with (out/'working-source.diff').open('wb') as stream:
    subprocess.run(['git','diff','--binary','HEAD','--','src','tests','evals','scripts','repos','goal.md','pyproject.toml'],stdout=stream,check=True)
shutil.copytree(qa,out/'full-qa-003')
sources={
 'model-protocol-attempts.tar.gz':root/'artifacts/model-protocol-development',
 'os-ingestion-audit.tar.gz':root/'artifacts/goal-ingestion-audit',
 'primary-demo.tar.gz':root/'artifacts/hackathon-demo',
 'unseen-onboarding.tar.gz':root/'artifacts/goal-unseen-onboarding',
}
# Check literal known provider credentials without printing or persisting values.
envfile=Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env')
secrets=[]
if envfile.exists():
    for line in envfile.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1)
            if any(x in k.upper() for x in ['KEY','TOKEN','SECRET']):
                v=v.strip().strip('"').strip("'")
                if len(v)>=12: secrets.append(v.encode())
for target,source in sources.items():
    for p in source.rglob('*'):
        if p.is_file():
            data=p.read_bytes()
            if any(value in data for value in secrets): raise RuntimeError('Credential found in '+str(p.relative_to(root)))
    with tarfile.open(out/target,'w:gz') as archive: archive.add(source,arcname=str(source.relative_to(root)))
write(out/'run-summary.json',{
 'classification':'HACKATHON_PRIMARY_AND_SECONDARY_DEVELOPMENT_EVIDENCE_NOT_FULL_ACCEPTANCE',
 'full_acceptance_validated':False,'heldout_questions_run':0,
 'primary':{'supported_deterministic_demo':'PASS','browser_rehearsals':3,'recorded_replay':'explicitly labeled',
            'fixed_port_recovery':'PASS after preserved port reassignment failure','demo_url':'http://localhost:8127'},
 'full_qa':{'passed':1234,'skipped':6,'live_excluded':3,'seconds':247.92,'source_files':198,'source_mismatches':[]},
 'native_model_development':{'native_decision_tests':13,'combined_continuation_regressions_passed':82,
            'accepted_end_to_end_answers':0,'latest_plaintext':'MODEL_INPUT_BUDGET_EXHAUSTED','latest_graph':'PROVIDER_HTTP_ERROR',
            'usage':'Actual token metadata enforced; no hidden retries or provider fallback'},
 'ingestion_audit':{'run':'run-004','status':'PASS in scoped synthetic Linux strace audit',
            'positive_control_execution_write_network':True,'unauthorized_execution_write_network':0,
            'prior_failed_harness_attempts_retained':3,'full_T8_validated':False},
 'unseen_onboarding':{'repository':'Click','status':'COMPLETE','selected_roots':5,'commits':2855,
            'seconds':41.140813851998246,'core_changes_for_trial':0,'full_T1_validated':False},
 'limitations':['No signed frozen T0','No held-out answers/quality run','No T10 effect or confidence intervals',
            'T3/T4/T5/T6/T7/T8/T9 complete matrices remain unvalidated','No independent current full bundle reproduction',
            'No official event rules supplied; no submission or video claimed','Working changes remain uncommitted; handoff commit canceled']})
write(out/'bundle-manifest.json',{'schema':'development-evidence-bundle/v1','acceptance_validated':False,
      'files':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
print(json.dumps({'output':str(out.relative_to(root)),'source_files':len(pin),'files':len(json.loads((out/'bundle-manifest.json').read_text())['files'])}))
