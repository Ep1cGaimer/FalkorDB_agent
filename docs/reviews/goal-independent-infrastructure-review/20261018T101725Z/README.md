# Independent evaluation infrastructure review — incomplete baseline

Reviewed 2026-10-18 by the independent AI subagent. This is AI-authored review, not human sign-off. The standards and specification checks follow the code-review skill without delegation. The authoritative contract is `remquirements-v1.md`, particularly T0, T2, T5, T8, and T10. No applicable AGENTS.md or additional coding-standard document was found.

**Verdict:** the exporter and plaintext tools are useful development infrastructure; the baseline has five reproduced defects/readiness gaps to resolve before freezing or using it for a fair confirmatory comparison. No acceptance gate is validated by this review. No fixes were made.

## Scope and independence

Reviewed only the new `evals/confirmatory/corpus_export.py`, `evals/confirmatory/plaintext_tools.py`, `tests/test_confirmatory_corpus.py`, and `tests/test_confirmatory_plaintext.py`, plus the Git plumbing helper they import. The four exact source hashes are in `probe-results.json`. The parent repository HEAD at review start was `15a92f6e0f87324087463775e450c26f9962e5cd`; the four reviewed files were untracked, so their individual hashes identify the reviewed version.

The oracle-authoring phase was closed before this separate implementation/reproduction role. This review did not read sealed expectations, held-out questions, Click source, product answers, or scoring results, and did not run any held-out investigation. All new probes use a fresh, independently constructed synthetic Git repository. No repository code or hooks are executed by those probes. The earlier independent deterministic reproduction remains a separate result on commit `f8faa67f5b9c9d0d2682ecff7d10d3ac084cf242`.

## Findings

1. **P2 — Source lines split on Unicode/control separators, invalidating citations.** `plaintext_tools.py:187` and `:213` use `str.splitlines(keepends=True)`, which recognizes separators beyond Git/source LF lines. A valid Python source string containing U+2028 on physical line 1 causes a literal match on physical line 2 to be cited as line 3. `read_file(start=2,end=2)` returns the tail of physical line 1. The exact probe returned `right'\n` and reported three lines for a two-LF-line file. T2 requires citations to resolve to the actual source spans. Use one explicitly declared LF-based source line convention for reading, searching, and diff spans, preserving original bytes/CRLF; add Unicode/control-separator regression cases.

2. **P2 — Commit search silently searches base64 rather than the raw commit text.** `plaintext_tools.py:240–241` searches the serialized `content` field regardless of its encoding. An immutable commit with declared ISO-8859-1 encoding contains the ASCII subject `plain-ascii-subject`; the exporter correctly represents its non-UTF8 raw bytes as base64. `log(text='plain-ascii-subject')` returns zero matches with `complete=true`. Decode raw objects and apply a declared commit-text encoding/search policy, or visibly report an unsupported coverage gap. This must not silently become definitive absence.

3. **P2 — Annotated tag evidence is exported but unavailable to the baseline.** `plaintext_tools.py:97–98` reduces each ref to its target commit and drops its original OID and raw tag chain. The public tools provide no list/show/search operation for that metadata. The synthetic exported tag contains `ANNOTATED_TAG_ONLY_EVIDENCE`, but the loaded baseline cannot retrieve it through its tools. T10 requires the same raw source/history evidence across arms; graph tag messages must not be available only to one arm. Preserve validated raw tag records and expose bounded ref/tag discovery and inspection, including nested annotated tags and immutable object identity.

4. **P2 — Diff concatenation produces a malformed patch for files without a final newline.** `plaintext_tools.py:264–266` joins `difflib.unified_diff()` strings without adding explicit missing-newline markers. Changing a one-byte file from `a` to `b` yields the combined line `-a+b`. `git apply --numstat -` rejects the returned text with exit 128, `corrupt patch at <stdin>:4`. A reader cannot reliably distinguish removed and added lines. Return a valid unified patch with missing-newline markers, or a structured old/new line representation with exact spans and newline flags.

5. **P2 — Row/line limits do not enforce output-byte, token, or work budgets.** `plaintext_tools.py:182–218` limits source line count and result rows but leaves each line and `coverage_gaps` unbounded; `:238–266` likewise materializes full history matches and complete patches. The synthetic one-line read and `search(limit=1)` each returned **300,002 UTF8 bytes**. A row limit is not a token/byte limit. Search also scans and accumulates every result before pagination, and no deadline/work check is applied here. A shared runner could supply some enforcement later, but none is demonstrated in these files. Before T0 freeze, declare and enforce separate source/work/output/token/time units across all arms, return explicit partial coverage/cursors, and withhold conclusions requiring omitted evidence. This is a readiness defect, not a claim that a currently unimplemented runner has failed a measured gate.

## Positive checks and limits

The exporter requires immutable full commit roots, rejects shallow history, hashes raw commit/blob/tag objects, preserves ordered raw parents, retains historical membership including excluded paths, and labels symlink/submodule scope gaps without dereferencing them. The latest `-r -t` tree enumeration preserves empty directories; the loader reconstructs Git tree IDs and checks parsed commit metadata against the immutable raw objects. Included blobs shared with excluded paths remain available only through included memberships. Explicit output directories are new-only; failed exports retain a failure receipt. No question/oracle/provider-key input is used by the reviewed export path.

The reviewed tests cover these development properties, but do not cover the five probes above. This review does not constitute a filesystem/process/network audit, measured scale benchmark, or proof of all hostile Git configurations. Live provider setup, exact tokenizer accounting, shared budget enforcement, signed T0, held-out execution, blinded scoring, score recomputation, and T11 live demos remain pending. Do not use these findings to change sealed cases or expectations.

## Reproduction and artifacts

`probe.py` and `probe-results.json` are preserved here. Copy `probe.py` into a fresh temporary directory before running; it creates an isolated synthetic Git repository and source export alongside itself. It imports the explicitly named reviewed modules from this workspace. The command used was:

```text
/private/tmp/rw-independent-812ecf7-z_wmyild/venv/bin/python /private/tmp/rw-independent-infra-review-20261018/probe.py
```

The fresh host environment is Python 3.12.13 from the independent reproduction; no DB, network, model, or provider credentials are required by the probes. The first synthetic setup used default `git commit-tree`, which recoded the intentionally invalid message to UTF8; the probe's attempted base64 decode failed. That first repository/export is retained under the temporary run directory. The successful second setup explicitly declares ISO-8859-1 for that commit and reproduces all five observations. No infrastructure source was changed; all four hashes matched at probe completion. The command's successful JSON output is saved as `probe-results.json`; the failure and setup notes are retained in `attempts.json`.

Earlier deterministic reproduction bundle: `docs/reviews/goal-independent-reproduction/20261018T101141Z-f8faa67-z_wmyild/README.md` (1,068 Python passes, six skips, three live deselections; 16 JS passes; deterministic smoke pass). Those are development test results, not confirmatory acceptance.

## Handles and cleanup

No live independent command, background service, or model run remains. Both owned reproduction containers `rw-independent-z_wmyild-a2` and `rw-independent-z_wmyild-a2-python` were removed; a final `docker ps -a --filter name=rw-independent-z_wmyild` returned no matches. Shared services were not stopped or modified. The clean clone and environments remain at `/private/tmp/rw-independent-812ecf7-z_wmyild`; synthetic review data remain at `/private/tmp/rw-independent-infra-review-20261018`. No source or test fixes were made. The sealed oracle package was neither opened nor edited during this review.
