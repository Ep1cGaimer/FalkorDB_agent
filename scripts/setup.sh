#!/usr/bin/env sh
# RollbackWitness setup (Linux / macOS, and Git Bash / MSYS on Windows).
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

# Relative on purpose: uv is a native binary, and under Git Bash / MSYS an absolute POSIX path such
# as /c/Users/... is not always translated for it. Relative paths need no translation, and this
# script has already cd'd to the repository root.
UV_CACHE_DIR=.uv-cache
export UV_CACHE_DIR

echo "RollbackWitness setup in $repo_root"

uv venv --python 3.12 --allow-existing .venv

# uv lays the environment out for the host OS, not for the shell running this script: on Windows
# (Git Bash / MSYS / Cygwin) the interpreter is Scripts/python.exe, everywhere else bin/python.
if [ -x ".venv/Scripts/python.exe" ]; then
    venv_python=.venv/Scripts/python.exe
elif [ -x ".venv/bin/python" ]; then
    venv_python=.venv/bin/python
else
    echo "setup: no interpreter found in .venv (looked for Scripts/python.exe and bin/python)" >&2
    exit 1
fi

uv pip install --python "$venv_python" -r pyproject.toml
# pyproject.toml declares runtime dependencies only. The test runner is pinned here so the non-live
# suite in docs/QUICKSTART.md runs in a fresh clone with no extra manual install.
uv pip install --python "$venv_python" "pytest==9.1.1"

"$venv_python" --version
echo "Done. Next: docs/QUICKSTART.md (docker compose up -d, then the non-live suite)."
