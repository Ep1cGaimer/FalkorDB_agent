# Build plan — RollbackWitness

## Status and mode

Implementation mode. Main product and gated prototype path are **approved**; the prep/runtime verification below is an implementation prerequisite, not a new approval request. No product code exists yet. This file and [TASKS.md](TASKS.md) are the active sequence; contracts live in [PRODUCT.md](PRODUCT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [STATUS.md](STATUS.md).

## Hackathon context

Target **Graph Hacks 2026 — "Context for AI Agents" (WeMakeDevs × FalkorDB)**, primarily *Agents That Act on Connected Data*. Don't add memory/swarm features just to claim more tracks. Build for "relationships are the hard part": multi-hop source/dependency/reader-state relationships shape a result inside a real agent loop (not a passive log or decorative diagram); interpretation changes the candidate or clarification; a valid evidence path backs the action; one reproducible synthetic dataset; a fair before/after on the same facts and budgets; truthful uncertainty and safe boundaries. Don't claim release assistance, generic rollback testing or approvals are novel — show the retained-state witness.

## Orchestration and routing

- **Opus 5.5 High — main orchestrator:** contracts, delegation, review, integration acceptance.
- **GPT-6.1 Sol via Codex — backend/integration implementer** under Opus.
- **DeepSeek V4.1 Flash on OpenCode Zen — default bounded parallel worker.** ID `opencode/deepseek-v4.1-flash-free`; **Zen only.**
- **Claude Sonnet 5.5 —** grounding/tool adapter, then UI.
- **Gemini 3.8 Flash (High) —** holdouts, visual review.
- **GPT-6 Astra —** optional hard-case review.

Scale DeepSeek tasks to actual concurrency; **no arbitrary two-worker ceiling**, but no idle agents or overlapping writers. Smoke checks are connectivity checks, **not product tests or a speed ranking**. Provider failures reschedule work; they never lower acceptance.

## Freeze before parallel writers

Scope/identity rules; `CandidatePlan`, `GroundingResult`, `CoverageReport`, `Obligation`, `ProbeReceipt`, `VerificationResult`, `Approval`; hash serialization; manifest shape; tool signatures; disposition precedence. One owner controls shared types. **Scope confirmation** (checking a proposal) and **action approval** (separate endpoint for local simulation) stay distinct; the model cannot approve its own action.

## Day 1 gate

Land a **real FalkorDB + probe + live grounding slice**: connection and import/read/null/cap behavior, exact reader-record obligations and a witness path, a failing reader receipt, a passing case, a missing-evidence case. A BLOCKED witness is the first slice. **No UI expansion until this works**; a mock is not FalkorDB validation.

## Verification rules

- Independently enumerate inventory IDs/edges; exact sets, not equal counts.
- Missing route/writer/format/source/coverage and truncation stay explicit; a failed join never hides a required item.
- Applicable witness → BLOCKED even with partial coverage; else unresolved evidence → NEEDS_EVIDENCE.
- BOUNDED_PASS needs complete obligations with current PASS receipts, limited to byte/shape readability.
- Bind receipts to the scope/plan/snapshot/deployment/codec/route/store/payload/probe/environment tuple.
- Distinguish codec incompatibility from timeout/crash/unavailable evidence (UNKNOWN).
- Only allowlisted authored readers, bounded I/O and timeouts; a subprocess is containment, not a sandbox.
- Keep expected outcomes out of runtime inputs; holdouts aren't rewritten to pass a patch.

## Four-day cut line

| Day | Exit artifact |
|---|---|
| 1 | Prep/runtime note, verified DB path, frozen contracts, live graph/probe/grounding slice |
| 2 | Complete obligation/evidence handling, negative cases, stable schemas, usable grounding |
| 3 | Evidence-led UI, source/fleet review, checked alternative if any, approval-bound simulation |
| 4 | Holdouts, equal-information controls, reproducible startup, visual review, short demo |

Feature freeze Day 4; fix evidence/reproducibility first. If nothing passes, ship a truthful blocked-only demo with no action button.
