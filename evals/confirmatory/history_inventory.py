"""Count pinned upstream source/history using Git plumbing, without execution.

Object first-seen path names are retained; this is a conservative inventory rather
than a claim that all path identities or syntax are supported.
"""
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parents[2]
PUBLIC=ROOT/"evals/confirmatory"
CORPUS=json.loads((PUBLIC/"corpus.draft-v1.json").read_text())

def included(path):
    source=path.endswith(".py") and path.startswith(("requests/","src/requests/","click/","src/click/")) and not path.startswith("requests/packages/")
    meta=path in ("HISTORY.rst","HISTORY.md","CHANGES.rst","CHANGES.md","CHANGELOG.rst","CHANGELOG.md","pyproject.toml","setup.py","setup.cfg")
    return source or meta

def main():
    out={"schema":"confirmatory-history-inventory/v1","status":"DRAFT","created_at":datetime.now(timezone.utc).isoformat(),"execution":"Git plumbing only; upstream code never imported/executed","token_count_status":"PENDING_EXACT_MODEL_TOKENIZER","method":"One content object per Git blob with included first-seen path, plus raw reachable commit objects and ordered parents. File membership maps remain available via Git, not duplicated for a token lower-bound calculation.","repositories":{}}
    for repo,meta in CORPUS["repositories"].items():
        base=["git",f"--git-dir={ROOT/meta['bare_path']}"]
        roots=[s["commit"] for s in meta["snapshots"]]
        listing=subprocess.check_output([*base,"rev-list","--objects",*roots]).decode().splitlines()
        names={}
        for line in listing:
            oid,_,path=line.partition(" ")
            if included(path):names[oid]=path
        data=("\n".join(names)+"\n").encode()
        sizes=subprocess.check_output([*base,"cat-file","--batch-check=%(objectname) %(objecttype) %(objectsize)"],input=data).decode().splitlines()
        blobs=[]
        for line in sizes:
            oid,typ,size=line.split()
            if typ=="blob":blobs.append({"object":oid,"first_seen_path":names[oid],"bytes":int(size)})
        commits=subprocess.check_output([*base,"rev-list",*roots]).decode().splitlines()
        commit_sizes=subprocess.check_output([*base,"cat-file","--batch-check=%(objectname) %(objecttype) %(objectsize)"],input=("\n".join(commits)+"\n").encode()).decode().splitlines()
        commit_bytes=sum(int(line.split()[2]) for line in commit_sizes)
        out["repositories"][repo]={"reachable_commits":len(commits),"included_unique_blobs":len(blobs),"included_unique_blob_bytes":sum(b["bytes"] for b in blobs),"raw_commit_object_bytes":commit_bytes,"included_blob_objects":sorted(blobs,key=lambda b:b["object"]),"roots":roots,"exact_tokens":None,"membership_metadata_tokens":None,"limitations":["First-seen object path is not an exhaustive rename/copy identity map.","Historical source may include syntax unsupported by the declared Python 3 adapter.","No model context-overflow claim until exact tokenizer and serialization are verified."]}
    path=PUBLIC/"feasibility-inventory.draft-v1.json"
    payload=json.dumps(out,indent=2,sort_keys=True)+"\n"
    with path.open("x") as f:f.write(payload)
    print(json.dumps({"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(payload.encode()).hexdigest(),"repositories":{r:{k:v for k,v in m.items() if k not in ('included_blob_objects','roots')} for r,m in out["repositories"].items()}},indent=2))

if __name__=="__main__":main()
