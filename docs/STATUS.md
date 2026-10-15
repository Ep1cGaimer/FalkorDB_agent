# Build status

Updated 2026-10-15 by the orchestrator (Opus 5.5). Product: **RollbackWitness**, build mode. Synthetic fixture only.

## Verified (commands actually run)

| Milestone | Evidence |
|---|---|
| Runtime | Docker Desktop was stopped (cause of earlier "missing pipe" failures); started it. `falkordb/falkordb:6.0.2` pulled (tag has no `v`; `latest` is the separate v4.22.1 line), digest `sha256:107455e862a8…`, module ver 60002, Redis 8.10.2, container `rw-falkordb` on `127.0.0.1:6379` only. `.venv` = Python 3.12 via uv with project-local cache; falkordb-py 1.8.0. |
| FalkorDB behavior | params, `ro_query` write rejection, no APOC, **null properties are not stored** (unknowns are detected by manifest comparison, never stored as null). |
| Contracts frozen | `docs/CONTRACTS.md`, `src/rw/contracts.py` before parallel writers. |
| Fixture | `fixtures/shop/` (DeepSeek): cart 1.4/1.5, checkout 2.0/2.1, one `cart-cache`, retained records 1001 (cart/v1) and 2002 (cart/v2), negative snapshots partial/orphan; deterministic rebuild; `health()` startup entry added by orchestrator. |
| Graph | `src/rw/graph.py` (DeepSeek): importer + fixed parameterized queries, cap+1 truncation; 8 live integration tests, mutation-checked (dropping each edge type fails ≥1 test). |
| Checker | `src/rw/verification.py` (Opus): obligations from the FalkorDB multi-hop path, cross-checked against independent manifest × routes; fail dominance; gaps → NEEDS_EVIDENCE. |
| Probes / simulator / API | `probes.py`, `simulation.py`, `api.py` (Sol): hash-checked bounded subprocess probes; approval only for BOUNDED_PASS, stale/mutated refusal, idempotent SQLite simulation; step-wise FastAPI. |
| Independent oracle | `evals/expected/dispositions.json` (Astra, authored without running src/): 8 cases A–H. |
| End-to-end acceptance | `tests/test_acceptance_oracle.py`: real FalkorDB + real readers match the oracle on **8/8** cases (disposition, exact obligation set, per-obligation probe result, gap kinds, witness path). Case A: cart 1.4 reader × saved-cart-2002 → FAIL exit 10 `unsupported saved-cart format 'cart/v2'` → BLOCKED. Case B (cart 1.5, `basket_v2=false`) → BOUNDED_PASS. |
| Relational control | `evals/relational_control.py` (DeepSeek): SQL joins over the same raw facts reproduce FalkorDB's obligation sets on 8/8 cases — **a tie** (representational parity, reported as such). |
| Test suite | `.venv/Scripts/python.exe -m pytest -q -m "not live"` → 122 passed. |

## Blocker: live LLM from this machine

`GEMINI_API_KEY` is the only model credential in the environment. `generateContent` for gemini-3.8-flash/3.7/3.6/3.5/2.5-pro/3.1-pro fails almost always with TLS record corruption (`SEC_E_MESSAGE_ALTERED` / `SSLV3_ALERT_BAD_RECORD_MAC`, also through Docker's network) or 503 high demand; short GETs to the same host succeed; `gemini-3.1-flash-lite` answers normally. Grounding is being made configurable (`RW_GROUNDING_MODEL`) and records the model that actually answered. No live grounding result is claimed until observed.

## In progress

Grounding adapter live run (Sonnet), evidence UI (Sonnet), flat-context LLM control (DeepSeek), adversarial correctness review (Astra).

## Not done / limits

Live grounding with the intended model; UI; LLM-control scores; holdout wording; visual review; reproducible quickstart doc. BOUNDED_PASS = modeled byte/shape readability only. Nothing committed yet.
