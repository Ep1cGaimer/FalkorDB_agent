# Metered development model runner

The later [citation integrity batch](goal-citation-integrity.md) adds the common
raw-corpus reference guard, immutable lock checks and empty-file membership
references. Full parent QA passed1,213 checks with6 missing-artifact skips and3
live exclusions. One fresh attempt per arm failed before accepted tool execution:
plaintext timeout and graph `MALFORMED_FUNCTION_CALL`. A separate native-call
disabling probe also failed to resolve the latter. No successful live end-to-end
general investigation is claimed. These later attempts are retained separately
from the three historical attempts below.
The later usage follow-up also rejects visible output with zero/missing candidate
tokens, retaining reservations and usage uncertainty. Its71 passing tests and
exact-response replay postdate the full-suite pin. The original graph failure's
output-completeness flag is unreliable; its recorded failure and raw bytes remain.

Development work on 2026-10-18. **T0–T11 remain IN_PROGRESS.** No held-out question,
sealed expectation or Click source was used, and no answer-quality or comparison
result is asserted.

`evals/confirmatory/gemini_meter.py` now preflights the complete request through
the provider tokenizer, reserves input/output capacity before generation, and
reconciles actual prompt, generated and thinking tokens from the returned usage.
It retains both the preflight and reported counts. Count requests include the
system instruction and generation request, following the official
[countTokens contract](https://ai.google.dev/api/tokens). Thinking and other usage
fields are defined by the provider's
[generation API](https://ai.google.dev/api/generate-content). No bytes/token
estimate is substituted for these per-request measurements.

All planner and answer turns share cumulative input/output, model-call and time
budgets. The default 64-token input reserve is a preflight discrepancy guard,
not measured usage. Provider overshoot is recorded and fails the attempt rather
than being clipped. A failed or malformed generation retains its reservation and
marks usage uncertain; reported token subtotals are then incomplete and cannot be
used as a zero-cost result. Provider billing remains unmeasured. There is no retry,
model fallback, answer cache, redirect following or credential-bearing URL. Keys
travel in a header; provider error bodies are excluded from journals.

`investigation_runner.py` performs iterative retrieval with an explicit capability
map. Each operation is journaled. Before final-answer generation it writes and
fsyncs a new-only retrieval artifact and records its SHA256. The final phase has
no retrieval tools and uses the same answer instruction across arms. Invalid JSON,
duplicate keys, budget exhaustion, missing usage, response-version drift and
source-only runtime dispositions leave a failed attempt and no accepted answer.
`COMPLETE_UNSCORED` means only that the response has the expected protocol shape;
independent fact/citation scoring is still required.

`development_cli.py` exposes the practical plaintext search/read/history/ref tools
over an explicit hashed export. It accepts only public task fields and rejects
confirmatory IDs and paths resolving into a `sealed` directory. This is a logical
guardrail, not the OS data allowlist/container isolation needed for T0. Unset
decoding fields remain provider defaults; no final model/prompt contract is frozen.

The shared tool meter also counts transmitted success-envelope bytes and failed
operation envelopes. Terminal exhaustion diagnostics are bounded metadata outside
the exhausted evidence allowance. Exact model input accounting includes the
assembled prompts and tool messages through provider usage.

## Observed checks

The combined corpus/plaintext/tool-budget/model-meter/runner/CLI and existing
scoring/statistics integrity suite passed **88 tests**, with zero failures, in
4.32 seconds. Provider behavior in those tests uses explicit fakes or HTTP mocks;
these are not 88 real questions or a model accuracy metric.

Three live development attempts were preserved:

| Attempt | Result | Meaning |
|---|---|---|
| Neutral transport smoke001 | PASS; 30 reported input tokens, 67 output including thinking, 3.332 s | Actual count/generation format and returned usage work for a neutral JSON request. |
| Requests investigation001 | ERROR: HTTP503 on second generation, after source search; 21.273 s | First generation reported 525 input and 210 output tokens. Failed generation usage unknown; no final answer or locked completed retrieval. |
| Requests investigation002 | ERROR: provider timeout; 120.008 s | No completed generation or answer; usage unknown, reservations retained. No automatic retry. |

The second Requests diagnostic was explicitly started as one fresh attempt after
the first failure, then stopped without further retries. It used the newly exposed
complete nine-tool CLI interface; attempt001 used four tools. Their prompts/tool
descriptions differ and both setups are retained. They are development diagnostics,
not paired repetitions, not a favorable-run selection, and not held-out results.

The two failed investigations remain **failures**. The 120.008-second elapsed time
also does not establish a hard 120-second OS limit. The live attempts predate the
last model-setup journal and envelope-accounting follow-ups; the final 182-file
archive is a post-run development source capture, not a claimed pre-result pin of
every live byte. Exact requests, responses, known usage, uncertainty, prompts,
tool results and both failures are in
[goal-model-runner-evidence](goal-model-runner-evidence/).

## Remaining work

- Successful live end-to-end development investigations. The actual graph adapter
  now exists and shares raw evidence/tools, answer instructions and budgets, but
  current generated investigations have failed and are not quality measurements.
- Final context-reserve proof and independently reviewed baseline eligibility.
  Separate compact full-development-corpus token counts are now recorded in the
  [direct-context report](goal-direct-context.md); no final Requests/Click plan
  has been signed or frozen.
- Frozen decoding/model metadata, fair baseline development and pilot power
  analysis, scorer/adjudicator identities, runner OS isolation and independent T0
  signature before any confirmatory run.
- Independent retrieval/answer scoring, paired repeats, scale measurements,
  comparative intervals/costs and T11 live reproduction/demos.

The evidence bundle contains no oracle, Click source or provider credentials.
