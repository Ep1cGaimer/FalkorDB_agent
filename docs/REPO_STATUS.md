# Repository integration status (remquirements-v1.md)

Statuses: `PROPOSED`, `IN_PROGRESS` (needs an implementation/experiment reference), `VALIDATED`
(needs reproducible E1–E5 evidence for that requirement), `BLOCKED` (needs the obstacle and next action).
Integration, history correctness, scale and FalkorDB benefit are reported separately; claims are
limited to the measured repositories (psf/requests, pallets/itsdangerous, two synthetic repos),
language (Python only), revisions, sizes and workloads below.

Each requirement was built in two passes: one agent wrote the tests (and held-out questions,
budgets and the E4 threshold) first, a separate agent wrote code to pass them.

## Requirements

| Req | Evidence | Status | Reference |
|---|---|---|---|
| S1 Configurable repository integration | E1 | VALIDATED (Python only) | `src/rw/repo/` (config, git, adapters/python, index); `tests/repo/test_s1_integration.py`; E1: requests (seen) and itsdangerous (unseen) onboarded by JSON config only — `artifacts/repo_onboarding/requests-20261018T054107.json`, `itsdangerous-20261018T053904.json`; unseen repo first onboarded under core freeze `evals/repo_onboarding/core_manifest_after_s5.json`, re-verified under `core_manifest.json`. Config effort: 6–7 fields. Limits: adapter `LIMITS` in each record; Python 2-era files fail to parse (recorded as extraction errors). Cross-language generality not demonstrated. |
| S2 Useful code and history evidence | E2, E4 | BLOCKED (E4) | E2 is strong after round 3 (answer 0.933, recall 1.0, validity 1.0 on new held-out questions; round 1/2 reruns 0.67/0.73); parsed vs inferred provenance kept. Blocked on E4: see below. |
| S3 Correct revision handling | E2 | VALIDATED (Python; measured repos only) | `fix_status`, `is_ancestor`, similarity renames, dotted-name resolution, citation discipline; tests `test_s3_revisions.py`, `test_s23_round2.py`, `test_s23_round3.py` (30/30). E2 round 3 on 30 new held-out questions (written after round-2 results, disjoint) `artifacts/repo_history_eval/20261018T053411Z.json`: answer 0.933, evidence recall 1.0, citation validity 1.0. 4 tasks flagged wrong-revision: these are citations to the *from* revision of change questions, which the question files name only in prose (not `compare_revision`), so the scorer counts them; reported, not re-scored. Known limits: edited fixes are UNCERTAIN by design (S3 uncertainty rule); backport equivalence only for identical patches; Python 2 files not parsed. Earlier rounds retained: round 1 0.52→0.67, round 2 0.50→0.73 on rerun. |
| S4 Large histories, bounded retrieval | E3, E4 | BLOCKED (E4) | `tests/repo/test_s4_scale.py`; E3 `artifacts/repo_scale/20261018T001848Z.json` (requests, 159 tags, 6470 commits, ≈20.2M plaintext tokens vs 128k context budget): initial 167.8 s, update 19.5 s (blobs reused), index 317 MB, peak 197 MB, p95 128 ms; interrupted import recovered, invalidation passed; 6/7 pre-declared budgets met — `failures_max` missed (1 workload query failed). E4 pending. |
| S5 Accessible investigation | E1 | VALIDATED (Python only) | `rw.repo.investigate`, `scripts/repo_index.py`, `scripts/repo_investigate.py`, `/api/repos*`, MCP tool `repo_investigate`; `tests/repo/test_s5_access.py` (parity across CLI, API, MCP function); E1 runs above. The MCP tool listing test is skipped locally (no `mcp` package). |
| S6 Preserve verification boundaries | E5 | VALIDATED | `rw.repo.runtime` (optional adapters; FAIL→BLOCKED, missing/stale→NEEDS_EVIDENCE, BOUNDED_PASS only with current receipts); `tests/repo/test_s6_boundaries.py` (no repo code executed; only allowlisted read-only git spawned; no fixture-harness import); `tests/repo/test_e5_reproducibility.py` over all run records, attempts kept with explained gaps. |

## Evidence summary

| Evidence | State | Record |
|---|---|---|
| E1 Integration and access | done | two real repos (one unseen), configuration only |
| E2 History correctness | measured | 46 held-out questions (4 sets); evidence scored separately from answers |
| E3 Scale and updates | measured | budgets declared first in `evals/repo_budgets.json`; 6/7 met |
| E4 FalkorDB benefit | BLOCKED | Threshold pre-registered in `evals/repo_benefit_threshold.json`. Runs 1–2 stopped by the low-memory reaper (5/132, 23/132). Run 3 (started on request, `artifacts/repo_benefit/attempts/20261018T051852Z-checkpoint.json`) hit Groq's free-tier **daily** cap (200k tokens/day for openai/gpt-oss-120b) at task 4; the full declared run needs ≈600k tokens, so it will end INCONCLUSIVE (>10% infra errors). **Next action (owner decision):** a paid Groq tier or additional quota, or a resumable run over ~3 days, or a new smaller pre-registered declaration (new file; the original stays). No FalkorDB retrieval advantage is claimed. |
| E5 Reproducibility | done | `evals/REPRODUCIBILITY.md`; every record carries command, manifest, coverage, config hash, traces, answers, timings |

Existing fixture results and the documented SQL tie do not establish large-codebase advantage; no
retrieval advantage is claimed until E4 passes its pre-registered threshold.
