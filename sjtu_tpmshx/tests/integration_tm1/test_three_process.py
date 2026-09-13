"""Real isolated prepare / solve / postprocess processes using YAML and HDF5."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest


@pytest.mark.slow
@pytest.mark.parametrize('dimension', [2, 3])
def test_real_three_process_handoff(tmp_path, dimension):
    from sjtu_tpmshx.tests.integration_tm1.test_2d_real import AIR_BASELINE_METRICS
    from sjtu_tpmshx.io.case_io import load_case
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.metrics_io import load_metrics
    upstream = tmp_path / 'upstream'
    downstream = tmp_path / 'handoff'
    upstream.mkdir()
    downstream.mkdir()
    config_path = upstream / 'config.json'
    example = (Path(__file__).resolve().parents[3] / 'examples' / 'three_module'
               / f'air_{dimension}d.json')
    shutil.copyfile(example, config_path)
    clean_env = dict(os.environ)
    from sjtu_tpmshx.domain.run_environment import RUN_OVERRIDES
    for name in RUN_OVERRIDES:
        clean_env.pop(name, None)
    def stage(name, source, target, environment, extra=()):
        launcher = '''
import sys
from sjtu_tpmshx.cli import main
status = main(sys.argv[1:])
stage = sys.argv[1]
for prefix in (('sjtu_tpmshx.solvers', 'numba', 'PySide6') if stage == 'prepare' else
               ('sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'PySide6') if stage == 'solve' else
               ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6')):
    assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules), prefix
raise SystemExit(status)
'''
        run = subprocess.run([sys.executable, '-c', launcher, name,
                              str(source), str(target), *extra], env=environment,
                             text=True, capture_output=True, timeout=600)
        (tmp_path / (name + '.log')).write_text(run.stdout + run.stderr)
        assert run.returncode == 0, run.stdout + run.stderr
    stage('prepare', config_path, upstream / 'case.yaml', clean_env, ('--case-id', f'B{dimension}0-files'))
    shutil.copy(upstream / 'case.yaml', downstream)
    shutil.copy(upstream / 'case.h5', downstream)
    shutil.rmtree(upstream)
    prepared = load_case(downstream / 'case.yaml')
    assert prepared.grid['dimension'] == dimension
    # These receiver overrides would change physical/numerical execution if
    # the frozen prepared Case were reinterpreted in the receiving process.
    receiver = dict(clean_env, TPMSHX_CHI_S='0.99', TPMSHX_SIMPLE_TOL='0.9',
                    TPMSHX_CONV_MODE='legacy', TPMSHX_VAR_RHOCP='0',
                    TPMSHX_ROUGH_MODE='bhatti_shah_1b', TPMSHX_ROUGH_EPS_UM='300')
    result_path = downstream / 'results.h5'
    stage('solve', downstream / 'case.yaml', result_path, receiver)
    (downstream / 'case.yaml').unlink()
    (downstream / 'case.h5').unlink()
    result = load_result(result_path)
    assert result.run_status['converged'] is True
    stage('postprocess', result_path, downstream / 'metrics.json', receiver)
    metrics = load_metrics(downstream / 'metrics.json').metrics
    expected = (AIR_BASELINE_METRICS if dimension == 2 else
                [338.48590825124325, 1945.2469619113485, 3044.9340885522665,
                 359.19558834036184, 344.9435887813375])
    names = ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')
    for name, value in zip(names, expected):
        assert metrics[name].status == 'available', metrics[name].reason
        np.testing.assert_allclose(metrics[name].value, value, rtol=1e-10, atol=1e-10)
    assert metrics['Q'].spec.unit == ('W/m' if dimension == 2 else 'W')
