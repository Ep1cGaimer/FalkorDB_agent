#!/usr/bin/env sh
# RollbackWitness setup (Linux / macOS).
#
# Creates the project virtual environment with uv (Python 3.12) and installs the dependencies
# declared in pyproject.toml. The uv cache lives inside this checkout (.uv-cache/, git-ignored), so a
# clone never shares or dirties another checkout's environment.
#
#   sh scripts/setup.sh
#
# Next step: docs/QUICKSTART.md (start FalkorDB, then run the non-live suite).

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
UV_CACHE_DIR="$repo_root/.uv-cache"
export UV_CACHE_DIR

echo "RollbackWitness setup in $repo_root"

uv venv --python 3.12 --allow-existing .venv
uv pip install --python "$repo_root/.venv/bin/python" -r pyproject.toml
# pyproject.toml declares runtime dependencies only. The test runner is pinned here so the non-live
# suite in docs/QUICKSTART.md runs in a fresh clone with no extra manual install.
uv pip install --python "$repo_root/.venv/bin/python" "pytest==9.1.1"

"$repo_root/.venv/bin/python" --version
echo "Done. Next: docs/QUICKSTART.md (docker compose up -d, then the non-live suite)."
