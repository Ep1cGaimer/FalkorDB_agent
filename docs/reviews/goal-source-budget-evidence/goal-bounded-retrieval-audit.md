# Independent bounded-retrieval audit — 2026-10-18

**T5 remains incomplete.** This initial audit found that a one-byte source limit consumed **159,984 bytes** before returning an explicit incomplete result. That historical hard-bound failure and all original traces are preserved. A subsequent parent-agent repair was independently validated against the **199-file candidate pin**, with **8/8 narrow checks passing** and zero blob payload bytes read into the query for the same oversized source: see the [source-preflight revalidation](goal-bounded-retrieval-source-revalidation.md). The original 198-file pin is historical, and the earlier 38 distinct successful probes were not rerun against the repaired candidate. No production files were changed by this audit agent.

The audit uses newly generated, public synthetic Git repositories and the real production importer/query path against disposable FalkorDB containers. It performs no provider calls and reads no sealed tasks, held-out questions/oracles, Click sources, or model outputs. The local token probe supplies a numeric fake count only and forbids generation; it is a component check, not provider validation.

| T5 clause | Controlled coverage | Result / limit |
| --- | --- | --- |
| Row boundaries and exact union | 0, 1, 9, 10, 11, 35 logical symbols at page limit 10; repeated execution compares complete results and citations | Pass: deterministic order, no duplicates/missing results, empty result, final-page evidence |
| Hop boundaries, cycles and fan-out | Forward/reverse independent BFS at depths 1–5; invalid 0/6; cycle, diamond, depth-six chain, leaves | Pass for requested bounded scope; no unbounded-closure claim |
| High fan-out / page cap | 205 independently listed edges at production maximum page limit 200 | Pass: 200+5 pages, final edge present, investigation exposes truncation |
| Long history and repeated names | 35 Git commits independently checked with `rev-list` and `ls-tree`, four revision pages; same function leaf name in two modules | Pass for this controlled size |
| Cursor binding | Malformed, negative/mismatched scope, past-end, cross-query, cross-revision, cross-repository, cross-graph, expired publication generation | Pass: explicit ValueError or INVALID_CURSOR; update requires restart |
| Production walk edge cap | 9,999 / 10,000 / 10,001 independently generated import edges, actual cap 10,000 | First and constructed terminal-offset pages match the independent expected slices. Over-cap graph retains `frontier_truncated` and TRUNCATED gap, including terminal page. Full union at this size was not completed. |
| Row / source / time exhaustion | One row, one source byte, and an already-expired 1ns deadline; direct pages plus deterministic investigations | Visible partial result; no answer, findings, or facts survive. Source byte hard bound **fails**. The tiny deadline is an exhaustion probe, not a hard scheduling guarantee. |
| Token exhaustion | Local counter-only meter preflight reports 11 tokens against input limit 10 | Component probe only; no real provider token measurement or model-answer completeness claim |

Terminal `Page.truncated=False` means there is no further **page**, while `coverage.frontier_truncated=True` plus a TRUNCATED gap identifies omitted walk edges. This is the documented paging contract in `tests/repo/test_s4_scale.py`; it is not counted as a false-complete answer. The broader requirement that all configured resources be hard bounded remains unfulfilled because of the source-byte failure.

Artifacts are under [`artifacts/goal-bounded-retrieval-audit`](../../artifacts/goal-bounded-retrieval-audit/). The initial run has 34/34 passing narrow cases in `cases.json` and `summary.json`, with exact independent expected state in `expected-state.json`, all parameterized query/page/cursor traces in `traces.json`, exact subprocesses in `commands.json`, and source/test/manifest hashes before and after. These hash checks open only implementation files and existing public tests; they do not independently rehash the manifest's held-out data entries. The pinned implementation manifest itself is unchanged.

Attempt ledger (all attempts retained):

1. Initial run: `run_audit.py`, `run-001.log`, root-level JSON evidence. 34 passing cases; production-cap and token limits explicitly excluded at that stage.
2. `run-002`: three production-cap first-page cases pass; strict source-byte hard-bound case fails; token case fails because the audit harness pre-created a directory that `Journal` owns. That harness failure is preserved, not treated as a product token failure.
3. `run-003`: full production-cap page-union attempt interrupted explicitly by the auditor with SIGINT because projected runtime exceeded the narrow audit slot. Partial compressed raw traces, exit 130, reason, source snapshots, and successful container cleanup remain. Its empty per-case ledger is not a completed success run.
4. `run-004`: **4 pass / 1 product failure in 21.91s**. Corrected local token harness, production-cap first/terminal-page probes, and the preserved strict source-byte failure. See its final `cases.json` and `summary.json`. `terminal-metadata-clarification.json` preserves a harmless audit detail-label error: raw `final_page_truncated` copied the first-page flag, although terminal assertions and raw page traces correctly record `False`; `union_returned=200` denotes the first-page sample. The reusable harness now labels these fields correctly. No raw attempt was rewritten.

The production-cap terminal page uses a deliberately constructed valid offset in the returned cursor scope. It tests terminal-page handling without pretending the preceding production-sized pages were all enumerated. The initial smaller controlled graphs do enumerate every continuation page. The 10,001-edge controlled graph has exactly one independently known omitted edge, visibly reported; no exact full-graph union claim is made.

Reproduce from this checkout using an unused output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/rw-mcp-compat/bin/python artifacts/goal-bounded-retrieval-audit/run_extended.py --output artifacts/goal-bounded-retrieval-audit/reproduction-001
```

`run_audit.py` is the exact initial harness and expects a fresh artifact directory for its fixed synthetic repository paths. The extended harness rejects an existing output directory and supports `--full-union` for the longer optional attempt. Executed harness snapshots for the extended attempts are saved inside each run; their original location is `artifacts/goal-bounded-retrieval-audit/run_extended.py`.

Every attempt uses image `falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`, two container CPUs, 1GiB container memory, and Docker-assigned loopback ports. Configuration, interpreter/host details (`hardware.json`), exact Docker inspection, final resource snapshot, commands, and cleanup are recorded. No user/demo database or host port 6379/6382 was used. No Git commit or push was made. The audit source freeze was released at **13:23:09 UTC / 18:53:09 IST**, after the run-004 after-source snapshot; subsequent parent-agent fixes are outside this audit's frozen-source claims.

Remaining evidence gaps: strict source-byte enforcement; completed production-cap unions; real provider token/time-budget behavior and answer-level omitted-evidence conclusions beyond these deterministic routes; stronger real-scale coverage. These are deliberately not converted into a full T5 pass.
