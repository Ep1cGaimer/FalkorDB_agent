# Evaluation assets

Independent expectations and controls, kept outside runtime application inputs. Do not import answer
files into `src/rw/`, and do not tune a holdout to accommodate a failing implementation.

- `expected/` — the independent oracle: `dispositions.json` (8 hand-derived cases A–H, 34 obligations) and its method write-up.
- `grounding_cases/` — live grounding eval cases: `requests.json` in, `expected.json` (hand-written, documentation only) alongside.
- `run_grounding_cases.py` — runs every request through the real grounding loop on a fresh temporary graph and prints the observed outcomes.
- `relational_control.py` — SQL joins over the same raw facts, deriving the same obligation sets as a fair, un-handicapped control.
- `llm_control.py` — equal-information flat-context control: the same model chain and transports, no graph and no Cypher.
- `score_controls.py` — scores saved product reports and control transcripts against the oracle (fleet match, obligation recall, false passes). A claim counts as oracle-consistent only when its own probe results support it: BOUNDED_PASS needs a PASS on every required reader × record pair, BLOCKED needs an observed FAIL. UNKNOWN probes are reported separately, and an *unsupported* BOUNDED_PASS is counted apart from a *false* one (oracle says not readable).
- `run_comparison.py` — same-model live comparison: runs the live control test once per pair, checks the product on disposable FalkorDB graphs, preserves pytest/JUnit evidence and saves the scorer output; stops at the first failed pair. A passing live test checks usable execution, not perfect interpretation or complete probe coverage. See [the change and verification report](../docs/ISSUE_3_FIX_REPORT.md).

  ```bash
  RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 \
    .venv/bin/python evals/run_comparison.py --runs 3 --model groq:qwen/qwen3.8-27b
  ```
- `reviews/astra-01.md` — independent review of the pipeline, and the source of the F1–F8 tags used in test names.
