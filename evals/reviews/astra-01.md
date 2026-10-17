**RollbackWitness independent correctness review — 2026-10-15**

**Answer: yes.** The checker can report `BOUNDED_PASS` without evidence for every declared reader, can accept a reader-generated fake PASS, and can approve simulation using evidence whose underlying bytes have changed. Exact receipt tuple comparison itself held up; several failures occur before tuple construction or after verification.

| Rank | Severity | Finding | Primary location |
|---|---|---|---|
| 1 | P1 / High | Losing one of multiple declared reader edges silently removes failing obligations | `src/rw/verification.py:191` |
| 2 | P1 / High | Reader prints PASS and exits zero without returning; checker accepts PASS | `src/rw/probes.py:117` |
| 3 | P1 / High | Changing graph route entry to `health` turns an incompatible rollback into a pass | `src/rw/verification.py:264` |
| 4 | P1 / High | Approved simulation succeeds after retained payload bytes change | `src/rw/api.py:355` |
| 5 | P1 / High | Session verifies against a cached manifest after disk coverage changes to PARTIAL | `src/rw/pipeline.py:93` |
| 6 | P2 / Medium | Manifest writer/format unknowns and contradictions are ignored | `src/rw/verification.py:229` |
| 7 | P2 / Medium | Non-HTTP investigation loop ignores grounding validation errors | `src/rw/pipeline.py:178` |
| 8 | P2 / Medium | Valid zero-obligation pass loses snapshot identity and cannot simulate | `src/rw/verification.py:350` |

P1 means an unsupported pass or action under a concrete evidence failure. P2 covers incorrect provenance/grounding or a valid workflow being refused. Graph mutation cases model incomplete or inconsistent imported evidence; they are **not** claims that request text can execute arbitrary graph mutations. Fixture extensions and byte changes were confined to private copies under `evals/reviews/scratch/`.

**Execution and scope**

Read `AGENTS.md`, `ROLLBACKWITNESS_IDEA.md`, `docs/CONTRACTS.md`, and all eight requested modules, plus the actual reader harness. No edits to application code, tests, root fixtures, docs, `grounding.py`, or `static/`; no commit. An existing `scratch/astra_01_repro.py` was inspected and executed, then independently supplemented with `scratch/astra_01_extra.py`. All graph integration cases used real local FalkorDB at `127.0.0.1:6379`, real queries and real subprocess probes, with private `rw_review_<hex>` graphs deleted in `finally` blocks. API cases injected deterministic grounding and a scratch SQLite path; they did not inject verdicts or receipts.

Commands actually executed from the repository root:

```powershell
.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py
.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_extra.py
.venv\Scripts\python.exe -B -m pytest tests/test_verification.py tests/test_probes.py tests/test_simulation.py -q -p no:cacheprovider --basetemp=evals/reviews/scratch/astra_pytest_20261015_1
```

The primary script was rerun after concurrent API edits were observed. Final primary output is in `scratch/astra_run_199fd0b1/results.jsonl` (local review scratch, not kept in the repo); supplemental output is in `scratch/astra_extra_c91735cc/results.jsonl` (local review scratch, not kept in the repo). Both exited 0. Earlier primary output is retained in `scratch/astra_run_8d6d86bc/results.jsonl`. JSON excerpts below are actual output, not expected results. Focused test output:

```text
.........................................................                [100%]
57 passed in 1.60s
```

The passing existing tests do not cover the false-pass reproductions below. No live-model evaluation or benchmark was run. API line numbers refer to the version with `replay_file` at line 157 and `simulate_plan` at line 355; this file was being changed concurrently.

**1. P1 — A missing EXECUTES_ROUTE edge can hide only the incompatible reader**

Locations: `src/rw/verification.py:191-204`, `:240-243`, `:299-301`; `src/rw/graph.py:833`.

Scenario: in a scratch release, declare two actual cart routes: the normal compatible reader and an additional `legacy_reader` whose real entry raises on retained records. Import and verify: six obligations, `BLOCKED`. Delete only the `EXECUTES_ROUTE` edge to `legacy_reader`, leaving the release declaration, ReaderRoute node, reader code and records intact. Verify the same plan: four obligations, no gaps, `BOUNDED_PASS`. The checker diagnoses a missing route only when **all** routes disappear. Its expected pair set is derived from the surviving graph routes, so it cannot detect partial reader loss.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F3_missing_one_of_two_routes`). Real output:

```json
{"after": {"disposition": "BOUNDED_PASS", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}, "before": {"disposition": "BLOCKED", "gaps": [], "obligations": 6, "results": ["PASS", "FAIL", "PASS", "PASS", "PASS", "FAIL"]}, "case": "F3_missing_one_of_two_routes", "orphan_routes": 1}
```

Fix: independently load the exact artifact's declared route ID set, validate the artifact hash, and compare it with graph route IDs per executing release before deriving obligations. Missing or extra routes must add an explicit gap even when another route survives. Preserve the orphan reader in the explanation. Add a two-route regression test, including a missing incompatible route.

**2. P1 — stdout is accepted as proof the reader returned**

Locations: `src/rw/probes.py:114-118`; `fixtures/shop/harness/run_reader.py:51-57`, `:69-70`.

Scenario: a real scratch codec's `read_cart` prints `{"status":"PASS","shape":{}}` and calls `sys.exit(0)`. It never returns a dictionary. The harness catches `Exception`, which does not catch `SystemExit`; the parent accepts the process's exit code and stdout as a harness-produced PASS. All four obligations pass and the complete pipeline reports `BOUNDED_PASS`. Even `{"status":"PASS"}` without `shape` is accepted.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F1_forged_harness_pass`). Real output:

```json
{"case": "F1_forged_harness_pass", "disposition": "BOUNDED_PASS", "gaps": [], "harness_exit": 0, "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"], "stdout": "{\"status\":\"PASS\",\"shape\":{}}\r\n"}
```

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_extra.py` (`harness_pass_then_exit_no_shape`). Real output:

```json
{"case": "harness_pass_then_exit_no_shape", "disposition": "BOUNDED_PASS", "exit": 0, "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"], "stdout": "{\"status\":\"PASS\"}\r\n"}
```

Fix: isolate reader output from the result protocol and emit PASS only after observing an actual dictionary return. Catch premature `BaseException` exits during module loading and entry execution. Validate the complete PASS schema. Merely requiring `shape` is insufficient: the first reproduction includes it. For hard process exits, use a completion channel that reader stdout cannot impersonate; absent completion must be UNKNOWN. This is a protocol-integrity issue, not a claim that the current fixture codecs are malicious.

Negative controls: plain `sys.exit(0)` produced empty stdout and UNKNOWN; printing PASS then raising `ValueError` produced exit 10 with two JSON lines and UNKNOWN, never PASS. Those two cases already fail closed.

**3. P1 — Route declaration hash is trusted without checking the executed entry**

Locations: `src/rw/verification.py:264-272`, `:295-296`; `src/rw/graph.py:837-838`; `src/rw/probes.py:61-72`.

Scenario: verify the actual cart 1.4 rollback against cart/v2 retained bytes: `BLOCKED`. In the private graph, set that route's `entry` property to `health`, retaining its route ID, claimed route contract hash, release ID and codec hash. Reverification runs the real `health` function, which returns a dict without decoding the retained bytes. It reports `BOUNDED_PASS` under the same plan and route contract. The probe spec is newly derived from the altered entry, so the preflight spec check also passes.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F2_mutated_route`). Real output:

```json
{"after": {"disposition": "BOUNDED_PASS", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}, "after_entry": "health", "before": {"disposition": "BLOCKED", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "FAIL", "PASS"]}, "before_entry": "read_cart", "case": "F2_mutated_route", "same_plan": true, "same_route_contract": true}
```

Fix: verify route entry, store, read domain, name and contract against the independently loaded, hash-validated release declaration. Recompute the route contract hash from those authoritative fields. Derive the probe entry from the verified declaration. Keep tuple matching as-is; this exploit constructs a misleading new tuple rather than reusing a mismatched old receipt.

**4. P1 — Simulation rechecks the manifest but not the evidence bytes**

Locations: `src/rw/api.py:304-307`, `:330-337`, `:355-374`; `src/rw/simulation.py:71-93`.

Scenario: through the real API, verify and approve a passing plan. Change the scratch retained payload bytes without changing manifest.json. Reconfirm scope: the API returns the cached pass. Simulate: HTTP 200, `applied=true`. Immediately run a fresh actual check: both obligations for that record become UNKNOWN due to payload hash mismatch, yielding `NEEDS_EVIDENCE`. This happens even with fresh prior human approval and correct idempotency. Original and scratch manifest bytes are identical in this case, so the API's hardcoded root-manifest check genuinely matches the approved hash.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F5_stale_probe_simulated`). Relevant fields from its real output:

```json
"verified": {"disposition": "BOUNDED_PASS", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}
"cached_reconfirm": {"disposition": "BOUNDED_PASS", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}
"fresh_check": {"disposition": "NEEDS_EVIDENCE", "gaps": ["RECEIPT_UNKNOWN", "RECEIPT_UNKNOWN"], "obligations": 4, "results": ["PASS", "UNKNOWN", "PASS", "UNKNOWN"]}
"simulation_http": 200
"applied": true
"repeat_applied": false
```

Fix: before approval and application, validate that bound payloads, artifacts, route declarations, harness/environment and graph completeness remain current, or pin immutable content-addressed inputs for the approved action. Reject drift and require re-verification plus new human approval. Do not silently substitute a new verification for an already approved hash. If unchanged evidence is revalidated, preserve the approved receipt identity; receipt timestamps make a newly executed verification hash differ.

Limit: payload drift was executed; analogous code/environment drift follows the same missing revalidation path but was not separately exercised at the API action boundary. No production deployment occurs in this repository.

**5. P1 — The session compares a cached manifest hash to another cached hash**

Locations: `src/rw/pipeline.py:66-67`, `:91-94`; `src/rw/verification.py:166-167`.

Scenario: construct a session and plan, then change its scratch snapshot manifest coverage from COMPLETE to PARTIAL. Call `Session.verify` after that disk change. It passes `self.manifest` and `self.manifest_hash`, both loaded during session construction, into the checker. The stale-snapshot comparison therefore succeeds and verification reports `BOUNDED_PASS` with no coverage gap.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F4_manifest_changed_after_session`). Real output:

```json
{"cached_hash": "sha256:416e1df3791f754c6d1224ca7a458b262c3c27bfec0bbf308dadbb477d74091c", "case": "F4_manifest_changed_after_session", "disk_coverage": "PARTIAL", "disk_hash": "sha256:70441d5f774d2ce1975752f64aecfc9d5880787084cdcf8d49e5fb2accdb6f92", "disposition": "BOUNDED_PASS", "gaps": [], "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}
```

Fix: retain the session's authoritative fixture/snapshot location and reload manifest bytes at verification. Compare the fresh hash with the plan and graph snapshot identity. Changed bytes must create `STALE_SNAPSHOT`; do not replace the plan's binding silently. Recheck before approval too. Distinction from finding 4: this changes the manifest itself; finding 4 changes bytes while leaving the manifest unchanged. Simulation's fresh manifest hash check correctly rejects a changed manifest, limiting this finding to stale verification/approval before that final gate.

**6. P2 — Writer and format evidence need only be truthy graph values**

Locations: `src/rw/verification.py:223-238`, `:271-275`.

Scenario A: graph writer/format for saved-cart-1001 are changed to checkout 2.1 / cart/v999, while the independently parsed manifest still says cart 1.4 / cart/v1. Probes pass and the report presents the contradictory writer path and format with no gap. Scenario B: the scratch manifest explicitly has null writer and format; add a graph WRITTEN_BY edge and set graph format to literal `UNKNOWN`. It still reports `BOUNDED_PASS`. The code checks manifest payload hashes but never reconciles manifest writer/format, and its truthiness check accepts `UNKNOWN` as established format evidence.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_extra.py`. Real output:

```json
{"case": "metadata_contradicts_manifest", "disposition": "BOUNDED_PASS", "gaps": [], "manifest_format": "cart/v1", "manifest_writer": {"service": "cart", "version": "1.4"}, "obligations": 4, "reported_format": "cart/v999", "reported_writer": "release:checkout:df9a7917d5945176", "results": ["PASS", "PASS", "PASS", "PASS"]}
{"case": "manifest_unknown_ignored", "disposition": "BOUNDED_PASS", "gaps": [], "graph_format": "UNKNOWN", "manifest_format": null, "manifest_writer": null, "obligations": 4, "results": ["PASS", "PASS", "PASS", "PASS"]}
```

Fix: resolve the manifest writer to an exact imported artifact and compare it to the graph writer set. Preserve manifest unknowns as gaps unless separately validated provenance evidence explicitly establishes them. Compare format identities and reject null, empty and literal UNKNOWN as established evidence. Duplicate or conflicting writer edges should be gaps, not a choice of whichever row survives dictionary construction. This finding proves unsupported provenance/completeness, not actual byte incompatibility: the readers did consume these bytes.

**7. P2 — run_investigation proceeds despite adapter validation errors**

Locations: `src/rw/pipeline.py:162-178` (previously `:153-160`); compare the correctly gated API at `src/rw/api.py:219-227`.

Scenario: inject a `GroundingResult` containing a valid existing-artifact proposal and nonempty `validation_errors` stating that an invented citation was dropped. The non-HTTP loop ignores those errors, rematerializes the remaining proposal, invokes confirmation, and verifies a plan with no source hashes. It labels the outcome `BOUNDED_PASS` and its top-level validation errors are empty. This demonstrates the loop's handling of an adapter-rejected result; no claim is made that the live provider spontaneously produced it.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_repro.py` (`F6_grounding_errors_ignored`). Real output:

```json
{"adapter_errors": ["CITATION_UNKNOWN_EXCERPT: malicious invented citation; dropped"], "case": "F6_grounding_errors_ignored", "outcome": "BOUNDED_PASS", "pipeline_errors": [], "source_hashes": []}
```

Fix: propagate `grounding.validation_errors` into the attempt and reject before scope confirmation, as the HTTP path already does. Also validate the returned request binding in this shared entrypoint. Keep a compatibility pass distinguishable from accepted request grounding. This does not prove a byte-reader incompatibility; it proves an ungrounded/rejected proposal is allowed through the advertised end-to-end loop.

During finalization, another writer added clarification handling to `pipeline.py`, shifting this location to line 178 without fixing the finding. Re-executed only this affected reproduction on the new source; it produced the same output above. Log: `scratch/astra_run_3bf1bff3/results.jsonl` (local review scratch, not kept in the repo). Exact targeted command:

```powershell
.venv\Scripts\python.exe -B -c "import ast,pathlib; p=pathlib.Path('evals/reviews/scratch/astra_01_repro.py').resolve(); tree=ast.parse(p.read_text()); first=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.With)); chosen=tree.body[:first]+[n for n in tree.body if isinstance(n,ast.With) and 'F6_grounding_errors_ignored' in ast.unparse(n)]; scope={'__file__':str(p),'__name__':'__main__'}; exec(compile(ast.Module(body=chosen,type_ignores=[]),str(p),'exec'),scope); scope['emit']('complete',results=str(scope['LOG']))"
```

**8. P2 — Empty complete inventory erases the verification's snapshot binding**

Locations: `src/rw/verification.py:324`, `:350-356`; `src/rw/contracts.py:220` (`GraphEvidence` has no explicit snapshot binding).

Scenario: in a scratch snapshot with COMPLETE coverage, set the retained inventory to an empty list. The graph agrees, both readers exist, and a zero-obligation `BOUNDED_PASS` is legitimate. `dispose` derives snapshot identity solely from the first obligation, so it returns empty snapshot ID and manifest hash. An approval matching that verification can be recorded, but simulation against the actual unchanged manifest refuses it as stale.

Command: `.venv\Scripts\python.exe -B evals\reviews\scratch\astra_01_extra.py` (`empty_inventory_loses_binding`). Real output:

```json
{"case": "empty_inventory_loses_binding", "disposition": "BOUNDED_PASS", "gaps": [], "obligations": 0, "results": [], "simulation": "stale snapshot manifest", "snapshot_id": "", "snapshot_manifest_hash": ""}
```

Fix: carry snapshot ID and manifest hash directly in trusted `GraphEvidence`, or provide the verified plan to `dispose`; never infer plan-level binding from the existence of an obligation. Test both empty complete inventories and explicitly stateless fleets. This is a fail-closed availability/binding error, not a false byte-compatibility pass.

**Checks that held up**

| Check | Executed result / evidence |
|---|---|
| Retained Batch without IN_STORE | `NEEDS_EVIDENCE`, three `INVENTORY_MISMATCH` gaps; missing record remained visible through property-anchored inventory |
| Missing WRITTEN_BY | `NEEDS_EVIDENCE`, `WRITER_UNKNOWN` |
| Missing format property | `NEEDS_EVIDENCE`, `FORMAT_UNKNOWN` |
| PARTIAL graph coverage | `NEEDS_EVIDENCE`, `COVERAGE_INCOMPLETE` |
| Missing only reader route | `NEEDS_EVIDENCE`, `ROUTE_EVIDENCE_MISSING` |
| Missing READS_FROM | `NEEDS_EVIDENCE`, `STORE_MISSING` |
| Same inventory count, different record ID | `NEEDS_EVIDENCE`, `INVENTORY_MISMATCH`; actual sets, not just counts, were checked |
| Real query cap=1 for routes, inventory and paths | `NEEDS_EVIDENCE`; all three `TRUNCATED` flags propagated into gaps |
| Wrong payload, codec, route-contract, environment, plan or snapshot-manifest tuple field | `receipt_applicable=false` for every mutation |
| Missing / UNKNOWN / mismatched receipts | Existing focused tests passed; none discharged an obligation; applicable FAIL dominated gaps/PASS |
| Actual stale bytes before probe | Existing tests and finding 4's fresh recheck returned UNKNOWN for changed payload/code; preflight rejects spec/environment drift |
| Plain early exit 0 | UNKNOWN; empty stdout did not count as PASS |
| Print PASS then raise | UNKNOWN; exit 10 and extra output did not count as PASS |
| Scope/approval identity `""` | HTTP 422 |
| Scope/approval identity whitespace, `model`, `agent`, active `review-model`, padded uppercase default model | HTTP 409 |
| Approve before verification | HTTP 409 |
| Nonpass approval/simulation; changed plan/verification/approval fields; unrecorded approval | Existing simulation tests passed, including concurrent duplicate calls |
| Changed manifest at API simulation | HTTP 409, `stale snapshot manifest`; supplemental API check injected only the fresh loader hash to avoid editing root fixtures |
| Changed server-held plan | Old plan URL returned HTTP 404; direct changed-plan/hash rejection also passed existing tests |
| Same approved simulation twice | First `applied=true`, second `applied=false`; SQLite concurrent exactly-once test passed |
| Flags true versus false | Both had four identical reader/record pairs and `BOUNDED_PASS`, but plan hashes and all obligation hashes differed; receipts cannot transfer across flag settings |
| Cypher-looking service/excerpt strings | Service rejected by allowlist; excerpt string remained a query parameter and returned zero rows; graph retained 65 nodes |
| Replay traversal and absolute outside path | HTTP 422 before replay reading; current API confines selection to saved JSON files in its transcript directory |

Request/model strings did not reach graph-name selection or dynamic Cypher text in the reviewed path. Graph names and snapshot selection are server-owned. Dynamic query-label/type interpolations are importer constants, and the history hop interpolation is a fixed constant. The operator can select a replay filename, but the current API resolves and confines it. Codec/payload paths come from importer data, not model tools; the low-level Python import/probe APIs accept trusted paths and are not filesystem sandboxes. Do not expose those low-level arguments as model tools without adding confinement.

Flags are safe for this fixture's modeled readership: neither value removes an obligation, and the probe entry does not receive runtime flags. Therefore these checks establish only unconditional byte/shape readability, not flag-dependent reader behavior or semantic correctness.

**Review identity and handoff**

Source SHA-256 captured during review (useful because the working tree is concurrent):

```text
contracts.py    27202650BA03C93B504DAAE83A250F6C1DB176223F88419FAFD564AAA3450B63
graph.py        EB32EB8485365DE7F0ADA65DB5781157176325D4CC673F3A049BC813FF82B29A
verification.py ADDC92933B40DB40B7E25A68D5CAE5F278F60DECB403DDD19FBC79B5320D50CF
probes.py       C00F0A45E4613E28355C2670D0952AB1644A0A4A86801F78C8ABE30BF3F13251
pipeline.py     0D4F7D352096E4B561505E8A2BC89EE82D1CFB4FBE7C76D895DD6332A8E891FA
simulation.py   BC52F3F8F9EE32734E01366875BFB310CA7EFFDCCF8DB89A717FC73772948424
api.py          19B3011B82FBCAF2B4FD4CB0E6C08459B97BDB820C2DFC13D35C9A7654DABD95
run_reader.py   8296ACFF7E8E747D13C8DC5B4D9E54A0F47AC3C1E6296616EADEC630766C2BAC
```

Final `pipeline.py` hash after the concurrent clarification addition and targeted rerun: `0F5139378D47C7EE49614FADC416729035DDFA163D4E035C6A0E68323A87D6B1`. Its `Session.verify` code was unchanged.

Read-only server check confirmed Redis `8.10.2`, graph module `60002`, and the configured `RESULTSET_SIZE=10000`. Comparing graph-created/deleted events from the two full primary runs and supplemental run with live `GRAPH.LIST` returned:

```json
{"created": 32, "deleted": 32, "owned_graphs_remaining": []}
```

The subsequent targeted rerun created and deleted one more graph, `rw_review_33e76464c24d4db1b533597de36d58dc`.

Review deliverables: this report, the supplemental reproduction script, and execution artifacts under scratch. No implementation fixes made. No runtime blocker encountered. Next action: give the checker owner findings 1–6 and the pipeline owner findings 7–8; require the demonstrated false-pass cases to become fail-closed regressions before integration acceptance.
