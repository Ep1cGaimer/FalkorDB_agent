# Goal-branch remediation — in progress

Base: remote `origin/goal`, `d7cf693e26073c825f0b6a2bd741ce5d05752f72`.
Work branch: `fix/goal-acceptance`. Authority: the full 134-line `remquirements-v1.md`,
restored from the supplied local specification rather than the branch's 24-line summary.

## Implemented repairs

- Harden Git object reads against repository-configured signature programs, filesystem monitors,
  executable diff drivers, inherited Git routing, replacement objects and implicit lazy fetching.
  Repository programs remain source data. This is not a general operating-system sandbox.
- Serialize imports with a renewable Redis lease and atomically fence every database command with
  WATCH/EXEC. Queries reject unfinished publications, validate generation consistency and clear
  cached views on publication changes. A failed update is recovered by rerunning the same import;
  it does not serve a previous snapshot while shared facts might have changed. Operational lease
  expiry is 120 seconds; a separate process-crash test uses a two-second lease.
- Invalidate file maps when extraction configuration changes; replace moved/deleted tag aliases;
  preserve relative-import context across identical blobs and avoid treating identical non-source
  bytes as source. Preserve source parse gaps in retrieval and withhold definitive symbol absence
  when coverage cannot support it. Colliding qualified names require path clarification.
- Bind cursors to repository, graph, revision, query parameters and publication generation. Page
  release notes server-side, enumerate tag candidates, and page a single blob exceeding row caps.
- Check required deletions as well as additions when determining whether a fix remains present.
- Publish a typed MCP repository response schema.
- Remove oracle retrieval instructions/file selection from development evaluators; retain failed
  attempts in denominators; reject invalid citations and partial evidence as grounded passes;
  average repeated scores per question. Development history runners now use three repeats.
- Add a deterministic 10,000-resample paired, repository/stratum-stratified bootstrap implementation
  with the specified A/B numerical conditions and repository regression veto. Its tests use
  synthetic scores and establish arithmetic only, not observed retrieval advantage.
- Preserve historical declarations/results. The modified comparison runner labels its old rule
  separately and cannot release an acceptance claim. Source/configuration line endings are fixed
  for future byte-hash freezes; fixture bytes retain their binary checkout rules.

## Verification

These are first-batch historical results. The later
[source freshness and transport batch](goal-source-freshness.md) records the
subsequent source freeze and validation; it does not replace these attempts.

The original audit regressions first reproduced **13 failures** locally, including the tracked
signature-program canary. The first focused repaired run passed **30 tests**. The expanded recovery,
access and history subset passed **112 tests**. The independently supplied 100 seeded mini histories,
pagination cases and additional integrity/recovery tests passed **127 tests** before the final run.
These are overlapping development subsets and must not be summed as distinct cases.

Two interim complete runs were retained: **894 passed / 2 failed / 9 skipped / 6 deselected**
(the two failures were the overly broad documentation coverage signal), then
**908 passed / 1 failed / 9 skipped / 6 deselected** (test monkeypatch instance state leaked
across tests). The coverage distinction and test isolation were corrected. The final frozen-source combined run passed **1,029 tests**, with **9 skipped** and **6 deselected**,
zero failures/errors, in **183.10 seconds**. The nine skips are missing clone/evaluation artifacts;
the selected command excludes live-provider and real-repository markers. These omissions prevent
acceptance validation. The interim failures are retained.

JavaScript: `node --test tests/js/*.test.mjs` observed **16 passed, zero failed**.
The actual killed-process recovery test and stale-writer fencing test both passed. Twelve
re-extraction persistence checkpoints were fault-injected; this is one path through the required
T4 matrix. The standalone deterministic smoke observed **8/8 PASS** and graph cleanup.
No live provider calls or fresh scale benchmark have been made during this repair batch.

## Remaining acceptance work

Every gate remains IN_PROGRESS in `goal-acceptance-ledger.json`. Required remaining work includes:
a new independently signed frozen protocol and fresh unseen/held-out data; at least 120 real
questions with the specified strata/negative/complexity counts, three paired repeats and blind
independent scoring; the full adversarial/fault/resource/transport/security matrices; controlled
three-slice cold/warm/concurrency benchmarks; fresh query-to-answer ablations; actual fair comparison
scores and confidence intervals; independent clean reproduction, the 12-question live rerun,
three reset demos and the submission claim card. The new bootstrap library cannot substitute for
that experiment. Old core freeze hashes remain historical; editing them to bless current code
would not establish a new unseen trial.

The original archive is a standalone historical artifact: extract it into an audit directory to
read its `audit/` and `artifacts/` entries. The original review's separately generated link directory
is not needed to run the archived scripts. Copied regression tests disclose their audit origin;
the depth assertion explicitly excluded by the original reviewer was replaced with a check of
requested hop scope. Extractor-version monkeypatches target the class to avoid leaking instance
attributes across tests.

## Current batch artifacts and recovery

The [run summary](goal-repair-evidence/run-summary.json),
[JUnit report](goal-repair-evidence/final-tests.xml),
[command output](goal-repair-evidence/final-tests.log),
[smoke output](goal-repair-evidence/smoke.log),
[JavaScript output](goal-repair-evidence/javascript.log),
[environment](goal-repair-evidence/environment.json), and
[159-file implementation manifest](goal-repair-evidence/implementation-manifest.json)
are retained with SHA-256 hashes in the
[evidence file manifest](goal-repair-evidence/bundle-manifest.json). The implementation files
were rehashed after the run: no changes since the recorded source freeze.

After upgrading an existing index, re-run `scripts/repo_index.py --config <config.json>` once.
Legacy indexes without a current publication marker are rejected until reindexed. Failed imports
recover through the same command; no manual graph repair is required for the tested failures.
A process killed during import holds its renewable lease until expiry (120 seconds normally).
Read responses include `index_generation`; API revision lists expose coverage and continuation
through `GET /api/repos/{name}/revisions?limit=...&cursor=...`. A cursor from an old publication
is rejected and pagination must restart. Repository-code ingestion remains non-executing.
