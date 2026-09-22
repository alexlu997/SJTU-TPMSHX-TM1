"""Current-run verdicts, with synthetic results instead of expensive sweeps."""
from copy import deepcopy
import importlib
import runpy
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import validate_sco2_v1 as v1
from sjtu_tpmshx.validation.cases import mms_3d_air_air as a2
from sjtu_tpmshx.validation.harness import _mms_driver


@pytest.mark.parametrize('damage', [None, 'Q_W', 'dP_A_Pa', 'dP_B_Pa',
                                   'rmsre', 'bias', 'fixed_dp', 'Q_A',
                                   'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
                                   'enthalpy_imbalance_rel'])
@pytest.mark.parametrize('invalid', [np.nan, np.inf])
def test_v1_rejects_nonfinite_gated_metrics(monkeypatch, damage, invalid):
    point = SimpleNamespace(dp_core_Pa=100., Um_m_s=.8, Tref=350., Re=10080.)
    metrics = {topo: dict(rmsre=.01, bias=0., limit=limit)
               for topo, limit in [('Diamond', .2), ('Gyroid', .15)]}
    result = SimpleNamespace(Q_W=100., dP_A_Pa=100., dP_B_Pa=100., converged=True,
                             residuals=dict(Q_A=100., mass_imbalance_rel_A=0.,
                                            mass_imbalance_rel_B=0., enthalpy_imbalance_rel=0.))
    result_3d = deepcopy(result)
    result_3d.Q_W *= .021
    if damage in ('Q_W', 'dP_A_Pa', 'dP_B_Pa'):
        setattr(result, damage, invalid)
    elif damage in ('rmsre', 'bias'):
        metrics['Gyroid'][damage] = invalid
    elif damage in result.residuals:
        result.residuals[damage] = invalid
    monkeypatch.setattr(v1, '_cfd_check', lambda: (metrics, point))
    monkeypatch.setattr(v1, 'FullCore3CellFixedDFV2', lambda *a: None)
    monkeypatch.setattr(v1, '_fixed_dp', lambda *a: invalid if damage == 'fixed_dp' else 100.)
    monkeypatch.setattr(v1, 'Pipeline2D', lambda cfg: SimpleNamespace(run=lambda: result))
    monkeypatch.setattr(v1, 'Pipeline3D', lambda cfg: SimpleNamespace(run=lambda: result_3d))
    assert v1.main() == (0 if damage is None else 1)


def _mms_result(case, *, Nx, **kwargs):
    exact = np.ones((Nx, Nx, Nx))
    result = dict(case=case, converged=True, outer_iters=1, last_chg=1e-12)
    for phase, field in [('A', 'Ta'), ('B', 'Tb'), ('s', 'Ts')]:
        num = exact + 1 / Nx**2
        result.update({f'L2_{phase}': 1 / Nx**2, f'Linf_{phase}': 1 / Nx**2,
                       f'{field}_num': num, f'{field}_exact': exact})
    return result


@pytest.mark.parametrize('damage', [None, 'unconverged', 'nan', 'infinite', 'large_error'])
def test_a2_current_result_controls_exit(monkeypatch, damage):
    def run(case, **kwargs):
        result = _mms_result(case, **kwargs)
        if damage == 'unconverged': result['converged'] = False
        if damage == 'nan': result['L2_A'] = np.nan
        if damage == 'infinite': result['Linf_s'] = np.inf
        if damage == 'large_error': result['L2_B'] = .021
        return result
    monkeypatch.setattr(a2, 'run_mms', run)
    monkeypatch.setattr(sys, 'argv', ['mms', '--case', '3d', '--grid', '16'])
    assert a2.main() == (0 if damage is None else 1)


SWEEPS = [
    ('mms_phase_a3_h_refine', ['--cases', '3d', '--grids', '8,16,30'],
     'mms_phase_a3_h_refine.csv'),
    ('mms_phase_a4_boundary', ['--grids', '8,16,30'], 'mms_phase_a4_boundary.csv'),
    ('mms_phase_b4_order', [], 'mms_phase_b4_raw.csv'),
]


@pytest.mark.parametrize('name,args,raw_name', SWEEPS)
@pytest.mark.parametrize('damage', [None, 'unconverged', 'nan', 'missing'])
def test_sweep_requires_every_grid_converged_and_finite(
        monkeypatch, tmp_path, name, args, raw_name, damage):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')
    def run(case, **kwargs):
        result = _mms_result(case, **kwargs)
        if kwargs['Nx'] == 16:
            if damage == 'unconverged': result['converged'] = False
            if damage == 'nan':
                result['L2_A'] = np.nan
                result['Ta_num'][1, 1, 1] = np.nan
        return result
    monkeypatch.setattr(module, 'run_mms', run)
    if name == 'mms_phase_a4_boundary':
        monkeypatch.setattr(module, '_inlet_face_response_errors',
                            lambda *a: dict(A=0., B=0.))
    if damage == 'missing':
        original = _mms_driver.run_grid_sequence
        def drop_grid(*args, **kwargs):
            return [row for row in original(*args, **kwargs) if row['N'] != 16]
        monkeypatch.setattr(module if hasattr(module, 'run_grid_sequence') else _mms_driver,
                            'run_grid_sequence', drop_grid)
    monkeypatch.setattr(sys, 'argv', [name, *args, '--out-dir', str(tmp_path)])
    assert module.main() == (0 if damage is None else 1)
    raw = pd.read_csv(tmp_path / raw_name, comment='#')
    if damage != 'missing':
        assert 16 in raw['N'].tolist()
        row = raw[raw['N'] == 16].iloc[0]
        assert bool(row['converged']) is (damage != 'unconverged')
        if damage == 'nan':
            assert raw.filter(regex='^L2_').isna().any().any()


@pytest.mark.parametrize('name', ['mms_phase_a3_h_refine', 'mms_phase_b4_order'])
@pytest.mark.parametrize('damage', ['low_order', 'low_r2'])
def test_existing_order_and_fit_quality_gates_apply_to_new_runs(monkeypatch, tmp_path, name, damage):
    module = importlib.import_module(f'sjtu_tpmshx.validation.cases.{name}')
    def run(case, **kwargs):
        result = _mms_result(case, **kwargs)
        n = kwargs['Nx']
        error = .001 if damage == 'low_order' else 1 / n**2 * (1.5 if n == 16 else 1.)
        for phase in ('A', 'B', 's'):
            result[f'L2_{phase}'] = error
        return result
    monkeypatch.setattr(module, 'run_mms', run)
    args = ['--cases', '3d', '--grids', '8,16,30'] if 'a3' in name else []
    monkeypatch.setattr(sys, 'argv', [name, *args, '--out-dir', str(tmp_path)])
    assert module.main() == 1


def test_b4_module_propagates_failed_gate_to_process_exit(monkeypatch, tmp_path):
    def run(case, **kwargs):
        result = _mms_result(case, **kwargs)
        result['converged'] = False
        return result
    monkeypatch.setattr(a2, 'run_mms', run)
    monkeypatch.setattr(sys, 'argv', ['b4', '--out-dir', str(tmp_path)])
    monkeypatch.delitem(sys.modules, 'sjtu_tpmshx.validation.cases.mms_phase_b4_order', raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module('sjtu_tpmshx.validation.cases.mms_phase_b4_order', run_name='__main__')
    assert exc.value.code == 1
