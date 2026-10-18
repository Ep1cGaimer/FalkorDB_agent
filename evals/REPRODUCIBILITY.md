# Evidence reproducibility (E1–E5)

Every evidence run writes one timestamped JSON record (`<name>-<YYYYMMDDTHHMMSS>Z.json`); earlier
records are never overwritten. Crashed or incomplete attempts go to `artifacts/<category>/attempts/`
with `status` and `error`/`failures`. `tests/repo/test_e5_reproducibility.py` checks each record.

Each record holds: `command`, `manifest` (repo + resolved revision shas), `coverage` (gaps/limits),
`config` or `config_sha256`, `model` (model id + prompt id/sha256, when an LLM was used), `traces` or
`traces_path`, `answers`, `usage`/`timings`, and `scoring` (for scored runs).

| Evidence | Command | Outputs |
|---|---|---|
| E1 onboarding (S1, S5) | `RW_REALREPO=1 .venv/Scripts/python.exe -m pytest -q -m realrepo tests/repo/test_e1_onboarding.py` (configs in `evals/repo_onboarding/configs/`) | `artifacts/repo_onboarding/*.json`, `artifacts/repo_onboarding/attempts/` |
| E2 history correctness (S2, S3) | `PYTHONPATH=src .venv/Scripts/python.exe evals/repo_eval_configs/index_all.py` (builds graphs for the synthetic/branchy/itsdangerous question repos; synthetic repos from `evals/repo_questions/build_*.py` into `artifacts/question_repos/`), then `PYTHONPATH=src .venv/Scripts/python.exe evals/repo_history_eval.py` (deterministic retrieval, no LLM; plans and answer keys in `evals/repo_eval_keys.json`); also `pytest -q tests/repo/test_s2_evidence.py tests/repo/test_s3_revisions.py` | `artifacts/repo_history_eval/*.json`, `artifacts/repo_history_eval/attempts/`, `artifacts/repo_eval_index/*.json` |
| E3 scale and updates (S4) | `.venv/Scripts/python.exe evals/repo_scale.py [--graph rw_repo_requests]` (budgets in `evals/repo_budgets.json`, declared before measuring) | `artifacts/repo_scale/*.json`, `artifacts/repo_scale/attempts/` |
| E4 FalkorDB benefit (S2–S4) | `PYTHONPATH=src .venv/Scripts/python.exe evals/repo_benefit.py` (declaration `evals/repo_benefit_threshold.json`, fixed before evaluation; smoke: `--smoke --questions <id> --contestants <name>`) | `artifacts/repo_benefit/*.json`, `artifacts/repo_benefit/traces/`, `artifacts/repo_benefit/attempts/` (checkpoints, smoke runs, crashed runs) |
| E5 reproducibility and boundaries (S1–S6) | `.venv/Scripts/python.exe -m pytest -q tests/repo/test_e5_reproducibility.py tests/repo/test_s6_boundaries.py` | pytest output |

Boundaries checked by E5: ingestion never runs repository code (only allowlisted read-only `git`
subcommands are spawned), retrieval never gives a compatibility disposition, and runtime checks only
come from registered adapters with current receipts. Otherwise the gap stays explicit
(`NO_RUNTIME_ADAPTER` / `runtime_unverified`). Fixture results and the documented SQL tie do not show
any large-codebase advantage.
