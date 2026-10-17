# Evaluation assets

Keep independent expectations and controls here, outside runtime application inputs. Do not import answer files into src/rw/ or tune holdouts to accommodate a failing implementation.

Product evaluations will cover grounded fleet/clarification, exact obligations and missingness, probe/receipt applicability, disposition and stale/idempotent approval. Give graph and appropriate selector/SQL controls the same relevant facts and probe access; no control is required to fail.

Run the same-model live comparison (Linux/WSL):

```bash
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 \
  .venv/bin/python evals/run_comparison.py --runs 3 --model groq:qwen/qwen3.8-27b
```

It runs the actual live control test once per pair, preserves pytest/JUnit evidence, checks the product on disposable FalkorDB graphs, and saves the existing scorer's output. It stops at a failed pair and preserves that outcome. A passing live test checks usable execution, not perfect interpretation or complete probe coverage. See [the change and verification report](../docs/ISSUE_3_FIX_REPORT.md).

model-checks/ contains the existing small DeepSeek Zen smoke-check records and their limits. These are not product graph/query tests, model rankings or clean throughput measurements. See [model-checks/README.md](model-checks/README.md).
