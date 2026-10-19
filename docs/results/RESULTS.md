# Results — 18–19 October 2026

Everything here was run on synthetic fixtures. Model runs used `gemini-3-flash` on **both** sides of
each comparison, reached through a local OpenAI-compatible endpoint (`RW_GROQ_API_URL`). Sample sizes
are small: read these as indications, not benchmarks. Raw files are in [`raw/`](raw/).

## 1. Remove the relationships, keep the records

`evals/ablation_relationships.py` — Astronomy Shop, the all-to-3.1.0 rollback, no model involved.
Every node and property is kept (202 nodes); only edges are deleted.

| Removed | Verdict | Checks derived | Failures found | Evidence paths |
|---|---|---|---|---|
| nothing (full graph) | **Unsafe** | 80 | 32 | 80 |
| `EXECUTES_ROUTE` (release → reader code) | Can't confirm | 0 | 0 | 0 |
| `READS_FROM` (reader → store) | Can't confirm | 0 | 0 | 0 |
| `IN_STORE` (record → store) | Can't confirm | 0 | 0 | 0 |
| `WRITTEN_BY` (record → writer release) | Unsafe, plus 40 "writer unknown" gaps | 80 | 32 | 80 |
| all four | Can't confirm | 0 | 0 | 0 |

**What disappears:** without the reader/store/record links, no check can be derived, so the
32 failing reads are never found and no evidence path exists. Without `WRITTEN_BY`, the failures are
still found but provenance is lost (every record's writer becomes unknown).
**What does not happen:** the system never falls back to a pass. Trusted code cross-checks the graph
against the release files and snapshot manifest, so missing links become named gaps.

Raw: [`raw/ablation_relationships.json`](raw/ablation_relationships.json)

## 2. Same model, with and without the graph (shop fixture)

`evals/llm_control.py` vs `scripts/investigate.py`, scored by `evals/score_controls.py` against the
hand-written oracle in `evals/expected/`. The control gets every fixture file as plain text and the
same probe tool, but no graph.

| | Runs | Final answer correct and backed by its own probes | "Safe" claimed without probing every required reader | Wrong "safe" |
|---|---|---|---|---|
| RollbackWitness | 14 investigations | 13 (the other ended at a clarifying question) | 0 | 0 |
| Plain-text control | 13 | 9 | 3 | 1 |

Raw rows: [`raw/controls_scored_rows.md`](raw/controls_scored_rows.md) (includes operator-specified
product rows, which are labeled and not counted above).

## 3. Plain-text LLM vs graph checker (Astronomy Shop)

`evals/plaintext_vs_graph.py` — one model call with the whole fixture as text, vs the graph checker,
on six designed cases, three model runs each.

| Case | Expected | Graph checker | Plain-text LLM (3 runs) |
|---|---|---|---|
| documented / code-only / needle | Unsafe | correct | 9/9 correct |
| inventory marked incomplete | Can't confirm | correct | safe, unsafe, safe |
| unknown writer | Can't confirm | correct | 3/3 correct |
| actually safe | Safe | correct | 2/3 (one run reported 32 failures that do not exist) |

Raw: [`raw/plaintext_vs_graph_astronomy.json`](raw/plaintext_vs_graph_astronomy.json)

## 4. Agent request grounding

`evals/run_grounding_cases.py --runs 3` — 13 of 15 runs matched the expected outcome kind. The vague
"from last week" request was guessed instead of clarified in 1 of 3 runs (issue #17).
Raw: [`raw/grounding_cases.md`](raw/grounding_cases.md)

## 5. Agent proposes the safe alternative itself (Astronomy Shop, live)

All three to 3.1.0 → unsafe (32 of 80 checks fail). Given the checker's evidence, the agent then
proposed rolling back only checkout and keeping accounting and fraud-detection on 3.2.0
("their 3.1.0 releases fail to read existing non-USD records"), which passed 80 of 80 checks.
In another run the agent asked a clarifying question instead, offering the same two options.

## 6. Relational control

SQL joins over the same raw facts reproduce the same obligation sets in 8 of 8 hand-derived cases —
a tie. The graph's contribution is that the connected query drives what the agent checks and is the
inspectable evidence path, not that no other database could compute it.

## 7. Incident fixture verification (19 Oct 2026)

`fixtures/astronomy-incident` is a separate synthetic fixture; the preceding Astronomy Shop
measurements remain unchanged. It contains twelve services, 40 orders, 37 ledger rows and
20 saved carts. These observations were checked by the real FalkorDB/reader integration suite
(`tests/test_incident_fixture.py`, 22 passed), not by a live model benchmark.

| Condition checked | Disposition | Obligations | FAIL receipts | Complete derived origins |
|---|---|---|---|---|
| accounting + fraud-detection 3.1.0 | BLOCKED | 137 | 48 | 16 ledger rows trace to checkout-written orders |
| Same fleet, `DERIVED_FROM` removed on disposable copy | BLOCKED | 137 | 48 | 0; declared lineage is incomplete |
| Same fleet, `EXECUTES_ROUTE`, `READS_FROM`, `IN_STORE` removed on disposable copy | NEEDS_EVIDENCE | 0 | 0 | No failing reads can be derived |
| Current 3.2.0 readers; checkout `localCurrencyCheckout: false` | BOUNDED_PASS | 137 | 0 | Not needed for compatibility disposition |

The failing reads are 16 local-currency orders × two old consumers, plus 16 `ledger/v2` rows ×
one old accounting reader. The 16 ledger lineage paths each follow one `DERIVED_FROM` edge.
The original graph survives relationship-removal checks unchanged. Lineage is explanatory:
the receipts determine compatibility, and unknown or incomplete provenance never establishes
a common origin. Disabling the flag stops new local-currency writes; it does not repair old data
or prove the arithmetic incident resolved.

The UI's plain-text comparison uses one call to the actual same live model, with fixture facts
as text and no reader probes. It has different tools and budget from the agent/checker loop;
it is illustrative, not a causal benchmark of graph contribution. Replay and unsupported model
origins are refused for that same-live-model action. No new plain-text comparison score is
claimed here. Two new live rehearsals stopped with provider HTTP 413 quota refusals.

The expanded incident ablation was then executed on 19 Oct with all 485 nodes retained:

| Removed relationships | Checks | Failures | Derived rows traced | Disposition | Evidence gaps |
|---|---|---|---|---|---|
| None | 137 | 48 | 16 | BLOCKED | 0 |
| `EXECUTES_ROUTE` | 0 | 0 | 0 | NEEDS_EVIDENCE | 147 |
| `READS_FROM` | 0 | 0 | 0 | NEEDS_EVIDENCE | 147 |
| `IN_STORE` | 0 | 0 | 0 | NEEDS_EVIDENCE | 234 |
| `WRITTEN_BY` | 137 | 48 | 16 paths, writers unknown | BLOCKED | 97 |
| `DERIVED_FROM` | 137 | 48 | 0 | BLOCKED | 0 compatibility gaps; lineage incomplete |
| All four reader/store/provenance edge types | 0 | 0 | 0 | NEEDS_EVIDENCE | 147 |

The final row removes `EXECUTES_ROUTE`, `READS_FROM`, `IN_STORE` and `WRITTEN_BY`; lineage is
removed separately. Writer removal retains topological source paths, but cannot establish their
origin writer. Lineage completeness is tracked separately from compatibility gaps. Raw:
[`raw/ablation_relationships_incident.json`](raw/ablation_relationships_incident.json).

Two fresh replays of genuine saved conversations each reproduced BLOCKED → CLARIFICATION →
BOUNDED_PASS with new reader probes (137/48, then 137/0) and unchanged plan hashes. This verifies
the replay path; it is not a new live model result. Current readiness and actual checks:
[STATUS.md](../STATUS.md), [recording runbook](../demo/RECORDING_RUNBOOK.md).
