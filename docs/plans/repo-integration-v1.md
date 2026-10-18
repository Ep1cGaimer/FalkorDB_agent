# Repository integration v1 — shared design (for remquirements-v1.md S1–S6)

This is the contract both the test writer and the implementer follow. Requirements and evidence
rules live in `remquirements-v1.md`; status lives in `docs/REPO_STATUS.md`.

## Constraints

- Python 3.12, **no new dependencies** (no pip in the venv). Allowed: stdlib, `falkordb`, `redis`,
  `pydantic`, `fastapi`, `httpx` (all already installed). Language extraction uses stdlib `ast`.
- **Ingestion never executes repository code**: no `import`, `exec`, `subprocess` of repo files, no
  `git checkout` of the working tree. Git access is read-only plumbing through `git -C <path>`
  (`rev-list`, `log`, `cat-file`, `ls-tree`, `diff-tree`, `for-each-ref`, `merge-base`).
- FalkorDB runs at `127.0.0.1:6379`. Each repository gets its own graph `rw_repo_<name>`; tests use
  unique graph names and delete them.
- The existing fixture product (`rw.pipeline`, `fixtures/shop`, `fixtures/astronomy-shop`) is the
  regression baseline and must keep passing unchanged: `python -m pytest -q -m "not live"`.
- Real repositories are cloned (bare or normal, never checked out by the indexer) into
  `artifacts/repos/<name>` (git-ignored). Tests that need network or real clones are marked
  `@pytest.mark.realrepo` and skipped when the clone is absent.

## Package layout: `src/rw/repo/`

| Module | Responsibility |
|---|---|
| `config.py` | `RepoConfig` (pydantic): `name` (`[a-z0-9][a-z0-9-]{0,63}`), `path`, `revisions` (explicit refs) and/or `tag_pattern` (regex), `languages` (e.g. `["python"]`), `include`/`exclude` globs, `release_notes` globs (e.g. `CHANGELOG*`, `HISTORY*`, `docs/changelog*`). Loaded from `repos/<name>.json`. `load_config(name_or_path)`. |
| `git.py` | Read-only git access. `resolve(rev) -> sha`, `commits(revs) -> [Commit(sha, parents[], author_time, subject, message)]` in topological order, `tags() -> [Tag(name, target_sha, message)]`, `tree(sha) -> [(path, blob_sha, mode)]`, `blob(sha) -> bytes`, `changes(parent, child) -> [Change(status A/M/D/R, old_path, new_path, similarity)]` with `-M` rename detection, `is_ancestor(a, b)`. |
| `adapters/__init__.py` | Adapter registry. `Adapter` protocol: `language`, `extensions`, `version`, `extract(path, data: bytes) -> Extraction`. `Extraction(symbols, relations, errors, limits)`. Files with no adapter are recorded as **coverage gaps**, never silently dropped. `SUPPORTED_LANGUAGES` and each adapter's declared `LIMITS` (list of strings) are importable. |
| `adapters/python.py` | `ast`-based: module, class, function, method symbols with qualified names and 1-based line spans; `IMPORTS` relations (parsed); `CALLS` by simple name resolution (**inferred**); `INHERITS` (parsed base names). Syntax errors become extraction errors, not crashes. |
| `model.py` | Dataclasses: `Citation(repo, commit, path, start_line, end_line, content_hash)`, `Symbol`, `Relation(kind, source, target, provenance in {"parsed","inferred"}, extractor="python@<version>")`, `Page(items, next_cursor, truncated, coverage)`, `Gap(kind, detail)`. |
| `index.py` | `index_repository(config, graph_name=None, db=None, *, interrupt_after=None) -> IndexReport`. Incremental: blobs keyed by content hash are extracted once and reused across revisions/re-runs. Records an `ImportRun` node (`STARTED` → `COMPLETE` / `FAILED`) with metrics (`seconds`, `peak_memory_bytes` via `tracemalloc`, `blobs_new`, `blobs_reused`, `commits`, `nodes`, `edges`). Re-indexing after new commits invalidates evidence of changed/deleted files for the new revisions without touching old revisions. `interrupt_after=N` raises after N blobs (test hook); a later run resumes and completes. |
| `query.py` | Bounded queries (every one takes `limit` ≤ 200 and `cursor`, returns `Page`): `symbols(rev, name=None)`, `dependencies(rev, symbol, hops=1..5)`, `dependents(rev, symbol, hops)`, `changes_between(rev_a, rev_b)` (renames/deletions), `symbol_history(symbol_or_path, revs)`, `fix_status(rev, fix_commit) -> FixStatus(state in {"PRESENT","ABSENT","UNCERTAIN"}, citations, gaps)`, `release_notes(rev)`. All read only from revisions whose `ImportRun` is `COMPLETE`; anything else is a `Gap(kind="INCOMPLETE_IMPORT")`. Every item carries a `Citation`. |
| `investigate.py` | `investigate(repo, revision, question, *, mode="retrieval") -> RepoFindings(findings[], gaps[], citations[], unresolved: str|None)`. Retrieval-only findings never carry a compatibility disposition; `disposition` is `None` unless a runtime adapter ran (S6). Unresolved repo/revision/change → `unresolved` explains what to clarify. |

## Graph schema (per repository graph)

Nodes: `Repository{name}`, `Commit{sha, author_time, subject}`, `Tag{name}`, `Blob{content_hash, git_sha, language, extracted_by}`, `Symbol{id, qualname, kind, start_line, end_line}`, `ReleaseNote{path, content_hash}`, `ImportRun{id, status, started_at, finished_at, metrics_json}`.

Edges: `(Commit)-[:PARENT {order}]->(Commit)`, `(Tag)-[:POINTS_TO]->(Commit)`, `(Commit)-[:HAS_FILE {path}]->(Blob)`, `(Blob)-[:DEFINES]->(Symbol)`, `(Symbol)-[:IMPORTS|CALLS|INHERITS {provenance, extractor}]->(Symbol or external Symbol{external:true})`, `(Commit)-[:HAS_NOTE]->(ReleaseNote)`, `(ImportRun)-[:INDEXED]->(Commit)`.

Large-history storage (S4/E3; schema unchanged, two bookkeeping properties added):
- Every reachable commit keeps its full file map (`HAS_FILE`), so any indexed sha stays queryable. Maps
  are computed from one `git log --raw --diff-merges=first-parent` pass (parent map + first-parent
  diff) and blobs are read through one streamed `git cat-file --batch`; writes are batched `UNWIND`s.
- `Commit.files_done = true` marks a commit whose file map is fully written; later runs (updates,
  resumes) write file maps only for new commits and rewrite partially written ones.
- `Blob.extracted_by` = `<language>@<adapter.version>` (`"none"` for files without an adapter) is set
  last; a blob without it, or with an older extractor identity, is re-extracted after its previous
  Symbols are `DETACH DELETE`d, so no stale relation edges survive a version change.
- Query bounds: `symbols` pages server-side (ORDER BY/SKIP/LIMIT + count); reads larger than the
  server result-set cap are fetched in pages or split; dependency walks stop after `MAX_WALK_EDGES`
  edges with `Gap("TRUNCATED")`/`coverage["frontier_truncated"]`; every page reports
  `coverage["total"]` and `coverage["returned"]`; bad cursors raise `ValueError` or return a
  `Gap("INVALID_CURSOR")` page.

Identity: a symbol is `(repo, blob content hash, qualname)`; a file at a revision is `(repo, commit sha, path)`. The same path in two repos or two revisions never shares a node unless the content hash is identical (then the Blob is shared *within one repo graph only*).

## Access surfaces (S5)

- CLI: `scripts/repo_index.py --config repos/<name>.json`, `scripts/repo_investigate.py --repo <name> --rev <ref> "<question>"` (JSON output).
- API: `POST /api/repos/{name}/index`, `GET /api/repos`, `POST /api/repos/{name}/investigate {revision, question}`.
- MCP: tool `repo_investigate(repo, revision, question)` registered in `rw.mcp_server` (the `mcp` package may be absent; logic must be testable without it, like the existing MCP client tests).

## Evidence locations

- Held-out history questions (E2): `evals/repo_questions/<repo>.json` — written **before** answers are
  inspected; each has `question`, `revision`, `expected_answer`, `expected_citations[]` (path, line span).
- Scale/perf runs (E3): `evals/repo_scale.py` → `artifacts/repo_scale/<timestamp>.json`; budgets
  declared in `evals/repo_budgets.json` before measuring.
- FalkorDB vs plaintext (E4): `evals/repo_benefit.py` with threshold declared in
  `evals/repo_benefit_threshold.json` before running → `artifacts/repo_benefit/`.
- Status table: `docs/REPO_STATUS.md` (PROPOSED / IN_PROGRESS / VALIDATED / BLOCKED per S1–S6).
