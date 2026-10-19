# Recording the incident demo

Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the spoken four-minute take. This runbook covers setup,
exact inputs, fallbacks and the remaining readiness gates. No recording has been published.

## Launch

From the repository root, with the existing virtual environment and local FalkorDB running:

```powershell
$env:PYTHONUTF8 = "1"
.venv/Scripts/python.exe scripts/serve_demo.py
```

Open `http://127.0.0.1:8000`. If that port is already serving another fixture, stop that server or
use `--port 8005` and open the matching address. The dedicated launcher always selects
`astronomy-incident`, uses a separate local simulation ledger, and lists only transcripts in
`artifacts/demo/replays/`. It does not mix the shop test fixture's recordings with incident recordings.
Restart the server after Python changes. The page should show twelve services and 97 retained
records: 40 orders, 37 ledger rows and 20 carts.

The launcher uses the existing local environment configuration. An optional `--env-file` accepts
a local configuration file without printing its values. Keep credentials, private connection
configuration and raw provider logs out of the video, commits and public materials.

## Exact operator input

The first sample should already populate this request:

> Japanese shoppers are seeing wrong totals since 3.2.0. Roll back accounting and fraud-detection
> to 3.1.0, their currency conversion is the suspect. Leave checkout alone.

For a live clarification, answer:

> Yes, you may change checkout's declared localCurrencyCheckout flag to false. Keep the newer
> readers so they can still read the retained orders and ledger rows.

For replay, select the **recorded answer** associated with that exact request and question. The
answer text is part of the bound request; paraphrasing it will not match the next transcript.

## Prepare and validate backups

```powershell
# Makes real model calls using the existing configured provider; runs checks, never simulation.
.venv/Scripts/python.exe scripts/prepare_demo.py --live --runs 2

# Replays saved conversations, then recomputes graph obligations and real reader receipts.
.venv/Scripts/python.exe scripts/prepare_demo.py --replay-dir artifacts/demo/replays --runs 2
```

Successful live loops are copied into fixture-specific bundles only after a fresh replay produces
the same plan hashes and the expected results. Every rehearsal, including provider failures, is
reported under a unique `artifacts/demo-readiness/<timestamp>/` directory. `ready: false` is a
failed gate. The tool confirms scope for checking only; it never creates a simulation approval.

For a saved bundle with three transcripts, choose them in order: initial proposal, alternative
clarification, answered proposal. The replay picker displays model origin, recording time and
recording ID. Keep **Replay · not live** visible throughout.

## Required observations before recording

| Gate | Expected evidence |
|---|---|
| Correct fixture | Twelve services; orders 40, ledger 37, carts 20; synthetic label. |
| Initial proposal | accounting and fraud-detection 3.1.0; checkout unchanged. Grounded source citations resolve. |
| First check | Green startup; **BLOCKED**; 137 obligations and 48 applicable FAIL receipts. |
| Failure witness | A real accounting 3.1.0 `reconcile_ledger` failure on a `ledger/v2` payload. |
| Origin view | Sixteen ledger rows trace one hop to orders written by checkout 3.2.0. Complete lineage metadata; no hidden gaps. |
| Alternative | Permission for broader checkout scope is explicit; all builds 3.2.0, checkout flag false. |
| Second check | Fresh **BOUNDED_PASS**, 137/137 PASS, zero failures. |
| Approval | Only human action enables local simulation; applying twice is idempotent. No deployment. |
| Replay backup | Same final fleet and plan hashes after fresh checks; replay label visible. |
| Browser | Graph, receipt drawer and candidate comparison legible at the recording size, no clipped controls or browser errors. |

Additional evidence checks:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_incident_fixture.py tests/test_comparison_guards.py tests/test_lineage_guards.py
node --test tests/js/*.test.mjs
.venv/Scripts/python.exe evals/ablation_relationships.py astronomy-incident
```

The ablation uses disposable graphs. Removing `DERIVED_FROM` must preserve the 48 failing reads
while losing complete upstream lineage. Removing reader/store/record links must yield
**NEEDS_EVIDENCE**, never an unsupported pass. Do not alter the displayed investigation's graph.

## Capture and edit

Use a 16:9 window at 1920×1080 if available. Set browser zoom once so body text and graph labels
remain readable. Close unrelated tabs, hide notifications and move the pointer away from numbers
while speaking. Record the application window rather than the whole desktop.

Capture one complete, correctly labeled flow first. Then record close views of the receipt,
lineage callout and changed flag for cuts. Keep clicks a little slower than normal. Pause after
“48 fail” and “137 pass.” Speak as the on-call engineer explaining a decision to a teammate.

Trim provider and probe waiting time with a visible caption. Avoid changing counts, hiding gaps,
presenting recorded model output as live, or combining results from different plans. Match every
close view to the same investigation and selected attempt. End around four minutes; the script
has optional comparison inserts if a longer technical cut is useful.

## Current readiness evidence — 2026-10-19

- Final affected rollback/API/graph/probe/approval/UI suite: **661 passed, 2 deselected**, 956.24s.
  It includes the 22 incident integration tests, comparison guards and provenance helper tests.
  Final comparison/UI follow-up: **27 passed** (14 comparison guards, 13 UI/cache tests); final JavaScript suite: **28 passed**. MCP clients,
  integration and stdio: **121 passed**. Source compilation and local document links also pass.
- Both genuine three-stage replay bundles were rehearsed on fresh graphs and real retained bytes:
  **BLOCKED → CLARIFICATION → BOUNDED_PASS**, 137 checks/48 failures followed by 137/0. Both
  plan hashes match the originals. Evidence: `artifacts/demo-readiness/20261019T004240Z/` (explicit plan-hash equality guard passed).
- All seven relationship-removal conditions ran, preserving 485 nodes each. See the
  [measured results](../results/RESULTS.md#7-incident-fixture-verification-19-oct-2026) and
  [raw output](../results/raw/ablation_relationships_incident.json).
- Browser review covered citations, all twelve proposed services, the blocked result, ledger
  filtering/receipt, complete lineage, the replay clarification and recorded answer, the flag-off
  proposal and the fresh 137/137 result. The replay label stays visible. No console errors were
  observed. The 390px mobile page fits without page-level horizontal overflow; graph/matrix
  scrolling stays inside their panels. Screenshots are in `artifacts/demo-readiness/screens/`.
- The browser is left at the passing candidate with **Approve local simulation** available.
  The operator performs that final human approval during recording. Approval/idempotency behavior
  is covered by the acceptance suite; the development assistant did not self-approve a simulation.
- New live attempts hit provider quota refusals (two HTTP 413s) and authentication errors (two
  HTTP 401s). They are retained as failures, not counted as successful live demonstrations.
  Use the verified replay path for a dependable recording until live configuration/quota is fixed.
- The earlier broad Windows suite was diagnostic and included mixed source during repairs plus
  repository-workflow platform failures. It is recorded in [STATUS.md](../STATUS.md), separately
  from the clean final affected-suite result above.

Ready for a clearly labeled replay recording. The default launcher command starts a new workspace;
the current local review server is on port 8006. No video or deployment has been published. The
separately requested GitHub README presentation is merged in
[PR #40](https://github.com/Ep1cGaimer/FalkorDB_agent/pull/40), with all CI checks passing.
