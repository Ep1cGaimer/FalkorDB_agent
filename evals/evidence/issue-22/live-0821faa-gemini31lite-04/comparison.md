Primary matched comparison: **tie**; aligned blocks=3.

Evidence consistency of grounding/retrieval with shared checker; request fit reported separately. Clarification semantics are ungraded. Byte/shape readability does not establish cross-service behavior.

### Matched grounding with shared checker

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 10.545 |
| 1 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7551 | 2.108 |
| 2 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7551 | 2.208 |
| 2 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 8.196 |
| 3 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 11.437 |
| 3 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7551 | 2.591 |

### Legacy workflow

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 23780 | 3.963 |
| 2 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 23780 | 4.09 |
| 3 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 23780 | 38.315 |
