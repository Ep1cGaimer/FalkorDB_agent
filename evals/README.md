# Evaluation assets

Independent expectations and controls, kept outside runtime application inputs. Do not import answer
files into `src/rw/`, and do not tune a holdout to accommodate a failing implementation.

- `expected/` — independent oracles: `dispositions.json` (8 hand-derived cases A–H, 34 obligations), `obligation_identity.json` (cases I–J, 14 obligations over a test overlay), and their method write-up.
- `grounding_cases/` — live grounding eval cases: `requests.json` in, `expected.json` (hand-written, documentation only) alongside.
- `run_grounding_cases.py` — runs every request through the real grounding loop on a fresh temporary graph and prints the observed outcomes.
- `relational_control.py` — SQL joins over the same raw facts, deriving the same obligation sets as a fair, un-handicapped control.
- `llm_control.py` — equal-information flat-context control: the same model chain and transports, no graph and no Cypher.
- `score_controls.py` — scores saved product reports and control transcripts against the oracle (fleet match, obligation recall, false passes). A claim counts as oracle-consistent only when its own probe results support it: BOUNDED_PASS needs a PASS on every required (service, version, route, store, record) key, BLOCKED needs an observed FAIL. UNKNOWN probes are reported separately, and an *unsupported* BOUNDED_PASS is counted apart from a *false* one (oracle says not readable). A product receipt counts only when its tuple equals the obligation's tuple exactly; repeated results for one key fold FAIL > UNKNOWN > PASS.
- `flat_grounding.py` — complete raw files plus importer-derived citation addresses, followed by the same trusted `run_investigation` / `Session` checker as graph grounding. No graph read, oracle or probe is available during flat grounding.
- `run_comparison.py` — three arms in rotated blocks: `graph_grounding_checker`, `flat_grounding_checker`, and legacy `flat_assessment`. One pinned model, eight turns, temperature zero, the same completion cap and retry policy. Each observation is checkpointed; operational failures stop collection and leave remaining slots unrun. Rejected proposals, adverse verdicts and genuine clarification remain observations. No alternative conversation, clarification answer, approval or simulation is granted.
- `relationship_ablation.py` — removes exactly two snapshot `IN_STORE` edges from owned disposable graphs. Nodes and raw files survive; connected reader–record obligation enumeration and witness paths disappear, and the unchanged checker fails closed. Restoration recovers the original results. SQL can independently reconstruct these pairs.
- `comparison_evidence.py` — exports allowlisted portable evidence, including all fixture/expectation bytes needed for offline rescoring. Strict validation rejects missing, extra, tampered, duplicate and unsafe entries. Generated evidence is excluded from source hashes.

Collect only after the offline suite passes. Use a dedicated FalkorDB on port 6382 (the standard test suite uses 6379); run database tests and live collection serially. Load keys from an ignored `.env` (`GEMINI_API_KEY` or `GROQ_API_KEY`). Gemini uses the same product HTTP retry/TLS helper with an evaluation observation hook; its completion cap is applied as `generationConfig.maxOutputTokens`. Pick a new batch directory for every invocation, retaining incomplete attempts separately; never retry a whole conversation to improve its semantic outcome.

```sh
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 \
  .venv/bin/python evals/run_comparison.py --runs 3 --model gemini:gemini-3.1-flash-lite \
  --db-port 6382 --out artifacts/issue-22/BATCH
.venv/bin/python evals/relationship_ablation.py --db-port 6382 --out artifacts/issue-22/BATCH/ablation
.venv/bin/python evals/comparison_evidence.py export --input artifacts/issue-22/BATCH \
  --out evals/evidence/issue-22/BATCH
.venv/bin/python evals/comparison_evidence.py verify evals/evidence/issue-22/BATCH
.venv/bin/python evals/score_controls.py --bundle evals/evidence/issue-22/BATCH --json /tmp/scores.json
```

The primary result uses aligned completed blocks of the two shared-checker arms, with equal denominators. Legacy results have their own table. Every failed/unrun slot remains visible. Clarification has no readability denominator; its appropriateness is ungraded. Request fit and readability are separate: unchanged deployments can be readable without satisfying the requested rollback. Cross-service basket behavior is outside the byte/shape checker. A tie or flat-control win is reported literally.

Each manifest records collection revision/dirty inventory, source and expectation hashes, schedule and completion; observations preserve exact requests (including prompts, tools and delivered history), returned identity, attempts, validation events, provider-reported numeric usage, unknown usage, monotonic timing and verified graph cleanup. Provider transport retries stay within one observation. Request elapsed time includes retries/backoff; individual backoff durations are unavailable. Tokens from unsuccessful requests remain unknown, never zero. No model aliases are assumed. The export drops provider envelopes, credentials, account metadata and local paths while preserving canonical evidence tuples; its artifact index excludes only the root manifest.

- `reviews/astra-01.md` — independent review of the pipeline, and the source of the F1–F8 tags used in test names.

Within one fixture/snapshot, evaluation compares the complete key
`(service, version, route_id, store_id, record_id)`. Route IDs are
`route:<content-derived-release-id>:<declared-route-name>`; store IDs are `store:<name>`.
This key is for evaluation; runtime receipts retain their complete existing binding tuple.
Oracle predictions additionally include the snapshot so different retained bytes cannot overwrite
one another's expectations.

The flat control's v6 protocol adds `ask_clarification` with validated questions, unresolved phrases and optional citations. Its probe tool requires all five fields. Its context includes file-backed canonical
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

Current issue #22 result: **3/3 tie** between matched arms; see the [verified primary bundle](evidence/issue-22/live-5a7160f-gemini31lite-05/comparison.md). Preliminary refusals and the superseded protocol are summarized in [STATUS](../docs/STATUS.md); only the final acceptance bundle is committed.
