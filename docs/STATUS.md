# Status

Updated 2026-10-19, local `feat/demo-overhaul` after `8f0b0d8`, with uncommitted demo evidence guards.
This page is the single current-state summary; older dated
logs, review notes and per-issue reports were removed from the tree and remain in Git history
(last commit containing them: `25b5513`). Measured comparisons: [results/RESULTS.md](results/RESULTS.md).

## What exists

| Part | State |
|---|---|
| Rollback workflow (`src/rw/`): grounding agent → FalkorDB obligations → real reader probes → disposition → one agent alternative → human-approved local simulation | Implemented, the hackathon product |
| Demo fixture `fixtures/astronomy-shop` (4 services × 2 releases, 40 Kafka `orders` records) | Implemented ([design](../fixtures/astronomy-shop/DESIGN.md)) |
| Recording fixture `fixtures/astronomy-incident` (12 services, orders/ledger/carts, 97 retained records) | Implemented; integration, relationship-removal and two fresh replay rehearsals pass ([design](../fixtures/astronomy-incident/DESIGN.md)) |
| Branded UI kit, graph clusters, receipt inspector, lineage, comparisons | Integrated; exact-batch lineage and stale-comparison guards added. Existing explanatory module unchanged |
| Four-minute demo preparation | [Narration](demo/DEMO_SCRIPT.md), [recording runbook](demo/RECORDING_RUNBOOK.md), dedicated launcher and live/replay preparation tool added; video not published |
| Test fixture `fixtures/shop` (cart/checkout, 2 saved carts) | Default for tests, the oracle and the controls |
| Console UI (`:8000`), CLI (`scripts/investigate.py`), MCP bridge (`scripts/serve_mcp.py`) | Implemented |
| Repository-evidence workflow (`src/rw/repo/`, `scripts/hackathon_demo.py`, `:8127`) | Secondary; deterministic (no LLM) source/Git-history retrieval. Spec: [repo/REQUIREMENTS.md](repo/REQUIREMENTS.md); its E1–E5/T0–T11 gates are not claimed |
| `evals/confirmatory/` | Unfinished draft evaluation package for the repository workflow; never run |

## Checked on 2026-10-19 (Windows 11, Python 3.12, FalkorDB 6.0.2)

| Command | Observed |
|---|---|
| `RW_FIXTURE=astronomy-shop scripts/investigate.py --fleet checkout=3.1.0 --fleet accounting=3.1.0 --fleet fraud-detection=3.1.0 --confirm-as …` | `BLOCKED`, 32 FAIL receipts (`UnsupportedCurrencyError`), witness path ending at a record written by 3.2.0 |
| same, `--fleet checkout=3.1.0` | `BOUNDED_PASS` |
| same, `--fleet checkout=3.1.0 --snapshot snap-002-partial` | `NEEDS_EVIDENCE` (`COVERAGE_INCOMPLETE` on `store:orders`, manifest and graph) |
| `evals/ablation_relationships.py` | Matches [RESULTS.md §1](results/RESULTS.md) (full graph 80 checks / 32 failures; without `EXECUTES_ROUTE`, `READS_FROM` or `IN_STORE`: 0 checks, `NEEDS_EVIDENCE`) |
| `PYTHONUTF8=1 pytest -q -m "not live"` | 1265 passed, 7 failed, 5 errors, 12 skipped. Every failure is in repository-workflow tests (symlink creation without Windows Developer Mode, `test_git_source_preflight` patch cases, `evals/confirmatory` direct-context setup); no rollback-workflow test fails. Without `PYTHONUTF8=1`, 23 more confirmatory tests error with `UnicodeEncodeError`. |

The preceding table records the original Astronomy Shop checks. New incident checks:

| Check | Observed |
|---|---|
| `pytest -q tests/test_incident_fixture.py` | **22 passed** in 147.07s. Complete snapshot: rollback BLOCKED, 137 obligations / 48 failures; flag-off alternative BOUNDED_PASS; partial/orphan snapshots NEEDS_EVIDENCE. Real FalkorDB and reader probes. |
| New `tests/test_comparison_guards.py` | **14 passed** in the final comparison/UI follow-up (27 passed combined). Exact applicable receipt selection, same live model requirement, stale payload/context and post-comparison drift refusals. |
| Existing incident endpoint/origins/relationship-removal subset | **5 passed**, 17 deselected. Includes disposable lineage removal and original graph preservation. |
| `pytest -q tests/test_lineage_guards.py` | **7 passed**. Missing lineage edges/declarations, cycles, depth/row caps, exact identities and ambiguous baseline claims; pure helper tests. |
| `node --test tests/js/*.test.mjs` | **28 passed**, including exact-batch joins, multiple roots, incomplete lineage and unresolved services. |
| Final affected rollback/API/graph/probe/approval/UI acceptance suite | **661 passed, 2 deselected** in 956.24s; JUnit and stdout in `artifacts/demo-readiness/pytest-final-rollback.*`. Last cache/presentation edits also checked separately: **13 UI tests passed**, final **28 JavaScript tests passed**. |
| MCP clients, integration and stdio after HTTP/report changes | **121 passed** in 25.81s. |
| Two fresh incident replay rehearsals | Both **BLOCKED → CLARIFICATION → BOUNDED_PASS**; 137 checks/48 failures, then 137/0. Both plan hashes match the original genuine recordings. Evidence: `artifacts/demo-readiness/20261019T004240Z/` (explicit plan-hash guard enabled). |
| `evals/ablation_relationships.py astronomy-incident` | All seven conditions executed; 485 nodes preserved in each. Full graph 137 checks/48 failures; no lineage: same failures, zero derived origins; removed reader/store/record links: NEEDS_EVIDENCE. [Raw results](results/raw/ablation_relationships_incident.json). |
| Browser QA | Real incident proposal/citations, blocked result, ledger cluster filtering and exact receipt, complete lineage, replayed clarification/answer, flag-off alternative and 137/137 passing result verified. Human approval is available only on the passing candidate. No browser console errors observed; 390px mobile page has no horizontal overflow. |
| Broad `pytest -q -m "not live"`, started before concurrent repairs | **1285 passed, 9 failed, 5 errors, 12 skipped, 3 deselected** in 1508.92s. Seven failures/five errors are existing Windows repository-workflow issues (symlink privilege or newline filenames). Two incident baseline failures loaded mixed pre/post-repair code; both pass in the subsequent 22-test incident run. This broad run is not final-source acceptance. |
| Two fresh `prepare_demo.py --live` rehearsals | Both stopped at provider quota refusal (HTTP 413). No successful fresh live rehearsal claimed. Local evidence: `artifacts/demo-readiness/20261019T000057Z/`. |

The demo is ready to record using the validated, visibly labeled replay path. The graph and real
reader checks still run afresh. Live calls remain dependent on provider availability: two fresh
attempts received HTTP 413 quota refusals, and two more received HTTP 401 authentication errors.
No new live success is claimed. The earlier approval-review usage block was resolved after the
user's reset; the local incident server now runs on port 8006 for review.

Human simulation approval remains a separate operator action; the development assistant left the
browser at the passing candidate. Approval/idempotency behavior is covered by the acceptance tests.
No deployment or video publication was performed. The separately requested visual README update
was merged on GitHub `main` in [PR #40](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/40), after
all required CI checks passed. The incident implementation remains in this local feature worktree.

## Open work

Tracked in [GitHub issues](https://github.com/Ep1cGaimer/FalkorDB_agent/issues):

- **#17 — vague requests are sometimes guessed instead of clarified.** Today only a prompt rule
  handles it (`src/rw/grounding.py` system prompt). A trusted request-reference check is WIP on
  `fix/issue-17-references` (draft PR #31) and is not wired into `grounding.py`.
- **#22 — fair LLM comparison.** PR #32 (`plan/issue-22-fair-comparison`) is unmerged and predates
  the #38 ablation results; reconcile before merging.
- **#23** grounding rubric v2 (the disputed "inseparable" expectation); **#25** Astronomy Shop spike
  (the fixture now exists; likely closable); **#27** judge-facing docs.

## Known limits

- **What the graph does and does not do.** Every relationship is imported from the fixture files,
  and the trusted checker re-reads those files to cross-check graph rows, so missing edges become
  named gaps instead of a pass. SQL joins over the same facts tie on obligation sets (8/8). The
  graph's role is the connected query that decides what is checked, the agent's exploration tools,
  the witness path, and the context for the agent's alternative; it is not the only source of truth.
- **Synthetic fixtures only.** `BOUNDED_PASS` means modeled byte/shape readability; readers are
  trusted fixture code (the harness contains failures, it is not a sandbox); "simulate" writes a
  local SQLite record and performs nothing.
- **Live models.** The default chain is Groq's free tier, which evaluations exhaust quickly
  (~200k tokens/day on `gpt-oss-120b`). Any OpenAI-compatible endpoint can be selected with
  `RW_GROQ_API_URL`; published results used `gemini-3-flash` on both sides. Live results are small
  samples, not benchmarks.
- **Windows test environment.** Tests that create symlinks need Developer Mode or an elevated shell;
  without them they fail. Some repository-workflow tests also need `PYTHONUTF8=1` because file writes
  use the platform default encoding. CI's Linux jobs run the full suite and are the reference run
  (green on `main` at #38); the Windows CI job runs only the MCP/UI subset.
- **Replay is labeled.** `replay:<file>` with `live=False` is a saved transcript, not a live call.

Setup and demo commands: [QUICKSTART.md](QUICKSTART.md).
