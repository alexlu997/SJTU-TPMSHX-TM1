"""Each fluid conducts through its own void fraction, on both thermal grids."""
import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ZoneInputConfig
from sjtu_tpmshx.models.fluid_props import get
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d import coupling
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.tests.solver_tm1.test_prepared_continuous_2d import _config as spline_config
from sjtu_tpmshx.tests.solver_tm1.test_prepared_zoned_thermal_2d import _config as zoned_config
from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments


@pytest.mark.parametrize('kind', ['uniform', 'x', 'y', 'grid', 'sigmoid', 'continuous'])
def test_prepared_effective_conductivity_has_one_stream_volume(kind, monkeypatch, tmp_path):
    cfg = spline_config() if kind == 'continuous' else zoned_config(
        'grid' if kind == 'sigmoid' else 'y' if kind == 'uniform' else kind)
    if kind == 'uniform':
        cfg.zones = ZoneInputConfig()
    elif kind == 'sigmoid':
        from sjtu_tpmshx.models import sigmoid_field
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=2, n_t=2, N=16, cache_dir=tmp_path)
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *a, **k: lut)
        cfg.zones.pareto_x_decision = np.tile([7., .4], 18).tolist()
    case = prepare_case(cfg, case_id='single-stream-' + kind)
    for side in ('A', 'B'):
        fluid = getattr(cfg, 'fluid_' + side)
        conductivity = float(get(fluid.type).k(fluid.T_in_K, fluid.P_in_Pa))
        if kind == 'uniform':
            props = case.parameters['static_properties'][side]
            effective, porosity = props['K_ff'], props['epsilon']
        else:
            effective = case.design_fields['K_ff' + side + '_arr']
            porosity = case.design_fields['eps_arr']
        np.testing.assert_allclose(effective, .5 * porosity * conductivity, rtol=1e-13)


@pytest.mark.parametrize('delta', [0., .6])
def test_main_thermal_call_uses_actual_side_porosity(monkeypatch, delta):
    cfg = zoned_config()
    cfg.zones = ZoneInputConfig()
    cfg.geometry.delta_levelset = delta
    case = prepare_case(cfg, case_id='split-conductivity')
    inputs, grid = build_execution_inputs(case)
    monkeypatch.setattr(SIMPLESolver, 'solve', lambda *a, **k: (True, 1))
    class ReachedThermal(Exception):
        pass
    captured = {}
    def capture(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        raise ReachedThermal
    monkeypatch.setattr(coupling, 'solve_full_domain', capture)
    with pytest.raises(ReachedThermal):
        coupling._run_solvers(inputs, build_runtime(inputs, grid))
    args, kwargs = captured['args'], captured['kwargs']
    split = case.parameters['thermal_geometry']['split_A']
    for side, index, fraction in (('A', 6, split), ('B', 7, 1. - split)):
        fluid = getattr(cfg, 'fluid_' + side)
        intrinsic = float(get(fluid.type).k(fluid.T_in_K, fluid.P_in_Pa))
        eps_side = args[13] * fraction
        np.testing.assert_allclose(args[index], eps_side * intrinsic, rtol=1e-13)
        if delta:
            np.testing.assert_allclose(kwargs['eps_' + side], eps_side, rtol=1e-13)


@pytest.mark.parametrize('split', [.5, .3])
def test_refined_thermal_call_preserves_single_stream_definition(monkeypatch, split):
    _, arguments = _arguments(monkeypatch, full=True)
    eps, ka, kb = .7, .03, .04
    arguments.update(eps=eps, split_A=split,
                     coeffs=dict(K_ffA=eps * ka / 2., K_ffB=eps * kb / 2., K_ss=1.))
    class ReachedThermal(Exception):
        pass
    def capture(*args, **kwargs):
        assert args[6] == pytest.approx(eps * split * ka)
        assert args[7] == pytest.approx(eps * (1. - split) * kb)
        raise ReachedThermal
    monkeypatch.setattr(coupling, 'solve_full_domain', capture)
    with pytest.raises(ReachedThermal):
        coupling._compute_Q_richardson(**arguments)
