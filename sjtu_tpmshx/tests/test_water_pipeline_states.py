"""Water checks follow actual pressure frames and survive cap/fallback paths."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python.two_d import coupling as solve_2d
from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
from sjtu_tpmshx.models.fluid_props import WaterStateError


@pytest.mark.parametrize('direction', range(4))
def test_2d_pressure_preserves_partial_inlet_anchor_and_direction(direction):
    p = np.arange(12.).reshape(3, 4) * 100.
    solver = SimpleNamespace(P=p, inlet_frac=np.array([0., .5, 1.]))
    expected = p.T if direction < 2 else p
    if direction % 2:
        expected = np.flip(expected, axis=0 if direction == 1 else 1)
    expected = 2e5 + expected - (p[1, 0] * .5 + p[2, 0]) / 1.5
    np.testing.assert_array_equal(
        solve_2d._simple_pressure_abs_2d(solver, direction, 2e5), expected)


@pytest.mark.parametrize('axis,perm', [(0, (1, 0, 2)), (1, (0, 1, 2)),
                                      (2, (0, 2, 1))])
@pytest.mark.parametrize('reverse', [False, True])
def test_3d_pressure_keeps_caller_offset_and_pairing(axis, perm, reverse):
    solver = SimpleNamespace(P=np.arange(24.).reshape(2, 3, 4))
    amap = dict(solver_to_real_perm=perm, is_reverse=reverse, stream_real_axis=axis)
    expected = (2e5 + solver.P).transpose(perm)
    if reverse:
        expected = np.flip(expected, axis=axis)
    np.testing.assert_array_equal(stages._pressure_real_3d(solver, amap, 2e5), expected)
    np.testing.assert_array_equal(stages._pressure_real_3d(solver, amap, 1e5), expected-1e5)


def _water_cfg(dimension):
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg
    cfg = _small_air_cfg()
    cfg.solver.Nx = cfg.solver.Ny = 6
    cfg.solver.Nz = 4 if dimension == 3 else 1
    if dimension == 2:
        cfg.geometry.Lz_m = None
    cfg.solver.max_outer_ltne = 2
    cfg.solver.max_iter_simple = 100
    for fluid, t in ((cfg.fluid_A, 380.), (cfg.fluid_B, 300.)):
        fluid.type = 'water'
        fluid.u_mps = .02
        fluid.T_in_K = t
        fluid.P_in_Pa = 2e5
    return cfg


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('side,bad', [('A', np.nan), ('B', 420.)])
def test_invalid_raw_water_return_raises_before_nan_patch_or_refresh(monkeypatch, dimension, side, bad):
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D

    def invalid(*args, **kwargs):
        shape = args[2:4] if dimension == 2 else args[3:6]
        fields = [np.full(shape, t) for t in (380., 300., 340.)]
        fields[0 if side == 'A' else 1].flat[-1] = bad
        return (*fields, dict(converged=False, iterations=1, residual=1.))

    monkeypatch.setattr(solve_2d if dimension == 2 else stages,
                        'solve_full_domain' if dimension == 2 else 'solve_full_domain_3d', invalid)
    with pytest.raises(WaterStateError, match='return ' + side):
        (Pipeline2D if dimension == 2 else Pipeline3D)(_water_cfg(dimension)).run()


@pytest.mark.parametrize('offset', [-1e9, 190000.])
def test_3d_temperature_path_uses_property_then_final_report_pressure(monkeypatch, offset):
    import inspect
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    observed = {}
    original = stages.fluid_props.check_water_state

    class CheckedReport(Exception):
        pass

    def check(fluid, t, p, *, where):
        if where in ('3D temperature return B', '3D property refresh B'):
            assert np.ndim(p) == 0 and p == 2e5
        if where == '3D final report state B':
            np.testing.assert_array_equal(p, observed['report'])
            assert not np.array_equal(p, observed['kernel'])
            original(fluid, t, p, where=where)
            raise CheckedReport
        original(fluid, t, p, where=where)

    def cap(*, step, post, **kwargs):
        _, carry = step(0)
        post(0, carry)
        state = inspect.getclosurevars(step).nonlocals
        solver, amap = state['sB'], state['axis_map_B']
        solver.P_ref_abs = offset
        observed['report'] = stages._pressure_real_3d(solver, amap, offset)
        observed['kernel'] = stages._pressure_real_3d(
            solver, amap, 2e5 - stages.SIMPLESolver3D.extract_dP_face_extrap(solver))
        return 0, False

    monkeypatch.setattr(stages.fluid_props, 'check_water_state', check)
    monkeypatch.setattr(stages, 'run_outer_coupling', cap)
    with pytest.raises(WaterStateError if offset < 0 else CheckedReport):
        Pipeline3D(_water_cfg(3)).run()


def test_3d_true_h_return_uses_last_kernel_pressure_not_report(monkeypatch):
    import inspect
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    cfg = _water_cfg(3)
    cfg.fluid_A.type = 'sco2'
    cfg.fluid_A.T_in_K = 500.
    cfg.fluid_A.P_in_Pa = 12e6
    cfg.fluid_B.P_in_Pa = 2e6
    observed = {}
    original = stages.fluid_props.check_water_state

    def outer(*, step, **kwargs):
        observed.update(inspect.getclosurevars(step).nonlocals)
        step(0)
        pytest.fail('invalid kernel return was accepted')

    def thermal(*args, **kwargs):
        observed['kernel'] = kwargs['pressure_B_field'].copy()
        # Separate, valid report pressure must not rescue an invalid kernel state.
        observed['sB'].P_ref_abs = 5e6
        shape = args[:3]
        return (np.full(shape, 490.), np.full(shape, 500.), np.full(shape, 495.), {})

    def check(fluid, t, p, *, where):
        if where == '3D enthalpy return B':
            np.testing.assert_array_equal(p, observed['kernel'])
            report = stages._pressure_real_3d(observed['sB'], observed['axis_map_B'], 5e6)
            original(fluid, t, report, where='test valid alternate report')
            assert not np.array_equal(p, report)
        original(fluid, t, p, where=where)

    monkeypatch.setattr(stages, 'run_outer_coupling', outer)
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', thermal)
    monkeypatch.setattr(stages.fluid_props, 'check_water_state', check)
    with pytest.raises(WaterStateError, match='3D enthalpy return B'):
        Pipeline3D(cfg).run()


@pytest.mark.parametrize('failure', ['return', 'duty', 'fallback'])
def test_richardson_water_failure_cannot_fall_back(monkeypatch, failure):
    from sjtu_tpmshx.tests.test_richardson_validity_2d import _arguments
    _, arguments = _arguments(monkeypatch)
    arguments.update(T_inA=380., T_inB=300., P_inA_val=2e5, P_inB_val=2e5)
    from dataclasses import replace
    from sjtu_tpmshx.models.fluid_props import get
    for side, t in (('A', 380.), ('B', 300.)):
        arguments['_p' + side] = replace(get('water'), rho=lambda *a: 1., cp=lambda *a: 1.)
        arguments['T' + side.lower()][:] = t

    def refined(*args, **kwargs):
        shape = args[2:4]
        fields = [np.full(shape, t) for t in (380., 300., 340.)]
        if failure == 'return':
            fields[1].flat[-1] = 420.
        return (*fields, dict(converged=True, iterations=1, residual=0.))

    calls = 0

    def duty(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failure == 'fallback' and calls == 1:
            raise RuntimeError('exercise existing fallback')
        raise WaterStateError('injected duty state')

    def density(*args):
        if failure == 'fallback' and calls:
            raise WaterStateError('injected fallback property state')
        return 1.
    arguments['_pA'] = replace(arguments['_pA'], rho=density)
    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', duty)
    with pytest.raises(WaterStateError):
        solve_2d._compute_Q_richardson(**arguments)
