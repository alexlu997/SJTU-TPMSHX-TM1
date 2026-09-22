"""Current A4 checks actual kernel boundary response, not cell-center pinning."""
import inspect
import sys

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import mms_3d_air_air as mms
from sjtu_tpmshx.validation.cases import mms_phase_a4_boundary as a4


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
def test_actual_physical_face_kernel_response_meets_strict_gate(case):
    errors = a4._inlet_face_response_errors(case, 4, .7)
    assert all(np.isfinite(error) and error < 1e-12 for error in errors.values())


@pytest.mark.parametrize('phase', ['A', 'B'])
def test_cell_center_temperature_used_as_face_fails_strict_gate(monkeypatch, phase):
    original = mms._gs_full_chunk_3d_stag
    signature = inspect.signature(original.py_func)
    coords = [(np.arange(4) + .5) * length / 4
              for length in (mms.L_DOM, mms.H_DOM, mms.LZ)]
    xyz = np.meshgrid(*coords, indexing='ij')
    cell_exact = mms._eval_grid(mms._build_mms('3d')[f'T{phase.lower()}_fn'], *xyz)

    def wrong_boundary(*args):
        bound = signature.bind(*args)
        bound.arguments[f'T_in{phase}_arr'] = (
            cell_exact[0, :, :].copy() if phase == 'A'
            else cell_exact[:, 0, :].copy())
        return original(*bound.args, **bound.kwargs)

    monkeypatch.setattr(mms, '_gs_full_chunk_3d_stag', wrong_boundary)
    errors = a4._inlet_face_response_errors('3d', 4, .7)
    assert errors[phase] > 1e-12


@pytest.mark.parametrize('phase,damage', [('A', .01), ('B', .01), ('A', np.nan)])
def test_a4_face_response_failure_controls_exit(monkeypatch, tmp_path, phase, damage):
    def run(case, *, Nx, **kwargs):
        exact = np.ones((Nx, Nx, Nx))
        result = dict(converged=True, outer_iters=1, last_chg=1e-12)
        for field in ('Ta', 'Tb', 'Ts'):
            result[f'{field}_exact'] = exact
            result[f'{field}_num'] = exact + 1 / Nx**2
        return result

    def response(case, grid, alpha_f):
        errors = dict(A=0., B=0.)
        if grid == 16:
            errors[phase] = damage
        return errors

    monkeypatch.setattr(a4, 'run_mms', run)
    monkeypatch.setattr(a4, '_inlet_face_response_errors', response)
    monkeypatch.setattr(sys, 'argv', ['a4', '--grids', '8,16,30', '--out-dir', str(tmp_path)])
    assert a4.main() == 1
    rows = pd.read_csv(tmp_path / 'mms_phase_a4_boundary.csv', comment='#')
    assert rows['N'].tolist() == [8, 16, 30]
    assert rows[f'L2_{phase}_inlet_{phase}'].gt(0).all()
    value = rows.loc[rows.N == 16, f'inlet_face_response_rel_{phase}'].iloc[0]
    assert np.isnan(value) if np.isnan(damage) else value == damage
