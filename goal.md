# Goal

Status: **proposed, 2026-10-18**. When the team agrees, replace this line with
"Agreed on <date> by <names>". After that, scope changes are made by editing this file in a commit.

## The product claim

Rolling back code does not roll back data. RollbackWitness decides, record by record, whether every
reader in a proposed rollback can read what is already stored, and refuses to call a rollback safe
when evidence is missing. Because the checks come from a FalkorDB graph of releases, readers, stores
and records, the result stays complete and exact as the system grows, where an LLM analysing the same
code and data as plain text gives false "safe" answers, misses records and readers, and stops fitting
in its context.

## Scope

### In scope

| # | Capability | Done when |
|---|---|---|
| 1 | End-to-end investigation on the Astronomy Shop dataset | a request becomes a proposed fleet; a blocked rollback names the failing record, the reader, the writer release and the real error; a safe alternative gives BOUNDED_PASS; approval and simulated rollout work, in the web UI and the CLI |
| 2 | Replay mode for every shipped sample request | each sample in `fixtures/astronomy-shop/sample_requests.json` runs from a saved recording with no network |
| 3 | Evidence gaps never pass | partial coverage, unknown writer or format, a changed snapshot, a payload hash mismatch and a truncated query each give NEEDS_EVIDENCE, with the gap named |
| 4 | Scale-system generator | one deterministic script builds systems of sizes S, M, L and XL (table below) with planted hazards whose correct outcomes are written by the generator |
| 5 | Checker that scales | records are grouped by writer release, format and shape; identical payloads are checked once per reader (cache keyed by reader code hash and payload hash); every group is checked; an XL system verifies without exceeding the query cap, and exceeding it still gives NEEDS_EVIDENCE |
| 6 | Plain text vs FalkorDB benchmark | the comparison below runs on all four sizes and saves raw results |
| 7 | Git release import | `scripts/import_git_releases.py` creates release folders from a repository's tags, keeping hand-declared routes and codecs |

### Scale sizes

| Size | Services | Releases | Stores | Retained records | Planted hazards |
|---|---|---|---|---|---|
| S | 4 | 8 | 1 | 40 | 1 |
| M | 20 | 60 | 5 | 1,000 | 3 |
| L | 100 | 400 | 20 | 20,000 | 5 |
| XL | 300 | 1,500 | 60 | 200,000 | 8 |

Hazard kinds: stored records an older reader cannot read (BLOCKED); a changelog that claims
compatibility but is wrong (BLOCKED); a limit visible only by running the reader (BLOCKED); a reader
no changelog mentions; partial coverage or an unknown writer (NEEDS_EVIDENCE); a safe rollback
(BOUNDED_PASS).

### Benchmark

Three contestants answer the same request for every hazard, at every size:

1. **Plain text:** an LLM given the system as text (chunked when it does not fit) answers with a
   verdict and the failing records.
2. **Plain text with a run tool:** the same, plus a tool that runs one reader on one record.
3. **RollbackWitness:** obligations from FalkorDB, every reader run on the real bytes, verdict from
   fixed rules.

Measured for each contestant and size: false "safe" rate, failing records found and wrongly flagged,
readers missed, agreement across repeated runs, whether the input fit in context, time and LLM tokens.

### Out of scope

Live Kafka, Postgres or other store sampling; running real .NET, Kotlin or Go binaries; Kubernetes,
Helm or registry import; automatic discovery of reader routes from source code; hosting for other
users. These stay in [docs/plans/arbitrary-repo-onboarding.md](docs/plans/arbitrary-repo-onboarding.md).

## Evidence rules

A capability is done, and a result may be quoted, only when all of these hold.

1. **Reproducible.** It comes from a committed script or test with a fixed seed; the exact command is
   recorded next to the result. Rerunning gives the same graph-side result.
2. **Raw output kept.** Every benchmark run saves its prompts, model responses, receipts and timings
   as JSON under `artifacts/`.
3. **Answers fixed in advance.** Expected outcomes come from the generator or the fixture design,
   written before any contestant runs. No contestant's output is used as the answer key.
4. **Equal information.** The plain-text contestants get every fact the graph imports: releases,
   changelogs, reader code, deployments, the record inventory with writers, and the decoded records.
   Anything trimmed or summarised to fit a limit is listed with the result.
5. **Same model.** Within one comparison, every LLM-based contestant and the product's grounding agent
   use the same model. Results from a different model are reported separately.
6. **Same question.** Contestants get the same request naming the exact target versions, so the safety
   verdict is compared on its own. Request interpretation is measured separately.
7. **Repeats.** Every LLM case runs at least 5 times; the spread is reported, not the best run.
8. **All outcomes reported.** Ties and plain-text wins are reported. "Did not fit in context" is its
   own outcome, not counted as a wrong answer.
9. **Synthetic data labelled.** Results on generated or Astronomy Shop data say they are synthetic,
   modelled on OpenTelemetry Demo 3.1.0, with release 3.2.0 authored.
10. **No hand-entered numbers.** Tables are produced from the saved JSON by a script.
11. **The product never passes on missing evidence.** Any change that lets a gap reach BOUNDED_PASS is
    a regression, whatever else it improves.
12. **Done means verified.** A capability counts as done only when its "done when" line is met and the
    command and output that show it are linked in the status table below. Any later change to that
    capability makes it not done until it is re-verified.

## Status

| # | Capability | Status | Evidence |
|---|---|---|---|
| 1 | End-to-end investigation | built, not verified | `improve-demo`; `tests/test_astronomy_fixture.py` passes; currency scenario not yet run end to end in the UI |
| 2 | Replay mode | not started | earlier recordings were for the retired framing scenario |
| 3 | Evidence gaps never pass | partly verified | snap-002 and snap-003 give NEEDS_EVIDENCE in `tests/test_astronomy_fixture.py`; changed-snapshot and hash-mismatch cases not checked on this dataset |
| 4 | Scale-system generator | not started | |
| 5 | Checker that scales | not started | today: one process per reader-record pair; the 200-row query cap fails safe |
| 6 | Benchmark | started, size S only | `evals/plaintext_vs_graph.py`: graph 6/6 correct; plain text gave false PASS in 5 of 6 evidence-gap runs, was correct on visible hazards, and the 96-record case did not fit the Groq free tier; 3 repeats, not 5 |
| 7 | Git release import | built on `feat/astronomy-shop-demo` | not yet on `improve-demo` |
