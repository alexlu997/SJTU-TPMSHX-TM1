"""Retained project and profiling entry points use the current package layout."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = sorted([
    *ROOT.glob('projects/703-sCO2-D76/*.py'),
    *ROOT.glob('projects/704-Aircooler-10kW/*.py'),
    *ROOT.glob('benchmarks/profiling/*.py'),
])


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_retained_entry_imports_from_repository_root(script):
    # Match direct project-script launch, including same-directory siblings.
    # Profilers are launched as modules from the repository root.
    code = 'import runpy, sys; from pathlib import Path; p = Path(sys.argv[1]); '
    if 'projects' in script.relative_to(ROOT).parts:
        code += 'sys.path[0] = str(p.parent); '
    code += "runpy.run_path(str(p), run_name='__tm1_import_smoke__')"
    # Do not let conftest's child-process bootstrap hide a broken script entry.
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, '-c', code, str(script)], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_aircooler_html_identifies_its_companion_workbook(tmp_path):
    # Empty result rows isolate the export path from numerical predictions.
    code = """
import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1], run_name='__tm1_report_smoke__')
for arrangement, filename in [('cross', 'quick_design_result.xlsx'),
                              ('counter', 'quick_design_result_counter.xlsx')]:
    workbook = Path(sys.argv[2]) / filename
    report = Path(sys.argv[2]) / f'{arrangement}.html'
    module['write_html_sweep'](report, workbook, [], module['AREA2'], arr=arrangement)
    assert f'<code>{workbook}</code>' in report.read_text(encoding='utf-8')
"""
    script = ROOT / 'projects/704-Aircooler-10kW/predict_aircooler_10kw.py'
    result = subprocess.run([sys.executable, '-c', code, str(script), str(tmp_path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
