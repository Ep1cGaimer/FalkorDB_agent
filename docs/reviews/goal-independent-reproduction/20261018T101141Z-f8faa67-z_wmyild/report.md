# Independent development reproduction — f8faa67

Outcome: **PASS** for the recorded development checks. This is an independent
AI-assisted reproduction, not a human review or full T11/v1 validation.

| Check | Observed result |
|---|---|
| Full Python suite, `-m "not live"`, both realrepo flags enabled | 1068 passed, 0 failed, 0 errors, 6 skipped; 3 live cases deselected |
| JavaScript tests on host Node | 16 passed, 0 failed, 0 skipped |
| Deterministic synthetic smoke | exit 0 |
| Approved source bytes before/after | 168/168 files checked; 0/0 mismatches |
| Sealed evaluator bytes | 14 files checked; 0 mismatches |
| Owned containers remaining | 0 |

The clean clone is `/private/tmp/rw-independent-812ecf7-z_wmyild/repo` and remains retained with its artifacts and fresh
environments. Setup began on `812ecf7`; before any Python test ran, the parent
amended the target to immutable `f8faa67f5b9c9d0d2682ecff7d10d3ac084cf242`. The original setup and approved
source-manifest receipts are both retained. No source or test expectations were
edited to obtain a pass.

Python tests ran on Linux/aarch64 with Python 3.12.9 in a fresh
venv installing the exact pyproject pins, MCP2.3.0 and pytest9.1.1, plus their42
resolved pins. The pinned FalkorDB image was `falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`. Its host port was
OS-assigned on loopback; the Python runner shared only that owned DB's network
namespace and used127.0.0.1:6379 internally. This isolates two legacy fixtures
that explicitly select6379. The shared host6379 service was never used or stopped.

Requests and ItsDangerous were fresh `--bare --no-hardlinks` development copies
at configuration paths. Click's repository and the confirmatory questions were
not used. Node used for Python subprocess checks came from the pinned owned
FalkorDB image; host JavaScript tests used the host Node runtime. Exact versions,
binary provenance, commands, environment, raw setup/test logs and JUnit are retained.

Setup attempts are retained, including Debian HTTP403, a driver quoting error,
mount-path correction, freeze-banner filtering and initial missing libatomic for
Node. Those are setup outcomes, not product-test failures. The final Git-only apt
install and Node prerequisite checks completed before pytest. The initial driver
was stopped/replaced to honor the parent's pre-test source-pin hold.

The exact skip reasons, per-test statuses, realrepo-case outcomes and failure
details are in[report.json](report.json), with raw output under[artifacts/](artifacts/).
The full commands run the unmodified source at the approved pin. To repeat, use a
new clone at that commit, exact pinned requirements, and an owned DB/Python network
namespace; mount the clone at the same absolute path used by its test processes.

No held-out generation, live12-question T11 rerun, blind scoring/recomputation,
comparative advantage experiment or three live demos was performed. T0's frozen
contract and remaining mandatory fields are still pending. These development
checks cannot validate all T0–T11 goals or establish FalkorDB advantage.
