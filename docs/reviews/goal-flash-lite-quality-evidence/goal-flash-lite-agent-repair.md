# Optional graph selection and typed calling repair

The development investigation agent now chooses among directly declared, typed
native functions instead of placing loosely typed arguments inside a generic
`select_action` call. Required revision/symbol arguments are visible to Gemini;
`symbols` uses `name`, while relationship traversals use `symbol`. Native call
parts, IDs and thought signatures survive continuation. Only the application
can dispatch the explicit read-only capability allowlist. The CLI's native mode
uses this protocol, `native-typed-tools/v3`; the older protocol remains available
for reproduction of previous attempts.

The shared reasoning prompt keeps graph use **optional**. It explains when graph
traversal can help with several hops, reverse relationships or history, and when
a direct source read is simpler. It asks the agent to verify graph findings in
source, inspect coverage, establish enclosing classes before naming methods,
avoid unchanged failed/repeated reads, and cite the actual supporting span. No
keyword router, mandatory graph-call counter or graph-only finish gate was added.
The graph arm can choose raw reads or finish without traversal. Its readiness
check attests corpus membership and is not counted as model-selected graph use.

This repair changes evaluation orchestration and prompts, not application
endpoints, production `src/`, application model configuration, or environment
files. Test processes explicitly use **models/gemini-3.1-flash-lite**. Every owned
quality database was removed; the existing demo remains at http://localhost:8127.
The handoff commit remains canceled. No commit or push was made.

## Focused final-answer results

These are three distinct development scenarios paired once per arm on inspected
ItsDangerous source at `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd`. Both arms use
the same source corpus, question, shared prompts, model, temperature 0, native
protocol and 96,000 input/8,000 output-token/180-second model limits. The model
chooses graph use freely. Source expectations were recorded before each version's
calls; this is development tuning, not a fresh confirmatory experiment.

| Scenario | Graph-capable agent, repaired version | Plaintext, repaired version |
|---|---|---|
| Two-hop inheritance | Correct two paths and all four exact source citations; actual `dependencies(hops=2)` returned four inheritance edges. Final answer in 42.66 seconds. | Core paths correct, but two final single-line citations miss the declarations: 80 instead of 79 and 176 instead of 170. Material citation failure. |
| Ambiguous `unsign` owner | Correctly lists `Signer` and `TimestampSigner`, with correct implementation spans. A single `symbols` lookup suffices; no unnecessary traversal. Final answer in 19.00 seconds. | Still names `TimedSerializer` instead of `TimestampSigner`; material answer failure. |
| Static completeness | Correctly warns that static evidence cannot prove exhaustive runtime callees; final citation spans do not support several material implementation claims. Material grounding failure. No successful dependency traversal claimed for this case. | Exhausts input-token budget without a final answer; counted as failure. |

The original separate missing-revision pair correctly kept the unavailable SHA
unresolved without fallback or invented citations. It used the earlier 24,000-token
JSON protocol and is not pooled into the repaired 96,000-token comparison.

All earlier JSON planner failures, HTTP 429 responses, 24,000-token native budget
failures, the interrupted higher-budget attempt, and the earlier follow-up results
remain in `artifacts/goal-quality-flash-lite/`. No successful first tool call is
promoted to answer-quality success. Reference identity validation does not prove
that a cited span supports a material claim. The unused bounded-answer controller
prototype was never run; it is explicitly marked `NOT_RUN` in the evidence.

The independent [source review](goal-flash-lite-agent-repair-review.md) is nonblind
and uses development tasks which informed the repair. The four-scenario exercise
does **not** establish aggregate graph superiority, full T2/T9/T10, confidence
intervals or the original v1 acceptance goal. All full T0–T11 gates remain
`IN_PROGRESS`. Remaining quality work includes reliable source-line selection,
class-context retrieval in the plaintext arm, and preserving enough budget for
a final answer. The unsigned 120-question, three-repeat blinded evaluation and
other full acceptance requirements remain required.

## Verification

Two new native-calling regressions initially failed; 13 existing native checks
passed. After implementing typed calls, an affected-suite attempt passed 105 and
failed one test whose fake still emitted the old `select_action` protocol. That
attempt is retained. Updating the fake to the new declared protocol and adding a
regression that explicitly chooses raw reads while graph traversal is available
produced **120 passed in 5.28 seconds**, with no failed or skipped tests. Command:

```sh
PYTHONPATH=src:evals /tmp/rw-mcp-compat/bin/python -m pytest \
  tests/test_confirmatory_native_decisions.py tests/test_confirmatory_model_meter.py \
  tests/test_confirmatory_investigation_runner.py tests/test_confirmatory_development_cli.py \
  tests/test_confirmatory_plaintext.py tests/test_confirmatory_citation_guard.py \
  tests/test_confirmatory_tool_budget.py -q \
  --junitxml=artifacts/quality-typed-tools-final.xml
```

The final six-attempt model run completed with no harness error, no source-pin
mismatches, no tool TypeErrors and successful owned-database cleanup. A fresh
post-repair demo smoke passed natural-language investigation, real hop-two
retrieval, source citations, fix/revert boundaries, truncation and missing evidence.
The earlier full application suite remains **1,244 passed, 6 skipped, 3 live
excluded** on its original 199-file pin; the later evaluation-only changes have
the affected checks above, not a new full-suite claim. The separate paired-score
aggregator passed 14 component checks and does not grade these answers or establish
comparative advantage.

Raw final results: `artifacts/goal-quality-flash-lite/run-005-typed-reasoning/`.
The [evidence bundle](goal-flash-lite-quality-evidence/bundle-manifest.json)
contains all attempt versions, independent reviews, exact source snapshot,
endpoint-preservation checks and test receipts. No sealed expected answers were
opened or used for this repair.
