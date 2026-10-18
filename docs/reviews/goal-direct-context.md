# Compact direct-context development preparation

On 2026-10-18 a direct-context renderer was added so baseline preparation does
not depend only on the verbose corpus-storage JSONL. **T0, T6 and T10 remain
IN_PROGRESS.** This is corpus preparation and token measurement, not a completed
answer baseline, a frozen evaluation plan, a quality score or a graph advantage.

`evals/confirmatory/direct_context.py` presents each source blob, raw commit/tag
object and ref once. It replaces repeated flattened path lists with deduplicated
immediate Git trees. Following those trees recovers the same historical paths,
modes and object IDs; the original include/exclude rules retain their meaning.
Payloads use explicit UTF-8 byte lengths, preserving physical lines, empty files,
CRLF, control characters and JSON-looking repository content. Non-UTF8 objects
remain base64 with an explicit encoding. No expected answer, task-dependent
selection, inferred dependency or executable repository code is introduced.

Three tests passed. An independent test reader reconstructs every rendered
synthetic Git object and compares it with `git cat-file`, expands every historical
tree and compares memberships, checks shared-subtree deduplication, excluded
content/symlinks, deterministic bytes, new-only output, retained byte-limit failure
and sealed-path rejection. These tests are not independent reviewer sign-off.

| Full development corpus | Compact bytes | Provider token count | Actual attempt |
|---|---:|---:|---|
| ItsDangerous, 607 commits / 310 included unique blobs | 4,136,716 | **1,610,496** | Entire text in one user part; HTTP200; 6.220 s |
| Requests, 6,372 commits / 3,300 included unique blobs | 65,272,715 | **23,642,469** | Text file input; exact uploaded hash/size verified; 75.254 s including upload/count/delete |

Both used `models/gemini-3.8-flash:countTokens` with the complete request, without
chunk summation or byte/token estimates. Requests upload deletion returned HTTP200.
The actual counting interface follows the official
[token API](https://ai.google.dev/api/tokens) and
[file-input API](https://ai.google.dev/gemini-api/docs/files). These totals exclude
the eventual final-answer instructions and output/tool reserves; the plan still
must freeze those and confirm model/context eligibility. Neither representation
is asserted to be a mathematically minimal encoding. Direct context must remain
an applicable comparator on smaller slices where it fits, alongside practical
search at every size. The final Requests/Click plan remains unsigned; no Click
source or held-out question was opened.

The compact hashes are:

- ItsDangerous: `539ff93ee544579bae645e74c71a801e4f84f30bc74b8bd62d742097f6447614`.
- Requests: `eee4135e12cd8a3ddfdbd76ec75709ddf4d02c093f7b2d09786a177bf77e05c8`.

The original failed uploads/tokenization attempts and earlier 2,851,850-token
ItsDangerous JSONL measurement remain in the
[historical token-count report](goal-corpus-token-counts.md). The successful
Requests compact count does not turn its earlier JSONL timeout into a success.
Exact receipts, counting scripts/responses and compressed byte-identical compact
contexts are in [goal-citation-integrity-evidence](goal-citation-integrity-evidence/).
No generated direct-context answer or comparative cost saving is asserted.
