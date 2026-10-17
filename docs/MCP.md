# Local MCP orchestration

RollbackWitness offers six stdio tools backed by the **same running HTTP API** as the human
console. All data is synthetic. Results cover `BYTE_SHAPE_ONLY`; actions are local simulation only.
The API's grounding model and provider credentials are still used for live investigations. Replay
uses saved transcripts and is always labeled `live=false`, `model=replay:<filename>`.

## Install and run

Python 3.12; official `mcp==2.3.0` (optional extra), with the existing runtime pins unchanged:

```sh
docker compose up -d                  # reuse an existing FalkorDB container
sh /absolute/path/to/FalkorDB_agent/scripts/setup.sh --mcp
/absolute/path/to/FalkorDB_agent/.venv/bin/python /absolute/path/to/FalkorDB_agent/scripts/serve.py
```

Windows: `powershell -ExecutionPolicy Bypass -File C:\path\to\FalkorDB_agent\scripts\setup.ps1 -Mcp`,
then `C:\path\to\FalkorDB_agent\.venv\Scripts\python.exe C:\path\to\FalkorDB_agent\scripts\serve.py`.
Default setup without `--mcp` / `-Mcp` still supports the API, CLI and tests. All launchers resolve
imports relative to their own file, independently of the current working directory.

Run **one HTTP worker** without reload. The API owns in-memory investigations; multiple workers or
reload split or lose that state. The bridge never starts an API, instantiates a Session, imports a
graph or loads `.env`. Provider keys belong to the HTTP process only. If no key is configured, list
saved transcripts and use replay; a fresh clone has no transcripts until you save a grounding run.

Configure a host that supports **stdio** (replace absolute paths; the settings-file location depends
on the host):

```json
{
  "mcpServers": {
    "rollbackwitness": {
      "command": "/absolute/path/to/FalkorDB_agent/.venv/bin/python",
      "args": ["/absolute/path/to/FalkorDB_agent/scripts/serve_mcp.py"],
      "env": {"RW_MCP_API_BASE_URL": "http://127.0.0.1:8000"}
    }
  }
}
```

On Windows use absolute `Scripts/python.exe` and script paths (escape backslashes in JSON). Do not
rely on shell activation, host cwd, or downloads at launch. Do not put model credentials in MCP
settings. HTTP-only MCP hosts are outside this release. Protocol traffic uses stdout; sanitized
operation logs use stderr. The official SDK handles modern `2026-07-28` discovery and legacy
`2025-11-25` initialization; both are exercised by the subprocess tests.

`RW_MCP_API_BASE_URL` is read once at startup. Only plain HTTP literal `127.0.0.1` or `[::1]` origins
with a valid port and root path are accepted. Hostnames, remote addresses, credentials, queries,
fragments and alternate schemes are rejected. HTTP proxies, redirects and automatic retries are
disabled. `RW_MCP_MUTATION_DEADLINE_SECONDS` defaults to 600 and accepts a positive finite value up
to 3600. Configure the host to allow at least that duration plus protocol overhead.

## Tools and workflow

| Tool | Arguments | Purpose |
|---|---|---|
| `rw_start_investigation` | `request_text`, `mode=live`, `replay_path=null`, `snapshot=snap-001` | Start a run; may initialize/reset synthetic fixture data and incur provider cost. |
| `rw_get_investigation` | `investigation_id` | Read complete stored attempts and evidence, with a review URL. |
| `rw_list_investigations` | `limit=20`, `cursor=null` | List process-local summaries. |
| `rw_list_transcripts` | `limit=20`, `cursor=null` | List saved replay metadata, without file contents or absolute paths. |
| `rw_answer_clarification` | `investigation_id`, `answer`, `replay_path=null` | Supply the user's actual answer once. Never invent an unresolved human preference. |
| `rw_request_alternative` | `investigation_id`, `replay_path=null` | Request an alternative after a human-confirmed BLOCKED/NEEDS_EVIDENCE report; at most two materialized plans. |

1. Discover tools; optionally list transcripts. Start with the exact saved request for replay.
2. Preserve the returned 32-character investigation ID. Obtain the user's answer for a clarification.
3. Give the human the returned `review_url` (`/?investigation=<id>`). Loading it performs only reads.
   The console loads the latest attempt and allows review of earlier attempts and refresh.
4. The human inspects the exact fleet/flags and confirms scope. This runs deterministic verification.
5. Retrieve state: BLOCKED carries witnesses; NEEDS_EVIDENCE carries gaps. Request the permitted
   alternative if appropriate; that new plan needs its own human scope confirmation.
6. For BOUNDED_PASS, explain the byte/shape-only scope. Human approval and simulation are separate
   console operations. MCP can retrieve their results but has no action tool.

The six tools do not expose confirmation, verification, approval, simulation, probes, graph reset,
Cypher, arbitrary HTTP, files or shell commands. Tool annotations are hints, not authorization.
Business outcomes, clarifications and grounding validation errors are successful tool results.
Missing evidence never becomes a pass. Reads return **stored verification**, not a new freshness
check. Confirmation of an already confirmed plan is cached. After byte drift, **start a new
investigation**, then have the human confirm and approve the new exact plan.

## Contracts and bounds

Inputs forbid unknown fields and validate raw arguments before SDK coercion. Strings are strict;
request text is preserved exactly (1–20,000 characters, nonblank), while answers are stripped by the
API (1–4,000). Investigation IDs are lowercase 32-hex strings. Replay selectors are JSON basenames
only (1–255 characters; no separators, drive prefixes or controls). Start requires a selector only
in replay mode. Answer and alternative also enforce the server-held mode. Limits are strict integers
1–100 (booleans, floats and numeric strings fail); cursors are opaque URL-safe strings up to 512
characters. The API remains the authority for replay confinement and workflow gates.

HTTP presentation contracts are separate from canonical domain models. The bridge validates status,
media type, bounded JSON, aliases, IDs, plan/report/snapshot/approval bindings, canonical hashes,
receipt references and deterministic disposition consistency. Distinct receipts for an obligation
remain allowed; FAIL dominance is preserved. This is transport-integrity checking, not another
compatibility verifier. MCP omits provider audit payloads and internal codec paths, converts
transcript paths to picker names, and retains all attempts, obligations, gaps, receipts, blocking
hashes, witness paths and query truncation flags. The stored verification hash identifies the
canonical report, not the projected JSON.

Each result carries `schema_version="1"`, `synthetic_fixture=true`,
`semantic_scope="BYTE_SHAPE_ONLY"` and `local_simulation_only=true`. Investigation results include
mode/model/live, snapshot and latest plan/verification hashes, typed `data`, `next_action` and
`review_url`. Lists use `{..., items, next_cursor}` envelopes. The SDK publishes `outputSchema` and
returns the same data as `structuredContent` and JSON text. Upstream JSON is streamed with a 1 MiB
cap, independent of Content-Length; serialized result data is capped at 128 KiB before framing.
The SDK's text copy adds roughly another copy plus JSON escaping/framing; tests check actual wire
serialization. Oversized evidence fails whole, without silently dropping obligations or gaps.

At most four HTTP calls are in flight, with one mutation per investigation and one start at a time.
Mutations are limited to ten per minute per bridge process. A busy error submits nothing. Connect
wait is 3 seconds; GET deadline is 15 seconds; the overall mutation deadline is configurable as
above. The backend's synchronous model/probe work may continue after a deadline or host cancellation.
Stopping the bridge wait does not promise cancellation, rollback or a bound on backend duration.

Expected tool failures have `isError=true`, a stable `[code]` text prefix and no `structuredContent`:
`invalid_input`, `not_found`, `state_conflict`, `provider_quota`, `provider_unavailable`,
`provider_error`, `backend_unavailable`, `outcome_unknown`, `invalid_backend_response`,
`response_too_large`, `busy`. Messages never forward arbitrary upstream response bodies or provider
text. Unknown tools/malformed protocol messages use SDK protocol errors.

Never automatically replay a mutation. After an uncertain answer/alternative, fetch the known
investigation to reconcile. After uncertain creation, list investigations and have the user identify
the run if ambiguous: request text is not an idempotency key. MCP restart reconnects to the API;
API restart loses investigations and attached approvals even though SQLite receipts survive.

## HTTP compatibility and trust

Existing list calls without pagination retain arrays and ordering. Opt-in `limit`/`cursor` mode also
returns arrays, with `X-Next-Cursor` only when more records exist. Cursors are versioned and
endpoint-specific; cursor without limit is 422. Investigation pages use stable ID ordering;
transcripts use descending `(mtime, file_name)`. Pages are weakly consistent if records/files change;
there is no completeness guarantee across concurrent changes. Paginated transcript listing skips
files over 1 MiB before parsing. Legacy unpaginated file handling is unchanged. Picker metadata is
weaker than full replay validation.

Two explicit HTTP text limits were added: newly live-grounded questions over 3,000 characters fail
with a sanitized provider error before an attempt is appended; composed answered requests over
28,000 characters fail 422 before consuming the answer round. Saved replay questions are not
retroactively rejected. Creation still has its original 20,000-character limit. Other status codes,
404 lookup semantics, replay-path truthiness quirks and request-body behavior remain compatible.
`/simulate` still ignores a supplied JSON body; there is no MCP simulation tool. All successful
product API operations remain HTTP 200.

This is a **local, single-operator** workflow. Approver labels are not authenticated human identity;
an invented human-looking label can pass the denylist. A client with other local HTTP/browser/shell
access can independently call the unauthenticated API. Excluding action tools limits this MCP
surface; it does not provide OS isolation or tenant isolation. Remote deployment, authentication,
durable commands, external-agent grounding and explicit re-verification require separately scoped
work. Do not expose this API to untrusted remote clients.

## Maintainer verification

```sh
.venv/bin/python -m pytest -q -m 'not live'
.venv/bin/python scripts/smoke.py
```

Base-only collection explicitly skips SDK-dependent modules. CI tests both base and MCP-enabled
installs, and the MCP job separately asserts SDK tests execute with zero skips. Integration tests
use unique graphs and temporary SQLite ledgers, real Sessions/readers and deterministic injected
grounding. No provider key or live model is needed. See [STATUS.md](STATUS.md) for observed results
and platform/browser limits. Official references: [SDK installation](https://py.sdk.modelcontextprotocol.io/get-started/installation/),
[structured output](https://py.sdk.modelcontextprotocol.io/servers/structured-output/),
[protocol versions](https://py.sdk.modelcontextprotocol.io/protocol-versions/).
