# Repository configs

Each repository is onboarded by one JSON file, `repos/<name>.json`, loaded by
`rw.repo.config.load_config("<name>")` (or a path to the file). No code changes are needed to add a repo.

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | `[a-z0-9][a-z0-9-]{0,63}`; the graph is `rw_repo_<name>` |
| `path` | yes | local Git repository, absolute or relative to this configuration file (bare or normal; never checked out or modified) |
| `revisions` | no | explicit refs to index (branches, tags, shas); all ancestors are indexed too |
| `tag_pattern` | no | regex; matching tags are indexed in addition to `revisions` |
| `languages` | no | adapters to use (default `["python"]`; see `rw.repo.adapters.SUPPORTED_LANGUAGES`) |
| `include` / `exclude` | no | path globs filtering indexed files |
| `release_notes` | no | globs for release-note files (default `CHANGELOG*`, `HISTORY*`, `NEWS*`, ...) |

Files without an adapter are recorded as `UNSUPPORTED_LANGUAGE` coverage gaps, not dropped silently.

```json
{
  "name": "requests",
  "path": "../artifacts/repos/requests",
  "revisions": ["main"],
  "tag_pattern": "^v2\\.3[0-2]\\.\\d+$",
  "languages": ["python"],
  "exclude": ["tests/*", "docs/_build/*"],
  "release_notes": ["HISTORY*", "CHANGELOG*"]
}
```

Relative repository paths are resolved once by `load_config`, using the JSON file's directory.
An absolute config path works from an unrelated working directory, including paths with spaces
and Unicode. CLI, API and MCP use the same loader. Existing root-relative configs must be changed
to config-file-relative paths or absolute paths when upgrading.

The database endpoint defaults to `127.0.0.1:6379`. Set `RW_FALKORDB_HOST` and
`RW_FALKORDB_PORT` in the process environment to select a separate instance; explicit arguments
to `rw.graph.connect(host, port)` take precedence. Invalid endpoint settings fail rather than
falling back to another database.
# Investigation work limits

Each investigation shares one request-local deadline and counters across revision
resolution, graph reads and source verification. Optional configuration fields can
lower the defaults: `query_timeout_seconds` (120), `query_max_rows` (250000), and
`query_max_source_bytes` (67108864). Nested queries inherit the counters. Separate
requests have separate budgets. Direct `RepoQuery` users can supply `ReadLimits`.

Graph statements receive a timeout of at most 1000 ms and the remaining deadline;
new read clients use a socket timeout of at most two seconds. Git subprocesses
receive the remaining request time and are killed/waited when that time expires.
Python processing checks cooperatively between reads and before returning results;
these checks do not establish a hard process-memory or operating-system wall-time
ceiling. Callers injecting a database client also own its transport timeout policy.

Graph output is clamped to remaining rows before it is materialized. A filled,
clamped result has unknown completeness and becomes an explicit
`RETRIEVAL_BUDGET_EXHAUSTED` gap. Source-byte accounting counts blobs when read in
each public query operation; repeated operations can consume the same bytes again.
This is evidence-work accounting, separate from model-token accounting.

`retrieval_budget` reports limits, consumed rows/bytes, graph call count and the
exhausted resource. `within_limits` describes accounting, not answer completeness.
Exhaustion clears supported findings/citations, final answers and compatibility
dispositions. Query pages expose incomplete coverage; restart with a narrower
investigation rather than treating an empty result as proof of absence.
