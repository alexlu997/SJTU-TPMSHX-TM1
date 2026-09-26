# Full-suite runner for the 128-core EPYC server (E:\LWH).
#
# Strategy (v2, 2026-07-13): single phase, `-n 64 --dist worksteal`.
#   * README.md recommends `--dist loadscope`, but that pins whole modules
#     to one worker. The duration outliers cluster in a few modules
#     (test_conservation_3d_energy: 1291s+1103s serialized = 40-min tail;
#     test_partial_bc_ghost_b: 1576s; test_asym_porosity_3d: 1607s), so
#     loadscope's wall-clock floor is the biggest module sum (~40 min).
#     worksteal distributes per-test and rebalances stragglers → floor is
#     the slowest single TEST (~21.5 min on this 2.25 GHz Zen 3).
#   * loadscope's purpose (per README.md) is fixture EFFICIENCY — keeping
#     module-scoped surrogate/MMS fixtures on one worker. Under worksteal
#     they rebuild on several workers: redundant compute, not a correctness
#     issue, and 128 cores absorb it.
#   * A v1 of this script split by the `slow` marker — WRONG: the marker is
#     the CI skip-list, not a duration census. The heaviest tests
#     (conservation_3d_energy, partial_bc_ghost_b, asym_porosity_3d) are
#     unmarked, so the "fast" phase inherited the whole 40-min tail.
#
# The 2026-07 measurements above describe the historical suite. Current
# enthalpy-transport tests explicitly exercise two Numba threads, so each
# worker must allow two. Keep BLAS/OMP at one to avoid nested oversubscription.
#
# The venv MUST be built from C:\Python312 (python.org CPython), never
# Anaconda — PySide6's abi3 forwarder crashes (0xc0000139) otherwise.

param(
    [ValidateSet('requirements-lock.txt', 'requirements-lock-server.txt')]
    [string]$LockFile = 'requirements-lock.txt',
    [switch]$Fast
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
$env:NUMBA_NUM_THREADS = "2"
# Headless server — Qt tests need the offscreen platform plugin.
$env:QT_QPA_PLATFORM = "offscreen"
$env:MPLCONFIGDIR = Join-Path $repo ".cache\matplotlib"
$env:XDG_CACHE_HOME = Join-Path $repo ".cache\xdg"
New-Item -ItemType Directory -Force $env:MPLCONFIGDIR, $env:XDG_CACHE_HOME | Out-Null

Set-Location $repo

& $py -m sjtu_tpmshx.runs.tools.check_locked_environment $LockFile
if ($LASTEXITCODE -ne 0) { throw "Shared environment differs from $LockFile" }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw "Shared environment failed pip check" }

if ($Fast) {
    Write-Host "=== FAST TIER (-m 'not heavy') — dev feedback, NOT the gate ===" -ForegroundColor Yellow
    $pytestArgs = @('-n', '32', '--dist', 'worksteal', '-m', 'not heavy')
    $successMessage = "FAST TIER green — run scripts/run_tests_server.ps1 before claiming done."
    $failurePrefix = 'FAST TIER FAILED'
} else {
    Write-Host "=== Full suite (-n 64 worksteal) ===" -ForegroundColor Cyan
    $pytestArgs = @('-n', '64', '--dist', 'worksteal', '--durations=15')
    $successMessage = 'READY — suite green.'
    $failurePrefix = 'FAILED'
}
& $py -u -m pytest sjtu_tpmshx/tests/ -q @pytestArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host $successMessage -ForegroundColor Green
} else {
    Write-Host "$failurePrefix — pytest exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
