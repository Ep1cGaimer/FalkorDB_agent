"""Record real CLI/TCP API/stdio MCP parity and graph ablations on disposable indexes.

This is a development diagnostic, not a frozen held-out experiment or advantage score.
--isolated-db creates an owned Docker container and tests a genuine stop/start outage.
Without that option the configured database is used, and never stopped or restarted.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
IMAGE = "falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6"


def core_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/rw").rglob("*.py"))}


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=60).stdout.strip()


@contextmanager
def endpoint(record, isolated):
    from rw import graph as G
    keys = ("RW_FALKORDB_HOST", "RW_FALKORDB_PORT")
    previous = {key: os.environ.get(key) for key in keys}
    name = "rw-acceptance-probe-" + uuid.uuid4().hex[:10] if isolated else None
    try:
        if name:
            docker("run", "-d", "--name", name, "-p", "127.0.0.1::6379", IMAGE)
            port = docker("port", name, "6379/tcp").rsplit(":", 1)[1]
            os.environ.update(RW_FALKORDB_HOST="127.0.0.1", RW_FALKORDB_PORT=port)
        deadline = time.monotonic() + 30
        while True:
            try:
                db = G.connect()
                assert db.connection.ping()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        record["database"] = {"owned_container": name, "image": IMAGE if name else None,
            "host": os.environ.get(keys[0], "127.0.0.1"), "port": int(os.environ.get(keys[1], "6379")),
            "server": {k: v for k, v in db.connection.info("server").items()
                       if k in {"redis_version", "run_id", "arch_bits"}},
            "modules": db.connection.execute_command("MODULE", "LIST")}
        yield name
    finally:
        if name:
            docker("rm", "-f", name)
            record["owned_database_removed"] = True
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def api_server(out):
    import httpx
    import uvicorn
    from rw.api import create_app
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(create_app(db_path=out / "unused.sqlite"),
        log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("temporary API did not start")
            time.sleep(0.02)
        assert httpx.get(origin + "/api/repos", timeout=10).status_code == 200
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("temporary API did not stop")


async def surfaces(record, cases, out, origin, phase):
    import httpx
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from rw.repo.investigate import investigate
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "RW_MCP_API_BASE_URL": origin}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/serve_mcp.py")],
                                  cwd=out, env=env)
    with (out / f"mcp-{phase}.stderr.log").open("w") as stderr:
        async with stdio_client(params, errlog=stderr) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=30) as session:
                await session.discover()
                tools = (await session.list_tools()).tools
                record.setdefault("mcp_sessions", []).append({"phase": phase,
                    "tools": [t.model_dump(mode="json", by_alias=True) for t in tools]})
                # Concurrent calls share one real stdio connection while selecting different repos.
                mcp_results = await asyncio.gather(*(session.call_tool("repo_investigate", c) for c in cases))
                for case, mcp in zip(cases, mcp_results):
                    direct = investigate(case["repo"], case["revision"], case["question"]).to_dict()
                    api = httpx.post(origin + f"/api/repos/{case['repo']}/investigate",
                        json={k: case[k] for k in ("revision", "question")}, timeout=30)
                    cli = subprocess.run([sys.executable, str(ROOT / "scripts/repo_investigate.py"),
                        "--repo", case["repo"], "--rev", case["revision"], case["question"]],
                        cwd=out, env=env, capture_output=True, text=True, timeout=30)
                    cli_json = json.loads(cli.stdout) if cli.returncode == 0 else None
                    same = not mcp.is_error and direct == api.json() == cli_json == mcp.structured_content
                    row = {"phase": phase, "request": case, "direct": direct,
                           "api": {"url": str(api.url), "status": api.status_code, "response": api.json()},
                           "cli": {"exit_code": cli.returncode, "stdout": cli.stdout, "stderr": cli.stderr},
                           "mcp": mcp.model_dump(mode="json", by_alias=True), "exact_semantic_parity": same}
                    record["transports"].append(row)
                    if not same:
                        record["failures"].append(f"{phase}: surface mismatch for {case}")
                    if phase in ("database-stopped", "incomplete-publication", "stale-record", "stale-relationship",
                                 "query-row-budget", "query-source-budget"):
                        expected = {"database-stopped": "INDEX_UNAVAILABLE",
                                    "incomplete-publication": "INCOMPLETE_IMPORT", "stale-record": "STALE_EXTRACTION",
                                    "stale-relationship": "STALE_EXTRACTION",
                                    "query-row-budget": "RETRIEVAL_BUDGET_EXHAUSTED",
                                    "query-source-budget": "RETRIEVAL_BUDGET_EXHAUSTED"}[phase]
                        assert not direct["findings"] and not direct["facts"] and any(g["kind"] == expected for g in direct["gaps"])
                if phase == "parallel-and-selection":
                    for invalid in ({**cases[0], "question": ""}, {**cases[0], "question": "x" * 2001}):
                        response = httpx.post(origin + f"/api/repos/{invalid['repo']}/investigate",
                            json={k: invalid[k] for k in ("revision", "question")}, timeout=10)
                        result = await session.call_tool("repo_investigate", invalid)
                        record.setdefault("malformed_inputs", []).append({"phase": phase,
                            "question_length": len(invalid["question"]), "api_status": response.status_code,
                            "mcp": result.model_dump(mode="json", by_alias=True)})
                        assert response.status_code == 422 and result.is_error


def ablations(cfg, revision, symbol, graph_name, row):
    from rw import graph as G
    from rw.repo.investigate import investigate
    from rw.repo.query import RepoQuery
    from redis.exceptions import ConnectionError
    graph = G.connect().select_graph(graph_name)
    trace = []
    q = RepoQuery(graph_name, cfg.name, trace=trace)
    sha, gap = q.resolve(revision)
    assert sha and gap is None
    candidates = [s for s in q.symbols(revision, symbol.rsplit(".", 1)[-1], limit=200).items
                  if s.qualname == symbol or s.qualname.endswith("." + symbol)]
    assert len(candidates) == 1, "public symbol must select one source identity"
    symbol = candidates[0].qualname
    page = q.dependencies(revision, symbol, hops=3, limit=200)
    assert page.items and any(e.hops >= 2 for e in page.items), "probe needs a genuine multi-hop result"
    row.update(resolved_sha=sha, resolved_symbol=symbol, multi_hop=asdict(page), graph_trace=trace)
    row["canonical_investigation"] = investigate(cfg.name, revision, f"What does {symbol} depend on?",
        config=cfg, graph_name=graph_name, trace=trace).to_dict()
    root = next(s for s in q._candidates(sha, symbol) if s.qualname == symbol)
    row["root_storage"] = {"hash": root.content_hash, "qualname": root.stored_qualname}
    edge = next(e for e in page.items if e.source == symbol and not e.external)
    assert edge.kind in {"CALLS", "IMPORTS", "INHERITS"}
    params = {"h": root.content_hash, "q": root.stored_qualname}
    match = (f"MATCH (:Blob {{content_hash:$h}})-[:DEFINES]->(s:Symbol {{qualname:$q}})"
             f"-[e:{edge.kind}]->(t:Symbol) ")
    saved = graph.ro_query(match + "RETURN s.id, t.id, e.provenance, e.extractor, e.relative_target", params).result_set
    assert saved
    graph.query(match + "DELETE e", params)
    try:
        after = q.dependencies(revision, symbol, hops=3, limit=200)  # same object, no hidden old cache
        assert len(after.items) < len(page.items)
        row.setdefault("ablations", []).append({"operation": f"remove root {edge.kind} edges",
            "removed_edge_count": len(saved), "same_query_object": True, "after": asdict(after),
            "supported_edge_count_before": len(page.items), "outcome": "PASS"})
    finally:
        for src, target, provenance, extractor, relative in saved:
            graph.query(f"MATCH (s:Symbol {{id:$s}}), (t:Symbol {{id:$t}}) "
                        f"CREATE (s)-[:{edge.kind} {{provenance:$p, extractor:$e, relative_target:$r}}]->(t)",
                        {"s": src, "t": target, "p": provenance, "e": extractor, "r": relative})
    original = graph.ro_query("MATCH (b:Blob {content_hash:$h}) RETURN b.extracted_by", params).result_set[0][0]
    graph.query("MATCH (b:Blob {content_hash:$h}) SET b.extracted_by='probe-stale'", params)
    try:
        result = investigate(cfg.name, revision, f"Where is {symbol} defined?", config=cfg, graph_name=graph_name)
        assert not result.findings and any(g.kind == "STALE_EXTRACTION" for g in result.gaps)
        row["ablations"].append({"operation": "stale extraction record", "result": result.to_dict(), "outcome": "PASS"})
    finally:
        graph.query("MATCH (b:Blob {content_hash:$h}) SET b.extracted_by=$x", {**params, "x": original})
    original_read = q.graph.ro_query
    reads = 0

    def interrupted(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 4:
            raise ConnectionError("explicit probe transport interruption")
        return original_read(*args, **kwargs)

    q.graph.ro_query = interrupted
    try:
        try:
            q.dependencies(revision, symbol, hops=3)
        except ConnectionError:
            row["ablations"].append({"operation": "inject transport failure after three real reads",
                                     "classification": "injected transport exception", "outcome": "PASS"})
        else:
            raise AssertionError("interruption must not return a cached answer")
    finally:
        q.graph.ro_query = original_read


async def run(args):
    from rw import graph as G
    from rw.repo.config import load_config
    from rw.repo.index import graph_name_for, index_repository
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    configs = out / "configs"
    configs.mkdir()
    record = {"schema": "repo-transport-probe/v1", "classification": "development, not held-out acceptance",
        "started_at": datetime.now(timezone.utc).isoformat(), "acceptance_validated": False,
        "llm_used": False, "core_before": core_hashes(), "repositories": [], "transports": [],
        "failures": [], "cleanup": []}
    record["command"] = [sys.executable, *sys.argv]
    record["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "executed-harness.py").write_bytes(Path(__file__).read_bytes())
    previous_configs = os.environ.get("RW_REPOS_DIR")
    os.environ["RW_REPOS_DIR"] = str(configs)
    active = []
    try:
        with endpoint(record, args.isolated_db) as container:
            try:
                for case in json.loads(args.cases.read_text())["repositories"]:
                    original = load_config(args.cases.resolve().parent / case["config"])
                    cfg = original.model_copy(update={"name": f"probe-{original.name}-{uuid.uuid4().hex[:8]}"})
                    (configs / f"{cfg.name}.json").write_text(cfg.model_dump_json(indent=2))
                    graph_name = graph_name_for(cfg)
                    active.append(graph_name)
                    started = time.perf_counter()
                    report = index_repository(cfg)
                    row = {"repo": cfg.name, "upstream": original.name, "config": cfg.model_dump(mode="json"),
                           "index": asdict(report), "setup_seconds": time.perf_counter() - started}
                    record["repositories"].append(row)
                    ablations(cfg, case["revision"], case["symbol"], graph_name, row)
                    row["revision"] = case["revision"]
                    print(original.name, "import and ablations PASS", flush=True)
                    (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
                cases = [{"repo": r["repo"], "revision": rev, "question": question}
                    for r in record["repositories"]
                    for rev, question in [(r["revision"], f"Where is {r['resolved_symbol']} defined?"),
                        (r["revision"], "List symbols"), (r["revision"], "Write an unsupported poem"),
                        (r["revision"], "Where is nonexistent_probe_symbol defined?"),
                        ("missing-probe-revision", "List symbols")]]
                cases.append({"repo": "missing-probe-repository", "revision": "HEAD", "question": "List symbols"})
                with api_server(out) as origin:
                    record["api_origin"] = origin
                    await surfaces(record, cases, out, origin, "parallel-and-selection")
                    await surfaces(record, [cases[0], cases[5]], out, origin, "stdio-restart")
                    for phase, field in (("query-row-budget", "query_max_rows"),
                                         ("query-source-budget", "query_max_source_bytes")):
                        original_configs = {}
                        try:
                            for r in record["repositories"]:
                                config_path = configs / f"{r['repo']}.json"
                                original_configs[config_path] = config_path.read_bytes()
                                body = json.loads(original_configs[config_path])
                                body[field] = 1
                                config_path.write_text(json.dumps(body))
                            await surfaces(record, [cases[0], cases[5]], out, origin, phase)
                        finally:
                            for config_path, original_bytes in original_configs.items():
                                config_path.write_bytes(original_bytes)
                    try:
                        for name in active:
                            G.connect().select_graph(name).query("MATCH (r:Repository) SET r.status='FAILED'")
                        await surfaces(record, [cases[0], cases[5]], out, origin, "incomplete-publication")
                    finally:
                        for name in active:
                            G.connect().select_graph(name).query("MATCH (r:Repository) SET r.status='COMPLETE'")
                    for r in record["repositories"]:
                        graph = G.connect().select_graph(r["index"]["graph_name"])
                        rows = graph.ro_query("MATCH (:Commit {sha:$s})-[:HAS_FILE]->(b:Blob) "
                            "WHERE b.language='python' RETURN b.content_hash, b.extracted_by LIMIT 1",
                            {"s": r["resolved_sha"]}).result_set
                        h, extractor = rows[0]
                        graph.query("MATCH (b:Blob {content_hash:$h}) SET b.extracted_by='probe-stale'", {"h": h})
                        r["transport_stale_record"] = {"hash": h, "extractor": extractor}
                    try:
                        await surfaces(record, [cases[0], cases[5]], out, origin, "stale-record")
                    finally:
                        for r in record["repositories"]:
                            saved = r["transport_stale_record"]
                            G.connect().select_graph(r["index"]["graph_name"]).query(
                                "MATCH (b:Blob {content_hash:$h}) SET b.extracted_by=$x",
                                {"h": saved["hash"], "x": saved["extractor"]})
                    try:
                        for r in record["repositories"]:
                            stored = r["root_storage"]
                            G.connect().select_graph(r["index"]["graph_name"]).query(
                                "MATCH (:Blob {content_hash:$h})-[:DEFINES]->(:Symbol {qualname:$q})-[e]->() "
                                "WHERE e.extractor IS NOT NULL SET e.probe_original_extractor=e.extractor, e.extractor='probe-stale'",
                                {"h": stored["hash"], "q": stored["qualname"]})
                        await surfaces(record, [{"repo": r["repo"], "revision": r["revision"],
                            "question": f"What does {r['resolved_symbol']} depend on?"} for r in record["repositories"]],
                            out, origin, "stale-relationship")
                    finally:
                        for name in active:
                            G.connect().select_graph(name).query("MATCH ()-[e]->() WHERE e.probe_original_extractor IS NOT NULL "
                                "SET e.extractor=e.probe_original_extractor, e.probe_original_extractor=null")
                    if container:
                        docker("stop", "-t", "1", container)
                        await surfaces(record, [cases[0], cases[5]], out, origin, "database-stopped")
                        for item in record["transports"][-2:]:
                            assert not item["direct"]["findings"]
                            assert any(g["kind"] == "INDEX_UNAVAILABLE" for g in item["direct"]["gaps"])
                        docker("start", container)
                        port = docker("port", container, "6379/tcp").rsplit(":", 1)[1]
                        os.environ["RW_FALKORDB_PORT"] = port
                        deadline = time.monotonic() + 20
                        while True:
                            try:
                                assert G.connect().connection.ping()
                                break
                            except Exception:
                                if time.monotonic() >= deadline:
                                    raise
                                await asyncio.sleep(0.1)
                        await surfaces(record, [cases[0], cases[5]], out, origin, "database-restarted")
                        record["database_restart"] = {"port": int(port),
                            "server_run_id": G.connect().connection.info("server")["run_id"]}
                        for item in record["transports"][-2:]:
                            assert item["direct"]["findings"] and item["direct"]["citations"]
            finally:
                for name in active:
                    try:
                        G.connect().select_graph(name).delete()
                        record["cleanup"].append({"graph": name, "deleted": True})
                    except Exception as exc:
                        record["cleanup"].append({"graph": name, "deleted": False, "error_type": type(exc).__name__})
                        if not container:
                            record["failures"].append(f"could not clean owned graph {name}")
    except BaseException as exc:
        record["failures"].append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        record["core_after"] = core_hashes()
        record["core_unchanged"] = record["core_after"] == record["core_before"]
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["outcome"] = "PASS" if record["core_unchanged"] and not record["failures"] else "FAIL"
        (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
        if previous_configs is None:
            os.environ.pop("RW_REPOS_DIR", None)
        else:
            os.environ["RW_REPOS_DIR"] = previous_configs
    return 0 if record["outcome"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("repo_probe_cases.json"))
    parser.add_argument("--out", type=Path, required=True, help="new directory; previous attempts are never overwritten")
    parser.add_argument("--isolated-db", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
