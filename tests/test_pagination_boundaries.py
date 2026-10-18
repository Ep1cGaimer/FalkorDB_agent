"""Controlled, independent enumeration probes for a subset of T5."""
from collections import deque

import pytest

from test_adversarial_review import env, commit, query
from rw.repo.index import index_repository


@pytest.mark.parametrize("count", [0, 1, 9, 10, 11, 35])
def test_row_boundaries_exact_independent_enumeration(count, env):
    path, cfg, graph = env
    if count:
        text = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(count - 1))
        commit(path, {"a.py": text}, "controlled symbols")
        expected = ["a"] + [f"a.f{i}" for i in range(count - 1)]
    else:
        commit(path, {"README.md": "No Python symbols\n"}, "zero symbols")
        expected = []
    index_repository(cfg, graph)
    q = query(cfg, graph)
    cursor, actual, pages = None, [], []
    while True:
        page = q.symbols("HEAD", limit=10, cursor=cursor)
        actual.extend(x.qualname for x in page.items)
        pages.append({"cursor": cursor, "returned": len(page.items), "coverage": page.coverage})
        assert len(page.items) <= 10
        cursor = page.next_cursor
        if cursor is None:
            break
    print("boundary", count, pages)
    assert actual == expected
    assert len(actual) == len(set(actual)) == count


@pytest.mark.parametrize("hops", [1, 2, 3, 4, 5])
def test_cycles_fanout_depth_and_last_page_match_independent_bfs(hops, env):
    path, cfg, graph = env
    adjacency = {0: [1, 2, 3, 4], 1: [0], 2: [5], 3: [5], 4: [], 5: [6], 6: [7], 7: [8], 8: []}
    text = "".join(f"def f{i}():\n" + ("".join(f"    f{j}()\n" for j in js) or "    pass\n") + "\n"
                   for i, js in adjacency.items())
    commit(path, {"a.py": text}, "cycle and depth")
    index_repository(cfg, graph)
    expected, dist, todo = set(), {0: 0}, deque([0])
    while todo:
        n = todo.popleft()
        if dist[n] >= hops:
            continue
        for target in adjacency[n]:
            expected.add((f"a.f{n}", f"a.f{target}", "CALLS"))
            if target not in dist:
                dist[target] = dist[n] + 1
                todo.append(target)
    q, cursor, actual = query(cfg, graph), None, []
    while True:
        page = q.dependencies("HEAD", "a.f0", hops=hops, limit=2, cursor=cursor)
        actual.extend((x.source, x.target, x.kind) for x in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert set(actual) == expected
    assert len(actual) == len(set(actual))
    print("bfs", {"hops": hops, "count": len(actual), "last_result": actual[-1]})



def test_explicit_hop_scope_is_reported(env):
    """The original review excluded its beyond-requested-depth assertion as too strong."""
    path, cfg, graph = env
    commit(path, {"a.py": "def first():\n    middle()\n\ndef middle():\n    last()\n\ndef last():\n    pass\n"}, "depth chain")
    index_repository(cfg, graph)
    page = query(cfg, graph).dependencies("HEAD", "a.first", hops=1, limit=200)
    assert page.coverage["hops"] == 1
    assert {(i.source, i.target) for i in page.items} == {("a.first", "a.middle")}
