# Pre-answer retrieval scoring checkpoint

The development runner now accepts an explicitly supplied retrieval scorer and
can require it before any generation. After retrieval is durably locked, the
scorer receives a detached copy. A bounded receipt binds task ID, retrieval hash,
scorer/rubric/oracle-manifest/assessment identities and finite precision/recall or
explicit N/A. The receipt is saved and hashed before final-answer generation.
No score, receipt or oracle annotation enters either answering-model phase.
Scores of zero do not trigger another retrieval attempt or suppress generation.

Missing required scoring, wrong trace identity, extra expected-answer fields,
nonfinite metrics and altered locked evidence stop generation. The trace and
receipt hashes are checked before and after final generation. Earlier development
runs without a scorer remain explicitly unscored. Confirmatory IDs remain disabled.

Six new regressions initially failed and19 existing runner checks passed. After
the change,69 affected runner/native/CLI/reference checks passed in2.78seconds.
Raw red and green outputs are preserved in the evidence bundle.

This is a callback/checkpoint interface, not an implemented independent evaluator
or OS isolation boundary. The receipt's assessment hash is an attestation from
the configured scorer; this runner does not open a sealed assessment to prove it.
A future frozen runner must bind roster applicability and scorer provenance,
validate the external assessment, enforce allowed reads, account for scoring cost
and timing, and obtain independent sign-off. Trace locking alone was insufficient;
this change supplies ordering/recording controls without claiming full T2.

Production source/endpoints are unchanged. The previous203-file source snapshot
and readiness review remain historical for the two changed evaluation files.
The new snapshot preserves the same203paths with new byte hashes. No model calls,
held-out reads, commit or push were made for these component checks. All complete
T0–T11 gates remain IN_PROGRESS.
