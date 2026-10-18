"""Preserve all quality attempts and current source; never promote development results to acceptance."""
import datetime,hashlib,json,os,shutil,subprocess,tarfile
from pathlib import Path
root=Path.cwd(); raw=root/'artifacts/goal-quality-flash-lite'
out=root/'docs/reviews/goal-citation-support-evidence';out.mkdir(exist_ok=False)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
assert (raw/'run-006-numbered-reserve/summary.json').exists()
assert (raw/'independent-review-003.json').exists()
base=json.loads((root/'artifacts/goal-source-preflight/implementation-manifest.json').read_text())['files']
files={p:digest(root/p) for p in sorted(set(base)|{'evals/confirmatory/paired_scores.py','tests/test_confirmatory_paired_scores.py','evals/confirmatory/claim_support.py','tests/test_confirmatory_claim_support.py'})}
assert all(digest(root/p)==h for p,h in base.items() if p.startswith('src/'))
write(raw/'endpoint-preservation-final.json',{'application_source_mismatches':[],
 'changed_existing_files_since_full004':[p for p,h in base.items() if digest(root/p)!=h],
 'test_model':'models/gemini-3.1-flash-lite','application_endpoint_mutations':0,
 'model_selection_scope':'Test process only; no application model settings or env files changed',
 'no_commit_or_push':True})
write(raw/'unrun-prototype.json',{'script':'run_quality_bounded_answer.py','status':'NOT_RUN',
 'explanation':'Earlier controller prototype was never executed; graph use and finish remain agent choices.'})
records=[]
for folder in sorted(p for p in raw.iterdir() if p.is_dir() and p.name.startswith('run-')):
 summary=folder/'summary.json'
 rows=[]
 for p in sorted(folder.glob('*/result.json')):
  r=json.loads(p.read_text());rows.append({'case_arm':p.parent.name,'result_path':str(p.relative_to(root)),
   'status':r['status'],'failure':r['failure'],'answer_generated':r['answer'] is not None,
   'usage':r['model_usage'],'reference_integrity':r.get('citation_reference_validation')})
 records.append({'attempt_version':folder.name,'summary':json.loads(summary.read_text()) if summary.exists() else None,
  'completed_result_files':rows,'unfinished_cells_are_not_passes':True})
write(out/'scorecard.json',{'schema':'focused-development-quality-attempt-ledger/v1',
 'classification':'Four distinct development scenarios; protocol/budget/prompt versions separate; not confirmatory',
 'acceptance_validated':False,'advantage_validated':False,'model':'models/gemini-3.1-flash-lite',
 'attempts':records,'support_calibrations':[{'version':p.parent.name,'summary':json.loads(p.read_text())} for p in sorted(raw.glob('support-calibration-*/summary.json'))],'independent_reviews':[str((raw/'independent-review-001.json').relative_to(root)),str((raw/'independent-review-002.json').relative_to(root)),str((raw/'independent-review-003.json').relative_to(root))],
 'limitations':['Nonblind source review; development oracle and repairs informed by development failures.',
 'No pooled win rate across different protocols/budgets/prompts; no three-repeat paired comparison.',
 'Valid reference identity does not establish correct material claims or supporting spans.',
 'Full T0–T11 requirements remain incomplete.']})
write(out/'implementation-manifest.json',{'schema':'working-source-files/v1','classification':'203 current paths; application src unchanged from 199-file full004; later evaluation-only calling/prompt and test/doc changes',
 'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'acceptance_validated':False,'files':files})
# Fail closed if any available credential value occurs in prospective quality artifacts.
from rw.config import load_env
load_env(Path('/Users/vinay2047/Documents/github/FalkorDB_agent/.env'))
secrets=[v.encode() for k,v in os.environ.items() if len(v)>=12 and any(s in k.upper() for s in ('API_KEY','SECRET','PASSWORD','ACCESS_TOKEN'))]
for p in raw.rglob('*'):
 if p.is_file() and any(value in p.read_bytes() for value in secrets):
  raise RuntimeError('Credential literal detected; archive not created')
with tarfile.open(out/'all-quality-attempts.tar.gz','w:gz') as archive:archive.add(raw,arcname='artifacts/goal-quality-flash-lite')
with tarfile.open(out/'implementation-source.tar.gz','w:gz') as archive:
 for p in files:archive.add(root/p,arcname=p)
for name in ['quality-followup-red.xml','quality-followup-green.xml','quality-typed-tools-red.xml','quality-typed-tools-green.xml','quality-typed-tools-final.xml','goal-paired-score-checks.xml','quality-answer-reserve-red.xml','quality-answer-reserve-green.xml','quality-answer-reserve-final.xml','quality-claim-support-component.xml','quality-claim-support-final.xml']:
 p=root/'artifacts'/name
 if p.exists():shutil.copy2(p,out/name)
for name in ['goal-flash-lite-quality-review.md','goal-flash-lite-agent-repair-review.md','goal-flash-lite-agent-repair.md','goal-paired-scoring-tooling.md','goal-citation-support-repair.md','goal-citation-support-repair-review.md']:
 p=root/'docs/reviews'/name
 if p.exists():shutil.copy2(p,out/name)
shutil.copy2(Path(__file__),out/'finalize.py')
write(out/'bundle-manifest.json',{'schema':'development-evidence-files/v1','acceptance_validated':False,
 'files':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
ledger=root/'docs/reviews/goal-acceptance-ledger.json';data=json.loads(ledger.read_text())
run='goal-numbered-source-and-final-answer-reserve-2026-10-18'
manifest=str((out/'implementation-manifest.json').relative_to(root));bundle=str((out/'bundle-manifest.json').relative_to(root));score=str((out/'scorecard.json').relative_to(root))
for entry in data['entries']:
 assert entry['status']=='IN_PROGRESS'
 entry['implementation_ref'].update(source_manifest=manifest,source_manifest_sha256=digest(root/manifest),
  classification='203-file current source; application unchanged since full004; later evaluation-only repair separately tested')
 if run not in entry['run_ids']:entry['run_ids'].append(run)
 for link in [manifest,bundle,score,'docs/reviews/goal-citation-support-repair.md','docs/reviews/goal-citation-support-repair-review.md']:
  if link not in entry['artifact_links']:entry['artifact_links'].append(link)
 if entry['requirement_id'] in {'T0','T2','T7','T9','T10','T11','E2','E4','E5','S2','S5'}:
  entry['observed_metrics']['latest_focused_flash_lite_quality']={'scorecard':score,'independent_nonblind_review':'docs/reviews/goal-citation-support-repair-review.md',
   'four_distinct_development_cases':True,'heldout':False,'full_acceptance':False,'graph_optional':True,'application_endpoint_mutations':0}
  entry['limitations'].append('Focused Gemini3.1FlashLite development quality and optional typed-tool repair do not replace 120 independent questions/three repeats/blind grading. Original budget, ambiguity and material citation failures retained.')
data['run_history'][run]={'artifact':score,'classification':'Development quality; all failures retained; optional typed-tool prompt/calling repair; no acceptance or statistical advantage claim'}
data['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();write(ledger,data)
integrity=root/'docs/reviews/goal-evidence-integrity.json';i=json.loads(integrity.read_text());names=[x['manifest'] for x in i['artifact_manifests']]
if bundle not in names:names.append(bundle)
i['artifact_manifests']=[]
for name in names:
 p=root/name;entries=json.loads(p.read_text())['files']
 bad=[q for q,h in entries.items() if not (p.parent/q).is_file() or digest(p.parent/q)!=h]
 i['artifact_manifests'].append({'manifest':name,'files':len(entries),'mismatches':bad})
i.update(current_source_manifest=manifest,current_source_files=len(files),current_source_mismatches=[p for p,h in files.items() if digest(root/p)!=h],
 ledger_missing_links=sorted({p for e in data['entries'] for p in e['artifact_links'] if not (root/p).exists()}),
 unresolved_run_ids=sorted({s for e in data['entries'] for s in e['run_ids'] if s not in data['run_history']}),
 checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
i['errors']=[x for x in i['artifact_manifests'] if x['mismatches']];write(integrity,i)
assert not i['errors'] and not i['current_source_mismatches'] and not i['ledger_missing_links'] and not i['unresolved_run_ids']
print(json.dumps({'integrity':'PASS','current_source_files':len(files),'quality_attempt_versions':len(records),'acceptance_validated':False}))
