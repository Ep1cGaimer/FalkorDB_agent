# Source freshness and transport repair evidence

This second development batch is based on remote `origin/goal` commit
`d7cf693e26073c825f0b6a2bd741ce5d05752f72`, following the
[first repair batch](goal-branch-remediation.md). All S/E/T requirements remain
**IN_PROGRESS**. These results establish the tested repairs, not acceptance or
comparative advantage.

Indexed citations now verify immutable Git tree membership, regular-file mode,
blob bytes, source span hashes and current extraction identity. Graph and source
caches last one public query operation, so deleting an edge affects the next read
on the same query object. Missing source, stale blobs and stale relationships
produce explicit gaps and withhold unsupported findings. This closes a reproduced
case where a failed dependency retrieval became a definitive empty finding.

Configuration paths resolve relative to their configuration file. CLI, TCP API
and actual MCP stdio use the same selected repository and canonical missing-index
errors. Database endpoint environment variables now select the actual connection.
Existing Requests and ItsDangerous trials are labeled development data; repaired
code cannot inherit the old unseen-repository claim.

The frozen 163-file source manifest had **zero mismatches** after validation:

| Check | Observed result | Scope |
|---|---|---|
| Python suite, real-repository markers enabled | 1,046 passed, 5 skipped, 3 deselected; 332.13 s | Includes both real onboarding trials and Requests history smoke; excludes live provider calls |
| JavaScript | 16 passed | Existing UI contracts |
| Deterministic fixture smoke | 8 PASS lines, cleanup confirmed | Real graph/probes/approval/simulation, fixed labeled grounding |
| Actual CLI/API/MCP comparison | 23/23 exact semantic matches | Selection/parallel requests, restart, incomplete publication, stale evidence, database stop/restart |
| Malformed transport input | 2 cases rejected | Empty and oversized questions |
| Real graph contribution | Requests: 4 edges through 3 hops; ItsDangerous: 7 edges through 2 hops | Inspected development selectors; query and source traces retained |

The diagnostic API used `http://127.0.0.1:63036` and stopped after the run. Its
separate, owned Docker database was removed. Existing database services were left
running. The database restart changed its server run ID; positive cited findings
returned after restart. Per-repository edge removal, stale extraction and a
labeled transport-failure injection after three actual reads all passed the
diagnostic expectations. None used model-generated answers or blinded scoring.

The five skipped Python cases require missing E2/E4 outputs, scale samples, or
benefit samples. Three live-provider cases were deselected. Real onboarding times
are diagnostics from concurrent local activity, not controlled cold benchmarks.
All three probe attempts, initial failures and corrected regressions are retained;
overlapping runs are not summed as distinct tests.

Evidence: [run summary](goal-freshness-evidence/run-summary.json),
[JUnit report](goal-freshness-evidence/final-tests.xml),
[probe summary](goal-freshness-evidence/probe-summary.json),
[raw probe attempts](goal-freshness-evidence/raw-probe-attempts.tar.gz),
[source manifest](goal-freshness-evidence/implementation-manifest.json),
[environment](goal-freshness-evidence/environment.json), and
[bundle hashes](goal-freshness-evidence/bundle-manifest.json).

A separate AI evaluator is preparing a fresh protocol and source/Git-derived
sealed expectations for Requests and Click. Its draft is explicitly unsigned and
incomplete. The implementer has not inspected Click source or sealed answers.
Model/prompt/tokenizer/baseline verification, final source freeze, independent
scoring, controlled scale measurements and clean reproduction remain required.
