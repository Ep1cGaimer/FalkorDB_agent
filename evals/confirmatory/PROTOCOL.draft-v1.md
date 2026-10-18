# Confirmatory T0 protocol — DRAFT v1

Status: **DRAFT / NOT FROZEN / NOT VALIDATED**. Prepared independently on 2026-10-18
by a Codex AI subagent using upstream source and Git plumbing. This is AI-authored
review, not human review. No product output, implementation, tests, previous oracle,
or prior results are inputs. Expected answers are sealed outside this directory.

## Corpus and feasibility

Requests, origin https://github.com/psf/requests.git, bare clone
`artifacts/repos/requests`; Click, origin https://github.com/pallets/click.git,
fresh bare clone `artifacts/confirmatory/repos/click`. Click was first inspected
only by this independent evaluator after the implementation freeze was reported.
Implementer must verify freeze hashes and absence of prior Click inspection.

Primary snapshots (aliases are documentary; immutable hashes control all scoring):

| repository | release | commit |
|---|---|---|
| requests | v2.10.0 | efb4af01271c8c0ddf49457c7096a5bc91edbdad |
| requests | v2.20.0 | bd840450c0d1e9db3bf62382c15d96378cc3a056 |
| requests | v2.31.0 | 147c8511ddbfa5e8f71bbf5c18ede0c4ceb3bba4 |
| requests | v2.32.3 | 0e322af87745eff34caffe4df68456ebc20d9068 |
| requests | v2.32.5 | b25c87d7cb8d6a18a37fa12442b5f883f9e41741 |
| click | 6.7 | df0e37dd890d36fc997986ae6d2b6c255f3ed1dc |
| click | 7.1.2 | 1784558ed7c75c65764d2a434bd9cbb206ca939d |
| click | 8.1.7 | 874ca2bc1c30d93a4ac6e36a15ed685eafe89097 |
| click | 8.2.1 | fd183b2ced1cb5857784fe7fb22f4982f671f098 |
| click | 8.3.0 | 00fadb8904387158ce6e9aa1573be770446895c1 |

All ancestors of the selected snapshots are available to every arm. Additional
case-specific commits/parents must be pinned in the final manifest before freeze.
Production Python source under `requests/`, `src/requests/`, `click/`, `src/click/`,
root packaging metadata, HISTORY/CHANGES/CHANGELOG files and Git commit/tag metadata
form the evidence corpus. Exclude tests, examples, generated docs, vendored
`requests/packages/` implementations and nonproduction Python; record their coverage
limits. Non-Python files may establish text/history facts but are not AST relations.
Supported relations: Python definitions, imports, syntactic bases, inferred static
calls, commit parents, tag targets, revision file membership and Git rename candidates.
No runtime dispatch/completeness, compatibility, semantic backport equivalence,
universal rename identity, or absence from missing edges is claimed.

Inventory must report byte/file/commit/tag counts and the exact tokenizer's token
count for the declared included content. It is not yet verified that this corpus
exceeds the usable context budget; no scale claim until verified.

## Task roster and design

120 distinct questions: 20 in each primary stratum, exactly 10 from each repository
per stratum. IDs `CF-{REQ,CLK}-{DEP,REL,BRN,FIX,IDN,GAP}-{01..10}`.
Strata: dependencies/affected components; distant-release differences;
branch/merge provenance; current fix presence after later changes;
rename/deletion identity; ambiguity/missing evidence. At least 40 require two
supported hops or cross-revision reasoning; at least 30 require a negative finding,
uncertainty or clarification. These annotations and specific IDs must be finalized
before freeze. Fix/backport/revert labels require actual upstream patch/tree evidence.
No manufactured upstream reverts or backports; synthetic DAG claims remain separate.

## Arms and paired repeats

Graph retrieval; practical iterative plaintext search/file-read/Git-history baseline
at all sizes; direct plaintext context only for identical corpus slices that fit.
Search must support iterative source and Git reads with exact spans and revisions.
Arm source availability, model, answer instructions, decoding, token/tool/time limits
and output allowance are identical. Comparable baseline development effort and exact
implementation/prompt hashes remain mandatory pending verification.

Three paired repeats per task and applicable arm, proposed seeds 7101, 7102, 7103;
if seeds are unsupported record nondeterminism. Randomize arm order with seed 682410.
No result-based early stopping; preserve all attempted runs, failures and retries.

## Numerical resource contract (proposed; verify before signature)

| field | proposed hard limit |
|---|---:|
| cold full indexing per repository | 3600 seconds |
| incremental update per repository | 900 seconds |
| index disk per repository | 8 GiB |
| process/container peak memory | 6 GiB |
| query rows per page / total | 100 / 2000 |
| dependency hops | 5 |
| tool calls per question | 30 |
| total input tokens per question | 24000 |
| output tokens per question | 4000 |
| query timeout | 120 seconds |
| query p95 latency | 60 seconds |
| demo duration | 600 seconds |
| full evaluation monetary ceiling | USD 250 |
| concurrency: primary / demo | 1 / 2 |
| cold imports / incremental trials per slice | 3 / 3 |
| warmup / measured requests per slice | 10 / 100 |

No silent retry outside these budgets. All tokens include prompts/tool outputs and
failed attempts. Cache state: independent empty DB graph and retrieval cache for cold
imports; warm query measurements use explicitly recorded priming only. Define three
immutable scale slices before measurements. Above budgets are proposals, not evidence
that the runtime meets them.

## Exactly one primary advantage gate

**Gate B only**: graph/plaintext mean total input-token ratio upper 95% confidence
bound <= 0.80; answer-pass, evidence-precision and evidence-recall paired difference
lower bounds >= 0. No repository may have lower answer pass or recall than its
stronger comparator. Also pass every T2 absolute gate. Use 10,000 bootstrap samples
of distinct questions stratified by repository and primary stratum, paired arms and
three repeats kept together, proposed bootstrap seed 541098. Compare every applicable
plaintext arm. Insufficient confidence/power is inconclusive, never a relaxed gate.
Pilot power/sample-size justification is pending; 120 is only the minimum.

## Scoring and isolation

Freeze retrieval traces before answer generation. Oracle fact units are individual
propositions with exact repo/commit/path/span/blob digest or commit-object provenance.
Recall = supported required facts / required facts. Precision = relevant retrieved
units / retrieved units after deduplicating exact `(repo,commit,path,start,end,hash)`
units and commit objects by SHA. Alternative proofs must support the same proposition
at the pinned revision; extra adjacent lines do not multiply units. Partially relevant
units count once as relevant only if they support a required reasoning step. Record
raw and deduplicated counts. Empty retrieval on answerable questions scores zero
precision/recall; timeout/error/unjustified abstention scores zero answer/recall.
Clarification-only evidence N/A cases must be enumerated before freeze and counted.

Answer pass requires all facts/conclusions, valid material citations, and required
limitations. Invented facts, wrong repository/revision, fabricated citations, false
definitive absence or source-only compatibility pass fail the case and critical gate.
Average repeats within question before macro-average distinct questions. Report every
run, per-repository, per-stratum, negative-case denominator and confidence bounds.
T2 thresholds: overall pass >=90%; each repository/stratum >=85%; evidence precision
>=95%; recall >=90%; material citation validity 100%; critical errors zero in every
run; all negative/ambiguity cases expose the specified gap/clarification.

Blind scorers to arm using randomized response IDs. Independently double-score at
least 30 questions (25%), stratified with >=2 per repository/stratum, plus every
disputed, wrong-revision, fabricated/false-pass case and all repeats thereof. Separate
AI scorer identities, prompts and versions must be recorded; no invented human
signatures. Retain initial labels, agreement, both rationales and third-reviewer
adjudications. The oracle author must not tune implementation using sealed answers.
Parent receives public tasks, package hashes/counts, and review status only. Sealed
files must be inaccessible to ingestion/retrieval and only opened by scoring roles.

## Required verification before freeze

Runtime interpreter must be verified (local shell Python is 3.14.7; declared product
target is 3.12). Observed host: macOS 27.0.1 build 26A434, 16 GiB memory, 10 logical
CPUs, Git 2.55.0. Record exact CPU model, execution architecture, DB version/image
digest/configuration, dependencies, model immutable version/provider, prompt bytes
and SHA256, tokenizer/version, context window, reserved output/tool tokens, pricing,
permissions and API/account prerequisites. None is inferred from prior runs.
Required pending: core before/after hashes, unseen-repository attestation, corpus
token calculation, pilot power justification, baseline readiness, all task/oracle
hashes, budgets approved as final, two independent scorer/adjudicator identities,
and evaluator sign-off. Missing fields prevent T0 validation or confirmatory runs.

## Version/hash/amendment rule

Final JSON plan is canonical UTF-8 sorted-key JSON; manifest records SHA256 of exact
bytes and every referenced file. Detached review signs that hash with UTC time and
AI authorship declaration. A draft has no frozen signature. Before-results changes
produce a new version/hash and fresh review. Any post-result change to questions,
budgets, prompt/model, corpus or thresholds requires a new evaluation version with
all earlier attempts retained. Holdouts informing implementation changes become
development data; choose new unseen corpus/cases for a subsequent confirmatory claim.
