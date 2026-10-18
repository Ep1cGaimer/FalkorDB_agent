# Status

Updated 2026-10-19, `main` after PR #38. This page is the single current-state summary; older dated
logs, review notes and per-issue reports were removed from the tree and remain in Git history
(last commit containing them: `25b5513`). Measured comparisons: [results/RESULTS.md](results/RESULTS.md).

## What exists

| Part | State |
|---|---|
| Rollback workflow (`src/rw/`): grounding agent → FalkorDB obligations → real reader probes → disposition → one agent alternative → human-approved local simulation | Implemented, the hackathon product |
| Demo fixture `fixtures/astronomy-shop` (4 services × 2 releases, 40 Kafka `orders` records) | Implemented ([design](../fixtures/astronomy-shop/DESIGN.md)) |
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

No live model calls were made for this update.

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
