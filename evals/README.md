# Evaluation assets

Independent expectations and controls, kept outside runtime application inputs. Do not import answer
files into `src/rw/`, and do not tune a holdout to accommodate a failing implementation.

- `expected/` — independent oracles: `dispositions.json` (8 hand-derived cases A–H, 34 obligations), `obligation_identity.json` (cases I–J, 14 obligations over a test overlay), and their method write-up.
- `grounding_cases/` — live grounding eval cases: `requests.json` in, `expected.json` (hand-written, documentation only) alongside.
- `run_grounding_cases.py` — runs every request through the real grounding loop on a fresh temporary graph and prints the observed outcomes.
- `relational_control.py` — SQL joins over the same raw facts, deriving the same obligation sets as a fair, un-handicapped control.
- `llm_control.py` — equal-information flat-context control: the same model chain and transports, no graph and no Cypher.
- `score_controls.py` — scores saved product reports and control transcripts against the oracle (fleet match, obligation recall, false passes). A claim counts as oracle-consistent only when its own probe results support it: BOUNDED_PASS needs a PASS on every required (service, version, route, store, record) key, BLOCKED needs an observed FAIL. UNKNOWN probes are reported separately, and an *unsupported* BOUNDED_PASS is counted apart from a *false* one (oracle says not readable). A product receipt counts only when its tuple equals the obligation's tuple exactly; repeated results for one key fold FAIL > UNKNOWN > PASS.
- `run_comparison.py` — same-model live comparison: runs the live control test once per pair, checks the product on disposable FalkorDB graphs, preserves pytest/JUnit evidence and saves the scorer output; stops at the first failed pair. A passing live test checks usable execution, not perfect interpretation or complete probe coverage.

  ```bash
  .venv/bin/python evals/run_comparison.py --runs 3 --model groq:gemini-3-flash
  ```
- `ablation_relationships.py` — Astronomy Shop: deletes graph relationship types while keeping every node and payload, and reruns the same fixed rollback check (no model). Shows which capability each relationship carries.
- `plaintext_vs_graph.py` — Astronomy Shop: one model call with the whole fixture as text vs the graph checker, on six designed cases.
- `reviews/astra-01.md` — independent review of the pipeline, and the source of the F1–F8 tags used in test names.
- `repo_*.py`, `repo_questions/`, `confirmatory/` — evaluation tooling for the secondary repository-evidence workflow. `confirmatory/` is an unfinished draft package; no confirmatory runs exist.

Within one fixture/snapshot, evaluation compares the complete key
`(service, version, route_id, store_id, record_id)`. Route IDs are
`route:<content-derived-release-id>:<declared-route-name>`; store IDs are `store:<name>`.
This key is for evaluation; runtime receipts retain their complete existing binding tuple.
Oracle predictions additionally include the snapshot so different retained bytes cannot overwrite
one another's expectations.

The flat control's v5 probe tool requires all five fields. Its context includes file-backed canonical
identity mappings alongside the release files and manifest; payload bytes remain behind the trusted
probe. Both provider adapters, tool audits and saved `probe_calls` preserve the IDs. Historical v1–v4
calls without either ID receive credit only when their service/version/record identifies exactly one
declared route/store obligation in that snapshot, with an explicit inference note. Ambiguous legacy
calls receive no credit. Original live transcripts and historical rubric labels are preserved.

`tests/fixtures/obligation_identity/` overlays a temporary copy of the shop. Both candidates read two
stores through three cart routes; `saved-cart-2002` appears in both stores with different bytes.
Case I remains BLOCKED when the legacy reader fails despite the inspection reader passing; case J
has complete passing coverage. Oracle/SQL/graph comparisons and offline scripted Gemini/Groq
transcripts exercise seven obligations per candidate. Removing any route/store observation lowers
scorer recall to `6/7`, and critical-record coverage requires all three applicable cart keys.

Run these checks against a ready FalkorDB instance (no live provider calls):

```sh
.venv/bin/python -m pytest -q tests/test_acceptance_oracle.py tests/test_relational_control.py tests/test_llm_control.py tests/test_score_controls.py -m 'not live'
.venv/bin/python evals/relational_control.py
.venv/bin/python -m pytest -q -m 'not live'
.venv/bin/python scripts/smoke.py
```

The SQL CLI defaults to the baseline; its reusable `compare(fixture_root, oracle_path)` is also
exercised against the overlay. The scorer accepts `--fixture-root` and `--oracle` for saved runs
against another fixture root. See [the oracle method](expected/README.md) for prediction provenance.

## Repository transport and graph diagnostics

`python evals/repo_transport_probe.py --isolated-db --out artifacts/repo_probes/<new-run-id>`
imports the configured development repositories, records multi-hop read queries and source hash
checks, removes/restores root dependency edges, marks extraction evidence stale, and injects a
transport interruption after real reads. It compares the same requests over the actual CLI, a
temporary TCP API, and concurrent calls on real MCP stdio sessions, including session restart,
incomplete/stale publications and malformed inputs. The isolated option uses the pinned Docker
image on a loopback-only assigned port and tests an actual owned-container stop/start. It never
stops the existing database. All owned services/indexes are cleaned up, and earlier output
directories are refused rather than overwritten.

The JSON record includes the source freeze, exact harness bytes/hash, read queries/parameters/rows,
transport requests/responses, failures and cleanup. The stopped-database case must expose an
INDEX_UNAVAILABLE gap. A stale relationship must not become an empty dependency answer.
These are inspected development cases with no live model calls or blind scoring; they establish
transport/causal diagnostics, not the full T7/T9 gates or comparative advantage.
