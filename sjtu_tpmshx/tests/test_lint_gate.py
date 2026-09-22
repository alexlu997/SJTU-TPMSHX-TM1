"""P2.1 standing gate: ruff lint (config in pyproject [tool.ruff]) is clean.

Rule set is F + E9, including unused-local rule F841; the
config file documents why `ruff format` is NOT part of the gate (line-number
churn vs atlas/file:line citations and source-marker tests). A new finding
either gets fixed or gets a per-file-ignore/noqa WITH rationale — never a
silent rule removal.
"""
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_ruff_lint_clean():
    r = subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', 'sjtu_tpmshx'],
        capture_output=True, text=True, timeout=300, cwd=str(_REPO))
    assert r.returncode == 0, "ruff findings:\n" + r.stdout[-2000:]
