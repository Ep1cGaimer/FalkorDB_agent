# Paired score aggregation tooling

The new `evals/confirmatory/paired_scores.py` aggregates supplied independent
adjudications; it does not generate, grade or inspect answers/oracles. Fourteen
synthetic contract checks passed. These are tooling checks, not model quality or
advantage evidence. The199-file product build remains unchanged; this module and
its test are two later evaluation-only additions outside that full-suite pin.

The aggregator requires every declared question/arm/repeat cell, at least three
repeats, strict score/usage types and an adjudication reference for completed
answers. Errors/timeouts remain in quality denominators with zero answer and
applicable precision/recall. Unknown usage stays unknown. Clarification-only
evidence exclusions must be declared in the roster before scores are supplied.
Repeated scores are averaged within a question before distinct-question metrics.
Critical errors and negative-case failures apply to every run, not majority vote.

Comparisons preserve repository/stratum groups, paired arms and repeated-run
blocks while resampling distinct questions10,000 times with a declared seed.
Each comparator is reported separately with repository noninferiority checks.
The preselected A/B numerical threshold is checked alongside absolute quality;
no result sets `acceptance_validated=true`, signs T0, verifies scorer independence
or claims real costs/break-even. Those remain external evidence requirements.

Run after independently adjudicated data exists:

```sh
PYTHONPATH=. python -m evals.confirmatory.paired_scores --input ratings.json --output new-summary.json
```

The output path must be new. Inputs are the public roster fields
`id,repository,stratum,evidence_applicable,negative`, explicit arm names, repeat
count, preselected gate and one score record per planned cell. All original
attempts and ratings/adjudications remain in the evidence bundle; this utility
cannot choose a successful retry or substitute its own correctness labels.

Validation command and synthetic JUnit:
`PYTHONPATH=.:src /tmp/rw-mcp-compat/bin/python -m pytest -q tests/test_confirmatory_paired_scores.py --junitxml=artifacts/goal-paired-score-checks.xml`.
The tests cover retained failures, repeated-question denominators, missing and
duplicate pairs, invalid usage, critical errors in one repeat, unknown costs/tokens,
predeclared evidence N/A and a stronger comparator veto. No held-out files or
provider calls are used by this component.
