"""Public byte/link checker. No heldout sources, scoring or network access."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
 reports=[]
 for path in sorted((ROOT/'docs/reviews').glob('*-evidence/bundle-manifest.json')):
  data=json.loads(path.read_text());bad=[p for p,h in data['files'].items() if not (path.parent/p).is_file() or digest(path.parent/p)!=h]
  reports.append({'manifest':str(path.relative_to(ROOT)),'files':len(data['files']),'mismatches':bad})
 current=ROOT/'docs/reviews/goal-citation-integrity-evidence/implementation-manifest-v2.json'
 files=json.loads(current.read_text())['files'];bad=[p for p,h in files.items() if not (ROOT/p).is_file() or digest(ROOT/p)!=h]
 ledger=json.loads((ROOT/'docs/reviews/goal-acceptance-ledger.json').read_text())
 missing=sorted({p for e in ledger['entries'] for p in e['artifact_links'] if not (ROOT/p).exists()})
 assert digest(ROOT/'remquirements-v1.md')==ledger['authority']['sha256']
 assert all(e['status']=='IN_PROGRESS' and e['validated_at'] is None and e['implementation_ref']['source_manifest_sha256']==digest(current) for e in ledger['entries'])
 hpath=ROOT/'docs/reviews/goal-independent-reproduction/20261018T101141Z-f8faa67-z_wmyild/HANDOFF.json'
 handoff=json.loads(hpath.read_text());hbad=[p for p,h in handoff['files'].items() if not (hpath.parent/p).is_file() or digest(hpath.parent/p)!=h]
 result={'schema':'goal-curated-evidence-integrity/v1','artifact_manifests':reports,'current_source_manifest':str(current.relative_to(ROOT)),
 'current_source_files':len(files),'current_source_mismatches':bad,'ledger_missing_links':missing,'current_implementation_commit':None,
 'current_working_tree_parent':'520e8fa','acceptance_statuses':sorted({e['status'] for e in ledger['entries']}),'acceptance_validated':False,
 'independent_reproduction_handoff':{'path':str(hpath.relative_to(ROOT)),'sha256':digest(hpath),'files':len(handoff['files']),'mismatches':hbad},
 'interpretation':'Byte/link integrity only;not independent correctness,scoring,scale,cost or advantage validation'}
 errors=[r['manifest'] for r in reports if r['mismatches']]+bad+missing+hbad
 result['errors']=errors
 return result
if __name__=='__main__':
 result=verify();print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))
