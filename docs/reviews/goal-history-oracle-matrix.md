# Independent additional T3 DAG matrix — 2026-10-18

This separate follow-up recorded **101 passes and 4 raw mismatches in 105 assertions**, with no execution error. It leaves the [100-seed batch](goal-history-oracle.md) unchanged. **Full T3 remains unvalidated.** Three mismatches are conservative `UNCERTAIN` answers where the independently specified exact-line oracle expected `ABSENT`; the fourth is a tag-name/full-SHA normalization defect in this reviewer's harness. All four original failures remain in [results.json](../../artifacts/goal-history-oracle-matrix/results.json).

The independently authored [predeclaration](../../artifacts/goal-history-oracle-matrix/predeclared.json) and [complete expected state](../../artifacts/goal-history-oracle-matrix/expected-state.json) were written before production indexing. [run_matrix.py](../../artifacts/goal-history-oracle-matrix/run_matrix.py) generates one 14-revision DAG with complete expected file bytes and ordered parent lists. Git plumbing checks tree paths, file bytes and direct parents; production checks compare graph file hashes and parents to those expectations. No product source, tests, evaluation implementation or frozen plan was changed, and no model or held-out material was used.

| Case | Oracle fix state | Observed fix state |
|---|---|---|
| Initial state | ABSENT | ABSENT |
| Two-line fix | PRESENT | PRESENT |
| Partial revert of one required line | ABSENT | ABSENT |
| Restore complete fix | PRESENT | PRESENT |
| Feature edit replaces one required line | ABSENT | UNCERTAIN |
| Divergent main edit replaces one required line | ABSENT | UNCERTAIN |
| Explicit conflict resolution, two ordered parents | ABSENT | UNCERTAIN |
| Unrelated cherry-pick precursor | ABSENT | ABSENT |
| Exact cherry-pick onto different ancestry | PRESENT | PRESENT, EQUIVALENT_BY_PATCH |
| Similar nonidentical backport | UNCERTAIN | UNCERTAIN, BACKPORT_EQUIVALENCE_UNKNOWN |
| Rename with an added comment | PRESENT | PRESENT |
| Copy with reused function names at two paths | PRESENT | PRESENT |
| Delete Python paths | ABSENT | ABSENT |
| Recreate original path with pre-fix content | ABSENT | ABSENT |

The real Git merge first failed with the independently expected conflict, then the generator explicitly wrote the resolution and committed its two expected parents. Git independently recognizes the rename with edits as `R074 a.py renamed.py`; [the receipt](../../artifacts/goal-history-oracle-matrix/route-parity-and-rename-evidence.json) preserves the command and output. The copy check concerns file/current-fix evidence at both paths; it does not establish general semantic identity across copies. Missing revisions and the missing fix commit in a depth-one clone returned `UNCERTAIN` with `UNKNOWN_REVISION`. A real detached-HEAD checkout resolved to the recorded fix SHA. The shallow import's receipt does not advertise a general missing-history coverage gap, so this experiment establishes the missing-fix query outcome only.

At every recorded revision the harness also asked the production investigation routes **“When did a.parse appear”** and **“Is fix SHA present”**, retaining their findings, citations, gaps and raw graph traces. The product explicitly labels introduction history as **sampled tagged ancestors plus the requested revision** in all 14 cases. This is not an exhaustive introduction search. A separate [identity-only replay](../../artifacts/goal-history-oracle-matrix/normalized-introduction-replay.json) resolves each returned first-present tag/SHA using Git: **14/14 identify the expected base commit**. The base case originally expected literal `t00-base`, while the product returned its correct equivalent full SHA; that one raw failure is a harness representation defect. The replay does not erase or replace it. A separate recorded parity check found **14/14 current-presence investigation states equal their direct `fix_status` results**; it does not turn the three oracle mismatches into passes.

The three content mismatches all preserve uncertainty after changed lines, with zero false `PRESENT`. This is a conservative limitation under this declared exact-current-text oracle, rather than evidence of a false fix-presence claim. The original oracle expected full-fix absence whenever a required added line had been removed; those expectations were not relaxed after observing results. [reduce_uncertainty.py](../../artifacts/goal-history-oracle-matrix/reduce_uncertainty.py) reproduces the same mismatch in a reduced **three-commit, one-file, one-function history**: base `return 'base-a'` → fix `return 'fixed-a'` → overwrite `return 'feature-a'`. The [reduced oracle and actual answer](../../artifacts/goal-history-oracle-matrix/reduced-results.json) retain the expected `ABSENT` and actual `UNCERTAIN` plus its `CHANGE_IDENTITY_UNKNOWN` evidence. No implementation repair was attempted.

The matrix completed in **3.514 seconds**; the separate reduction also ran successfully. It is functional synthetic evidence, not a performance or scale result. All **40** production `src/` file hashes matched [before](../../artifacts/goal-history-oracle-matrix/source-before.json) and [after](../../artifacts/goal-history-oracle-matrix/source-after.json). All **198** frozen implementation files matched the parent's implementation pin in [the final independent check](../../artifacts/goal-history-oracle-matrix/full198-pin-after.json).

Owned container `rw-history-matrix-20261018`, ID `6376f0cdde53311deeb2ca04c355160cec301206d18e38c26837e956fb2ef1a4`, used random loopback port **57955** and pinned image `falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`. Neither host 6379 nor 6382 was used. After the matrix and reduction, `GRAPH.LIST` returned `[]`; only this container was stopped and removed. Inspect confirmed its absence at **13:09:00 UTC / 18:39:00 IST**. [Cleanup receipt](../../artifacts/goal-history-oracle-matrix/cleanup.json), [all generator Git commands](../../artifacts/goal-history-oracle-matrix/git-commands.jsonl), [Git repositories archive](../../artifacts/goal-history-oracle-matrix/repositories.tar.gz).

Reproduce in a fresh pinned checkout with no existing generated matrix repositories by launching the declared owned image on port 57955, then running `PYTHONPATH=src /tmp/rw-mcp-compat/bin/python artifacts/goal-history-oracle-matrix/run_matrix.py` and the corresponding reduction script. Port 57955 is hardcoded in these archived scripts and must be reserved or changed explicitly for a new run; no host service on 6379/6382 is needed. The original matrix expected values and all failures must be retained when reproducing. The interpreter/dependency environment is the same one recorded for the 100-seed batch.

Remaining limits include strict oracle disagreement, sampled introduction history, broader rename/copy/backport ambiguity, larger/different generated DAG families, missing-history cases beyond one shallow boundary, real-repository held-out T2 results, and independent clean-environment reproduction. These two synthetic runs cannot validate full T3 or any S/E gate whose traceability requires other tests.
