# Independent confirmatory package

This package is **DRAFT, not frozen or validated**. It was independently authored
and reviewed by a Codex AI evaluator from upstream source and Git only. No human
review, generated product answers, or successful acceptance gates are asserted.

Current package: `package-manifest.draft-v2.json`. The plan is
`plan.draft-v2.json`; its source-only review is `review.draft-v2.json`.
`PROTOCOL.draft-v1.md` is the preserved initial prose protocol. Draft v2 separates
internal graph rows, returned evidence rows, raw source bytes and actual model
tokens, and fixes explicit scorer sampling and branch-source rubrics. Earlier
drafts remain preserved. There have been no confirmatory product runs.

`tasks.draft-v2.json` contains 120 public questions, with IDs
`CF-{REQ,CLK}-{DEP,REL,BRN,FIX,IDN,GAP}-{01..10}`. Each of the six primary strata
has 10 Requests and 10 Click cases. The source-only manifest records 80 conservative
cross-revision complexity cases, 50 negative/ambiguity cases and eight predefined
clarification-only evidence N/A cases. Repeats are not counted as new questions.

**Do not open `artifacts/confirmatory/sealed/` in implementation, ingestion,
retrieval or answer-generation roles.** That directory contains oracle answers,
source excerpts and evaluator authoring scripts. Public manifests expose hashes
and corpus identities, not oracle propositions. Same-account separation is logical,
not cryptographic; the final runner must enforce source/data allowlists and preserve
access traces. Only isolated scoring roles may open the oracle after retrieval and
answers have been locked. Oracle authorship and AI assistance must remain disclosed.

The fresh Click bare clone is `artifacts/confirmatory/repos/click`; Requests uses
`artifacts/repos/requests`. All raw source is read through Git plumbing without
checkout, import, build, installation or repository-code execution. Provenance
retains parent maps, tag objects and a Python 3.12 AST-only snapshot parsing receipt.
The historical inventory counts unique included blobs, not repeated snapshots or
complete rename identities. Exact model tokens and context-overflow verification
remain pending.

Before any confirmatory run, fill and verify every field listed in
`mandatory_pending_before_frozen_signature`, create a new final plan version/hash,
and obtain the independent reviewer's explicit frozen-plan sign-off. This includes
the final core/source freeze and unseen-repository attestation; immutable model,
tokenizer, exact prompts, baseline readiness, actual corpus token calculation,
power justification, final budgets/environment, and independent scorer/adjudicator
identities. Gate B is the sole proposed primary T10 gate. A draft review does not
authorize declaring T0 or T2 passed. Retain all future attempted runs and failed pairs.

Public metadata integrity can be checked with:

```sh
python3 evals/confirmatory/check_public_package.py
```

This checker never opens sealed files, upstream source, implementation or results.
The independent evaluator must separately check the sealed byte hash before scoring.
