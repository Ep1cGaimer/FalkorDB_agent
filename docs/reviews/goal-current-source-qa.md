# Current working-source parent QA

The current **full-004** run passed **1,244 tests**, with **6 missing-artifact
skips** and **3 live exclusions**, in **250.75 seconds**. All **199** source
hashes matched before/after. Its owned containers were removed. This covers the
source-byte preflight repair and ten new regressions. The [repair report](goal-source-budget-repair.md)
distinguishes current tests, independent narrow revalidation and historical
198-file experiments. No complete acceptance gate is released by these counts.

The latest **full-003** working-source run passed **1,234 tests**, with the same
**6 missing-artifact skips** and **3 live exclusions**, in **247.92 seconds**.
All **198** recorded files matched before and after; both real-repository flags
were enabled and both owned QA containers were removed. This covers the current
native continuation implementation and deterministic demo source as well as the
earlier fixes. It is parent development QA, not full acceptance or independent
current reproduction. See the [current delivery evidence](goal-hackathon-delivery.md)
and [raw full-003 summary](goal-hackathon-delivery-evidence/full-qa-003/summary.json).
The older counts and separately pinned follow-ups below remain historical.

The newer **full-002** run on 2026-10-18 passed **1,213 tests**, with **6 missing
artifact skips** and **3 live exclusions**, in **246.32 seconds**. Both real-repo
flags were enabled; all **192** recorded source/test hashes matched before and
after. Its owned database/runner containers were removed. This remains parent
development QA. The citation guard, immutable retrieval lock and empty-file
evidence repairs are covered by this run. The later compact-context renderer
passed three separate tests and is outside the 192-file full-run pin. Exact
records are in the [citation integrity report](goal-citation-integrity.md) and
[full-002 artifacts](goal-citation-integrity-evidence/full-qa-002/).
Two existing metering/test files subsequently changed to reject visible generated
text with missing/zero output-token metadata. That follow-up passed71 affected
tests and an exact recorded-response replay. It is separately pinned as the v2
source capture and is not covered by a claimed fresh full-suite run.

## Earlier full-001 run

On 2026-10-18 the full staged non-live suite passed **1,172 tests**, with **6
skipped** and **3 live tests deselected**, in **251.60 seconds**. Both
`RW_REALREPO=1` and `RW_REALREPO_SMOKE=1` were enabled. Requests and ItsDangerous
onboarding and the Requests bounded-history smoke ran. JavaScript separately
passed **16/16**, and the deterministic fixture smoke passed with cleanup.

This is a **parent-run development check, not independent reproduction or full
T0–T11 validation**. It uses a clone of parent commit `520e8fa`, overlaid with the
actual working changes and new files. No source commit or clean-tree claim is
invented. All **186 recorded implementation/configuration/test file hashes**
matched the original working source before the run and matched again afterward
and after the supplemental smoke. The canceled handoff draft was excluded.

Python ran in a disposable container sharing only its own FalkorDB container's
network namespace. Hardcoded test port6379 therefore reached the owned database,
not the host's existing service. Runtime: Linux/aarch64 Python3.12.9,
Git2.39.5, Node26.10.0, MCP2.3.0 and the recorded resolved dependency pins. The
dependency venv was reused from the earlier independently prepared environment;
this is not represented as a newly independent installation. Exact image IDs,
Dockerfile, commands, package versions, raw logs, JUnit and before/after hashes are
in [goal-current-qa-evidence](goal-current-qa-evidence/).

The six required skips remain explicit: absent E2 history output, absent E2/E4
evaluation output, absent scale output, missing scale and benefit run categories,
and an empty historical artifact parameter set. Passing artifact-shape tests do
not replace those missing experiments. Artifact-parameterized counts can grow as
attempts accumulate; 1,172 is not a question or accuracy denominator.

The test image's package download/setup time is retained separately. The runner
used an OS-isolated namespace and owned containers; neither the user's database,
issue22 service nor other unrelated containers were stopped. Both QA containers
and the separate smoke container were removed. The staged checkout and owned
image remain as reproducibility/cache prerequisites.

A later file-identity utility and its 14 passing unit tests were added after this
full run. They are separately recorded in the
[corpus token-count report](goal-corpus-token-counts.md), outside the 186-file pin.
The working-source graph report and later source capture distinguish these
versions. Every S/E/T gate remains IN_PROGRESS.
