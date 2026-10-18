# Evidence-first repository onboarding: revised implementation plan

Status: proposed, 2026-10-18. This is a design and delivery plan, not implemented behavior.
It revises [the original onboarding proposal](arbitrary-repo-onboarding.md) without changing it.
Repository baseline: `feat/astronomy-shop-demo`, including the Git-tag importer, per-request
datasets, evidence-led UI and HTTP/MCP interfaces. No implementation, commit, external connection
or customer-code execution is authorized by this document alone.

## 1. Outcome and boundaries

Make a tagless or history-poor repository useful without pretending missing facts are known.
A user can select an identifiable candidate, confirm a reader declaration, provide exported
records, and get an inspectable observation from that candidate's actual decoder. If information
needed for a broader verdict is missing, show that missing information rather than a green gate.

The first deliverable is **one tagless repository, one confirmed reader, an explicit candidate,
exported records, isolated execution, and a graph-backed failure or unresolved result**. Broad
language support, live connectors and near-automatic onboarding follow that working slice.

In scope:

- Discover candidate code and artifacts from several independent sources.
- Check a named rollback target or a named pre-deploy candidate.
- Preserve the distinction between source claims, schema checks and actual reader execution.
- Import exports first; later capture bounded, read-only samples.
- Explain scope, provenance, uncertainty and the exact failure witness in the existing UI.
- Keep scope confirmation, action approval and local simulation separate.

Out of scope for this roadmap:

- Executing production rollbacks, migrations, writes or consumer-group resets.
- Proving business correctness, absence of all runtime failures or production safety.
- Claiming exhaustive discovery from static scanning or an LLM review.
- Supporting every language, store, build system and serialization protocol at launch.
- Providing a multi-tenant hostile-code execution service on the developer's machine.

## 2. Current code to preserve or deliberately migrate

| Current component | Existing behavior | Required treatment |
|---|---|---|
| `src/rw/git_import.py` | Tags become declarations; new releases require reader declarations | Extend discovery, but never convert an undeclared reader into `no_state_read` |
| `src/rw/contracts.py` | Frozen plans, full obligation tuples, receipts and approvals | Introduce an explicit v2 contract; do not change the meaning of stored v1 hashes |
| `src/rw/verification.py` | Failure dominates; unknown writers and incomplete inventory are gaps | Preserve these gates; add observations without suppressing gaps |
| `src/rw/probes.py` | Reviewed fixture harness, nonce and bounded I/O | Retain for fixtures only; it is not an arbitrary-code sandbox |
| `src/rw/graph.py` | Fixed parameterized queries and independently checked manifests | Add provenance relationships without model-generated queries or inferred compatibility edges |
| `src/rw/pipeline.py`, `api.py` | Server-owned investigations and per-request dataset selection | Bind new modes and policies; resolve datasets through a trusted registry |
| `src/rw/api_contracts.py`, `mcp_contracts.py` | Typed HTTP views and safe MCP projections | Migrate both; remove legacy snapshot-name restrictions through shared validated identifiers |
| `src/rw/simulation.py` | Approval-bound, freshness-checked local simulation | Do not grant eligibility to sampled/schema-only observations |
| `src/rw/static/` | Minimal evidence-led UI and state-preserving navigation | Keep one workspace; add explicit modes and contextual review, not a second dashboard |
| `tests/` and `.github/workflows/ci.yml` | Fixture, checker, transport and browser coverage | Keep baseline tests; add negative and isolation suites before enabling new capabilities |

Some contracts still assume synthetic fixture data or the original snapshot names. Those are
explicit migration work, not facts to silently reuse for imported datasets. Existing architecture
documents describe repository-wide analysis and broad connectors as out of scope; amend those
boundaries only alongside the corresponding implemented phase.

## 3. Non-negotiable evidence rules

1. A tag, branch, version string or image tag is an alias, not immutable identity.
2. Identifiable source, a successful build, and an observed running deployment are different facts.
3. Unknown data, dynamic routes and contradictory evidence stay visible and unresolved.
4. A successful schema check is not a successful application-reader execution.
5. An applicable decoder rejection can block a scoped candidate even when the writer is unknown.
6. Passing sampled reads cannot discharge completeness or writer-provenance gaps.
7. Scanner findings and human-confirmed declarations do not prove there are no other readers.
8. Generated or transformed records never masquerade as untouched production records.
9. No repository build or customer decoder runs on the trusted host as an onboarding shortcut.
10. The model proposes; trusted code resolves identity, validates evidence, runs checks and gates actions.
11. Missing history does not silently change a rollback request into a pre-deploy check.
12. Every approval binds the exact mode, scope, policy, artifacts, configuration and verification.

## 4. Architecture and proposed data contracts

```text
Read-only collectors -> immutable observations -> candidate resolution -> human scope confirmation
                               |                         |
                        conflicts and gaps        isolated build/runner
                               |                         |
Reviewed routes + captured inventory -> graph obligations -> exact-byte read observations
                                                              |
                                              deterministic policy evaluation
                                                              |
                                           verdict + witness + limits + gaps
                                                              |
                                              separately gated local simulation
```

Collectors do not build; scanners do not grant route completeness; the runner does not decide
disposition. The policy evaluator consumes applicable evidence and remains deterministic.

### 4.1 Separate identities

Proposed v2 entities, to be finalized in the contract implementation PR:

| Entity | Identity binds | Important distinction |
|---|---|---|
| `SourceSnapshot` | Repository identity, resolved commit or captured file manifest, service boundary and shared build inputs | A dirty/local folder is a separate captured snapshot, not falsely labeled `HEAD` |
| `Artifact` | Built bytes or OCI digest, platform, and immutable artifact manifest | Same source may produce different artifacts |
| `BuildRecord` | Source snapshot, recipe/toolchain, dependency materials, build parameters, output digests and execution policy | A successful build does not prove deployment |
| `DeploymentObservation` | Source/environment, resource UID, observed time, actual image/artifact and relevant configuration | Intended config is not necessarily observed running state |
| `EvidenceObservation` | Collector/version, immutable source reference, content hash, claim, observation time and scope | Preserve disagreements and original evidence |
| `RouteDeclaration` | Source/artifact, store selector, reader entry, framing, read domain, cited evidence and reviewer decision | Confirmation is a declaration, not proof of exhaustive discovery |
| `CaptureManifest` | Record identities/hashes, capture boundaries, coverage, origin, transformations and private blob references | A complete export is not automatically a complete live-store inventory |
| `CheckRequest` | Dataset, snapshot, explicit check mode, selected artifacts and policy version | Model live/replay mode is a separate field |

Keep source-to-artifact mappings explicit, including whether they are claimed, corroborated or
verified under a configured provenance trust policy. Do not collapse everything into one numeric
confidence score. An unresolved build may be a discoverable candidate, but not a runnable release.

Source identity must include shared libraries, root lockfiles, generated-source inputs and build
configuration that affect the service. Do not hash just its apparent subdirectory. Dependency
versions, base images and build arguments can change outputs without a service-code change.
Keep runtime flags/configuration separately bound to the candidate deployment.

Preserve aliases and their observation history when they resolve to the same immutable object.
Retagging should not erase provenance; changing a mutable alias should create a new observation.
Do not deduplicate distinct compiled artifacts merely because their source tree hashes match.

### 4.2 Backward-compatible introduction

- Keep v1 fixture identities, receipts and hash functions unchanged.
- Add explicit dataset/evidence schema versions and server-controlled policy versions.
- Give v2 distinct canonical hash namespaces and typed readers; reject unknown future versions.
- Treat an adapted legacy release as a reviewed fixture artifact with its existing identity and origin.
- Do not relabel a handwritten `codec.py` as the original service executable.
- Never convert an old approval into a v2 approval; require a new check and explicit approval.
- Keep existing fixed queries working; add a small set of parameterized provenance queries.

## 5. Discover versions by reconciliation, not a fallback chain

Run the enabled collectors independently. Merge observations about the same immutable identity,
retain aliases, and surface contradictions. Discovery order may optimize latency; it must not
determine truth or discard stronger evidence because tags happened to exist.

| Source | What it can establish | What it cannot establish alone |
|---|---|---|
| Git tag | A label resolves to a commit at observation time | That it built, shipped or is currently running |
| Helm/Kubernetes/Argo history | Recorded rollout or intended revision; stronger running-state evidence when observed | Complete history, successful execution or a unique source build from a mutable tag alone |
| Running container image ID / registry digest | Exact image identity and platform when captured | Accurate source attribution from a self-declared label alone |
| Version-field change | A candidate source revision associated with a manifest change | A release or production deployment |
| Default-branch merge | A candidate commit and ancestry | That it shipped or is the last good release |
| Current commit or explicit local folder | Capturable candidate source | Historical rollback evidence or reproducible buildability |

Implementation requirements:

1. Collect candidates per confirmed service boundary, with limits and continuation cursors.
2. Resolve branches/tags to full commit IDs and image tags to platform-qualified digests.
3. Record both requested alias and resolved identity. If resolution changes before execution,
   require reconfirmation; do not follow the alias to new bytes automatically.
4. Treat pruned rollout history, inaccessible registries and missing labels as missing evidence.
5. Distinguish repository/config history, attempted deployment, successful rollout and observed
   running workload. A Compose file in Git is desired-state evidence, not proof that it ran.
6. Preserve candidate status such as `DISCOVERED`, `RESOLVED`, `BUILT`, `OBSERVED_RUNNING` as
   separately evidenced facts rather than a guessed linear lifecycle.
7. For equal version strings pointing to different artifacts, require exact selection or clarification.
8. Record DAG ancestry and explicit rollout order independently. Do not invent a single `PREVIOUS`
   chain by sorting version strings, timestamps or unrelated branches.

Kubernetes documents mutable image tags versus fixed digests and retention of rollout history;
the importer must accommodate both rather than assume an eternal deploy record.
[Image identity](https://kubernetes.io/docs/concepts/containers/images/#image-names),
[history retention](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#clean-up-policy).
OCI revision/source annotations describe declared metadata. A trusted build-provenance record
requires a separate verification policy and evidence of the builder/materials, not merely those
strings. [OCI annotations](https://github.com/opencontainers/image-spec/blob/main/annotations.md),
[SLSA provenance model](https://slsa.dev/spec/v1.1/provenance).

The UI should say, for example, "Named commit; build succeeded; deployment not established,"
not assign the generic label "strong release."

## 6. Check modes, observations and verdicts

### 6.1 Two explicit workflows

- `ROLLBACK`: inspect the user-selected rollback target under a confirmed proposed configuration.
  Current-state/deployment evidence remains required where the full fleet comparison needs it.
- `PRE_DEPLOY`: inspect an explicitly selected candidate's readers against the selected retained
  inventory. One candidate can be useful even when no previous release or writer history exists.

Use the same request box and review screen with a small, explicit mode selector. Model execution
still independently chooses `live` or `replay`; do not overload that existing field. The UI may
offer a pre-deploy check when history is missing, but it requires the user's explicit selection.

A named target is an input mechanism for either workflow, not a third mode. Unknown writers,
partial coverage and schema-only execution are evidence dimensions that can occur in either mode.
If the running baseline is unavailable, a named artifact can still receive a clearly scoped reader
observation; it cannot become a verified full-fleet rollback comparison by assuming the baseline.

### 6.2 Keep verdict and observations separate

Initial policy: `strict_byte_shape_v2`. Preserve current conservative verdict semantics while
making useful partial results visible. Do not introduce a new approval-eligible sampled pass.

| Evidence | Overall verdict under the initial policy | Observation shown |
|---|---|---|
| Applicable real reader rejects an original retained record on an established route | `BLOCKED` | Exact decoder rejection, candidate, record and capture origin |
| All observed reads pass, but writers are unknown | `NEEDS_EVIDENCE` | "Observed reads passed; writer provenance unresolved" |
| All observed reads pass, inventory is sampled/partial | `NEEDS_EVIDENCE` | "Observed reads passed; only the listed sample was checked" |
| Schema validates; actual reader cannot run | `NEEDS_EVIDENCE` | "Schema validation passed; application reader untested" |
| Framing is ambiguous or the route is only an unconfirmed suggestion | `NEEDS_EVIDENCE` | Diagnostic observations, not an applicable incompatibility witness |
| Timeout, build failure, missing dependency or sandbox failure | `NEEDS_EVIDENCE` | Runner/build failure, not a compatibility failure |
| Complete applicable actual-reader passes and no required gaps | `BOUNDED_PASS` | Byte/shape readability only for the confirmed modeled scope |
| Generated/transformed record is rejected | Scope-dependent diagnostic result | "Rejected generated/transformed input," never an untouched production-record claim |

A counterexample needs established route applicability, immutable candidate identity, confirmed
input protocol and a decoder-rejection classification. Failure dominance does not authorize
misclassifying an arbitrary process crash or bad adapter as a read incompatibility.

Track `check_level` (`FIXTURE_MODEL`, `SCHEMA_ONLY`, `ACTUAL_READER`), `data_origin`, writer
provenance, route coverage and inventory coverage independently. These are not a simple scalar
ranking: a complete synthetic model and a partial real sample answer different questions.

`WRITER_UNKNOWN` remains a gap; the writer hop in a witness is optional. Group unknown-writer
records by established format only for presentation. Do not omit their obligations or test just
one representative and call the entire group passing. Ambiguous formats remain unknown.

Schema rejections can be reported as schema incompatibility observations, but do not replace an
actual-reader obligation by default. Likewise, existing fixture-model passes retain their original
explicitly synthetic scope; they never become proof about an imported service binary.

If a later product needs sample-only approval, introduce a separately reviewed policy and action
class with its own hash bindings and UI wording. It is explicitly not part of the first release.

## 7. Selecting and capturing candidates safely

Supported selectors are a full commit, a resolvable branch/tag, a pinned image, or an explicit
local source folder. The model can propose only candidates returned by trusted resolution.

- Capture selected source into a read-only, bounded content store before scanning or building.
- Do not mutate the original checkout, execute hooks, fetch submodules or include untracked files
  implicitly. Missing submodules/LFS inputs are explicit resolution gaps.
- A dirty folder requires an explicit include manifest and confirmation. Do not copy `.env`, Git
  credentials, home directories or secret mounts into the build context.
- Validate paths, archive entries, symlinks, file sizes and total capture size; reject traversal and
  links escaping the capture root. Use argument arrays, not shell-interpolated selectors.
- Capture monorepo build dependencies outside the service folder only when explicitly included.
- Build only the selected candidate and required dependencies, not every discovered revision.
- Keep cancellation/resume states explicit; interrupted builds cannot produce runnable-artifact facts.

For a repo with one commit, pre-deploy checking can proceed with a runnable reader and data.
For a repo with no Git metadata, an explicitly captured directory can serve the same purpose.
Neither case creates a fictional previous release or a fictional writer.

## 8. Reader/writer discovery and human review

### 8.1 Static scanning is candidate discovery

Begin with one ecosystem and a narrow set of client/serializer calls. Output structured findings
with source snapshot ID, file hash, line range, symbol, route/store expression, serializer/framing
candidate, scanner version and unresolved dependencies/config keys.

Prefer AST/parser-based rules over keyword matching. Support known wrappers gradually. Apply
resource limits to parsers and treat schemas, source comments and generated metadata as untrusted.
Do not run imports, repository plugins, code generators or custom build hooks during scanning.

Crucial rule: **no findings does not establish `no_state_read`**. Unknown dynamic routing and
unsupported client libraries contribute to a discovery-coverage statement and unresolved review.

### 8.2 LLM assistance remains proposal-only

- Give the model bounded source/config excerpts, never credentials or unrestricted store access.
- Bind each proposal to source identity, file hash and exact quoted span; reject stale citations.
- Treat source text and tool output as untrusted evidence, not executable instructions.
- Separate proposed reader function, store selector, format/framing and read domain into reviewable claims.
- A person may accept, edit or reject each claim. Accepted edits are auditable declarations;
  unconfirmed claims never become trusted graph routes.
- Changing source, build configuration or the relevant routing config invalidates confirmation.
- Record unresolved coverage even after all currently visible suggestions are accepted.

Store signed-off declarations outside generated source files, keyed by immutable source/artifact
identity. Apply an explicit merge/export step for legacy `release.json` compatibility. Re-importing
must not overwrite a review or copy it to a different commit just because the filename is unchanged.

Writer discovery and per-record writer attribution are separate. Discovering a producer says it
can write a store; it does not establish that it wrote a particular retained record.

## 9. Schema adapters versus actual-reader adapters

### 9.1 Schema observations

Provide generic adapters only for explicitly supported format/envelope combinations:

- JSON parsing plus JSON Schema validation with a pinned dialect and validator.
- Protobuf decoding with exact descriptors, message type and framing rules.
- Avro decoding with established writer-schema identity and reader-schema resolution where needed.

A format identifier or magic byte is not enough to infer every missing protocol detail. Distinguish
schema registry framing, compression, encryption, message indexes and plain payloads. Unknown
framing/schema or multiple plausible message types produce unresolved observations.

Pin parser versions and schema inputs. Disable remote schema references by default; resolve only
declared local content or an explicitly authorized read-only resolver whose results are captured.
Run custom generators/plugins only inside the build isolation boundary, never in the scanner.

Schema success has its own receipt and cannot be substituted for an actual reader's receipt.
Protocol Buffers' unknown-field behavior and Avro's writer/reader schema resolution are examples
of why one generic notion of "strict schema decode" is insufficient.
[Protobuf guide](https://protobuf.dev/programming-guides/proto3/),
[Avro specification](https://avro.apache.org/docs/1.12.0/specification/),
[JSON Schema documentation](https://json-schema.org/docs).

### 9.2 Actual application readers

The adapter invokes the version's existing decode entry point and required preprocessing; it must
not replace it with a handwritten equivalent. The adapter source, entry point, dependency closure,
configuration and platform are reviewed and bound into execution evidence.

Initial language: Python for the narrow vertical slice. Add Go and the Astronomy Shop consumers'
actual .NET/Kotlin runtimes only with separate tested adapters. Until then, keep their fixture
models honestly labeled; do not claim the upstream services themselves were executed.

Use a typed result envelope and route-specific rejection classification:

- `PASS`: the reviewed reader invocation returned successfully within its declared byte/shape scope.
- `FAIL`: an established decoder rejection of the supplied bytes under the confirmed protocol.
- `UNKNOWN`: build/runtime infrastructure error, protocol/adapter uncertainty, timeout, unexpected
  crash, dependency failure, resource limit, malformed result or unsupported environment.

Do not extend the fixture convention "an entry-call Exception means FAIL" blindly to arbitrary
service code. Missing configuration and genuine incompatibility can otherwise look identical.
A trusted supervisor records execution identity and outcome; arbitrary stdout cannot fabricate a
parent-issued receipt or approve a candidate. An intentionally dishonest decoder can still accept
anything: execution is evidence of observed behavior, not a proof of semantic correctness or intent.

## 10. Isolation: establish it before any customer build

Threat model: source, build scripts, dependencies, schema tooling and decoder inputs may be
malicious. Isolation applies to compilation and dependency lifecycle scripts as well as readers.
The existing nonce-based fixture subprocess is not an acceptable fallback.

Runner requirements:

1. Separate trusted orchestration from an isolated, disposable Linux runner environment.
2. Use a dedicated VM/microVM boundary for unreviewed code; a constrained rootless container on
   that disposable runner is an execution layer, not the whole hostile-code security argument.
3. No host Docker socket, privileged mode, host networking, host process namespace, broad bind
   mounts, SSH agent, cloud metadata access or inherited user credentials.
4. Read-only captured inputs; ephemeral writable scratch; non-root execution; dropped capabilities;
   platform-supported syscall restrictions; enforced CPU, memory, process, disk, wall-time and I/O caps.
5. Default-deny network for build and execution. Missing dependencies fail closed.
6. If dependencies must be downloaded, use a separate, explicitly authorized material-fetch stage
   with destination constraints, pinned material hashes and no repository lifecycle execution.
   Verify fetched materials before the offline build; do not grant the decoder network access.
7. Kill the whole process tree on timeout/cancel; discard scratch and revoke ephemeral credentials.
8. Capture supervisor attestations, runner/toolchain digests and sanitized diagnostics. No customer
   code controls the result-channel schema or the canonical receipt identity.

Document a narrow reviewed-repository beta if the VM boundary is not ready. Do not market a
container-only local beta as safe arbitrary hostile-code execution. Docker itself documents the
importance of daemon access, privileges and kernel isolation.
[Docker security model](https://docs.docker.com/engine/security/).

Windows/macOS hosts may orchestrate a supported isolated Linux runner. If it is unavailable,
return `NEEDS_EVIDENCE`; never fall back to running a repository with host Python/Node/JVM.

## 11. Records, sampling, writer provenance and privacy

### 11.1 Exports first; bounded live capture later

The MVP imports user-provided exports using a validated capture manifest. Preserve source store
identity, record key/partition/offset, byte hash, format/envelope metadata, capture time, origin and
coverage. Do not assume an export includes everything in its originating system.

Kafka is the first live connector. Use separate read-only credentials, an isolated non-production
consumer identity/assignment, bounded byte/record/time budgets and explicit partition/offset
boundaries. Do not commit offsets to production groups or alter topic/group state.

Record start/end offsets, retention limitations, partition changes and capture timing. Offsets can
have gaps; compaction/retention and concurrent writes matter. A bounded sample stays `PARTIAL`.
An exhaustive finite-range export can be complete for that named captured scope only when the
collector can account for its contents; it does not become a complete ever-changing live store.

Later connectors use equivalent store-specific scopes and read-only guarantees. Read-only is
not load-free: rate limits, query cost, cancellation and per-store budgets are required.

### 11.2 Writer attribution is not format matching

Keep `ESTABLISHED`, `CLAIMED`, `HYPOTHESIZED` and `UNKNOWN` provenance distinct. The precise
established-evidence policy is server controlled and versioned.

- An authenticated provenance record binding an event to a producer artifact can establish a writer
  under that policy. Check issuer trust and artifact resolution rather than trusting a field name.
- Ordinary `app_version` or producer headers are claims unless their provenance is established.
- A schema ID identifies a schema, not a unique service build that used it.
- Deployment timestamps suggest candidates, but delayed writes, rolling deployments, retries,
  backfills and replay tools prevent timestamp matching from being proof.
- Matching payload format suggests a compatibility group, not which release wrote the record.

Only established attribution produces a trusted `WRITTEN_BY` edge. Preserve hypotheses separately;
they may help an operator investigate, but cannot discharge `WRITER_UNKNOWN`.

### 11.3 Preserve the identity of the bytes actually tested

Preferred flow: keep original records inside restricted local capture/runner storage, test those
bytes, and sanitize metadata/diagnostics before displaying them. The model and graph never need
raw customer records or complete decoded JSON by default.

- Graph state holds opaque capture references and bounded evidence, not raw payloads or credentials.
- Give private blob storage restrictive OS permissions, retention limits and explicit deletion.
  Git-ignored storage alone is not access control.
- Redacted/transformed payloads have a new hash, transform/version identity and `TRANSFORMED`
  origin. Their results apply only to those bytes, not the original record.
- Treat exception messages, decoded shapes, record keys and even hashes as potentially sensitive.
  Public display may need opaque IDs/keyed identifiers; do not publish low-entropy secret hashes.
- Redaction failure means no public output. A private capture may still support local checking.
- Synthetic generated records have `GENERATED` origin and generator/schema/seed identities. A
  counterexample demonstrates a possible failure, not that such bytes exist in production.
- Do not copy sampled payloads into tracked `fixtures/` or attach them to CI artifacts/PRs.

## 12. Receipt binding, caching and freshness

Preserve the existing full-tuple applicability check. Proposed v2 bindings additionally include:

- Contract version, check mode, policy version/hash and action class.
- Resolved artifact digest and source/build provenance dependency identities.
- Reader entry, adapter bytes, route/framing contract and configuration fingerprint.
- Capture manifest, original/transformed/generated origin, exact input hash and relevant metadata.
- Schema/descriptor and writer-schema identities where applicable.
- Trusted harness/supervisor, runner, toolchain/runtime and isolation-policy digests.
- Resource limits, supported platform and execution specification.

Relevant source, declarations, writer evidence, candidate configuration and capture/provenance
dependencies participate in revalidation, including facts outside one reader's immediate tuple.
Changing these invalidates the verification/approval instead of silently preserving eligibility.

Initial implementation: cache build artifacts, not plan-bound receipts. Re-run the bounded reader
checks for a new plan. Never use only `(release_hash, record_hash)` as a receipt cache key.

If execution-result caching is later needed, separate immutable execution facts from plan-bound
receipts. Match the complete execution specification, input and environment, revalidate all
dependencies, and have trusted code issue a newly bound receipt with the original execution
timestamp/reference. Never edit an old receipt tuple to make it fit a new plan. Add replay/drift
tests before enabling this optimization.

Freshness is always as of a named capture. Re-running an old sample is not proof that the current
live store is unchanged; additional capture or state attestation is needed for a new claim.

## 13. CLI, API, MCP and minimalist UI

### 13.1 User flow

1. Choose a repository and confirm service boundaries/build inputs.
2. Choose `Rollback check` or `Pre-deploy check` explicitly.
3. Resolve one candidate; inspect immutable identity and provenance limitations.
4. Confirm a reader/store/protocol declaration and its scope.
5. Import an export, or explicitly authorize bounded read-only capture.
6. Review the exact fleet/check scope; confirm before building/running customer code.
7. See verdict, observed checks, gaps, source/capture labels and the exact witness.
8. Approve local simulation only when the server's policy explicitly allows it.

Do not impose a historical current/target pair on the one-candidate pre-deploy workflow. Do not
hide unresolved route discovery merely because a manually selected reader ran successfully.

### 13.2 Proposed interfaces, not commands available today

```text
rw onboard --repo <path> --name <dataset> --dry-run
rw onboard --repo <path> --name <dataset> --resume <run-id>
rw check --dataset <id> --check-mode pre-deploy --candidate <resolved-id> --capture <id>
rw check --dataset <id> --check-mode rollback --target <resolved-id> --capture <id>
```

Dry-run performs local inspection only: no build, install, store connection or customer-code
execution. Fetch/remote discovery/capture and execution require explicit opt-ins and resource scopes.
Stage private onboarding runs outside tracked fixtures. Publish a validated dataset atomically;
interrupted/unreviewed output is not automatically selectable as a complete dataset.

Add a trusted dataset registry for both existing fixtures and restricted imported-dataset roots.
HTTP/MCP requests select registered IDs, not arbitrary local filesystem paths. Expose check mode,
policy, candidate identity, origin and completeness in both projections. Generalize snapshot
validation without weakening path/dataset isolation; keep list/get pagination and response caps.

MCP discovery and proposal tools remain read-only unless a separately authorized tool contract
permits a mutation. A natural-language instruction never supplies operator authority implicitly.
The existing `local-ui-user` label is not authentication; real connector/capture authorization must
come from explicit local consent or a genuine identity layer, not a free-text approver field.

### 13.3 UI treatment

- Keep one workspace and request field; add only the explicit check-mode selector and candidate input.
- Derive dataset/service/store/format titles and candidate aliases from typed API evidence.
- Keep synthetic/export/sample/transformed origin and model live/replay labels prominent and separate.
- Use the compact expandable retained-data panel; show named capture scope and coverage.
- Put unconfirmed declarations in a contextual review drawer with exact source spans, not an activity feed.
- Lead with `BLOCKED` / `NEEDS_EVIDENCE` / `BOUNDED_PASS`; put observed successes beneath the verdict.
- Under gaps, the saved-data summary remains amber/unresolved even if individual cells passed.
- In a witness, say `Writer unknown` when appropriate. Keep store, record and reader identities distinct.
- Never show an enabled approval button solely because a schema or sample passed.
- Preserve drafts, selected mode/target, disclosure, review state and receipts through Back/Forward/reload.

## 14. Delivery phases and exit gates

### Phase 1 — Freeze v2 semantics and resolve explicit candidates

Work: define v2 identities, policy/mode fields, compatibility adapters and dataset registry; extend
Git discovery to explicit commits/local captures, version changes and merges. Keep tag support.
Collectors emit observations without claiming deployment or executing code.

Files: `contracts.py`, new `identities.py` / `discovery/git.py` / `datasets.py`, `git_import.py`,
`api_contracts.py`, `mcp_contracts.py`, contract/architecture docs.

Exit gate: throwaway repos cover tags, no tags, one commit, no Git metadata, dirty source,
monorepo shared inputs, moved aliases and conflicting version names. v1 fixture identities and
approvals are unchanged. Mode/policy changes alter v2 hashes. No-history import alone is not
advertised as runnable end-to-end onboarding.

### Phase 2 — Isolation and one actual-reader adapter

Work: implement isolated build/material handling, a trusted supervisor and a Python adapter.
Use explicit confirmed routes and exported test inputs; broad scanning is not a prerequisite.

Files: new `sandbox/`, `runners/`, `captures/export.py`; integrate through `probes.py` without
allowing arbitrary code into the existing fixture harness.

Exit gate: actual decoder from captured source is invoked; different output bytes have distinct
artifact identities, while different build materials retain distinct build records even if their
outputs match. Host/environment/credential/network/file escape attempts are rejected.
Build errors/timeouts/bad envelopes are UNKNOWN; classified decode rejection is FAIL. Missing
isolation on Windows/Linux fails closed. No repository script executes on the orchestration host.

### Phase 3 — First complete no-history workflow: MVP milestone

Work: connect the candidate, reviewed declaration, export capture, graph obligations, reader
receipt, strict disposition and existing review UI. Add explicit rollback/pre-deploy selection.
Support useful unknown-writer observations without enabling a sampled pass action.

Files: `verification.py`, `pipeline.py`, `graph.py`, `api.py`, HTTP/MCP contracts and tools,
`static/app.mjs`, `views.mjs`, `evidence.mjs`, and browser tests.

Exit gate: a tagless single-candidate repo plus exported records produces an actual-reader failure
witness. A passing unknown-writer/partial variant remains NEEDS_EVIDENCE with observed passes.
A complete controlled variant can obtain a correctly bounded result. Add one pinned, license-
compatible external repository exercise; a tiny authored test repo alone is not the realism claim.
No generated compatibility implementation may stand in for its actual decoder.

This is the first milestone to demonstrate to judges/users: one truthful end-to-end case rather
than six discovery connectors ending in handwritten `codec.py` files.

### Phase 4 — Discovery assistance and schema evidence

Work: one ecosystem's AST-based client/serializer scanner; supported schema/envelope adapters;
LLM proposal interface; source-bound review records and coverage gaps.

Files: new `discovery/scanners/`, `schema_adapters/`, `declarations.py`; grounding tools and the
contextual UI review drawer.

Exit gate: unresolved config/wrappers stay unresolved, stale citations cannot be accepted, empty
scan does not prove no reads. A schema-pass/actual-reader-fail example remains blocked by the
actual failure. Missing Avro writer schema and ambiguous protobuf framing cannot produce a pass.

### Phase 5 — Deployment and registry evidence

Work: Kubernetes running/rollout observations plus OCI digest/label resolution first; add Helm
and Argo collectors as separate follow-ups. Reconcile with Git rather than replace Git evidence.

Files: new `discovery/kubernetes.py`, `oci.py`, later `helm.py` / `argocd.py`; provenance queries
and candidate-picker evidence details.

Exit gate: disposable cluster with two rollouts captures immutable identities and config changes.
Pruned history, missing labels, moved image tags, failed rollouts and source/image contradictions
remain explicit. Read-only RBAC and bounded API use are tested. Git configuration files are not
misrepresented as observed deployments.

### Phase 6 — Real bounded capture and privacy controls

Work: Kafka read-only capture, private blob storage, export parity, sanitized public evidence and
writer claims/provenance. No timestamp-to-writer promotion.

Files: new `captures/kafka.py`, `capture_manifest.py`, `privacy.py`; capture lifecycle API/CLI,
verification dependencies and privacy-safe projections.

Exit gate: production groups/offsets and store contents do not change; limits/cancel/retention gaps
are observable. Sampled successes stay NEEDS_EVIDENCE. Redacted bytes cannot reuse original-
payload receipts. Sensitive payloads and error strings do not reach model prompts, graph values,
logs, replay exports, screenshots or uploaded CI diagnostics without an explicit safe projection.

### Phase 7 — Resumable onboarding and supported expansion

Work: package `rw onboard` / `rw check`; atomic dataset publication; resumable review/capture/build
states; controlled Go/.NET/Kotlin adapter expansion as needed for real target services. Preserve
the distinction between an authored Astronomy Shop fixture and executions of upstream readers.

Files: CLI entry points in `pyproject.toml`, onboarding orchestration module, dataset registry,
new adapters and fixture-independent onboarding documentation.

Exit gate: an unseen repo in the documented support matrix onboards through inspection and
explicit confirmations, or stops with actionable unsupported/missing-evidence reasons. Resume
does not reuse stale confirmation/approval. Re-onboarding does not overwrite reviewed data or
another dataset. Full offline legacy, v2, transport, browser and isolated-runner checks pass.

Dependencies: phases 1 -> 2 -> 3 establish the first usable slice. Phase 4 follows that slice;
phase 5 can then progress independently of scanner breadth; phase 6 requires the capture/privacy
contracts and may consume phase 5 provenance. Phase 7 integrates supported components. No
calendar estimates until the first build/isolation spike establishes the environment cost.

## 15. Test strategy and implementation PR boundaries

Required regression/acceptance cases:

| Area | Must prove |
|---|---|
| Identity | Same code/different dependencies, runtime config or adapter cannot reuse wrong evidence |
| Discovery | Tags plus deployment observations coexist; conflicting aliases are not arbitrarily selected |
| No history | One candidate works for pre-deploy observations; no fictional target or writer appears |
| Verdict | Actual applicable failure dominates partial coverage; sampled/schema-only success never grants approval |
| Reader errors | Missing dependencies, bad adapters, timeout, signals and invalid output remain UNKNOWN |
| Schema protocols | Actual-reader disagreement, unknown framing/message type and missing writer schema are visible |
| Provenance | Schema IDs, timestamps, ordinary producer headers and format matching cannot establish a writer alone |
| Capture | Stable record/store identity, bounded partitions/ranges, cancellation and retention/compaction limits |
| Privacy | Original/transformed receipts cannot cross-apply; secrets and payloads do not escape public projections |
| Sandbox | Network/metadata/host access, symlink escape, fork/resource abuse and build-hook execution are contained |
| Freshness | Mode/policy/source/config/declaration/capture/writer dependency drift invalidates old approval |
| API/MCP | Identical policy outcome and safe provenance labels; no legacy snapshot-name or synthetic-only assumptions |
| UI | Arbitrary dataset names, modes, amber gaps, exact witnesses and Back/Forward/reload behavior |
| Isolation | Two datasets/runs cannot share unauthorized paths, captures, caches or credentials |

Use deterministic captured collector responses for ordinary CI. Use disposable local Kafka/
Kubernetes services for connector integration. Put adversarial execution tests on a disposable
dedicated runner with no repository/org credentials, never casually on a privileged hosted job.
Tests themselves must not require real customer data or production credentials.

Suggested PR sequence: v2 contract/golden hashes; candidate resolution; capture/export and runner
interface; isolation and Python execution; graph/checker integration; mode-aware API/MCP/UI; MVP
acceptance exercise. Then make each collector, scanner and language adapter a separate reviewable
PR. Update `CONTRACTS.md`, `ARCHITECTURE.md`, `UI.md`, `QUICKSTART.md` and `STATUS.md` only to
describe features actually delivered and verified in that PR.

## 16. Decisions fixed by this revision

- Version sources are reconciled, not an exclusive cascade with fixed "strength" rankings.
- Source, built artifact and deployed configuration have distinct identities.
- Pre-deploy is an explicit mode in the existing workspace; no silent fallback from rollback.
- Unknown writers are an evidence dimension, not a mode or a reason to invent provenance.
- Partial successes remain useful observations, not a shortcut around the strict action gate.
- Schema validation and actual-reader execution remain different evidence classes.
- Original, transformed and generated inputs remain distinguishable through every receipt and view.
- Isolation precedes arbitrary builds; unsupported environments stop with evidence gaps.
- The first release targets one end-to-end supported slice, not arbitrary-repo universality.

Before implementation, record the concrete isolated-runner provider/OS and one external repo/
decoder for the MVP acceptance exercise. Prefer a reproducible, offline-buildable Python reader
for the initial slice; select it on license, build closure and retained-format behavior, not on
whether it happens to make the demo pass. These selections do not change the evidence rules.
