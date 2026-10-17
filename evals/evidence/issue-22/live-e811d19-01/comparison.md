Primary matched comparison: **incomplete: no aligned completed blocks**; aligned blocks=0.

Evidence consistency of grounding/retrieval with shared checker; request fit reported separately. Clarification semantics are ungraded. Byte/shape readability does not establish cross-service behavior.

### Matched grounding with shared checker

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | graph_grounding_checker | completed | BOUNDED_PASS | 4/4 | True | basket=partial, receipt=True | 15167 | 68.906 |
| 1 | flat_grounding_checker | failed | OPERATIONAL_ERROR | — | — | basket=ungraded, receipt=ungraded | unknown | 0.258 |
| 2 | flat_grounding_checker | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
| 2 | graph_grounding_checker | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
| 3 | graph_grounding_checker | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
| 3 | flat_grounding_checker | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |

### Legacy workflow

| Block | Arm | Status | Outcome | Recall | Evidence consistent | Request fit | Tokens (reported total) | Seconds |
|---|---|---|---|---|---|---|---|---|
| 1 | flat_assessment | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
| 2 | flat_assessment | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
| 3 | flat_assessment | unrun | UNRUN | — | — | basket=ungraded, receipt=ungraded | unknown | unknown |
