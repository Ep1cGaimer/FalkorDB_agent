# Fresh audit of the remote `goal` branch

**Result: 0 completely passing gates, 3 partially examined gates, 9 failed acceptance gates. No S1–S6 requirement is validated against the full local specification.**

The branch contains substantial working Python repository integration. It also has reproducible correctness and ingestion-safety failures. It is not ready to claim that v1 scope, history correctness, safe ingestion or a FalkorDB advantage has been validated.

This is a review of the implementation, not an implementation repair. Application source was not changed.

## What was reviewed

- Remote `origin/goal`, freshly fetched and checked out at `d7cf693e26073c825f0b6a2bd741ce5d05752f72` in `/private/tmp/falkordb-goal-audit`.
- Comparison base `f189d7c1a38e3648cd28b977050822c95d8c7597` (`origin/main` at review start). The diff has 160 changed files and 15,881 added lines.
- **Your local** `remquirements-v1.md`: 134 lines, SHA-256 `a177653c4096f885cad1e129f77331cffe59fe13f608bac924232e632c1dd627`. Its full T0–T11 section is authoritative. The remote branch’s shorter 24-line copy was not used as the acceptance specification.
- All verdicts use fresh executions and current source inspection. Earlier reported scores, saved test results and statements in `docs/REPO_STATUS.md` were not accepted as test evidence.
- Python 3.12.13, MCP 2.3.0, FalkorDB client 1.8.0 and server module 60002 / Redis 8.10.2. Exact installed versions and the observed 10,000-row database cap are in [database-environment.json](goal-branch-evidence/database-environment.json).

“Complete passing” means every mandatory clause and numerical threshold is freshly proven. “Partial” means a useful subset was freshly demonstrated while the full required experiment remains incomplete. “Absolute failure / FAIL” means a mandatory contract has a fresh counterexample, or the required evaluation/release method is absent or contradicts the specification. A failed gate does not mean that every feature in it fails. Missing evidence never counts as a pass.

## T0–T11 scorecard

| Gate | Verdict | Plain-language reason |
|---|---|---|
| T0 — Evaluation contract | **Absolute failure** | No complete signed pre-result contract; oracle annotations influence retrieval; budgets/environment are incomplete. |
| T1 — Integration and fixture regression | **Absolute failure** | Fresh imports work, but the shipped unseen freeze, MCP schema regression and a live control fail. Required regressions are not all passing. |
| T2 — Retrieval and answer quality | **Absolute failure** | Too few real questions, two repeats instead of three, no required blind scoring, and fresh probes show invalid grounding/denominator logic. |
| T3 — Git/history identity | **Absolute failure** | Moved/deleted tags and relative imports produce wrong identities; a partially undone fix is still reported present. |
| T4 — Index integrity and recovery | **Absolute failure** | An interrupted re-extraction can serve missing symbols as a complete snapshot; config updates differ from a clean index. |
| T5 — Bounded retrieval | **Absolute failure** | Cursors cross revisions, while two readers can silently miss evidence at their caps. Several ordinary pagination cases do pass. |
| T6 — Scale and cost | **Partial** | Three fresh large-graph measurements completed, but the required slices, cold controls, 100-query workloads, concurrency and quality/cost evidence are incomplete. |
| T7 — CLI/API/MCP consistency | **Partial** | Eight real cases match over actual MCP transport, API and CLI; the full failure/concurrency/restart/status matrix is not proven. |
| T8 — Safe ingestion/runtime boundaries | **Absolute failure** | Repository-controlled Git configuration executed a harmless tracked repository program during ingestion. Fixture/runtime boundary regressions otherwise pass in the tested subset. |
| T9 — Actual FalkorDB contribution | **Partial** | Real multi-hop traces and edge-removal effects were demonstrated on both repositories. Held-out generated answers and the complete ablation/failure matrix remain missing. |
| T10 — Fair comparison/advantage | **Absolute failure** | The implemented thresholds differ from the required A/B gate, permit quality loss, use two repeats and have no required confidence intervals or repo veto. |
| T11 — Reproduction/demo readiness | **Absolute failure** | This audit bundle is available, but the complete independent scientific reproduction, 12-question live rerun, three demos and submission claim card are absent. |

## Fresh execution results

| Run | Fresh result | Evidence |
|---|---|---|
| Complete non-model/non-realrepo branch suite, MCP installed | **881 passed, 1 failed, 9 skipped**, 6 deselected | [JUnit](goal-branch-evidence/branch-suite.xml), [log](goal-branch-evidence/branch-suite.txt) |
| Repository portion of that suite | **188 passed, 0 failed, 9 skipped** | Same JUnit. This green subset does not cover the full local acceptance contract. |
| Shipped independent fixture oracle | All **10 cases passed**, including the original eight and two identity cases | Same JUnit, `tests.test_acceptance_oracle` |
| Fresh declared onboarding and citation checks | **3 passed, 1 failed** | [JUnit](goal-branch-evidence/fresh-real-onboarding.xml) |
| Additional config-only audit onboarding | Requests, ItsDangerous, MarkupSafe imported successfully; core before/after hashes identical | [Record](goal-branch-evidence/surfaces-and-graph.json) |
| Real CLI/API/MCP configured cases | **8/8 exact semantic matches**; missing-repo error formats differ | [Requests/responses and MCP tool schemas](goal-branch-evidence/surfaces-and-graph.json) |
| Independent targeted adversarial tests | **12 failed assertions**, exposing the cases below | [JUnit](goal-branch-evidence/adversarial.xml), [log](goal-branch-evidence/adversarial.txt) |
| 100 seeded mini histories | **100 passed** | [JUnit](goal-branch-evidence/generated-histories.xml), [seeds/oracle log](goal-branch-evidence/generated-histories.txt) |
| Row/cycle/fan-out/depth enumeration | **11 scoped checks passed**; one additional depth-warning assertion was too strong for an explicitly requested hop scope and is excluded from confirmed defect counts | [JUnit](goal-branch-evidence/pagination-boundaries.xml) |
| Execution canaries, tracked-program confirmation | **1 passed, 1 failed**; signature checker marker was created | [JUnit](goal-branch-evidence/ingestion-canaries-v2.xml), [log](goal-branch-evidence/ingestion-canaries-v2.txt) |
| Live provider fixture tests | **2 passed, 1 failed** | [JUnit](goal-branch-evidence/fresh-live-fixture.xml), [log](goal-branch-evidence/fresh-live-fixture.txt) |
| Deterministic smoke / JavaScript | Smoke passed; JavaScript has zero failures | [Smoke](goal-branch-evidence/smoke.txt), [JavaScript](goal-branch-evidence/js-tests.txt) |
| Remaining real-repository smoke and fresh artifact checks | **13 passed, 1 skipped** (no complete benefit-run category exists); these are smoke/record-shape checks, not acceptance validation | [JUnit](goal-branch-evidence/final-fresh-artifact-checks.xml) |
| MCP schema check on comparison base | **1 passed**; the corresponding goal-branch check failed | [Base JUnit](goal-branch-evidence/base-mcp-schema-v2.xml) |

Two raw live grounding transcripts were retained. The plaintext control’s temporary raw transcript was removed by pytest temporary-directory retention before copying; its printed answer, probe summary, validation failure and JUnit result remain. This limits replay of that one attempt and is not presented as complete raw evidence.

The nine initial suite skips are missing real clones/evaluation artifacts at collection time. Fresh clones and separate onboarding checks followed. Missing full held-out/comparison evidence was not fabricated to remove those skips. The two real citation checks passed after cloning.

The first database-free attempt ran while Docker was paused and produced environment-related errors. It is retained as an attempt, excluded from product correctness totals, and superseded by the fresh database-backed run. Two graph-probe setup attempts used shorthand names incorrectly with the low-level query API; those failures are retained. The corrected exact-identity graph probes passed. One baseline-test attempt used the branch’s renamed test identifier and collected no test; the corrected base check passed. These audit harness/setup failures are not product defects.

## Confirmed findings, in everyday wording

### Ingestion can execute a repository program

Set repository-local `log.showSignature=true` and `gpg.program` to a harmless executable tracked in that repository, then ingest a synthetic signed commit. The executable created its marker during ingestion. The test changed only the temporary repository and marker; it did not set global Git configuration or execute an external payload.

The cause is that the “read-only” Git wrapper inherits repository configuration and runs `git log` without neutralizing its executable signature-verification behavior: [src/rw/repo/git.py:42](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/git.py#L42), [src/rw/repo/git.py:66](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/git.py#L66). Read-only Git subcommand names alone do not guarantee non-execution. This directly fails T8 for existing local repositories containing hostile Git configuration. It does not imply that ordinary bare clones execute code by default.

### A fix can be reported present after part of it was undone

The independent example removes an unsafe helper and adds a guard. A later commit restores the unsafe helper but leaves the guard. `fix_status` still returns `PRESENT`, with no uncertainty gap. The checker discards deletion-only hunks and tests additions: [src/rw/repo/query.py:609](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L609). A complete fix needs its required deletions as well as its additions checked. This is a direct T3 correctness failure.

### A failed update can damage a snapshot still labeled complete

Start with a complete index containing `a` and `a.a`. Change the extractor version and interrupt immediately after old symbols are deleted. A new query still resolves the revision as complete, but now returns **zero symbols**, with no gap. Re-extraction edits shared facts in place while the old import remains `COMPLETE`: [src/rw/repo/index.py:335](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/index.py#L335), [src/rw/repo/query.py:207](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L207). Staging a new generation or explicitly rejecting queries during the update is needed to uphold T4.

### Identical bytes can produce dependencies for the wrong package

Both `pkg_a/__init__.py` and `pkg_b/__init__.py` contain `from .util import helper`. Querying package B incorrectly returns `pkg_a.util.helper`. Extraction is reused by content hash even though relative-import meaning depends on path: [src/rw/repo/index.py:167](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/index.py#L167), [src/rw/repo/adapters/python.py:53](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/adapters/python.py#L53). Caching must preserve path/package context.

### Moving or deleting a tag leaves stale revision aliases

After moving `v1` from commit A to B and reindexing, the graph contains both targets, and resolution selects A. Deleting the tag still leaves it resolvable. Tag updates only add targets: [src/rw/repo/index.py:152](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/index.py#L152). Resolution chooses the first returned target: [src/rw/repo/query.py:216](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L216). T3/T4 require accurate current aliases or explicit uncertainty, never silent selection of stale aliases.

### Configuration changes do not fully invalidate old index facts

Index `keep.py` and `drop.py`, then add `drop.py` to exclusions and update. The incremental index still returns `drop` and `drop.drop`; a clean index does not. Existing `files_done` flags bypass file-map rebuilding regardless of changed configuration: [src/rw/repo/index.py:140](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/index.py#L140). Include/exclude and other extraction/manifest changes need identity-aware invalidation.

### Pagination cursors are reusable at another revision

A cursor from one revision was accepted at another, returning that other revision’s next rows without rejection. Cursors contain only an encoded offset: [src/rw/repo/query.py:103](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L103). The required repository/revision/query/generation identity is missing. A page boundary can therefore silently change meaning.

### Parse failures disappear from query coverage

An import correctly records that `broken.py` could not be parsed. A symbol query for its function then returns no results with an empty gap list. Import-time diagnostics alone do not tell an investigator why evidence is missing: [src/rw/repo/query.py:304](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L304). “Not extracted” must remain distinguishable from “does not exist.”

### Some large reads silently omit evidence

A controlled graph-transport test simulates the **actually configured** 10,000-row result cap. With 10,001 release notes, the code reports total=10,000 with no truncation gap. Another controlled probe puts the first containing tag at candidate 2,001; the lookup returns `None`. These are explicit simulated transport/unit cases, not claims that 10,001 real notes were freshly imported.

Affected code: [src/rw/repo/query.py:506](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/query.py#L506) and [src/rw/repo/investigate.py:386](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/repo/investigate.py#L386). The passing ordinary pagination tests do not cover these readers. The depth-warning test is deliberately excluded here: explicitly requesting N hops can legitimately limit scope to N hops.

### The new MCP tool breaks the published schema check

The complete fresh suite fails `test_tools_schemas_output_refs_annotations_and_parity`: the new repository tool has no valid published output schema (`None`). The corresponding base-commit check passed in the same environment. Registration returns untyped `dict`: [src/rw/mcp_server.py:138](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/src/rw/mcp_server.py#L138). Real tool calls can work while the schema contract still regresses.

### The shipped unseen-repository freeze cannot be reproduced here

The clean-checkout ItsDangerous test fails before ingestion because core hashes differ from `core_manifest.json`. Thirteen mismatches match a uniform LF-to-CRLF conversion; `src/rw/repo/git.py` matches neither its current bytes nor that conversion. The remaining mismatch needs investigation. This is a reproducibility/freeze failure, not evidence that ItsDangerous itself cannot import: the separate fresh config-only import succeeded.

### The quality evaluator can award credit it has not earned

A fresh direct probe shows `grounded()` returning true even when a positive answer includes a fabricated citation. Another shows empty answerable retrieval receiving `precision=None`, which the aggregation skips. The history runner also reads per-question retrieval instructions from answer keys. See [evals/repo_eval_common.py:157](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/evals/repo_eval_common.py#L157), [evals/repo_eval_common.py:193](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/evals/repo_eval_common.py#L193), [evals/repo_history_eval.py:37](https://github.com/Ep1cGaimer/FalkorDB_agent/blob/d7cf693e26073c825f0b6a2bd741ce5d05752f72/evals/repo_history_eval.py#L37). Such a score cannot establish the stronger T2 correctness/grounding contract.

The live plaintext-control failure was `explicit_flags: cart 1.5 {'basket_v2': False}`. It is one freshly observed model-adherence failure, not a claim that the model always fails. Both live grounding-request cases passed in the same run.

## Fresh scale measurements and their limits

The corpus includes **159 selected tags, 6,470 reachable commits, 79,860,933 Python-source bytes across the selected tag snapshots**, and about 858,191 history-text bytes. The runner’s bytes/4 estimate is **20,179,781 tokens** against its declared 128,000-token context budget. That estimate is not an actual model-tokenizer/context-reserve validation.

| Trial | Initial import s | Update s | Timed calls | Query p95 ms | Query max ms | Process peak MiB | Recorded workload failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 66.920 | 6.953 | 66 | 64.64 | 10207.16 | 155.5 | 1 |
| 2 | 75.858 | 7.937 | 66 | 79.47 | 12402.58 | 154.8 | 1 |
| 3 | 67.638 | 6.396 | 66 | 68.31 | 9920.37 | 156.8 | 1 |

Each final index occupied **318,767,104 bytes (304 MiB)** by the recorded graph memory method. Fresh updates reused 4,998 blobs and extracted 89 new blobs. The declared interruption/retry experiment recovered in each trial, and the runner’s selected invalidation checks passed. These successes do not undo the independent interrupted re-extraction or configuration-invalidation failures.

Every trial reports `all_budgets_met=false`; the recorded failure is “resolve Session at v0.2.0: Session class not found.” This reflects the benchmark’s historical-symbol assumption and must remain a failed workload attempt. It is not evidence of a database crash. The runner does not supply the complete ≥100-call/slice, failed-request latency, cold/warm/concurrency, full container-memory, actual-cost and quality-at-scale measurements required by T6. Trials used fresh graphs and processes while OS/database caches remained warm and other audit/local work overlapped. Performance claims are limited to these observations.

## Actual graph contribution

Fresh graph probes used **15 recorded parameterized query calls per repository**. The selected queries returned two-hop paths, and all checked citations resolved to the requested commit and path/span. Removing one selected edge reduced the fresh result from **3 to 0** edges on Requests and **7 to 4** on ItsDangerous. Marking the import failed yielded `INCOMPLETE_IMPORT` rather than a complete result.

[graph-contribution.json](goal-branch-evidence/graph-contribution.json) contains the queries, parameters, returned rows, import IDs, timings, extracted/inferred provenance, citations and ablations. This establishes real graph use for the selected cases. The history entries are raw path-qualified-symbol observations, not an independently scored rename-history result. None of this establishes an accuracy, token, cost or latency advantage over plaintext.

## Scope/evidence status and claim rules

| Item | Review status | Why it cannot be VALIDATED |
|---|---|---|
| S1 / E1 — Configurable integration | IN_PROGRESS | Real onboarding works; mandatory T0/T1/T8/T11 evidence/gates do not all pass. |
| S2 / E2 — Useful evidence | IN_PROGRESS | Real citations/paths exist; identity, fix and scoring counterexamples plus missing T2/T11 prevent validation. |
| S3 / E2 — Revision correctness | IN_PROGRESS | Tags, package identity and partial-fix conclusions fail fresh probes. |
| S4 / E3 — Scale/updates | IN_PROGRESS | Measured graph size/reuse/recovery work; generation integrity, cursor binding and full scale gates fail or remain incomplete. |
| S5 / E1 — Access | IN_PROGRESS | Actual CLI/API/MCP parity works for a subset; schema/quality/full-contract evidence is incomplete. |
| S6 / E5 — Verification boundary | IN_PROGRESS | Fixture verification checks pass; ingestion non-execution has a fresh counterexample. |
| E4 — FalkorDB advantage | IN_PROGRESS / unvalidated | Required paired comparison method and confidence gates are not implemented or measured compliantly. |
| E5 — Reproducibility | IN_PROGRESS | This audit is retained; the required independent full evidence/reproduction/demo contract is not satisfied. |

These are review recommendations, not edits to the branch’s existing status document. `docs/REPO_STATUS.md` prematurely labels S1/S3/S5/S6 validated relative to your fuller local gates. A finite set of passing tests does not validate the missing conjunction. A failed test alone is not a BLOCKED workflow status. [evidence-ledger.json](goal-branch-evidence/evidence-ledger.json) preserves S/E/T mappings, hashes, artifact references, limitations and review status; no validation timestamp is invented.

## Every mandatory testing clause

The following table covers **all 47 T0–T11 bullets**, including each pass/evidence bullet. “Partial” rows are not accepted as completed gates.

| Clause | Outcome | Required behavior | Fresh finding / limitation |
|---|---|---|---|
| T0.1 | FAIL | Freeze plan and separate answers from investigation | Some budgets/prompts exist, but the history runner reads oracle-specific retrieval plans from scoring keys, and the direct baseline chooses files from expected citations. This is not the required clean separation. |
| T0.2 | PARTIAL | Numerical budgets and environment | Import/update/memory/disk/p95 and model token/call budgets exist. A complete frozen timeout, demo, spend, tokenizer, cache, hardware and concurrency contract does not. |
| T0.3 | PARTIAL | Two real repos, one unseen, corpus larger than context | Fresh config-only imports worked for Requests, ItsDangerous and audit-selected MarkupSafe. The scale runner estimates 20,179,781 tokens by bytes/4; usable model input/output reserves are not established. Historical unseen status cannot be reconstructed. |
| T0.4 | FAIL | Hashed pre-result contract with independent sign-off | No complete independently signed plan exists for the full local gates. This audit cannot retroactively preregister earlier development. |
| T1.1 | PARTIAL | Clean real onboarding, effort and frozen core hashes | Requests onboarding passed; the shipped ItsDangerous freeze check failed. Independent fresh imports of all three repos succeeded with identical core before/after hashes. Setup execution time is recorded, but human configuration effort and the original unseen freeze remain unproved. |
| T1.2 | PARTIAL | Arbitrary paths, collisions, malformed/unsupported source | Fresh synthetic paths contain spaces/Unicode; isolation and hostile-name checks ran. Malformed source produces an import error but no parse/extraction gap in symbol-query coverage. Identical-content package imports point to the wrong package. |
| T1.3 | FAIL | Exact fixture oracle, SQL control, regressions and live integration | All ten shipped oracle cases (eight baseline plus two identity cases), SQL-control tests and smoke passed freshly. The MCP schema regression failed. Live request tests passed 2/2; the live plaintext control failed its explicit flag check. |
| T1.4 | PARTIAL | Both real imports, no leakage, all required regressions | Configuration-only integration is demonstrated for this checkout. Required regressions are not all passing; the complete frozen real-repository access/isolation matrix is not demonstrated. |
| T2.1 | FAIL | 120 real questions, six strata, 40 complex cases | The checked-in initial real suite has 22 questions; all three evolving rounds together contain at most 62 real questions. This is below 120, and not one frozen six-stratum confirmatory suite. No compliant power plan is present. |
| T2.2 | PARTIAL | 30 negative cases with independent detailed oracles | Some negative, ambiguity and synthetic backport cases exist. The required 30-case real-suite negative oracle set and complete alternative-proof rubric are absent. |
| T2.3 | FAIL | Evidence-first scoring and every material claim grounded | Fresh scoring probe: a positive answer with a fabricated citation can still pass grounded(). Keyword checks plus any evidence overlap do not establish every required supported conclusion. |
| T2.4 | FAIL | Keep errors/empty retrieval in denominators | Fresh scoring probe: empty answerable retrieval yields precision=None instead of zero. Aggregators drop None, and the history runner can omit failed cases. |
| T2.5 | FAIL | Three repeats, blind scoring and 25% double scoring | The declared runners use two repeats. No blind independent double-scoring/adjudication record for the required suite exists. |
| T2.6 | FAIL | 90% answers, 85% groups, 95% precision, 90% recall, zero critical errors | No fresh compliant suite establishes these thresholds. Concrete fresh wrong identity and false fix-presence results also contradict the zero-critical-error boundary. No historical scores were used. |
| T3.1 | PARTIAL | Independent adversarial DAG and Git plumbing oracle | Fresh branch tests and the 100 seeded audit histories cover important operations. The complete required merge-conflict/copy/partial-revert/backport/DAG matrix with independent expected trees is not established. |
| T3.2 | FAIL | Before/after, moved tags, detached/shallow/missing history, identity | Fresh moved-tag test left two targets and resolved the old commit; deleted tags still resolved. Identical Python bytes in two packages resolved both relative imports to the first package. Remaining shallow/detached cases are incomplete. |
| T3.3 | PARTIAL | 100 seeded histories and invariants | The audit freshly generated and passed 100 seeds checking trees/hashes, indexing order, unrelated branches, reverts, deletion and recreation. These mini histories do not include every required adversarial operation. Source and seeds are retained. |
| T3.4 | FAIL | 100% oracle agreement and no false fix presence | Fresh minimal mixed-fix case restored code that the fix deleted while retaining its additions; fix_status still returned PRESENT with no gap. The passing seeded subset cannot override this counterexample or replace T2. |
| T4.1 | FAIL | Full vs incremental normalized equality and invalidation | Fresh exclusion/configuration update retained drop.py symbols; a clean index omitted them. Existing reuse/update tests passed, but full normalized equality across all required updates did not. |
| T4.2 | FAIL | Fault every boundary, restart/retry and preserve prior snapshot | The shipped interruption/recovery path worked in three new scale trials. An independent fault immediately after re-extraction deletes old symbols left the old revision queryable as complete with an empty symbol result. Full boundary/restart/random fault matrix is absent. |
| T4.3 | FAIL | Concurrent operations isolated or explicitly rejected | There is no generation lock/pin or conflict rejection. The fresh interrupted re-extraction probe demonstrates in-place changes visible under an old COMPLETE import. |
| T4.4 | FAIL | All faults recover, no duplicates/stale facts, full comparisons | A documented rebuild can recover some interruptions, but the invariant that partial state is never served complete is broken. Counts alone in the runner do not prove equality of all entities, relationships, coverage and answers. |
| T5.1 | PARTIAL | Rows/depth/cycles/fan-out/cursors/final-page enumeration | Fresh 0/1/9/10/11/35-result tests at cap=10 and cycle/fan-out BFS at hops 1–5 passed (11 cases). Simulated server-cap and 2,001st-tag probes failed. Full expiry/high-fan-out/token/time matrix remains incomplete. |
| T5.2 | FAIL | Repository/revision/generation-bound stable cursors and visible bounds | A cursor issued at one revision was accepted at another. The implementation encodes only an offset. No pinned generation or repository/query identity is encoded. |
| T5.3 | FAIL | Exact enumeration and no false completeness/absence | Release-note code treated a simulated 10,000-row cap as the complete total of 10,001 records; first-containing-tag lookup silently ignored candidate 2,001. Both are controlled unit probes, not massive real imports. |
| T6.1 | PARTIAL | Large real corpus plus two slices and workload structure | Three new full-corpus trials covered 159 Requests tags and 6,470 reachable commits. Two smaller measured slices, dependency-depth/fan-out distributions, and an actual tokenizer calculation are missing. |
| T6.2 | PARTIAL | Three cold imports/updates per slice, 100 queries and concurrency | Three fresh graph imports/updates ran. OS/database caches were not reset, other local work overlapped, each workload timed 66 calls, and no declared concurrency or smaller-slice workload ran. These are fresh graph trials, not fully controlled cold benchmarks. |
| T6.3 | PARTIAL | Frozen budgets, 99% timely valid success plus T2/T5 at scale | Import/update/memory/disk/p95 budgets passed. All three records report all_budgets_met=false because Session cannot be resolved at v0.2.0. That workload assumption is not proof of an engine failure; its failure remains in the record. T2/T5 quality-at-scale gates remain unmet. |
| T7.1 | PARTIAL | Same pinned cases across CLI/API/real MCP | Eight configured real-repository cases matched exactly across direct workflow, CLI, API and real MCP stdio. Missing-repository error formats differ; normalization needs a frozen contract. Full incomplete/truncated/upstream-error matrix is not established. |
| T7.2 | PARTIAL | Malformed inputs, cancellation, restart, parallel selection, no leaks | Empty/oversized inputs were rejected, and two repositories were selected sequentially in one real MCP session. Fresh branch transport tests ran, but the full repository-specific restart/cancellation/parallel/follow-up matrix is missing. |
| T7.3 | PARTIAL | 100% deterministic identity/status/coverage and live answers | Real MCP transcripts now exist for this audit subset. The full required semantic matrix and generated real-repository answer grounding are not proven. The new tool also regresses the published output-schema check. |
| T8.1 | FAIL | No execution/effects; hostile code/hooks/names/symlinks/instructions | A fresh canary tracked inside the ingested repository executed through repository-local log.showSignature/gpg.program. Source imports, hooks, script names, symlink target and embedded-instruction canaries otherwise stayed inert in the tested subset. |
| T8.2 | PARTIAL | Retrieval is evidence only; runtime execution explicit and isolated | Fresh branch tests preserved no-adapter gaps and retrieval-only no-pass behavior. No non-fixture execution isolation claim is established; that capability stays outside the tested boundary. |
| T8.3 | PARTIAL | Every runtime obligation, identity, precedence, approval/idempotence | Fixture obligation/receipt/drift/approval/simulation regressions passed freshly. Generic adapter receipts model only obligation/revision/extractor/adapter; a complete independently enumerated non-fixture identity matrix is not established. |
| T8.4 | FAIL | Zero executions/unauthorized effects/false passes and complete audits | The harmless execution canary directly fails the zero-execution rule for existing local repositories with hostile Git configuration. No sandbox or global settings were changed by the test. |
| T9.1 | PARTIAL | Real DB query-to-answer trace with identities and provenance | Fresh traces contain parameterized Cypher, parameters, rows, timing, commit/import identities, two-hop edges and valid source citations on both real repositories. These are representative deterministic probes, not the required held-out generated-answer set. |
| T9.2 | PARTIAL | Edge/stale-record/retrieval-interruption ablations | Removing a selected dependency edge changed fresh results (Requests 3→0, ItsDangerous 7→4). Invalidating import publication produced INCOMPLETE_IMPORT. Stale individual evidence, interrupted retrieval, hidden-cache behavior and labeled fallback need fuller tests. |
| T9.3 | PARTIAL | All ablations plus necessary multi-hop graph contribution per repo | Actual graph contribution is demonstrated for two probes. This does not establish every selected ablation, independently necessary held-out proof paths, or comparative advantage. |
| T10.1 | PARTIAL | Direct context and practical iterative plaintext search; SQL control | Both baseline implementations exist and SQL control passed freshly. Direct-context files are selected from oracle citations, rather than the same full applicable corpus. No compliant fresh paired comparison was run. |
| T10.2 | FAIL | Same settings/evidence/budgets, random paired three repeats | Some prompts/budgets/order randomization are shared, but only two repeats are declared. Oracle file selection and retrieval plans violate the required evidence boundary. Retry/accounting details are incomplete. |
| T10.3 | FAIL | Exactly one preselected advantage gate A or B | The implementation allows either +15-point accuracy with ±20% total tokens, or 30% fewer total tokens with up to 5-point quality loss. Neither is the local spec’s exactly-one A/B gate with input-token, cost and no-quality-regression constraints. |
| T10.4 | FAIL | 10,000 stratified paired bootstrap resamples and 95% intervals | Required confidence-interval calculation and its acceptance tests are absent. No new advantage score or monetary saving is claimed. |
| T10.5 | FAIL | Each comparator, no repo regressions, T2 safety and break-even | The verdict pools repositories and permits quality regression; it lacks the required per-repository veto, compliant intervals, absolute T2 gate and measured break-even. Advantage remains unvalidated. |
| T11.1 | PARTIAL | Versioned complete evidence bundle and claim links | This review delivers fresh logs/scripts/manifests/traces and an audit ledger. The product’s full frozen-plan/held-out/model/scorer/CI/attempt bundle is not present, and the shipped reproducibility tests skip missing categories. |
| T11.2 | FAIL | Independent clean reproduction, score recomputation and 12 live held-outs | The branch was freshly run from a clean source checkout with a reused pinned environment. That is not independent full score/CI reproduction. The required both-repo/six-stratum 12-question live rerun was not available. |
| T11.3 | FAIL | Three complete reset live demos with all required scenes | No three reset demo rehearsals, fresh real questions, scorecards and duration records were supplied or performed. Automated smoke/transport checks are different evidence. |
| T11.4 | FAIL | Reproduction/demos within budgets, claim card and official deliverables | No completed compliant demos, official event/submission context, validated comparison claim card or full claim-to-evidence release record exists. The engineering review cannot establish submission readiness. |

## Standards

The separate standards review identified two documented contract violations: stale/contradictory tag aliases are silently chosen, and some capped reads can appear complete. These conflict with `docs/ARCHITECTURE.md`’s ambiguity/completeness rules and `docs/plans/repo-integration-v1.md`’s requirement to page or split large reads. Fresh tests confirmed moved-tag behavior; controlled cap probes confirmed the reader problems.

One judgment call is Feature Envy / Duplicated Code: investigation handlers duplicate raw tag queries and call private query storage methods. A public paginated query interface would centralize evidence bounds. This is a design smell, not an independently mandatory coding violation. No repository AGENTS/CONTRIBUTING/CODING_STANDARDS or issue-tracker workflow file was found. The user supplied the specification directly, so no setup action was required to perform this review.

Standards summary: **two documented contract findings and one design concern**; stale revision aliases are the most serious contract issue within this axis.

## Spec

The separate specification review found that the local T0–T11 contract is substantially stronger than the branch’s shipped evaluator. The required question count, three repeats, blind scoring, denominator rules, independently frozen contract, full fault matrix, generation/cursor identity, bootstrap intervals and demo/reproduction artifacts are incomplete or contradicted. Existing status labels cannot establish them. Astronomy-shop/UI expansion is ancillary work; it does not close those acceptance gaps.

Fresh behavior confirms failures involving fix presence, tag/package identity, incremental invalidation, partially served generations, missing parse coverage and indirect execution. Actual source-backed retrieval, configuration-only onboarding and real transport do work for the audited subsets. This axis makes no claim of measured retrieval advantage.

Spec summary: **nine failed and three partial acceptance gates, zero complete gates**; indirect ingestion execution and false fix-presence conclusions are the most serious observed safety/correctness issues within this axis.

## Reproduction and omitted acceptance work

The [evidence archive](goal-branch-evidence.tar.gz) contains `audit/` scripts/logs/XML/manifests, fresh model transcripts, scale/onboarding records and query traces. It excludes credentials, model keys, unrelated user data and repository clone object stores. Public clone URLs, exact revisions and commands are in the included manifests/README. Extract it into a clean checkout at the reviewed commit, provide the declared dependencies/local database and rerun the listed commands. The separate evidence directory makes the principal files directly readable.

The audit’s synthetic expectations were authored from generated file states and Git, not graph answers; AI assistance is disclosed. The source review and audit were performed by Codex with separate Standards/Spec review agents. This is not independent human sign-off, blind multi-rater scoring, clean full-environment reproduction, or event submission approval.

The full 120-question × three-repeat × comparison-arm evaluation, 30-negative/six-stratum oracle suite, independent double scoring, full fault/concurrency/security matrix, controlled multi-slice scale run, 10,000-resample comparison, 12-question live reproduction and three rehearsed demos were **not performed**. The branch does not provide the complete frozen methods/cases required to run them compliantly. Their absence is recorded as missing acceptance evidence; smaller smoke checks are not substituted for them. The task completed here is the fresh audit and report, not making the implementation pass those gates.
