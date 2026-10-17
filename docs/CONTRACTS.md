# Contracts

The field-level reference for the current code: hashing and identity rules, fixture layout, the graph
schema and probe protocol, the gap kinds and disposition precedence, and the frozen module signatures.
Everything here is synthetic fixture data; the runnable instructions are in
[QUICKSTART.md](QUICKSTART.md) and the observed results in [STATUS.md](STATUS.md).

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
| Batch | `batch:<store_name>:<snapshot_name>:<record_id>:<payload_hash[7:23]>` (the hash segment is the literal `UNKNOWN` when the record carries no `payload_hash`) |
| Snapshot | `snapshot:<name>`; `manifest_hash = bh(manifest.json bytes)` |
| Plan | `plan:<plan_hash[7:23]>` |

### Artifact hash inputs (what the code actually does)

`artifact_hash` comes from one shared helper used by both the importer and the checker:
`rw.contracts.release_dir_files()` / `rw.contracts.artifact_hash()`. Both hash
`[[relpath, bh(bytes)] for every file in the release dir]` with posix relative paths, so a release id
is a function of the shipped bytes only. Two details are part of the helper's contract:

- **Exclusions.** Any path part equal to `__pycache__` is skipped, and so is any file whose suffix is
  `.pyc` (anywhere in the tree), so a stray bytecode file can never change a release id.
- **Sort order.** Entries are sorted by posix relative path, so the same bytes give the same hash on
  every OS and case-insensitive filesystems cannot reorder the list.

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

Trusted code (`src/rw/probes.py`) is the only sanctioned caller of the fixture harness. It generates a
fresh per-run secret `nonce = secrets.token_hex(16)` and starts

```text
python -I fixtures/shop/harness/run_reader.py <codec_path> <entry>
```

with a minimal environment containing only `RW_PROBE_NONCE=<nonce>`, `SYSTEMROOT` and `PATH` (no
other inherited variables); payload bytes on stdin (at most 65536, and one byte past the limit is
read so an oversized file is detected); stdout capped at 8192 bytes; stderr discarded; timeout 5 s.

**Result channel.** The harness pops `RW_PROBE_NONCE` from its environment (absent →
`HARNESS_ERROR` exit 20), saves the real stdout fd with `os.dup(1)`, then `os.dup2(2, 1)` and
`sys.stdout = sys.stderr` **before** loading `codec.py`. Everything the reader prints — including a
raw `os.write(1, ...)` — therefore goes to the parent's discarded stderr. The harness loads the codec
by path, calls `entry(data: bytes)`, and writes exactly one JSON line (sorted keys) to the saved fd,
carrying `"nonce": <nonce>`, then exits with `os._exit(code)`. That diversion and the nonce keep
ordinary reader output and early exits out of the result channel. They are failure containment for
allowlisted, reviewed fixture readers, not a sandbox: a reader that deliberately introspects the live
process (frame walking, `/proc/self/environ`) can still reach the nonce. A reader that exits or raises
a non-`Exception` `BaseException` (`SystemExit` / `KeyboardInterrupt` / `GeneratorExit` /
`BaseExceptionGroup`) before returning is a harness error, never a `FAIL`; only an `Exception` raised
by the entry call is a reader verdict.

The parent requires stdout to be exactly one line: the bytes must end with a single `\n` and contain
no other `\n`, so padded or blank lines are rejected. The parsed `nonce` must equal the nonce it
generated; anything else → `UNKNOWN` with message `harness error or invalid stdout`.

| Harness exit | stdout | Receipt result |
|---|---|---|
| 0 | one line `{"status":"PASS","nonce":<nonce>,"shape":{...}}` | PASS (only when `shape` is a dict) |
| 10 | one line `{"status":"FAIL","nonce":<nonce>,"error_type":str,"message":str}` | FAIL |
| 20 or any other exit, timeout, stdout > 8192 bytes, missing/mismatched nonce, bad JSON, extra/blank lines | — | UNKNOWN (harness error, never FAIL) |

`run_probe(obligation, payload_path, timeout_s=5) -> ProbeReceipt` performs the identity checks
before running anything: payload ≤ 65536 bytes and `bh(payload) == tuple.payload_hash`;
`probe_spec_hash(entry) == tuple.probe_spec_hash` and `environment_hash() == tuple.environment_hash`;
`bh(codec bytes) == tuple.codec_hash`; `timeout_s > 0`. Any failure returns an UNKNOWN receipt with the
reason as `message` — never a FAIL.

`probe_spec_hash(entry) = h({"family":"byte_shape_v1","harness_hash":bh(run_reader.py),"entry":entry,"timeout_s":5,"max_input":65536})`;
`environment_hash() = h({"python": sys.version_info[:3] as list, "platform": sys.platform, "harness_hash": bh(run_reader.py)})`.
Both include the harness bytes, so editing the harness changes every obligation's probe-spec and
environment hash; `revalidate` reports that as drift (expected, not a bug).

`pipeline.startup_check(codec_path)` runs the same harness on the `health` entry with an empty payload
and reports `GREEN` / `RED` / `UNKNOWN` beside the obligations for contrast only: it reads no retained
state and can never discharge an obligation.

## Obligation and receipt binding

An obligation is one (executing reader route under a plan) × (retained record in a store that route reads) pair. Its canonical tuple — every field below — hashes to `obligation_hash`; a receipt is applicable only if it carries the identical tuple hash **and** identical fields. Format unknown is the literal `"UNKNOWN"`; `semantic_scope` is always `"BYTE_SHAPE_ONLY"`.

## Disposition precedence (trusted code only)

1. Any applicable FAIL receipt → `BLOCKED` (even with incomplete coverage or other gaps).
2. Else any gap (missing route/no-read evidence, unknown read domain, coverage ≠ COMPLETE, inventory ID-set mismatch, missing writer/IN_STORE edge, truncation, invalid fleet, missing/UNKNOWN/inapplicable receipt) → `NEEDS_EVIDENCE`.
3. Else → `BOUNDED_PASS` (modeled byte/shape readability only).

## Gap kinds (`contracts.GapKind`) — unknown evidence is never a pass

Every `Gap` is `(kind, subject, detail)` and is emitted by trusted code only. The current members and
the facts that raise them:

| Kind | Raised when |
|---|---|
| `INVALID_FLEET` | plan fleet ≠ snapshot services; no independently loaded declaration for a release; graph deployment missing for a service, or running a different release than the plan |
| `ROUTE_EVIDENCE_MISSING` | a release declares no reader routes and no `no_state_read` evidence |
| `READ_DOMAIN_UNKNOWN` | the declared `read_domain` is not `ALL_KEYS` |
| `STORE_MISSING` | a declared route has no `reads_from`; a store read by the fleet is absent from the snapshot manifest |
| `COVERAGE_INCOMPLETE` | manifest or graph coverage is `PARTIAL` / `UNKNOWN` / missing for a read store |
| `INVENTORY_MISMATCH` | graph batch id set ≠ independently parsed manifest set; payload hash differs; batch lacks its `IN_STORE` edge; a declared (route, record) pair is missing from the graph path query |
| `WRITER_UNKNOWN` | batch has no `WRITTEN_BY` writer release; manifest writer `null`; manifest writer does not resolve to a declared release; graph/manifest writer contradiction |
| `FORMAT_UNKNOWN` | record format not established on either side; manifest format ≠ graph format |
| `TRUNCATED` | a fixed query returned `cap + 1` rows |
| `RECEIPT_MISSING` | no probe receipt for an obligation |
| `RECEIPT_UNKNOWN` | a probe ran but the harness could not establish a result |
| `RECEIPT_INAPPLICABLE` | a receipt exists but its bound tuple differs from the obligation tuple |
| `STALE_SNAPSHOT` | the plan was built against different manifest bytes than the manifest read at verification time; or the snapshot manifest cannot be re-read at verification time |
| `ROUTE_DECLARATION_MISMATCH` | graph route set ≠ shipped `release.json`: a declared route is missing from the graph, or a graph route is not declared; a graph route field (`entry`, `read_domain`, `store_id`, `route_name`, `route_contract_hash`) differs from the declaration; the graph `codec_hash` differs from the declaration |

## Scope confirmation vs action approval

Scope confirmation (human confirms the grounded fleet) permits checking. Action approval is a separate human call bound to `plan_hash`, `verification_hash`, `snapshot manifest_hash`; only allowed for `BOUNDED_PASS`; idempotency key = `h([plan_hash, verification_hash])`. The model can do neither.

## Module API (frozen signatures)

Every graph query function returns `(rows, log)` — except `store_inventory`, which returns the `(coverage_row, batch_rows, log)` triple below — where `rows` is a list of plain dicts with exactly the keys listed and `log = {"name": str, "params": dict, "rows": int, "truncated": bool}`. Unknown values are `None` in rows (never invented). Queries use `LIMIT $cap + 1` with `cap = QUERY_CAP`; if `cap+1` rows return, set `truncated=True` and return only `cap` rows. All reads use `ro_query`. No string-concatenated user/model input in Cypher; parameters only.

### `src/rw/graph.py`

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
receipts_for(g, obligation_hashes: list[str]) -> rows: probe_id, obligation_hash, result, receipt_json   # historical copies included
receipts_by_id(g, probe_ids: list[str]) -> same columns            # exactly these ProbeRuns; Session.verify reads back only the receipts it just wrote
```

Release node properties: id, service, version, artifact_hash, codec_hash, codec_path (posix, relative to repo root), built_at, bundle_id (omitted if null), declared_flags_json, no_state_read. Excerpts: one per CHANGELOG bullet/paragraph (`kind="changelog"`) and one per top-level `def` in codec.py (`kind="code"`), with 1-based inclusive line spans.

### `src/rw/verification.py`

```python
load_manifest(fixture_root, snapshot) -> (manifest: dict, manifest_hash: str)   # independent of the graph
load_release_declarations(fixture_root) -> {release_id: {service, version, artifact_hash,
    codec_path, codec_hash, routes: {route_id: route_dict}, no_state_read}}     # independent of the graph
release_index_by_service_version(declarations) -> {(service, version): release_id}  # ambiguous keys dropped
materialize_plan(proposal, current_fleet_rows, release_rows_by_service, snapshot_id, manifest_hash, request_text, origin, label) -> (CandidatePlan | None, errors)
    # sets CandidatePlan.baseline_fleet_hash = fleet_hash(observed current fleet rows); it is part of plan_hash(),
    # so the same proposal against a different baseline is a different plan. fleet_hash(entries) (contracts.py)
    # hashes service/release_id/flags sorted by service; `changed` is excluded.
validate_citations(citations, excerpt_rows) -> errors
build_evidence(plan, manifest, manifest_hash, route_rows, route_log, inventories, path_rows, path_log,
               probe_spec_for, environment_hash, *, declarations) -> GraphEvidence
dispose(evidence, receipts) -> VerificationResult
fixture_file(path, fixture_root) -> Path          # re-roots a fixtures/shop/... path under one fixture root
revalidate(verification, fixture_root, environment_hash_fn, probe_spec_fn) -> list[str]
```

`declarations` is a **required keyword** argument of `build_evidence`: the graph's route set, route
fields and `codec_hash` are trusted only insofar as they match the shipped `release.json` (see
`ROUTE_DECLARATION_MISMATCH`), and every obligation tuple takes `route_contract_hash`, `codec_hash`,
`reader_entry` and `reader_codec_path` from the declaration, never from graph rows. The expected
(route, record) pair set is computed from **declared** routes, so a route missing from the graph still
leaves its pairs reported as missing.

`GraphEvidence` fields: `plan_hash`, `obligations`, `gaps`, `queries` (each
`{"name","params","rows","truncated"}`), and the plan-level binding `snapshot_id` +
`snapshot_manifest_hash` (set from the plan and from the manifest read at verification time).
`dispose` takes the snapshot binding from the evidence itself, never from the first obligation, so
zero-obligation evidence keeps a non-empty binding.

`GraphEvidence.dependencies` (copied onto `VerificationResult.dependencies`) is the sorted list of
every release the evidence rests on: every fleet release from the plan, plus every writer release the
manifest resolves for a store the fleet reads. `revalidate` checks it independently of the
obligations, so a writer-only artifact that no reader obligation names still counts as evidence.

Two Batch rows claiming one `record_id` in a store are never collapsed: the conflict is an
`INVENTORY_MISMATCH` gap (`conflicting batches for one record: <batch ids>`), and an obligation is
built only for a path row whose batch and payload hash equal the independent manifest record.

`revalidate(verification, fixture_root, environment_hash_fn, probe_spec_fn)` returns one
human-readable drift line per distinct fact, or `[]` when the bytes behind a verification are still
current. It fails closed on: a fresh `bh(manifest.json)` for `verification.snapshot_id`; per
obligation the payload bytes resolved through the fresh manifest record, `bh(reader codec bytes)`,
`environment_hash_fn()` and `probe_spec_fn(obligation.reader_entry)`; that `fixture_root/releases`
still declares `tuple.release_id` with the same `h(route_dict)` for `tuple.route_id`; that every
`verification.dependencies` release id is still declared (content-addressed, so presence ⇔ unchanged
bytes — this is what catches a writer-only artifact); and that each read store's manifest record still
resolves its writer to a release the verification already depended on. Only stores a fleet route reads
are in scope (the obligation store ids plus the read stores named by the still-declared
dependencies), so a manifest store no fleet route reads cannot invent drift. A missing or
unreadable file is a drift line, not an exception. Both hash functions already include the harness
hash, which is why they bind the harness too. Callers: `api.py` `/approve` and `/simulate`, which
answer HTTP 409. When `revalidate` reports drift the body is
`{"detail": {"reason": "<reason>", "drift": ["<line>", ...]}, "reason": "<reason>"}`; every other
refusal answers `{"detail": "<reason>", "reason": "<reason>"}`. No action may be taken on evidence that
no longer exists as verified.

### `src/rw/probes.py`

```python
harness_path() -> Path
probe_spec_hash(entry) -> str
environment_hash() -> str
run_harness(codec_path, entry, payload: bytes, timeout_s=5) -> dict   # the only sanctioned harness caller
run_probe(obligation: Obligation, payload_path: Path, timeout_s=5) -> ProbeReceipt
```

`run_harness` owns the nonce, the minimal child environment, bounded I/O, the timeout and the strict
one-line/nonce/schema parsing; it returns
`{"result": "PASS"|"FAIL"|"UNKNOWN", "exit": int|None, "stdout": bytes, "timed_out": bool, "error_type": str|None, "message": str|None, "shape": dict|None}` (callers branch on the explicit `timed_out` flag, never on the message string).
See "Probe protocol" above for the exit-code table. `run_probe` returns an UNKNOWN receipt on any
identity mismatch and never FAILs from its own checks.

### `src/rw/grounding.py`

A provider-neutral bounded tool loop (≤ 8 model turns) over the read-only tools `current_fleet`, `release_history`, `store_readers`, `get_excerpts` and the terminal tools `propose_fleet(changes, citations, rationale)` / `ask_clarification(question, unresolved, citations)`. Returns `GroundingResult`. Read tools, argument validation, citation hashing, the audit trail and terminal validation are written once and shared; only conversation rendering and response parsing differ per provider. A terminal call whose only failures are citation-check errors (`CITATION_*`) earns one correction round: the loop stays open and that model gets the exact failures plus the quoting rule so it can resend verbatim quotes. A second invalid terminal call ends the loop as before, and the round is recorded as a `citation_correction` event in the transcript/audit.

`propose_fleet` requires citation coverage: every entry in `changes` needs at least one verbatim citation of a `changelog` excerpt of that same release, otherwise `CITATION_MISSING: <release_id> ...` (eligible for the one correction round). `Session.plan_from_proposal` repeats the check for `origin="agent"` proposals against the graph's excerpt rows; operator/fixture fleets (`--fleet`, controls, oracle) are not agent proposals and skip it. Flag values must be real booleans (`"false"`, `0`, `null` are invalid calls, never coerced). Tool-call arguments that are not a JSON object get an `arguments must be a JSON object` error and the loop continues. A provider envelope with the wrong shape (null or non-list `choices`/`candidates`, non-dict message/content/parts) raises `GroundingError(code="malformed_response")` with a fixed message; the next configured model is tried, and the raw body is never recorded (a `model` event is written only after a successful parse).

Providers are chosen by `RW_GROUNDING_MODEL` (comma-separated `provider:model`; a bare entry means `gemini:`); the default chain is `groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b`.

- `groq` — OpenAI-compatible Chat Completions (`GROQ_API_KEY`, Bearer header only), `tool_choice: "required"`, `parallel_tool_calls: false`, temperature 0. Assistant content and `tool_calls` IDs/arguments are preserved before matching tool replies; provider-only reasoning metadata is not fed back. Tool-result JSON is compact UTF-8 with unchanged decoded values. Completion tokens are capped by `RW_GROUNDING_MAX_COMPLETION_TOKENS` (default 2048); GPT-OSS reasoning effort is set by `RW_GROUNDING_REASONING_EFFORT` (default `medium`, accepts `low`/`medium`/`high`).
- `gemini` — `generateContent` (`GEMINI_API_KEY` in a header only), `functionCallingConfig.mode = ANY`, raw parts (thought signatures) preserved. Optional; used when a `gemini:` entry is selected.

When a chain entry exhausts its retries the **whole conversation restarts** from turn 0 on the next entry — providers are never mixed. `GroundingResult.model` records the `provider:model` that actually answered, or `replay:<file>` with `live=False` for a saved transcript. Retries: 2–30 s exponential backoff, or the server's `Retry-After` (capped at 120 s); non-retryable are statuses outside 408/429/500/502/503/504 and Groq 429s whose body says `tokens per day` or `request too large` (waiting cannot clear those). The credential only ever travels in a header and is redacted from error text. Transcripts are saved under `artifacts/grounding/` for labeled replay.

HTTP 400 `tool_use_failed` is a special generated-call rejection: the shared product/control loop records a `model_error` event with only HTTP status, an allowlisted code and a fixed message, executes nothing, and sends a trusted correction listing declared tool names. Raw provider messages and `failed_generation` are discarded, including in old replay events. Each correction consumes a model turn within the existing cap; repeated rejection aborts without a proposal/pass. Replays preserve these error turns. Other 400s still fail normally. Product/control abandoned attempts and failure reports use the same structured sanitizer; arbitrary transport exception text is never persisted.

The Groq transport records safe usage/rate metadata and settings in `transport_trace` / `transport_settings`. If reported remaining tokens are below a conservative byte-based request estimate plus the completion cap, it waits for the reported reset before the next call. Missing headers remain unknown. This estimate affects scheduling only, never disposition. Concurrent callers can still cause 429 responses, and daily exhaustion/oversized requests still fail closed.

Repeated excerpt text is replaced by `text_already_returned: true` only for an `(excerpt_id, content_hash)` whose actual text survived the model-result cap. All unique source text and the full trusted citation-validation store remain available. A capped-away excerpt or changed hash is not suppressed. On provider failure, a separate grounding failure artifact preserves the successful prefix and transport metadata; it is not listed as a normal replay transcript.

The standalone flat-context CLI now loads `.env`. Its version-4 protocol uses `submit_assessment` as the terminal function and retains aborted provider failures, explicitly marking partial history unavailable. The live control test runs one conversation per execution and selects its credential gate from the configured provider. `evals/run_comparison.py` pins one model, preserves test evidence and product reports, and invokes the scorer. Its inventory covers all fixture/evidence file types, including changelogs and retained payload bytes. A pair requires both matching models and operational product completion; provider errors stop collection and return exit 1 even after a successful prefix. BLOCKED/NEEDS_EVIDENCE outcomes remain valid completed checks. See [ISSUE_3_FIX_REPORT.md](ISSUE_3_FIX_REPORT.md).

### `src/rw/simulation.py`

SQLite ledger under `artifacts/sim.sqlite` (git-ignored). `record_approval(db_path=DEFAULT_DB_PATH, approval=None, verification=None, forbidden_identities=DEFAULT_FORBIDDEN_IDENTITIES)` refuses a verification that is not `BOUNDED_PASS`, a mismatched `verification_hash`/`plan_hash`/`snapshot_manifest_hash`, and a missing or forbidden approver identity (the model can never be the approver). `simulate(db_path=DEFAULT_DB_PATH, approval=None, verification=None, current_manifest_hash=None, current_fleet=None, plan=None) -> SimulationReceipt` (raises `SimulationRefused`) additionally requires the recorded approval, a current manifest hash equal to the approval's, matching plan/verification identities, and a current fleet, and applies each idempotency key (`h([plan_hash, verification_hash])`) exactly once — a duplicate returns the stored receipt with `applied=False`. Before the first application it also refuses `current fleet changed since the plan was built` when `fleet_hash(current_fleet) != plan.baseline_fleet_hash` (a plan without a baseline can never be simulated); this runs after the idempotency lookup, so a repeat stays `applied=False`. `previous_fleet_hash` is `fleet_hash(current_fleet)`.

### API (`src/rw/api.py`)

`create_app(...)` builds the FastAPI app; `scripts/serve.py` binds `127.0.0.1:8000`. The grounding
agent and the MCP bridge have no approve, apply or deploy tool, and approval refuses the configured model
identities. The HTTP API itself is unauthenticated and local-only: anyone who can reach it can supply a
human-looking approver label, so the label is an operator name, not verified identity (see [MCP.md](MCP.md)).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/investigations` | start one investigation (live, or labeled replay of a saved transcript) |
| GET | `/api/investigations`, `/api/investigations/{identifier}` | list / read one investigation |
| GET | `/api/transcripts` | saved transcripts available for replay |
| POST | `/api/investigations/{identifier}/plans/{plan_hash}/confirm-scope` | human scope confirmation for one plan |
| POST | `/api/investigations/{identifier}/answer` | one clarification round: body `{"answer": str, "replay_path": str \| null}`; the answer is folded into the request text via `pipeline.with_answer` and the session re-grounds against it. Blank answer → 422; a second round is refused; in replay mode `replay_path` is required, in live mode it is rejected (422) |
| POST | `/api/investigations/{identifier}/alternative` | at most one alternative, only after `BLOCKED` / `NEEDS_EVIDENCE` |
| POST | `/api/investigations/{identifier}/plans/{plan_hash}/approve` | human approval: only for `BOUNDED_PASS`, only on current bytes (409 `{"detail": {"reason", "drift"}, "reason"}` when `revalidate` reports drift) and only on the fleet the plan was built against (409 `current fleet changed since the plan was built`) |
| POST | `/api/investigations/{identifier}/plans/{plan_hash}/simulate` | local idempotent simulation (409 on drift, including fleet drift since the plan was built); never a deployment |
| GET | `/api/snapshots` | read-only fixture manifests, their hashes and explicit `data_origin: "synthetic_fixture"` for initial workspace context; does not initialize a graph or call a model |
| GET | `/` | the investigation workspace (visible synthetic-fixture and live/replay context; humanized disposition labels: Blocked, Needs evidence, Bounded pass; API disposition values are unchanged) |
| GET | `/static/{path}` | same-origin CSS, browser modules and the SVG favicon; no frontend build step |

### ID-form clarification (binding)

`snapshot_id` everywhere (params, Batch/Coverage/Plan properties, `CandidatePlan.snapshot_id`, `ObligationTuple.snapshot_id`) is the node form `snapshot:<name>`; `store_id` is `store:<name>`. Batch id = `batch:<store_name>:<snapshot_name>:<record_id>:<short(payload_hash)>`. Release `codec_path` and Batch `payload_path` are posix paths relative to the repo root.


## Local MCP and HTTP presentation contracts

`api_contracts.py` defines explicit success/error presentation schemas for the nine product HTTP
operations. Enrichment fields, nulls and latest-attempt aliases are preserved; report plans do not
gain a citations field. These models are separate from the frozen canonical domain contracts and
never participate in hashing or approval identity. Existing status codes and HTTP lookup semantics
are unchanged. Opt-in list pagination returns arrays plus `X-Next-Cursor`; unpaginated calls keep
their existing ordering. Paginated transcript parsing skips files over 1 MiB. Newly live-grounded
questions are limited to 3,000 characters; answered requests to 28,000 before state mutation.
Replay questions remain selectable regardless of historical length.

`mcp_contracts.py`, `mcp_client.py` and `mcp_server.py` expose only six allowlisted operations over
one existing local HTTP API. Strict raw input validation precedes SDK coercion. Upstream evidence
is validated for canonical hashes/bindings and deterministic disposition consistency before safe
projection and outgoing schema validation. The server does not run another Session, initialize a
graph, or expose verification, confirmation, approval or simulation tools. Full operational,
projection, pagination, error, concurrency and restart contracts are in [MCP.md](MCP.md).

Scope confirmation and action approval remain distinct human workflow gates, with byte revalidation
on approval/simulation. Reading stored evidence does not reverify it. After drift, start a new
investigation and confirm/approve its new exact plan; repeated confirmation returns cached evidence.
The local identity denylist is not authentication. This release has no tenant isolation or remote
MCP transport. `/simulate` continues to ignore supplied bodies for HTTP compatibility.
