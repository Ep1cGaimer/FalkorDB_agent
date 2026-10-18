import datetime,hashlib,json
from pathlib import Path
root=Path.cwd();bundle='docs/reviews/goal-citation-integrity-evidence';directory=root/bundle
manifest_path=bundle+'/implementation-manifest-v2.json'
manifest_sha=hashlib.sha256((root/manifest_path).read_bytes()).hexdigest()
qa=json.loads((directory/'full-qa-002/summary.json').read_text())
ledger_path=root/'docs/reviews/goal-acceptance-ledger.json'
ledger=json.loads(ledger_path.read_text());ledger['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
new_qa={'passed':1213,'failed':0,'errors':0,'skipped':6,'live_deselected':3,'seconds':246.32,
 'realrepo_flags_enabled':True,'source_files_before_after':192,'source_mismatches':0,'independent':False,
 'heldout_questions_run':0,'artifact':bundle+'/full-qa-002/summary.json',
 'classification':'development full-002;subsequent2 meter/test changes have71 separate checks+recorded-byte replay;not full acceptance'}
counts={n:json.loads((directory/'direct-context'/(n+'-provider-count-001.json')).read_text()) for n in ['requests','itsdangerous']}
newcounts={n:{'tokens':r['response']['totalTokens'],'context_sha256':r['context_sha256'],'corpus_sha256':r['corpus_sha256'],'model':r['model'],'artifact':bundle+'/direct-context/'+n+'-provider-count-001.json'} for n,r in counts.items()}
newrefs={'scope':'reference identity/retrieval membership only;semantic grounding UNSCORED', 'focused_tests_passed':75,
 'real_development_references':{'requests':11,'itsdangerous':9},'real_model_pilot':{'plaintext':'PROVIDER_TIMEOUT','graph':'MODEL_RESPONSE_INCOMPLETE/MALFORMED_FUNCTION_CALL','accepted_answers':0},
 'usage_followup':{'red_failures':4,'fixed_checks':71,'recorded_byte_replay':'PASS;not live','original_graph_output_completeness_flag':'UNRELIABLE'},'acceptance_validated':False}
run_id='goal-citation-integrity-development-2026-10-18'
for entry in ledger['entries']:
 assert entry['status']=='IN_PROGRESS' and entry['validated_at'] is None
 ref=entry['implementation_ref'];ref.update(source_manifest=manifest_path,source_manifest_sha256=manifest_sha,commit=None,
 classification='194-file current development capture v2;192-file full-002 plus2 new direct-context files and2 later meter/test edits;no final T0 pin')
 if run_id not in entry['run_ids']:entry['run_ids'].append(run_id)
 for p in ['docs/reviews/goal-citation-integrity.md','docs/reviews/goal-direct-context.md',bundle+'/bundle-manifest.json',manifest_path,bundle+'/full-qa-002/summary.json',bundle+'/usage-followup.json']:
  if p not in entry['artifact_links']:entry['artifact_links'].append(p)
 entry['observed_metrics']['latest_parent_full_qa']=new_qa
 entry['observed_metrics']['reference_integrity_development']=newrefs
 if entry['requirement_id'] in {'T0','T6','T10','T11','S4','E3','E4','E5'}:
  entry['observed_metrics']['compact_context_provider_counts']=newcounts
 entry['limitations']=[('Historical earlier batch: '+s) if s.startswith(('Latest full parent QA passed1172','Entire ItsDangerous development JSONL')) else s for s in entry['limitations']]
 limitation='Current citation/reference checks are not material-claim scoring. Latest full-002 passed1213 with6 required evidence skips/3 live exclusions on192 hashes;2 later meter/test edits passed71 separate checks+exact-response replay. Compact development counts succeeded but final Requests/Click protocol remains unsigned. Both fresh model-arm attempts failed; output usage from the malformed graph response is unknown. No acceptance or advantage validation.'
 if limitation not in entry['limitations']:entry['limitations'].append(limitation)
ledger['run_history'][run_id]={'artifact':bundle+'/bundle-manifest.json','classification':'development reference/lock/empty-file repairs,full-002,compact corpus counts,failed model attempts and metering replay;not acceptance'}
ledger_path.write_text(json.dumps(ledger,indent=2)+'\n')
print(json.dumps({'entries':len(ledger['entries']),'statuses':sorted(set(e['status'] for e in ledger['entries'])),'source_manifest':manifest_path}))
