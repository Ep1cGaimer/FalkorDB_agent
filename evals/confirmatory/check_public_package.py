"""Verify only public draft artifacts; never opens a sealed file or product."""
import hashlib
import json
import pathlib
from collections import Counter

ROOT=pathlib.Path(__file__).resolve().parents[2]
HERE=ROOT/"evals/confirmatory"

def check(path,expected):
    if "sealed" in pathlib.Path(path).parts:
        raise ValueError("public checker refuses sealed paths")
    actual=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    if actual!=expected:raise ValueError(f"hash mismatch: {path}")

def main():
    package=json.loads((HERE/"package-manifest.draft-v2.json").read_text())
    for name in ["plan","review","public_tasks"]:
        item=package[name];check(item["path"],item["sha256"])
    plan=json.loads((ROOT/package["plan"]["path"]).read_text())
    for path,expected in plan["artifact_hashes"].items():check(path,expected)
    tasks=json.loads((ROOT/package["public_tasks"]["path"]).read_text())
    counts=Counter((t["id"].split('-')[1],t["primary_stratum"]) for t in tasks)
    assert len(tasks)==len({t["id"] for t in tasks})==len({t["question"] for t in tasks})==120
    assert len(counts)==12 and set(counts.values())=={10}
    assert plan["advantage_gate"]["selected"]=="B" and not plan["advantage_gate"]["accuracy_gate_A_selected"]
    assert plan["repeats"]["paired_repeats"]==3
    ids=plan["scoring"]["double_score"]["ids"]
    assert len(ids)==len(set(ids))==30
    assert not plan["freeze"]["frozen"] and plan["freeze"]["signature"] is None
    print(json.dumps({"public_integrity":"PASS","questions":120,"repository_stratum_cells":12,"each_cell":10,"double_score_base_cases":30,"frozen":False,"gate_passes_claimed":False},indent=2))

if __name__=="__main__":main()
