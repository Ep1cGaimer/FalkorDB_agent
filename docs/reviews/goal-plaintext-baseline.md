# Source-only corpus and practical plaintext baseline

Development work on 2026-10-18. **T0/T2/T5/T6/T10 remain IN_PROGRESS.** No held-out
answers, Click source, scoring oracles or provider generation informed this batch.
The canceled handoff draft remains uncommitted and is not the status authority.

`evals/confirmatory/corpus_export.py` serializes immutable Git roots and their
complete ancestor commit objects, historical tree/path/mode memberships, included
unique blobs and eligible ref/tag objects. It retains explicit content exclusions,
symlink and submodule gaps. Source is never checked out, imported or executed.
The plaintext loader verifies object digests and reconstructs raw nested tree
hashes, including empty directories, before using this data.

The development Requests export002 contains 6,372 commits, 5,438 distinct trees,
3,300 included unique blobs and 48,951,611 raw included blob bytes. Its serialized
151,612,580-byte corpus hash is
`0a276e3e6134389c0d7b97a559c6db93f918eeb0d200fee79e6fd1a0db36420c`.
These are actual bytes/object counts, **not model-token counts**. Exact tokenizer
measurement and beyond-context validation remain pending. Earlier export001 and
its smoke predate explicit directory metadata; they are retained separately.

`plaintext_tools.py` supports literal source search, follow-up line reads,
file discovery, commit/history search, ancestry and exact-revision text diffs.
Ref discovery and inspection preserve nested annotated tag evidence. It reads
only the explicitly supplied export and offers no shell, checkout, arbitrary
filesystem or network tool. Search absence is scoped to included decoded text;
ancestry does not establish current fix presence.

An independent AI reviewer found five reproducible defects/readiness gaps in the
initial implementation. Its original
[review and synthetic probes](goal-independent-infrastructure-review/20261018T101725Z/README.md)
are preserved unchanged. New regressions reproduced all five before repairs:

| Finding | Repair / observed check |
|---|---|
| Unicode separators shifted source line citations | LF-only physical source lines preserve Unicode/control content and CRLF bytes; original failure now passes. |
| Non-UTF8 commit search searched base64 text | Decode raw Git objects using their declared text encoding; unsupported decoding exposes a coverage gap rather than a complete empty search. |
| Annotated tag evidence unavailable | Validate nested tag object/target chains; expose list/search/show ref operations with raw objects, identity and decoded messages. |
| No-final-newline diff produced `-a+b` | Explicit missing-newline markers; the regression checks that actual `git apply --numstat` accepts the patch. |
| One row could return 300,002 bytes | Shared question-level tool budget counts output bytes, scanned source bytes, work units, calls and elapsed time; oversized evidence is withheld with a visible incomplete envelope. Full model-token enforcement remains pending. |

`tool_budget.py` can wrap either arm through an explicit capability map. A session
spans model turns and retains every attempted operation, including malformed
calls, exceptions and exhaustion. Nested calls count tool output once; separate
request contexts do not share usage. Limits default to 120 seconds, 30 calls,
64 MiB scanned source, 1,000,000 work units and 98,304 serialized output bytes.
These are proposed development limits, not a signed final resource contract.
ASCII JSON escaping is included in the measured output serialization.

Deadlines are cooperative and do not preempt a running Python/native operation.
The export loader's memory/startup cost is separate from tool-query work. Search
and diff still materialize intermediate data and require measured resource checks.
No hard OS memory/wall-time bound, exact provider-token accounting, complete model
runner, frozen prompts, pilot power analysis, baseline parity or T10 win is claimed.
The fifth finding is therefore **partially addressed**, not an accepted gate pass.

Observed development checks:

- Initial exporter run: 10 passed, one macOS invalid-filename fixture setup failure;
  rewritten to construct the same non-UTF8 path through Git objects, then 11 passed.
- Initial corpus/baseline suite: 25 passed; independent review then found gaps
  outside those tests. Passing test counts did not establish complete correctness.
- Five review regressions before repair: **5 failed**.
- After repair and cumulative-budget regressions: **42 passed**.
- Corpus/baseline/budget plus existing evaluation/statistical integrity checks:
  **51 passed**, no model or database use in that run.

Raw JUnit reports, corpus receipts/spec, the earlier smoke and exact six-file
implementation snapshot are in [goal-baseline-evidence](goal-baseline-evidence/).
No sealed answer files, fresh Click content or credentials are included.
