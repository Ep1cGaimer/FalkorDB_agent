# Repository configs

Each repository is onboarded by one JSON file, `repos/<name>.json`, loaded by
`rw.repo.config.load_config("<name>")` (or a path to the file). No code changes are needed to add a repo.

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | `[a-z0-9][a-z0-9-]{0,63}`; the graph is `rw_repo_<name>` |
| `path` | yes | local Git repository (bare or normal; it is never checked out or modified) |
| `revisions` | no | explicit refs to index (branches, tags, shas); all ancestors are indexed too |
| `tag_pattern` | no | regex; matching tags are indexed in addition to `revisions` |
| `languages` | no | adapters to use (default `["python"]`; see `rw.repo.adapters.SUPPORTED_LANGUAGES`) |
| `include` / `exclude` | no | path globs filtering indexed files |
| `release_notes` | no | globs for release-note files (default `CHANGELOG*`, `HISTORY*`, `NEWS*`, ...) |

Files without an adapter are recorded as `UNSUPPORTED_LANGUAGE` coverage gaps, not dropped silently.

```json
{
  "name": "requests",
  "path": "artifacts/repos/requests",
  "revisions": ["main"],
  "tag_pattern": "^v2\\.3[0-2]\\.\\d+$",
  "languages": ["python"],
  "exclude": ["tests/*", "docs/_build/*"],
  "release_notes": ["HISTORY*", "CHANGELOG*"]
}
```
