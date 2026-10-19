"""FalkorDB importer and read queries for RollbackWitness.

Frozen API: see docs/CONTRACTS.md section `src/rw/graph.py`. Everything this module
writes is derived from fixture bytes plus identifiers from trusted code; no user or
model text ever reaches Cypher (parameters only) and no compatibility verdict is
stored. Reads use ``ro_query``, writes use ``query``.

Conventions fixed here (the frozen contracts leave these open; all are documented so
the orchestrator can check them):

* ``snapshot_id`` is always the Snapshot NODE id form ``snapshot:<name>``
  (e.g. ``snapshot:snap-001``); the plain name is kept on the node as ``name``.
* ``store_id`` is always ``store:<name>`` (e.g. ``store:cart-cache``).
* ``Batch.id = batch:<store_name>:<snapshot_name>:<record_id>:<short(payload_hash)>``.
  When a manifest record carries no ``payload_hash`` the hash segment is the literal
  ``UNKNOWN``; the record is still imported and its ``payload_hash`` property is
  omitted (FalkorDB does not store nulls).
* ``Coverage.id = coverage:<snapshot_name>:<store_name>`` with
  ``inventory_id_hash = h(sorted(record_ids))``.
* Snapshot deployment id = ``deployment:<snapshot_id>:<service>``, i.e.
  ``deployment:snapshot:snap-001:cart`` (the snapshot id already carries its prefix).
* Plan candidate deployment id = ``deployment:<plan_id>:<service>`` (frozen contract).
* ``payload_path`` / ``codec_path`` are posix paths relative to the repository root
  (absolute posix if the fixture lives outside the repository).
* Excerpts: one per CHANGELOG bullet/paragraph (markdown heading lines and the
  ``SYNTHETIC FIXTURE ...`` disclaimer paragraph are not release content, so they are
  skipped) and one per top-level ``def`` in ``codec.py``; spans are 1-based inclusive.
* ``current_fleet.flags`` are the snapshot deployment flags; ``declared_flags`` is the
  release's own ``flags`` array (name/default pairs). ``writes`` declarations from
  release.json are not modelled: the frozen schema has no writer-side edge.
* Every read function takes an optional ``cap`` (default ``QUERY_CAP``); the queries
  fetch ``cap + 1`` rows and report ``truncated`` at ``cap + 1`` so tests can exercise
  the truncation path without fixture data that large.
* ``store_readers.currently_deployed_in`` lists snapshot NODE ids; ``ProbeRun.id`` is
  ``probe:<short(receipt_hash)>`` so re-writing one receipt is a no-op.
* ``store_inventory`` runs two bounded queries (coverage, batches) and merges them into
  one log entry (``rows`` = coverage + batches, ``truncated`` = either query hit cap).
* ``release_history`` follows at most ``CHAIN_HOP_CAP`` PREVIOUS hops; a longer chain is
  reported as the shorter chain it walked rather than silently guessed.
* Unknown values are ``None`` in rows; unknown properties and edges are omitted.
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import falkordb

from rw.contracts import (
    QUERY_CAP,
    SCOPE_ID,
    CandidatePlan,
    ProbeReceipt,
    artifact_hash as release_artifact_hash,
    bh,
    canonical_json,
    h,
    repo_rel,
    short,
)

CHANGELOG_KIND = "changelog"
CODE_KIND = "code"
CHANGELOG_FILE = "CHANGELOG.md"
CODEC_FILE = "codec.py"
DISCLAIMER_PREFIXES = ("SYNTHETIC FIXTURE",)
CHAIN_HOP_CAP = 10  # max PREVIOUS hops a release_history chain walk follows

NODE_LABELS = (
    "Service",
    "Release",
    "SourceExcerpt",
    "Snapshot",
    "Deployment",
    "ReaderRoute",
    "StateStore",
    "Batch",
    "Coverage",
    "Plan",
    "ProbeRun",
)
EDGE_TYPES = (
    "HAS_DEPLOYMENT",
    "OF_SERVICE",
    "RUNS",
    "PREVIOUS",
    "HAS_SOURCE",
    "EXECUTES_ROUTE",
    "READS_FROM",
    "IN_STORE",
    "WRITTEN_BY",
    "DERIVED_FROM",
    "HAS_COVERAGE",
    "BASED_ON",
    "TESTS_READER",
    "TESTS_BATCH",
)

# Cypher text of every fixed read that has run, by log name. The API shows it to the human UI;
# it never enters a model prompt (grounding tool results carry only the name/params/rows log).
QUERY_TEXT: dict[str, str] = {}

_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


# --------------------------------------------------------------------------- helpers


def connect(host: str | None = None, port: int | None = None, *,
            socket_timeout: float | None = None) -> "falkordb.FalkorDB":
    """Open a FalkorDB client (no graph is created until a write happens)."""
    host = host if host is not None else os.environ.get("RW_FALKORDB_HOST", "127.0.0.1")
    port = port if port is not None else int(os.environ.get("RW_FALKORDB_PORT", "6379"))
    if not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid FalkorDB endpoint configuration")
    return falkordb.FalkorDB(host=host, port=port,
                           socket_connect_timeout=min(2, socket_timeout) if socket_timeout is not None else 2,
                           **({"socket_timeout": socket_timeout} if socket_timeout is not None else {}))


def _drop_graph(db: "falkordb.FalkorDB", graph_name: str) -> None:
    graph = db.select_graph(graph_name)
    try:
        graph.delete()
    except Exception:
        # FalkorDB errors on GRAPH.DELETE for a key that does not exist.
        pass


def _read(
    graph: Any,
    name: str,
    query: str,
    params: dict[str, Any],
    cols: tuple[str, ...],
    cap: int = QUERY_CAP,
    conv: dict[str, Callable[[Any], Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one read query with LIMIT cap+1 truncation semantics."""
    if cap < 0:
        raise ValueError("cap must be >= 0")
    full_params = dict(params)
    full_params["limit"] = cap + 1
    QUERY_TEXT.setdefault(name, query.strip())
    result = graph.ro_query(query, full_params)
    raw = result.result_set
    truncated = len(raw) == cap + 1
    if truncated:
        raw = raw[:cap]
    rows: list[dict[str, Any]] = []
    for record in raw:
        row: dict[str, Any] = {}
        for index, col in enumerate(cols):
            value = record[index]
            if conv and col in conv:
                value = conv[col](value)
            row[col] = value
        rows.append(row)
    log = {
        "name": name,
        "params": full_params,
        "rows": len(rows),
        "truncated": truncated,
    }
    return rows, log


def _plain(value: Any) -> Any:
    """FalkorDB returns maps as OrderedDict; normalize to plain builtins."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _as_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _plain(json.loads(value))


def _as_list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    return _plain(json.loads(value))


def _as_plain_list(value: Any) -> list[Any]:
    return _plain(value) if value is not None else []


def _span(row: dict[str, Any]) -> str | None:
    start, end = row.pop("line_start"), row.pop("line_end")
    if start is None or end is None:
        return None
    return f"{start}-{end}"


def _write_props(row: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown (None) values: FalkorDB cannot store a null property."""
    return {k: v for k, v in row.items() if v is not None}


def _bulk_create(graph: Any, label: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    graph.query(
        f"UNWIND $rows AS row CREATE (n:{label}) SET n += row",
        {"rows": [_write_props(r) for r in rows]},
    )


def _bulk_edge(
    graph: Any,
    edge_type: str,
    from_label: str,
    to_label: str,
    rows: list[dict[str, Any]],
) -> None:
    """Create edges only where both endpoints exist (missing end -> no edge)."""
    if not rows:
        return
    graph.query(
        f"UNWIND $rows AS row "
        f"MATCH (a:{from_label} {{id: row.from_id}}), (b:{to_label} {{id: row.to_id}}) "
        f"CREATE (a)-[:{edge_type}]->(b)",
        {"rows": rows},
    )


# --------------------------------------------------------------------------- excerpts


def _is_heading(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_bullet(line: str) -> bool:
    return bool(_BULLET.match(line))


def _changelog_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, text) 1-based inclusive blocks for bullets/paragraphs.

    Headings and the fixture disclaimer are skipped; each bullet is its own block so
    one bullet yields one excerpt.
    """
    lines = text.split("\n")
    blocks: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            index += 1
            continue
        if _is_heading(line):
            while index < len(lines) and lines[index].strip() != "" and _is_heading(lines[index]):
                index += 1
            continue
        start = index
        bullet = _is_bullet(line)
        block = [line]
        index += 1
        while index < len(lines):
            current = lines[index]
            if current.strip() == "" or _is_heading(current):
                break
            if bullet and current[:1] not in (" ", "\t"):
                break  # a new bullet/paragraph starts a new block
            if not bullet and current[:1] not in (" ", "\t"):
                break
            block.append(current)
            index += 1
        text_block = "\n".join(block)
        if text_block.startswith(DISCLAIMER_PREFIXES):
            continue
        blocks.append((start + 1, index, text_block))
    return blocks


def _code_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, text) spans of every top-level def in a codec module."""
    tree = ast.parse(text)
    lines = text.split("\n")
    blocks: list[tuple[int, int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = node.lineno, node.end_lineno or node.lineno
        blocks.append((start, end, "\n".join(lines[start - 1 : end])))
    return blocks


def _excerpt_rows(release_id: str, artifact_hash: str, release_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relpath, kind, blocks in (
        (CHANGELOG_FILE, CHANGELOG_KIND, _changelog_blocks((release_dir / CHANGELOG_FILE).read_text(encoding="utf-8"))),
        (CODEC_FILE, CODE_KIND, _code_blocks((release_dir / CODEC_FILE).read_text(encoding="utf-8"))),
    ):
        for start, end, text in blocks:
            rows.append(
                _write_props(
                    {
                        "id": f"excerpt:{short(artifact_hash)}:{relpath}:{start}-{end}",
                        "scope_id": SCOPE_ID,
                        "release_id": release_id,
                        "kind": kind,
                        "path": relpath,
                        "line_start": start,
                        "line_end": end,
                        "text": text,
                        "content_hash": bh(text.encode("utf-8")),
                    }
                )
            )
    return rows


# --------------------------------------------------------------------------- importer


def _collect_releases(fixture_root: Path) -> tuple[
    list[dict[str, Any]],  # release rows
    list[dict[str, Any]],  # excerpt rows
    list[dict[str, Any]],  # route rows
    dict[tuple[str, str], str],  # (service, version) -> release id
    list[dict[str, Any]],  # declarations (parsed release.json + resolved ids)
    list[dict[str, Any]],  # HAS_SOURCE edges
    list[dict[str, Any]],  # EXECUTES_ROUTE edges
]:
    release_rows: list[dict[str, Any]] = []
    excerpt_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    has_source: list[dict[str, Any]] = []
    executes_route: list[dict[str, Any]] = []
    by_version: dict[tuple[str, str], str] = {}
    declarations: list[dict[str, Any]] = []

    for release_dir in sorted((fixture_root / "releases").iterdir()):
        if not release_dir.is_dir() or not (release_dir / "release.json").is_file():
            continue
        declaration = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
        service = declaration["service"]
        artifact_hash = release_artifact_hash(release_dir)
        release_id = f"release:{service}:{short(artifact_hash)}"
        declarations.append(
            {
                "declaration": declaration,
                "release_id": release_id,
                "artifact_hash": artifact_hash,
                "dir": release_dir,
            }
        )
        by_version[(service, declaration["version"])] = release_id
        release_rows.append(
            _write_props(
                {
                    "id": release_id,
                    "scope_id": SCOPE_ID,
                    "service": service,
                    "version": declaration["version"],
                    "artifact_hash": artifact_hash,
                    "codec_hash": bh((release_dir / CODEC_FILE).read_bytes()),
                    "codec_path": repo_rel(release_dir / CODEC_FILE),
                    "built_at": declaration.get("built_at"),
                    "bundle_id": declaration.get("bundle_id"),
                    "declared_flags_json": canonical_json(declaration.get("flags", [])).decode("utf-8"),
                    "no_state_read": bool(declaration.get("no_state_read", False)),
                }
            )
        )
        for excerpt in _excerpt_rows(release_id, artifact_hash, release_dir):
            excerpt_rows.append(excerpt)
            has_source.append({"from_id": release_id, "to_id": excerpt["id"]})
        for route in declaration.get("routes", []):
            route_id = f"route:{release_id}:{route['name']}"
            route_rows.append(
                _write_props(
                    {
                        "id": route_id,
                        "scope_id": SCOPE_ID,
                        "release_id": release_id,
                        "name": route["name"],
                        "entry": route.get("entry"),
                        "read_domain": route.get("read_domain"),
                        "contract": route.get("contract"),
                        "route_contract_hash": h(route),
                    }
                )
            )
            executes_route.append({"from_id": release_id, "to_id": route_id})
    return release_rows, excerpt_rows, route_rows, by_version, declarations, has_source, executes_route


def _collect_snapshot(fixture_root: Path, snapshot_name: str, known_releases: dict[tuple[str, str], str]):
    manifest_path = fixture_root / "snapshots" / snapshot_name / "manifest.json"
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    manifest_hash = bh(raw)
    snapshot_id = f"snapshot:{snapshot_name}"

    snapshot_row = _write_props(
        {
            "id": snapshot_id,
            "scope_id": SCOPE_ID,
            "name": snapshot_name,
            "manifest_hash": manifest_hash,
            "captured_at": manifest.get("captured_at"),
            "environment": manifest.get("environment"),
            "captured_from": repo_rel(manifest_path),
        }
    )

    deployments: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    of_service: list[dict[str, Any]] = []
    has_deployment: list[dict[str, Any]] = []
    services: set[str] = set()
    for entry in manifest.get("deployments", []):
        service = entry["service"]
        version = entry.get("version")
        services.add(service)
        release_id = known_releases.get((service, version))
        deployment_id = f"deployment:{snapshot_id}:{service}"
        flags_json = (
            canonical_json(entry["flags"]).decode("utf-8") if "flags" in entry else None
        )
        deployments.append(
            _write_props(
                {
                    "id": deployment_id,
                    "scope_id": SCOPE_ID,
                    "service": service,
                    "version": version,
                    "release_id": release_id,
                    "snapshot_id": snapshot_id,
                    "flags_json": flags_json,
                }
            )
        )
        has_deployment.append({"from_id": snapshot_id, "to_id": deployment_id})
        of_service.append({"from_id": deployment_id, "to_id": f"service:{service}"})
        if release_id is not None:
            runs.append({"from_id": deployment_id, "to_id": release_id})

    store_names: list[str] = []
    store_kinds: dict[str, str] = {}
    coverages: list[dict[str, Any]] = []
    has_coverage: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    in_store: list[dict[str, Any]] = []
    written_by: list[dict[str, Any]] = []
    batches_by_record: dict[str, list[str]] = {}
    derived_refs: list[tuple[str, Any]] = []

    for store in manifest.get("stores", []):
        store_name = store["name"]
        store_id = f"store:{store_name}"
        store_names.append(store_name)
        if store.get("kind") is not None:
            store_kinds[store_name] = store["kind"]
        records = store.get("records", [])
        coverage_id = f"coverage:{snapshot_name}:{store_name}"
        coverages.append(
            _write_props(
                {
                    "id": coverage_id,
                    "scope_id": SCOPE_ID,
                    "snapshot_id": snapshot_id,
                    "store_id": store_id,
                    "status": store.get("coverage"),
                    "inventory_id_hash": h(sorted(str(r.get("record_id")) for r in records)),
                }
            )
        )
        has_coverage.append({"from_id": store_id, "to_id": coverage_id})
        for record in records:
            record_id = str(record["record_id"])
            payload_hash = record.get("payload_hash")
            writer = record.get("writer") or None
            writer_release_id = None
            if writer:
                writer_release_id = known_releases.get((writer.get("service"), writer.get("version")))
            batch_id = (
                f"batch:{store_name}:{snapshot_name}:{record_id}:"
                f"{short(payload_hash) if payload_hash else 'UNKNOWN'}"
            )
            payload_path = record.get("payload")
            batches.append(
                _write_props(
                    {
                        "id": batch_id,
                        "scope_id": SCOPE_ID,
                        "store_id": store_id,
                        "snapshot_id": snapshot_id,
                        "record_id": record_id,
                        "payload_hash": payload_hash,
                        "payload_path": repo_rel(fixture_root / payload_path) if payload_path else None,
                        "format_id": record.get("format"),
                        "lineage_valid": True,
                        "lineage_parents_json": "[]",
                    }
                )
            )
            in_store.append({"from_id": batch_id, "to_id": store_id})
            if writer_release_id is not None:
                written_by.append({"from_id": batch_id, "to_id": writer_release_id})
            batches_by_record.setdefault(record_id, []).append(batch_id)
            if record.get("derived_from") is not None:
                derived_refs.append((batch_id, record["derived_from"]))

    # Lineage: a record derived from another record of the same snapshot (any store). A source
    # that is absent or names more than one batch is reported, never guessed or silently dropped.
    derived_from: list[dict[str, Any]] = []
    lineage_gaps: list[dict[str, Any]] = []
    batch_props = {b["id"]: b for b in batches}
    for batch_id, sources in derived_refs:
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            batch_props[batch_id]["lineage_valid"] = False
            lineage_gaps.append({"batch_id": batch_id, "source": None, "reason": "derived_from is not a list of record ids"})
            continue
        for source in sources:
            candidates = batches_by_record.get(source, [])
            if len(candidates) == 1:
                derived_from.append({"from_id": batch_id, "to_id": candidates[0]})
            else:
                batch_props[batch_id]["lineage_valid"] = False
                lineage_gaps.append({"batch_id": batch_id, "source": source,
                                     "reason": "source record not in snapshot" if not candidates
                                     else "source record id names more than one batch"})
        batch_props[batch_id]["lineage_parents_json"] = json.dumps(sorted({
            e["to_id"] for e in derived_from if e["from_id"] == batch_id}))

    return {
        "snapshot_row": snapshot_row,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest_hash,
        "services": services,
        "deployments": deployments,
        "has_deployment": has_deployment,
        "runs": runs,
        "of_service": of_service,
        "store_names": store_names,
        "store_kinds": store_kinds,
        "coverages": coverages,
        "has_coverage": has_coverage,
        "batches": batches,
        "in_store": in_store,
        "written_by": written_by,
        "derived_from": derived_from,
        "lineage_gaps": lineage_gaps,
    }


def reset_and_import(
    db: "falkordb.FalkorDB", graph_name: str, fixture_root: Path, snapshots: list[str]
) -> dict:
    """Delete ``graph_name`` if present, import every release plus the named snapshots.

    Returns ``{"graph", "nodes", "edges", "snapshots"}`` where ``nodes``/``edges`` are
    counts read back from the graph and ``snapshots`` maps the plain snapshot name to
    its ``manifest_hash``.
    """
    fixture_root = Path(fixture_root)
    _drop_graph(db, graph_name)
    graph = db.select_graph(graph_name)

    (
        release_rows,
        excerpt_rows,
        route_rows,
        known_releases,
        declarations,
        has_source,
        executes_route,
    ) = _collect_releases(fixture_root)

    snapshot_data = [_collect_snapshot(fixture_root, name, known_releases) for name in snapshots]

    # Services: every release service plus every service a snapshot deploys.
    service_names = {row["service"] for row in release_rows}
    for data in snapshot_data:
        service_names.update(data["services"])

    # PREVIOUS edges: newer -> the explicit previous_version build of the same service.
    previous: list[dict[str, Any]] = []
    previous_ids: dict[str, str] = {}
    for entry in declarations:
        version = entry["declaration"].get("previous_version")
        if not version:
            continue
        older_id = known_releases.get((entry["declaration"]["service"], version))
        if older_id is None:
            continue
        previous.append({"from_id": entry["release_id"], "to_id": older_id})
        previous_ids[entry["release_id"]] = older_id

    # Routes read stores; a store declared only by a release still gets a node so the
    # route edge is honest, but only manifests carry kind/coverage.
    manifest_store_names: set[str] = set()
    store_kinds: dict[str, str] = {}
    for data in snapshot_data:
        manifest_store_names.update(data["store_names"])
        store_kinds.update(data["store_kinds"])
    route_store_edges: list[dict[str, Any]] = []
    for declaration in declarations:
        for route in declaration["declaration"].get("routes", []):
            store_name = route.get("reads_from")
            if not store_name:
                continue
            route_store_edges.append(
                {
                    "from_id": f"route:{declaration['release_id']}:{route['name']}",
                    "to_id": f"store:{store_name}",
                }
            )
    extra_stores = sorted(
        {
            row["to_id"].removeprefix("store:")
            for row in route_store_edges
            if row["to_id"].removeprefix("store:") not in manifest_store_names
        }
        | {
            store["store"]
            for declaration in declarations
            for store in declaration["declaration"].get("writes", [])
            if store.get("store") not in manifest_store_names
        }
    )

    # Write nodes, then edges, so nothing depends on a missing endpoint.
    _bulk_create(
        graph,
        "Service",
        [{"id": f"service:{name}", "scope_id": SCOPE_ID, "name": name} for name in sorted(service_names)],
    )
    _bulk_create(
        graph,
        "StateStore",
        [
            _write_props({"id": f"store:{name}", "scope_id": SCOPE_ID, "name": name, "kind": store_kinds.get(name)})
            for name in sorted(manifest_store_names)
        ]
        + [{"id": f"store:{name}", "scope_id": SCOPE_ID, "name": name} for name in extra_stores],
    )
    _bulk_create(graph, "Release", release_rows)
    for release_id, older_id in previous_ids.items():
        graph.query(
            "MATCH (r:Release {id: $id}) SET r.previous_release_id = $older",
            {"id": release_id, "older": older_id},
        )
    for entry in declarations:
        version = entry["declaration"].get("previous_version")
        if version:
            graph.query(
                "MATCH (r:Release {id: $id}) SET r.previous_version = $version",
                {"id": entry["release_id"], "version": version},
            )
    _bulk_create(graph, "SourceExcerpt", excerpt_rows)
    _bulk_create(graph, "ReaderRoute", route_rows)
    for data in snapshot_data:
        _bulk_create(graph, "Snapshot", [data["snapshot_row"]])
        _bulk_create(graph, "Deployment", data["deployments"])
        _bulk_create(graph, "Coverage", data["coverages"])
        _bulk_create(graph, "Batch", data["batches"])

    _bulk_edge(graph, "HAS_SOURCE", "Release", "SourceExcerpt", has_source)
    _bulk_edge(graph, "EXECUTES_ROUTE", "Release", "ReaderRoute", executes_route)
    _bulk_edge(graph, "READS_FROM", "ReaderRoute", "StateStore", route_store_edges)
    _bulk_edge(graph, "PREVIOUS", "Release", "Release", previous)
    for data in snapshot_data:
        _bulk_edge(graph, "HAS_DEPLOYMENT", "Snapshot", "Deployment", data["has_deployment"])
        _bulk_edge(graph, "RUNS", "Deployment", "Release", data["runs"])
        _bulk_edge(graph, "OF_SERVICE", "Deployment", "Service", data["of_service"])
        _bulk_edge(graph, "HAS_COVERAGE", "StateStore", "Coverage", data["has_coverage"])
        _bulk_edge(graph, "IN_STORE", "Batch", "StateStore", data["in_store"])
        _bulk_edge(graph, "WRITTEN_BY", "Batch", "Release", data["written_by"])
        _bulk_edge(graph, "DERIVED_FROM", "Batch", "Batch", data["derived_from"])

    nodes: dict[str, int] = {}
    for label in NODE_LABELS:
        nodes[label] = graph.ro_query(f"MATCH (n:{label}) RETURN count(n) AS c").result_set[0][0]
    edges: dict[str, int] = {}
    for edge_type in EDGE_TYPES:
        edges[edge_type] = graph.ro_query(
            f"MATCH ()-[e:{edge_type}]->() RETURN count(e) AS c"
        ).result_set[0][0]

    return {
        "graph": graph_name,
        "nodes": nodes,
        "edges": edges,
        "snapshots": {data["snapshot_row"]["name"]: data["manifest_hash"] for data in snapshot_data},
        "lineage_gaps": {data["snapshot_row"]["name"]: data["lineage_gaps"]
                         for data in snapshot_data if data["lineage_gaps"]},
    }


# --------------------------------------------------------------------------- reads


def current_fleet(graph: Any, snapshot_id: str, cap: int = QUERY_CAP):
    """Deployments recorded by one snapshot, with the release each one runs."""
    query = """
MATCH (s:Snapshot {id: $snapshot_id})-[:HAS_DEPLOYMENT]->(d:Deployment)
OPTIONAL MATCH (d)-[:RUNS]->(r:Release)
RETURN d.service AS service, d.id AS deployment_id, r.id AS release_id, d.version AS version,
       d.flags_json AS flags_json, r.declared_flags_json AS declared_flags_json,
       r.bundle_id AS bundle_id, r.built_at AS built_at
ORDER BY service
LIMIT $limit
"""
    return _read(
        graph,
        "current_fleet",
        query,
        {"snapshot_id": snapshot_id},
        (
            "service",
            "deployment_id",
            "release_id",
            "version",
            "flags",
            "declared_flags",
            "bundle_id",
            "built_at",
        ),
        cap,
        conv={"flags": _as_dict, "declared_flags": _as_list},
    )


def release_history(graph: Any, snapshot_id: str, service: str, max_depth: int = 5, cap: int = QUERY_CAP):
    """The deployment chain of one service: depth 0 is the running build."""
    query = f"""
MATCH (s:Snapshot {{id: $snapshot_id}})-[:HAS_DEPLOYMENT]->(d:Deployment {{service: $service}})-[:RUNS]->(r:Release)
MATCH path = (r)-[:PREVIOUS*0..{CHAIN_HOP_CAP}]->(p:Release)
WITH p, length(path) AS depth
WHERE depth <= $max_depth
OPTIONAL MATCH (p)-[:HAS_SOURCE]->(e:SourceExcerpt)
WITH p, depth, e ORDER BY depth, e.path, e.line_start
RETURN p.id AS release_id, p.service AS service, p.version AS version, depth,
       p.built_at AS built_at, p.bundle_id AS bundle_id,
       p.declared_flags_json AS declared_flags_json,
       p.previous_release_id AS previous_release_id,
       collect(CASE WHEN e IS NULL THEN null ELSE {{
           excerpt_id: e.id, kind: e.kind, path: e.path,
           span: toString(e.line_start) + '-' + toString(e.line_end),
           text: e.text, content_hash: e.content_hash
       }} END) AS excerpts
ORDER BY depth
LIMIT $limit
"""
    return _read(
        graph,
        "release_history",
        query,
        {"snapshot_id": snapshot_id, "service": service, "max_depth": max_depth},
        (
            "release_id",
            "service",
            "version",
            "depth",
            "built_at",
            "bundle_id",
            "declared_flags",
            "previous_release_id",
            "excerpts",
        ),
        cap,
        conv={
            "declared_flags": _as_list,
            "excerpts": lambda v: [_plain(item) for item in (v or [])],
        },
    )


def releases_for_service(graph: Any, service: str, cap: int = QUERY_CAP):
    """Every imported build of one service."""
    query = """
MATCH (r:Release {service: $service})
RETURN r.id AS release_id, r.version AS version, r.built_at AS built_at,
       r.bundle_id AS bundle_id, r.declared_flags_json AS declared_flags_json,
       r.codec_hash AS codec_hash
ORDER BY r.built_at, r.version
LIMIT $limit
"""
    return _read(
        graph,
        "releases_for_service",
        query,
        {"service": service},
        ("release_id", "version", "built_at", "bundle_id", "declared_flags", "codec_hash"),
        cap,
        conv={"declared_flags": _as_list},
    )


def get_excerpts(graph: Any, excerpt_ids: list[str], cap: int = QUERY_CAP):
    """Fetch source excerpts by id (order follows the request-independent excerpt id)."""
    query = """
MATCH (r:Release)-[:HAS_SOURCE]->(e:SourceExcerpt)
WHERE e.id IN $excerpt_ids
RETURN e.id AS excerpt_id, r.id AS release_id, e.kind AS kind, e.path AS path,
       e.line_start AS line_start, e.line_end AS line_end, e.text AS text,
       e.content_hash AS content_hash
ORDER BY e.id
LIMIT $limit
"""
    rows, log = _read(
        graph,
        "get_excerpts",
        query,
        {"excerpt_ids": list(excerpt_ids)},
        ("excerpt_id", "release_id", "kind", "path", "line_start", "line_end", "text", "content_hash"),
        cap,
    )
    ordered = [
        {
            "excerpt_id": row["excerpt_id"],
            "release_id": row["release_id"],
            "kind": row["kind"],
            "path": row["path"],
            "span": _span(row),
            "text": row["text"],
            "content_hash": row["content_hash"],
        }
        for row in rows
    ]
    return ordered, log


def store_readers(graph: Any, store_id: str, cap: int = QUERY_CAP):
    """Reader routes that read one store, with the snapshots currently running them."""
    query = """
MATCH (st:StateStore {id: $store_id})<-[:READS_FROM]-(rt:ReaderRoute)<-[:EXECUTES_ROUTE]-(r:Release)
OPTIONAL MATCH (d:Deployment)-[:RUNS]->(r)
OPTIONAL MATCH (sn:Snapshot)-[:HAS_DEPLOYMENT]->(d)
RETURN r.id AS release_id, r.service AS service, r.version AS version, rt.id AS route_id,
       rt.entry AS entry, collect(DISTINCT sn.id) AS currently_deployed_in
ORDER BY r.id, rt.id
LIMIT $limit
"""
    return _read(
        graph,
        "store_readers",
        query,
        {"store_id": store_id},
        ("release_id", "service", "version", "route_id", "entry", "currently_deployed_in"),
        cap,
        conv={"currently_deployed_in": _as_plain_list},
    )


ORIGIN_HOP_CAP = 4  # max DERIVED_FROM hops a record_origins walk follows


def record_origins(graph: Any, snapshot_id: str, record_ids: list[str], cap: int = QUERY_CAP,
                   *, batch_ids: list[str] | None = None):
    """Bounded provenance paths, with explicit completeness separate from compatibility.

    Inspect every path prefix and its declared parents. A missing edge, invalid declaration,
    cycle or depth/row cap must never turn a derived record into an apparent root.
    """
    query = f"""
MATCH (b:Batch {{snapshot_id: $snapshot_id}})
WHERE b.record_id IN $record_ids AND ($all_batches OR b.id IN $batch_ids)
MATCH path = (b)-[:DERIVED_FROM*0..{ORIGIN_HOP_CAP}]->(src:Batch)
OPTIONAL MATCH (src)-[:DERIVED_FROM]->(parent:Batch)
OPTIONAL MATCH (b)-[:WRITTEN_BY]->(bw:Release)
OPTIONAL MATCH (src)-[:WRITTEN_BY]->(w:Release)
RETURN b.id AS batch_id, b.record_id AS record_id, b.store_id AS store_id, bw.id AS writer_release_id,
       [n IN nodes(path) | n.record_id] AS chain, src.record_id AS origin_record,
       src.store_id AS origin_store_id, w.id AS origin_release_id, w.service AS origin_service,
       w.version AS origin_version, length(path) AS hops, src.id AS origin_batch_id,
       [n IN nodes(path) | n.id] AS chain_batches,
       [n IN nodes(path) | n.snapshot_id] AS chain_snapshots,
       src.lineage_valid AS lineage_valid, src.lineage_parents_json AS parents_json, parent.id AS parent_id
ORDER BY batch_id, hops, origin_batch_id, parent_id
LIMIT $limit
"""
    raw, log = _read(
        graph,
        "record_origins",
        query,
        {"snapshot_id": snapshot_id, "record_ids": sorted(set(record_ids)),
         "all_batches": batch_ids is None, "batch_ids": sorted(set(batch_ids or []))},
        ("batch_id", "record_id", "store_id", "writer_release_id", "chain", "origin_record", "origin_store_id",
         "origin_release_id", "origin_service", "origin_version", "hops", "origin_batch_id",
         "chain_batches", "chain_snapshots", "lineage_valid", "parents_json", "parent_id"),
        cap,
        conv={k: _as_plain_list for k in ("chain", "chain_batches", "chain_snapshots")},
    )
    gaps: set[tuple[str, str, str]] = set()
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in raw:
        groups.setdefault((row["batch_id"], row["origin_batch_id"]), []).append(row)
    roots = []
    for (batch, node), paths in groups.items():
        row = paths[0]
        try:
            expected = json.loads(row["parents_json"])
            valid = row["lineage_valid"] is True and isinstance(expected, list)
        except (ValueError, TypeError):
            expected, valid = [], False
        actual = {p["parent_id"] for p in paths if p["parent_id"]}
        if not valid:
            gaps.add((batch, node, "lineage declaration is unresolved"))
        if set(expected) != actual:
            gaps.add((batch, node, "declared lineage edges are missing or unexpected"))
        for path in paths:
            chain = path["chain_batches"]
            if len(set(chain)) != len(chain):
                gaps.add((batch, node, "lineage cycle"))
            if any(s != snapshot_id for s in path["chain_snapshots"]):
                gaps.add((batch, node, "lineage leaves the bound snapshot"))
            if path["hops"] == ORIGIN_HOP_CAP and actual:
                gaps.add((batch, node, "lineage depth cap reached"))
        if valid and not expected and not actual:
            # Multiple paths to one root remain paths; consumers count unique batches, not rows.
            seen = set()
            for path in paths:
                key = (tuple(path["chain_batches"]), path["origin_release_id"])
                if key in seen:
                    continue
                seen.add(key)
                roots.append({k: v for k, v in path.items()
                              if k not in ("chain_snapshots", "lineage_valid", "parents_json", "parent_id")})
    seen_batches = {r["batch_id"] for r in raw}
    if batch_ids is not None:
        for missing in set(batch_ids) - seen_batches:
            gaps.add((missing, missing, "requested batch is absent"))
    else:
        for missing in set(record_ids) - {r["record_id"] for r in raw}:
            gaps.add((missing, missing, "requested record is absent"))
    bad = {batch for batch, _, _ in gaps}
    for row in roots:
        row["lineage_complete"] = row["batch_id"] not in bad and not log["truncated"]
    log.update(raw_rows=log["rows"], rows=len(roots), complete=not gaps and not log["truncated"],
               gaps=[{"batch_id": b, "at": n, "reason": reason} for b, n, reason in sorted(gaps)])
    return roots, log


def plan_reader_routes(graph: Any, plan_id: str, cap: int = QUERY_CAP):
    """One row per candidate deployment route; route fields are None when there is none."""
    query = """
MATCH (p:Plan {id: $plan_id})-[:HAS_DEPLOYMENT]->(d:Deployment)
OPTIONAL MATCH (d)-[:RUNS]->(r:Release)
OPTIONAL MATCH (r)-[:EXECUTES_ROUTE]->(rt:ReaderRoute)
OPTIONAL MATCH (rt)-[:READS_FROM]->(st:StateStore)
RETURN d.service AS service, d.id AS deployment_id, r.id AS release_id, r.codec_hash AS codec_hash,
       r.codec_path AS codec_path, r.no_state_read AS no_state_read, rt.id AS route_id,
       rt.name AS route_name, rt.entry AS entry, rt.read_domain AS read_domain,
       rt.route_contract_hash AS route_contract_hash, st.id AS store_id
ORDER BY d.service, rt.name
LIMIT $limit
"""
    return _read(
        graph,
        "plan_reader_routes",
        query,
        {"plan_id": plan_id},
        (
            "service",
            "deployment_id",
            "release_id",
            "codec_hash",
            "codec_path",
            "no_state_read",
            "route_id",
            "route_name",
            "entry",
            "read_domain",
            "route_contract_hash",
            "store_id",
        ),
        cap,
    )


def store_inventory(graph: Any, snapshot_id: str, store_id: str, cap: int = QUERY_CAP):
    """Coverage row plus every Batch of one store in one snapshot.

    Batches are anchored on ``(store_id, snapshot_id)`` properties, not on edges, so a
    record with a missing IN_STORE edge (``in_store`` False) stays visible.
    """
    coverage_query = """
MATCH (st:StateStore {id: $store_id})
OPTIONAL MATCH (st)-[:HAS_COVERAGE]->(c:Coverage {snapshot_id: $snapshot_id})
RETURN c.id AS coverage_id, c.status AS status, c.inventory_id_hash AS inventory_id_hash
LIMIT $limit
"""
    coverage_rows, coverage_log = _read(
        graph,
        "store_inventory:coverage",
        coverage_query,
        {"snapshot_id": snapshot_id, "store_id": store_id},
        ("coverage_id", "status", "inventory_id_hash"),
        cap,
    )

    batch_query = """
MATCH (b:Batch {store_id: $store_id, snapshot_id: $snapshot_id})
OPTIONAL MATCH (b)-[:IN_STORE]->(st:StateStore {id: $store_id})
OPTIONAL MATCH (b)-[:WRITTEN_BY]->(w:Release)
RETURN b.id AS batch_id, b.record_id AS record_id, b.payload_hash AS payload_hash,
       b.payload_path AS payload_path, b.format_id AS format_id,
       (st IS NOT NULL) AS in_store, w.id AS writer_release_id
ORDER BY b.record_id
LIMIT $limit
"""
    batch_rows, batch_log = _read(
        graph,
        "store_inventory:batches",
        batch_query,
        {"snapshot_id": snapshot_id, "store_id": store_id},
        (
            "batch_id",
            "record_id",
            "payload_hash",
            "payload_path",
            "format_id",
            "in_store",
            "writer_release_id",
        ),
        cap,
    )

    coverage_row = coverage_rows[0] if coverage_rows and coverage_rows[0]["coverage_id"] else None
    log = {
        "name": "store_inventory",
        "params": batch_log["params"],
        "rows": (1 if coverage_row else 0) + len(batch_rows),
        "truncated": coverage_log["truncated"] or batch_log["truncated"],
    }
    return coverage_row, batch_rows, log


def obligation_paths(graph: Any, plan_id: str, snapshot_id: str, cap: int = QUERY_CAP):
    """The real multi-hop evidence path: plan reader route -> store <- retained batch."""
    query = """
MATCH (p:Plan {id: $plan_id})-[:HAS_DEPLOYMENT]->(d:Deployment)-[:RUNS]->(r:Release)-[:EXECUTES_ROUTE]->(rt:ReaderRoute)-[:READS_FROM]->(s:StateStore)<-[:IN_STORE]-(b:Batch {snapshot_id: $snapshot_id})
OPTIONAL MATCH (b)-[:WRITTEN_BY]->(w:Release)
RETURN p.id AS plan_id, d.id AS deployment_id, r.service AS service, r.id AS release_id,
       r.codec_hash AS codec_hash, rt.id AS route_id, s.id AS store_id, b.id AS batch_id,
       b.record_id AS record_id, b.payload_hash AS payload_hash, b.format_id AS format_id,
       w.id AS writer_release_id, w.version AS writer_version
ORDER BY d.id, b.record_id
LIMIT $limit
"""
    return _read(
        graph,
        "obligation_paths",
        query,
        {"plan_id": plan_id, "snapshot_id": snapshot_id},
        (
            "plan_id",
            "deployment_id",
            "service",
            "release_id",
            "codec_hash",
            "route_id",
            "store_id",
            "batch_id",
            "record_id",
            "payload_hash",
            "format_id",
            "writer_release_id",
            "writer_version",
        ),
        cap,
    )


# --------------------------------------------------------------------------- writes


def write_plan(graph: Any, plan: CandidatePlan) -> str:
    """MERGE the candidate plan and its candidate deployments; returns the plan id.

    Idempotent: a second call adds no node and no edge. A fleet entry whose release is
    absent from the graph gets no RUNS edge (and therefore no deployment node).
    """
    plan_id = plan.plan_id()
    fleet = sorted(
        (
            {
                "service": entry.service,
                "release_id": entry.release_id,
                "flags_json": canonical_json(entry.flags).decode("utf-8"),
            }
            for entry in plan.fleet
        ),
        key=lambda entry: entry["service"],
    )
    fleet_json = canonical_json(fleet).decode("utf-8")
    query = """
MERGE (p:Plan {id: $plan_id})
SET p.scope_id = $scope_id, p.plan_hash = $plan_hash, p.snapshot_id = $snapshot_id,
    p.origin = $origin, p.label = $label, p.fleet_json = $fleet_json
WITH p
MATCH (sn:Snapshot {id: $snapshot_id})
MERGE (p)-[:BASED_ON]->(sn)
WITH p
UNWIND $fleet AS f
MATCH (rel:Release {id: f.release_id})
MERGE (dep:Deployment {id: 'deployment:' + $plan_id + ':' + f.service})
ON CREATE SET dep.scope_id = $scope_id
SET dep.service = f.service, dep.release_id = f.release_id, dep.plan_id = $plan_id,
    dep.flags_json = f.flags_json
MERGE (p)-[:HAS_DEPLOYMENT]->(dep)
MERGE (dep)-[:RUNS]->(rel)
MERGE (svc:Service {id: 'service:' + f.service})
ON CREATE SET svc.scope_id = $scope_id
MERGE (dep)-[:OF_SERVICE]->(svc)
"""
    graph.query(
        query,
        {
            "plan_id": plan_id,
            "plan_hash": plan.plan_hash(),
            "scope_id": plan.scope_id,
            "snapshot_id": plan.snapshot_id,
            "origin": plan.origin,
            "label": plan.label,
            "fleet_json": fleet_json,
            "fleet": fleet,
        },
    )
    return plan_id


def write_receipt(graph: Any, receipt: ProbeReceipt) -> str:
    """MERGE one ProbeRun bound to its obligation, reader release and batch.

    probe_id = ``probe:<short(receipt_hash)>``: deterministic per receipt content, so
    re-writing the same receipt is a no-op. Missing release/batch -> no edge.
    """
    probe_id = f"probe:{short(receipt.receipt_hash())}"
    query = """
MERGE (pr:ProbeRun {id: $probe_id})
SET pr.scope_id = $scope_id, pr.obligation_hash = $obligation_hash, pr.plan_hash = $plan_hash,
    pr.snapshot_id = $snapshot_id, pr.result = $result, pr.receipt_json = $receipt_json,
    pr.executed_at = $executed_at
WITH pr
OPTIONAL MATCH (r:Release {id: $release_id})
FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END | MERGE (pr)-[:TESTS_READER]->(r))
WITH pr
OPTIONAL MATCH (b:Batch {id: $batch_id})
FOREACH (_ IN CASE WHEN b IS NULL THEN [] ELSE [1] END | MERGE (pr)-[:TESTS_BATCH]->(b))
"""
    graph.query(
        query,
        {
            "probe_id": probe_id,
            "scope_id": receipt.tuple.scope_id,
            "obligation_hash": receipt.obligation_hash,
            "plan_hash": receipt.tuple.plan_hash,
            "snapshot_id": receipt.tuple.snapshot_id,
            "result": receipt.result.value,
            "receipt_json": receipt.model_dump_json(),
            "executed_at": receipt.executed_at,
            "release_id": receipt.tuple.release_id,
            "batch_id": receipt.tuple.batch_id,
        },
    )
    return probe_id


def receipts_for(graph: Any, obligation_hashes: list[str], cap: int = QUERY_CAP):
    """Receipts stored for the given obligation hashes (historical copies included)."""
    query = """
MATCH (pr:ProbeRun)
WHERE pr.obligation_hash IN $obligation_hashes
RETURN pr.id AS probe_id, pr.obligation_hash AS obligation_hash, pr.result AS result,
       pr.receipt_json AS receipt_json
ORDER BY pr.obligation_hash, pr.id
LIMIT $limit
"""
    return _read(
        graph,
        "receipts_for",
        query,
        {"obligation_hashes": list(obligation_hashes)},
        ("probe_id", "obligation_hash", "result", "receipt_json"),
        cap,
    )


def receipts_by_id(graph: Any, probe_ids: list[str], cap: int = QUERY_CAP):
    """Probe receipts for exactly the given ProbeRun ids — fresh receipts only.

    ``receipts_for`` selects by obligation hash, so every historical ProbeRun copy competes for
    the same cap; this reads back a verification's own receipts without them, whatever their
    history. A cap+1 result is still reported ``truncated`` by ``_read`` and missing ids simply
    return no row, so a truncated or absent receipt stays visible as an evidence gap.
    Returns the same columns as ``receipts_for``.
    """
    query = """
MATCH (pr:ProbeRun)
WHERE pr.id IN $probe_ids
RETURN pr.id AS probe_id, pr.obligation_hash AS obligation_hash, pr.result AS result,
       pr.receipt_json AS receipt_json
ORDER BY pr.obligation_hash, pr.id
LIMIT $limit
"""
    return _read(
        graph,
        "receipts_by_id",
        query,
        {"probe_ids": list(probe_ids)},
        ("probe_id", "obligation_hash", "result", "receipt_json"),
        cap,
    )
