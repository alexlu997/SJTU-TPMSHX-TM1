"""Actual numerical archives consumed in the isolated minimal CI environment."""
import gc
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import weakref

import numpy as np
import pytest


def _evaluate_archive(archive, *, require_converged=False):
    from sjtu_tpmshx.shared.io.result_io import load_result
    from sjtu_tpmshx.postprocess.api import evaluate
    enabled = gc.isenabled()
    gc.disable()
    try:
        result = load_result(archive)
        if require_converged:
            assert result.run_status['converged'] is True
        references = [weakref.ref(result), *(weakref.ref(value) for value in result.fields.values())]
        report = evaluate(result)
        del result
        assert all(reference() is None for reference in references)
        return report.metrics
    finally:
        if enabled:
            gc.enable()


def test_real_archives_in_minimal_environment():
    directory = os.environ.get('TM1_REAL_HANDOFF_DIR')
    if directory is None:
        pytest.skip('requires real producer files and the minimal environment')
    _check_archives(directory)


def _check_archives(directory):
    from sjtu_tpmshx.development.runs.tools.check_three_module_environment import main
    from sjtu_tpmshx.shared.io.metrics_io import load_metrics
    main()
    archives = list(Path(directory).glob('**/handoff/results.h5'))
    assert len(archives) == 2, 'require both real 2D and 3D producer archives'
    units = set()
    for archive in archives:
        actual = _evaluate_archive(archive, require_converged=True)
        expected = load_metrics(archive.with_name('metrics.json')).metrics
        assert actual.keys() == expected.keys()
        for name, metric in actual.items():
            baseline = expected[name]
            assert metric.spec == baseline.spec
            assert metric.status == baseline.status
            assert metric.reason == baseline.reason
            if metric.value is None:
                assert baseline.value is None
            else:
                np.testing.assert_allclose(metric.value, baseline.value,
                                           rtol=1e-10, atol=1e-10)
        assert actual['Q'].status == 'available'
        units.add(actual['Q'].spec.unit)
    assert units == {'W/m', 'W'}
    main()  # Verify actual evaluation did not import a numerical backend.


def test_quick_archives_in_minimal_environment():
    directory = os.environ.get('TM1_QUICK_HANDOFF_DIR')
    if directory is None:
        pytest.skip('requires frozen Quick files and the minimal environment')
    _check_quick_archives(directory)


def _check_quick_archives(directory):
    from sjtu_tpmshx.development.runs.tools.check_three_module_environment import main
    from sjtu_tpmshx.shared.io.metrics_io import load_metrics
    main()
    for case in ('cross-const', 'cross-mean', 'counter-const'):
        archive = Path(directory) / f'quick-design-{case}/results.h5'
        actual = _evaluate_archive(archive)
        expected = load_metrics(archive.with_name('metrics.json')).metrics
        assert actual.keys() == expected.keys()
        for name, metric in actual.items():
            baseline = expected[name]
            assert metric.spec == baseline.spec
            assert metric.status == baseline.status and metric.reason == baseline.reason
            assert metric.value == baseline.value
        assert actual['Q'].status == 'available'
    main()


@pytest.mark.parametrize("kind", ["wheel-direct", "wheel-from-sdist"])
def test_installed_wheel_evaluates_real_archives(kind):
    wheels = os.environ.get('TM1_WHEEL_DIR')
    archives = os.environ.get('TM1_REAL_HANDOFF_DIR')
    if wheels is None or archives is None:
        pytest.skip('requires wheels, real producer files and the minimal environment')
    wheel, = (Path(wheels).resolve() / kind).glob('*.whl')
    library = Path(os.environ['TPMSHX_RESULT_LIBRARY']).resolve(strict=True)
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    env['TPMSHX_RESULT_LIBRARY'] = str(library)
    program = """
from pathlib import Path
import runpy
import sys
import os
sys.path.insert(0, sys.argv[1])
import sjtu_tpmshx
assert Path(sjtu_tpmshx.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
checks = runpy.run_path(sys.argv[2])
checks['_check_archives'](sys.argv[3])
if os.environ.get('TM1_QUICK_HANDOFF_DIR'):
    checks['_check_quick_archives'](os.environ['TM1_QUICK_HANDOFF_DIR'])
assert not any(name.split('.')[0] in ('CoolProp', 'PySide6') for name in sys.modules)
print('installed real 2D/3D result evaluation passed')
"""
    with TemporaryDirectory(prefix='tm1-offline-wheel-') as directory:
        target = Path(directory) / 'installed'
        subprocess.run([sys.executable, '-I', '-m', 'pip', 'install', '--no-deps', '--no-index',
                        '--no-compile', '--target', str(target), str(wheel)],
                       cwd=directory, env=env, check=True, capture_output=True, text=True, timeout=120)
        result = subprocess.run([sys.executable, '-I', '-c', program, str(target),
                                 str(Path(__file__).resolve()), str(Path(archives).resolve())],
                                cwd=directory, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
