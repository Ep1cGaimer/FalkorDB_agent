"""Record verified delivery state without promoting partial evidence to acceptance."""
import datetime,hashlib,json,shutil
from pathlib import Path
root=Path.cwd();folder=root/'docs/reviews/goal-final-delivery-evidence';folder.mkdir(exist_ok=False)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
source=root/'docs/reviews/goal-citation-support-evidence/implementation-manifest.json'
pin=json.loads(source.read_text())['files']
assert not [p for p,h in pin.items() if digest(root/p)!=h]
copy={
 'final-status.md':'docs/reviews/goal-final-status.md',
 'contract-final-readiness.md':'docs/reviews/goal-contract-final-readiness.md',
 'review.readiness-v3.json':'evals/confirmatory/review.readiness-v3.json',
 'implementation-manifest.json':str(source.relative_to(root)),
 'live-endpoint-check.json':'artifacts/goal-quality-flash-lite/final-live-endpoint-check.json'}
for target,p in copy.items():shutil.copy2(root/p,folder/target)
shutil.copytree(root/'artifacts/goal-contract-readiness/token-counts-001',folder/'token-counts-001')
summary={'schema':'goal-delivery-current-state/v1','recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'primary':'Supported scoped deterministic demo ready; source/browser/rehearsal limits in docs/demo/STATUS.md',
 'latest_requested_deadline':'20:30IST plus subsequent5minute wrapup; full secondary remains unfinished',
 'complete_goal_achieved':False,'full_acceptance_validated':False,'all_T0_T11_status':'IN_PROGRESS',
 'live_endpoint':json.loads((folder/'live-endpoint-check.json').read_text()),
 'current_source_files':len(pin),'current_source_mismatches':[],
 'full_application_qa':{'pin_files':199,'passed':1244,'skipped':6,'live_excluded':3,'later_eval_changes_have_separate_checks':True},
 'later_eval_checks':{'affected_passed':133,'claim_support_component_passed':5,'not_full_suite':True},
 'quality':'Nonblind development findings only; multi-hop/ambiguity graph finals pass; static main spans repaired with smaller omissions retained; semantic reviewer fallible',
 'token_counts':json.loads((folder/'token-counts-001/summary.json').read_text()),
 'independent_readiness':'Unsigned; concrete remaining contract/scoring/isolation requirements in review.readiness-v3.json',
 'application_source_endpoints_and_model_settings_changed_in_latest_eval_work':False,
 'commit_or_push':False,'working_source_committed':False}
write(folder/'summary.json',summary)
shutil.copy2(Path(__file__),folder/'finalize_delivery.py')
write(folder/'bundle-manifest.json',{'schema':'development-evidence-files/v1','acceptance_validated':False,
 'files':{str(p.relative_to(folder)):digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}})
ledger=root/'docs/reviews/goal-acceptance-ledger.json';data=json.loads(ledger.read_text())
run='goal-final-delivery-and-exact-corpus-readiness-2026-10-18'
links=['docs/reviews/goal-final-status.md','docs/reviews/goal-contract-final-readiness.md',
 'evals/confirmatory/review.readiness-v3.json',str((folder/'summary.json').relative_to(root)),str((folder/'bundle-manifest.json').relative_to(root))]
for e in data['entries']:
 assert e['status']=='IN_PROGRESS'
 if run not in e['run_ids']:e['run_ids'].append(run)
 for p in links:
  if p not in e['artifact_links']:e['artifact_links'].append(p)
 if e['requirement_id'] in {'T0','T10','T6','E3','E4'}:
  e['observed_metrics']['candidate_exact_flash_lite_corpus_counts']={
   'requests':23642588,'click':24111700,'model':'models/gemini-3.1-flash-lite','full_context':1048576,
   'payloads':'Five-root factored direct serializations, pinned bytes/hash; no fixed prompts included',
   'temporary_uploaded_files_deleted_http':200,'actual_billing':'UNVERIFIED','advantage_validated':False}
 if e['requirement_id'] in {'T0','T2','T11','E5'}:
  e['observed_metrics']['final_public_readiness_review']='Unsigned;20publichashes and203sourcepins verified; no question/oracle opened; retrieval scoring must precede final generation, locking alone is insufficient.'
data['run_history'][run]={'artifact':links[3],'classification':'Delivery/scopedQA and exact-model corpus counts; full goal and every full acceptance gate incomplete'}
data['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();write(ledger,data)
p=root/'docs/reviews/goal-evidence-integrity.json';i=json.loads(p.read_text());names=[x['manifest'] for x in i['artifact_manifests']]
new=links[4]
if new not in names:names.append(new)
i['artifact_manifests']=[]
for name in names:
 m=root/name;files=json.loads(m.read_text())['files'];bad=[q for q,h in files.items() if not (m.parent/q).is_file() or digest(m.parent/q)!=h]
 i['artifact_manifests'].append({'manifest':name,'files':len(files),'mismatches':bad})
i.update(current_source_mismatches=[p for p,h in pin.items() if digest(root/p)!=h],
 ledger_missing_links=sorted({p for e in data['entries'] for p in e['artifact_links'] if not (root/p).exists()}),
 unresolved_run_ids=sorted({s for e in data['entries'] for s in e['run_ids'] if s not in data['run_history']}),
 checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
i['errors']=[x for x in i['artifact_manifests'] if x['mismatches']];write(p,i)
assert not i['errors'] and not i['current_source_mismatches'] and not i['ledger_missing_links'] and not i['unresolved_run_ids']
print(json.dumps({'integrity':'PASS','full_goal_achieved':False,'current_source_files':len(pin),'bundle':str(folder.relative_to(root))}))
