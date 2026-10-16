# Issue #3: recorded live comparison

Recorded 2026-10-16, with UTC timestamps. This completes the issue's **local evaluation acceptance**: three separate live control-test passes, a same-model product comparison, and the existing scorer's recorded output. It does not close the GitHub issue or publish these local changes.

## Protocol and evidence

- Request: `Undo the basket rollout, but keep the receipt correction.` Snapshot: `snap-001`.
- Both sides: `groq:qwen/qwen3.8-27b`, temperature 0, completion cap 1000, maximum eight model turns, Groq's OpenAI-compatible Chat Completions endpoint. Control protocol version 4.
- Product: normal grounding plus real graph/checker/reader probes; evaluation scope confirmation only, with no alternative round, action approval or simulation. Each run used and deleted a disposable graph.
- Control: all 13 relevant source files as plain text, the same trusted reader-probe capability, and its own fleet/disposition decision. No source file or answer was removed to force a product win.
- Base commit: `771ce3814e7ad8bb6c5902e4ac9de83a711abbee`; the tested patch remains local and uncommitted. Runner source hashes were unchanged during collection. All 13 context-file hashes agree across the three controls and match the checkout, including the changelogs.
- Dataset: `artifacts/issue-3/comparison-20261016T172909885914Z/`. Its manifest has `requested_pairs_complete=true`, `source_unchanged_during_run=true`, and `issue_3_complete=true`. All three JUnit files record exactly one pass, zero skips/failures/errors. Provider response model IDs also match the pinned model.

The dataset retains control transcripts, product reports, grounding transcripts, JUnit/logs, `scores.json`, the source-hash manifest and the scorer's `comparison.md`. Artifacts are git-ignored; this document preserves the shareable result. Failed earlier pilots remain separate and are described in [the fix report](ISSUE_3_FIX_REPORT.md).

## How to read the result

The scorer reports **product 3/3 versus control 0/3 oracle-consistent runs**. Its definition requires the oracle disposition *and* every required probe. Each control checked 3/4 pairs, missing Checkout 2.1 × `saved-cart-1001`; each product checked 4/4. Both selected fleets really have readable fixture bytes, so both have **zero false BOUNDED_PASS** under the scorer's disposition-only definition.

The fleet difference also matters. All three controls submitted an extra field named `flags:` instead of the declared `flags`. The existing normalizer ignored that field and used the declared default, leaving `basket_v2=true` (oracle D), despite prose describing the flag-off approach. Raw arguments are preserved; no answer was repaired after the fact. The live test checks a usable terminal result and validation errors, but it does not reject every unknown nested field or guarantee semantic correctness. Tightening that validation is a separate follow-up; these results do not count the normalized fleet as a successful rollback.

The product proposed Cart 1.5 with `basket_v2=false` plus Checkout 2.1 (oracle B). The independent oracle calls the basket rollback **partial** under a cross-service interpretation: retained cart/v2 records still contain baskets, and Checkout 2.1 still supports basket headings. Keeping the receipt correction is established from release-source evidence, not behavior tested by the readability probes. BOUNDED_PASS therefore remains modeled byte/shape readability only.

This compares complete workflows, including the product's deterministic obligation enumeration. It does not isolate a causal advantage of graph storage over SQL, generalize to production, or complete the separate multi-request grounding evaluation (#2). Three repeated temperature-0 runs on one request are not a broad model benchmark.

## Observed provider behavior

| Workflow | Successful conversations | Model turns per conversation | Reported tokens per conversation | Maximum observed prompt tokens | Recoverable HTTP responses across three runs |
|---|---:|---:|---:|---:|---|
| Flat control | 3/3 | 5 | 20,980 | 5,237 | Three HTTP 400 `tool_use_failed`; two HTTP 429 |
| Product | 3/3 | 4 | 15,167 | 6,609 | Two HTTP 429 |

All three generated-call rejections were corrected within the existing turn cap. All four 429 responses recovered through the existing HTTP retry policy. No HTTP 413 occurred in this final dataset. Token totals are the provider's usage on successful responses; they do not estimate usage of rejected requests. Pacing waits totaled about 542 seconds for the controls and 326 seconds for the product, excluding HTTP retry waits and inference time. New conversations can still start inside a depleted shared window because transport budget state is local to a conversation; retries remain necessary. The patch does not remove account limits.

## Exact scorer output

The following is copied unchanged from this dataset's `comparison.md`. `[-basket_v2]` means false; `[basket_v2]` means true. The scorer's abbreviated `product-1.js#1` labels refer to `reports/product-1.json`, and similarly for 2 and 3. “Tool calls” counts model read/probe audit entries, not the product checker's four reader executions.

## Product vs flat-context control — scored against evals/expected/dispositions.json (synthetic fixture)

| run | model (live) | proposed fleet | oracle case | receipt correction kept | probe recall | proposed cart reader x 2002 probed | false BOUNDED_PASS | disposition = oracle | model turns | tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| product product-1.js#1 | groq:qwen/qwen3.8-27b | cart 1.5 [-basket_v2], checkout 2.1 | B | yes | 4/4 | yes | no | yes | 4 | 3 |
| product product-2.js#1 | groq:qwen/qwen3.8-27b | cart 1.5 [-basket_v2], checkout 2.1 | B | yes | 4/4 | yes | no | yes | 4 | 3 |
| product product-3.js#1 | groq:qwen/qwen3.8-27b | cart 1.5 [-basket_v2], checkout 2.1 | B | yes | 4/4 | yes | no | yes | 4 | 3 |
| flat_control 10-16 17:32:06 | groq:qwen/qwen3.8-27b | cart 1.5 [basket_v2], checkout 2.1 | D | yes | 3/4 | yes | no | yes | 5 | 3 |
| flat_control 10-16 17:42:33 | groq:qwen/qwen3.8-27b | cart 1.5 [basket_v2], checkout 2.1 | D | yes | 3/4 | yes | no | yes | 5 | 3 |
| flat_control 10-16 17:48:20 | groq:qwen/qwen3.8-27b | cart 1.5 [basket_v2], checkout 2.1 | D | yes | 3/4 | yes | no | yes | 5 | 3 |

Outcome: product ahead on oracle-consistent runs — control: 0/3 oracle-consistent runs (best: none); product: 3/3 (false BOUNDED_PASS: control 0/3, product 0/3)

Breakdown (oracle case / claimed disposition):
- control: D/BOUNDED_PASS x3
- product: B/BOUNDED_PASS x3

Notes:
- probe recall counts only probes that actually ran and compares exact reader identity (service, version, record_id); a probe of another version of the same service is not the obligation the proposed fleet carries, and a call rejected by the allowlist does not count.
- `proposed cart reader x 2002 probed` is the cart reader of the proposed version on the retained cart/v2 bytes (saved-cart-2002).
- disposition for a fleet with no oracle case is derived from the oracle's per-reader predictions plus manifest gaps, and the row says so.

wrote /home/varun/code/FalkorDB_agent/artifacts/issue-3/comparison-20261016T172909885914Z/scores.json

## Reproduce

See the [fix report's commands](ISSUE_3_FIX_REPORT.md#reproduce-the-comparison). The comparison is a real provider workload and may take many minutes on this allowance. Run it with an available credential and FalkorDB; a replay is not a replacement for these live tests.
