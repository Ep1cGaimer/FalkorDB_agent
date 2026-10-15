# Frozen contracts — slice 1

Owner: Opus (orchestrator). Workers may not change this file or `src/rw/contracts.py`; request changes in their handoff. Everything here is synthetic fixture data.

## Verified runtime (2026-10-15)

| Item | Observed |
|---|---|
| Server | Docker image `falkordb/falkordb:6.0.2` (digest `sha256:107455e862a8…`), graph module ver `60002`, Redis 8.10.2, container `rw-falkordb` bound to `127.0.0.1:6379` |
| Client | `falkordb` 1.8.0 (redis 8.1.0) in `.venv` (Python 3.12, uv with project-local `.uv-cache`) |
| Module defaults | `TIMEOUT 1000` ms, `RESULTSET_SIZE 10000`, `MAX_QUEUED_QUERIES 25` |
| Behaviors observed | parameterized `$params` work; `ro_query` rejects writes; APOC absent; **a property set to `null` is not stored** — reading it returns `None`, identical to an absent property |

Consequence of the null behavior: unknowns can never be recorded as graph nulls. The importer omits unknown properties/edges, and trusted code detects them by comparing graph results with the independently parsed manifest (missing edge → explicit gap row).

## Scope and graph

- `SCOPE_ID = "fixture-shop"`; graph name `rw_fixture_shop` (server constant; test runs use `rw_test_<suffix>`). Never derived from user/model text.
- Every node carries `scope_id` and `id`.

## Canonical hashing

`canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`; `h(obj) = "sha256:" + sha256(canonical_json(obj)).hexdigest()`; byte hash `bh(b) = "sha256:" + sha256(b).hexdigest()`. Lists that are sets are sorted before hashing.

## Identity rules

| Entity | ID |
|---|---|
| Service | `service:<name>` |
| Release | `release:<service>:<artifact_hash[7:23]>` (16 hex chars after `sha256:`); `version` is a display alias only |
| artifact_hash | `h([[relpath, bh(bytes)] for every file in the release dir, sorted by relpath, posix paths]])` |
| codec_hash | `bh(codec.py bytes)` |
| SourceExcerpt | `excerpt:<artifact_hash[7:23]>:<relpath>:<start>-<end>` (1-based inclusive line span); `content_hash = bh(text.encode())` |
| ReaderRoute | `route:<release_id>:<route_name>`; `route_contract_hash = h(route declaration dict)` |
| StateStore | `store:<name>` |
| Batch | `batch:<store>:<snapshot_id>:<record_id>:<payload_hash[7:23]>` |
| Snapshot | `snapshot:<name>`; `manifest_hash = bh(manifest.json bytes)` |
| Plan | `plan:<plan_hash[7:23]>` |

## Fixture layout (`fixtures/shop/`)

```text
releases/<service>-<version>/release.json   declared facts (no compatibility verdicts)
releases/<service>-<version>/codec.py       real reader/writer code for that build
releases/<service>-<version>/CHANGELOG.md   human release notes (source excerpts)
snapshots/<name>/manifest.json              deployments, stores, coverage, inventory
payloads/<record_id>.bin                    retained bytes, produced by scripts/build_fixture.py from writer code
harness/run_reader.py                       trusted probe harness (allowlisted)
```

`release.json`:

```json
{"service": "cart", "version": "1.5", "previous_version": "1.4", "built_at": "2026-10-06T09:00:00Z",
 "bundle_id": "rollout-2026-10-basket",
 "routes": [{"name": "load_saved_cart", "reads_from": "cart-cache", "entry": "read_cart",
             "read_domain": "ALL_KEYS", "contract": "saved-cart"}],
 "writes": [{"store": "cart-cache", "entry": "write_cart"}],
 "flags": [{"name": "basket_v2", "default": true}],
 "no_state_read": false}
```

`bundle_id` may be `null`; `previous_version` is `null` for the first build. `read_domain` ∈ `ALL_KEYS | UNKNOWN`.

`snapshots/<name>/manifest.json`:

```json
{"snapshot": "snap-001", "captured_at": "2026-10-15T08:00:00Z", "environment": "fixture-local",
 "deployments": [{"service": "cart", "version": "1.5", "flags": {"basket_v2": true}}, ...],
 "stores": [{"name": "cart-cache", "kind": "kv-cache", "coverage": "COMPLETE",
             "records": [{"record_id": "saved-cart-1001", "payload": "payloads/saved-cart-1001.bin",
                          "payload_hash": "sha256:...", "writer": {"service": "cart", "version": "1.4"},
                          "format": "cart/v1"}]}]}
```

`writer` and `format` may be `null` (unknown). `coverage` ∈ `COMPLETE | PARTIAL | UNKNOWN`.

## Graph schema (written by the importer only)

Labels: Service, Release, SourceExcerpt, Snapshot, Deployment, ReaderRoute, StateStore, Batch, Coverage, Plan, ProbeRun.
Edges: `Snapshot-HAS_DEPLOYMENT->Deployment`, `Deployment-OF_SERVICE->Service`, `Deployment-RUNS->Release`, `Release-PREVIOUS->Release`, `Release-HAS_SOURCE->SourceExcerpt`, `Release-EXECUTES_ROUTE->ReaderRoute`, `ReaderRoute-READS_FROM->StateStore`, `Batch-IN_STORE->StateStore`, `Batch-WRITTEN_BY->Release`, `StateStore-HAS_COVERAGE->Coverage`, `Plan-HAS_DEPLOYMENT->Deployment`, `Plan-BASED_ON->Snapshot`, `ProbeRun-TESTS_READER->Release`, `ProbeRun-TESTS_BATCH->Batch`.
No edge or property encodes a compatibility verdict. `bundle_id` is investigation metadata only.

## Probe protocol (byte/shape family `byte_shape_v1`)

`python -I fixtures/shop/harness/run_reader.py <codec_path> <entry>` with payload bytes on stdin (max 64 KiB), timeout 5 s, stdout capped at 8 KiB. The harness loads `codec.py` by path and calls `entry(data: bytes) -> dict`.

| Harness exit | Meaning | Receipt result |
|---|---|---|
| 0, stdout `{"status":"PASS","shape":{...}}` | reader returned a dict | PASS |
| 10, stdout `{"status":"FAIL","error_type":..,"message":..}` | reader raised while reading these bytes | FAIL |
| 20 or any other exit, timeout, bad stdout | harness could not load/call the reader | UNKNOWN (harness error, never FAIL) |

`probe_spec_hash = h({"family":"byte_shape_v1","harness_hash":bh(run_reader.py),"entry":entry,"timeout_s":5,"max_input":65536})`; `environment_hash = h({"python": sys.version_info[:3] as list, "platform": sys.platform, "harness_hash": ...})`.

## Obligation and receipt binding

An obligation is one (executing reader route under a plan) × (retained record in a store that route reads) pair. Its canonical tuple — every field below — hashes to `obligation_hash`; a receipt is applicable only if it carries the identical tuple hash **and** identical fields. Format unknown is the literal `"UNKNOWN"`; `semantic_scope` is always `"BYTE_SHAPE_ONLY"`.

## Disposition precedence (trusted code only)

1. Any applicable FAIL receipt → `BLOCKED` (even with incomplete coverage or other gaps).
2. Else any gap (missing route/no-read evidence, unknown read domain, coverage ≠ COMPLETE, inventory ID-set mismatch, missing writer/IN_STORE edge, truncation, invalid fleet, missing/UNKNOWN/inapplicable receipt) → `NEEDS_EVIDENCE`.
3. Else → `BOUNDED_PASS` (modeled byte/shape readability only).

## Scope confirmation vs action approval

Scope confirmation (human confirms the grounded fleet) permits checking. Action approval is a separate human call bound to `plan_hash`, `verification_hash`, `snapshot manifest_hash`; only allowed for `BOUNDED_PASS`; idempotency key = `h([plan_hash, verification_hash])`. The model can do neither.

## Module API (frozen signatures; one owner per file)

Every graph query function returns `(rows, log)` where `rows` is a list of plain dicts with exactly the keys listed and `log = {"name": str, "params": dict, "rows": int, "truncated": bool}`. Unknown values are `None` in rows (never invented). Queries use `LIMIT $cap + 1` with `cap = QUERY_CAP`; if `cap+1` rows return, set `truncated=True` and return only `cap` rows. All reads use `ro_query`. No string-concatenated user/model input in Cypher; parameters only.

### `src/rw/graph.py` (owner: DeepSeek graph worker)

```python
connect(host="127.0.0.1", port=6379) -> falkordb.FalkorDB
reset_and_import(db, graph_name: str, fixture_root: Path, snapshots: list[str]) -> dict
    # deletes graph_name if it exists, imports all releases + the named snapshots; returns
    # {"graph": name, "nodes": {label: n}, "edges": {type: n}, "snapshots": {name: manifest_hash}}
current_fleet(g, snapshot_id) -> rows: service, deployment_id, release_id, version, flags (dict), declared_flags (list), bundle_id, built_at
release_history(g, snapshot_id, service, max_depth=5) -> rows: release_id, service, version, depth, built_at, bundle_id,
    declared_flags (list), previous_release_id, excerpts (list of {excerpt_id, kind, path, span, text, content_hash})
releases_for_service(g, service) -> rows: release_id, version, built_at, bundle_id, declared_flags, codec_hash
get_excerpts(g, excerpt_ids: list[str]) -> rows: excerpt_id, release_id, kind, path, span, text, content_hash
store_readers(g, store_id) -> rows: release_id, service, version, route_id, entry, currently_deployed_in (list of snapshot ids)
write_plan(g, plan: CandidatePlan) -> plan_id            # idempotent MERGE; candidate Deployment id = f"deployment:{plan_id}:{service}"
plan_reader_routes(g, plan_id) -> rows: service, deployment_id, release_id, codec_hash, codec_path, no_state_read,
    route_id, route_name, entry, read_domain, route_contract_hash, store_id   # one row per (deployment, route); route fields None if no route
store_inventory(g, snapshot_id, store_id) -> (coverage_row | None, batch_rows, log)
    # coverage_row: coverage_id, status, inventory_id_hash ; batch_rows anchored on Batch{store_id, snapshot_id} (NOT via edges):
    # batch_id, record_id, payload_hash, payload_path, format_id, in_store (bool: IN_STORE edge to this store exists), writer_release_id
obligation_paths(g, plan_id, snapshot_id) -> rows: plan_id, deployment_id, service, release_id, codec_hash, route_id, store_id,
    batch_id, record_id, payload_hash, format_id, writer_release_id, writer_version
    # the multi-hop path Plan-HAS_DEPLOYMENT->Deployment-RUNS->Release-EXECUTES_ROUTE->ReaderRoute-READS_FROM->StateStore<-IN_STORE-Batch{snapshot_id}
    # with OPTIONAL MATCH (Batch)-WRITTEN_BY->(writer Release)
write_receipt(g, receipt: ProbeReceipt) -> probe_id
receipts_for(g, obligation_hashes: list[str]) -> rows: probe_id, obligation_hash, result, receipt_json
```

Release node properties: id, service, version, artifact_hash, codec_hash, codec_path (posix, relative to repo root), built_at, bundle_id (omitted if null), declared_flags_json, no_state_read. Excerpts: one per CHANGELOG bullet/paragraph (`kind="changelog"`) and one per top-level `def` in codec.py (`kind="code"`), with 1-based inclusive line spans.

### `src/rw/verification.py` (owner: orchestrator)

```python
load_manifest(fixture_root, snapshot) -> (manifest: dict, manifest_hash: str)   # independent of the graph
materialize_plan(proposal, current_fleet_rows, release_rows_by_service, snapshot_id, manifest_hash, request_text, origin, label) -> (CandidatePlan | None, errors)
validate_citations(citations, excerpt_rows) -> errors
build_evidence(plan, manifest, route_rows, inventories, path_rows, probe_spec_for) -> GraphEvidence
dispose(evidence, receipts) -> VerificationResult
```

### `src/rw/probes.py` (owner: Sol)

```python
harness_path() -> Path; probe_spec_hash(entry) -> str; environment_hash() -> str
run_probe(obligation: Obligation, payload_path: Path, timeout_s=5) -> ProbeReceipt   # subprocess, -I, bounded I/O; timeout/harness error -> UNKNOWN
```

### `src/rw/grounding.py` (owner: Sonnet)

A bounded tool loop (≤ 8 model turns) over read-only tools `current_fleet`, `release_history`, `store_readers`, `get_excerpts` and terminal tools `propose_fleet(changes, citations, rationale)` / `ask_clarification(question, unresolved, citations)`. Returns `GroundingResult`. Live provider: Gemini API `gemini-3.8-flash` via `GEMINI_API_KEY`; transcripts saved for labeled replay (`live=False`).

### `src/rw/simulation.py` (owner: Sol)

SQLite ledger under `artifacts/sim.sqlite`; `record_approval(db_path, approval, verification, forbidden_identities)`, `simulate(db_path, approval, verification, current_manifest_hash, current_fleet, plan) -> SimulationReceipt` (raises `SimulationRefused`); rejects non-BOUNDED_PASS, stale manifest/plan/verification, and applies each idempotency key once.

### ID-form clarification (binding)

`snapshot_id` everywhere (params, Batch/Coverage/Plan properties, `CandidatePlan.snapshot_id`, `ObligationTuple.snapshot_id`) is the node form `snapshot:<name>`; `store_id` is `store:<name>`. Batch id = `batch:<store_name>:<snapshot_name>:<record_id>:<short(payload_hash)>`. Release `codec_path` and Batch `payload_path` are posix paths relative to the repo root.
