# Fast-tier suite runner — DEV INNER LOOP ONLY, NOT THE VERIFICATION GATE.
#
# P3.1 (2026-07-20): the duration census (retained in Git history) found
# 21 `heavy` tests (call >= 30s): 1.7% of tests carrying
# 89% of call-compute; manifest: sjtu_tpmshx/tests/_fast_tier_manifest.txt,
# applied by tests/conftest.py at collection). Environment checks are shared
# with run_tests_server.ps1. Measured wall ~1 min vs ~19 min full.
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
& (Join-Path $PSScriptRoot 'run_tests_server.ps1') -LockFile $LockFile -Fast
exit $LASTEXITCODE
