# Goal

Priority updated by the user on 2026-10-18: **complete Primary first, then resume
Secondary**. This changes work order; it does not declare any acceptance gate
passed or remove the remaining requirements. The handoff commit remains canceled.

**User deadline: Primary by 18:45 IST on 2026-10-18; all Secondary work by
19:30 IST.** Finish Primary first, then pursue the full Secondary requirements.
These are requested deadlines, not achieved results or permission to replace the
secondary acceptance work with demo packaging. Retain unfinished requirements
and failed evidence explicitly if the requested deadline cannot be met.

The latest user deadline is **20:30 IST on 2026-10-18**, superseding the earlier
additional-30-minute timebox of approximately20:24. Preserve the full remaining requirements; a timebox is not an
acceptance waiver. Focus quality checks on distinct multi-hop, ambiguity and
missing/limited-evidence failures, using **Gemini 3.1 Flash Lite in test processes
only**. Do not change application endpoints or model settings. Graph use remains
optional: improve tool-selection reasoning and calling schemas, allowing direct
source reads whenever they are the more useful evidence path.

Timebox from 18:07 IST: working live graph flow by18:25; cited dependency/history
examples and focused smoke by18:35; three rehearsals and primary readiness by18:45;
then secondary acceptance work, launch instructions and delivery fixes through19:30.
Use the working deterministic, source-backed investigation path if the live model
provider remains unreliable; label its behavior honestly. Do not spend the demo
window repeatedly probing providers or make a replay appear live.

RollbackWitness helps investigate code and Git history using FalkorDB and
revision-specific source evidence. Its specialized fixture workflow checks
rollback compatibility against explicit runtime receipts. General source retrieval
keeps runtime compatibility unverified. Comparative advantage remains unproven.

## Primary — Immediate demo requirements

Deliver a reliable, understandable demonstration on a real repository through
one existing interface. Prioritize the complete user flow over adding features,
new interfaces, broad test matrices or benchmark volume.

| Priority | Requirement | Done when |
|---|---|---|
| P1 | Reliable end-to-end investigation | A fresh natural-language question on an explicitly selected real repository/revision retrieves actual FalkorDB evidence and produces a useful final answer within a declared demo time/token budget. Provider failures and budget exhaustion remain visible. A first tool call alone does not count. |
| P2 | Inspectable source citations | The answer identifies the repository, exact commit, path and physical source lines. The presenter can open the cited source at that revision and verify the material findings. Empty files use membership evidence without invented lines. |
| P3 | A useful multi-hop graph finding | One investigation follows at least two dependency/history hops, explains the practical implication, and retains the actual graph query/result trace linking the finding to source. |
| P4 | A convincing correctness boundary | Show a revert/branch trap with the correct revision-specific conclusion, plus a bounded/truncated or missing-evidence case that exposes its limitation and withholds an unsupported conclusion. |
| P5 | Repeatable presentation and recovery | Document setup/import, selected repository/revisions, the demo sequence, reset and launch commands. Rehearse the complete sequence three consecutive times within the declared demo duration, including a fresh real-repository investigation each time. Retain failures. Keep a clearly labeled replay as a backup. |

### Primary verification and evidence

- Run targeted regression tests for changed behavior and a short end-to-end smoke
  check. Repeat broader suites when a change or observed failure warrants it.
- Verify citations and conclusions in the actual demonstrated scenarios. Retain
  commands, source/index identities, retrieval traces, model responses, timings,
  usage and failures. Do not tune against sealed held-out answers.
- Keep repository-code execution disabled during ingestion. Keep existing safety
  boundaries intact: missing evidence cannot yield `BOUNDED_PASS`; source-only
  investigation cannot establish runtime compatibility.
- Use the existing interface that supports the flow. Additional UI polish or new
  transport surfaces are secondary unless they block presenting the primary demo.
- The specialized fixture failure/pass workflow is a short supporting segment if
  it strengthens the presentation. Show it if the demo claims rollback safety;
  clearly label its synthetic data and fixture-only runtime scope.
- Show quantitative comparison claims only when measured and linked to evidence.
  A successful demo does not establish the full acceptance specification.

### Primary status at prioritization

These are observations, not completion claims. Recheck the actual current state
before using them as demo evidence.

| Requirement | Current position | Next work |
|---|---|---|
| P1 | Verified for the supported deterministic natural-language workflow on inspected real source; live LLM development remains unresolved. | Preserve the working no-provider demo path. |
| P2 | Verified: exact source citations open in the browser and hashes/spans resolve in the focused smoke. | Keep citations visible in the presentation. |
| P3 | Verified: real two-hop dependency retrieval is connected to source and the displayed finding. | Explain the inspection use and static-inference limits. |
| P4 | Verified: synthetic revert/ancestry trap, real-source truncation and missing-symbol gap shown through the live browser. | Clearly label the trap as synthetic. |
| P5 | Three automated browser-flow rehearsals passed after distinct reset publications; offline labeled replay/source snapshots verified. Launch/reset and presentation notes exist. No narrated human/video rehearsal is claimed. | See [primary evidence and limits](docs/demo/STATUS.md). |

## Secondary — Full acceptance, broader testing and comparison

Resume this work after Primary is verified, except for a targeted check needed
to diagnose a primary blocker or preserve its correctness/safety. These tasks
remain required before claiming the complete original goal or v1 acceptance.
The authoritative full contract remains [remquirements-v1.md](remquirements-v1.md);
its thresholds and evidence rules are unchanged. Every T0–T11 gate remains
`IN_PROGRESS` at this prioritization; none is waived or marked validated.

| Gate | Secondary work remaining beyond the focused demo checks |
|---|---|
| T0 — Frozen evaluation contract | Final corpus/model/prompts/budgets, independent review and sign-off, exact context accounting and a pre-result hashed plan. Freeze before confirmatory evaluation. |
| T1 — Configuration-only integration | Clean onboarding of both evaluation repositories, including a genuinely unseen repository after implementation freeze; complete regression/access evidence. |
| T2 — Held-out quality | At least 120 independent questions across both repositories/all six strata, three paired repeats per arm, blind grading, required double-scoring and every absolute quality/safety threshold. |
| T3 — History correctness | Complete adversarial Git DAG, at least 100 seeded histories, all identity/current-presence invariants and independent deterministic expectations. |
| T4 — Index integrity/recovery | Full versus incremental equivalence, all persistence/publication fault points, restart/retry/concurrency behavior and stale/deleted evidence invalidation. |
| T5 — Retrieval bounds | Complete row/hop/page boundary matrix, independent enumeration, cursor invalidation and token/time/resource exhaustion behavior. |
| T6 — Scale/performance/cost | Three declared slices, repeated cold imports and updates, at least 100 requests per slice, concurrency, resource/latency/success measurements and actual costs. |
| T7 — CLI/API/MCP parity | Full identity/status/coverage matrix across all surfaces, real MCP restart, malformed inputs, cancellations, concurrent selections, follow-ups and live grounding. |
| T8 — Ingestion/runtime boundaries | Complete observable process/filesystem/network audit, malicious repository cases and all applicable receipt/disposition/approval/simulation checks. |
| T9 — Causal graph contribution | Held-out query-to-answer traces, required multi-hop examples on each evaluation repository and dependency/history/stale/interruption/outage ablations. |
| T10 — Fair comparative advantage | Applicable direct-context and practical search baselines, shared budgets/model/instructions, paired repeats, the preselected A/B threshold, 10,000-resample confidence intervals, repository vetoes and cost/break-even reporting. |
| T11 — Reproduction/submission | Complete versioned evidence bundle, independent clean reproduction and score recomputation, at least 12 stratified live held-out reruns, full prescribed demos/claim card and verified official event deliverables. Primary rehearsals count only if they meet the applicable frozen requirements. |

Keep all earlier failed, skipped and inconclusive attempts. A held-out result that
informs a repair becomes development data for a later confirmatory claim. Report
integration, history correctness, scale and advantage separately. Track exact
current status and artifacts in the
[evidence ledger](docs/reviews/goal-acceptance-ledger.json) and
[repository status](docs/REPO_STATUS.md).

### Preserved earlier fixture and benchmark plan

The following is the original Astronomy Shop plan, retained for secondary work
and historical traceability. Its opening comparative statement is an **unproven
hypothesis**, not the current product claim. Its status table, branch names and
numbers are historical assertions requiring fresh verification. Its five-repeat
synthetic benchmark is a separate experiment from the three paired repeats in
the real-repository T2/T10 contract; neither replaces the other. Its out-of-scope
list applies to that fixture plan, not to the later repository-integration scope.

#### The product claim

Rolling back code does not roll back data. RollbackWitness decides, record by record, whether every
reader in a proposed rollback can read what is already stored, and refuses to call a rollback safe
when evidence is missing. Because the checks come from a FalkorDB graph of releases, readers, stores
and records, the result stays complete and exact as the system grows, where an LLM analysing the same
code and data as plain text gives false "safe" answers, misses records and readers, and stops fitting
in its context.

#### Scope

##### In scope

| # | Capability | Done when |
|---|---|---|
| 1 | End-to-end investigation on the Astronomy Shop dataset | a request becomes a proposed fleet; a blocked rollback names the failing record, the reader, the writer release and the real error; a safe alternative gives BOUNDED_PASS; approval and simulated rollout work, in the web UI and the CLI |
| 2 | Replay mode for every shipped sample request | each sample in `fixtures/astronomy-shop/sample_requests.json` runs from a saved recording with no network |
| 3 | Evidence gaps never pass | partial coverage, unknown writer or format, a changed snapshot, a payload hash mismatch and a truncated query each give NEEDS_EVIDENCE, with the gap named |
| 4 | Scale-system generator | one deterministic script builds systems of sizes S, M, L and XL (table below) with planted hazards whose correct outcomes are written by the generator |
| 5 | Checker that scales | records are grouped by writer release, format and shape; identical payloads are checked once per reader (cache keyed by reader code hash and payload hash); every group is checked; an XL system verifies without exceeding the query cap, and exceeding it still gives NEEDS_EVIDENCE |
| 6 | Plain text vs FalkorDB benchmark | the comparison below runs on all four sizes and saves raw results |
| 7 | Git release import | `scripts/import_git_releases.py` creates release folders from a repository's tags, keeping hand-declared routes and codecs |

##### Scale sizes

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

##### Benchmark

Three contestants answer the same request for every hazard, at every size:

1. **Plain text:** an LLM given the system as text (chunked when it does not fit) answers with a
   verdict and the failing records.
2. **Plain text with a run tool:** the same, plus a tool that runs one reader on one record.
3. **RollbackWitness:** obligations from FalkorDB, every reader run on the real bytes, verdict from
   fixed rules.

Measured for each contestant and size: false "safe" rate, failing records found and wrongly flagged,
readers missed, agreement across repeated runs, whether the input fit in context, time and LLM tokens.

##### Out of scope

Live Kafka, Postgres or other store sampling; running real .NET, Kotlin or Go binaries; Kubernetes,
Helm or registry import; automatic discovery of reader routes from source code; hosting for other
users. The original plan referenced `docs/plans/arbitrary-repo-onboarding.md`, which is absent
from this checkout. Current repository-integration planning is in
[docs/plans/repo-integration-v1.md](docs/plans/repo-integration-v1.md).

#### Evidence rules

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

#### Status

| # | Capability | Status | Evidence |
|---|---|---|---|
| 1 | End-to-end investigation | built, not verified | `improve-demo`; `tests/test_astronomy_fixture.py` passes; currency scenario not yet run end to end in the UI |
| 2 | Replay mode | not started | earlier recordings were for the retired framing scenario |
| 3 | Evidence gaps never pass | partly verified | snap-002 and snap-003 give NEEDS_EVIDENCE in `tests/test_astronomy_fixture.py`; changed-snapshot and hash-mismatch cases not checked on this dataset |
| 4 | Scale-system generator | not started | |
| 5 | Checker that scales | not started | today: one process per reader-record pair; the 200-row query cap fails safe |
| 6 | Benchmark | started, size S only | `evals/plaintext_vs_graph.py`: graph 6/6 correct; plain text gave false PASS in 5 of 6 evidence-gap runs, was correct on visible hazards, and the 96-record case did not fit the Groq free tier; 3 repeats, not 5 |
| 7 | Git release import | built on `feat/astronomy-shop-demo` | not yet on `improve-demo` |
