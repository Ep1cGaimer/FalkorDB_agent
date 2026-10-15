# RollbackWitness architecture

## Purpose and status

Build spec for the product in [PRODUCT.md](PRODUCT.md): graph schema, tool contracts and the evidence/action invariants trusted code enforces. A contract, not verified behavior.

**Status: proposed, not proven.** No FalkorDB query, client decode, probe run or end-to-end loop has been executed here. FalkorDB **v6.0.2** is the proposed pin, to be validated against the actual client before any query-compatibility claim. Sequence: [BUILD_PLAN.md](BUILD_PLAN.md); ownership: [TASKS.md](TASKS.md); verified state and blockers: [STATUS.md](STATUS.md).

## Components and trust boundary

- **Grounding agent (one runtime agent):** interprets the behavioral request, reads source excerpts, cites the actual artifact, and proposes an exact available fleet or a specific clarification.
- **Deterministic checker (trusted code):** validates exact sets, runs bounded graph queries, enumerates obligations, executes allowlisted probes and computes disposition.
- **FalkorDB:** snapshots, releases, routes, stores, batches and excerpts; relationships select retrieved context and expose the witness behind a result.
- **API, one evidence-led screen, local approval-bound simulator.**

Interpretation happens **before** the mandatory compatibility check: the agent must actually change the candidate or clarification, not narrate a precomputed verdict. It may read and propose but not waive checks, change receipt status, execute code, write arbitrary Cypher, pick real deployment targets or approve its own action. Trusted code owns identity, permissions, graph keys, caps, obligations, probe execution, disposition, freshness, approval and idempotency. Excerpt text is untrusted data.

## Graph schema

Every entity carries server-controlled `scope_id` plus immutable logical `id`, `source_ref`, `source_hash`, `observed_at` and `snapshot_id` where applicable.

| Label | Properties beyond the common set |
|---|---|
| Service | name, explicit aliases |
| Release | service_id, artifact_hash, built_at, bundle_id (nullable), codec_hash |
| SourceExcerpt | release_id, artifact_hash, text, source_span, kind, content_hash, source_revision, valid_from/valid_to when explicitly known |
| Deployment | service_id, release_id, environment_hash, source-backed no_state_read declaration if applicable |
| ReaderRoute | route_hash, executing_codec_hash, route_contract_hash, read_domain declaration |
| StateStore | store_id, kind, source manifest reference |
| Batch | store_id, snapshot_id, record_id, payload_hash, nullable format_id, writer_artifact_hash; one fixture record per Batch |
| Snapshot | immutable manifest_hash, captured_at, environment_hash |
| Coverage | store_id, snapshot_id, COMPLETE/PARTIAL/UNKNOWN, exact inventory_id_hash, source_hash |
| Plan | requested_text_hash, exact fleet/flags hash, base_snapshot_hash, source_hashes, proposed_scope, approval binding, disposition, simulator receipt |
| ProbeRun | full obligation_hash, probe_spec_hash, environment_hash, PASS/FAIL/UNKNOWN, evidence_uri/hash, executed_at |

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
- Service-CALLS->Service is optional impact explanation only; never infer a decoder from caller topology.

Critical path: `Plan -> Deployment -> Release -> ReaderRoute -> StateStore <- Batch -> writer Release -> SourceExcerpt`. Pre-checker source path: current `Deployment -> Release -> bounded PREVIOUS history -> SourceExcerpt`. Both drive the real loop; a picture of a precomputed answer fails.

## Identity, provenance and time

IDs are scope-, artifact/content- and source-qualified; version/display names are aliases, not identity. Resolve aliases only from evidence; ambiguity or conflicting artifacts yields clarification/UNKNOWN, never a guessed merge. Batch identity is (scope, store, snapshot, source record ID, payload hash); the same display key with a changed payload is a new observed version. Excerpts bind to immutable artifact and content hash with quoted spans in every interpretation; model-extracted interpretations are proposed claims, not truth. Snapshot observed time is distinct from source-stated validity time; corrections supersede rather than silently rewrite. Exact plan/source/snapshot/environment changes invalidate prior approval. Previous-receipt reuse is excluded; later memory may reuse only a full applicable canonical tuple with fresh coverage, and new interactions rerun current eligibility.

## Seven fixed graph operations

Proposed fixed, parameterized operations with bounded limits (cap + 1) and exact-set checks; no APOC or arbitrary procedures.

1. **Which actual artifact contains the change/fix named?** Traversal: current Deployment -> Release -> bounded PREVIOUS chain -> HAS_SOURCE excerpts + alias lookup. Result: artifact IDs/hashes, predecessor IDs/times, span/text/hash, nulls/conflicts. Use: bind request phrases to candidates; ask when referent/provenance is unresolved; never assert inheritance. Limit: similarity seeds excerpts but cannot join exact current artifact, chronology and provenance.
2. **What fleet would my rollback run?** Traversal: source-ID-anchored Deployment -> Release -> all declared ReaderRoutes -> StateStore, separate fixed steps. Result: exact fleet rows, routes, stores, no-read declarations, missing IDs/edges. Use: show exact candidate scope for human review; separate attainable, inseparable and ambiguous requests. Limit: similarity cannot enumerate every candidate decoder or preserve missing declarations.
3. **What retained state is in scope?** Traversal: independently anchor stores/Coverage by snapshot and Batches by store/snapshot; inspect IN_STORE and WRITTEN_BY separately. Result: exact record IDs/payload hashes, nullable writer/format links, per-store coverage, source mismatches. Use: ask for inventory/classification and expose unknowns; never infer emptiness from a failed join. Limit: sampling cannot establish complete ID sets or reveal orphaned records.
4. **Which readers could encounter which records?** Traversal: Plan -> Deployment -> Release -> ReaderRoute -> StateStore <- Batch -> writer Release. Result: canonical obligation tuples with witness path plus separate unresolved-gap rows. Use: select relevant evidence context and explain what retained state constrains. Limit: vector matching cannot enumerate candidate-specific reachability; complete SQL/BFS is a fair control.
5. **Do we have applicable observed proof?** Traversal: each obligation hash -> ProbeRun bound to exact reader, route contract, record payload, snapshot, probe/environment. Result: exact PASS/FAIL/UNKNOWN receipt with evidence hash/span, or null. Use: request the missing probe, explain failure or uncertainty, revise the proposal. Limit: a similar test under a different tuple is not applicable proof.
6. **Would the known alternative change that outcome?** Traversal: recompute operations 2–5 for the second explicit candidate with its own fleet/flag/source/plan hash. Result: two evidence sets/dispositions and their differences. Use: offer the independently verified alternative or abstain; no hybrid generation. Limit: answer text cannot recompute changed-reader obligations or prove all records stay in domain.
7. **May the approved local plan run now?** Traversal: Plan -> base Snapshot plus independently fetched current manifest and source/approval bindings. Result: current/stale approval, atomic state guard, idempotency key and local simulation receipt. Use: explain stale eligibility, ask for renewed scope/action approval, report simulated verification. Limit: history alone cannot establish current-state authorization.

## Completeness and missingness

Every candidate deployment resolves to exact release/read routes or explicit no-read evidence; nulls stay unknown. Every store has snapshot-specific coverage, and exact source record ID sets and edge sets are compared independently of traversal — counts or successful traversal do not prove completeness. Query truncation/cap is incomplete; missing writer/format/route/source metadata must not vanish in joins. Key-lookup fixture routes must be able to request every scoped record, else read-domain uncertainty stays unknown.

## Receipt contract

A canonical receipt binds scope, plan, snapshot/inventory, deployment, executing release/codec, route hash/contract, store, record/payload, format **or explicit unknown plus a semantic-scope sentinel**, probe specification and environment. P0 proof is byte/shape readability only, never overall production safety or semantic correctness. A source note claiming compatibility cannot discharge an obligation.

## Disposition

Trusted code computes, in precedence order:

- **BLOCKED** — any applicable reachable incompatibility witness, even with partial coverage (fail dominance).
- **NEEDS_EVIDENCE** — no such witness, but some required scope, route, inventory, identity, freshness or probe information is unresolved; unknown never silently becomes pass.
- **BOUNDED_PASS** — complete modeled obligations with current applicable PASS receipts.

A harness failure or timeout is UNKNOWN, distinct from an observed incompatibility.

## Update, deletion and scope isolation

The importer creates immutable observed snapshots and independently compares source-manifest IDs, edges and hash sets. Records may disappear only from a newly complete inventory, never from a missing join. Explicit deletion creates a new snapshot; audit receipts preserve prior evidence. Local fixture reset removes only its server-selected graph and files after permitted cleanup — no production deletion claim. Every query is server-bound to a scope graph and scope IDs; tenant graph names and allowed actions never come from raw user text or model output.

## Approval, simulation and idempotency

Only allowlisted authored fixture readers run, with bounded input/output and timeouts; a subprocess is failure containment, not a network sandbox. Scope confirmation and action approval are separate, and the model cannot approve its own action. When nothing passes, surface a truthful blocked/unknown result and never expose an eligible action button. Local simulation needs a fresh approval/current-state guard and must be idempotent; changed relevant evidence invalidates eligibility, so approval is scoped to the exact canonical tuple.

## Ownership and open gaps

Claude Opus 5.5 High orchestrates and owns contracts; DeepSeek V4.1 Flash on OpenCode Zen (`opencode/deepseek-v4.1-flash-free`) parallelizes bounded implementation within available capacity. Unverified: the v6.0.2 pin, complete query/client decoding, all seven operations, obligation enumeration, probe execution and the disposition/approval path.
