# Optional tool selection and typed calling — independent review

**The new graph multi-hop final is correct and precisely cited. The plaintext multi-hop final gets the paths right but cites unrelated single lines for two declarations.** This snapshot reviews the two completed results available at **2026-10-18 14:38:12 UTC** in `run-005-typed-reasoning`; ambiguity and static-limit pairs remained pending. Prior attempts and [the previous quality review](goal-flash-lite-quality-review.md) remain preserved.

The shared guidance and dispatcher preserve **optional graph use**. The guidance says graph traversal is often useful for multi-hop and reverse relationships, then explicitly says it is optional and to choose the shortest reliable evidence path. Exact-symbol/hop advice applies **when choosing** graph traversal. The graph arm still exposes raw search/read/file/history capabilities. Every observed native retrieval request allows those raw tools and `finish_investigation` alongside graph functions. `mode: ANY` requires a tool-or-finish transport decision; it does not require selecting a graph tool. The inspected runner dispatches the model-selected capability and contains no question-keyword branch forcing graph calls. Graph readiness can validate the arm before retrieval; that is not itself model-selected graph evidence.

Native typed transport v3 addresses the concrete calling problems: `dependencies` and `dependents` declare required `revision` and `symbol`, while `symbols` declares required `revision` and optional `name`. Schemas reject extra keys and describe integer arguments as integers, with required keys explicit. Native call names must belong to the explicit allowlist; one call is accepted per decision; finish takes no arguments. Continuation preserves the native call parts/signature and matches function-response name/id. Actual request traces show these preserved continuations and no tools in the final-answer request. Numeric ranges are still descriptions plus operation validation, rather than schema `minimum`/`maximum` constraints; this review did not execute adversarial schema tests.

| Completed result | Independent final-answer/source check |
| --- | --- |
| Multi-hop, graph | **Pass for the asked static paths:** `symbols` resolves the exact qualified definition; `dependencies` with `hops: 2` returns four successful INHERITS edges; source follow-ups verify both routes. Final citations are `url_safe.py:79–83`, `timed.py:170`, `url_safe.py:15`, and `serializer.py:42`, all correct bytes and declarations at the pinned commit. |
| Multi-hop, plaintext | Both paths are true in retrieved source, but final `url_safe.py:80` is a docstring line and `timed.py:176` is blank. Their actual declarations are **79** and **170**, outside those single-line final citations. `url_safe.py:15` is correct. This is a material citation-grounding failure despite reference-integrity `valid: true`. |

Both answers frame the paths as static source relationships and do not claim executed MRO or runtime compatibility. The graph extractor labels three parameterized-base edges `inferred` and the direct mixin edge `parsed`; source checks support the selected static origin relationships, not runtime MRO verification. Graph coverage also reports unsupported `pyproject.toml` and `complete: false`; final `gaps: []` does not restate that global limitation. The positive declaration paths are nevertheless directly source-supported, with no absence or exhaustive-coverage claim.

This is a **non-blind development review**, with arm identities and parent-derived task expectations visible and the same tasks informing the repair. It is not an independent task/oracle design, blinded arm comparison, full T2 claim, or measured aggregate graph benefit. The reviewer made no provider calls, reruns, new tests, core changes, or endpoint changes. Raw Git checks use commit `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd`; they do not rely on the clone's checkout.

[`independent-review-002.json`](../../artifacts/goal-quality-flash-lite/independent-review-002.json) records source/input hashes, exact Git commands, per-citation source excerpts, final answers, native continuation/allowlist checks, successful tool sequences, and pending cases. A successful first graph call is not treated as answer quality; the judgments above apply to the completed final answers.

## Addendum — 2026-10-18T14:39:38Z

Both ambiguity finals are now reviewed. **Graph correctly identifies `Signer.unsign` and `TimestampSigner.unsign`**, cites full implementation spans `signer.py:244–256` and `timed.py:72–158`, and does not count overload stubs as separate implementations. One successful `symbols(name="unsign", revision=<pinned SHA>)` call supplies both exact owner-qualified identities; independent raw Git confirms them against enclosing classes at `signer.py:76` and `timed.py:22`. No traversal was required for this local-definition ambiguity: this is evidence of choosing a suitable definition lookup rather than forcing dependency hops.

**Plaintext still fails the class-owner question**, naming `TimedSerializer` “or its subclasses” instead of `TimestampSigner`. It reads the `timed.py:50–80` method region without its enclosing class at line 22, so the earlier missing-context failure persists despite shared reasoning guidance. Both final references are real signatures, but the incorrect owner is not supported. This limits any claim that guidance alone repairs all reasoning. The static-limit pair remained pending at this addendum; no case was rerun by the reviewer.

## Addendum — 2026-10-18T14:41:27Z

The static-limit **plaintext** attempt ended with `MODEL_INPUT_BUDGET_EXHAUSTED`, answer null, after 10 tool calls and 90,388 reported input tokens. This is an attempted question failure, not a successful uncertainty explanation and not a source-quality pass. Its failure remains in the record. The graph static-limit result is still pending; no interim call is credited as a final answer.

## Final addendum — 2026-10-18T14:43:03Z

All six run-005 attempts have now been reviewed. The **graph static-limit** answer reaches the correct uncertainty conclusion but again fails material citation grounding: final `serializer.py:315–325` covers `dumps`/`dump`, not **`Serializer.loads:330–345`** and calls339/341. Final 240–255 includes only the beginning of `load_payload`, excluding the stated serializer calls at263/265. Final290–300 documents fallback construction and begins its loop but excludes tuplehandling303–304 and construction309. The actual implementations were present in retrieved pages, so valid file hashes do not justify these final spans. Its “classes or instances” wording also exceeds the documented fallback forms: dict, signer class, or class/kwargs tuple; arbitrary signer instances are not established by that source.

All nine operations in this graph-arm static case return `OK`, so the earlier omitted-revision TypeErrors do not recur. Its first `symbols(name="Serializer.loads")` returns zero, then it uses raw search and source reads; there is **no dependency traversal** in this case. This is permitted optional tool choice, not a graph-walk success. A repeated identical literal search still finds the protocol stub rather than the multiline implementation, showing remaining selection inefficiency despite improved argument shapes. The final does not claim exhaustive runtime absence or runtime verification.

| Final scoped ledger | Judgment |
| --- | --- |
| Graph multi-hop | Correct paths and precise supporting declarations |
| Plaintext multi-hop | Core paths true; material final citation spans fail |
| Graph ambiguity | Correct two owner identities and implementation citations |
| Plaintext ambiguity | Wrong `TimedSerializer` owner persists |
| Graph static-limit | Correct uncertainty; material final citation spans fail |
| Plaintext static-limit | Input-budget failure, no answer |

This supports a narrow conclusion: typed arguments and optional tool guidance produced successful graph calling and two source-grounded graph finals in these development attempts, while citation selection, some owner reasoning, and budget efficiency remain unresolved. It does not establish a causal graph advantage or full T2 acceptance. No reviewer provider calls, reruns, source changes, or endpoint changes occurred; earlier attempts and snapshots remain intact.
