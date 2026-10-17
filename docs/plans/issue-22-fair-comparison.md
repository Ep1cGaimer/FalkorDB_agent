# Issue #22 implementation plan

Execution note (2026-10-18): implementation and the nine-observation acceptance batch are complete; see [STATUS](../STATUS.md#fair-comparison-and-relationship-ablation--issue-22-2026-10-18) and the [portable primary bundle](../../evals/evidence/issue-22/live-5a7160f-gemini31lite-05/README.md). The user authorized Gemini after Groq refusals. The planning assumptions below are retained as history.

Planning date: 2026-10-17. Issue: [#22 — Make the LLM control comparison fair and isolate the graph's contribution](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/22).

This document is a reviewed implementation plan, not a claim that the feature or live evaluation has been completed. No live model calls were made while preparing it.

## Workspace and prerequisites

- Branch: `plan/issue-22-fair-comparison`.
- Worktree: `.worktrees/issue-22-fair-comparison` in the original checkout.
- Base: freshly fetched `origin/main`, `793d7b168caa48e1925927b44e07e1fbae1f615b`.
- Active ownership guard: original checkout's `.worktrees/guards/issue-22-fair-comparison/ownership.json`.
- No credentials or environment files copied; no services started. Future ports 6382 (database) and 8022 (HTTP, only if needed) were checked free and recorded, not bound. Recheck before launch. Use `rw_issue22_<uuid>` for disposable evaluation graphs.
- Planning validation: from this worktree, using the original checkout's existing Python interpreter, `python -m pytest tests/test_llm_control.py tests/test_run_comparison.py -q -m 'not live'` produced **43 passed, 1 deselected**. These tests use scripted providers and real fixture readers; they do not establish live-provider or database acceptance.

**Dependency gate:** issue #22 refers to “the stricter scorer (#21),” but [#21 is an open PR](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/21), not merged code on this base. Its reviewed head was `0d046f1db6ea71ce6ab477dbf99da3775a434aca`. It changes the scorer, provider parsing, citation coverage, receipt read-back, fleet binding and related tests. Implement and collect acceptance evidence after those fixes land, then rebase this branch and recheck the affected interfaces. Do not silently collect with the older scorer or duplicate the PR's fixes here. A separately authorized stacked branch is possible if that dependency remains open.

[PR #19](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/19), head `ae799b8b30cb3ac26c46974d9cfe21f52f18453c`, separately changes grounding intent/ambiguity behavior for #17. It is not a prerequisite to the main comparison. If it lands before collection, rebase, refresh prompts and protocol hashes, and rerun the offline gates. Never mix observations across application revisions in one acceptance batch.

## Requirements and acceptance evidence

| Issue requirement | Necessary change | Evidence required to close it |
|---|---|---|
| 1. Equivalent clarification option | Add a genuine `ask_clarification` terminal to the legacy flat control and the new flat-grounding arm. | Scripted provider tests for valid/invalid questions, parity of terminal outcomes, no plan/probes on clarification, and saved/scored clarification rows. |
| 2. Same downstream checker | Add flat-context grounding followed by the existing `run_investigation` / `Session` checker path. | A fixed valid proposal produces equivalent canonical plans, obligations, receipt results and disposition in graph-grounding and flat-grounding workflows. |
| 3. Remove relationships, keep records | Add a deterministic `IN_STORE` edge ablation in disposable graphs. Name the lost capability: **connected reader–record obligation enumeration and its witness paths**. | Intact / ablated / restored outputs, unchanged node and file digests, exact removed edges, preserved inventory, lost path pairs and fail-closed gaps. |
| 4. Same model, `--runs 3`, complete accounting | Extend the runner to collect three arms in three paired blocks, with explicit protocol and telemetry. | Nine primary observations, one pinned model, complete prompts/tools, budgets, attempts, source hashes, outcomes, token accounting and elapsed time. All failures and missing observations remain visible. |
| 5. Commit sanitized bundle | Export a portable, checked evidence directory outside ignored results/artifacts. | A reviewer can validate hashes and recompute every score and table without credentials, provider access or the original machine. |
| Documentation completion | Update `docs/STATUS.md`, the README comparison line, and eval instructions after collection. | Current results link to the committed bundle; ties/control wins are reported literally. Historical author-reported data remains labeled as history. |

## What the current code establishes

- `evals/llm_control.py` supplies every release's `release.json`, `CHANGELOG.md`, `codec.py` and the selected snapshot manifest as flat text. It uses the product's transports/provider adapters, eight turns and temperature zero. Its tools are `run_reader_probe` and `submit_assessment`; its prompt currently forces an assessment even when intent cannot be bound. The model chooses probes and claims the disposition.
- `src/rw/grounding.py` separates a proposal from clarification. Its terminal validation checks delivered release identities, declared flags and exact excerpt citations, with one bounded citation correction. `run_investigation` in `src/rw/pipeline.py` accepts an injected grounding callable, so an evaluation adapter can reuse the complete trusted downstream path without changing the product API.
- `Session.verify` reads independent release declarations and snapshot bytes, writes a candidate plan, queries routes/inventory/obligation paths, runs readers, reads current receipts back, and computes disposition. It owns work that the legacy control currently has to perform inside its eight model turns. Giving both sides eight turns does not make those workflows equivalent.
- `graph.obligation_paths` requires `ReaderRoute -READS_FROM-> StateStore <-IN_STORE- Batch`. `store_inventory` independently anchors batches on their stored `store_id` and `snapshot_id` properties. Removing `IN_STORE` therefore leaves records discoverable while breaking their connected paths. `build_evidence` compares expected route × inventory pairs to returned path pairs, making missing connections explicit gaps.
- `evals/run_comparison.py` currently executes the legacy live pytest test in a subprocess, runs the product, and stops after a failed pair. Its manifest inventories source files but has no complete prompt/budget/time summary. Its source scanner traverses `evals/` except `results/`, which would accidentally include a newly committed evidence directory in future source hashes.
- `evals/score_controls.py` on this base conflates clarification with aborted execution internally and compares counts of consistent outcomes. PR #21 strengthens evidence validity. Extend that stricter implementation; preserve its tuple/hash matching and FAIL > UNKNOWN > PASS rules.
- `docs/ISSUE_3_COMPARISON.md` explicitly describes uncommitted, author-reported results. They cannot be relabeled as new acceptance evidence. `evals/relational_control.py` already demonstrates an SQL/graph obligation-set tie; this work must preserve that interpretation.

## Experiment contract

Freeze this contract in the runner's manifest before spending model quota.

| Arm | Model input and terminal decision | Downstream checking | Interpretation |
|---|---|---|---|
| `graph_grounding_checker` | Existing product graph tools; existing proposal or clarification | Existing trusted checker | Product reference |
| `flat_grounding_checker` | Same raw facts as the legacy control, with trusted citation identities; proposal or clarification | **The same** trusted checker | Primary comparison isolating grounding/retrieval interface |
| `flat_assessment` | All raw facts; individual reader probes; assessment or clarification | Independent scorer evaluates the model's claim | Legacy workflow comparison, labeled as a broader workflow difference |

Use the existing main request and `snap-001` for the primary live batch: “Undo the basket rollout, but keep the receipt correction.” Three blocks × three arms = nine conversations, excluding bounded transport retries. Rotate arm order by block with a fixed, recorded schedule so one arm is not always measured at the end of a quota window. No additional live case grid is required for #22; exercise clarification with scripted ambiguous/conflicting requests. A future broader benchmark is separate work.

All arms use one explicit `provider:model`, temperature zero, the same completion cap and transport retry policy, and at most eight model turns including correction/rejected-generation turns. Pin the model with `--model`; fallback to another model invalidates a same-model block. Record requested and returned model identities, and explicitly validate any provider alias rather than inferring identity from an environment variable. Record the actual settings, not just their defaults.

The matched arms make one initial grounding decision and one checker execution. Set `allow_alternative=False` for both and supply no clarification answer callback: a genuine clarification is a completed observation with no plan. The legacy arm may retain its historical optional alternative field as unexecuted metadata; do not score it as an extra attempt or grant an extra conversation. Evaluation scope confirmation only binds the plan to checking; it never approves or simulates an action.

Prompt and tool differences needed for flat versus graph access are intentional and must be disclosed and hashed. This isolates the **grounding/retrieval interface with a shared checker**, not graph storage versus SQL, not equal prompt length, and not guaranteed model reliability. Report request fit separately from byte readability: an unchanged fleet can have correct readability and still fail the requested rollback. Preserve the existing caveat about cross-service basket behavior.

## Implementation sequence

### 1. Freeze inputs and add control clarification

Files: `evals/llm_control.py`, `tests/test_llm_control.py`.

1. Add `ask_clarification(question, unresolved, citations)` with the same question/unresolved/citation meanings as the product. Validate a nonblank question, string unresolved references, and any supplied citations against text actually delivered. It requires neither fleet nor disposition. Remove the instruction that forces `submit_assessment` for an unbound request.
2. Save a distinct `CLARIFICATION` terminal with question, unresolved references, citations and raw call arguments. Keep turn exhaustion, malformed terminals and provider failures distinct from a model-chosen clarification. Do not classify the product's synthetic “Grounding aborted” clarification as a successful clarification.
3. Bump the control protocol version. Preserve reading of version-4 assessment transcripts without rewriting their original answers. Update the live smoke assertion so a genuine clarification can be usable execution without pretending to be a readability verdict.
4. Keep prompts neutral: no fixture-specific answer hints. Reject malformed nested fleet fields such as `flags:` rather than silently applying defaults to a different fleet; retain the original arguments and the bounded validation response. Carry forward PR #21's real-boolean checks. Do not turn harmless explicit flag choices into validation failures.

### 2. Add flat grounding with the shared checker

Proposed new file: `evals/flat_grounding.py`; tests: `tests/test_flat_grounding.py`. Reuse flat-context file enumeration from `llm_control.py`.

1. Build an evaluation-only source catalog directly from release files and the selected manifest. Include every existing raw text file, baseline fleet, declared flags and stable release identities. Attach source excerpt IDs, spans and content hashes using the same deterministic extraction/identity rules as the importer. Raw files remain fully available; annotations add citation addresses, not answers. Prefer reuse of the pure extraction helpers to a second excerpt algorithm, with parity tests guarding those internal seams.
2. Render only `propose_fleet` and `ask_clarification` as model tools. Flat grounding does not run individual probes, inspect the oracle, traverse graph relationships, or receive checker conclusions before its terminal. The prompt changes only the instructions needed to consume flat facts and cite their annotated text.
3. Use existing provider rendering/parsing, transports, terminal validation and citation-correction policy. Seed validation only with source/release rows actually included in the delivered context. Keep the small flat-context loop/adapter in `evals/`; avoid a general agent framework or a product-wide grounding rewrite. If a small reusable helper must be exposed from `grounding.py`, make that the only runtime refactor and regression-test unchanged graph-grounding behavior.
4. Return the existing `GroundingResult` plus transcript path from the adapter. Pass it as the `ground=` callable to `run_investigation` with the same snapshot, confirmation callback and alternative policy as the product arm. Preserve origin `agent` so the shared materializer enforces PR #21's citation coverage; never bypass it with `origin='fixture'` or `operator` for live model output.
5. For the legacy arm's clarification citations, reuse the same delivered source catalog. Do not grant the legacy assessment a different source inventory merely to obtain a favorable result.

### 3. Add the relationship-removal ablation

Proposed new file: `evals/relationship_ablation.py`; tests: `tests/test_relationship_ablation.py` against real FalkorDB. This is deterministic and needs no model quota.

1. Import identical fixtures into owned disposable graphs. Fix the snapshot, fleet, plan identity/confirmation and environment; use a fixture-origin proposal only for this explicitly deterministic experiment. Cover oracle A (blocked old reader) and B (readable flag-off fleet), loaded as expectations only by tests/scoring, not as runtime answers.
2. Record intact query rows and checker outputs: four reader × record obligations on `snap-001`, their exact identities, witness paths, probe results and disposition.
3. In the ablated graph remove **only** the two `Batch -IN_STORE-> StateStore` edges belonging to `snapshot:snap-001`. Select by parameterized snapshot/batch/store IDs. Keep releases, routes, stores, batches, source excerpts, coverage, payload bytes and all node properties. Never delete nodes or edit the fixture/manifest to manufacture the effect. Constrain destructive queries to handles created by this experiment.
4. Before/after mutation, compare node IDs, labels and canonical properties, fixture/source hashes, and the complete edge set. Require the edge-set difference to be exactly the recorded `IN_STORE` pairs. Compare the graph state at the same phase, before verification adds transient probe nodes. `store_inventory` must still return both batch IDs and payload hashes; only `in_store` becomes false.
5. Run the unchanged checker: the path query loses all four pairs, no connected obligations/witness paths can be materialized, and disposition must be `NEEDS_EVIDENCE` with inventory/missing-path gaps. Never describe the absence of a failing receipt as evidence that the old reader became compatible.
6. Restore exactly the removed edges and rerun. Require the original obligation identities, witness paths, probe results and disposition to return. Ignore receipt nonce/timestamps when comparing results, not obligation bindings. Save intact/ablated/restored reports and a structured difference, then delete only owned graphs in `finally`; verify deletion independently.

The capability demonstrated is connected obligation enumeration and its witness path. Raw records and direct ID lookup survive; SQL or an independent join can reconstruct the pairs. Do not claim “only a graph can do this.” Do not broaden to removing every edge type unless this targeted experiment fails to demonstrate the specified loss.

### 4. Make scoring distinguish decisions, evidence and experimental arms

Files: `evals/score_controls.py`, `tests/test_score_controls.py` from #21, existing scorer tests in `tests/test_llm_control.py`.

1. Add explicit protocol/arm/block/case metadata and normalization for the new matched arm. Shared-checker reports use the same report parser and strict receipt validation regardless of grounding origin. Do not relabel them as ordinary product runs or pool them with the legacy assessment.
2. Represent genuine clarification, rejected proposal, turn exhaustion, provider error and missing execution separately. Show every observation. Clarification has no obligation-recall denominator and no fabricated disposition; assessing its semantic appropriateness is separate from readability scoring.
3. Retain strict canonical obligation hashes, exact receipt tuples, per-run evidence support, gap handling and repeated-result precedence from #21. Distinguish false passes from unsupported passes. Expose fleet/request-fit observations separately; do not infer semantic success from `BOUNDED_PASS`.
4. Report primary matched-arm results by aligned completed blocks for the same request/model. Keep operational-failure counts and excluded/missing rows visible. Compare equal denominators; do not choose a winner from pooled raw success counts when block coverage differs. Report a tie or control win literally, and never pick “best case” as the headline. Show the legacy workflow result in its own table.
5. Preserve the existing CLI for historical artifacts. Add explicit bundle/manifest input for portable rescoring rather than relying on absolute transcript paths or filename glob guesses. Missing, duplicate, corrupt or unknown-version bundle entries must fail validation instead of being silently skipped.

### 5. Extend the runner and evidence accounting

Files: `evals/run_comparison.py`, `tests/test_run_comparison.py`; proposed exporter/validator `evals/comparison_evidence.py` and `tests/test_comparison_evidence.py`.

1. Run each arm directly through its callable and shared artifact protocol. Keep the standalone live pytest smoke as a smoke test; its assertions must not decide which experiment outcomes survive. A wrong fleet, rejected proposal, unsupported assessment or genuine clarification is an observed result, not permission to discard/retry the experiment.
2. Validate run count/model/output path up front. Write the initial manifest before the first provider call and checkpoint after every arm. Stop on operational failure, timeout, model mismatch or source drift, preserving the failed observation and explicitly marking remaining scheduled slots unrun. Never restart whole trials until a preferred answer appears. A later invocation gets a new bundle ID; retain interrupted attempts separately.
3. Record protocol version, UTC start/end, application Git SHA and dirty input inventory, Python/dependency/server versions, snapshot/request/case, arm order, requested/completed blocks and per-slot status. Record all system/user prompts, tool schemas and delivered tool results plus their hashes. Record actual turn/completion/context caps, retry/backoff/timeout/pacing settings and alternative/clarification policies.
4. For every turn/attempt record requested/actual model, sanitized outcome or error category, validation/correction events, model turns, calls and retry status. Use monotonic clocks for grounding, checking, waiting and whole-arm elapsed seconds; UTC timestamps establish ordering. Keep model calls separate from deterministic reader probes.
5. Use an evaluation-local transport wrapper around the existing transport for prompt/response usage and timing. Include bounded transport retry/pacing traces. Sum numeric provider-reported prompt/completion/total usage for successful responses, preserving the provider's field names; mark unavailable usage, especially rejected/failed requests, as unknown. Do not report missing usage as zero or estimate it into measured totals. Retain attempt data on exceptions.
6. Correct source inventory boundaries: hash all runtime/eval code, fixture declarations/changelogs/codecs, manifests, retained bytes, harness and dependency inputs before/after. Hash oracle/expectation files separately and never deliver them to the model. Exclude generated output trees (`artifacts/`, `evals/results/`, `evals/evidence/`), caches, credentials and the manifest itself from source hashes. Prove additions/removals are detected and generating the bundle cannot cause self-induced source drift.
7. Give each arm its own graph namespace where needed; validate ownership and delete in `finally`. Record cleanup errors without replacing the original error and verify actual graph absence. Restore temporary environment overrides. Never approve, simulate, deploy, or call someone else's graph cleanup.

### 6. Export, validate, collect live, then document

Commit a curated bundle at `evals/evidence/issue-22/<batch-id>/`, not ignored `artifacts/` or `evals/results/`:

```text
manifest.json                   # protocol, schedule, input hashes, completion and artifact index
protocol.json                   # exact requests, prompts/tools or relative references, budgets
observations/<block>-<arm>.json  # sanitized model events, timing, usage, terminal and checker report
ablation/                      # intact/ablated/restored reports and structural differences
scores.json                    # recomputable scorer output
comparison.md                  # generated tables and qualified interpretation
README.md                      # reproduction commands, provenance, redaction policy, limitations
```

Use an allowlist export schema. Exclude credentials, authorization/cookie headers, account/org/request IDs, raw HTTP error bodies, unrelated response fields and machine-specific absolute paths. Preserve synthetic quotes, model tool arguments, failures, receipt tuples/hashes, query results and relevant numeric usage. Normalize only non-evidentiary paths to bundle-relative references; never change bytes inside canonical hashed tuples. Keep a redaction summary and hash the exported bytes. Manifest artifact hashes exclude the manifest itself to avoid circular hashing.

Before live collection, freeze code/protocol, complete the offline gates below, and run the exporter/validator against synthetic transcripts containing fake secrets. Then run the comparison with an explicit single Groq model and cap. The existing smaller-budget example is a candidate setting, not a claim that current quota or model availability has been verified:

```sh
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 \
  .venv/bin/python evals/run_comparison.py --runs 3 \
  --model groq:qwen/qwen3.8-27b \
  --out artifacts/issue-22/<new-batch-id>
```

The runner implementation must document export/validation/rescore commands in `--help` and `evals/README.md`; suggested interfaces are `comparison_evidence.py export --input ... --out evals/evidence/issue-22/<batch-id>` and `comparison_evidence.py verify <bundle>`, followed by `score_controls.py --bundle <bundle> --json <temporary-score-path>`. These interfaces are planned, not present on the base revision.

Groq quota is a real dependency. Load credentials only for live execution; if copying `.env` into the worktree is needed then, keep it ignored and mode 0600. Check availability without logging keys. A quota refusal produces an incomplete preserved batch; it does not satisfy the live requirement and cannot be replaced by replay. Do not remove “author-reported” from the current comparison line until a complete checked bundle exists. If interpretation/export code changes after collection, keep the original artifacts and record the rescoring revision; rerun live if runtime inputs, prompts or budgets changed.

After successful validation, update `docs/STATUS.md` with all nine rows, actual model/budgets/retries, accounting limitations, the ablation delta, the exact bundle path and commands actually run. Replace the README's current comparison bullet with the measured primary result and a bundle link. Keep historical #3 provenance intact. Update `evals/README.md` and incorrect “only one difference/equal checker access” descriptions in the legacy control. Commit code/tests and the curated evidence/docs as reviewable changes; a planning document alone does not close #22.

## Testing instructions for sensitive changes

Complete stages in order; do not run database tests/smoke concurrently with live collection. Prior STATUS evidence records a test cleanup deleting an evaluation graph mid-run. Unique names help, but do not assume they fix broad cleanup helpers. Use the recorded dedicated database port for the new eval harness, with narrowly scoped `--db-port` plumbing if needed; existing regression suites hardcode 6379, so schedule those serially against their documented test server. Do not globally redirect or stop another checkout's server. The current Compose file also fixes container name/ports; a second instance needs an explicit isolated configuration.

| Change/risk | Required test and pass condition |
|---|---|
| Clarification versus abort | Script both provider formats through assessment, valid clarification, blank question, malformed references/citations, correction, text-only turns and exhaustion. Real clarification is complete with zero plan/checker/probe calls; exhaustion/provider errors remain failures. Preserve version-4 transcript scoring. |
| Flat-source parity and citation boundary | Compare all delivered file hashes against legacy context enumeration, release/excerpt IDs against importer extraction, and exact quotes/spans against files. Spy on graph functions during flat grounding: no graph access before the terminal. Unknown release/flag, string booleans, invented quote, omitted release citation and nested `flags:` must be rejected, without repairing answers. Oracles and prior reports never enter context. |
| Shared checker equivalence | Inject the same request and valid cited proposal into each matched arm. With frozen identity/time inputs, compare plan hashes and exact obligation tuples; otherwise normalize only documented nonce/time fields. Require the same reader results, gaps, witnesses and disposition. Exercise A/B plus partial/orphan snapshots; clarification/rejection must never verify. |
| Relationship mutation | Real FalkorDB test: two edges removed, identical nodes/properties/files, both records still inventoried, four intact pairs → zero connected pairs with `NEEDS_EVIDENCE` → four restored pairs. Test mismatched graph ownership/snapshot rejection and cleanup on exceptions. No mutation leaks to a product graph or fixture. |
| Scorer safety regression | Keep #21 tests for wrong tuple/hash, stale/extra/missing receipt, conflicting repeated results, UNKNOWN, forged BLOCKED/PASS and gaps. Add all-arm parity, genuine clarification, old schemas, unequal/missing blocks, duplicate observations, tie and control-win fixtures. No unsupported claim becomes consistent merely because the oracle agrees. |
| Runner completion and cleanup | Script three complete blocks and each failure boundary: first/middle/last arm provider failure, timeout, abort, source addition/removal/edit, mismatched model, existing output, missing transcript, exporter failure and graph cleanup failure. Every scheduled slot is completed, failed or unrun; files persist and completion is false when required execution is missing. Adverse semantic outcomes alone do not stop/redo collection. |
| Telemetry accuracy | Fake monotonic clock and provider usage including numeric zero, missing fields, malformed values, rejected generations and retries. Check sums, measured wall time, attempt counts and unknown labels. Do not double-count per-turn events or treat provider retries as new experiments. |
| Evidence portability/security | Embed fake API keys, headers, account identifiers, error bodies and absolute paths; prove export removes them while preserving score inputs. Move the bundle to a temporary checkout/directory with no credentials, deny network, verify hashes and regenerate scores/tables. Tamper/delete/add an indexed artifact or use a path traversal and require validation failure. Check `git check-ignore` and staged-file contents so the curated bundle is actually tracked. |
| Product contract regressions | If any `src/rw/` helper changes, run grounding/replay/pipeline, API contracts, approval/simulation and MCP regression tests. Confirm no model path can approve/simulate, drift guards still reject changes and repeated local simulation stays idempotent. Browser checks are needed if public behavior/schema or UI files change. |

Focused commands after implementation (new filenames below are planned):

```sh
.venv/bin/python -m pytest tests/test_llm_control.py tests/test_flat_grounding.py \
  tests/test_run_comparison.py tests/test_score_controls.py \
  tests/test_comparison_evidence.py -q -m 'not live'
.venv/bin/python -m pytest tests/test_relationship_ablation.py \
  tests/test_graph_integration.py tests/test_acceptance_oracle.py \
  tests/test_relational_control.py tests/test_pipeline.py tests/test_verification.py -q -m 'not live'
.venv/bin/python -m pytest -q -m 'not live'
.venv/bin/python scripts/smoke.py
node --test tests/js/*.test.mjs
git diff --check
```

Run the final non-live suite in both base and MCP-enabled installation modes, as CI does, if runtime code changes; do not add unconditional optional-SDK imports. A full suite needs the documented real database. Record actual counts and legitimate optional skips instead of copying historical counts from #21. Verify SQL/graph/oracle parity remains 8/8; run `evals/relational_control.py` if changing any obligation derivation. After code gates pass, run the ablation and live collection serially, export/validate, and rescore the committed bundle without network access. No repeat of successful gates is needed unless further changes invalidate them.

## Scope and completion gate

Necessary scope is the control terminal, one eval-only grounding adapter, one targeted ablation, arm-aware scoring/runner/evidence tooling, tests and linked documentation. No production feature, provider migration, dependency refresh, fixture/oracle retuning, UI redesign, generalized benchmark platform or SQL replacement is required. Add no model prompt hints tailored to produce a winner.

Completion requires every requirement row above, all relevant offline checks passing, intact/ablated/restored evidence verified, three complete same-model blocks committed with portable rescoring, and README/STATUS updated from those artifacts. A tie, control win, adverse grounding outcome or honest clarification can still complete the experiment. Missing live runs, quota exhaustion, incomplete hashes or unverifiable evidence cannot.
