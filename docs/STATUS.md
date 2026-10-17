# Build status

Updated 2026-10-17 (PR #16 reviewer fixes; earlier dated evidence is preserved below).
Product: **RollbackWitness**, build mode. Current implementation branch: `feat/mcp-http-bridge`,
rebased onto `main` at `1f51cfc` after PR #15 merged. The unrelated `d311456` documentation commit
from PR #14 is excluded. Synthetic fixture only — no production data or product deployment.

Every row below is a command that was actually run, with its observed output. Nothing here is a plan
or an estimate.

## MCP exposure — 2026-10-17

Implemented six optional stdio tools through the existing single-worker HTTP API, strict transport
contracts, bounded lists/client/result sizes, human review links, setup opt-in and base/MCP CI.
Canonical domain models, hashes, checker, probes, provider routing, fixture bytes, oracle cases and
SQLite schema are unchanged. See [MCP.md](MCP.md) for installation and operational limits.

Initial implementation evidence, before PR #15 and the reviewer fixes, observed locally on
**macOS 27.0.1 arm64, Python 3.12.13**:

| Check | Observed result |
|---|---|
| Pre-change baseline | `.venv/bin/python -m pytest -q -m 'not live' --tb=short`: **295 passed, 3 deselected**. |
| Fresh dependency environment | `/tmp/rw-mcp-compat`: resolved/installed **mcp 2.3.0**, mcp-types 2.3.0, httpx2 2.13.1 alongside unchanged Pydantic 2.14.1, FastAPI 0.143.2, Starlette 1.8.0, httpx 0.28.1, Uvicorn 0.54.0, FalkorDB 1.8.0, Redis 8.1.0 and pytest 9.1.1. |
| Base-only non-live suite | `.venv/bin/python -m pytest -q -m 'not live' --tb=short`: **409 passed, 3 skipped, 3 deselected**. Three SDK-dependent modules explicitly skip without the optional extra; no unconditional MCP import was added to existing application/CLI modules. |
| MCP-enabled non-live suite | `/tmp/rw-mcp-compat/bin/python -m pytest -q -m 'not live' --tb=short --junitxml=/tmp/rw-mcp-results.xml`: **448 passed, 3 deselected**, zero skips. Includes HTTP contracts, JS handoff/matcher, bridge transport/errors/budgets/concurrency, exact composed-text boundaries, canonical integrity tampering, multiple distinct receipts with FAIL dominance, zero-obligation bindings, replay, clarification, partial/orphan evidence and full human action flow. |
| Deterministic smoke | `/tmp/rw-mcp-compat/bin/python scripts/smoke.py`: **8/8 checks PASS**, exit 0; BLOCKED approval refusal, BOUNDED_PASS alternative, simulation true/false idempotency, partial/orphan evidence, isolated `rw_smoke_5143a584` graph cleanup. No model calls. |
| Actual stdio subprocess | Official SDK ClientSession with **2026-07-28 discovery** and **2025-11-25 initialization**, launched from a temporary cwd: exactly six tools, outputSchema/local refs, text/structuredContent parity, strict arguments, tool/protocol errors, no backend access on discovery, missing backend, clean EOF, JSON-only stdout and stderr-only setup diagnostics. A near-limit result test measures SDK text duplication and escaping (under 512 KiB total serialization for the exercised escaped payload). |
| Setup from arbitrary cwd | Default `setup.sh` followed by `setup.sh --mcp`, invoked from `/tmp` against a temporary checkout containing the setup files and pyproject: both exit 0, exact pins verified. The project's existing base `.venv` was preserved. |
| Browser handoff | Real Helium browser on an isolated API at port 8123: MCP-created ID loads original/current request, labels and fleet; page load/refresh log only GETs after initial creation. Human confirmation yields exact-plan BLOCKED evidence/witness; alternative selects a fresh unverified candidate. Temporary ledger and unique `rw_test_browser_7a0b96510fa143e18cb438d862d281c0` graph; API stopped and graph deleted. Focused Node tests also cover malformed/unknown links, refresh, latest selection, earlier attempts and exact displayed/submitted plan hash. |
| Static checks | `git diff --check`, Python compileall, `sh -n scripts/setup.sh`, workflow YAML parse: pass. |

Tests initially failed under sandbox-denied localhost access; the results above used permitted local
network access to the existing FalkorDB. No live provider evaluation was rerun. Windows setup/stdin
lifecycle and Linux CI execution have **not been observed locally**; the workflow now includes both
Linux install modes and a Windows PowerShell/stdio job. PR #16 at `f5afcbb` passed both Linux
install modes, Windows MCP checks and GitGuardian.
The rebased source revision `cdf5a9a` also passed all three CI jobs and GitGuardian in
[run 39007803917](https://github.com/Ep1cGaimer/FalkorDB_agent/actions/runs/39007803917).

### Reviewer-fix validation — 2026-10-17

- MCP-enabled suite: `/tmp/rw-mcp-compat/bin/python -m pytest -q -m 'not live' --tb=short` →
  **460 passed, 3 deselected**, zero skips.
- Base suite: `.venv/bin/python -m pytest -q -m 'not live' --tb=short` →
  **421 passed, 3 skipped, 3 deselected**; skips are the three optional SDK modules.
- Deterministic smoke: `/tmp/rw-mcp-compat/bin/python scripts/smoke.py` → **8/8 PASS**, graph
  `rw_smoke_587dfea2` cleaned up. No live provider calls.
- Added compatibility checks compare `Investigation.public()` against the strict response schema
  and HTTP output through clarification, verification, alternatives, approval and repeat simulation.
- Browser acceptance: `UI_BROWSER_BINARY=/Applications/Helium.app/Contents/MacOS/Helium node
  tests/ui/check.mjs` passed the existing flow and new handoff/refresh, earlier clarification,
  exact-hash confirmation and invalid/expired-link cases. Zero browser exceptions or failed
  resource requests. One existing replay-clarification case skipped because no matching saved
  answer was available; deterministic clarification and its handoff were exercised.
- Static checks: `git diff --check`, Python compileall, shell syntax, Node module syntax and
  Ruby YAML parsing of the workflow all passed.
- Required-check gate: parsed the shipped YAML and executed its command with `success`, `failure`,
  `cancelled` and `skipped`; only `success` passed. The aggregate runs with `always()`.

### PR review status

[PR #16](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/16) is open. The reviewer requested
removing PR #14's unrelated commit, response-schema compatibility coverage, shared bridge constants,
explicit HTTP behavior-change documentation, porting handoff to PR #15's modules and this status update.
PR #15 merged at `1f51cfc`; PRs #14 and #13 remain open as of this review. The unrelated PR #14
commit was dropped rather than waiting for its merge. No merge or review approval has been submitted.

The pre-fix head `f5afcbb` passed GitHub CI: `test (false)`, `test (true)`, `mcp-windows` and
GitGuardian. The rebased source revision `cdf5a9a` passed the same checks, including both Linux
browser acceptance runs. The reviewer confirmed that main requires a check named exactly `test`;
the matrix alone only emitted `test (false)` and `test (true)`. A final aggregate job now reports
`test`, waits for the whole matrix and fails unless both legs succeeded, including when a leg
failed, was cancelled or skipped. PR #18's separate browser-race fix remains open and is not
included here; update from main after it merges. Next action: inspect the
[current PR checks](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/16/checks) and obtain reviewer
approval before merging.
Local workflow identity remains unauthenticated and single-operator.

## Verified (commands actually run)

| Milestone | Evidence |
|---|---|
| Runtime | `docker compose -f docker-compose.yml config` resolves to image `falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`, container `rw-falkordb`, ports `127.0.0.1:6379` and `127.0.0.1:3000`. Running container: module ver 60002, Redis 8.10.2. `.venv` = Python 3.12 via uv with a project-local `.uv-cache`; client `falkordb` 1.8.0. |
| FalkorDB behavior | parameterized `$params` work; `ro_query` rejects writes; APOC absent; **a property set to `null` is not stored** — unknowns are detected by comparison with independently parsed files, never stored as null. |
| Contracts | `docs/CONTRACTS.md` + `src/rw/contracts.py` describe the current code: probe nonce/result channel, `GapKind` list, `GraphEvidence` fields, `build_evidence(declarations=…)`, `revalidate`, grounding providers, API endpoints. |
| Fixture | `fixtures/shop/`: cart 1.4/1.5, checkout 2.0/2.1, one `cart-cache`, retained records `saved-cart-1001` (cart/v1) and `saved-cart-2002` (cart/v2), plus the negative snapshots `snap-002-partial` / `snap-003-orphan`; deterministic rebuild via `scripts/build_fixture.py`. |
| Graph | `src/rw/graph.py`: importer + fixed parameterized queries, `cap+1` truncation; 8 live integration tests, mutation-checked (dropping each edge type fails ≥ 1 test). |
| Checker | `src/rw/verification.py`: obligations from the FalkorDB multi-hop path, cross-checked against the independently loaded declarations and the manifest read from disk; `ROUTE_DECLARATION_MISMATCH`; writer/format reconciliation; fail dominance; snapshot binding on the evidence; revalidation is scoped to the stores the fleet actually read, so a manifest store no route reads cannot invent writer drift. |
| Probes / simulator / API | `src/rw/probes.py`, `simulation.py`, `api.py`: per-run nonce result channel that keeps ordinary reader output and early exits out of the verdict (failure containment for allowlisted readers, not a sandbox), receipts bound to the exact obligation tuple, approval only for `BOUNDED_PASS` on current bytes (`revalidate` → HTTP 409 on drift), idempotent SQLite simulation, one clarification round via `POST /api/investigations/{id}/answer`. |
| Independent oracle | `evals/expected/dispositions.json` (authored without running `src/`): 8 cases A–H. `.venv\Scripts\python.exe -m pytest tests/test_acceptance_oracle.py -q` → **8 passed** on the real server with the real readers. Case A: cart 1.4 reader × `saved-cart-2002` → FAIL exit 10 `unsupported saved-cart format 'cart/v2'` → BLOCKED. Case B (cart 1.5, `basket_v2=false`) → BOUNDED_PASS. |
| Relational control | `.venv\Scripts\python.exe evals\relational_control.py` → `SQL obligations == FalkorDB obligations: 8/8 cases`, `SQL obligations == independent oracle: 8/8 cases` — **a tie** (representational parity, not superiority; the control is not handicapped). |
| Deterministic smoke (`scripts/smoke.py`) | `.venv\Scripts\python.exe scripts\smoke.py` at HEAD `5829810` → exit 0, **8/8 PASS**; creates graph `rw_smoke_9e3b9ec4` and deletes it in the same run. Checklist: `PASS snap-001 BLOCKED` (receipt `saved-cart-2002 ValueError: unsupported saved-cart format 'cart/v2'`; witness `(Plan)→-HAS_DEPLOYMENT->(Deployment cart)-RUNS->(Release cart 1.4)-EXECUTES_ROUTE->(ReaderRoute load_saved_cart)-READS_FROM->(StateStore store:cart-cache)<-IN_STORE-(Batch saved-cart-2002 (cart/v2))-WRITTEN_BY->(Release writer 1.5)`), `PASS blocked approval refused (HTTP 409)`, `PASS snap-001 BOUNDED_PASS`, `PASS approved as smoke-operator; simulate applied=true, repeat applied=false`, `PASS snap-002-partial NEEDS_EVIDENCE (COVERAGE_INCOMPLETE)`, `PASS snap-003-orphan NEEDS_EVIDENCE (FORMAT_UNKNOWN, WRITER_UNKNOWN)`, `PASS cleanup graph=rw_smoke_9e3b9ec4`, `PASS deterministic-smoke complete`. Grounding is injected and labeled `deterministic-smoke`, `live=false`: no model call, no key, temp SQLite ledger. Run standalone it prints the third-party Starlette/httpx deprecation notice (the one warning narrowly silenced inside pytest by `pyproject.toml`). |
| Operator-specified fleet (`scripts/investigate.py --fleet`) | `.venv\Scripts\python.exe scripts\investigate.py --fleet cart=1.4 --confirm-as tester` → exit 0; prints `[OPERATOR-SPECIFIED FLEET — no agent involved]`, resolves `cart 1.4 (release:cart:9703e568235e03f3)` from the graph, verifies with `model=operator-specified, live=False`, probes 4 obligations (`saved-cart-2002` fails with `unsupported saved-cart format 'cart/v2'`) and reports `DISPOSITION: BLOCKED` with the witness path. `--snapshot` selects the snapshot; an unknown service/version/flag exits 2 with nothing verified (Task 11 report). |
| Live demo (2026-10-16, 16:37) | Full demo on `groq gpt-oss-120b` → clarification → answer → `cart 1.5 basket_v2=false` + `checkout 2.1` → **`BOUNDED_PASS`** (4/4 probes PASS). A labeled live run, not a replay. |
| Test suite | `.venv\Scripts\python.exe -m pytest -q -m "not live"` at HEAD `5829810` → **295 passed, 3 deselected** (needs the container above). The 3 deselected tests call the live provider. |
| Reproducibility (fresh clone) | `git clone --branch build/slice-2` into a temp directory, with its own `.venv` and `.uv-cache` inside the clone (the main checkout's `.venv` untouched), then both setup scripts: `scripts/setup.ps1` under Windows PowerShell and `sh scripts/setup.sh` under Git Bash (`C:\Program Files\Git\bin\bash.exe`), each installing Python 3.12.10, the 21 packages from `pyproject.toml` and `pytest==9.1.1` (exit 0). `.venv\Scripts\python.exe -m pytest -q -m "not live"` → **229 passed, 3 deselected**, and `.venv\Scripts\python.exe -m pytest -q -m "not live" tests/test_acceptance_oracle.py` → **8 passed**. `docker compose -f <clone>\docker-compose.yml config` resolves the pinned image without starting a second container, and the three `fixtures/shop/snapshots/*/manifest.json` sha256 values in the clone equal the main checkout's (`416e1df3…`, `734cae65…`, `7e2947e4…`). |
| Slice-2 commits | `f8e4a7c` (T1), `3d3310d` (T2), `c8aad81` (T3), `eb4939e` (T4), `24ec745` (T5), `92acc5a` (T6), `103f5df` + `0bf177f` (T7), `a22b986` (T8), `1d82ec6` + `27b63aa` (T9); fix wave `bdf53cb` (C1), `12f0488` (C2), `4f60c6e` (I3), `8b1faaa` (I4+I5), `8ae1f0a` (I6), `6f74539` (I7), `498e983` (I8 + recovered minors); Task 10 UI/snapshot `a8a1b48` + `da08d55`; Task 11 smoke + operator fleet `52f5901`; Task 12 revalidate store scope `6f50450` + this status-sync commit. |
| Issue fixes (2026-10-16) | Merged on `main` and reviewed: **#1** citation-correction round gated to citation-only failures (`691920f`, `81f1d18`; Opus review → fix → Sonnet re-review clean); **#5** route-derived read-store scope test (`9d54860`); **#6** UI polish — readable snapshot labels, "NOT LIVE" for non-provider models, header scroll margin, trusted citation `release_id` (`c67639a`); **#7** robustness — duplicate release id → `NEEDS_EVIDENCE`/`INVALID_FLEET`, route named in path-row gaps, pinned `WRITTEN_BY` wording, smoke `RW_FALKORDB_HOST`/`PORT`, `--fleet` unconfirmed-scope test (`34be265`, `684c1c5`, `11f5d1a`, `5829810`); **#8** docs consistency (`b445215`). #5–#8 approved by GPT-6 Astra review. |

## Known limits (measured, not assumed)

- **Groq free tier (re-measured 2026-10-16).** `openai/gpt-oss-120b` allows 200k tokens/day and was
  exhausted again today (198,269/200,000 used); `qwen/qwen3.8-27b` allows 7000 input / 1000 output
  tokens per minute and returned HTTP 413 "request too large" on longer grounding turns. A live run
  can therefore fail fast with a non-retryable quota refusal (the chain records the abandoned attempt
  and tries the next entry).
- **Live grounding eval — partial, 2026-10-16.** A `--runs 3` attempt (~17:00–17:20) completed only the
  main case: main request ×3 = **1 `CLARIFICATION`** (`gpt-oss-120b`) + **2 `PROPOSAL` `cart 1.5
  basket_v2=off`** (`qwen3.8-27b` fallback; matches expected `PROPOSAL`). The other cases did not
  complete: DNS outage, then `gpt-oss-120b` daily limit exhausted and `qwen3.8-27b` HTTP 413 on the
  longer grounding turns. The eval is **incomplete**; see open item #2.
- **Live grounding eval — earlier recorded run (history, 2026-10-15): 6/10 runs matched the expected
  kind** (`evals/results/grounding_20261015T205622Z.md`, git-ignored: 5 cases × 2 runs, model
  `groq:openai/gpt-oss-120b`, chain default, temperature 0). The aggregate hides which case failed, so
  the case-level result is listed below; a kind match that also carries a validation error still counts
  as a match but is not clean grounding. This is a small-N single-machine observation, not a benchmark
  or a ranking.

  | case | expected kind | run 1 | run 2 | note |
  |---|---|---|---|---|
  | main | PROPOSAL | CLARIFICATION — miss | CLARIFICATION — miss | asked instead of proposing the requested change |
  | ambiguous | CLARIFICATION | PROPOSAL — miss | PROPOSAL — miss | proposed `cart=1.4` instead of asking which change |
  | inseparable | CLARIFICATION | match | match | run 1 cited a code quote absent from the excerpt (`CITATION_QUOTE_NOT_IN_EXCERPT`, dropped by validation) |
  | named-old-build | PROPOSAL | match | match | proposed `cart=1.4` |
  | keep-everything | CLARIFICATION | match | match | asked instead of proposing |
- **Live LLM control (#3) has no live run** — same quota limits; the control prompt is larger than
  `qwen3.8-27b`'s per-minute input cap, so it cannot be served on the current chain, not a code
  defect. No control score is claimed (open item #3).
- **Live model access from this machine is flaky for Gemini**: `gemini-3.8-flash` and larger fail
  almost always with TLS record corruption (`SEC_E_MESSAGE_ALTERED` / `SSLV3_ALERT_BAD_RECORD_MAC`) or
  503; pinning TLS 1.2 and retrying helps; `gemini-3.1-flash-lite` answers normally. The product
  default chain is Groq.
- **SQL control = tie** on obligation sets (8/8). Parity is reported as parity.
- **Synthetic fixture only.** No production data, and the "simulate" action writes a local SQLite
  record; it performs nothing.
- **`BOUNDED_PASS` = modeled byte/shape readability only.** It is not behavioral compatibility and
  not a claim that no other reader or writer exists.
- **UI screenshots are untracked** (`artifacts/screens/` is git-ignored; the images were removed from
  git in Task 8), so the console visuals must be regenerated locally.
- **Replay is labeled.** `model=replay:<file>` with `live=False` means a saved transcript was re-run.

## Not done / next (open issues)

Remaining open items, tracked in `docs/OPEN_ISSUES.md`:

- **#2 — live grounding eval incomplete.** The 2026-10-16 `--runs 3` attempt finished only the main
  case before DNS/quota stopped it; re-run the full case set on a fresh quota and record the case-level
  table. The 6/10 table above is history and predates the ambiguity rule in `SYSTEM_PROMPT`; it is
  code-and-test evidence, not a live score.
- **#3 — live LLM control not run.** The equal-information flat-context control is blocked by the same
  limits (its prompt exceeds `qwen3.8-27b`'s per-minute cap). No control score is claimed.
- **#4 — Groq free-tier limits.** `gpt-oss-120b` daily limit exhausted again (198,269/200,000);
  `qwen3.8-27b` cannot fit the full grounding turns (HTTP 413). A documented choice — paid tier, a
  second provider key in the chain, or a smaller eval budget — is still needed.

No deployment, publishing, submission or third-party message has been made.

Setup and demo commands for a reviewer: [QUICKSTART.md](QUICKSTART.md).
