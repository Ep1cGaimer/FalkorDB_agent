# Plaintext control flag validation parity

Commit `812ecf7` fixes a validity-rule mismatch in the fixture's plaintext control.
The preceding repair commit is `8058032`; both descend from the audited remote
`origin/goal` revision. This is development evidence, not a comparative result.

The first fresh live fixture attempt produced **2 passed, 1 failed** in 408.83 s.
Both grounding-request cases passed. The control submitted an existing release
with a declared flag set to `false`; its validator incorrectly added an
`explicit_flags` error whenever a declared value differed from the release default.
Its prompt permits declared flags, and the production validator permits boolean
overrides. This explains the observed structural failure without attributing it
to an invented or undeclared flag. The supplied historical review is preserved
unchanged; this follow-up corrects its interpretation of the same failure shape.

The control now uses the same strict boolean parser as production and continues
to reject undeclared flags. It accepts a declared nondefault boolean and rejects
strings, integers and null values instead of coercing them. Runtime receipt
precedence, expected fixture dispositions and product prompts are unchanged.

Twelve new regressions failed before repair. After repair, **243 affected offline
tests passed**, with the three live-provider cases deselected. Replaying only the
original raw fleet through the repaired normalizer yields no structural errors;
this is labeled a [normalization replay](goal-control-flags-evidence/normalization-replay.json),
not a new live result or retrospective acceptance pass.

A separate fresh live control attempt then passed **1 test**, with 53 other
control tests deselected, in **215.87 s**. It used `groq:openai/gpt-oss-120b`, six
model turns and five tool calls. The original failed attempt, provider transcripts,
probe results and fresh attempt remain separately archived. One successful live
conversation does not establish general answer quality or retrieval advantage.

The complete 1,059-test offline run belongs to `8058032`. Commit `812ecf7` has the
affected 243-test subset and fresh live control check; independent clean full
reproduction is being recorded separately. The 166-file manifest was rehashed
after these checks with zero mismatches. All S/E/T gates remain **IN_PROGRESS**.

Evidence: [run summary](goal-control-flags-evidence/run-summary.json),
[current subset JUnit](goal-control-flags-evidence/control-flags-current.xml),
[original failed live attempt](goal-budget-evidence/goal-live-fixture-001.xml),
[fresh live attempt](goal-control-flags-evidence/goal-live-fixture-control-002.xml),
[raw fresh transcript](goal-control-flags-evidence/live-control-002-transcripts.tar.gz),
and [source manifest](goal-control-flags-evidence/implementation-manifest.json).
