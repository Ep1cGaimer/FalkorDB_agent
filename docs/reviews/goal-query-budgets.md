# Shared retrieval budgets and import renewal repair

This is a third development repair batch on `fix/goal-acceptance`, based on
`origin/goal` at `d7cf693e26073c825f0b6a2bd741ce5d05752f72`. All acceptance gates
remain **IN_PROGRESS**. Earlier attempts remain in the
[first repair report](goal-branch-remediation.md) and
[source freshness report](goal-source-freshness.md).

Investigations now share a request-local deadline and consumed-evidence counters
across resolution, nested graph queries and Git reads. Graph output is limited
before materialization; a filled clamped result cannot establish completeness.
Exhaustion clears final findings, citations, answers and compatibility dispositions
and exposes `RETRIEVAL_BUDGET_EXHAUSTED`. Standalone query pages report incomplete
coverage. Independent requests cannot inherit an exhausted request's counters.

Git subprocesses receive the remaining deadline and are killed/waited on timeout.
Database statements receive at most 1000 ms and the remaining deadline, using the
[FalkorDB read-query timeout parameter](https://falkordb-py.readthedocs.io/en/stable/falkordb.html#falkordb.graph.Graph.ro_query).
New read clients bound socket waits to at most two seconds. Python processing
checks cooperatively; injected clients own their transport policy. These changes
do not establish hard process-memory/OS wall-time limits or actual model-token
accounting. Defaults and lower configuration limits are documented in
[repository configuration](../../repos/README.md).

The first new transport attempt failed during an actual long import: same-owner
lease renewal invalidated WATCH and incorrectly marked ownership lost. A new
regression reproduced this with three deterministic real Redis renewal races.
The importer now retries only WATCH-aborted transactions under a fresh owner
check, up to eight times. A successor's token still prevents mutation. A separate
race test replaces ownership between WATCH and EXEC and verifies that symbols
are preserved, followed by successful documented retry recovery.

Observed development checks:

| Check | Result |
|---|---|
| Initial five budget tests | 5 failed before implementation |
| Deadline, paging, freshness and access subset | 62 passed, 1 real-repository smoke skipped |
| Renewal race before repair | 1 failed, 1 passed |
| Budget, renewal and persistence-recovery subset after repair | 21 passed |
| Actual CLI/TCP API/stdio MCP probe after repair | 27/27 exact semantic matches, plus 2 malformed-input cases |

The probe includes row/source budget exhaustion on both inspected development
repositories, parallel selections, MCP restart, incomplete publication, stale
blobs/relationships and actual database stop/restart. Its API at
`http://127.0.0.1:52449` was confirmed stopped after the run; no owned probe
containers remained. The failed import attempt and all successful traces are in
[raw probe attempts](goal-budget-evidence/raw-probe-attempts.tar.gz).

A complete-suite attempt was interrupted deliberately after the renewal defect
was reproduced: 176 passed, 5 skipped, 3 deselected at 136.37 seconds. It is not a
complete validation run. A mistaken file selector and an interleaved selector
invocation with fixture setup errors are also retained in the attempt ledger.
The standalone scale regression subsequently passed 14 tests with 1 skipped.

The complete offline suite then passed **1,059 tests**, with **5 skipped** and
**3 live-provider tests deselected**, in **372.24 seconds**. The 166 frozen file
hashes had zero mismatches afterward. Five skips still require missing evaluation,
scale or benefit outputs. Artifact-parameterized tests increase as attempts are
recorded; this count is not a held-out-question or accuracy metric. JavaScript
passed 16/16 and deterministic fixture smoke produced all 8 PASS lines and cleanup.
The separate live fixture attempt produced 2 passed and 1 failed: a plaintext
control flag-validation mismatch, subsequently repaired and verified in a
[separate source version and fresh run](goal-control-flags.md). The original
failure remains in this batch's evidence.

The [run summary](goal-budget-evidence/run-summary.json),
[JUnit report](goal-budget-evidence/final-tests.xml), and
[166-file manifest](goal-budget-evidence/implementation-manifest.json) cover
product/development Python/JavaScript implementation and tests, plus recorded config
inputs. Independent authoring files have their own package manifest. The new independent 120-question package is sealed from the implementer;
its draft protocol is unsigned. No held-out product generation, blind scoring,
controlled three-slice benchmark or advantage validation has occurred in this
batch. Provider model listings are readiness metadata, not answer-quality results.
