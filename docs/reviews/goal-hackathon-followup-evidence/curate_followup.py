import datetime, hashlib, json, shutil, tarfile
from pathlib import Path
root=Path.cwd();out=root/'docs/reviews/goal-hackathon-followup-evidence';out.mkdir(exist_ok=False)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,r):p.write_text(json.dumps(r,indent=2)+'\n')
shutil.copy2(Path(__file__),out/'curate_followup.py')
for name,source in {
 'independent-history-100.tar.gz':'artifacts/goal-history-oracle',
 'independent-history-matrix.tar.gz':'artifacts/goal-history-oracle-matrix',
 'native-provider-003.tar.gz':'artifacts/model-protocol-development/native-pilot-003',
 'current-transports-003.tar.gz':'artifacts/repo_probes/goal-current-transport-003',
}.items():
    with tarfile.open(out/name,'w:gz') as archive:
        def include(info):
            return None if info.name.endswith('/repositories') and info.isdir() else info
        archive.add(root/source,arcname=source,filter=include)
for rel in ['docs/reviews/goal-history-oracle.md','docs/reviews/goal-history-oracle-matrix.md']:
    shutil.copy2(root/rel,out/Path(rel).name)
native=root/'artifacts/model-protocol-development/run_native_pilot_003.py'
shutil.copy2(native,out/native.name)
for rel in ['docs/demo/HACKATHON.md','docs/demo/STATUS.md','docs/demo/CLAIMS.md','docs/demo/TALK_TRACK.md']:
    target=out/'presentation'/Path(rel).name;target.parent.mkdir(exist_ok=True);shutil.copy2(root/rel,target)
pin=json.loads((root/'docs/reviews/goal-hackathon-delivery-evidence/implementation-manifest.json').read_text())
mismatch=[p for p,h in pin['files'].items() if digest(root/p)!=h];assert not mismatch
matrix=json.loads((root/'artifacts/goal-history-oracle-matrix/results.json').read_text())
transport=json.loads((root/'artifacts/repo_probes/goal-current-transport-003/record.json').read_text())
summary={'classification':'SCOPED_SECONDARY_DEVELOPMENT_AND_INDEPENDENT_SYNTHETIC_EVIDENCE_NOT_ACCEPTANCE',
 'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'acceptance_validated':False,
 'source_manifest':'docs/reviews/goal-hackathon-delivery-evidence/implementation-manifest.json',
 'source_files_checked':len(pin['files']),'source_mismatches':mismatch,
 'seeded_history':{'seeds':100,'checks_passed':10800,'checks_total':10800,'citation_checks_passed':5400,
      'citation_checks_total':5400,'seconds':96.623,'independent_AI_author':'/root/history_oracle_check','full_T3_validated':False},
 'additional_history_matrix':{'checks_passed':101,'checks_total':105,'raw_mismatches':matrix['failures'],
      'zero_false_PRESENT':True,'normalized_introduction_identity_replay':'14/14; original alias failure retained',
      'limits':'Conservative UNCERTAIN vs ABSENT disagreements; sampled introduction; broader matrices/T2 remain pending'},
 'current_transports':{'exact_semantic_matches':sum(x['exact_semantic_parity'] for x in transport['transports']),
      'total':len(transport['transports']),'malformed_inputs_rejected':len(transport['malformed_inputs']),
      'outcome':transport['outcome'],'core_unchanged':transport['core_unchanged'],
      'owned_database_removed':transport['owned_database_removed'],'generated_answers':False,'full_T7_validated':False},
 'provider_003':{'task':'DEV-ITS-SIGNATURE-001','planned_order':['graph','plaintext'],'both_http_status':429,
      'accepted_answers':0,'automatic_retries':0,'usage_unknown':True,'owned_container_removed':True},
 'goal_status':'Primary scoped demo ready before18:45 IST; full secondary remains IN_PROGRESS'}
write(out/'summary.json',summary)
write(out/'bundle-manifest.json',{'schema':'development-evidence-files/v1','acceptance_validated':False,
      'files':{str(p.relative_to(out)):digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
print(json.dumps({'output':str(out.relative_to(root)),'files':len(json.loads((out/'bundle-manifest.json').read_text())['files']),'source_mismatches':mismatch}))
