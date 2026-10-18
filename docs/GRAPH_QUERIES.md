# Cypher queries and graph algorithms

This reference documents the queries and algorithms the current product depends
on, reviewed against source at `a8f2224`. Start with the
[README setup](../README.md#quickstart) and
[repository graph model](../README.md#repository-evidence-graph) and
[rollback graph model](ARCHITECTURE.md#graph-schema). The repository-evidence demo
and synthetic rollback workflow use different graphs and result types.

The query blocks below preserve the implementation's logic; whitespace is
expanded for readability. Parameters are supplied separately, never interpolated
from model prose. Some identifiers, relationship kinds and traversal bounds are
constructed by trusted implementation code. Source links are authoritative if
the code changes later.

## 1. Derive reader × retained-record obligations

**Implementation:** [`graph.obligation_paths`](../src/rw/graph.py).
**Used by:** the trusted rollback checker after candidate scope confirmation.
**Why it matters:** determines which real reader executions need probe receipts
and preserves the path explaining a failure.

```cypher
MATCH (p:Plan {id: $plan_id})-[:HAS_DEPLOYMENT]->(d:Deployment)
      -[:RUNS]->(r:Release)-[:EXECUTES_ROUTE]->(rt:ReaderRoute)
      -[:READS_FROM]->(s:StateStore)
      <-[:IN_STORE]-(b:Batch {snapshot_id: $snapshot_id})
OPTIONAL MATCH (b)-[:WRITTEN_BY]->(w:Release)
RETURN p.id AS plan_id, d.id AS deployment_id, r.service AS service,
       r.id AS release_id, r.codec_hash AS codec_hash,
       rt.id AS route_id, s.id AS store_id, b.id AS batch_id,
       b.record_id AS record_id, b.payload_hash AS payload_hash,
       b.format_id AS format_id,
       w.id AS writer_release_id, w.version AS writer_version
ORDER BY d.id, b.record_id
LIMIT $limit
```

| Parameter | Meaning |
| --- | --- |
| `$plan_id` | Server-generated ID of the exact candidate plan |
| `$snapshot_id` | Selected fixture snapshot ID; filters the retained records |
| `$limit` | Supplied by `graph._read` as the requested row cap plus one |

Example: cart 1.4 → `load_saved_cart` → cart cache ← `saved-cart-2002` → cart 1.5.
The query identifies the obligation. Executing the actual cart 1.4 reader on the
retained `cart/v2` bytes supplies the incompatibility receipt. It is not inferred
from a service-to-service call edge.

The writer match is optional so a missing writer does not silently remove a
reachable record. Independent inventory/route checks are still needed: a
successful join cannot prove that every required edge or record exists.

## 2. Retrieve source linked to release history

**Implementation:** [`graph.release_history`](../src/rw/graph.py).
**Used by:** the rollback grounding agent's read-only tools.
**Why it matters:** ties candidate release reasoning to the source of actual
available artifacts rather than an unversioned note.

```cypher
MATCH (s:Snapshot {id: $snapshot_id})-[:HAS_DEPLOYMENT]->
      (d:Deployment {service: $service})-[:RUNS]->(r:Release)
MATCH path = (r)-[:PREVIOUS*0..10]->(p:Release)
WITH p, length(path) AS depth
WHERE depth <= $max_depth
OPTIONAL MATCH (p)-[:HAS_SOURCE]->(e:SourceExcerpt)
WITH p, depth, e ORDER BY depth, e.path, e.line_start
RETURN p.id AS release_id, p.service AS service, p.version AS version, depth,
       p.built_at AS built_at, p.bundle_id AS bundle_id,
       p.declared_flags_json AS declared_flags_json,
       p.previous_release_id AS previous_release_id,
       collect(CASE WHEN e IS NULL THEN null ELSE {
           excerpt_id: e.id, kind: e.kind, path: e.path,
           span: toString(e.line_start) + '-' + toString(e.line_end),
           text: e.text, content_hash: e.content_hash
       } END) AS excerpts
ORDER BY depth
LIMIT $limit
```

Parameters: selected snapshot, service, requested maximum depth and cap-plus-one
row limit. `10` is the current trusted `CHAIN_HOP_CAP` expanded from the source;
the operation defaults to a requested depth of five. Depth zero includes the
current release. `PREVIOUS` is an explicit build-history
relationship, not proof that an earlier release preserves a fix. Retrieved source
can support a proposal but cannot waive the compatibility checker.

## 3. Select published repository revisions

**Implementation:** [`RepoQuery.revisions`](../src/rw/repo/query.py).
**Used by:** repository investigation tooling.
**Why it matters:** a partially written import must not masquerade as a complete
repository index.

```cypher
MATCH (repo:Repository {name:$name, status:'COMPLETE'}),
      (r:ImportRun {status:'COMPLETE'})-[:INDEXED]->(c:Commit)
WHERE r.id=repo.published_run
OPTIONAL MATCH (t:Tag)-[:POINTS_TO]->(c)
RETURN c.sha, collect(DISTINCT t.name)
ORDER BY c.sha
SKIP $o LIMIT $l
```

Parameters: configured repository name, decoded page offset `$o`, and page size
`$l`. The method also runs a count query over the same publication and produces
coverage and cursor metadata. The publication generation scopes caches and
cursors; reindexing can invalidate a previously issued cursor.

## 4. Retrieve source-level dependency facts

**Implementation:** [`RepoQuery._load`](../src/rw/repo/query.py).
**Used by:** `dependencies`, `dependents` and related source investigations.
**Why it matters:** obtains the actual relationship facts and extraction
provenance that the bounded Python walk uses.

```cypher
MATCH (b:Blob)-[:DEFINES]->(s:Symbol)-[e]->(t:Symbol)
WHERE b.content_hash IN $hs
RETURN b.content_hash, s.qualname, s.first_path, type(e),
       t.qualname, t.external,
       e.provenance, e.extractor, e.relative_target
```

`$hs` is a batch of content hashes from the selected revision's file map, not a
list selected by the model. The implementation reads symbol definitions too,
rebases module paths, resolves supported static references and checks extractor
identity. An unresolved external target is not promoted to a verified local
definition. An inferred edge remains labeled inferred.

The two-hop dependency visualization is **not one variable-length Cypher query**.
FalkorDB supplies facts; the Python walk resolves the neighborhood within the
selected revision. Seeing an edge does not prove runtime method resolution.

## 5. Walk commit ancestry when Git ancestry is unavailable

**Implementation:** [`RepoQuery._ancestors`](../src/rw/repo/query.py).
**Used by:** the ancestry fallback in `_is_ancestor`.

```cypher
MATCH (c:Commit)-[:PARENT]->(p:Commit)
WHERE c.sha IN $f
RETURN DISTINCT p.sha
```

`$f` is the current frontier of commit SHAs. Python maintains the visited set,
advances the frontier and respects the ancestry bound and active read budget.
The preferred path uses the local Git repository's ancestry operation. Ancestry
alone does not determine whether a fix is present in the selected source.

## Algorithms around the queries

| Algorithm | Actual behavior | Boundary |
| --- | --- | --- |
| Repository dependency/dependent walk, `RepoQuery._walk` | Builds adjacency from revision-specific facts; breadth-first traversal with visited nodes/edges; supports forward or reverse direction, hop bounds, pagination and explicit ambiguity/gap reporting | Demo requests two hops. Truncation means omitted evidence, not absence. Static source relationships do not establish runtime behavior. |
| Fix presence, `RepoQuery.fix_status` | Reads the fix's parent diff; compares required additions/deletions with verified target-revision content; considers ancestry, renames and bounded patch-equivalence checks; returns `PRESENT`, `ABSENT` or `UNCERTAIN` with citations/gaps | Textual/change identity check, not a semantic equivalence proof or runtime test. Similar modified changes can remain uncertain. |
| Incremental repository indexing, `index_repository` | Reads Git objects, constructs per-commit file maps, content-addresses blobs, extracts symbols/edges and batches graph writes; publishes only after completion | Does not import or execute repository code. Unsupported extraction and incomplete imports remain visible. |
| Rollback completeness checks, `verification.py` | Compares traversed route/inventory sets with independently parsed fixture declarations; validates evidence and receipt identity | A missing edge, unknown writer, stale receipt or truncated query cannot silently become pass. |
| Rollback disposition, `verification.py` | Applicable incompatibility witness → `BLOCKED`; otherwise unresolved required evidence → `NEEDS_EVIDENCE`; otherwise complete applicable passes → `BOUNDED_PASS` | Pass means modeled byte/shape readability only. A harness error is `UNKNOWN`, not an observed incompatibility. |

The rollback model proposes a fleet or clarification through fixed read-only
tools. It does not generate arbitrary Cypher, manufacture receipts or approve
simulation. Probe execution and approval are trusted-code/human operations.

## Bounds and missing evidence

The rollback graph's `graph._read` uses `ro_query`, requests `cap + 1` rows,
returns at most `cap`, and logs truncation. The checker treats incomplete
retrieval as an evidence gap. Missing optional metadata remains unknown.

The repository query layer uses its own pagination, generation checks and shared
read budgets. Its defaults are configured in
[`RepoConfig`](../src/rw/repo/config.py); the demo wraps retrieval in a ten-second
budget and requests a one-relationship page for the truncation scene. These
cooperative budgets are bounds, not measured latency promises. No LLM is invoked
by the dedicated repository demo.

## Run a read-only query against the prepared demo

First complete [repository-demo setup](../README.md#repository-evidence-demo--linux--wsl).
Run from the repository root against its dedicated database:

```sh
RW_FALKORDB_PORT=55688 PYTHONPATH=src .venv/bin/python - <<'PY'
from rw.repo.config import RepoConfig
from rw.repo.query import RepoQuery

q = RepoQuery("rw_hackathon_demo_real", "hackathon-itsdangerous")
page = q.revisions(limit=5)
print("Revisions:", page.items)
print("Truncated:", page.truncated)

# Use the same configured Git path and revision as the demo for source checks.
import json
from pathlib import Path
cases = json.loads(Path("artifacts/hackathon-demo/cases.json").read_text())
real = cases["real"]
cfg = RepoConfig.model_validate(real["config"])
q = RepoQuery(real["graph"], cfg.name)
matches = q.symbols(real["revision"], name="URLSafeTimedSerializer")
if len(matches.items) != 1:
    raise SystemExit("Expected one definition; inspect matching symbols and gaps")
page = q.dependencies(real["revision"], matches.items[0].qualname, hops=2, limit=30)
for edge in page.items:
    print(edge.hops, edge.source, "->", edge.target, edge.provenance)
print("Truncated:", page.truncated)
print("Coverage:", page.coverage)
PY
```

Expected: published revision identities and relationships including hop two;
exact row counts depend on indexed facts. For the fixture workflow,
`.venv/bin/python scripts/smoke.py` exercises the real obligation queries and
probes using fixed grounding, without a model key. See
[QUICKSTART](QUICKSTART.md) for the fixture DB and
[the README](../README.md#repository-evidence-demo--linux--wsl) for demo expectations.

## Validation and related references

The documented queries were checked against the implementation. Four query
blocks (obligations, release history, relationships and ancestry) were also
compared automatically with captured/static implementation strings without DB
calls. The read-only example's Python syntax passed, relative file links
were checked locally, and
`git diff --check` passed. This documentation pass
does not constitute a fresh DB-backed smoke or clean-machine setup run. Current
observed results are in [STATUS.md](STATUS.md).

Schema details: [fixture architecture](ARCHITECTURE.md),
[repository evidence design](repo/DESIGN.md).
Demo setup: [repository evidence demo](../README.md#repository-evidence-demo--linux--wsl).
