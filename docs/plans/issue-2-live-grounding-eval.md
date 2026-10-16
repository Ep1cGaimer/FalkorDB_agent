# Issue #2: live grounding evaluation plan

Drafted 2026-10-16 against local `main` at `771ce38`.
Source: https://github.com/Ep1cGaimer/FalkorDB_agent/issues/2 (open, no comments).
This document is a plan; it records no new live evaluation results.

## Requirements and scope

Issue #2 requires running `evals/run_grounding_cases.py --runs 3` live, recording the
case-level table in `docs/STATUS.md`, and reporting whether the ambiguous request was
clarified or guessed. An unfavorable result is valid evidence. The issue does not
require changing the prompt until every case passes.

The full evaluation is five requests times three runs: 15 scheduled observations.
Provider errors and aborted conversations must remain visible. They do not demonstrate
the ambiguity rule's success or failure, and a quota-interrupted run does not supply
the full behavioral evidence sought by this issue.

Other open issues are #3 (equal-information live control), #4 (provider quota strategy),
#11 (UI revamp), and #12 (startup instructions). Their implementation is outside #2.
An unresolved quota limit can prevent completing #2, but it must not silently reduce
the requested run count or trigger a provider migration.

## Repository structure and current behavior

| Location | Responsibility and implication |
|---|---|
| `src/rw/grounding.py` | Product tool loop, generic ambiguity rule, provider chain, terminal validation, transcript storage. The rule already exists in `SYSTEM_PROMPT`; no new rule is required before measuring it. |
| `src/rw/graph.py` | Fixture import and bounded graph reads. The runner creates one unique temporary graph for the entire invocation, imports `snap-001`, and uses read-only grounding tools for every observation. It does not recreate a graph per case; the unchanged imported graph supplies the same starting state. |
| `evals/grounding_cases/requests.json` | Five fixed requests. These are evaluation inputs, outside application runtime data. |
| `evals/grounding_cases/expected.json` | Independent expected kinds and rationale, loaded by the runner for reporting only. Application code must not read these answers. |
| `evals/run_grounding_cases.py` | Already defaults to three runs per case. Calls the real `ground()` function, retries provider failures, reports kind/fleet/model/citation counts/errors/matches, writes a final Markdown report, and attempts temporary-graph cleanup in `finally`. |
| `artifacts/grounding/` | Git-ignored successful/aborted grounding transcripts, including model, tool events, final question/proposal, validation errors, and abandoned provider attempts. A total provider failure raises without saving a transcript. |
| `evals/results/` | Git-ignored generated reports. Results must be copied into tracked `docs/STATUS.md` to satisfy #2. |
| `tests/test_grounding.py` | Existing prompt, provider, replay, formatter, summarizer, and live tests. The live tests check basic result validity, not the expected outcome kind. |
| `.github/workflows/ci.yml` | Runs non-live tests and deterministic smoke. This task does not need live-model credentials or calls in CI. |

The issue's `build/slice-2` reference is historical. Only `main` is checked out locally;
it includes the issue-fix and CI merges. Use a task branch from current `main` during
implementation and record the evaluated commit. Do not restore the older branch.
The existing untracked `graphify-out/` directory is investigation tooling output and
must not be included in the implementation commit.

`docs/STATUS.md` already contains the earlier 6/10 result and a partial later run:
main returned one clarification and two proposals before DNS/quota trouble. Preserve
both as history. Changes since the 6/10 run include citation correction hardening, so
a rerun measures current behavior; it cannot isolate the ambiguity prompt's causal
effect by itself.

## Cases and review criteria

| Case | Existing expected kind | What to inspect beyond the kind |
|---|---|---|
| `main` | `PROPOSAL` | Cart 1.4 rollback or cart 1.5 with `basket_v2=false`, preserving checkout 2.1's receipt correction. A valid rollback proposal can later be blocked by retained-state verification; compatibility is not the grounder's decision. |
| `ambiguous` | `CLARIFICATION` | Asks which change/release/behavior the user means, identifies the unresolved reference, and cites candidate evidence rather than choosing cart 1.4 by assumption. |
| `inseparable` | `CLARIFICATION` | Baseline rationale is disputed; see the decision below. Do not treat this kind label as an unquestionable semantic oracle. |
| `named-old-build` | `PROPOSAL` | Binds to cart 1.4 using release evidence while preserving checkout 2.1. This guards against blanket clarification of every rollback phrase. |
| `keep-everything` | `CLARIFICATION` | Explains the conflict between preserving checkout basket behavior and removing the co-shipped receipt correction; does not invent a hybrid release or flag. |

The runner's `matches expected` field compares only kinds. It can say `yes` alongside
validation errors. A semantically incorrect proposal can also match the expected kind.
The `proposed fleet` column lists proposed changes, not the completed fleet; unchanged
services are normally omitted. Read the transcript and baseline snapshot to interpret it.

Exit 0 means no row exhausted all provider attempts. It does not mean all expected kinds
matched, all citations validated, or no run aborted. Inspect all 15 rows explicitly.

## Baseline decision

The `inseparable` request says:

> Turn off the order summary basket headings, but keep the basket grouping of saved carts.

Its rationale assumes undoing the headings requires splicing checkout 2.1 because the
receipt correction lives in that same release. The request does not say to keep the
receipt correction. Keeping cart 1.5 and proposing checkout 2.0 appears to be an
existing-artifact interpretation; checkout 2.0's inability to read retained cart/v2
data belongs to the later deterministic checker. This is a potential expectation
defect, not a confirmed reason to change runtime behavior.

Two options were presented to the user:

1. Preserve the historical request/expectation for #2 and annotate the inconsistency
   separately. Recommended: it retains comparability and does not delay measuring
   the `ambiguous` case.
2. Review and correct the expectation before evaluating. If selected, document the
   rationale and changed baseline before seeing new results; distinguish the new
   aggregate from the historical 6/10 score. Do not silently rewrite the request or
   tune the expected answer to observed model output.

The user selected option 1 during implementation on 2026-10-16: preserve the
historical baseline and annotate the inconsistency. Keep `requests.json` and
`expected.json` unchanged; interpret the `inseparable` kind match with that caveat.

## Implementation sequence

### 1. Establish reproducible prerequisites

- Start from current `main` on a task branch; capture the exact commit, UTC time,
  Python version, fixture identity, and prompt hash for the evidence record.
- Create the project environment using the existing `sh scripts/setup.sh`. This
  checkout has no `.venv/bin/python`; `uv` and Docker executables are available.
- Inspect existing Docker services before starting anything. Reuse a compatible
  server at `127.0.0.1:6379` or start the project's pinned FalkorDB service if needed.
  The evaluation runner calls `graph.connect()` with default host/port; it does not
  inherit the smoke script's `RW_FALKORDB_HOST`/`PORT` support. Resolve any actual
  port conflict before running rather than changing connection behavior speculatively.
- Use `config.load_env()` and the current product chain. Here `GROQ_API_KEY` is
  present, `GEMINI_API_KEY` is absent, and no chain override is set. Do not print
  secrets. Key presence does not establish current provider quota availability.
- Keep the existing product settings: default chain
  `groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b`, temperature 0, eight-turn cap,
  configured transport retries, and three outer provider attempts. Record any
  necessary operational override instead of silently changing it.

### 2. Run the unchanged baseline live

On macOS/Linux, from the repository root:

```sh
.venv/bin/python -m pytest tests/test_grounding.py -q -m "not live"
mkdir -p artifacts/grounding-eval
.venv/bin/python -u evals/run_grounding_cases.py --runs 3 > artifacts/grounding-eval/issue-2-live.log 2>&1
```

Run database-backed tests and smoke **before**, never concurrently with, the live
batch. `tests/test_grounding.py::_drop_test_graphs` deletes every graph whose name
starts with `rw_test_grounding_`, including the runner's temporary graph. This was
observed during implementation; the interrupted attempt must remain separately
labeled in the evidence record.

Capture the exit code immediately and monitor the log while the evaluation runs.
The runner performs real provider calls; deterministic transports and transcript
replay do not satisfy #2. Run the existing full case set once without selecting only
favorable cases. An additional live smoke call is unnecessary before this batch.

Preserve the generated `evals/results/grounding_<timestamp>.md` and relevant local
transcripts. Verify the temporary graph is actually gone: cleanup errors are swallowed
by the current runner, so its report's deletion wording alone is not proof.

If quota or networking prevents completion, preserve every observed row and failure,
label the evidence partial, and report the dependency on #4. If later rerunning on
fresh quota, record it as a distinct invocation. Do not combine selected observations
from multiple batches into an unlabeled apparently clean 15-run table.

### 3. Review the evidence

- Verify all five case IDs have run indices 1, 2, and 3, with no duplicates or omissions.
- Distinguish normal terminal results, `ABORTED`, provider `ERROR`, and kind matches
  with validation failures. Record the actual answering model for every row.
- Inspect all three ambiguous transcripts: exact question, unresolved references,
  cited candidate excerpts, errors, and whether any terminal proposal guessed a release.
- Inspect `main` and `named-old-build` for over-clarification and preservation of the
  receipt correction. Inspect the other cases against the agreed baseline.
- Report aggregate kind matches out of 15 scheduled observations, per-case results
  out of three, and clean versus error-bearing matches. Identify provider mixtures;
  do not describe mixed-model observations as a single-model success rate.
- For ambiguity, report `3/3 clarified`, `n/3 guessed`, or the exact incomplete/mixed
  outcome. Only claim the rule was observed working when the clarifications actually
  address the vague referent with valid supporting evidence. Even 3/3 is small-sample
  evidence, not a reliability guarantee.

### 4. Record the measured result

Update `docs/STATUS.md` after the run with:

- Evaluated commit, UTC timestamp, exact command, exit code, chain, answering models,
  snapshot, eight-turn cap, and any operational overrides.
- The complete generated 15-row table, including fleets, citation counts, validation
  errors, and kind matches. If interrupted, include all available observations and
  explicitly name missing runs instead of inventing rows.
- A brief semantic review, especially the three ambiguity questions and any guessing,
  excessive clarification, aborts, or invalid citations. Add local transcript filename
  mappings for audit; explain that those files and raw reports are git-ignored.
- An explicit conclusion: observed ambiguity behavior improved, remained incorrect,
  or could not be determined because of infrastructure failures.
- Updated #2 wording in the open-items section. A completed unfavorable evaluation
  may satisfy the issue's reporting requirement; a runtime fix can be a follow-up.
  A quota-limited partial attempt must remain incomplete.

Preserve earlier dated evidence. Correct the stale `docs/OPEN_ISSUES.md` reference in
the touched open-items section to the actual GitHub issues; that file is absent.
Leave broader startup documentation work with #12.

### 5. Consider remediation only after measurement

No application-code change is justified before the baseline. If it still guesses,
record that result first. Any follow-up prompt change should express a generic
disambiguation principle without fixture names, dates, versions, or expected answers.
It must preserve behavior for explicit requests such as `named-old-build`.

A changed prompt affects every investigation and is a behavioral compatibility risk
even when API schemas stay stable. Review and evaluate it as a separate change with
a separately labeled complete live batch; never replace the failed baseline evidence.

## Proposed file changes and compatibility review

| File | Proposed change | Compatibility assessment |
|---|---|---|
| `docs/plans/issue-2-live-grounding-eval.md` | This implementation plan. | Documentation only. |
| `docs/STATUS.md` | Required: actual measured table, metadata, ambiguity analysis, and updated #2 status after execution. | No runtime/API/schema effect; historical claims remain dated and intact. |
| `evals/grounding_cases/expected.json` | Conditional: only the disputed expectation if the user chooses baseline review and the review supports correction. | No application effect, but changes evaluation meaning and historical comparability; requires an explicitly versioned baseline explanation. |
| Runtime, graph schema, fixture bytes, contracts, CI, dependencies | No planned changes for the evidence-only path. | Existing tool signatures, replay format, proposal validation, deterministic verification, and approval behavior remain compatible. |

The runner lacks interruption checkpoints and does not put transcript paths/questions
in its generated table. These are optional future tooling improvements, not prerequisites
for #2: persistent stdout/stderr and transcript inspection suffice for this run. Do not
expand this task into a new evaluation framework or change existing exit-code semantics.

## Validation and completion checklist

- Existing non-live grounding tests pass after environment setup; no new tests are
  necessary for a documentation-only result update.
- Run `.venv/bin/python -m pytest -q -m "not live"` and
  `.venv/bin/python scripts/smoke.py` before a PR, matching repository CI expectations.
  These check deterministic behavior, not the live ambiguity result.
- Review the recorded table against raw output and transcripts, verify denominator
  accounting and temporary-graph cleanup, and run `git diff --check`.
- Commit only tracked plan/status changes and any separately agreed expectation
  correction. Keep `.env`, raw logs, generated results, transcripts, and graphify output
  out of the change.
- Completion requires the full live evidence and tracked case-level report with an
  honest ambiguity conclusion. This planning task itself does not complete issue #2.

Planning validation: reviewed source, tests, fixtures, current open issues via `gh`,
and environment/key presence without printing credentials. No dependencies were
installed, tests executed, Docker services changed, or live model requests made while
drafting this plan.
