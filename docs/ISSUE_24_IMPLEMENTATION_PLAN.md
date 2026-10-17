# Issue #24 implementation plan

Reviewed 2026-10-17 against `main` at `793d7b168caa48e1925927b44e07e1fbae1f615b`.
Implemented on `fix/issue-24-obligation-identity`, based on that current `origin/main`. All six steps
below are implemented. Acceptance evidence is recorded in [STATUS.md](STATUS.md#full-evaluation-obligation-identity--issue-24-2026-10-17):
base suite **472 passed**, MCP suite **511 passed**, explicit SDK leg **39 passed**, baseline/variant
SQL parity **8/8 + 2/2**, and deterministic smoke **8/8 PASS**. Hosted CI and remote PR mergeability
have not been observed. The dependency audit below remains a dated finding, rechecked at start of implementation.

[Issue #24](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/24) requires distinct reader obligations to survive evaluation even when a release has several routes or reads several stores.

## Dependency finding

**No direct dependency on an outstanding issue or PR was found. Work can start from current main.**

Evidence: reviewed all eight open issues (#12, #17, #22–#27), both open PRs (#19 and #21), issue #24's body/comments and timeline, and GitHub's `issues/24/dependencies/blocked_by` endpoint, which returned `[]`. Issue #24 has no comments or recorded prerequisite in its timeline.

| Item | Relationship to #24 | Consequence |
| --- | --- | --- |
| [#25, Astronomy Shop](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/25) | Explicitly requires full obligation identity before landing | #24 is a prerequisite for #25; the direction is outward |
| [PR #21, review fixes](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/21) | Changes `evals/score_controls.py`, `evals/llm_control.py`, their tests and fixture rebuild tests | Coordinate/rebase overlapping edits; no new API or feature from #21 is necessary for #24 |
| [#22, comparison fairness](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/22) | Changes control capabilities and comparison methodology | Keep tool budgets, clarification and live evaluation work separate; identity fixes can land first |
| [#17](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/17) / [PR #19](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/19) | Grounding ambiguity and provider-quota acceptance | Does not block deterministic oracle/control/scorer work |
| #12, #23, #26, #27 | Startup, grounding rubric, CI and documentation work | No prerequisite for this change |

PR #21 still uses `(service, version, record_id)` as its scorer key, so it does not solve #24. Its receipt binding, canonical hash checks, evidence-supported verdicts and repeated-result precedence must survive integration whichever PR lands first. #24 should not absorb those separate fixes. Recheck open PR state before implementation/merge because this audit is a point-in-time finding.

## Requirements and current gaps

| Requirement | Current behavior | Required result |
| --- | --- | --- |
| Independent expectations identify every route/store obligation | `evals/expected/dispositions.json` records service/version/record only | Every expected obligation includes `route_id` and `store_id` |
| Acceptance compares exact obligations, outcomes and failures | `tests/test_acceptance_oracle.py` reduces all three to service/record pairs | Compare the full evaluation key in each assertion, including blocking receipts |
| SQL parity compares exact identities | SQL already returns route name and store, but its CLI and `tests/test_relational_control.py` discard them | Preserve and normalize those fields for SQL = graph = oracle comparisons |
| Flat control probes the requested reader | `FlatControlTools.records` is keyed by record ID alone; `run_reader_probe` selects the first route reading that store | Index records by store/record and require an explicit validated route/store selection |
| Scorer preserves every obligation | Fixture indexing drops route names; predictions, required obligations and observed probes use triples | Retain route/store through indexing, enumeration, extraction, recall and diagnostics |
| Regression proves multiplicity | Shipped oracle cases have one reader route per release and one store | A checked fixture variant exercises multiple routes and stores through the real pipeline, SQL and scorer |

The runtime already carries `route_id` and `store_id` in `ObligationTuple`, materializes per-route obligations and binds receipts to the complete runtime tuple (`src/rw/contracts.py`, `graph.py`, `verification.py`). No production schema, receipt-hash or graph-query redesign is indicated by this issue.

Reproduced during this review using a temporary fixture copy: adding a second cart 1.4 route over the existing two records creates **six** declared route × record obligations across the fleet; `score_controls.reader_obligations` retains **four** keys. No tracked fixture was changed.

## Implementation sequence

### 1. Define and document the evaluation identity

Use `(service, version, route_id, store_id, record_id)` everywhere within a case/run. Snapshot and fixture root remain explicit surrounding context. Keep runtime receipt applicability bound to the entire existing `ObligationTuple`; this five-field evaluation key does not replace it.

Use canonical IDs consistently: `store:<store-name>` and `route:<release-id>:<declared-route-name>`, with release IDs derived from fixture bytes by the documented release identity rule. Resolve SQL route names and declaration store names at their comparison boundaries. The scorer already independently derives release IDs from fixture files; retain that independence rather than importing the graph importer or checker as the expectation source.

Add literal route/store IDs to all 34 existing oracle obligations. Verify them from release files and the documented identity convention, without deriving expected outcomes from runtime output. Validate required fields and uniqueness of each full key before converting oracle rows into sets/dicts. Update `evals/expected/README.md` with the identity convention and migration method.

### 2. Add an isolated, authored fixture variant and expectations

Keep the current shop behavior and cases A–H as the baseline. Add a small checked fixture overlay under `tests/fixtures/obligation_identity/`, plus independently authored cases in `evals/expected/obligation_identity.json`. A test helper copies the shop into `tmp_path` and applies the overlay before any importer/control/scorer reads it. All consumers receive the same resulting root. Reuse existing snapshot names so no product snapshot enum or dataset switch is needed.

The variant should contain one release with two routes reading the same store and a third route reading a second store. Reuse a record ID across stores with different retained bytes. Give the two same-store routes distinct reviewed reader entries, including a record that passes one reader and fails the other. Keep coverage complete and writer/format metadata known so the identity regression has no unrelated gaps.

Author exact obligation lists, per-route probe predictions and dispositions from the declarations, codec control flow and payload bytes. Include a passing candidate and a blocked candidate. Confirm predictions directly with the fixture harness, and check overlay/release hashes deterministically. Expected outcome files remain outside runtime imports.

This one small variant exercises both collision paths. Its fixed bytes also make canonical route IDs reproducible. It needs no Kafka, new provider, live model call or product dataset configuration.

### 3. Fix acceptance and SQL parity

- Update every obligation, probe-result and failing-obligation comparison in `tests/test_acceptance_oracle.py` to the full key. Check unique cardinality as well as equality, so conversion to a set cannot hide duplicate rows.
- Parameterize acceptance setup for the baseline and overlay oracle/root. Replace the acceptance test's `case_id == "A"` import assumption with explicit import state per fixture root; use isolated graph names and guaranteed cleanup.
- Preserve SQL's existing six-column result contract where possible: it already includes version, route name, store and record. Normalize its projection into the full evaluation key rather than introducing an unnecessary SQL schema migration.
- Update the relational CLI comparison, mismatch reporting, summary wording and `tests/test_relational_control.py`. Factor its comparison loop to accept a fixture root/oracle path for reuse by the variant integration test, with existing defaults preserved.
- Require SQL = graph = independent oracle for both baseline and variant cases, with exact counts. Retain existing gap and naive rollback checks.

### 4. Make the flat control's probe selection explicit

- Retain canonical route IDs while loading release declarations; index retained records by `(store_id, record_id)` instead of record ID alone.
- Change the probe interface to require `service`, `version`, `route_id`, `store_id`, `record_id`. Resolve all five against trusted declarations and the selected manifest. Reject unknown IDs, foreign-release routes and route/store mismatches before running a subprocess. Remove first-match route selection.
- Update the neutral tool specification, both provider renderings, dispatcher, system prompt and usage examples. Include trusted canonical identity mappings in flat context so the model can select content-derived route IDs without calculating hashes. Give each mapping file-backed provenance; disclose no payload bytes or predicted outcomes.
- Carry both IDs through tool arguments, audit events and saved `probe_calls`; increment `control_version` for the changed interface. Preserve subprocess bounds, payload-hash checks and existing error behavior.
- Make transcript source-path labels support fixture roots outside the repository, matching `flat_context`'s existing fallback. The current `context_files` recording uses unconditional `relative_to(REPO_ROOT)`, which would fail for the proposed temporary fixture. Record its file hashes as usual.
- Update direct-call tests and fake Gemini/Groq transcripts. Verify each route dispatches its declared entry and duplicate record IDs select the correct store's bytes.

### 5. Migrate the scorer end to end

Update `fixture_index`, `oracle_index`, `reader_obligations`, `derived_disposition`, `run_from_control`, `runs_from_report` and `score_run` to retain/use the five-field key. Specifically:

- Keep route identities in fixture metadata and prediction lookup. Include the snapshot in prediction indexing as well, preventing the same route/store/record with different snapshot bytes from overwriting a prediction. Reject conflicting expectations within the same snapshot/key.
- Extract control identity from recorded validated calls. Extract product identity directly from obligation tuples, resolving only the version from fixture release metadata. A missing or mismatched route/store earns no credit for another obligation.
- Credit a probe only to its exact required key; one result cannot satisfy two routes. Keep missing predictions unresolved. Deduplicate retries only within a complete identity, preserving the prevailing result rules on the integration base.
- Replace hard-coded critical cart/checkout triples with full required-key selection for the proposed version and critical record. If several routes/stores qualify, report their coverage explicitly and mark complete only when all applicable keys were probed.
- Update recall labels, notes, docstrings and JSON/Markdown explanations to name the complete identity. Update existing scorer tests in `tests/test_llm_control.py`; add focused tests in `tests/test_score_controls.py` (or extend that file if PR #21 has landed).
- For historical transcripts lacking route/store, infer only when the recorded service/version/record resolves to exactly one declared route/store obligation in the identified fixture/snapshot. Mark that inference in notes. Ambiguous or invalid legacy calls receive no credit; never expand one old call into several probes. New transcripts always record both IDs. Preserve historical live-result files and their original rubric labels.

### 6. Verify the acceptance boundary and update current documentation

Required regression checks:

1. Both same-store routes survive enumeration; removing either expected/observed route causes an exact-set or recall failure.
2. Two stores with the same record ID retain separate obligations and dispatch different bytes; wrong-store evidence cannot discharge either obligation.
3. A passing route cannot hide a failing route on the same record; the blocked candidate remains BLOCKED. A fully probed passing candidate has complete recall.
4. Baseline cases A–H retain their dispositions, per-obligation predictions and gap kinds after adding identity fields.
5. Oracle and SQL integration use the real FalkorDB pipeline; scorer integration consumes the resulting product report and an offline scripted control transcript for that same fixture/candidate. Both complete and deliberately incomplete evidence are scored.
6. Tool schemas, dispatch and saved transcripts round-trip both IDs through both provider adapters. No live provider quota is needed.
7. Unique legacy calls can be interpreted with an explicit note; ambiguous legacy calls cannot inflate recall. Snapshot-specific expectations do not overwrite one another.

Run the focused oracle, relational, LLM-control and scorer tests first. Then run the repository's non-live suite and deterministic smoke against a ready FalkorDB instance:

```sh
.venv/bin/python -m pytest -q tests/test_acceptance_oracle.py tests/test_relational_control.py tests/test_llm_control.py tests/test_score_controls.py -m "not live"
.venv/bin/python evals/relational_control.py
.venv/bin/python -m pytest -q -m "not live"
.venv/bin/python scripts/smoke.py
git diff --check
```

The new variant is included in the parameterized tests; the SQL CLI's existing defaults continue to check the baseline. Run the existing CI matrix, including its MCP leg, without redesigning CI. Update `evals/README.md`, `evals/expected/README.md` and the relevant current `docs/STATUS.md` evidence entry with the full identity rule, variant coverage, commands and actual observed results. Adjust other current descriptions only where their pair/triple wording or counts becomes inaccurate.

## Completion boundary

Complete when all five issue-listed locations retain full identity, the additional relational test no longer compares pairs, baseline and variant oracle/SQL/scorer gates pass, and incomplete route/store evidence visibly reduces coverage. Product receipt binding and PR #21's separate safeguards must remain intact after integration.

Keep Astronomy Shop, dataset switching, Kafka read domains, comparison fairness/clarification, grounding rubric changes, live comparison runs and startup/CI redesign in their own issues. No product UI, approval or simulation changes are needed unless the new focused regression demonstrates a concrete runtime defect.
