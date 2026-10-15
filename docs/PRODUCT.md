# RollbackWitness

**Rolling back code does not roll back the data it wrote.**

## User and outcome

An on-call engineer needs to undo a faulty release while retaining a required fix and avoiding incompatibility with records already written by newer software.

The engineer states desired behavior rather than artifact IDs: “Undo the basket rollout, but keep the receipt correction.” The agent grounds that request in actual release artifacts, cites the relevant source text, and proposes a fleet or asks a precise clarification. Deterministic tools then check every modeled executing-reader/retained-record obligation.

The result is a grounded proposal, a concrete incompatibility witness, or a specific missing-evidence request. A reviewed passing candidate can be applied only in a local approval-bound simulator.

The main product and gated prototype path are approved. Build it; do not restart product selection. Initial preparation/runtime checks remain implementation prerequisites. HiveMind is a separate project and is outside this repository.

## Minimum shipped loop

1. Retrieve release history and version-linked source excerpts through fixed graph tools.
2. Interpret the request into exact existing artifacts or an evidence-backed clarification.
3. Show the candidate for scope confirmation.
4. Enumerate candidate-specific reader/record obligations from FalkorDB, preserving incomplete evidence.
5. Execute allowlisted trusted fixture readers and collect exact applicable receipts.
6. Compute BLOCKED, NEEDS_EVIDENCE or BOUNDED_PASS in trusted code and explain the evidence path.
7. Compare at most one predefined alternative. Offer human approval of local simulation only if eligible.

Meaningful interpretation happens before compatibility checking. The agent must change the candidate or clarification; narrating a precomputed verdict is insufficient. Existing artifacts may form a mixed fleet, but the agent cannot invent a binary combining selected behaviors from an inseparable release.

## Graph contribution

Critical evidence path:

**Plan → Deployment → Release → ReaderRoute → StateStore ← Batch → writer Release → SourceExcerpt**

Actual executing readers matter. Service callers are not automatically decoders. The graph selects source context, derives obligations for the proposed fleet and exposes the witness behind a result.

Removing relationship tools while retaining raw records removes this implementation's connected source lookup, obligation generation and witness paths. Complete SQL/BFS can reproduce the logic and is a fair control. The shipped proof still requires actual FalkorDB; another database or a drawn graph is not a substitute.

## Scope

Start with Cart and Checkout, two releases per service, one cache, two retained records, one byte/shape probe family, and at most two predefined plans. Use independent, clearly synthetic writer/readers and source manifests. Expected outcomes and holdouts stay outside runtime inputs.

Deliver one grounding agent, a deterministic evidence checker, a small API and one evidence-led screen. Trusted code owns permissions, limits, exact inventory identity, probe execution, receipt matching, disposition and approval.

Exclude production deployment, broad connectors, repository-wide analysis, arbitrary generated Cypher/code, migrations, semantic-unit verification, general incident management, autonomous swarms and cross-session company memory.

## Result semantics

- **BLOCKED:** an applicable reachable incompatibility witness, including when other coverage is incomplete.
- **NEEDS_EVIDENCE:** no such witness, but some required scope, route, inventory, identity, freshness or probe information is unresolved.
- **BOUNDED_PASS:** complete modeled obligations with current applicable passing receipts. Limited to byte/shape readability, never overall production safety or semantic correctness.

A note claiming compatibility is not a probe receipt. Co-bundling does not establish atomic rollback. Ancestry does not establish fix preservation. Disabling a feature does not repair incompatible retained records by itself.

## Thirty-second experience

Enter a behavioral rollback request → inspect the cited fleet proposal → show startup succeeds → run a reader against newer retained state → reveal the failing receipt and short graph path → evaluate the known alternative if available → approve only eligible local simulation.

All of these are target behaviors until actually executed. A blocked-only demonstration is valid if no alternative passes; it must not expose an eligible action button. Replay must be labeled.

## Evidence and acceptance

Use equal relevant sources, artifacts, relationships, probe access and comparable model budgets for source/changelog selector, flat-source, relational and graph workflows. Report scope correctness, exact obligation recall, path/receipt validity, false passes, missingness handling, preparation effort and time to accepted output. No control is required to fail.

The technical rollback hazard has supporting engineering references preserved in the archive. Demand, ingestion economics and differentiation from configured deployment tooling remain unvalidated. Synthetic fixture success demonstrates mechanics only.

Acceptance requires an actual FalkorDB-derived obligation set, a real retained-payload probe result, meaningful live request grounding, truthful missingness/receipt handling, and fresh idempotent approval whenever simulation exists. See [ARCHITECTURE.md](ARCHITECTURE.md), [BUILD_PLAN.md](BUILD_PLAN.md) and [TASKS.md](TASKS.md).
