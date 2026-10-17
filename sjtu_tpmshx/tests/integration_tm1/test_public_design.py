"""Native Quick Design handoff; C++ references reproduced from v0.1.0."""
from dataclasses import asdict
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.tests.design.test_forward import _case

EXPECTED = {
    'cross-const': [411.6415792728253, 360.13906860416233, 83930.4700621987, 83930.79245130344,
        0.03313918988878337, 0.016005700922110556, 11169.737378348786, 1884.9700138039068],
    'cross-mean': [411.2885930236618, 359.5642649341854, 82728.78176594643, 82728.87797738171,
        0.03313918988878337, 0.016005700922110556, 12929.883184186996, 2590.608151793145],
    'counter-const': [414.9959694660356, 359.65236643943683, 82912.5838291164, 82913.09822486242,
        0.03313918988878337, 0.0036560128812301263, 11169.737378348786, 1122.0059605975634],
    'counter-mean': [412.7343618851766, 359.3660369862176, 82314.04969598474, 82314.38333818095,
        0.03313918988878337, 0.0036560128812301263, 12903.64861676546, 1536.6823361211882],
}


@pytest.mark.slow
@pytest.mark.parametrize('arrangement,model', [(a, m) for a in ('cross', 'counter') for m in ('const', 'mean')])
def test_real_quick_design_three_process(tmp_path, arrangement, model):
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.metrics_io import load_metrics
    inputs = tmp_path / 'input.json'
    inputs.write_text(json.dumps(dict(case=asdict(_case()), arrangement=arrangement, model=model)))
    launcher = '''
import json, sys
stage, source, target = sys.argv[1:]
if stage == 'prepare':
    from sjtu_tpmshx.design.cases import DesignCase
    from sjtu_tpmshx.preprocess.api import prepare_quick_design
    from sjtu_tpmshx.io.case_io import save_case
    from dataclasses import replace
    from pathlib import Path
    data = json.loads(Path(source).read_text())
    case = prepare_quick_design(DesignCase(**data['case']), 'Diamond', 7., .5, .084, .05,
                               data['arrangement'], case_id='quick-design', height=.07,
                               prop_model=data['model'])
    save_case(replace(case, config_snapshot={}), target)
    status = 0
else:
    from sjtu_tpmshx.cli import main
    status = main([stage, source, target])
for prefix in (('sjtu_tpmshx.solvers', 'numba', 'PySide6') if stage == 'prepare' else
               ('sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'PySide6') if stage == 'solve' else
               ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6')):
    assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules), prefix
raise SystemExit(status)
'''
    env = dict(os.environ, TPMSHX_DF_METHOD='cfd_full_core_3cell_fixed_v2',
               TPMSHX_DF_OVERRIDES='1', TPMSHX_DF_RESIDUAL_CORR='0')
    key = arrangement + '-' + model
    evidence = Path('.cache/tm1-quick-design') / key
    evidence.mkdir(parents=True, exist_ok=True)
    paths = [inputs, tmp_path / 'case.yaml', tmp_path / 'results.h5', tmp_path / 'metrics.json']
    exits = []
    for index, stage in enumerate(('prepare', 'solve', 'postprocess')):
        if stage != 'prepare':
            env.update(TPMSHX_DF_METHOD='rbf', TPMSHX_DF_OVERRIDES='0', TPMSHX_DF_RESIDUAL_CORR='1')
        run = subprocess.run([sys.executable, '-c', launcher, stage, str(paths[index]), str(paths[index + 1])],
                             env=env, capture_output=True, text=True, timeout=240)
        (evidence / (stage + '.log')).write_text(run.stdout + run.stderr)
        assert run.returncode in ((0, 2) if stage == 'solve' else (0,)), run.stdout + run.stderr
        exits.append(run.returncode)
        paths[index].unlink()
        if stage == 'solve':
            (tmp_path / 'case.h5').unlink()
            result = load_result(paths[2])
            shutil.copyfile(paths[2], evidence / 'results.h5')
            assert exits[-1] == (0 if result.run_status['converged'] else 2)
            assert len(result.run_status['passes']) == (2 if model == 'mean' else 1)
            np.savez(evidence / 'fields.npz', **{k: result.fields[k] for k in ('Ta', 'Tb', 'Ts')})
            (evidence / 'run_status.json').write_text(json.dumps(
                {'converged': result.run_status['converged'], 'solve_exit': exits[-1]}))
    metrics = load_metrics(paths[3]).metrics
    names = ('T_out_A', 'T_out_B', 'Q', 'Q_cold', 'dP_A', 'dP_B', 'Re_A', 'Re_B')
    values = []
    for name in names:
        assert metrics[name].status == 'available', metrics[name].reason
        values.append(metrics[name].value)
    values[4] /= _case().P_in_h
    values[5] /= _case().P_in_c
    np.testing.assert_allclose(values, EXPECTED[key], rtol=1e-10, atol=1e-10)
    assert metrics['Q'].spec.unit == metrics['Q_cold'].spec.unit == 'W'
    assert metrics['mass'].status == 'unsupported'
