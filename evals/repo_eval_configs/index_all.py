"""Index the E2/E4 evaluation repositories (configs in this directory) into rw_repo_<name>.
Usage: PYTHONPATH=src .venv/Scripts/python.exe evals/repo_eval_configs/index_all.py [name ...]"""
import json, sys, time
from dataclasses import asdict
from pathlib import Path
from rw.repo.config import load_config
from rw.repo.index import index_repository

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "artifacts" / "repo_eval_index"
OUT.mkdir(parents=True, exist_ok=True)
for name in sys.argv[1:] or ["synthetic-history", "branchy-history", "itsdangerous"]:
    rep = index_repository(load_config(HERE / f"{name}.json"))
    d = asdict(rep) if hasattr(rep, "__dataclass_fields__") else vars(rep)
    t0 = time.perf_counter()
    (OUT / f"{name}-{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps({**d, 'config_file': f'evals/repo_eval_configs/{name}.json'}, indent=1, default=str))
    print(name, json.dumps({k: v for k, v in d.items() if not isinstance(v, (list, dict))}, default=str))
