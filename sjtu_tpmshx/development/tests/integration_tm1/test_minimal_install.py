"""Actual numerical archives consumed in the isolated minimal CI environment."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pytest


def test_real_archives_in_minimal_environment():
    directory = os.environ.get('TM1_REAL_HANDOFF_DIR')
    if directory is None:
        pytest.skip('requires real producer files and the minimal environment')
    _check_archives(directory)


def _check_archives(directory):
    from sjtu_tpmshx.development.runs.tools.check_three_module_environment import main
    from sjtu_tpmshx.shared.io.result_io import load_result
    from sjtu_tpmshx.shared.io.metrics_io import load_metrics
    from sjtu_tpmshx.postprocess.api import evaluate
    main()
    archives = list(Path(directory).glob('**/handoff/results.h5'))
    assert len(archives) == 2, 'require both real 2D and 3D producer archives'
    units = set()
    for archive in archives:
        result = load_result(archive)
        assert result.run_status['converged'] is True
        actual = evaluate(result).metrics
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
sys.path.insert(0, sys.argv[1])
import sjtu_tpmshx
assert Path(sjtu_tpmshx.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
runpy.run_path(sys.argv[2])['_check_archives'](sys.argv[3])
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
