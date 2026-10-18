# Common-corpus graph arm and parameterized-base origins

Development work on 2026-10-18. **T0–T11 remain IN_PROGRESS.** These are real graph
and source-integrity diagnostics, not held-out answer scores or a comparison win.
The frozen-plan signature, corpus token total, independent scoring, controlled
scale study and complete submission evidence remain required.

## Identical raw evidence before comparison

`evals/confirmatory/graph_tools.py` adds graph-backed definitions, forward/reverse
dependencies, changes, release notes and fix-state tools to the same nine raw
source/history tools available to the plaintext baseline. Both arms receive the
same corpus hash/spec context, answer instruction and cumulative model/tool
budgets. No import, mutation, shell, checkout or arbitrary network capability is
exposed to the model. The new CLI accepts an explicit existing `--graph` for the
graph arm and runs a readiness check before generation.

Readiness compares every published commit, included historical file binding, Git
blob/SHA256 identity and ordered parent edge against the export. Extra or missing
source/ancestry rejects the arm. Each returned citation is also checked against
the common raw corpus. This attests membership/provenance, not extraction semantics
or answer correctness. Raw graph query parameters, rows, timings and publication
identity are retained in an audit artifact, separate from model context.

Each graph-arm operation checks the pinned COMPLETE publication before and after
the read. This includes calls to the shared raw source tools. An unavailable,
incomplete or changed graph returns a fatal arm status; the runner retains the
failure and cannot silently finish as a plaintext fallback. Internal graph rows
are counted cumulatively across graph and raw operations. Exhausted row/source/
deadline budgets produce an incomplete result, with evidence withheld.

Readiness and tool traces are written before final-answer generation; failure
traces are retained even if readiness or retrieval fails. Provider tokens remain
measured by the model meter, separately from graph rows and source/output bytes.

## Configuration mismatch repaired

Two new regressions failed because existing importer globs can match a basename:
an include for root `setup.py` also admits `nested/setup.py`. The export uses full
repository-relative paths, so using those configurations unchanged would give the
graph extra source. The importer now has an explicit `path_matching` profile and
`regular_files_only` option. Their values participate in the configuration
fingerprint so a normal retry rebuilds changed file maps. Existing default
basename behavior is preserved. The export-derived configuration uses exact paths
and regular files and limits tags to those eligible in the export.

The [configuration reference](../../repos/PATH_MATCHING.md) records the semantics
and exclusions. It is separate from the older independently hashed README. A
temporary edit of that README correctly failed the draft public checker; its
original dependency bytes were restored and the new documentation moved to the
separate reference. The checker passes again; draft plan/task/oracle files were
not changed, and no signature or validated gate was created.

One intermediate migration test read a private `_files` cache immediately after
reimport instead of using public revision resolution. Its failure is retained;
the regression now exercises public generation refresh before checking the
updated membership. It does not change the expected strict-path result.

## Parameterized bases were missing

The first ItsDangerous diagnostic matched the complete corpus, then failed its
selected second-hop assertion. Source inspection showed that bases expressed as
`Serializer[str]` were skipped by the extractor. Three synthetic regressions
reproduced the missing edge, missing second hop and undeclared limitation.

Python adapter version **3** now extracts the syntactic origin of a subscripted
base and marks it `provenance='inferred'`. Plain bases remain parsed. This is a
static origin relation; runtime `__class_getitem__`, inheritance and MRO are not
evaluated or proved. Base factories and other unresolved expressions remain
unsupported and are declared in adapter limits. The canary test verifies that a
`__class_getitem__` body with a filesystem effect is never executed. The adapter
version change invalidates earlier extraction for normal retry/reindex.

## Observed development results

| Check | Outcome |
|---|---|
| Initial strict-path regressions | 2 failed before implementation |
| Initial parameterized-base regressions | 3 failed before implementation |
| Graph/corpus/path/source-line/generic-base subset after repairs | 20 passed |
| Corpus/model/runner/scoring unit suite | 93 passed, no model or database calls |
| Broader repository suite before the later generic-base repair | 249 passed, 8 skipped; historical for adapter v3 |
| Final Requests development graph diagnostic | PASS |
| Initial ItsDangerous graph diagnostic | ERROR at second-hop assertion; retained |
| Repeated ItsDangerous graph diagnostic after adapter repair | PASS |

The final Requests diagnostic checked **6,372 commits, 106,594 historical source
memberships and 7,973 ordered parent edges**. The repeated ItsDangerous diagnostic
checked **607 commits, 5,698 memberships and 813 parent edges**. Both returned
actual hop-2 relationships, verified source spans/hashes through the common raw
tools, then stopped their own database and observed `UNAVAILABLE` on the next
graph-arm raw read. The in-memory plaintext export remained readable, so this
also exercises prevention of silent fallback.

Requests import/attestation took 32.414/2.388 seconds; ItsDangerous took
2.261/0.048 seconds. These single development trials are not cold-controlled T6
measurements. There were no live model calls or answer scores in these graph
diagnostics. Synthetic edge removal separately changed the next graph result
without changing the raw source. Missing edges still do not prove absence.

Owned probe containers were removed. The database service on host port6379,
issue22 service and other unrelated containers were untouched. Both real
repositories are inspected development data; the independent Click holdout remains
unused by implementation and product execution.

The [evidence directory](goal-graph-arm-evidence/) contains all attempts, raw query
archives, source/config manifests, failed assertions and successful reports. The
subsequent [full parent QA](goal-current-source-qa.md) passed1,172 tests with six
skips and three live exclusions, with both real-repository flags enabled. It ran
inside its own database network namespace so hardcoded test port6379 could not
reach the existing host service. That development result is not independent T11
reproduction or a full acceptance-gate pass.
