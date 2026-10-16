# Build status

Updated 2026-10-16 (Task 12: revalidate store scope + status sync). Each row names the task that ran
it; the smoke, operator-fleet and test-suite rows were re-run in Task 12 and carry its output.
Product: **RollbackWitness**, build mode, branch `build/slice-2`. Synthetic fixture only — no
production data, no deployment, nothing published or submitted.

Every row below is a command that was actually run, with its observed output. Nothing here is a plan
or an estimate.

## Verified (commands actually run)

| Milestone | Evidence |
|---|---|
| Runtime | `docker compose -f docker-compose.yml config` resolves to image `falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`, container `rw-falkordb`, ports `127.0.0.1:6379` and `127.0.0.1:3000`. Running container: module ver 60002, Redis 8.10.2. `.venv` = Python 3.12 via uv with a project-local `.uv-cache`; client `falkordb` 1.8.0. |
| FalkorDB behavior | parameterized `$params` work; `ro_query` rejects writes; APOC absent; **a property set to `null` is not stored** — unknowns are detected by comparison with independently parsed files, never stored as null. |
| Contracts | `docs/CONTRACTS.md` + `src/rw/contracts.py` describe the current code: probe nonce/result channel, `GapKind` list, `GraphEvidence` fields, `build_evidence(declarations=…)`, `revalidate`, grounding providers, API endpoints. |
| Fixture | `fixtures/shop/`: cart 1.4/1.5, checkout 2.0/2.1, one `cart-cache`, retained records `saved-cart-1001` (cart/v1) and `saved-cart-2002` (cart/v2), plus the negative snapshots `snap-002-partial` / `snap-003-orphan`; deterministic rebuild via `scripts/build_fixture.py`. |
| Graph | `src/rw/graph.py`: importer + fixed parameterized queries, `cap+1` truncation; 8 live integration tests, mutation-checked (dropping each edge type fails ≥ 1 test). |
| Checker | `src/rw/verification.py`: obligations from the FalkorDB multi-hop path, cross-checked against the independently loaded declarations and the manifest read from disk; `ROUTE_DECLARATION_MISMATCH`; writer/format reconciliation; fail dominance; snapshot binding on the evidence; revalidation is scoped to the stores the fleet actually read, so a manifest store no route reads cannot invent writer drift. |
| Probes / simulator / API | `src/rw/probes.py`, `simulation.py`, `api.py`: per-run nonce result channel that keeps ordinary reader output and early exits out of the verdict (failure containment for allowlisted readers, not a sandbox), receipts bound to the exact obligation tuple, approval only for `BOUNDED_PASS` on current bytes (`revalidate` → HTTP 409 on drift), idempotent SQLite simulation, one clarification round via `POST /api/investigations/{id}/answer`. |
| Independent oracle | `evals/expected/dispositions.json` (authored without running `src/`): 8 cases A–H. `.venv\Scripts\python.exe -m pytest tests/test_acceptance_oracle.py -q` → **8 passed** on the real server with the real readers. Case A: cart 1.4 reader × `saved-cart-2002` → FAIL exit 10 `unsupported saved-cart format 'cart/v2'` → BLOCKED. Case B (cart 1.5, `basket_v2=false`) → BOUNDED_PASS. |
| Relational control | `.venv\Scripts\python.exe evals\relational_control.py` → `SQL obligations == FalkorDB obligations: 8/8 cases`, `SQL obligations == independent oracle: 8/8 cases` — **a tie** (representational parity, not superiority; the control is not handicapped). |
| Deterministic smoke (`scripts/smoke.py`) | `.venv\Scripts\python.exe scripts\smoke.py` → exit 0; creates graph `rw_smoke_9e3b9ec4` and deletes it in the same run. Checklist: `PASS snap-001 BLOCKED` (receipt `saved-cart-2002 ValueError: unsupported saved-cart format 'cart/v2'`; witness `(Plan)→-HAS_DEPLOYMENT->(Deployment cart)-RUNS->(Release cart 1.4)-EXECUTES_ROUTE->(ReaderRoute load_saved_cart)-READS_FROM->(StateStore store:cart-cache)<-IN_STORE-(Batch saved-cart-2002 (cart/v2))-WRITTEN_BY->(Release writer 1.5)`), `PASS blocked approval refused (HTTP 409)`, `PASS snap-001 BOUNDED_PASS`, `PASS approved as smoke-operator; simulate applied=true, repeat applied=false`, `PASS snap-002-partial NEEDS_EVIDENCE (COVERAGE_INCOMPLETE)`, `PASS snap-003-orphan NEEDS_EVIDENCE (FORMAT_UNKNOWN, WRITER_UNKNOWN)`, `PASS cleanup graph=rw_smoke_9e3b9ec4`, `PASS deterministic-smoke complete`. Grounding is injected and labeled `deterministic-smoke`, `live=false`: no model call, no key, temp SQLite ledger. Run standalone it prints the third-party Starlette/httpx deprecation notice (the one warning narrowly silenced inside pytest by `pyproject.toml`). |
| Operator-specified fleet (`scripts/investigate.py --fleet`) | `.venv\Scripts\python.exe scripts\investigate.py --fleet cart=1.4 --confirm-as tester` → exit 0; prints `[OPERATOR-SPECIFIED FLEET — no agent involved]`, resolves `cart 1.4 (release:cart:9703e568235e03f3)` from the graph, verifies with `model=operator-specified, live=False`, probes 4 obligations (`saved-cart-2002` fails with `unsupported saved-cart format 'cart/v2'`) and reports `DISPOSITION: BLOCKED` with the witness path. `--snapshot` selects the snapshot; an unknown service/version/flag exits 2 with nothing verified (Task 11 report). |
| Test suite | `.venv\Scripts\python.exe -m pytest -q -m "not live"` → **282 passed, 3 deselected** in 27.59 s, **0 warnings** (needs the container above). The 3 deselected tests call the live provider. |
| Reproducibility (fresh clone) | `git clone --branch build/slice-2` into a temp directory, with its own `.venv` and `.uv-cache` inside the clone (the main checkout's `.venv` untouched), then both setup scripts: `scripts/setup.ps1` under Windows PowerShell and `sh scripts/setup.sh` under Git Bash (`C:\Program Files\Git\bin\bash.exe`), each installing Python 3.12.10, the 21 packages from `pyproject.toml` and `pytest==9.1.1` (exit 0). `.venv\Scripts\python.exe -m pytest -q -m "not live"` → **229 passed, 3 deselected**, and `.venv\Scripts\python.exe -m pytest -q -m "not live" tests/test_acceptance_oracle.py` → **8 passed**. `docker compose -f <clone>\docker-compose.yml config` resolves the pinned image without starting a second container, and the three `fixtures/shop/snapshots/*/manifest.json` sha256 values in the clone equal the main checkout's (`416e1df3…`, `734cae65…`, `7e2947e4…`). |
| Slice-2 commits | `f8e4a7c` (T1), `3d3310d` (T2), `c8aad81` (T3), `eb4939e` (T4), `24ec745` (T5), `92acc5a` (T6), `103f5df` + `0bf177f` (T7), `a22b986` (T8), `1d82ec6` + `27b63aa` (T9); fix wave `bdf53cb` (C1), `12f0488` (C2), `4f60c6e` (I3), `8b1faaa` (I4+I5), `8ae1f0a` (I6), `6f74539` (I7), `498e983` (I8 + recovered minors); Task 10 UI/snapshot `a8a1b48` + `da08d55`; Task 11 smoke + operator fleet `52f5901`; Task 12 revalidate store scope `6f50450` + this status-sync commit. |

## Known limits (measured, not assumed)

- **Groq free tier.** `openai/gpt-oss-120b` allows 200k tokens/day and was exhausted during the
  slice-2 evaluation runs on 2026-10-15 (199,113 used); `qwen/qwen3.8-27b` allows 7000 input /
  1000 output tokens per minute and rejects the flat-context control prompt as "request too large".
  A live run can therefore fail fast with a non-retryable quota refusal (the chain records the
  abandoned attempt and tries the next entry).
- **Live grounding eval: 6/10 runs matched the expected kind** (`evals/results/grounding_20261015T205622Z.md`,
  git-ignored: 5 cases × 2 runs, model `groq:openai/gpt-oss-120b`, chain default, temperature 0). The
  aggregate hides which case failed, so the case-level result is listed below; a kind match that also
  carries a validation error still counts as a match but is not clean grounding. This is a small-N
  single-machine observation, not a benchmark or a ranking.

  | case | expected kind | run 1 | run 2 | note |
  |---|---|---|---|---|
  | main | PROPOSAL | CLARIFICATION — miss | CLARIFICATION — miss | asked instead of proposing the requested change |
  | ambiguous | CLARIFICATION | PROPOSAL — miss | PROPOSAL — miss | proposed `cart=1.4` instead of asking which change |
  | inseparable | CLARIFICATION | match | match | run 1 cited a code quote absent from the excerpt (`CITATION_QUOTE_NOT_IN_EXCERPT`, dropped by validation) |
  | named-old-build | PROPOSAL | match | match | proposed `cart=1.4` |
  | keep-everything | CLARIFICATION | match | match | asked instead of proposing |
- **Flat LLM control has no live run today** — blocked by the quota above, not by a code defect. No
  control score is claimed.
- **Live model access from this machine is flaky for Gemini**: `gemini-3.8-flash` and larger fail
  almost always with TLS record corruption (`SEC_E_MESSAGE_ALTERED` / `SSLV3_ALERT_BAD_RECORD_MAC`) or
  503; pinning TLS 1.2 and retrying helps; `gemini-3.1-flash-lite` answers normally. The product
  default chain is Groq.
- **SQL control = tie** on obligation sets (8/8). Parity is reported as parity.
- **Synthetic fixture only.** No production data, and the "simulate" action writes a local SQLite
  record; it performs nothing.
- **`BOUNDED_PASS` = modeled byte/shape readability only.** It is not behavioral compatibility and
  not a claim that no other reader or writer exists.
- **UI screenshots are untracked** (`artifacts/screens/` is git-ignored; the images were removed from
  git in Task 8), so the console visuals must be regenerated locally.
- **Replay is labeled.** `model=replay:<file>` with `live=False` means a saved transcript was re-run.

## Not done / next

- Live grounding eval on a fresh quota; the flat-context LLM control live run; UI visual review at
  1280/1920; holdout wording for the report. No deployment, publishing, submission or third-party
  message has been made.
- **Live verification is DEFERRED.** The recorded 6/10 table above predates the ambiguity-handling rule
  added to `SYSTEM_PROMPT`, and no live model call was made to re-measure it — the Groq free tier was
  exhausted on 2026-10-15. The case-level table and the new rule are code-and-test evidence only; do
  not read them as a new live score.

Setup and demo commands for a reviewer: [QUICKSTART.md](QUICKSTART.md).
