"""Cold-start air screening closes native mass/enthalpy boundary transport."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.preprocess.api import prepare_screening_2d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.continuous_field import uniform_field
from sjtu_tpmshx.tests.test_evaluator_frozen_values import _FAST_CFG, _X_NONUNIF


@pytest.mark.slow
@pytest.mark.parametrize('loops', [1, 3])
@pytest.mark.parametrize('uniform', [False, True])
def test_screening_cold_model_h_native_boundary(tmp_path, monkeypatch, loops, uniform):
    monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')
    fc = uniform_field(6., .4, 'Diamond', 17., L_domain=.10, H_domain=.05) if uniform else None
    case = prepare_screening_2d(None if uniform else _X_NONUNIF.copy(),
                               {**_FAST_CFG, 'n_rho_loops': loops, 'max_iter_energy': 2000},
                               fc=fc,
                               case_id=f'model-h-{loops}')
    with pytest.raises(ValueError, match='energy formulation'):
        run_case(replace(case, metadata={**case.metadata, 'energy_formulation': 'temperature'}))
    result = run_case(case)
    path = tmp_path / 'result.h5'
    save_result(result, path)
    result = load_result(path)
    assert result.run_status['execution'] == 'completed'
    assert result.metadata['model_configuration']['energy_formulation'] == 'conservative_air_model_h'
    transport = result.metadata['thermal_transport']
    assert tuple(transport['model_fluids']) == ('air', 'air')
    dx, dy = np.asarray(result.grid['dx']), np.asarray(result.grid['dy'])
    area = dx[:, None] * dy[None, :]
    a, b, c, origin, reference = model_h_coefficients('air')

    def h(T):
        x, r = T - origin, reference - origin
        return a*(x-r) + .5*b*(x*x-r*r) + c/3*(x*x*x-r*r*r)

    for side, name, direction in (('A', 'Ta', 0), ('B', 'Tb', 3)):
        T = result.fields[name]
        mx, my = transport['mass_flux_' + side]
        faces = (-mx[0], mx[-1], -my[:, 0], my[:, -1])
        boundary_T = [T[0], T[-1], T[:, 0], T[:, -1]]
        Tin = result.metadata['parameters']['T_in' + side]
        boundary_T[direction] = np.full_like(boundary_T[direction], Tin)
        outward_h = sum(float(np.sum(m*h(t))) for m, t in zip(faces, boundary_T))
        inlet = (0, slice(None)) if side == 'A' else (slice(None), -1)
        cross, width = (dy, dx[0]) if side == 'A' else (dx, dy[-1])
        conduction = float(np.sum(2*result.fields['K_ff'+side+'_arr'][inlet]
                                   *cross/width*(T[inlet]-Tin)))
        exchange = float(np.sum(result.fields['h_v'+side+'_arr']*(result.fields['Ts']-T)*area))
        assert abs(outward_h + conduction - exchange)/max(abs(exchange), 1.) < 1e-4
