"""Screening source comparison across real, independently loaded file stages."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


@pytest.mark.slow
@pytest.mark.parametrize('name', ['2d-uniform', '2d-nonuniform', '3d-uniform', '3d-nonuniform'])
def test_screening_three_process(tmp_path, name):
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.metrics_io import load_metrics
    from sjtu_tpmshx.tests.test_evaluator_frozen_values import (
        _FROZEN_2D_UNIFORM, _FROZEN_2D_NONUNIF,
        _FROZEN_3D_UNIFORM, _FROZEN_3D_NONUNIF,
    )
    reference = dict(zip(
        ('2d-uniform', '2d-nonuniform', '3d-uniform', '3d-nonuniform'),
        (_FROZEN_2D_UNIFORM, _FROZEN_2D_NONUNIF, _FROZEN_3D_UNIFORM, _FROZEN_3D_NONUNIF),
    ))[name]
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'name': name}))
    paths = [source, tmp_path / 'case.yaml', tmp_path / 'results.h5', tmp_path / 'metrics.json']
    launcher = '''
import sys, json
from pathlib import Path
stage, source, target = sys.argv[1:]
if stage == 'prepare':
    from dataclasses import replace
    import numpy as np
    from sjtu_tpmshx.preprocess.api import prepare_screening_2d, prepare_screening_3d
    from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
    from sjtu_tpmshx.models.continuous_field import uniform_field
    from sjtu_tpmshx.io.case_io import save_case
    name = json.loads(Path(source).read_text())['name']
    cfg = dict(max_iter_simple=800, max_iter_energy=1500,
               tol_energy=.5, n_rho_loops=1, t_bounds=(.3, .5))
    x = np.array([5., 6., 7., 8., 5.5, 6.5, 7.5, 6., .4, .45, .5, .55, .42, .48, .52, .46])
    fc = uniform_field(6., .4, 'Diamond', 17., .10, .05) if name == '2d-uniform' else None
    if name.startswith('2d'):
        case = prepare_screening_2d(x, cfg, fc=fc, case_id=name)
    else:
        if name == '3d-uniform':
            x = np.r_[np.full(8, 4.), np.full(8, .6)]
        # Same resolved historical bounds as the frozen reference capture.
        case = prepare_screening_3d(x, dict(DEFAULT_CONFIG, t_bounds=(.3, .5)), case_id=name, Nx=10, Ny=6, Nz=3, Lz=.042,
                                   max_outer=2, max_iter_simple=300,
                                   max_iter_energy=800, tol_energy=.5, roughness_mode='norris_1a',
                                   roughness_eps_um=100., verbose=False)
    save_case(replace(case, config_snapshot={}), target)
    status = 0
else:
    from sjtu_tpmshx.cli import main
    status = main([stage, source, target])
prefixes = (('sjtu_tpmshx.solvers', 'numba', 'PySide6') if stage == 'prepare' else
            ('sjtu_tpmshx.preprocess', 'sjtu_tpmshx.optimization', 'sjtu_tpmshx.pipelines', 'PySide6') if stage == 'solve' else
            ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.optimization', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6'))
for prefix in prefixes:
    assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules), prefix
raise SystemExit(status)
'''
    env = dict(os.environ, TPMSHX_DF_METHOD='cfd_full_core_3cell_fixed_v2', TPMSHX_DF_OVERRIDES='1', TPMSHX_DF_RESIDUAL_CORR='0', TPMSHX_CONV_MODE='f2')
    evidence = Path('.cache/tm1-optimization') / ('handoff-' + name)
    evidence.mkdir(parents=True, exist_ok=True)
    for i, stage in enumerate(('prepare', 'solve', 'postprocess')):
        if i:
            env.update(TPMSHX_DF_METHOD='rbf', TPMSHX_DF_OVERRIDES='0', TPMSHX_DF_RESIDUAL_CORR='1', TPMSHX_CHI_S='1.0', TPMSHX_CONV_MODE='legacy')
        run = subprocess.run([sys.executable, '-c', launcher, stage, str(paths[i]), str(paths[i + 1])],
                             env=env, capture_output=True, text=True, timeout=240)
        (evidence / (stage + '.log')).write_text(run.stdout + run.stderr)
        assert run.returncode == 0, run.stdout + run.stderr
        paths[i].unlink()
        if stage == 'solve':
            (tmp_path / 'case.h5').unlink()
            result = load_result(paths[2])
            assert result.run_status['converged'] is True
            (evidence / 'status.json').write_text(json.dumps(dict(execution=result.run_status['execution'], converged=result.run_status['converged'], native_exit=run.returncode)))
            np.savez(evidence / 'native.npz', **{k: result.fields[k] for k in ('Ta', 'Tb', 'Ts')})
    metrics = load_metrics(paths[3]).metrics
    values = [-metrics['Q'].value, metrics['dP_A'].value + metrics['dP_B'].value, metrics['mass'].value]
    if name.startswith('3d'):
        values[0] /= .042
        values[2] /= .042
    np.testing.assert_allclose(values, reference, rtol=1e-12, atol=0)
    assert metrics['Q'].spec.unit == ('W/m' if name.startswith('2d') else 'W')
    assert metrics['mass'].spec.unit == ('kg/m' if name.startswith('2d') else 'kg')
    assert metrics['T_out_A'].status == 'unsupported'
