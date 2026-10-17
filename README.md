# RollbackWitness

**Rolling back code does not roll back the data it wrote.**

A Graph Hacks 2026 project for the WeMakeDevs × FalkorDB “Context for AI Agents” hackathon.

An on-call engineer asks for a behavioral rollback — *"Undo the basket rollout, but keep the receipt correction."* RollbackWitness turns that into an exact fleet of existing release artifacts (or asks a precise clarification), uses FalkorDB to find every reader that fleet will run and every retained record those readers can meet, runs the real readers on the real stored bytes, and returns one of:

- **BLOCKED** — a concrete failure witness: this reader cannot read this saved record, with the receipt and the graph path that explains why.
- **NEEDS_EVIDENCE** — no failure found, but something required is missing (coverage, writer, format, route, receipt…), listed exactly.
- **BOUNDED_PASS** — every modeled reader × record obligation has a current passing receipt. This covers **byte/shape readability of the modeled records only**, not production safety.

Only a `BOUNDED_PASS` can be approved, by a human, for an idempotent **local simulation**. Nothing is ever deployed.

> All data is a **synthetic fixture** (Cart and Checkout services, two releases each, one cache, retained saved carts). Replayed agent runs are labeled as replays.

New to the codebase? Read the [project guide with examples and Mermaid diagrams](docs/PROJECT_GUIDE.md). The [initial issue #3 analysis](docs/ISSUE_3_ANALYSIS.md) preserves the investigation and solution options before implementation.

The [issue #3 implementation report](docs/ISSUE_3_FIX_REPORT.md) explains the tool-call and rate-limit changes, why each was needed, and their verification results. The [historical live comparison](docs/ISSUE_3_COMPARISON.md) contains author-reported results; its raw artifacts are not committed and those numbers are not independently verifiable acceptance evidence.

For the free-tier operating choice and the browser check of the sanitized quota message, see the [issue #4 quota plan](docs/ISSUE_4_QUOTA.md).

## The thirty-second story

1. The agent grounds the request in release notes and code, cites exact quotes, and asks when the fix to keep and the change to undo live in the same artifact.
2. Proposed fleet: cart → 1.4, keep checkout 2.1. **cart 1.4 starts GREEN** — but its reader **FAILS** on `saved-cart-2002`, which cart 1.5 already wrote as `cart/v2`.
3. FalkorDB shows the evidence path: `Plan → Deployment → cart 1.4 → load_saved_cart → cart-cache ← saved-cart-2002 (cart/v2) → written by cart 1.5`. Disposition: **BLOCKED**.
4. Given that evidence, the agent proposes an existing alternative: keep cart 1.5 with `basket_v2` off. Rechecked from scratch → **BOUNDED_PASS**.
5. A human approves the local simulation; applying it twice changes nothing the second time.

## How it works

| Part | Role |
|---|---|
| Grounding agent (`src/rw/grounding.py`) | One bounded tool loop (≤ 8 turns) over fixed read-only graph tools; proposes an existing-artifact fleet or a clarification. Default model chain: Groq `openai/gpt-oss-120b`, then `qwen/qwen3.8-27b`; Gemini optional. The model never sees graph names, Cypher, probes or approval. |
| FalkorDB (`src/rw/graph.py`) | FalkorDB 6.0.2. Releases, routes, stores, retained records, snapshots, plans and receipts; fixed parameterized queries with row caps. The multi-hop obligation query decides what gets checked and supplies the witness path. |
| Trusted checker (`src/rw/verification.py`) | Cross-checks graph results against independently parsed release files and snapshot manifests, so a missing edge, conflicting record or truncated query becomes a gap instead of disappearing. Computes the disposition (FAIL dominates; any gap → NEEDS_EVIDENCE). |
| Probes (`src/rw/probes.py`, `fixtures/shop/harness/`) | Runs allowlisted fixture readers on retained bytes in a bounded subprocess; receipts are bound to the exact obligation tuple (plan, snapshot, release, codec, route, record, payload, probe spec, environment). |
| Approval & simulation (`src/rw/simulation.py`, `src/rw/api.py`) | Human approval only for BOUNDED_PASS; evidence bytes are re-verified before approval and before simulation; SQLite ledger applies each approval once. |
| UI (`src/rw/static/`) | Minimal investigation workspace: snapshot context, cited fleet proposal, scope confirmation, startup-vs-reader verdict, connected evidence and receipt inspector, candidate comparison, and eligible human-approved simulation. Separate browser modules and CSS; no frontend build step. See [docs/UI.md](docs/UI.md). |

## Quickstart

Full instructions: [docs/QUICKSTART.md](docs/QUICKSTART.md). Short version (Windows shown; `sh scripts/setup.sh` on Linux/macOS/Git Bash):

```powershell
docker compose up -d                                              # FalkorDB 6.0.2 on 127.0.0.1:6379
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1         # .venv with Python 3.12 via uv
.venv\Scripts\python.exe -m pytest -q -m "not live"               # offline test suite
.venv\Scripts\python.exe scripts\smoke.py                          # end-to-end check, no model key needed
```

Try it:

```powershell
# Operator-specified fleet, no agent involved (shows BLOCKED with the witness):
.venv\Scripts\python.exe scripts\investigate.py --fleet cart=1.4 --confirm-as you

# Live agent (needs GROQ_API_KEY in .env):
.venv\Scripts\python.exe scripts\investigate.py "Undo the basket rollout, but keep the receipt correction." --confirm-as you

# Web UI on http://127.0.0.1:8000 (live or replay of saved runs; snapshot selector for NEEDS_EVIDENCE cases):
.venv\Scripts\python.exe scripts\serve.py
```

## Local MCP tools

Install the optional bridge with `sh scripts/setup.sh --mcp` (PowerShell: `scripts\setup.ps1 -Mcp`).
Start the existing HTTP API with `scripts/serve.py`; a stdio host then launches `scripts/serve_mcp.py`
using absolute interpreter/script paths. Six tools start, list and read investigations/transcripts,
answer a clarification and request an alternative. Human scope confirmation, approval and local
simulation remain in the console through the returned review URL. See [docs/MCP.md](docs/MCP.md)
for host configuration, strict inputs, size/time limits and restart/retry behavior.

## Evidence and honest limits

- **Independent oracle:** 8 hand-derived cases (`evals/expected/`) — the real pipeline on real FalkorDB matches all 8 (disposition, exact obligations, probe results, gaps).
- **Relational control:** SQL joins over the same raw facts reproduce the same obligation sets in 8/8 cases — a **tie**. The graph's contribution here is the connected query that drives what the agent checks and the inspectable evidence path, not exclusivity.
- **Live grounding:** a historical 10-run eval matched the expected outcome kind in **6/10** runs (case-level detail in [docs/STATUS.md](docs/STATUS.md)). The subsequent live control/product comparison, code fixes and remaining limits are recorded in the [issue #3 implementation report](docs/ISSUE_3_FIX_REPORT.md).
- **Scope:** synthetic fixture; BOUNDED_PASS is byte/shape readability of modeled records only; readers are trusted, reviewed fixture code (the probe harness is failure containment, not a sandbox); local simulation only.

## Repository layout

```text
src/rw/            product: contracts, graph, verification, probes, grounding, pipeline, api, simulation, static UI
tests/             unit, integration (live FalkorDB) and acceptance tests
fixtures/shop/     synthetic releases (code + changelogs), snapshots, retained payloads, probe harness
evals/             independent expected outcomes, SQL and LLM controls, grounding eval runner, reviews
scripts/           setup, smoke, investigate (CLI), serve (UI), fixture builder
docs/              QUICKSTART, CONTRACTS, STATUS, OPEN_ISSUES, architecture and plans
```

Contributor setup and behavior: [QUICKSTART.md](docs/QUICKSTART.md) and [CONTRACTS.md](docs/CONTRACTS.md). Product brief: [PRODUCT.md](docs/PRODUCT.md). HiveMind is a separate project; this repository does not build it.
