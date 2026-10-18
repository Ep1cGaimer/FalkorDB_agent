"""100 independently tracked, seeded mini histories; not the full T3 DAG matrix."""
import hashlib
import json
import random

import pytest

from test_adversarial_review import env, git, commit, query
from rw import graph as G
from rw.repo.index import index_repository


@pytest.mark.parametrize("seed", range(100))
def test_generated_state_order_and_branch_invariants(seed, env, tmp_path):
    path, cfg, graph = env
    rng = random.Random(seed)
    symbol = f"f{rng.randrange(20)}"
    original = f"def {symbol}():\n    return {rng.randrange(1000)}\n"
    fixed = original.replace("return ", "return 10000 + ")
    recreated = f"def {symbol}():\n    return 'recreated-{seed}'\n"
    oracle = {}

    def add(files, text):
        sha = commit(path, files, text)
        oracle[sha] = dict(files)
        return sha

    first = add({"a.py": original}, "initial")
    fix = add({"a.py": fixed}, "fix")
    reverted = add({"a.py": original}, "revert content")
    (path / "a.py").unlink()
    deleted = add({"README.md": "deleted a.py\n"}, "delete")
    recreated_sha = add({"a.py": recreated, "README.md": "deleted a.py\n"}, "recreate same path")
    cfg = cfg.model_copy(update={"revisions": [recreated_sha]})
    index_repository(cfg, graph)

    def normalized(gname, sha):
        q = query(cfg, gname)
        rows = q._q("MATCH (:Commit {sha:$s})-[f:HAS_FILE]->(b:Blob) "
                    "RETURN f.path,b.content_hash ORDER BY f.path", {"s": sha})
        return rows, sorted(x.qualname for x in q.symbols(sha, limit=200).items)

    before = {s: normalized(graph, s) for s in oracle}
    # An unrelated branch has the same file/symbol names but different contents.
    git(path, "checkout", "-qb", "unrelated", first)
    branch = commit(path, {"a.py": f"def {symbol}():\n    return 'unrelated'\n"}, "branch")
    cfg = cfg.model_copy(update={"revisions": [recreated_sha, branch]})
    index_repository(cfg, graph)
    after = {s: normalized(graph, s) for s in oracle}
    other = graph + "_reverse"
    try:
        # A clean index with reversed revision input must produce the same pinned states.
        index_repository(cfg.model_copy(update={"revisions": [branch, recreated_sha]}), other)
        reverse = {s: normalized(other, s) for s in oracle}
        assert before == after == reverse
        for sha, files in oracle.items():
            expected = [[p, hashlib.sha256(text.encode()).hexdigest()] for p, text in sorted(files.items())]
            assert before[sha][0] == expected
            # Git independently confirms the oracle's expected tracked paths.
            assert git(path, "ls-tree", "--name-only", sha).splitlines() == sorted(files)
        q = query(cfg, graph)
        assert q.fix_status(fix, fix).state == "PRESENT"
        assert q.fix_status(reverted, fix).state != "PRESENT"
        assert q.fix_status(deleted, fix).state != "PRESENT"
        assert not q.symbols(deleted, symbol).items
        assert q.symbols(first, symbol).items
        print(json.dumps({"seed": seed, "oracle_shas": list(oracle), "branch": branch,
                          "checked": ["trees", "hashes", "revert", "delete/recreate", "order", "unrelated branch"]}))
    finally:
        G.connect().select_graph(other).delete()
