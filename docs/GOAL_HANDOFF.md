# Goal branch repair handoff

Updated 2026-10-18. The user requested this handoff before further implementation.
The objective remains active. **No S1–S6, E1–E5 or T0–T11 gate is validated.**

## Start here

1. Read the full [requirements](../remquirements-v1.md), then the T0–T11 table
   below and the [machine ledger](reviews/goal-acceptance-ledger.json). The original
   [audit](reviews/goal-branch-review.md) and
   [archive](reviews/goal-branch-evidence.tar.gz) describe the old remote source;
   current repairs and current evidence are separate.
2. Inspect `git status --short`, `git log -8 --oneline`, and the independent
   [reproduction report](reviews/goal-independent-reproduction/20261018T101141Z-f8faa67-z_wmyild/README.md).
   Required result: identify the current checkout and distinguish the tested
   product source from the newer, incomplete evaluation tooling.
3. Read the independent infrastructure review under
   `docs/reviews/goal-corpus-infrastructure-review/` before using the draft
   plaintext baseline. Its counterexamples are the next repair work, not passing
   acceptance evidence. Reproduce them on development data and retain the failures.
4. Keep the source-only evaluation isolation described below. Finalize and
   independently sign T0 before generating confirmatory answers. Completion means
   every mandatory clause and threshold passes with exact evidence, not merely a
   green unit suite. Keep the goal active until that audit succeeds.

User objective: implement all changes required by the supplied review and full
requirements in a grounded way, toward a useful hackathon product, without
inventing or biasing evidence. A judging outcome cannot be guaranteed.

## Branch and evidence versions

- Local branch: `fix/goal-acceptance`; based on remote `origin/goal` at
  `d7cf693e26073c825f0b6a2bd741ce5d05752f72`. Nothing has been pushed.
- The authoritative requirements file has 134 lines and SHA256
  `a177653c4096f885cad1e129f77331cffe59fe13f608bac924232e632c1dd627`.
  The original remote's shortened requirements were replaced with this full copy.
- `8058032fd4724da4a9471909f92e597795112fe8`: main integrity, extraction,
  retrieval, publication, ingestion and evaluation repairs; full parent run
  1,059 passed, 5 skipped, 3 live deselected.
- `812ecf7e2153d7662f6523a80365b0622cf92ceb`: plaintext fixture control accepts
  declared nondefault boolean flags under the same rules as the product.
- **`f8faa67f5b9c9d0d2682ecff7d10d3ac084cf242` is the latest product source pin:**
  ignore local Git graft overlays and refresh imported parent facts on retry.
- `7561306` and `520e8fa`: independent clean reproduction documentation and all
  curated raw files. The latter explicitly includes nested `artifacts/` files
  otherwise excluded by the generic Git ignore rule.
- The new `evals/confirmatory/corpus_export.py`, `plaintext_tools.py` and their
  two tests are **draft evaluation infrastructure**, outside the independently
  reproduced 168-file pin. They have known defects listed below.

## Latest completed tests

Independent AI subagent `/root/independent_evaluation` used a clean clone of
`f8faa67`, fresh Linux/aarch64 Python 3.12.9, exact resolved dependency pins and
its own FalkorDB container. Both real-repository flags were enabled.

| Check | Observed outcome | Evidence |
|---|---|---|
| Full independent non-live Python suite | **1,068 passed, 0 failed, 6 skipped; 3 live deselected**, 277.87 s | [JUnit](reviews/goal-independent-reproduction/20261018T101141Z-f8faa67-z_wmyild/artifacts/pytest.xml) |
| Independent JavaScript | **16 passed**, no failures/skips | Same reproduction bundle |
| Independent deterministic fixture smoke | Passed | Same reproduction bundle |
| Source hashes | **168/168 before and after**, no tracked edits | Same reproduction bundle |
| Requests/ItsDangerous onboarding and Requests bounded history | All three real-repository cases passed | [report.json](reviews/goal-independent-reproduction/20261018T101141Z-f8faa67-z_wmyild/report.json) |
| Latest product affected subset | **37 passed** on `f8faa67` | [graft report](reviews/goal-git-grafts.md) |
| Real CLI/TCP API/stdio MCP diagnostics | **27/27 semantic matches**, plus two malformed-input cases, on earlier product source | [budget report](reviews/goal-query-budgets.md) |
| Draft corpus/baseline tests | **25 passed**; independently found counterexamples remain outside those tests | Corpus tooling evidence accompanying this handoff |

The six clean-run skips are missing E2 history outputs, E2/E4 quality/comparison
outputs, E3 scale output, scale and benefit run categories, and an empty historical
artifact parameter set. They are acceptance gaps, not waived requirements.
Artifact-parameterized checks affect test counts; 1,068 is not a question count or
an answer-accuracy measurement. No held-out product answers have been generated.

The first live fixture attempt on `8058032` had **2 passed, 1 failed**. The control
validator rejected a valid declared flag. Its failure was retained, the rule was
repaired, and a fresh control-only run on `812ecf7` passed **1/1**. These are separate
attempts/versions, not a single current three-case live pass. See the
[control report](reviews/goal-control-flags.md).

## T0–T11 progress and remaining acceptance work

Every row's machine status remains **IN_PROGRESS**. Passing subchecks below do not
constitute a full gate pass. The complete clauses and thresholds live in the spec.

| Gate | Completed evidence | Remaining work / failures |
|---|---|---|
| **T0: freeze protocol** | Independent source-derived 120-case draft, corpus/task/oracle hashes; model/tokenizer readiness metadata. | Exact final model/settings, prompt/tool hashes, comparable baselines, actual corpus tokens, power rationale, budgets, scorer/adjudicator identities, runner isolation and independent frozen-plan signature. Draft is unsigned. |
| **T1: configuration integration** | Development Requests/ItsDangerous imports; fixture eight cases; selection/isolation and deterministic suite pass. | Freeze final core then perform fresh configuration-only unseen Click import, before/after hashes, documented effort/coverage and complete applicable live integrations. A necessary core change consumes that unseen trial. |
| **T2: grounded answer quality** | 120 independently authored questions: 20 per category across two repos; 80 complex/cross-revision, 50 negative/ambiguous, eight evidence-N/A clarification cases. | No confirmatory generation/scoring. Run at least three paired repeats/arm, blind scoring, independent double scoring ≥25% plus all disputes/critical cases. Require overall ≥90%, each repo/stratum ≥85%, precision ≥95%, recall ≥90%, material citations 100%, critical errors zero every run. |
| **T3: history/identity** | 100 seeded histories, adversarial regressions, moved/deleted tag/import/fix-presence repairs, graft/parent-retry checks. | Complete independently specified DAG and invariant matrix; all Git-oracle expectations and real held-out T2 cases. Preserve uncertainty for unsupported identity/backport claims. |
| **T4: integrity/recovery** | Persistence/process interruption, retry, publication, stale evidence and real lease-race checks pass in tested cases. | All discovery/parsing/checkpoint/publication/random/DB fault boundaries, complete normalized full-versus-incremental entities/relations/provenance/coverage/answers, restart/concurrency and recovery timings. |
| **T5: bounded completeness** | Row/hop/cursor/page/freshness tests and shared deadline/row/source-byte exhaustion pass in development. | Every reader and final-page/boundary case, exact independent enumeration, model-token/resource enforcement. Python deadlines are cooperative; hard OS memory/wall limits are unproved. Draft plaintext tools still return oversized output (below). |
| **T6: measured scale** | Development imports/metrics and deterministic scale smoke. Deterministic source export exists. | Fresh three-slice benchmark: ≥3 cold imports and ≥3 updates per slice, ≥100 queries each/all strata, warmup/single/demo concurrency, disk/peak process+container memory, all failures/latencies/tokens/actual costs; frozen budgets, ≥99% on-time structurally valid responses plus T2/T5. Old bytes/4 is not token validation. |
| **T7: surfaces** | Actual CLI/API/MCP semantic parity, parallel requests, MCP restart, stale/incomplete evidence, budget and DB-stop/restart diagnostics. | Complete malformed/oversize, cancellation/timeout/retry/upstream failure/follow-up matrix; live grounded generated answers on all three surfaces, pinned identities and zero leakage. |
| **T8: execution boundaries** | Tested Git execution canaries and fixture receipt/disposition/approval/idempotence regressions pass. | Full malicious hook/script/filename/symlink/embedded-instruction matrix with process/filesystem/network audit; all stale/missing/conflicting identity receipt permutations. Runtime execution remains fixture-only. |
| **T9: graph causality** | Actual parameterized multi-hop traces on two development repos; tested edge/stale/interrupted/unavailable-service ablations. | Fresh frozen held-out query-to-answer traces, full required ablations, exact repository/revision/generation and extraction-versus-inference provenance on final source. |
| **T10: fair advantage** | 10,000-bootstrap/gate arithmetic tested on synthetic scores. Practical baseline under development. | No compliant real paired comparison or savings measured. Proposed **Gate B only**, still unfrozen: token ratio CI upper ≤0.80, answer/precision/recall difference CI lower ≥0, every applicable plaintext baseline, repo veto, T2 absolute gates and full costs/break-even. A tie/failure/inconclusive result remains unvalidated. |
| **T11: reproduction/demo** | Independent clean deterministic reproduction complete; all 103 handoff files verified against committed bytes; development archives exist. | Final unified frozen evidence bundle, independent score/CI recomputation, ≥12 stratified live held-out reruns, three consecutive reset demos within budget, claim card and identified event's current official deliverables. Event not yet identified; invent no event requirements. |

## Known unfixed draft baseline defects — next coding work

The independent reviewer reproduced these on synthetic development Git objects.
They were discovered after the 25 passing draft tests, so add red regressions first.
The review/probe artifacts under `reviews/goal-corpus-infrastructure-review/`
record exact source hashes and observations.

1. **Wrong source line numbers:** `str.splitlines()` treats U+2028 inside a valid
   Python string as a source newline. A search match on LF line 2 is cited as
   line 3, and reading line 2 returns part of line 1. Define physical LF source
   lines consistently with immutable Git bytes and citation validation.
2. **Commit message search misses non-UTF8 objects:** a raw ISO-8859-1 commit is
   preserved as base64, but `log()` searches its base64 representation rather than
   decoded message text. An ASCII subject can disappear with `complete=true`.
   Handle declared Git commit encoding and expose unsupported decoding honestly.
3. **Tag evidence is inaccessible:** exporter preserves annotated tag objects;
   loader retains only targets. Add bounded inspection/search for tag messages so
   the practical baseline can retrieve the same raw tag evidence as the graph arm.
4. **Malformed no-newline diff:** comparing files without terminal newlines can
   produce `-a+b` rather than a valid auditable patch. Preserve newline markers or
   another explicit exact-byte diff representation and test its interpretation.
5. **Row/line bounds do not bound returned bytes/tokens:** one read/search item
   can return 300,002 bytes. Add shared whole-question output-byte/token/deadline
   accounting, explicit continuation/gaps, failure retention and identical budget
   contracts across arms before freezing the comparison. Current standalone
   baseline has no model runner, full question budget, or frozen prompts.

Corpus export and source tools are new infrastructure, not the product entrypoint.
Avoid declaring all source citation paths repaired from a fix in this module alone;
check applicable graph/product/evaluator paths too. After a hold-out informs a fix,
it becomes development data for the next confirmatory claim.

## Source/oracle isolation

- Public draft package: [README](../evals/confirmatory/README.md),
  `package-manifest.draft-v2.json`, `plan.draft-v2.json`. Parent implementation has
  used development/synthetic cases, not the sealed expected answers or Click source.
- **Keep `artifacts/confirmatory/sealed/` closed to implementation, ingestion,
  retrieval and answer-generation roles.** Only the independently assigned scorer
  may consume sealed expectations after retrieval/answers are locked. This is a
  role boundary, not cryptographic isolation against the same user account.
- Fresh unseen clone: `artifacts/confirmatory/repos/click`. Only the independent
  evaluator inspected it to author source/Git expectations. Product onboarding and
  model evaluation have not started. Parent core repairs therefore did not consume
  a Click trial. Freeze final core first and preserve the independent author's seal.
- Public tasks are allowed runner input, but tuning should use development cases.
  Old inspected Requests/ItsDangerous questions and original audit cases are
  development data. Public checker reads no sealed files:
  `python3 evals/confirmatory/check_public_package.py`.
- Draft roster: 120 questions, 12 repository/stratum cells with 10 each. Plan SHA256
  `ffe7f4257c329841d3b2be6b60fe145e6befc2e23d6f4d8c9014d9c0545409bc`;
  package-manifest SHA256
  `c069f9f7fd0cf1c728cf2740cd1b6678d0aa4c4b2b8bd58839e7d73538ff2b0f`.
  Preserve drafts; finalize a new version/hash/signature before confirmatory runs.

## Local environment and safe continuation commands

Current worktree: `/Users/vinay2047/.codex/worktrees/4f55/FalkorDB_agent`.
Parent interpreter: `/tmp/rw-mcp-compat/bin/python` (3.12.13). `pyproject.toml`
contains exact main/MCP pins; the independent bundle records all resolved pins.
Fresh environments elsewhere must record their own versions and prerequisites.

```sh
git status --short
git log -8 --oneline
python3 evals/confirmatory/check_public_package.py
/tmp/rw-mcp-compat/bin/python -m pytest -q tests/test_confirmatory_corpus.py tests/test_confirmatory_plaintext.py
```

For a full suite, first provision an **owned disposable FalkorDB service and test
runtime**. Two legacy tests explicitly connect to `127.0.0.1:6379`; setting
`RW_FALKORDB_PORT` alone cannot isolate them. Follow the independent container
network-namespace setup in the reproduction bundle. Its fresh containers shared
only their own loopback, so hardcoded 6379 never reached the user's existing DB.
The actual command then enables `RW_REALREPO=1 RW_REALREPO_SMOKE=1`, runs
`python -m pytest -q -m 'not live' --junitxml=<new-output>` and records all skips.
Do not delete user graphs or stop unrelated containers/services.

Pinned available DB image:
`falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`.
Independent test clone/venvs remain under
`/private/tmp/rw-independent-812ecf7-z_wmyild`; its owned containers were removed.
All parent test/export sessions were terminal when this handoff was finalized.
Revalidate process/tool state before starting anything; never restart solely after
an observation timeout. No user-facing API is intentionally left running.

Development bare clones: `artifacts/repos/requests` and `artifacts/repos/itsdangerous`.
They are local prerequisites, not committed. Original provider credentials remain
in the original local project's environment; no credential bytes belong in this
handoff, commands, logs or Git. Existing live tests used credentials loaded into
an ephemeral child process, without copying `.env` into this worktree. No live
provider run is needed to reproduce deterministic source-only tooling failures.

New Requests source export receipts live in `artifacts/corpus-development/`;
the small receipts/spec and test reports are curated with this handoff. Full JSONL
exports are ignored, locally reproducible development artifacts, not acceptance
bundles. Latest export002: 6,372 commits, 5,438 distinct trees, 3,300 included unique
blobs, 48,951,611 included raw blob bytes, 151,612,580 serialized bytes; SHA256
`0a276e3e6134389c0d7b97a559c6db93f918eeb0d200fee79e6fd1a0db36420c`.
Exact model tokens remain unset. Export001 predates explicit directory metadata;
its smoke is historical and must not be relabeled as export002 validation.

## Preserve evidence when finishing a work batch

Use fresh run IDs/output paths, retain failed attempts and reasons for skips,
record source/config/model/prompt/corpus hashes, then update the machine ledger
and status links. Verify every linked artifact exists in committed bytes. Generic
`artifacts/` ignore rules also match nested curated directories: explicitly stage
only reviewed evidence files with `git add -f` where necessary. Keep raw log/XML
whitespace; source checks can exclude `docs/reviews/**/*.log` and `*.xml`.

Record independent AI authorship accurately. Tests, source-byte integrity, real
held-out quality, measured scale and comparative advantage establish different
things. Final release requires the full requirement audit; incomplete evidence
keeps the corresponding gate IN_PROGRESS.
