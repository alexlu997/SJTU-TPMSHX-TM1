"""P1.9 standing gate: the package import graph carries ZERO unsanctioned
layering violations.

The layer model, the sanctioned-edge list (with adjudication rationale) and
the checker all live in runs/tools/audit_import_graph.py; the architecture
historical sanctions are indexed in docs/history/retired-tools.md.
A new upward import either gets fixed or gets a conscious SANCTIONED entry —
never silently merged.
"""
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / 'sjtu_tpmshx' / 'runs' / 'tools' / 'audit_import_graph.py'


def test_no_unsanctioned_layering_violations():
    r = subprocess.run(
        [sys.executable, str(_TOOL), '--fail-on-violations'],
        capture_output=True, text=True, timeout=120, cwd=str(_REPO))
    assert r.returncode == 0, (
        "unsanctioned import-layering violations:\n" + r.stdout[-2000:])
