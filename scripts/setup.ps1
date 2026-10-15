# RollbackWitness setup (Windows / PowerShell).
#
# Creates the project virtual environment with uv (Python 3.12) and installs the dependencies
# declared in pyproject.toml. The uv cache lives inside this checkout (.uv-cache/, git-ignored), so a
# clone never shares or dirties another checkout's environment.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Next step: docs/QUICKSTART.md (start FalkorDB, then run the non-live suite).

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:UV_CACHE_DIR = Join-Path $RepoRoot ".uv-cache"

Write-Host "RollbackWitness setup in $RepoRoot"

uv venv --python 3.12 --allow-existing .venv
uv pip install --python (Join-Path $RepoRoot ".venv\Scripts\python.exe") -r pyproject.toml
# pyproject.toml declares runtime dependencies only. The test runner is pinned here so the non-live
# suite in docs/QUICKSTART.md runs in a fresh clone with no extra manual install.
uv pip install --python (Join-Path $RepoRoot ".venv\Scripts\python.exe") "pytest==9.1.1"

& (Join-Path $RepoRoot ".venv\Scripts\python.exe") --version
Write-Host "Done. Next: docs/QUICKSTART.md (docker compose up -d, then the non-live suite)."
