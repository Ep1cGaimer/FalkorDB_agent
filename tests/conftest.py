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


def pytest_sessionstart(session):
    """Say once, up front, when FalkorDB is unreachable: graph tests would otherwise fail one by one
    with connection errors. Portable subsets (e.g. the Windows MCP job) run without a server, so this
    only warns; it never stops the run."""
    import os
    import socket

    host = os.environ.get("RW_FALKORDB_HOST", "127.0.0.1")
    port = int(os.environ.get("RW_FALKORDB_PORT", "6379"))
    try:
        socket.create_connection((host, port), timeout=1).close()
    except OSError:
        print(f"\nWARNING: FalkorDB is not reachable at {host}:{port}. Tests that need the graph will "
              "fail. Start Docker, then run: docker compose up -d --wait\n")


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
        try:
            G.connect().select_graph(state["name"]).delete()
        except Exception:  # never imported (e.g. a setup failure): there is nothing to delete
            pass


@pytest.fixture
def oracle_graph(oracle_case, oracle_graphs):
    root, _case = oracle_case
    if root not in oracle_graphs:
        oracle_graphs[root] = {"name": f"rw_test_{uuid.uuid4().hex[:12]}", "imported": False}
    return oracle_graphs[root]
