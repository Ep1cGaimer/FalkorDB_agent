# Source-byte preflight repair — independent revalidation

**The previously observed source-byte overflow is fixed in the tested paths: 8/8 narrow checks pass.** This revalidation targets the **199-file candidate** at `artifacts/goal-source-preflight/implementation-manifest.json`, SHA-256 `534424a9c8032a4a120e34180e5bba288968b1a78f78aabb1d658a1679b4d709`. The earlier 198-file pin and its failures remain historical evidence; they are not presented as the current implementation.

The independent harness generated a new Git repository with a 159,984-byte Python source blob and a 159,985-byte edited version. It indexed both revisions into its own disposable pinned-image FalkorDB container, then observed real `GitRepo._proc` calls while delegating their execution unchanged. Indexing reads are excluded from the retrieval byte measurements.

| Narrow check | Observed result |
| --- | --- |
| Original 159,984-byte source under one-byte query limit | Zero blob payload commands, zero payload stdout bytes, source counter zero; explicit incomplete page with RETRIEVAL_BUDGET_EXHAUSTED |
| Deterministic investigation under the same limit | Zero payload bytes/counter; no answer, findings, facts, or citations |
| Exact-fit query limit 159,984 | Exactly 159,984 payload bytes and source counter 159,984; both independently expected logical symbols returned |
| `patch` and `patch_id` under one-byte limit | Rejected before patch generation; zero patch payload bytes and source counter zero |
| Exact-fit old/new reservation | Both operations reserve exactly 319,969 bytes; outputs equal real Git outputs computed outside the bounded scope; a repeated operation is rejected without increasing the reservation |
| Declined counter charge | Starting at 2/4 bytes, declining another 3 leaves the counter at 2 |

The exact-fit `patch` payload contains 131 output bytes; `patch_id`'s diff payload contains 160,136 output bytes. These differ from the source reservation because it conservatively accounts both complete old/new source blobs, not the emitted diff size. Measurements record real Git child stdout payload bytes. They do **not** claim attribution of operating-system filesystem or disk reads; metadata commands still execute during preflight.

Evidence: [`run-005-source-revalidation`](../../artifacts/goal-bounded-retrieval-audit/run-005-source-revalidation/). It contains `cases.json`, `git-traces.json`, parameterized graph/page traces, independent expected Git trees and blob identities, exact subprocess commands, configuration/hardware/container inspection, source hashes before and after, candidate-pin verification, and cleanup. All 98 applicable implementation/public-test files in the safe hashed subset agree with the 199-file candidate pin, and the before/after snapshots are identical. Held-out files were not opened, including for hashing.

The tested production source hashes are:

```text
src/rw/repo/git.py    ed67b601bdeee97fd215590e4d87b4f1585a47ddf9ceddcc2ae3b4b59f8847c4
src/rw/repo/budget.py 16cdc7ac17ae2a447420b178953d3c368517a6a3e25fc86e4ab8fa66eaf1ddce
src/rw/repo/query.py  e3656fd4013e3e8a4c06c909c8800a6b148e8a7fcb89b3cce23ebad30a80baeb
```

The run completed in 7.90 seconds. Its container `eafc01a922b01a1a7ab07f8b0ebcb436015988239613e8cc3579ade14ef3da97` was removed, with no remaining audit-owned preflight container. It used the same pinned FalkorDB image, two container CPUs, 1GiB memory, and a Docker-assigned loopback port; it did not access the parallel full-QA database, demo, or host ports 6379/6382. No source edits, model calls, commit, or push occurred.

Reproduce using an unused output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/rw-mcp-compat/bin/python artifacts/goal-bounded-retrieval-audit/revalidate_source_preflight.py --output artifacts/goal-bounded-retrieval-audit/source-revalidation-002
```

The original overflow FAIL, harness failure, interrupted long-union attempt, and prior source snapshots are preserved in the [original audit](goal-bounded-retrieval-audit.md). Only these eight source-preflight cases were rerun against the 199-file candidate; the earlier 38 distinct successful probes were **not** rerun or relabeled current. This is a narrow repair validation, **not a full T5 pass**; production-sized complete unions, broader answer-level gates, and real provider-budget evidence remain outside its scope.
