# RollbackWitness architecture

How the product is put together: graph schema, the fixed graph operations, the tool contracts and the
evidence/action invariants trusted code enforces. [CONTRACTS.md](CONTRACTS.md) is the exact
field-level reference; [QUICKSTART.md](QUICKSTART.md) runs it; [STATUS.md](STATUS.md) records what has
actually been observed.

## Components and trust boundary

- **Grounding agent (one runtime agent):** interprets the behavioral request, reads source excerpts, cites the actual artifact, and proposes an exact available fleet or a specific clarification.
- **Deterministic checker (trusted code):** validates exact sets, runs bounded graph queries, enumerates obligations, executes allowlisted probes and computes disposition.
- **FalkorDB:** snapshots, deployments, releases, reader routes, stores, retained batches/records, source excerpts, plans and probe receipts; relationships select retrieved context and expose the witness behind a result.
- **API, one evidence-led screen, local approval-bound simulator.**

Interpretation happens **before** the mandatory compatibility check: the agent must actually change the candidate or clarification, not narrate a precomputed verdict. It may read and propose but not waive checks, change receipt status, execute code, write arbitrary Cypher, pick real deployment targets or approve its own action. Trusted code owns identity, permissions, graph keys, caps, obligations, probe execution, disposition, freshness, approval and idempotency. Excerpt text is untrusted data.

## Graph schema

Every node carries a server-controlled `scope_id` and an immutable logical `id`, both written by the importer, so nothing a model produces can select or name graph data. A property the source file does not supply is omitted, never stored as `null` (FalkorDB stores no nulls), and trusted code detects the missing fact by comparing the graph with the independently parsed file.

| Label | Properties written, beyond `scope_id` and `id` |
|---|---|
| Service | name |
| Release | service, version, artifact_hash, codec_hash, codec_path, built_at, bundle_id (omitted when null), declared_flags_json, no_state_read, previous_release_id |
| SourceExcerpt | release_id, kind (`changelog` per notes bullet/paragraph, `code` per top-level `def`), path, line_start, line_end, text, content_hash |
| Deployment | service, version, release_id, snapshot_id, flags_json; plan candidate deployments also carry plan_id |
| ReaderRoute | release_id, name, entry, read_domain, contract, route_contract_hash |
| StateStore | name, kind (only when a manifest declares it) |
| Batch | store_id, snapshot_id, record_id, payload_hash, payload_path, format_id; the writer is an edge, not a property |
| Snapshot | name, manifest_hash, captured_at, environment, captured_from |
| Coverage | snapshot_id, store_id, status (COMPLETE/PARTIAL/UNKNOWN), inventory_id_hash |
| Plan | plan_hash, snapshot_id, origin, label, fleet_json |
| ProbeRun | obligation_hash, plan_hash, snapshot_id, result (PASS/FAIL/UNKNOWN), receipt_json, executed_at |

`SourceExcerpt` is the only added label, so the graph returns provenance-bound raw evidence; no preclassified answer edges are imported, and `bundle_id` is investigation metadata, never authorization.

## Directed edges

- Snapshot-HAS_DEPLOYMENT->Deployment; Deployment-OF_SERVICE->Service; Deployment-RUNS->Release.
- Release-PREVIOUS->Release (newer build to the explicit previous build of the same service; not semantic inheritance).
- Release-HAS_SOURCE->SourceExcerpt (same artifact/content identity).
- Release-EXECUTES_ROUTE->ReaderRoute; ReaderRoute-READS_FROM->StateStore.
- Batch-IN_STORE->StateStore; Batch-WRITTEN_BY->Release.
- StateStore-HAS_COVERAGE->Coverage.
- Plan-HAS_DEPLOYMENT->candidate Deployment; Plan-BASED_ON->Snapshot.
- ProbeRun-TESTS_READER->Release; ProbeRun-TESTS_BATCH->Batch.
- Service-CALLS->Service does not exist in the schema or the fixture: a decoder is never inferred from caller topology.

Critical path: `Plan -> Deployment -> Release -> ReaderRoute -> StateStore <- Batch -> writer Release -> SourceExcerpt`. Pre-checker source path: current `Deployment -> Release -> bounded PREVIOUS history -> SourceExcerpt`. Both drive the real loop; a picture of a precomputed answer fails.

## Fixed graph operations (`src/rw/graph.py`)

Every product read query is fixed and parameterized — no APOC, no string-concatenated or model-supplied Cypher, no user text inside a query string — and runs through `ro_query` with `LIMIT $cap + 1`: a `cap + 1` result sets `log["truncated"]` and returns only `cap` rows, so a cap is never mistaken for completeness. The operations the product actually uses:

- `current_fleet`, `release_history` (bounded `PREVIOUS` chain, ≤ 5) and `releases_for_service`, plus `get_excerpts`: the artifact candidates with their declared flags, and the version-linked source excerpts the grounding agent may cite.
- `store_readers`: which releases execute a reader route that reads a store. Impact context only — never an inferred decoder.
- `plan_reader_routes`, `store_inventory` and `obligation_paths`: the multi-hop `Plan-HAS_DEPLOYMENT->Deployment-RUNS->Release-EXECUTES_ROUTE->ReaderRoute-READS_FROM->StateStore<-IN_STORE-Batch` query that yields one obligation per executing reader × retained record, with the optional `Batch-WRITTEN_BY->Release` writer hop that supplies the witness path.
- `receipts_for` and `receipts_by_id`: probe receipts bound to exact obligation hashes; verification reads back exactly the ProbeRun ids it wrote, so stored history cannot push fresh receipts past the cap.
- `write_plan` and `write_receipt`: the only writes after import, both `MERGE`-idempotent (`reset_and_import` re-imports the scope graph itself).

## Identity, provenance and time

IDs are scope-, artifact/content- and source-qualified; version and display names are aliases, never identity. Aliases are resolved only from independently loaded declarations — an ambiguous or contradictory pair produces a clarification or a gap (`INVALID_FLEET`), never a guessed merge. Batch identity is (scope, store, snapshot, source record ID, payload hash), so the same display key with changed bytes is a new observed version. Excerpts bind to the release's artifact hash and their own content hash with quoted spans, and a model-extracted interpretation is a proposed claim, not truth. Any exact plan/source/snapshot/environment change invalidates prior approval, and a receipt is applicable only under its own obligation hash — prior receipts are never reused.

## Completeness and missingness

Every candidate deployment resolves to exact release/read routes or explicit no-read evidence; nulls stay unknown. Every store has snapshot-specific coverage, and exact source record ID sets and edge sets are compared independently of traversal — counts or successful traversal do not prove completeness. Query truncation/cap is incomplete; missing writer/format/route/source metadata must not vanish in joins. Key-lookup fixture routes must be able to request every scoped record, else read-domain uncertainty stays unknown.

## Receipt contract

A canonical receipt binds scope, plan, snapshot/inventory, deployment, executing release/codec, route hash/contract, store, record/payload, format **or the literal `UNKNOWN`**, probe specification and environment. The proof is byte/shape readability only, never overall production safety or semantic correctness.

- A source note claiming compatibility cannot discharge an obligation.
- Co-bundling does not establish atomic rollback; ancestry does not establish fix preservation.
- Disabling a feature does not make retained records written by the newer code readable.

## Disposition

Trusted code computes, in precedence order:

- **BLOCKED** — any applicable reachable incompatibility witness, even when other coverage is incomplete (fail dominance).
- **NEEDS_EVIDENCE** — no such witness, but some required scope, route, inventory, identity, freshness or probe information is unresolved; unknown never silently becomes pass.
- **BOUNDED_PASS** — every modeled obligation has a current applicable PASS receipt. Complete applicable passes only, and limited to byte/shape readability of the modeled records.

A harness failure or timeout is UNKNOWN, distinct from an observed incompatibility.

## Approval, simulation and idempotency

Only allowlisted authored fixture readers run, with bounded input/output and timeouts; a subprocess is failure containment, not a network sandbox. Scope confirmation and action approval are separate, and the model cannot approve its own action. When nothing passes, surface a truthful blocked/unknown result and never expose an eligible action button. Local simulation needs a fresh approval/current-state guard and must be idempotent; changed relevant evidence invalidates eligibility, so approval is scoped to the exact canonical tuple.

## Graph contribution

Actual executing readers matter; service callers do not automatically decode what they call. The graph selects source context, derives the obligations for the proposed fleet, and exposes the witness behind a result. Removing the relationship operations while keeping the raw records would remove this connected source lookup, the obligation set and the witness path. A complete SQL/BFS control can reproduce the obligation logic and is a fair, un-handicapped comparison; the shipped proof still requires actual FalkorDB — another database, or a drawn graph, is not a substitute.

## Out of scope

Production deployment, broad connectors, repository-wide analysis, arbitrary generated Cypher or code, data migrations, semantic-unit verification, general incident management, autonomous swarms and cross-session company memory.
