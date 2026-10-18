# Source-line and claim-support follow-up

The observed fault was a reference that existed but did not support its claim.
The reference guard still checks identity/range/retrieval membership only and
explicitly leaves material grounding `UNSCORED`. Its success is never promoted to
semantic correctness.

Both comparison arms now receive source reads with explicit physical LF line
labels (`NUMBER | text`). The shared adapter replaces presentation text without
duplicating it; raw corpus bytes, source hashes, immutable citations and the
underlying raw read API remain unchanged. Tool-output bytes and provider tokens
include the formatted response. CRLF and embedded Unicode line separators retain
their correct physical LF numbering. Graph use remains optional.

The shared model runner can reserve capacity for a final answer before issuing
another retrieval generation. The recorded heuristic estimates answer headroom
from the current request plus1,024 tokens, one call and one output cap; it is not
an exact guarantee. Actual final token limits still apply. A controller stop is
locked as `FINAL_ANSWER_RESERVE` with `incomplete: true`; the final input requires
its disclosure, and an empty gap list is rejected. Nonempty gaps alone do not
semantically prove adequate disclosure. New result records also expose the
controller termination directly. This last output-metadata addition and its test
postdate the model trial; they do not change the trial's model requests.

Two focused regressions initially failed. The repaired affected suite passed132
checks, then **133 passed in8.31 seconds** after adding the explicit no-hidden-limit
regression and result metadata check. This is evaluation-only QA, separate from
the historical1,244-pass full application build. The five new claim-review
component checks passed separately. No full203-file suite claim is made.

## Focused static-limit pair

`run-006-numbered-reserve` repeats only the distinct static-limit scenario that
failed material citations or exhausted budget. Both arms use Gemini3.1FlashLite,
temperature0, the same raw corpus and the same96,000 input/8,000 output/180-second
model limits. The two attempts completed with no source-pin mismatches, no harness
error and successful owned-database cleanup. All earlier attempts remain intact.

Both final answers now cite the actual `Serializer.loads` implementation at
**serializer.py:330–345**, replacing the unrelated ranges previously selected.
The graph-capable answer stopped retrieval to preserve final-answer capacity and
explicitly disclosed the resulting limitation in both prose and gaps. It finished
in62.78 seconds with85,207 reported input tokens. Plaintext finished naturally in
60.10 seconds with88,105 input tokens, where its previous attempt exhausted its
budget without a final answer.

The independent [source review](goal-citation-support-repair-review.md) confirms
these repairs but retains smaller material-reference omissions: graph's concrete
`json` default requires line97, outside its final citations; plaintext mentions
fallback construction at299–309 in prose without including that span in its
structured citations. **Do not claim every material subclaim is now fully cited.**
The review is nonblind development work, not full T2 or comparative advantage.

## Separate model-assisted support review

`evals/confirmatory/claim_support.py` first requires valid references, then gives a
separate metered reviewer only the final source claims and exact cited lines.
It does not show uncited neighboring source, arm labels, expected answers or
retrieval strategy. The reviewer must split source claims and classify each as
supported, unsupported or unclear, anchored to supplied citation indices.
Unsupported/unclear claims reject the model review; malformed reviews remain
`UNVALIDATED`. Non-source Git proofs require another reviewer rather than being
silently accepted. This helper is a separate development evaluator, not enabled
as a new application endpoint or an infallible production guard.

Calibration001 used three previously reviewed answers, not three new investigation
questions. Gemini supported the precisely cited multi-hop answer and rejected the
old static answer with unrelated cited ranges. Its subtle-default review was
**UNVALIDATED**: it returned unsupported schema shapes and incorrectly used the
answer's own assertion as evidence for the `json` default. This failure is retained.
A subsequent generic prompt revision explicitly separates source facts from
process caveats, treats the answer/gaps as non-evidence, and distinguishes assigning
a default attribute from proving that attribute's value. Only that unresolved
calibration sample was retried as calibration002, recorded separately. Its raw
outcome is **MODEL_REVIEW_REJECTED**: the missing `json` evidence is caught.
Independent review still found a misclassified process claim and an omitted
fallback-signers claim in that revised review. The model-generated claim list
does not prove complete claim coverage; only sampleC used the revised prompt.
Raw output is in `artifacts/goal-quality-flash-lite/support-calibration-002/summary.json`.
No reviewer-accuracy rate or full semantic-checker validation is claimed from
these few development examples. Independent source adjudication remains required.

Application `src/`, endpoints, model settings and environment files are unchanged.
The deterministic live demo remains available at http://localhost:8127. No commit
or push was made. The latest requested deadline is20:30IST; all full T0–T11 gates
remain incomplete, including the120-question paired/blinded evaluation. This
follow-up advances that scope without declaring its remaining requirements waived.

Evidence: [bundle manifest](goal-citation-support-evidence/bundle-manifest.json),
raw `artifacts/goal-quality-flash-lite/`, `quality-answer-reserve-final.xml`, and
`quality-claim-support-final.xml`. Earlier evidence bundles are preserved unchanged.
