# Quickstart — RollbackWitness (synthetic fixture)

Everything here runs against a small **synthetic fixture shop** (`fixtures/shop/`) on a pinned local
FalkorDB container. There is no production data, no deployment and no external service beyond the
optional live model provider. Read this together with [CONTRACTS.md](CONTRACTS.md) (what the code
promises) and [STATUS.md](STATUS.md) (what has actually been observed).

Observed output below is from the reference machine (Windows 11, Docker Desktop, uv 0.11.19).

Commands are written once, OS-neutrally: `.venv/bin/python` means
`.venv\Scripts\python.exe` on Windows PowerShell, and script paths use `/` (Windows accepts both).

## 0. Prerequisites

| Tool | Used here | Notes |
|---|---|---|
| Docker + Compose v2 | Docker Desktop | the FalkorDB container |
| uv | 0.11.19 | creates `.venv`, installs dependencies, fetches Python 3.12 |
| Git | any recent | clone the repository |
| Python 3.12 | not required on PATH | uv installs/uses 3.12 for `.venv` |

## 1. Clone

```sh
git clone --branch main https://github.com/Ep1cGaimer/FalkorDB_agent.git rollbackwitness
cd rollbackwitness
```

The clone has no `.env` (git-ignored); `.env.example` in the repository root lists the variables that
are read. That only matters for the optional live steps in §6 — the whole non-live suite and the
deterministic acceptance proof run without any credential.

## 2. Start FalkorDB

```sh
docker compose up -d --wait
docker compose ps
```

`--wait` returns once the container's healthcheck (`redis-cli ping`) passes, so the next steps never
race a starting server. Docker Desktop (or another Docker engine) must already be running. If
FalkorDB is not reachable, the test suite prints one warning at the start instead of failing quietly.

Expected: one container `rw-falkordb` (status `healthy`), image
`falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6`,
ports `127.0.0.1:6379->6379` and `127.0.0.1:3000->3000`.

**Already running?** If a container named `rw-falkordb` already holds `127.0.0.1:6379`, do not start a
second one. Validate the file instead — this prints the resolved configuration and touches no
running server:

```sh
docker compose -f docker-compose.yml config
```

## 3. Set up the environment

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1     # Windows PowerShell
```

```sh
sh scripts/setup.sh                                            # Linux / macOS / Git Bash on Windows
```

Both create `.venv` with uv (Python 3.12), install the dependencies declared in `pyproject.toml`, and
install the pinned test runner `pytest==9.1.1` (the `pyproject.toml` dependencies are runtime only —
the test runner is pinned in the setup script so this quickstart needs no extra manual install). The
uv cache lives inside the checkout (`.uv-cache/`, git-ignored). `setup.sh` also picks the interpreter
uv created for the host OS — `.venv/Scripts/python.exe` on Windows (including Git Bash / MSYS),
`.venv/bin/python` elsewhere — so the same script works from Git Bash. `falkordb==1.8.0`,
`redis==8.1.0`, `pydantic==2.14.1`, `fastapi==0.143.2`, `starlette==1.8.0`,
`uvicorn==0.54.0` and `httpx==0.28.1` are pinned in `pyproject.toml`.

For the optional local MCP bridge, add `--mcp` to the POSIX setup command or `-Mcp` to PowerShell.
This installs official `mcp==2.3.0` alongside the unchanged runtime pins. The host launches
`scripts/serve_mcp.py` as a separate stdio process while the HTTP API runs with one worker.
See [MCP.md](MCP.md) for absolute-path host configuration and the human handoff workflow.

## 4. Run the tests

```sh
.venv/bin/python -m pytest -q -m "not live"
```

The suite needs the container from §2. See [STATUS.md](STATUS.md) for current observed base and
MCP-enabled counts; SDK-dependent tests explicitly skip when the optional extra is absent.

Live-marked tests call a model provider and need the selected provider's credential (§6).

CI runs the same checks on every pull request. The single required check, `test`, passes only when:
- the Linux jobs pass: the full suite with and without the MCP extra against the pinned FalkorDB
  service, plus smoke and browser acceptance;
- the Windows job passes: PowerShell setup with `-Mcp` and the portable MCP/UI contract tests.
  Hosted Windows runners can't run the Linux FalkorDB container, so graph-backed tests run on Linux
  only.

Two more checks that need **no model at all**:

```sh
.venv/bin/python -m pytest tests/test_acceptance_oracle.py -q
.venv/bin/python evals/relational_control.py
```

The first is the deterministic end-to-end proof: 8 fixture cases A–H driven through the real server
and the real fixture readers, compared with the independent oracle in
`evals/expected/dispositions.json`. The second loads the same raw facts into SQLite and derives the
obligations with one SQL join; expected tail:

```text
SQL obligations == FalkorDB obligations: 8/8 cases
SQL obligations == independent oracle: 8/8 cases
Note: a tie is a valid outcome; obligation sets are compared as (service, record_id) pairs.
```

A tie is the honest result: the control is not handicapped and is not claimed to be worse.

## 5. Demo: one investigation

Live (needs §6):

```sh
.venv/bin/python scripts/investigate.py "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction." --confirm-as alice
```

Replay of a saved transcript (the CLI labels this `REPLAY — not live`; the browser uses
`Replay · not live`):

```sh
.venv/bin/python scripts/investigate.py "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction." --replay artifacts/grounding/<file>.json --confirm-as alice --no-alternative
```

Transcripts are written to `artifacts/grounding/` (git-ignored) and no transcript is committed, so
replay needs at least one local live run first: either run the live command once, or point `--replay`
at a transcript you saved yourself. `--no-alternative` is needed when you hold a single transcript — a
`BLOCKED` result normally asks the agent for one alternative, which would need a second transcript.

Without a configured provider key, the live command stops with `GroundingError: all models failed`
and structured sanitized error summaries. Check the selected provider's key in `.env` (§6).

Observed on the reference machine (2026-10-16, replay of a saved transcript, so the model is
`replay:<file>` and `live=False`) — the cart rollback is blocked by a real probe (the rationale and
citation lines are elided below; the command prints them):

```text
Request: 'Roll cart back to the build it ran before the basket rollout, but keep the receipt correction.'   snapshot=snapshot:snap-001  (SYNTHETIC FIXTURE)

[REPLAY — not live] grounding from artifacts/grounding/6a8e17d5b92500cf.json

  Proposed fleet (candidate 1, plan plan:55cfbe2d80ebe065):
    [CHANGE] cart      cart 1.4 (release:cart:9703e568235e03f3)
    [keep  ] checkout  checkout 2.1 (release:checkout:df9a7917d5945176)

== Attempt 1: BLOCKED  (model=replay:6a8e17d5b92500cf.json, live=False)
    probe cart 1.4 (release:cart:9703e568235e03f3)      x saved-cart-1001 (cart/v1): PASS
    probe cart 1.4 (release:cart:9703e568235e03f3)      x saved-cart-2002 (cart/v2): FAIL  <- ValueError: unsupported saved-cart format 'cart/v2'
    probe checkout 2.1 (release:checkout:df9a7917d5945176) x saved-cart-1001 (cart/v1): PASS
    probe checkout 2.1 (release:checkout:df9a7917d5945176) x saved-cart-2002 (cart/v2): PASS
    witness: (Plan candidate 1)-HAS_DEPLOYMENT-> (Deployment cart)-RUNS-> (Release cart 1.4)-EXECUTES_ROUTE-> (ReaderRoute load_saved_cart)-READS_FROM-> (StateStore store:cart-cache)<-IN_STORE- (Batch saved-cart-2002 (cart/v2))-WRITTEN_BY-> (Release writer 1.5)
  DISPOSITION: BLOCKED

Report: artifacts\reports\ac67aa0e0768dde7.json
```

The contrast case (`--replay artifacts/grounding/c329bc7f5ad843a2.json`) keeps cart 1.5 with
`basket_v2=false` and passes the same probes (again, rationale/citations elided):

```text
== Attempt 1: BOUNDED_PASS  (model=replay:c329bc7f5ad843a2.json, live=False)
    probe cart 1.5 (release:cart:9d521fc02aa4498e)      x saved-cart-1001 (cart/v1): PASS
    probe cart 1.5 (release:cart:9d521fc02aa4498e)      x saved-cart-2002 (cart/v2): PASS
    probe checkout 2.1 (release:checkout:df9a7917d5945176) x saved-cart-1001 (cart/v1): PASS
    probe checkout 2.1 (release:checkout:df9a7917d5945176) x saved-cart-2002 (cart/v2): PASS
  DISPOSITION: BOUNDED_PASS  (byte/shape readability of modeled records only)
```

Read those two results for exactly what they are. `BLOCKED` comes from a real reader execution on
retained payload bytes: the cart 1.4 reader raised `ValueError: unsupported saved-cart format
'cart/v2'` (harness exit 10) on record `saved-cart-2002`, which cart 1.5 wrote.
`BOUNDED_PASS` means **modeled byte/shape readability only** — not behavioral compatibility, and not
a guarantee that no other writer or reader exists.

`scripts/investigate.py` never approves or simulates an action; approval and local simulation live in
the console (§7) and are separate human steps.

## 6. Live grounding (optional)

Create a git-ignored `.env` in the repository root by copying `.env.example` (which lists the
variable) and filling it in:

```text
GROQ_API_KEY=<your key>
```

Never commit or paste that file. The provider chain comes from `RW_GROUNDING_MODEL`
(comma-separated `provider:model`; a bare name means `gemini:`); the default is
`groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b`. `GEMINI_API_KEY` is optional and only used when a
`gemini:` entry is selected.

The selected free-tier profile is `groq:qwen/qwen3.8-27b` with a 1000-token completion cap. The
author-reported historical comparison says three pairs completed and four transient HTTP 429
responses recovered; raw artifacts are not committed. This profile reduces the workload but does
not promise uninterrupted access. Groq applies limits at the organization level; some accounts separate input and output
allowances, and the exact limits are shown on your [Groq Limits page](https://console.groq.com/docs/rate-limits).
See the [issue #4 decision and browser check](ISSUE_4_QUOTA.md) for the chosen budget profile.

The current client requires tool calls, caps completion tokens at 2048 by default, uses `medium`
reasoning effort for GPT-OSS, and paces subsequent requests from reported rate-limit headers.
Generated-call errors can be corrected within the same eight-turn budget. These changes do not
increase the account's quota; see [the fix and verification report](ISSUE_3_FIX_REPORT.md).

To collect the issue #22 matched comparison on one model (Linux/WSL), with a dedicated
FalkorDB on port 6382 and `GEMINI_API_KEY` configured:

```bash
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 \
  .venv/bin/python evals/run_comparison.py --runs 3 --model gemini:gemini-3.1-flash-lite \
  --db-port 6382 --out artifacts/issue-22/NEW-BATCH
```

This collects three rotated arms and preserves failed/unrun slots. Export, verify and rescore the
portable bundle using [evals/README.md](../evals/README.md). The [committed primary result](../evals/evidence/issue-22/live-5a7160f-gemini31lite-05/comparison.md)
is a tie in readability evidence; it does not establish full request fit. Quota and model availability
can change; never combine providers or models within an acceptance batch.

## 7. Console

```sh
.venv/bin/python scripts/serve.py
```

Then open <http://127.0.0.1:8000>. The workspace opens with the actual fixture fleet and retained
data summary. The summary title comes from the selected store; expand Inspect listed records
to see the inventory. A new live request starts blank. Enter your request, review cited release
changes, and confirm the fleet to execute checks.
The review shows the startup-vs-reader contrast, actual failure, evidence path, matrix and next
eligible action. Select a record or matrix cell to inspect its receipt, or open Cited sources to
inspect the proposal's evidence. Demo setup holds live/replay selection, the recording and the
retained-data scenario. Scope confirmation and simulation approval require explicit clicks,
without name fields; the API records a local UI audit-origin label.

The prominent `Synthetic fixture` and `Replay · not live` labels identify the browser's demo
context. Replay pickers show the recorded model, live/non-live origin, time and recording ID;
replaying a live-origin recording is still not a live model call. Approval and local simulation are available
only for `BOUNDED_PASS`, which carries its byte/shape limit. Approval is refused if relevant evidence
bytes changed since verification. Restart any already-running server after the workspace refactor
to load the static asset mount and snapshot endpoint. See [UI.md](UI.md) for the module layout
and browser verification instructions.

## 8. Same bytes, same hashes

```sh
.venv/bin/python -c "from pathlib import Path; import hashlib; [print(p.parent.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(Path('fixtures/shop/snapshots').glob('*/manifest.json'))]"
```

Expected (these are the values the committed fixture produces):

```text
snap-001 416e1df3791f754c6d1224ca7a458b262c3c27bfec0bbf308dadbb477d74091c
snap-002-partial 734cae65082cdc78ada9251609e6a4e25c2fe5090c42996a11c6ff1640a3668c
snap-003-orphan 7e2947e49f9131854fdf59cfdc0930aac72d38a6092720606a051920a3c1d1ac
```

`.gitattributes` marks `fixtures/** -text` and `*.bin binary`, so a checkout never rewrites fixture
bytes and these hashes are stable across machines. Release artifact hashes are derived the same way
from the exact file bytes (see CONTRACTS.md "Artifact hash inputs").

## Limits and labels (stated up front)

- **Synthetic fixture only.** No production data, no deployment; the "simulate" action is a local,
  idempotent SQLite record that performs nothing.
- **Replay is labeled.** `replay:<file>` with `live=False` means a saved transcript was re-run; it is
  not a live model result.
- **`BOUNDED_PASS` = byte/shape readability** of modeled records only.
- **UI screenshots are untracked** (`artifacts/screens/` is git-ignored), so visuals must be
  regenerated locally.
- Live-model results are quota-limited and reported per run in STATUS.md, never generalized.
