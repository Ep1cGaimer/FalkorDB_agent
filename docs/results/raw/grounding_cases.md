# Grounding cases — 20261018T154816Z

- chain: `groq:gemini-3-flash,groq:gpt-oss-120b-medium`
- fixture: `fixtures/shop` snapshot `snap-001` (temp graph `rw_test_grounding_eval_bcb15a41`, deleted after)
- runs per case: 3 · turns cap: 8 · temperature 0 (product loop)
- models that answered: groq:gemini-3-flash
- expected kinds (independent documentation, never imported by `src/`): main=PROPOSAL, ambiguous=CLARIFICATION, inseparable=CLARIFICATION, named-old-build=PROPOSAL, keep-everything=CLARIFICATION

| case | run | model | kind | proposed fleet | citations | validation errors | matches expected |
|---|---|---|---|---|---|---|---|
| main | 1 | groq:gemini-3-flash | PROPOSAL | cart=1.4 | changelog x2 | — | yes |
| main | 2 | groq:gemini-3-flash | PROPOSAL | cart=1.5{basket_v2=off} | changelog x2 | — | yes |
| main | 3 | groq:gemini-3-flash | CLARIFICATION | — | changelog x2 | — | no |
| ambiguous | 1 | groq:gemini-3-flash | CLARIFICATION | — | changelog x3 | — | yes |
| ambiguous | 2 | groq:gemini-3-flash | CLARIFICATION | — | changelog x3 | — | yes |
| ambiguous | 3 | groq:gemini-3-flash | PROPOSAL | cart=1.4 | changelog x2 | — | no |
| inseparable | 1 | groq:gemini-3-flash | CLARIFICATION | — | changelog x1 | — | yes |
| inseparable | 2 | groq:gemini-3-flash | CLARIFICATION | — | changelog x1 | — | yes |
| inseparable | 3 | groq:gemini-3-flash | CLARIFICATION | — | changelog x1 | — | yes |
| named-old-build | 1 | groq:gemini-3-flash | PROPOSAL | cart=1.4 | changelog x2 | — | yes |
| named-old-build | 2 | groq:gemini-3-flash | PROPOSAL | cart=1.4 | changelog x2 | — | yes |
| named-old-build | 3 | groq:gemini-3-flash | PROPOSAL | cart=1.4 | changelog x2 | — | yes |
| keep-everything | 1 | groq:gemini-3-flash | CLARIFICATION | — | changelog x2 | — | yes |
| keep-everything | 2 | groq:gemini-3-flash | CLARIFICATION | — | changelog x2 | — | yes |
| keep-everything | 3 | groq:gemini-3-flash | CLARIFICATION | — | changelog x2 | — | yes |
