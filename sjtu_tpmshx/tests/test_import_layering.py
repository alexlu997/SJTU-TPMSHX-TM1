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

import pytest

from sjtu_tpmshx.runs.tools import audit_import_graph as audit

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / 'sjtu_tpmshx' / 'runs' / 'tools' / 'audit_import_graph.py'


def test_no_unsanctioned_layering_violations():
    r = subprocess.run(
        [sys.executable, str(_TOOL), '--fail-on-violations'],
        capture_output=True, text=True, timeout=120, cwd=str(_REPO))
    assert r.returncode == 0, (
        "unsanctioned import-layering violations:\n" + r.stdout[-2000:])


@pytest.mark.parametrize('filename,source,edge,exit_code', [
    ('domain/probe.py', 'import sjtu_tpmshx.ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx.ui import theme as appearance', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'from .. import ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'def load():\n    from .. import ui', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx.ui import *', 'domain -> ui', 1),
    ('domain/probe.py', 'from ui.theme import get_theme', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import tests as support', 'domain -> tests', 1),
    ('domain/probe.py', 'import io\nfrom io import StringIO', None, 0),
    ('domain/probe.py', 'from scipy import io', None, 0),
    ('models/probe.py', 'from sjtu_tpmshx.domain import case_data', 'models -> domain', 0),
    ('models/probe.py', 'from sjtu_tpmshx import df_surrogate', 'models -> df_surrogate', 0),
    ('models/deep/probe.py', 'from ... import ui', 'models -> ui', 1),
    ('models/__init__.py', 'from .. import ui', 'models -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import io', 'domain -> io', 1),
])
def test_import_spelling_preserves_layer_policy(tmp_path, monkeypatch, capsys,
                                               filename, source, edge, exit_code):
    package = tmp_path / 'sjtu_tpmshx'
    for unit in ('domain', 'models', 'ui', 'tests', 'io', 'df_surrogate'):
        (package / unit).mkdir(parents=True)
    path = package / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
    monkeypatch.setattr(audit, 'PKG', package)
    monkeypatch.setattr(audit, 'REPO', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['audit_import_graph', '--fail-on-violations'])

    assert audit.main() == exit_code
    output = ' '.join(capsys.readouterr().out.split())
    if edge is None:
        assert '0 edges' in output
    else:
        assert edge in output
