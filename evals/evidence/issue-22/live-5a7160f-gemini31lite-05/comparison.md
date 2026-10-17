Primary matched comparison: **tie**; aligned blocks=3.

Evidence consistency of grounding/retrieval with shared checker; request fit reported separately. Clarification semantics are ungraded. Byte/shape readability does not establish cross-service behavior.

### Matched grounding with shared checker

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 10.921 |
| 1 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 8.584 |
| 2 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 11.147 |
| 2 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 13.115 |
| 3 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 14412 | 9.087 |
| 3 | flat_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 7632 | 4.037 |

### Legacy workflow

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 8.85 |
| 2 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 7.884 |
| 3 | flat_assessment | completed | CLARIFICATION | — | False | basket=ungraded, receipt=ungraded | 15816 | 4.912 |
