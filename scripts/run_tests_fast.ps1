# Fast-tier suite runner — DEV INNER LOOP ONLY, NOT THE VERIFICATION GATE.
#
# P3.1 (2026-07-20): the duration census (retained in Git history) found
# 21 `heavy` tests (call >= 30s): 1.7% of tests carrying
# 89% of call-compute; manifest: sjtu_tpmshx/tests/_fast_tier_manifest.txt,
# applied by tests/conftest.py at collection). Everything else is identical
# to run_tests_server.ps1. Measured wall ~1 min vs ~19 min full.
#
# The full suite (run_tests_server.ps1) retains all collected tests; heavy
# includes conservation, boundaries, asymmetric geometry and design checks.
# CI separately excludes slow/heavy and runs public-module integration.
# This local fast subset alone does not establish full-suite acceptance.
#
# `slow` marker semantics untouched (CI skip-list, hand-curated).

param(
    [ValidateSet('requirements-lock.txt', 'requirements-lock-server.txt')]
    [string]$LockFile = 'requirements-lock.txt'
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$venvPathFile = Join-Path $repo ".venv-path"
if (-not (Test-Path -Path $venvPathFile -PathType Leaf)) {
    throw "Missing .venv-path. Follow README.md to configure the shared venv."
}
$py = [string](Get-Content -Path $venvPathFile -TotalCount 1)
$py = $py.Trim()
if ([string]::IsNullOrWhiteSpace($py) -or
    -not (Test-Path -Path $py -PathType Leaf)) {
    throw "Shared Python interpreter not found: $py"
}

$venvRoot = Split-Path (Split-Path $py -Parent) -Parent
$venvHome = (Select-String -Path (Join-Path $venvRoot "pyvenv.cfg") -Pattern '^home = (.+)$').Matches[0].Groups[1].Value
if ($venvHome -match 'Anaconda') {
    throw "venv is built from Anaconda ($venvHome) — PySide6 will crash (0xc0000139). Rebuild it from C:\Python312\python.exe"
}

$env:PYTHONHASHSEED = "0"
$env:OMP_NUM_THREADS = "1"; $env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"; $env:NUMEXPR_NUM_THREADS = "1"
# Enthalpy-transport tests explicitly exercise two Numba threads.
$env:NUMBA_NUM_THREADS = "2"
$env:QT_QPA_PLATFORM = "offscreen"
$env:MPLCONFIGDIR = Join-Path $repo ".cache\matplotlib"
$env:XDG_CACHE_HOME = Join-Path $repo ".cache\xdg"
New-Item -ItemType Directory -Force $env:MPLCONFIGDIR, $env:XDG_CACHE_HOME | Out-Null

Set-Location $repo

& $py -m sjtu_tpmshx.runs.tools.check_locked_environment $LockFile
if ($LASTEXITCODE -ne 0) { throw "Shared environment differs from $LockFile" }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw "Shared environment failed pip check" }

Write-Host "=== FAST TIER (-m 'not heavy') — dev feedback, NOT the gate ===" -ForegroundColor Yellow
& $py -u -m pytest sjtu_tpmshx/tests/ -q -n 32 --dist worksteal -m "not heavy"

if ($LASTEXITCODE -eq 0) {
    Write-Host "FAST TIER green — run scripts/run_tests_server.ps1 before claiming done." -ForegroundColor Green
} else {
    Write-Host "FAST TIER FAILED — pytest exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
