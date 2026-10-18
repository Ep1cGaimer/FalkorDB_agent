# Citation integrity and current development checks

Development work on 2026-10-18. **Every S/E/T entry remains IN_PROGRESS.** No
held-out answers, Click source or confirmatory results informed these changes.
The handoff commit remains canceled; these are uncommitted working changes.

The development runner previously accepted a final answer citing the wrong
repository after successful real source retrieval. A regression reproduced that
failure before the guard was connected to the CLI. The shared `CitationGuard`
now checks both arms against the exact verified raw corpus and the evidence
returned before final generation: repository, immutable revision, included path,
blob/content hashes, physical LF spans and retrieved-span coverage. It also
checks returned commit/tag objects, diffs, ancestry results, refs and file
membership. Arguments, unsuccessful calls and JSON-looking repository text do
not establish retrieved evidence. Invalid references reject the generated answer;
raw responses and usage remain recorded.

This is **reference integrity only**. A valid reference can be irrelevant or fail
to support a material claim. The report explicitly leaves material grounding and
answer quality UNSCORED. An empty citation list is not a grounding pass. Independent
semantic grading, evidence precision/recall and T2's critical-error checks remain
required.

Two further regressions showed that changing `retrieval.json` during final
generation could go undetected, and a borrowed tool-cache object could change
after locking. The runner now detaches the JSON snapshot before saving it and
rechecks the saved digest before accepting a final answer. Validation has a
deadline and work/citation ceilings; exhaustion is a visible failure.

Five empty-file regressions then reproduced invented line-1 citations in product
module/change/note/fix evidence and unavailable empty-file reads in the plaintext
arm. Product citations for empty files now omit source lines. The graph adapter
and plaintext reader expose a `file_membership` proof with immutable identity and
hashes. Included file listings supply the content hash needed to copy that proof.
This establishes file membership, not any code-content claim. Nonempty source
keeps physical LF spans; out-of-range reads still fail.

## Observed verification

| Check | Actual result | Scope |
|---|---|---|
| Wrong-repository final CLI citation, before guard | 1 failed regression | Actual export/retrieval; fake provider final answer |
| Retrieval file/cache mutation, before fix | 2 failed regressions | Controlled mutation during fake final generation |
| Lock and citation checks after fix | 37 passed | Deterministic development tests |
| Empty-file regressions before fix | 2 raw-reader failures, 3 graph/product failures | Fresh synthetic Git and actual isolated FalkorDB |
| Affected graph/reader/runner/CLI checks after fix | 75 passed, zero failures | Includes real graph operations and fake model cases |
| Full staged non-live suite | **1,213 passed; 6 skipped; 3 live deselected; 246.32 s** | Parent QA, both real-repo environment flags enabled |
| Full-run source pin | **192 files, zero before/after mismatches** | Clone of `520e8fa` plus recorded working overlay |
| Fresh real-corpus reference probes | Requests 11/11; ItsDangerous 9/9 references valid | Actual graph lookup/hop-2/source references; no generated answer |

The six full-suite skips are absent E2/history, E2/E4, scale and benefit outputs
and an empty historical-artifact parameter set. These are missing required
experiments, not waived acceptance requirements. Test counts include artifact
checks and are not real-question or accuracy denominators. The new compact-context
renderer was added afterward and passed three separate reconstruction/isolation
tests; it is outside the 192-file full-suite pin. An initial renderer test failure
from assuming tag records carried a byte-count field is retained with its fix.
The supplemental checks do not make this an independent clean reproduction.

## Live failures retained

One fresh attempt per arm was declared, plaintext then graph, on the same public
Requests development question and full raw corpus. Both used Gemini3.8, common
answer instructions and shared budgets; graph interfaces and attestation overhead
were disclosed. Plaintext timed out on its first generation at 120.009 seconds,
with usage unknown and reservations retained. Graph readiness checked 6,372
commits, 106,594 file bindings and 7,973 ordered parent edges; the first generation
returned `MALFORMED_FUNCTION_CALL`, so no tool action or answer was accepted.
Its reported 1,255 input tokens were retained. Neither attempt is a completed
investigation, paired quality measurement, or T9/T10 pass.

A separate first-action configuration probe added explicit
`toolConfig.functionCallingConfig.mode=NONE`. The official
[GenerateContent function-calling guide](https://ai.google.dev/gemini-api/docs/generate-content/function-calling?hl=en)
documents that this prohibits native function calls. The observed service still
returned `MALFORMED_FUNCTION_CALL`. This did not establish a fix, and the probe
was not promoted into the runner or counted as an investigation. Non-STOP text
was not salvaged into a successful action. Model/protocol availability remains
unresolved; no automatic retry or fallback was added.

Inspecting that response also exposed incomplete usage metadata: it contained
visible planner text but no candidate-token count, with total tokens equal to
prompt tokens. The original meter treated its output usage as known zero. Four
regressions reproduced this for missing/zero counts and STOP/non-STOP responses.
The follow-up now keeps the output reservation and marks usage unknown, retaining
reported subtotals. **71 affected tests passed**. Replaying the exact recorded
request/count/response through the corrected meter rejected the metadata and
retained a 1,000-token output reservation; this is explicitly a replay, not a
fresh live result. The original live result is unchanged. Its output-completeness
flag is not reliable and must not be used to infer zero cost or complete usage.

That meter/test follow-up changed two existing files after full-002. The original
194-file source capture is retained; `implementation-manifest-v2.json` and
`source-snapshot-v2.tar.gz` identify the current source. Thus the full-suite
numbers above apply to their original 192-file pin; current metering additionally
has the separate 71-test and actual-byte replay evidence. No whole-suite rerun
on the later meter is claimed.

Raw red/green reports, full-suite logs/environment, actual graph traces, live
failures, the configuration probe and source capture are in
[goal-citation-integrity-evidence](goal-citation-integrity-evidence/). Owned
containers were removed; unrelated database services were left running. No new
commit or push was made. Signed T0, unseen onboarding, held-out scoring, measured
scale/costs, all comparison gates and independent live reproduction/demos remain.
