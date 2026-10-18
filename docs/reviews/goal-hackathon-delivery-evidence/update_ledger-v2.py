import datetime, hashlib, json, shutil
from pathlib import Path
root=Path.cwd()
folder=root/'docs/reviews/goal-hackathon-delivery-evidence'
shutil.copy2(root/'artifacts/goal-hackathon-delivery/curate.py',folder/'curate.py')
shutil.copy2(Path(__file__),folder/'update_ledger-v2.py')
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data): p.write_text(json.dumps(data,indent=2)+'\n')
manifest='docs/reviews/goal-hackathon-delivery-evidence/implementation-manifest.json'
summary='docs/reviews/goal-hackathon-delivery-evidence/run-summary.json'
bundle='docs/reviews/goal-hackathon-delivery-evidence/bundle-manifest-v3.json'
write(root/bundle,{'schema':'development-evidence-files/v1','acceptance_validated':False,
      'classification':'v3 uses the existing run_history registry; earlier manifests and drivers retained',
      'files':{str(p.relative_to(folder)):digest(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='bundle-manifest-v3.json'}})
ledger_path=root/'docs/reviews/goal-acceptance-ledger.json'
r=json.loads(ledger_path.read_text())
r['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
run='goal-hackathon-primary-secondary-development-2026-10-18'
for e in r['entries']:
    assert e['status']=='IN_PROGRESS'
    e['implementation_ref'].update(source_manifest=manifest,source_manifest_sha256=digest(root/manifest),
        classification='198-file full-003 working-source pin; not final signed T0 implementation freeze')
    if run not in e['run_ids']:e['run_ids'].append(run)
    for p in ['docs/reviews/goal-hackathon-delivery.md',bundle,manifest,summary]:
        if p not in e['artifact_links']:e['artifact_links'].append(p)
    e['observed_metrics']['current_working_source_full_qa']={'passed':1234,'failed':0,'errors':0,'skipped':6,
        'live_excluded':3,'seconds':247.92,'source_files_checked':198,'source_mismatches':[],
        'independent':False,'heldout_quality':False,'run':'full-003'}
    key=e['requirement_id']
    if key in ['T1','S1','E1']:
        e['observed_metrics']['unseen_click_config_only_trial']={'status':'COMPLETE','commits':2855,
            'blobs_new':2374,'roots_verified':5,'seconds':41.140813851998246,'core_changes':0,
            'source_mismatches':[],'generated_answers':False,'full_T1_validated':False}
    if key in ['T8','S6','E5']:
        e['observed_metrics']['os_ingestion_audit']={'status':'PASS_SCOPED_SYNTHETIC','run':'run-004',
            'trace_lines':4258,'positive_execution_write_network_control':True,
            'unexpected_execution_write_network_or_escape':0,'full_T8_validated':False}
    if key in ['T2','T10','E4']:
        e['observed_metrics']['native_provider_development']={'accepted_answers':0,
            'latest_plaintext_failure':'MODEL_INPUT_BUDGET_EXHAUSTED','latest_graph_failure':'PROVIDER_HTTP_ERROR',
            'confirmatory_runs':0,'scoring':'NOT_RUN'}
    if key in ['T11','S5','E1','E5']:
        e['observed_metrics']['primary_demo']={'supported_deterministic_flow':'PASS','browser_rehearsals':3,
            'outage_replay_live_recovery':'PASS_AFTER_FIXED_PORT_REPAIR','full_T11_demo':False,'human_narration':False}
r.setdefault('run_history',{})[run]={'artifact':summary,'classification':'Primary deterministic demo and scoped secondary QA/onboarding/audit development; no full gate pass'}
r.pop('runs',None)
write(ledger_path,r)

# Refresh byte/link integrity only. Historical source captures remain historical.
integrity=json.loads((root/'docs/reviews/goal-evidence-integrity.json').read_text())
manifests=[x['manifest'] for x in integrity['artifact_manifests']]
if bundle not in manifests:manifests.append(bundle)
integrity['artifact_manifests']=[]
for name in manifests:
    p=root/name; values=json.loads(p.read_text())['files']; mismatches=[]
    for rel,h in values.items():
        target=p.parent/rel
        if not target.is_file() or digest(target)!=h:mismatches.append(rel)
    integrity['artifact_manifests'].append({'manifest':name,'files':len(values),'mismatches':mismatches})
files=json.loads((root/manifest).read_text())['files']
integrity.update(current_source_manifest=manifest,current_source_files=len(files),
    current_source_mismatches=[p for p,h in files.items() if not (root/p).is_file() or digest(root/p)!=h],
    ledger_missing_links=sorted({p for e in r['entries'] for p in e['artifact_links'] if not (root/p).exists()}),
    checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
integrity['errors']=[x for x in integrity['artifact_manifests'] if x['mismatches']]
write(root/'docs/reviews/goal-evidence-integrity.json',integrity)
assert not integrity['errors'] and not integrity['current_source_mismatches'] and not integrity['ledger_missing_links']
print(json.dumps({'current_source_files':len(files),'bundle_files':len(json.loads((root/bundle).read_text())['files']),
                  'integrity':'PASS','acceptance_validated':False,'statuses':sorted({e['status'] for e in r['entries']})}))
