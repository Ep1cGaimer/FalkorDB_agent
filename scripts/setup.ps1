# RollbackWitness setup (Windows / PowerShell).
#
# Creates the project virtual environment with uv (Python 3.12) and installs the dependencies
# declared in pyproject.toml. The uv cache lives inside this checkout (.uv-cache/, git-ignored), so a
# clone never shares or dirties another checkout's environment.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# The Python version defaults to 3.12; override it for a test run with
#
#   $env:RW_PY = "9.9"; powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Next step: docs/QUICKSTART.md (start FalkorDB, then run the non-live suite).

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:UV_CACHE_DIR = Join-Path $RepoRoot ".uv-cache"
$PythonVersion = if ($env:RW_PY) { $env:RW_PY } else { "3.12" }
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

# A native command's non-zero exit does not stop PowerShell, so every step is checked explicitly and
# a failure aborts the script with that code instead of reporting success.
function Invoke-Step([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $What failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "RollbackWitness setup in $RepoRoot (Python $PythonVersion)"

Invoke-Step "uv venv (python $PythonVersion)" { uv venv --python $PythonVersion --allow-existing .venv }
Invoke-Step "install project dependencies" { uv pip install --python $PythonExe -r pyproject.toml }
# pyproject.toml declares runtime dependencies only. The test runner is pinned here so the non-live
# suite in docs/QUICKSTART.md runs in a fresh clone with no extra manual install.
Invoke-Step "install pytest" { uv pip install --python $PythonExe "pytest==9.1.1" }
Invoke-Step "python --version" { & $PythonExe --version }

Write-Host "Done. Next: docs/QUICKSTART.md (docker compose up -d, then the non-live suite)."
