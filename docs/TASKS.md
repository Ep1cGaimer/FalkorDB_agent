# Tasks — RollbackWitness

Task ownership, dependencies and acceptance for [BUILD_PLAN.md](BUILD_PLAN.md). Contracts/semantics: [PRODUCT.md](PRODUCT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [STATUS.md](STATUS.md).

## Current status (honest)

- **No product code yet.** Source/test/fixture directories are a scaffold; this and BUILD_PLAN are the authorized refactor's output.
- **Blockers (recheck during setup):** Docker daemon access failed; current Python lacks FalkorDB/FastAPI/Pydantic/pytest; uv cache returned an access error. Don't assume a working Compose command or admin access.
- Verified only: DeepSeek V4.1 Flash as `opencode/deepseek-v4.1-flash-free` on Zen plus two small smoke checks — **not product tests, not a benchmark**.
- Pending: real FalkorDB server/client verification, fixture writers/readers, live grounding loop, API/UI, approval simulator, acceptance tests.

## Work packages

Dependency-based order; integrate by dependency.

**0. First slice and shared contract** — Opus, Sol executing backend. `src/rw/contracts.py`, contract tests. Acceptance: source facts express the scenario without compatibility-verdict edges; canonical serialization; missing-evidence and approval precedence explicit; verified runtime path. Blocked by runtime diagnosis.

**1. Trusted fixture and reader harness** — one bounded worker; independent expected-outcome review by Gemini/Astra. `fixtures/readers/`, `fixtures/manifests/`, `fixtures/sources/`, `tests/test_fixture_readers.py`. Acceptance: reproducible bytes from writer code; incompatibility distinguished from harness failure; compatible input passes; unknown coverage stays visible; runtime code must not import expected answers.

**2. Graph adapter and obligation evidence** — DeepSeek on Zen; Sol fallback. `src/rw/graph.py`, `src/rw/queries/`, `tests/test_graph_integration.py`, `evals/relational_control.py`. Prerequisite: frozen contract and fixture IDs. Acceptance: exact sets match independently checked expectations; orphan/wrong-ID cases visible; real pinned server/client queries work; no in-memory graph counts. Excludes verification/approval policy.

**3. Grounding adapter, then evidence UI** — Sonnet, two sequenced deliverables. `src/rw/grounding.py` + tests, then `src/rw/static/` once the report schema stabilizes. Acceptance: attainable/ambiguous/inseparable requests handled without invented artifacts; live tool calls exercised; source injection can't alter tools/approval; UI renders actual report fields and disables ineligible actions.

**4. Checker, approval and local simulator** — Sol under Opus; Astra reviews when useful. `src/rw/verification.py`, `src/rw/probes.py`, `src/rw/simulation.py` + high-value tests. Acceptance: applicable FAIL dominates incomplete coverage; missing/stale evidence can't pass; payload/route/environment/plan mutation invalidates applicability; source/snapshot mutation invalidates approval; duplicate application executes once; no action endpoint for blocked/unknown results.

**5. Independent evidence and presentation** — Gemini holdouts/presentation; Astra false-pass review; Opus reproduction. `evals/holdouts/`, `evals/results/`, runbook, final screens. Acceptance: UI source/path/receipt agree with backend; replay labeled; no timing/accuracy claim without measurement; blocked-only result has no action button.

## Review and integration

Opus owns integration and acceptance. Independent review is required for graph completeness, receipt applicability, disposition and approval changes; a worker never rewrites expected outcomes to pass its own patch. Every handoff lists exact owned files, frozen payload references, observed check output, remaining gaps and the next acceptance criterion. Use worktrees or exclusive ownership; no concurrent edits to shared types. After a provider failure, preserve work and reassign the same bounded task — don't grow scope.

## Cut first if short

Animated graph canvas, extra stores/services, semantic probes, historical receipt reuse, migrations, broad auth, deployment infra, swarms. A concise evidence path beats a force-directed graph.
