"""Independent oracle cases over the shipped shop and an isolated identity fixture overlay."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORACLES = {"baseline": ROOT / "evals/expected/dispositions.json",
           "obligation_identity": ROOT / "evals/expected/obligation_identity.json"}
ORACLE_CASES = [(suite, case) for suite, path in ORACLES.items()
                for case in json.loads(path.read_text(encoding="utf-8"))["cases"]]


@pytest.fixture(scope="module")
def identity_fixture_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("obligation_identity") / "shop"
    shutil.copytree(ROOT / "fixtures/shop", root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "tests/fixtures/obligation_identity", root, dirs_exist_ok=True)
    return root


@pytest.fixture(scope="module", params=ORACLE_CASES, ids=[case["id"] for _, case in ORACLE_CASES])
def oracle_case(request, identity_fixture_root):
    suite, case = request.param
    root = ROOT / "fixtures/shop" if suite == "baseline" else identity_fixture_root
    return root, case


@pytest.fixture(scope="module")
def oracle_graphs():
    graphs = {}
    yield graphs
    from rw import graph as G
    for state in graphs.values():
        G.connect().select_graph(state["name"]).delete()


@pytest.fixture
def oracle_graph(oracle_case, oracle_graphs):
    root, _case = oracle_case
    if root not in oracle_graphs:
        oracle_graphs[root] = {"name": f"rw_test_{uuid.uuid4().hex[:12]}", "imported": False}
    return oracle_graphs[root]
