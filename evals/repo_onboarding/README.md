# E1 onboarding protocol (S1, S5)

Goal: show that real repositories can be onboarded with configuration only — no change to core query or
orchestration code — and that repository/revision selection works through the CLI, API and MCP bridge.

## Inputs

- `configs/<repo>.json` — one `RepoConfig` per repository (`name`, `path` relative to the configuration file,
  bounded `revisions`, `languages`, `include`/`exclude`). Optional `"unseen": true` marks a repository
  not inspected during implementation.
- `core_manifest_file` (optional config metadata; otherwise `core_manifest.json`) — `{"files": {"src/rw/<path>.py": "<sha256>", ...}}`, recorded by the implementer
  **before** onboarding an unseen repository. For unseen repos the test fails if any `src/rw/**/*.py`
  hash differs (or a file is added/removed).

## Procedure

1. Clone each repository under `artifacts/repos/<name>` (plain `git clone`; nothing is executed).
2. Run `RW_REALREPO=1 .venv/Scripts/python.exe -m pytest -q -m realrepo tests/repo/test_e1_onboarding.py`.
   For each config whose path exists the test:
   - indexes the selected revisions and asserts the ImportRun is `COMPLETE`;
   - runs fixed generic investigations through `rw.repo.investigate.investigate`: list symbols at the
     last revision; dependencies of a function/method found in that list; changes between the first and
     last selected revisions; release notes at the last revision;
   - checks every citation is a full sha among the selected revisions and resolves via
     `git -C <path> show <sha>:<path>` with valid line spans;
   - checks findings carry no compatibility disposition;
   - writes `artifacts/repo_onboarding/<repo>-<timestamp>.json` with configuration effort (config fields
     used, config lines), index report, coverage gaps / adapter limitations, per-question finding,
     citation and gap counts, and the unresolved messages.
3. Exercise the access surfaces on the same repos (`tests/repo/test_s5_access.py` covers the mechanics
   on synthetic repos; for the real repos run `scripts/repo_investigate.py --repo <name> --rev <ref>
   --config evals/repo_onboarding/configs/<name>.json "<question>"`, the API `POST
   /api/repos/<name>/investigate` and the MCP tool `repo_investigate` and keep their outputs with the
   report).
4. Record every attempted run, including failures, in the artifacts directory; do not delete results.

## Reporting

Report per repository: configuration effort, languages covered, coverage gaps and adapter limitations,
and whether core files changed. Two repositories (one unseen) are required for E1; one well-supported
language is sufficient initially. Claims are limited to the measured repositories and revisions.

The current Requests and ItsDangerous configurations are development inputs. ItsDangerous's
original unseen trial and manifest remain historical at the audited branch revision; its new
metadata explicitly records invalidation after core repairs. A new unseen trial needs a new
repository and a core freeze captured before source inspection. The test records core hashes
both before and after each import. Passing the existing development imports does not close T1.
