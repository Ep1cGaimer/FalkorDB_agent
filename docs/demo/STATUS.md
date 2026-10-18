# Primary demo status — 18 October 2026

Demo: **http://localhost:8127**. Primary verification recorded before18:45 IST.
This is a development demonstration, not full T0–T11 acceptance.

The later199-file source-byte repair passed1,244 parent tests (6 missing-artifact
skips,3 live exclusions),8 independent narrow checks, a fresh focused demo smoke
and actual browser citation/boundary/replay/live checks. The server was restarted
on that build. The three earlier complete rehearsals retain their original source
pins; this later focused recheck does not replace them or imply full T11 acceptance.

| Primary item | Observed result | Evidence |
|---|---|---|
| P1 — Useful end-to-end investigation | PASS for supported deterministic question shapes. A fresh question uses the existing product investigation workflow and returns a source-backed answer from live FalkorDB. No provider/API key is needed. | `artifacts/hackathon-demo/browser-rehearsals.json`, referenced raw run receipts |
| P2 — Inspectable citations | PASS in the demonstrated flow. Browser displayed exact-commit source and content-hash verification; focused smoke resolves every returned dependency citation. | Browser source step; `rehearsal-*-smoke.log`; source endpoint |
| P3 — Multi-hop finding | PASS on inspected ItsDangerous2.2.0. URLSafeTimedSerializer connects through TimedSerializer and URLSafeSerializerMixin to Serializer. Parsed/static-inferred provenance is shown. | Live graph edges, source citations and actual parameterized query traces in run JSON |
| P4 — Correctness boundary | PASS on the declared synthetic Git trap: PRESENT at the fix; ABSENT after revert although the fix remains an ancestor. Separate live queries expose truncation and a missing symbol. | Fixed/reverted/bounded/missing run receipts linked from browser rehearsals |
| P5 — Repeatable flow and backup | Three consecutive automated browser-flow rehearsals passed after distinct index publications/reset commands, including fresh real-repository questions. Replay/source snapshots worked with the owned DB stopped; live failure remained explicit. Setup/reset/launch instructions exist. | `browser-rehearsals.json`, `offline-backup.json`, [walkthrough](HACKATHON.md) |

Budget:10 seconds of shared cooperative retrieval budget per investigation; zero
LLM tokens; planned spoken walkthrough180 seconds. Recorded automated UI sequences
took32.019,4.817 and4.853 seconds. These are interaction timings, not narrated
presentation durations, model latency measurements or T6 benchmark results.

The source-pin and logs distinguish a small later failure-display cleanup from
the three complete rehearsals: failed live queries clear prior results. The
underlying query path is unchanged. A targeted actual browser follow-up verified
that cleanup, manual replay during an outage, and return to a fresh live answer.
It found and repaired an automatically reassigned Docker port by recreating only
the owned demo container with a fixed55688 binding; `recovery-followup.json`
retains the failure, repair and fresh run IDs. A prior blank browser refresh is retained as
a setup issue; navigation to a clean localhost tab succeeded before the three
consecutive complete rehearsals.

Supported question forms include `What does <symbol> depend on?` and `Where is
<symbol> defined?`; unsupported questions expose a gap. This is not a general
LLM conversation. Runtime method resolution, runtime compatibility and graph
advantage remain unverified. The revert trap is synthetic and labeled as such.
No narrated human rehearsal, video, independent held-out evaluation or submission
has been claimed. The specialized fixture runtime workflow is not presented by
this repository-evidence demo; no rollback-safety verdict is claimed for it.

The full secondary programme in [goal.md](../../goal.md) remains required and
incomplete. It must not be silently replaced by this demo or its packaging.

A later evaluation-only optional-tool-selection/native-calling repair left
application source and endpoints unchanged. A fresh live smoke passed all seven
checks. Focused Gemini3.1FlashLite development results are recorded separately in
[the agent repair report](../reviews/goal-flash-lite-agent-repair.md); they do not
turn this deterministic demo into a general LLM conversation or establish graph
superiority. The graph-capable development agent now correctly answers the
multi-hop and ambiguity cases; material citation failures remain in the static
case. All full secondary acceptance gates remain incomplete.
