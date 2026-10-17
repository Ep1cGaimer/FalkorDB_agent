# Build status

Updated 2026-10-18. Includes issue #22 evidence on `5a7160f`, based on main through PR #30.
Earlier dated evidence is preserved below. Product: **RollbackWitness**,
synthetic fixture only — no production data or product deployment.

For issue #3 and #4 work, see [the implementation report](ISSUE_3_FIX_REPORT.md) and
[the quota plan](ISSUE_4_QUOTA.md). The historical comparison numbers are author-reported;
their raw artifacts are not committed. They are separate from the issue #2 evaluation below.

Every row below is a command that was actually run, with its observed output. Nothing here is a plan
or an estimate.

## Fair comparison and relationship ablation — issue #22, 2026-10-18

**Primary result: tie, 3/3 evidence-consistent observations in each shared-checker arm.**
Both propose oracle fleet B (cart 1.5 with `basket_v2=false`, checkout 2.1), with `4/4`
exactly bound reader/record receipts and `BOUNDED_PASS`. This is a readability result:
the oracle labels the requested basket rollback **partial**, while the receipt correction is kept.
It does not establish full request fulfillment or cross-service basket behavior.

The committed [portable bundle](../evals/evidence/issue-22/live-5a7160f-gemini31lite-05/README.md)
contains all nine observations, complete delivered prompts/tool histories, validation events,
receipt tuples, source/expectation hashes, telemetry, scoring inputs, and intact/ablated/restored
reports. Collection revision: `5a7160f676ddab30438e141fe68594506c9ccaff`, with runtime sources unchanged.
The recorded dirty inventory contains only README/STATUS drafts, which are not model inputs; generated
evidence is excluded from source hashes. No model-facing code, fixture, oracle or budget changed within the batch.

Protocol: one pinned `gemini:gemini-3.1-flash-lite`, temperature zero, eight model turns,
1,000 maximum output tokens per call, six bounded HTTP attempts, 90-second request timeout,
2–30 second exponential backoff (or provider Retry-After), no alternative conversation and no
operator clarification answer. Scope confirmation permits checking only. No action approval,
simulation or deployment was performed. The three blocks rotate the arm order.

UTC collection window: `2026-10-17T19:38:32.911447+00:00` to
`2026-10-17T19:39:52.036425+00:00` (2026-10-18 locally). The nine arm times sum to **78.537 seconds**.
There were **21 model calls, 21 HTTP attempts**, and **113,580 reported tokens**
(110,763 prompt; 2,817 candidate). No transport retries occurred in this primary batch.
All successful responses supplied usage; no missing usage is reported as zero. Failed-request usage
in the preserved earlier attempts remains unknown. Checker, grounding, whole-arm and request times
are preserved separately; these timings do not establish a general latency ranking.

Primary matched comparison: **tie**; aligned blocks=3.

Evidence consistency of grounding/retrieval with shared checker; request fit reported separately. Clarification semantics are ungraded. Byte/shape readability does not establish cross-service behavior.

### Matched grounding with shared checker

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 10.921 |
| 1 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 8.584 |
| 2 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 11.147 |
| 2 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 13.115 |
| 3 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 9.087 |
| 3 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 4.037 |

### Legacy workflow

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 8.85 |
| 2 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 7.884 |
| 3 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 4.912 |

The legacy clarification rows are completed model decisions with no plan or checker result and
no readability denominator; their semantic appropriateness is ungraded. In each legacy conversation,
the model made two rejected probe calls using `cart-cache` instead of the supplied canonical
`store:cart-cache`, then asked about the route/store mapping. The record preserves these
errors and the question; it is not a finding that the engineer's original request needed clarification.
The legacy table measures a broader workflow and is not pooled with the matched result.

Deterministic ablation on the same fixture bytes and dedicated FalkorDB 6.0.2 / Redis 8.10.2:
exactly two `Batch -IN_STORE-> StateStore` edges were removed. Every node ID, label/property,
remaining edge, source/payload digest and both inventoried records survived. Four connected
reader–record paths became zero, and both candidates became `NEEDS_EVIDENCE` with missing-path/
inventory gaps and zero connected obligations. Restoring those two edges restored the same
obligation tuples, witnesses and receipt results: A `BLOCKED → NEEDS_EVIDENCE → BLOCKED`;
B `BOUNDED_PASS → NEEDS_EVIDENCE → BOUNDED_PASS`. Only receipt nonce/time were excluded from
result comparison. Owned graphs were independently verified absent after cleanup. The lost capability
is **connected reader–record obligation enumeration and witness paths**; SQL or an independent join
can reconstruct the pairs, and raw records remain discoverable.

Earlier attempts remain separate and are not pooled into the nine-row batch:

- [Groq attempt 1](../evals/evidence/issue-22/live-e811d19-01/manifest.json): graph completed, flat request refused with HTTP 413; seven slots unrun.
- [Groq attempt 2](../evals/evidence/issue-22/live-c2b777e-02/manifest.json): compact addresses, same refusal and preserved unrun slots.
- [Gemini 3.8 attempt](../evals/evidence/issue-22/live-0821faa-gemini-03/manifest.json): first tool response succeeded, subsequent call exhausted six attempts with HTTP 429. A separate sanitized capacity diagnostic identified the exhausted 20-request daily quota.
- [Superseded Flash-Lite protocol](../evals/evidence/issue-22/live-0821faa-gemini31lite-04/README.md): all nine conversations completed, but the final full regression found omitted canonical store annotations in the compact context. It is retained with acceptance disabled and excluded from the headline. The final batch restores those addresses and follows both full suites passing; no model answers were repaired.
- Standalone [Groq](../evals/evidence/issue-22/groq-capacity-preflight.json) and [Gemini capacity diagnostics](../evals/evidence/issue-22/gemini-alternatives-capacity.json) are feasibility probes, not primary experiments. Gemini 3.7 timed out, 2.5 was unavailable, and 3.6/3.1 Lite answered tiny requests. The user's Gemini preference led to the separately pinned Flash-Lite batch.

Commands actually run (repository's existing Python 3.12.13 base interpreter was used from the worktree):

```sh
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 python evals/run_comparison.py --runs 3 \
  --model gemini:gemini-3.1-flash-lite --db-port 6382 \
  --out artifacts/issue-22/live-5a7160f-gemini31lite-05
python evals/relationship_ablation.py --db-port 6382 \
  --out artifacts/issue-22/live-5a7160f-gemini31lite-05/ablation
python evals/comparison_evidence.py export --input artifacts/issue-22/live-5a7160f-gemini31lite-05 \
  --out evals/evidence/issue-22/live-5a7160f-gemini31lite-05
python evals/comparison_evidence.py verify evals/evidence/issue-22/live-5a7160f-gemini31lite-05
python evals/score_controls.py --bundle evals/evidence/issue-22/live-5a7160f-gemini31lite-05 \
  --json /tmp/issue22-rescored.json
```

Post-collection validation/rescoring revision: `dd8560c83b3ed315946861f045bd968500fc9584`.
Only the portable validator changed after collection: normal filesystem aliases outside the bundle
(such as macOS `/var`) are accepted, while internal artifact symlinks remain rejected. Model-facing
inputs, prompts, budgets, raw observations and scores did not change. Both revisions are recorded
in the bundle manifest; documentation was completed after collection.

Main/PR compatibility: PRs #21 and #29 were merged before implementation; the strict scorer and
full route/store obligation identity are retained. PR #30 merged during work and was merged cleanly
before the final batch. Draft PR #31 at `f1942d3` has no file conflicts; it explicitly reports its own
intent-check wiring as unfinished. The flat adapter inherits product prompt/tool schemas, calls the
shared terminal validator, and supplies the original request in validation state with file-backed
service identities. A change to #31's unfinished loop-level validation will need its own final
integration check and a fresh protocol/recollection if it changes model inputs; no observations
from that draft are mixed into this batch.

Validation on macOS arm64, Python 3.12.13, pinned FalkorDB 6.0.2:

| Check | Observed result |
|---|---|
| Full base installation, non-live | **702 passed, 3 optional MCP skips, 3 live tests deselected**. |
| Full MCP-enabled installation, non-live | **741 passed, 3 live tests deselected**, no skips. |
| Deterministic smoke | All checks PASS, including blocked approval refusal, drift/evidence gaps, and idempotent simulation. |
| JavaScript unit tests | **16 passed**. |
| SQL / graph / independent oracle | Equal obligation sets in **8/8** baseline cases; inherited seven-obligation overlay regressions pass. |
| Portable evidence | Moved bundle verified/rescored with credentials removed and sockets denied; all prior bundles also verify. |
| Portability regressions | **12 passed**, including a normal filesystem alias outside the bundle and rejection of an internal artifact symlink. |
| Whitespace | `git diff --check` passes. |

## Obligation identity combined with the evidence rules — issue #24, 2026-10-18

PR #28's route/store identity work, rebuilt on top of #21 so that both hold at once:
- Every evaluation obligation is keyed by (service, version, route_id, store_id, record_id).
- The scorer's evidence rules apply per full key: canonical obligation-hash check, exact receipt-tuple binding, FAIL > UNKNOWN > PASS folding, unsupported vs false BOUNDED_PASS, reported-gap handling.

Review findings fixed on top:
- `tests/fixtures/**` is protected from line-ending conversion, so the overlay's content-addressed release IDs match on Windows.
- `evals/obligation_identity.release_identity` follows the documented rule (skip `__pycache__`/`*.pyc`, sort by posix path), pinned to the runtime by a test.
- The flat control lists a route with no declared store as `store_id: null` instead of crashing.

Observed on Windows 11, Python 3.12, FalkorDB 6.0.2, with the MCP extra installed:

| Check | Observed result |
|---|---|
| Non-live suite | `.venv\Scripts\python.exe -m pytest -q -m "not live" -p no:cacheprovider`: **679 passed, 3 deselected**, 0 skipped. |
| Deterministic smoke | `scripts\smoke.py`: all checks PASS. |
| Operator fleet CLI | `scripts\investigate.py --fleet cart=1.4 --confirm-as you`: **BLOCKED**. |
| Relational control | `evals\relational_control.py`: SQL = FalkorDB = oracle in **8/8** cases, compared as full five-field keys. |
| JS unit tests | `node --test tests/js/*.test.mjs`: **16 passed**. |

No live model calls.

## Full evaluation obligation identity — issue #24 (author's PR #28 branch at `e6b15ec`), 2026-10-17

The table below is the PR author's own run on their branch, before it was combined with #21. The checks for the combined result are in the next section.

The oracle, SQL control, flat-control probe API and scorer now retain
`(service, version, route_id, store_id, record_id)` within each fixture/snapshot. Baseline cases A–H
preserve all 34 predictions, dispositions, gaps and request-fit labels. Authored overlay cases I/J
exercise seven obligations each, with two routes over cart-cache and a third over cart-archive,
including the same record ID with different bytes in both stores. Real graph reports and offline
scripted Gemini/Groq transcripts score `7/7`; removing any one observation scores `6/7`. Historical
calls receive an explicit inference note only when one exact obligation is identifiable.

Observed locally on macOS arm64, Python 3.12.13, using the existing local FalkorDB and isolated graph
names. No live provider calls were made. The existing CI workflow was unchanged.

| Check | Observed result |
|---|---|
| Focused oracle/SQL/control/scorer suite | **79 passed, 1 deselected**, before two additional direct-harness/retry regressions; subsequent control/scorer subset **49 passed, 1 deselected**. |
| Final base-only suite | `artifacts/issue-24/base-venv/bin/python -m pytest -q -m 'not live' --tb=short`: **472 passed, 3 skipped, 3 deselected**. Base environment installed offline from pinned cached dependencies; skips are the three optional MCP SDK modules. |
| Final MCP-enabled suite | `.venv/bin/python -m pytest -q -m 'not live' --tb=short --junitxml=/tmp/rw-issue24-mcp-suite.xml`: **511 passed, 3 deselected**, zero skips. |
| Explicit MCP SDK leg | `.venv/bin/python -m pytest tests/test_mcp.py tests/test_mcp_integration.py tests/test_mcp_stdio.py -q --junitxml=/tmp/rw-issue24-mcp-sdk.xml`: **39 passed**, zero skips. |
| Baseline SQL CLI | `.venv/bin/python evals/relational_control.py`: SQL = graph = authored oracle for **8/8 cases**, comparing full identity and cardinality. Variant CLI comparison also passed for **2/2 cases** inside the relational suite. |
| Direct fixture harness | All **14/14** authored variant predictions confirmed with isolated Python subprocesses and manifest-checked payload bytes; covered by both final suites. |
| Deterministic smoke | `.venv/bin/python scripts/smoke.py`: **8/8 PASS**, exit 0; isolated graph cleanup confirmed. |
| Browser acceptance | `UI_BROWSER_BINARY=/Applications/Helium.app/Contents/MacOS/Helium node tests/ui/check.mjs`: all available checks PASS, Chrome 155.0.8059.39; zero browser exceptions/failed resource requests. Existing replay-clarification case skipped because no saved question was available. QA server stopped and temporary graph cleaned up. |
| Static/source checks | `git diff --check`: pass. Removing only the added route/store fields makes the baseline oracle structurally identical to `origin/main`. |

Linux/Windows hosted CI and remote PR mergeability remain unobserved for this branch. See
[the implementation plan](ISSUE_24_IMPLEMENTATION_PLAN.md) and [oracle method](../evals/expected/README.md).

## Review-finding fixes — 2026-10-17

Fixes for defects an independent repository review reproduced on `main` at `793d7b1`:

- **Uncited agent proposals:** these used to reach BOUNDED_PASS. Every changed release now needs a verbatim changelog citation of that release, enforced in the grounding loop and again in `plan_from_proposal`.
- **Malformed provider replies and non-object tool arguments:** these used to crash the run. They now fail closed and fall through to the next configured model.
- **Flags given as the string `"false"`:** these used to become true. They are now invalid calls.
- **Fresh probe receipts past the 200-row cap:** history could hide them. Verification now reads back the exact ProbeRun ids it wrote.
- **Fleet drift after approval:** simulation still applied. Approval and first simulation now refuse a fleet that differs from the plan's `baseline_fleet_hash`.
- **Scorer:** it used to count UNKNOWN probes as a supported pass; a claim now needs its own PASS or FAIL evidence.
- **Fixture rebuild test:** it used to rewrite tracked fixture files; it now builds into a temporary directory.
- **CLI:** `investigate.py` used to reset the UI's graph; it now uses its own `rw_cli_<hex8>` graph and deletes it, even when setup fails partway.
- **Second review round:**
  - a truncated current-fleet or release-inventory read now refuses to build a plan; it used to allow BOUNDED_PASS;
  - incomplete current-fleet rows refuse `/approve` and `/simulate` with 409 instead of 500;
  - provider envelopes are type-checked before defaults, non-JSON 200 bodies and non-string tool names fail closed, and saved `usage` is limited to numeric token/time fields;
  - the scorer counts a receipt only when its tuple equals the obligation's, and FAIL dominates repeated results;
  - fixture copies inside the repo no longer report false codec drift.
- **Third review round:**
  - non-boolean or undecodable stored deployment flags refuse `/approve` and `/simulate` with 409;
  - HTTP 200 error envelopes or responses without `choices`/`candidates` are malformed and fall through to the next model;
  - the control loop has the same malformed-call guards as the product;
  - the scorer rejects obligations whose hash is not the canonical hash of their tuple, and treats a BOUNDED_PASS from a report that lists evidence gaps as unsupported.

Observed on Windows 11, Python 3.12, FalkorDB 6.0.2, with the MCP extra installed:

| Check | Observed result |
|---|---|
| Non-live suite | `.venv\Scripts\python.exe -m pytest -q -m "not live" -p no:cacheprovider`: **653 passed, 3 deselected**, 0 skipped (after the third review round). |
| Deterministic smoke | `scripts\smoke.py`: all checks PASS, cleanup PASS. |
| Operator fleet CLI | `scripts\investigate.py --fleet cart=1.4 --confirm-as you`: **BLOCKED**, cart 1.4 × saved-cart-2002 FAIL with the witness path; no `rw_cli_*` graph left. |
| Relational control | `evals\relational_control.py`: SQL = FalkorDB = oracle in **8/8** cases. |
| Browser acceptance | `tests/ui/serve_fixture.py` + `node tests/ui/check.mjs` (Edge 155): all checks PASS; one existing SKIP (no recorded replay clarification answer). |
| JS unit tests | `node --test tests/js/*.test.mjs`: **16 passed**. |

No live model calls were made for these fixes; live grounding behavior (issue #17, PR #19) is unchanged by them except that uncited proposals are now rejected.

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

*Historical (2026-10-17, before merge): PRs #13 and #16 have since merged into `main`.*

[PR #16](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/16) is open. The reviewer requested
removing PR #14's unrelated commit, response-schema compatibility coverage, shared bridge constants,
explicit HTTP behavior-change documentation, porting handoff to PR #15's modules and this status update.
PRs #14, #15 and #18 have merged into main and are included in the branch sync at `d4ad437`.
PR #13 remains open. No merge or review approval has been submitted for PR #16.

The pre-fix head `f5afcbb` passed GitHub CI: `test (false)`, `test (true)`, `mcp-windows` and
GitGuardian. The rebased source revision `cdf5a9a` passed the same checks, including both Linux
browser acceptance runs. The reviewer confirmed that main requires a check named exactly `test`;
the matrix alone only emitted `test (false)` and `test (true)`. A final aggregate job now reports
`test`, waits for the whole matrix and fails unless both legs succeeded, including when a leg
failed, was cancelled or skipped. PR #18's browser-race fix is included unchanged from main.
Before committing this sync, current main was checked at `d4ad437` with a passing `test` check.
Next action: inspect the
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

## Issue #2 live grounding evaluation — 2026-10-16

**Completed the full live evaluation; the ambiguity rule still guessed in 3/3 runs.**
This satisfies [#2](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/2)'s measurement and
reporting requirement, not a claim that ambiguity handling is fixed. The unchanged historical
expectations matched in **11/15** scheduled observations: **11 clean kind matches**, **0
error-bearing kind matches**. All 15 reached normal terminal results (8 proposals, 7
clarifications); there were **0 `ABORTED` and 0 provider `ERROR` rows**.

### Reproduction and provenance

- Evaluated commit: `771ce3814e7ad8bb6c5902e4ac9de83a711abbee` (`main`, also the task
  branch's starting commit); branch `fix/issue-2-live-grounding-eval`. No application,
  prompt, fixture, request, or expectation changes were made for this evaluation.
- UTC start: **2026-10-16 18:01:26Z** (runner stamp `20261016T180126Z`); final transcript
  saved **18:19:53.706435Z**. Python **3.12.13**, installed with `sh scripts/setup.sh`.
- Exact command: `.venv/bin/python -u evals/run_grounding_cases.py --runs 3 > artifacts/grounding-eval/issue-2-live-batch-2.log 2>&1`;
  exit code **0**, captured immediately. This is one complete invocation, separate from
  the interrupted attempt below and both historical runs in Known limits.
- Configured chain: `groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b`. Actual answering
  model: **`groq:openai/gpt-oss-120b` for all 15 rows**; no abandoned provider attempts
  in any saved transcript. `.env` loaded through `config.load_env()`; Groq key present,
  Gemini key absent. No operational overrides (`RW_GROUNDING_MODEL` and
  `RW_GROUNDING_RETRIES` unset). Temperature **0**, **8 turns**, **6 transport attempts**,
  **3 outer provider attempts** as configured by the unchanged product and runner.
- Fixture: `fixtures/shop`, snapshot **`snap-001`**; baseline cart **1.5** with
  `basket_v2=true`, checkout **2.1**. One imported graph serves the full invocation;
  all grounding reads are read-only. Server: the pinned FalkorDB **6.0.2** image and
  digest in `docker-compose.yml`, started at `127.0.0.1:6379` after inspecting existing
  containers (no existing service occupied the project's ports).
- SHA-256 of `SYSTEM_PROMPT` UTF-8 text:
  `0e05defab38ea444e96541fc931d6c377b246cea20065f018d4da6f226982c58`.
  SHA-256 of `snapshots/snap-001/manifest.json` bytes:
  `416e1df3791f754c6d1224ca7a458b262c3c27bfec0bbf308dadbb477d74091c`.
  Request-file SHA-256: `9ab57074f9c443be4d8d61e6b9c9081fcf6f4707accb72c0f449fdb99862c7f8`;
  expectation-file SHA-256: `5671bf5a86d5cd026ba6ce18e68bd2ced654179692bbfaabc6fef0632b366ef7`.
  All fixture-file, prompt, request, and expectation hashes matched before and after.
- Raw report: `evals/results/grounding_20261016T180126Z.md`. The table below was checked
  verbatim against it and rebuilt directly from all 15 saved transcripts; every
  case has exactly runs **1, 2, 3**, with no duplicates or omissions. Every terminal
  citation's quote is an exact substring of a retrieved excerpt and its content hash
  matches the excerpt's SHA-256. No citation correction events occurred.
- Temporary graph `rw_test_grounding_eval_30a173ab` was confirmed absent via
  `graph.connect().list_graphs()` at **2026-10-16 18:20:30Z**, independently of the
  runner's cleanup wording.

### Complete generated case-level table

The fleet column lists proposed changes; omitted services retain the baseline deployment.
`matches expected` compares only terminal kinds, not semantic correctness or compatibility.

| case | run | model | kind | proposed fleet | citations | validation errors | matches expected |
|---|---|---|---|---|---|---|---|
| main | 1 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.5{basket_v2=off} | changelog x3 | — | yes |
| main | 2 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.5{basket_v2=off} | changelog x2 | — | yes |
| main | 3 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x2 | — | no |
| ambiguous | 1 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x2 | — | no |
| ambiguous | 2 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x2 | — | no |
| ambiguous | 3 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x2 | — | no |
| inseparable | 1 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x2 | — | yes |
| inseparable | 2 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x3 | — | yes |
| inseparable | 3 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x2 | — | yes |
| named-old-build | 1 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x3 | — | yes |
| named-old-build | 2 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x3 | — | yes |
| named-old-build | 3 | groq:openai/gpt-oss-120b | PROPOSAL | cart=1.4 | changelog x3 | — | yes |
| keep-everything | 1 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x3 | — | yes |
| keep-everything | 2 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x2 | — | yes |
| keep-everything | 3 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x2 | — | yes |

| case | expected kind | kind matches | semantic review |
|---|---|---|---|
| main | PROPOSAL | 2/3 | Runs 1–2 disable cart 1.5's `basket_v2` and preserve checkout 2.1; run 3 over-clarifies the co-shipped checkout behaviors. |
| ambiguous | CLARIFICATION | 0/3 | All three guess cart 1.4; none asks which change or release the user means. |
| inseparable | CLARIFICATION | 3/3 | Historical label retained with the expectation caveat below; this is not three independently established semantic successes. |
| named-old-build | PROPOSAL | 3/3 | All three bind to cart 1.4 through release evidence, cite checkout's receipt correction, and leave checkout 2.1 unchanged. |
| keep-everything | CLARIFICATION | 3/3 | All three explain checkout's co-shipped behaviors and ask about the conflict; none invents a hybrid build or undeclared flag. |

### Ambiguity and semantic review

For **“Roll back the cart change from last week.”**, the outcome is **0/3 clarified,
3/3 guessed**. There is **no terminal question or unresolved-reference list in any of
these three results**; each is a proposal for cart 1.4. Run 1 assumes the basket_v2
change in cart 1.5 (built 2026-10-06); run 2 assumes the basket_v2 rollout; run 3 again
assumes the dated cart 1.5 rollout. None establishes that this is the user's intended
referent or asks for the missing time/change anchor.

All three cite the same two retrieved candidates, with valid exact quotes:

- `excerpt:9d521fc02aa4498e:CHANGELOG.md:5-5`:
  “- Basket rollout — cart lines are grouped into named baskets and saved as cart/v2; behind flag basket_v2 (default on).”
- `excerpt:9703e568235e03f3:CHANGELOG.md:5-5`:
  “- Saved carts are persisted to cart-cache as cart/v1.”

Those citations support the releases' behaviors, not the assumed binding of “last week.”
There are no validation errors in any ambiguous result; structural citation validity
therefore does not demonstrate successful disambiguation.

The `main` run 3 question focuses on checkout 2.1 containing both the receipt correction
and basket support, rather than choosing the documented cart-side rollback/flag option.
The explicit `named-old-build` case does not over-clarify: all three proposals retain
checkout 2.1. Their compatibility with retained cart/v2 data belongs to the later
checker; this grounding evaluation makes no compatibility or approval claim.

**Preserved expectation caveat (`inseparable`).** The user explicitly chose to keep the
historical request and expectation before reviewing this case's new results. The request
asks to remove order-summary headings while keeping saved-cart grouping; it does not ask
to preserve the receipt correction. Keeping cart 1.5 and proposing the existing checkout
2.0 artifact is a plausible grounding interpretation, with retained-data readability
left to the deterministic checker. The historical rationale's receipt-preservation
assumption is disputed. All three observed clarifications match the retained kind, but
several questions focus on checkout's cart/v2 support or ask whether a flag exists even
though checkout declares no flags. The 11/15 aggregate preserves comparability of labels;
it is not an unquestionable semantic score.

**Conclusion:** the ambiguity behavior **remained incorrect** in this complete live
sample. The generic rule did not prevent guessing in any of its three observations.
The earlier 6/10 result predates other grounding changes, including citation hardening;
these different small samples do not isolate the prompt rule's causal effect or establish
reliability. Any generic disambiguation remediation and re-evaluation should be a
separate change; no runtime behavior was tuned to this batch.

Follow-up: [#17 — Clarify ambiguous rollback references before proposing a release](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/17)
tracks the unresolved ambiguity behavior and its re-evaluation.

### Local audit artifacts

All filenames below are under `artifacts/grounding/`, in run order. The three
ambiguous-case transcripts are included in this PR for review:
[run 1](../artifacts/grounding/70a0b3fbd63b17a3.json),
[run 2](../artifacts/grounding/4f5d394955ed1fda.json), and
[run 3](../artifacts/grounding/459f0e5b394a2f39.json).
The remaining transcripts, logs, metadata (`artifacts/grounding-eval/issue-2-metadata.json`),
cleanup verification, and raw reports remain git-ignored local evidence. Results for
the other cases are author-reported; the measured table, hashes, interpretation, and
filename mappings are retained here in tracked docs.

| case | run 1 transcript | run 2 transcript | run 3 transcript |
|---|---|---|---|
| main | `fd6825e59b290912.json` | `ba4150221375c2ec.json` | `046d5b1263dda1b1.json` |
| ambiguous | `70a0b3fbd63b17a3.json` | `4f5d394955ed1fda.json` | `459f0e5b394a2f39.json` |
| inseparable | `2649304e421f2ee0.json` | `b3b9acb5c43c40ff.json` | `f9c93a7078306a25.json` |
| named-old-build | `72639133824339f5.json` | `66b5ba933654f77b.json` | `58e07d2189662cc0.json` |
| keep-everything | `f894c89d4a4e9caf.json` | `ccc0303bcf8c3885.json` | `a0bbbc6f964d360b.json` |

### Separate interrupted invocation and validation

Before the complete batch, the same `--runs 3` command wrote to
`artifacts/grounding-eval/issue-2-live.log` and exited **1** after one completed
observation. Its only saved result, at **2026-10-16 18:00:49Z**, was:

| case | run | model | kind | proposed fleet | citations | validation errors | matches expected |
|---|---|---|---|---|---|---|---|
| main | 1 | groq:openai/gpt-oss-120b | CLARIFICATION | — | changelog x3 | — | no |

Transcript: `artifacts/grounding/d018501f0559a7c5.json`. It asked whether to retain
checkout's receipt correction despite its co-shipped basket support. During `main` run 2,
the concurrently executed non-live suite's `_drop_test_graphs` helper deleted its graph
`rw_test_grounding_eval_d88191c3` because the runner shares the `rw_test_grounding_`
prefix. The runner raised `redis.exceptions.ResponseError: Invalid graph operation on
empty key`; it did not write a final report. `main` run 2 has no completed result;
`main` run 3 and runs 1–3 of the other four cases were not reached (**14 missing
observations**). This is an interrupted invocation, not an `ABORTED` model result or a
provider `ERROR`, and its observation is excluded from the complete batch's denominator.
That graph was also confirmed absent at 18:20:30Z. Database-backed tests and smoke were
finished before starting the isolated full batch; do not run them concurrently with it.

Validation on the same application commit:

- `.venv/bin/python -m pytest tests/test_grounding.py -q -m "not live"` → **43 passed,
  2 deselected** (preflight).
- `.venv/bin/python -m pytest -q -m "not live"` → **295 passed, 3 deselected**.
- `.venv/bin/python scripts/smoke.py` → exit **0**, **8/8 PASS**, including graph
  `rw_smoke_9edc5e10` cleanup. The standalone smoke emitted the known Starlette/httpx
  deprecation warning; pytest's narrow warning filter keeps its suite clean.
- `git diff --check` → clean.

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
  longer grounding turns. That invocation remains **incomplete** and is preserved as history,
  separately from the complete issue #2 evaluation above.
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
- **Live LLM control (#3) had no live run at that time** (since then, only author-reported results exist; see [ISSUE_3_FIX_REPORT.md](ISSUE_3_FIX_REPORT.md)) — same quota limits; the control prompt is larger than
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

[#2](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/2)'s measurement/reporting work is
complete: the full 15-row live result and semantic review are recorded above. The ambiguity
rule still guessed in 3/3 runs and needs a separate behavioral follow-up.

Remaining open work is tracked in [GitHub issues](https://github.com/Ep1cGaimer/FalkorDB_agent/issues):

- **[#3](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/3) — PR #13 under review.**
  The separate three-pair comparison is recorded in [ISSUE_3_COMPARISON.md](ISSUE_3_COMPARISON.md)
  as author-reported observations, not independently verifiable acceptance evidence.
- **[#4](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/4) — PR #13 under review.**
  The smaller-budget choice and simulated browser quota-message check are documented in
  [ISSUE_4_QUOTA.md](ISSUE_4_QUOTA.md). Finite quota and future rate-limit errors remain possible.

The UI revamp ([#11](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/11)) and startup
instructions ([#12](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/12)) remain separate work.
No product deployment or publishing has been performed.

Setup and demo commands for a reviewer: [QUICKSTART.md](QUICKSTART.md).
