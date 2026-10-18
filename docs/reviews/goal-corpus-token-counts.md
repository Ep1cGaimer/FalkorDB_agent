# Exact development corpus token counting and file-identity diagnostic

The later [compact direct-context measurement](goal-direct-context.md) succeeded
for both development corpora: **23,642,469 provider tokens for Requests** and
**1,610,496 for ItsDangerous**. Those are separate, lossless factored-tree
presentations. The failures and missing count for the earlier Requests JSONL
encoding below remain historical failures; they have not been overwritten.

Development checks on 2026-10-18. **T0 and T6 remain IN_PROGRESS.** No question,
answer, oracle or Click source was sent. These were tokenizer/file-protocol calls,
not generated investigations or quality/comparison measurements.

The complete ItsDangerous development export is 6,983,628 bytes, SHA256
`4d55d72fa81b6221660526560a4c35ab252f2e4529fb530968388975d0b53352`.
Sending that entire canonical JSONL string as one user text part to
`models/gemini-3.8-flash:countTokens` returned **2,851,850 tokens**, HTTP200, in
9.022 seconds. The request hash and exact provider response are retained. This
is an actual tokenizer count for that serialization, not bytes/4 or a sum of
independently tokenized chunks.

The storage serialization includes historical memberships and metadata, JSON
escaping and raw objects. This count does **not** establish the minimum or best
practical direct-context encoding. A fair compact direct-context representation
still needs independent review and its own count, prompt/tool/output reserves and
eligibility determination. The final chosen Requests/Click protocol remains
unsigned; this development measurement does not validate it.

The larger Requests export is 151,612,580 bytes, SHA256
`0a276e3e6134389c0d7b97a559c6db93f918eeb0d200fee79e6fd1a0db36420c`.
Two explicit Files API attempts were made, following the documented
[large-file input path](https://ai.google.dev/gemini-api/docs/files):

| Attempt | Outcome |
|---|---|
| requests-full-file-token-count001 | Upload HTTP200; identity verification failed before counting; owned uploaded file deleted with HTTP200. |
| tiny file-identity diagnostic001 | Size matched, but the decoded metadata hash was 64 ASCII hexadecimal characters, rather than 32 digest bytes; owned file deleted with HTTP200. |
| requests-full-file-token-count002 | Upload HTTP200; exact SHA256 and size verified after explicit representation normalization; token request timed out; owned file deleted with HTTP200. |

The [File metadata reference](https://ai.google.dev/api/files) describes
`sha256Hash` as a base64-encoded digest. The observed service encoded hexadecimal
text inside base64. The new `file_identity.py` verifier accepts either exact
32-byte digest or exact 64-character hexadecimal representation, records which
was observed, and requires equality with the locally computed SHA256 **and** byte
size. It rejects malformed encodings, arbitrary text, wrong hashes and wrong
sizes. **14 separate unit tests passed**. No digest or size mismatch is ignored.

The first large-file attempt did not retain its returned checksum fields before
raising; its identity failure and cleanup remain recorded. The tiny diagnostic
retains the actual safe metadata needed to identify the encoding issue. Attempt002
retains normalized identity, request hash, failure and deletion receipt. Upload
session URLs and API keys are excluded. The final Requests full-corpus token
count remains **missing**; no estimate is substituted for its timeout.

The inspected official SDK
[local-tokenizer model map](https://github.com/googleapis/python-genai/blob/main/google/genai/_local_tokenizer_loader.py)
did not list the proposed Gemini3.8 model at this check. A different model's local
tokenizer was not silently substituted. Per-request provider counting still works
as recorded in the model-runner report, but this does not guarantee availability
or hard deadlines for large-file tokenization. Account billing for count/file
operations remains unmeasured; no monetary saving is asserted.

Raw attempts, checksum tests and reproducibility scripts are in
[goal-corpus-token-evidence](goal-corpus-token-evidence/). These observations do not
justify removing the practical plaintext baseline or claiming graph benefit.
