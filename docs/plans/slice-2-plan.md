# Slice 2 plan — harden evidence, reliable live agent, demo-ready

Spec: `AGENTS.md`, `ROLLBACKWITNESS_IDEA.md`, `docs/CONTRACTS.md` (binding). Review input: `evals/reviews/astra-01.md` (findings F1–F8 referenced below by number).
Branch: `build/slice-2`. Python: `.venv\Scripts\python.exe` (3.12). FalkorDB 6.0.2 at `127.0.0.1:6379` (container `rw-falkordb`). Never install packages unless a task says so.

## Global Constraints

- Trusted code owns identity, query templates, limits, completeness, probes, receipt applicability, disposition, approval and idempotency. The LLM only proposes existing-artifact fleets or clarifications.
- Disposition precedence (unchanged): any applicable FAIL → `BLOCKED`; else any gap → `NEEDS_EVIDENCE`; else `BOUNDED_PASS` (byte/shape readability of modeled records only).
- Unknown evidence must never become a pass. Missing edges, nulls, caps and contradictions surface as `Gap` rows.
- No compatibility verdicts in fixtures or graph. Expected outcomes live only under `evals/expected/` and are read only by tests.
- Never store null in FalkorDB properties (FalkorDB 6.0.2 drops them); detect unknowns by comparison with independently parsed files.
- All Cypher is fixed and parameterized; no user/model text in query strings, graph names or file paths.
- Every existing test must keep passing: `.venv\Scripts\python.exe -m pytest -q -m "not live"` (163+ tests at BASE). Tests needing the server use a unique graph name `rw_test_<hex8>` and delete it.
- Commit each task on `build/slice-2` with a message ending in the line `Co-Authored-By: <your model name> <noreply@example.com>`. Do not push. Do not edit files outside the task's file list.
- Secrets: `.env` holds `GROQ_API_KEY` (and the environment may hold `GEMINI_API_KEY`). Never print, log, commit or write a key into transcripts/reports.

## Task 1: Checker reads release declarations independently (F1, F3)

Files: `src/rw/contracts.py` (additive only), `src/rw/verification.py`, `src/rw/pipeline.py`, `tests/test_verification.py`.

Problem: the checker trusts the graph's route set and route fields. Dropping one of two `EXECUTES_ROUTE` edges hides a failing reader (F1); changing a route's `entry` in the graph to `health` turns BLOCKED into BOUNDED_PASS (F3).

Implement:
1. `contracts.py`: add enum member `GapKind.ROUTE_DECLARATION_MISMATCH = "ROUTE_DECLARATION_MISMATCH"`. No other contract changes.
2. `verification.py`: new function `load_release_declarations(fixture_root: Path) -> dict[str, dict]` that, for every directory `fixture_root/releases/*/`, computes `artifact_hash = h([[relpath, bh(bytes)] for every file in the dir, sorted by posix relpath]])` exactly per CONTRACTS.md "Identity rules" (skip `__pycache__` dirs and `*.pyc`), `release_id = "release:<service>:" + short(artifact_hash)`, parses `release.json`, and returns `{release_id: {"service", "version", "artifact_hash", "codec_path" (posix, relative to repo root), "codec_hash": bh(codec.py bytes), "routes": {route_id: route_dict}, "no_state_read": bool}}` where `route_id = f"route:{release_id}:{route['name']}"` and `route_dict` is the route object exactly as in release.json. It must not import `rw.graph`.
3. `build_evidence(...)`: add a required keyword parameter `declarations: dict[str, dict]`. For each plan fleet entry:
   - release_id absent from `declarations` → `Gap(INVALID_FLEET, release_id, "no independently loaded declaration for this release")`.
   - Compare the set of declared route IDs with the set of graph route IDs (from `route_rows`) for that release: each declared-but-missing route → `Gap(ROUTE_DECLARATION_MISMATCH, route_id, "declared route missing from graph")`; each graph-only route → `Gap(ROUTE_DECLARATION_MISMATCH, route_id, "graph route not declared by the release")`.
   - For each route present in both: compare graph `entry`, `read_domain`, `store_id` (must equal `"store:" + reads_from`), `route_name`, and `route_contract_hash` (must equal `h(route_dict)` recomputed from the declaration). Any difference → `Gap(ROUTE_DECLARATION_MISMATCH, route_id, "<field> differs: graph=<g> declared=<d>")`. Also compare graph `codec_hash` with the declaration's `codec_hash` → mismatch gap with subject = release_id.
   - The expected (route, record) pair set must be computed from **declared** routes (store from `reads_from`) × records, not graph routes, so a missing graph route leaves its pairs reported as missing.
   - Obligation tuples must take `route_contract_hash`, `codec_hash`, probe entry (`reader_entry`) and `reader_codec_path` from the **declaration**, never from graph rows.
4. `pipeline.py` `Session.verify`: load declarations once per verify via `load_release_declarations(FIXTURE_ROOT)` and pass them in.
5. Tests in `tests/test_verification.py` (hand-built rows like the existing tests; extend the existing helpers rather than duplicating them): (a) two declared routes for cart, graph rows only contain one → NEEDS_EVIDENCE with a `ROUTE_DECLARATION_MISMATCH` "declared route missing from graph" gap and the missing route's pairs in an `INVENTORY_MISMATCH` gap; (b) graph route `entry="health"` while declaration says `read_cart` → `ROUTE_DECLARATION_MISMATCH` gap and obligation `reader_entry == "read_cart"`; (c) graph `route_contract_hash` tampered → gap; (d) release missing from declarations → INVALID_FLEET; (e) a real-fixture test: `load_release_declarations(REPO_ROOT/"fixtures"/"shop")` returns exactly 4 releases whose IDs equal those produced by `rw.graph.reset_and_import` on a temp graph (exact set equality).
Acceptance: full non-live suite passes, including `tests/test_acceptance_oracle.py` 8/8 unchanged.

## Task 2: Manifest reconciliation, fresh manifest, snapshot binding, grounding errors, capped summary (F5, F6, F7, F8)

Files: `src/rw/contracts.py` (additive only), `src/rw/verification.py`, `src/rw/pipeline.py`, `tests/test_verification.py`, `tests/test_pipeline.py` (new).

Implement:
1. F8 — `contracts.GraphEvidence`: add fields `snapshot_id: str = ""` and `snapshot_manifest_hash: str = ""`. `build_evidence` sets them from the plan's `snapshot_id` and the `manifest_hash` argument. `dispose` must take snapshot binding from `evidence.snapshot_id` / `evidence.snapshot_manifest_hash`, never from the first obligation. Test: zero-obligation complete evidence → `VerificationResult.snapshot_id` and `snapshot_manifest_hash` non-empty.
2. F6 — in `build_evidence`, for each record present in both manifest and graph: resolve the manifest writer `{service, version}` to a release_id using `declarations` (match on service+version). Manifest writer `null` → `WRITER_UNKNOWN` gap (even if the graph has a writer edge). Manifest writer resolvable but different from graph `writer_release_id` → `WRITER_UNKNOWN` gap with detail `"writer contradiction: graph=<g> manifest=<m>"`. Manifest writer not resolvable to any declared release → `WRITER_UNKNOWN`. Format: treat `None`, `""` and the literal `"UNKNOWN"` as unknown on either side → `FORMAT_UNKNOWN`; manifest format ≠ graph format → `FORMAT_UNKNOWN` with `"format contradiction"` detail. Emit at most one WRITER_UNKNOWN and one FORMAT_UNKNOWN gap per batch.
3. F5 — `Session.verify` must re-read the manifest from disk (`load_manifest`) at verification time and use the fresh bytes/hash for `build_evidence`; if the fresh hash differs from `plan.snapshot_manifest_hash` the existing STALE_SNAPSHOT gap must appear. Remove reliance on the cached `self.manifest` inside `verify` (keep the attribute for display).
4. F7 — `run_investigation`: if `grounding.validation_errors` is non-empty and the result is a proposal, record them in the attempt as `validation_errors`, set outcome `"REJECTED_PROPOSAL"`, and do not call `confirm` or `verify`.
5. `summarize_for_agent(report)`: cap output — list every FAIL obligation and every gap (max 20 lines each, then `"... and N more"`), then one line `"PASS: <n> obligations"`. Never list PASS obligations individually.
6. `tests/test_pipeline.py`: F7 via a fake `ground` returning a proposal with a validation error → outcome REJECTED_PROPOSAL and `confirm` never called; F5 via a `Session` on a temp graph whose fixture root is a tmp copy of `fixtures/shop` (add an optional `fixture_root: Path | None = None` parameter to `Session.__init__`, default `FIXTURE_ROOT`; store it and use it in `verify`), mutate the copy's manifest coverage to PARTIAL after building the plan → verification contains STALE_SNAPSHOT; summarize cap test with 50 synthetic FAIL obligations → ≤ 22 FAIL-section lines.
Acceptance: full non-live suite passes; oracle 8/8 unchanged.

## Task 3: Evidence revalidation before approval and simulation (F4, checker side)

Files: `src/rw/verification.py`, `tests/test_verification.py`.

Implement `revalidate(verification: VerificationResult, fixture_root: Path, environment_hash_fn, probe_spec_fn) -> list[str]` (both hashes already include the harness hash) returning human-readable drift errors (empty list = current). Checks: (1) fresh `bh(manifest.json)` for `verification.snapshot_id` equals `verification.snapshot_manifest_hash`; (2) for every obligation: payload file bytes (resolve via the fresh manifest record `payload` path for `tuple.record_id` in store `tuple.store_id`) hash equals `tuple.payload_hash`; `bh(reader codec file)` equals `tuple.codec_hash`; `environment_hash_fn()` equals `tuple.environment_hash`; `probe_spec_fn(obligation.reader_entry)` equals `tuple.probe_spec_hash`; (3) `fixture_root/releases` declarations still contain `tuple.release_id` with the same route contract hash for `tuple.route_id`. Missing files are drift errors, not exceptions. Tests with a tmp copy of the fixture: unchanged → `[]`; payload byte change → error naming the record; codec change → error; manifest change → error; environment function returning a different value → error.
Acceptance: full non-live suite passes.

## Task 4: Harness result channel that reader code cannot impersonate (F2)

Files: `fixtures/shop/harness/run_reader.py`, `src/rw/probes.py`, `tests/test_probes.py`, `tests/test_fixture_readers.py`.

Implement:
1. `probes.run_probe` generates `nonce = secrets.token_hex(16)` per run and starts the harness with env `{"RW_PROBE_NONCE": nonce, "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("PATH", "")}` (no other inherited variables).
2. Harness: first statement in `main` pops `RW_PROBE_NONCE` from `os.environ` (missing → HARNESS_ERROR exit 20). Save the real stdout fd with `saved = os.dup(1)`, then `os.dup2(2, 1)` and set `sys.stdout = sys.stderr` before loading the codec, for the whole load + entry call, so all reader output (including `os.write(1, ...)`) goes to stderr. Catch `BaseException` around module load and around the entry call: `SystemExit`/`KeyboardInterrupt`/`GeneratorExit` during either → HARNESS_ERROR exit 20; ordinary `Exception` during the entry call → FAIL exit 10; non-dict return → FAIL exit 10. Write exactly one JSON line (sort_keys) including `"nonce": nonce` to `saved` via `os.write(saved, line.encode() + b"\n")`, then `os._exit(code)`.
3. Parent (`run_probe`): stdout must decode to exactly one non-empty line, parse to a dict whose `nonce` equals the generated nonce; PASS requires exit 0, `status == "PASS"` and `shape` a dict; FAIL requires exit 10, `status == "FAIL"`, string `error_type` and `message`; anything else → UNKNOWN with message `"harness error or invalid stdout"`. `stderr` stays discarded.
4. Tests (tmp_path codecs + a copy of the real harness, as existing tests do): reader prints `{"status":"PASS","shape":{}}` then `sys.exit(0)` → UNKNOWN; same without shape → UNKNOWN; reader does `os.write(1, b'{"status":"PASS","shape":{}}\n')` then returns a dict → PASS only via the harness line (exactly one line seen by parent) — assert result PASS and that the parent-visible stdout has one line containing the nonce; reader raising → FAIL; real fixture cart-1.4 on saved-cart-2002 → FAIL and on saved-cart-1001 → PASS. Update `tests/test_fixture_readers.py` harness invocations to pass a nonce env and check the nonce in output.
Acceptance: full non-live suite passes (probe_spec/environment hashes change with the harness bytes — expected).

## Task 5: API gates approval and simulation on revalidation (F4, API side)

Files: `src/rw/api.py`, `tests/test_api.py`.

Implement: in both `/approve` and `/simulate` handlers, call `verification.revalidate(<stored VerificationResult>, <session fixture root>, ...)` passing `rw.probes.environment_hash` and `rw.probes.probe_spec_hash` as the two functions. Non-empty → HTTP 409 with detail `{"reason": "evidence changed since verification; re-verify and re-approve", "drift": [...]}`. Never substitute a new verification. Use the `fixture_root` the session was built with (Task 2 adds `Session(fixture_root=...)`). Test: session on a tmp copy of the fixture; verify a BOUNDED_PASS plan (cart 1.5 basket_v2=false); change one payload byte in the copy; approve → 409 with drift naming the record; restore, approve OK, change payload, simulate → 409.
Acceptance: full non-live suite passes.

## Task 6: Groq provider for the grounding agent

Files: `src/rw/config.py` (new), `src/rw/grounding.py`, `tests/test_grounding.py`, `scripts/investigate.py` (only the model-chain print line), `scripts/serve.py` (only to call `config.load_env()` at startup).

Implement:
1. `src/rw/config.py`: `load_env(path: Path = REPO_ROOT/".env") -> None` — minimal parser (lines `KEY=VALUE`, ignore blanks/`#`, strip optional quotes), sets `os.environ` only for keys not already set. No dependency.
2. `grounding.py`: model chain from env `RW_GROUNDING_MODEL`, comma-separated entries `provider:model`; default `"groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b"`. Entries without a provider prefix are treated as `gemini:`. Add a Groq transport using the OpenAI-compatible Chat Completions API at `https://api.groq.com/openai/v1/chat/completions` (Bearer `GROQ_API_KEY`, httpx, TLS max 1.2 like the existing Gemini transport, temperature 0, `tool_choice: "auto"`), with the same retry/backoff, `Retry-After` handling and whole-conversation restart on the next chain entry. Keep the provider-neutral loop: convert the existing tool declarations to OpenAI `tools` format and tool results to `{"role":"tool","tool_call_id":..., "content": json}` messages; the assistant message with `tool_calls` must be appended verbatim before tool replies. Record `provider:model` actually used in `GroundingResult.model` and the transcript; record abandoned attempts (model + error) in the transcript. `replay()` must work for Groq transcripts.
3. `scripts/investigate.py` and `scripts/serve.py`: call `config.load_env()` before anything reads env; investigate prints the chain from the same default as grounding (import the default constant).
4. Tests with fake transports: OpenAI-format tool-call round trip to a proposal; unknown tool → error message back to model; chain fallback from a failing groq entry to the next; transcripts never contain the API key (assert the key string is absent from the saved JSON when a fake key is set in env).
Acceptance: unit tests pass; then run `.venv\Scripts\python.exe -m pytest tests\test_grounding.py -m live -q` with the default chain and record the real result (model that answered, outcome) in the report. Never claim a live result you did not observe.

## Task 7: Grounding quality pass + repeatable grounding eval

Files: `src/rw/grounding.py` (SYSTEM_PROMPT text and alternative-context handling only), `evals/grounding_cases/requests.json`, `evals/grounding_cases/expected.json`, `evals/run_grounding_cases.py` (new), `tests/test_grounding.py`.

Implement:
1. Prompt: require that each release kept or changed is supported by a `changelog` excerpt describing behavior; code excerpts may supplement but a version string alone (e.g. a `health()` return value) is not evidence. Keep every existing rule. Do not mention fixture-specific answers (no "cart/v2", no "basket_v2 off is safe").
2. `requests.json`: keep the 3 existing cases; add `{"id": "named-old-build", "text": "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction."}` and `{"id": "keep-everything", "text": "Undo the receipt correction but keep the basket rollout."}`. `expected.json` gets independent expected kinds with reasoning (never imported by `src/`).
3. `evals/run_grounding_cases.py`: for each case run the real grounding loop N times (`--runs`, default 3) against a temp graph imported from the fixture (delete after), save transcripts, and print a markdown table: case, run, model, kind (PROPOSAL/CLARIFICATION/ABORTED), proposed fleet (service→version+flags), citation kinds (changelog/code), validation errors, matches expected kind. Also write the table to `evals/results/grounding_<timestamp>.md` (git-ignored dir).
4. Unit test: the runner's table builder on a hand-made transcript list.
Acceptance: unit tests pass; run `.venv\Scripts\python.exe evals\run_grounding_cases.py --runs 2` live and paste the real table in the report.

## Task 8: Evidence UI to the agreed design

Files: `src/rw/static/index.html`, `src/rw/api.py` (the new `/answer` endpoint plus any missing read-only field), `tests/test_api.py` (tests for those additions).

Implement the agreed single-screen design (see `docs/plans/slice-2-ui.md`): investigation order request → agent question (with answer box wired to a new `POST /api/investigations/{id}/answer {answer}` that re-grounds with `pipeline.with_answer`) → proposed fleet with version labels (`release_labels`) and anchored quotes → scope confirmation → verdict + GREEN-vs-FAIL contrast pair as the dominant element → witness chain → reader×record matrix with receipt drawer → alternative comparison → action section rendered only for BOUNDED_PASS. Replay picker from `GET /api/transcripts`; "REPLAY — not live" banner; model actually answered in the header; SYNTHETIC FIXTURE label always visible; BOUNDED_PASS caption always visible. "Guided demo" toggle pre-fills answer text, operator and approver names (values from a small JS constant; no fake results). Typography: one heading face + one monospace via system font stacks; hashes hidden behind short forms with click-to-expand; color only for verdict semantics (red FAIL/BLOCKED, green PASS/BOUNDED_PASS/GREEN, amber NEEDS_EVIDENCE/UNKNOWN). No external assets.
Acceptance: start `scripts/serve.py`, drive the flow in replay mode via a saved transcript and live mode once; save screenshots under `artifacts/screens/slice2-*.png` (1280 and 1920 widths); report exactly what was observed.

## Task 9: Reproducible setup and docs

Files: `.gitattributes` (new), `docker-compose.yml` (new), `scripts/setup.ps1` (new), `scripts/setup.sh` (new), `README.md` (product section only — keep existing hackathon text), `docs/CONTRACTS.md` (update probe protocol, GapKind list, GraphEvidence fields, grounding providers), `docs/STATUS.md`.

Implement: `.gitattributes` with `fixtures/** -text` and `*.bin binary` so fixture bytes/hashes never change on checkout; `docker-compose.yml` pinning `falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`, ports `127.0.0.1:6379:6379` and `127.0.0.1:3000:3000`, container name `rw-falkordb`; setup scripts create `.venv` with uv (`UV_CACHE_DIR=.uv-cache`, Python 3.12) and install pinned deps from `pyproject.toml`; README quickstart: compose up → setup → `pytest -m "not live"` → `scripts/investigate.py ...` → `scripts/serve.py`, with expected outputs described truthfully and the synthetic/replay labels. Verify by running the commands in a fresh clone of the branch into a temp dir (do not touch the main checkout's `.venv`), and paste real outputs.
Acceptance: fresh-clone run of setup + non-live tests passes; hashes of `fixtures/shop/snapshots/*/manifest.json` in the fresh clone equal those in the main checkout.
