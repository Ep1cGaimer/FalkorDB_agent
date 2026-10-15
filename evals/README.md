# Evaluation assets

Keep independent expectations and controls here, outside runtime application inputs. Do not import answer files into src/rw/ or tune holdouts to accommodate a failing implementation.

Product evaluations will cover grounded fleet/clarification, exact obligations and missingness, probe/receipt applicability, disposition and stale/idempotent approval. Give graph and appropriate selector/SQL controls the same relevant facts and probe access; no control is required to fail.

model-checks/ contains the existing small DeepSeek Zen smoke-check records and their limits. These are not product graph/query tests, model rankings or clean throughput measurements. See [model-checks/README.md](model-checks/README.md).
