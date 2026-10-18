# Physical source lines and reusable index metadata

Development repair on 2026-10-18, after the independent full run on `f8faa67`.
**Every acceptance gate remains IN_PROGRESS.** The older full run remains a
historical result on its exact source pin. This batch changes product source;
fresh held-out, full independent, scale and model evaluation are still required.

The independent plaintext review exposed a source-line convention defect. Checking
the same pattern in product ingestion and queries produced two actual failures:

- A Unicode U+2028 separator inside a valid Python string before a function shifted
  the text used for that function's indexed span hash. AST line numbers still
  referred to physical source lines, so the hash covered different text.
- A release-note bullet containing U+2028 was rewritten into two lines; its
  citation ended at line 6 of a five-line source file.

`rw.repo.source.source_lines` now defines LF-delimited physical source lines,
removes CR only as part of CRLF line endings, and retains Unicode/control content.
Ingestion span hashes, query verification, file/release-note spans, fix checks,
patch parsing and development citation line-count validation use that convention.
Full-file hashes still use unchanged raw Git bytes.

Blob reuse now requires `line_schema='physical-lf-v1'` as well as the existing
extractor identity. The index configuration fingerprint advances to schema 3.
A normal import retry reextracts legacy metadata; no manual graph repair is
needed. The completion marker and new line schema are published together after
symbol/relationship persistence. Interrupted destructive writes still clear the
extractor completion marker first. The migration regression injects an old span
hash with a valid old completion marker, verifies stale-source rejection, retries
the normal importer, checks repaired metadata, and verifies unchanged blobs are
reused on the next import.

Observed checks, using a newly owned disposable FalkorDB container each time:

| Run | Outcome |
|---|---|
| Original three graph-backed regressions | **2 failed, 1 passed** |
| Same three after repair | **3 passed** |
| Repository suite including migration and source-line contract | **237 passed, 8 skipped**, 72.86 s |

The eight skips are retained in the
[run summary](goal-physical-lines-evidence/run-summary.json). Real-repository flags
were not enabled in this run; missing acceptance/measurement artifacts remain
missing. No live model or held-out question ran. The independent source-only
public package checker still passes, reports 120 cases and correctly reports
`frozen=false` and no passing gates.

Both original failures and successful runs, exact commands, owned-container
identities/ports, cleanup results, JUnit, a 176-file post-run source capture and
source archive are in [goal-physical-lines-evidence](goal-physical-lines-evidence/).
The archive permits replay of this development source; it is not a pre-result T0
signature. Owned containers were removed and shared services were untouched.
