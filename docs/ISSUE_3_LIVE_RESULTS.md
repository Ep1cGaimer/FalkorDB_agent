# Issue #3: pre-fix live evaluation results

These are historical results from before the user authorized code changes. See [ISSUE_3_FIX_REPORT.md](ISSUE_3_FIX_REPORT.md) for the implementation, reasons and subsequent verification.

Date: 2026-10-16. Source commit: `771ce3814e7ad8bb6c5902e4ac9de83a711abbee`.

**Status: incomplete: 0 of 3 required successful control tests.** Three separate live-test executions failed, one per model, with two internal control attempts each. The product's successful browser walkthrough does not satisfy this separate evaluation requirement.

## What was executed

The existing `tests/test_llm_control.py::test_live_control_runs_once` test was run against Groq with the user-supplied local credential. Each model was selected using `RW_GROUNDING_MODEL`, with a single model per test and no fallback to a different model. The test itself permits two attempts.

The request remained:

> Undo the basket rollout, but keep the receipt correction.

The fixture, prompt, tool declarations, eight-turn cap and temperature 0 were unchanged. Application, test and evaluation source files were not edited. The web app's configured model was left unchanged; alternate models were selected only in the evaluation subprocess environment.

| Model | Live-test result | Recorded provider failure |
|---|---|---|
| `groq:openai/gpt-oss-120b` | Failed: both internal attempts failed | HTTP 400, `tool_use_failed`. The attempted tool names were `json` and `commentary`, neither of which was declared. |
| `groq:qwen/qwen3.8-27b` | Failed: both internal attempts failed | HTTP 400, `tool_use_failed`; the provider reported that it could not generate a valid function call. |
| `groq:openai/gpt-oss-20b` | Failed: both internal attempts failed | HTTP 429, an 8,000-token-per-minute allowance was exceeded. |

GPT-OSS 120B and Qwen used the existing default transport retry setting. GPT-OSS 20B used the supported environment override `RW_GROUNDING_RETRIES=2` to bound rate-limit retries. This difference is recorded; these are feasibility attempts, not model rankings.

Each JUnit result records one failed test, zero errors and zero skips. There are no successful control transcripts. Additional live tests and product comparison calls were not run after these failures; no passing model configuration was established for a paired dataset.

## What the failures establish

The fresh GPT-OSS 120B and Qwen errors were **tool-call failures**, not reported daily quota exhaustion or oversized-request errors. This updates the earlier diagnosis based on historical quota failures. Groq documents HTTP 400 as a possible result of invalid tool-call generation. [Official local-tool-calling documentation](https://console.groq.com/docs/tool-use/local-tool-calling)

The GPT-OSS 20B attempt separately demonstrates a current per-minute quota obstacle. A shorter product request can succeed while the larger multi-turn control fails; successful authentication and model visibility do not establish enough inference capacity for the evaluation.

The transport truncates provider error text to 200 characters. It does not save a completed control transcript when all attempts raise a provider error. Therefore these failure logs cannot establish the full generated tool payload, the exact failed turn, all intermediate retry statuses or total token usage. They should not be presented as a complete root-cause trace.

## Evidence locations

The local evaluation directories are git-ignored:

- `artifacts/issue-3/20261016T163708Z/`: GPT-OSS 120B manifest, captured pytest output and JUnit result.
- `artifacts/issue-3/20261016T164322Z/`: Qwen manifest, captured pytest output and JUnit result.
- `artifacts/issue-3/20261016T164719Z/`: GPT-OSS 20B manifest and captured output.

Each directory keeps separate `controls/`, `reports/`, `logs/` and `pytest/` paths. Successful transcripts would be copied from pytest's temporary directory into `controls/` for the existing scorer. No fake or replay transcript is substituted for a failed live run.

The existing `evals/score_controls.py` was invoked separately for each directory, and its output is saved in that directory's `comparison.md`. All three invocations exited 0 with **no scored runs found**: neither a completed control transcript nor a matched product dataset was available. This is a scorer execution, not a completed comparison or evidence of a tie.

SHA-256 comparison confirmed that all 48 application, test, evaluation, fixture and script files recorded before the trials remained unchanged. Only documentation and ignored local evaluation artifacts were written. No GitHub issue update, commit or push was performed. The web app remained available on `http://127.0.0.1:8000/` after the trials.

This tracked report contains the relevant sanitized observations so a reviewer does not need access to local account identifiers or the credential.

## Reproduce a live-test attempt

From the repository root, with the credential already in the ignored `.env`:

```bash
RW_GROUNDING_MODEL='groq:openai/gpt-oss-120b' \
  .venv/bin/python -m pytest -q -s -m live \
  tests/test_llm_control.py::test_live_control_runs_once
```

For the other trials, replace the model with `groq:qwen/qwen3.8-27b` or `groq:openai/gpt-oss-20b`. The recorded GPT-OSS 20B trial additionally set `RW_GROUNDING_RETRIES=2`. This command makes real provider calls; none of its results should be counted as a successful run unless pytest actually passes.

## How to finish the issue

1. Resolve sufficient model capacity and the observed tool-call failures using a configuration the maintainer permits. An increased quota alone does not establish that the HTTP 400 errors are resolved.
2. Run the existing live control test until **three executions actually pass**, preserving unsuccessful attempts too. Do not count skips.
3. Collect product runs for the same request, snapshot, source revision and actual model. Preserve clarifications and rejected proposals rather than replacing them with operator-specified fleets.
4. Run `evals/score_controls.py` against only that paired dataset and preserve the table in a tracked report. Report a tie or control win as observed.

With the current environment-only restriction, another provider's base URL cannot be selected: the Groq endpoint is hardcoded. If the existing models remain unusable, the maintainer needs to decide whether to investigate the provider/tool-call behavior or authorize a small configuration change enabling another OpenAI-compatible endpoint. No such application change was made here.

For the project explanation, see [PROJECT_GUIDE.md](PROJECT_GUIDE.md). For configuration constraints and the original solution options, see [ISSUE_3_ANALYSIS.md](ISSUE_3_ANALYSIS.md).
