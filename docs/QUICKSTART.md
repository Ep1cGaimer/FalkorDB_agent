# Quickstart — RollbackWitness (synthetic fixture)

Everything here runs against a small **synthetic fixture shop** (`fixtures/shop/`) on a pinned local
FalkorDB container. There is no production data, no deployment and no external service beyond the
optional live model provider. Read this together with [CONTRACTS.md](CONTRACTS.md) (what the code
promises) and [STATUS.md](STATUS.md) (what has actually been observed).

Expected durations are for the reference machine (Windows 11, Docker Desktop, uv 0.11.19).

## 0. Prerequisites

| Tool | Used here | Notes |
|---|---|---|
| Docker + Compose v2 | Docker Desktop | the FalkorDB container |
| uv | 0.11.19 | creates `.venv`, installs dependencies, fetches Python 3.12 |
| Git | any recent | clone the branch |
| Python 3.12 | not required on PATH | uv installs/uses 3.12 for `.venv` |

## 1. Clone the branch

```sh
git clone --branch build/slice-2 https://github.com/Ep1cGaimer/FalkorDB_agent.git rollbackwitness
cd rollbackwitness
```

Until that branch is pushed, clone from a local checkout instead (this is exactly what the
reproducibility check in this task did):

```sh
git clone --branch build/slice-2 C:\path\to\FalkorDB_agent %TEMP%\rw-clone
```

The clone has no `.env` (git-ignored). That only matters for the optional live steps in §6; the whole
non-live suite and the deterministic acceptance proof run without any credential.

## 2. Start FalkorDB

```sh
docker compose up -d
docker compose ps
```

Expected: one container `rw-falkordb`, image
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
`redis==8.1.0` and `pydantic==2.14.1` are pinned in `pyproject.toml`; `fastapi`, `uvicorn` and `httpx`
are not pinned there and resolve to current releases.

## 4. Run the tests

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not live"
```

Expected (needs the container from §2):

```text
229 passed, 3 deselected, 1 warning in 20.31s
```

The 3 deselected tests call the live model provider and need `GROQ_API_KEY` (§6).

Two more checks that need **no model at all**:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_acceptance_oracle.py -q     # 8 passed
.venv\Scripts\python.exe evals\relational_control.py                     # SQL control
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

```powershell
.venv\Scripts\python.exe scripts\investigate.py "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction." --confirm-as alice
```

Replay of a saved transcript (always labeled `REPLAY — not live`):

```powershell
.venv\Scripts\python.exe scripts\investigate.py "Roll cart back to the build it ran before the basket rollout, but keep the receipt correction." --replay artifacts\grounding\<file>.json --confirm-as alice --no-alternative
```

Transcripts are written to `artifacts/grounding/` (git-ignored), so a fresh clone has none: run the
live command once, or point `--replay` at a transcript you saved. `--no-alternative` is needed when
you hold a single transcript — a `BLOCKED` result normally asks the agent for one alternative, which
would need a second transcript.

Without a key in a fresh clone the live command stops immediately with a clear, key-free error:

```text
rw.grounding.GroundingError: all models failed: groq:openai/gpt-oss-120b: GROQ_API_KEY is not set | groq:qwen/qwen3.8-27b: GROQ_API_KEY is not set
```

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

The contrast case (`--replay artifacts\grounding\c329bc7f5ad843a2.json`) keeps cart 1.5 with
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

Create a git-ignored `.env` in the repository root:

```text
GROQ_API_KEY=<your key>
```

Never commit or paste that file. The provider chain comes from `RW_GROUNDING_MODEL`
(comma-separated `provider:model`; a bare name means `gemini:`); the default is
`groq:openai/gpt-oss-120b,groq:qwen/qwen3.8-27b`. `GEMINI_API_KEY` is optional and only used when a
`gemini:` entry is selected.

Free-tier reality (measured 2026-10-15, see [STATUS.md](STATUS.md)): `gpt-oss-120b` allows
200k tokens/day and was exhausted by the slice-2 evaluation runs; `qwen3.8-27b` allows 7000 input /
1000 output tokens per minute and rejects the flat-context control prompt. A live run may therefore
fail fast with a quota refusal — the transcript records the abandoned attempt and the next chain
entry is tried.

## 7. Console

```powershell
.venv\Scripts\python.exe scripts\serve.py
```

Then open <http://127.0.0.1:8000>. The single screen carries the request, the agent's proposal with
anchored quotes, the human scope confirmation, the verdict with the GREEN-vs-FAIL contrast, the
witness chain, the reader×record matrix with receipts, and the action section (approval + local
simulation) rendered only for `BOUNDED_PASS`. Replay mode is labeled `REPLAY — not live`, the
`SYNTHETIC FIXTURE` label is always visible, and `BOUNDED_PASS` always carries its byte/shape caption.
Approval is refused if the evidence bytes changed since verification.

## 8. Same bytes, same hashes

```powershell
.venv\Scripts\python.exe -c "from pathlib import Path; import hashlib; [print(p.parent.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(Path('fixtures/shop/snapshots').glob('*/manifest.json'))]"
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
