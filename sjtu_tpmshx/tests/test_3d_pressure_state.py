"""One physical pressure reference, with thermal/final-flow stage ownership."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models import fluid_props
from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
from sjtu_tpmshx.solvers.backends.python.three_d import runtime
from sjtu_tpmshx.solvers import ltne_enthalpy_3d, ltne_energy_3d
from sjtu_tpmshx.tests.test_3d_model_enthalpy_transport import _pipeline_cfg


@pytest.mark.parametrize('flow_model', ['incompressible', 'ideal_gas'])
def test_reference_uses_open_area_mean_of_physical_inlet(flow_model):
    dx, dy, dz = np.array([1., 3.]), np.array([1., 2., 4.]), np.array([2., 5.])
    centres = np.cumsum(dy) - dy / 2.
    inlet = np.array([[20., 40.], [80., 150.]])
    slope = np.array([[2., 3.], [5., 7.]])
    pressure = inlet[:, None, :] - slope[:, None, :] * centres[None, :, None]
    fractions = np.array([[0., .5], [.2, 1.]])
    solver = SimpleNamespace(fluid_type=flow_model, P=pressure.copy(), dx=dx, dy=dy,
                             dz=dz, inlet_frac=fractions, P_ref_abs=1234.)
    runtime._anchor_incompressible_pressure(solver, 200000.)
    weights = fractions * dx[:, None] * dz[None, :]
    expected = 200000. - np.sum(inlet * weights) / weights.sum()
    assert solver.P_ref_abs == pytest.approx(expected if flow_model == 'incompressible' else 1234.)
    np.testing.assert_array_equal(solver.P, pressure)
    if flow_model == 'incompressible':
        assert np.sum((solver.P_ref_abs + inlet) * weights) / weights.sum() == pytest.approx(200000.)


@pytest.mark.parametrize('pair,mode', [
    (('air', 'sco2'), 'true_h'),
    (('sco2', 'air'), 'true_h'),
    (('air', 'water'), 'model_h'),
    (('water', 'water'), 'legacy_temperature'),
])
@pytest.mark.parametrize('cap', [False, True])
def test_thermal_pressure_tracks_completed_flow_and_is_detached_before_post(monkeypatch, pair, mode, cap):
    def flow(solver, **kwargs):
        solver._test_calls = getattr(solver, '_test_calls', 0) + 1
        centres = np.cumsum(solver.dy) - solver.dy / 2.
        solver.P[:] = (10. * solver._test_calls) * (1. - centres[None, :, None] / solver.dy.sum())
        return True, 0

    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', flow)
    cfg = _pipeline_cfg(pair)
    if pair[0] == 'sco2':
        cfg['P_inA'] = 12e6
    prob = _build_3d_problem(cfg)
    hv = runtime._build_hv_machinery(prob)
    shape = prob.Nx, prob.Ny, prob.Nz
    fields = tuple(np.full(shape, t) for t in (340., 310., 325.))
    snapshots, kernel_pressures, property_pressures = [], [], []
    # The corrected reporting/enthalpy reference must not change the frozen
    # pressure convention of the default incompressible transport properties.
    if 'sco2' in pair:
        side = 'A' if pair[0] == 'sco2' else 'B'
        original_model = getattr(prob, '_m' + side)
        def observe_property(function):
            def call(t, p):
                property_pressures.append(np.asarray(p).copy())
                return function(t, p)
            return call
        setattr(prob, '_m' + side, replace(
            original_model, rho=observe_property(original_model.rho),
            mu=observe_property(original_model.mu)))

    def temperature(*args, **kwargs):
        snapshots.append(tuple((s.P_ref_abs + s.P).copy() for s in (prob.sA, prob.sB)))
        return (*fields, dict(converged=True, iterations=1, residual=0.))

    def enthalpy(*args, **kwargs):
        kernel_pressures.append(tuple(kwargs['pressure_' + side + '_field'].copy() for side in ('A', 'B')))
        return (*fields, dict(converged=True, iterations=1, residual=0., Q_A=1., Q_B=1.))

    def drive(*, step, post, **kwargs):
        step(0)
        post(0, None)
        step(1)
        if cap:
            post(1, None)
        return 1, not cap

    monkeypatch.setattr(runtime, 'solve_full_domain_3d', temperature)
    monkeypatch.setattr(ltne_enthalpy_3d, 'solve_ltne_enthalpy_3d_pipeline', enthalpy)
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))
    monkeypatch.setattr(runtime, 'run_outer_coupling', drive)
    outer = runtime._run_outer_coupling_3d(prob, hv, capture_native=True)
    assert outer.native_evidence['mode'] == mode
    for index, (side, solver) in enumerate(zip(('A', 'B'), (prob.sA, prob.sB))):
        expected = snapshots[-1][index]
        if side == 'B':
            expected = expected[:, ::-1, :]
        actual = outer.native_evidence['P_thermal_' + side]
        np.testing.assert_array_equal(actual, expected)
        final = solver.P_ref_abs + solver.P
        if side == 'B':
            final = final[:, ::-1, :]
        assert np.array_equal(actual, final) is not cap
        if mode == 'true_h':
            for snapshot, pressures in zip(snapshots, kernel_pressures):
                np.testing.assert_array_equal(pressures[index], snapshot[index] if side == 'A' else snapshot[index][:, ::-1, :])
        if pair[index] != 'air':
            # Analytic linear profile from flow(): inlet gauge is 10*n.
            assert solver.P_ref_abs + 10. * solver._test_calls == pytest.approx(getattr(prob, 'P_in' + side))
    if 'sco2' in pair:
        assert property_pressures
        assert all(p.ndim == 0 and float(p) == 12e6 for p in property_pressures)


def test_water_phase_guard_checks_actual_local_pressure(monkeypatch):
    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = _build_3d_problem(_pipeline_cfg(('air', 'water')))
    hv = runtime._build_hv_machinery(prob)
    prob.cfg['T_s_init'] = 380.
    prob.T_inB = 380.  # liquid at the specified 200 kPa, vapour at actual 100 kPa
    prob.sB.P_ref_abs = 100000.
    prob.sB.P[:] = 0.
    fluid_props.check_water_state('water', 380., prob.P_inB)
    monkeypatch.setattr(runtime, 'run_outer_coupling', lambda *, step, **kwargs: step(0))
    def forbidden(*args, **kwargs):
        pytest.fail('invalid local water state reached the thermal kernel')
    monkeypatch.setattr(runtime, 'solve_full_domain_3d', forbidden)
    with pytest.raises(fluid_props.WaterStateError, match='3D temperature warm start B.*P_abs=100000 Pa'):
        runtime._run_outer_coupling_3d(prob, hv)


@pytest.mark.parametrize('case_name', ['sco2-floor', 'fast-air'])
def test_public_pressure_state_matches_thermal_and_reporting(monkeypatch, case_name):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.tests.native.test_native_execution import _config

    cfg = _config(3, air_sco2=True)
    if case_name == 'sco2-floor':
        cfg.fluid_B.P_in_Pa = 7_900_100.
    else:
        cfg.fluid_A.u_mps = 30.
    seen = []
    thermal = ltne_enthalpy_3d.solve_ltne_enthalpy_3d_pipeline
    def observe(*args, **kwargs):
        seen.append(tuple(kwargs['pressure_' + side + '_field'].copy() for side in ('A', 'B')))
        return thermal(*args, **kwargs)
    monkeypatch.setattr(ltne_enthalpy_3d, 'solve_ltne_enthalpy_3d_pipeline', observe)
    result = run_case(prepare_case(cfg, case_id=case_name))
    assert result.run_status['converged']
    for index, side in enumerate(('A', 'B')):
        field = result.fields['P_report_' + side]
        np.testing.assert_array_equal(result.fields['P_thermal_' + side], seen[-1][index])
        np.testing.assert_array_equal(field, seen[-1][index])
        np.testing.assert_array_equal(result.fields['P_f' + side + '_display'], field)
        evidence = result.pressure_evidence[side]
        p, widths = evidence['P'], evidence['dy']
        # Independently extend the first two cell centres to the physical face.
        inlet = p[:, 0] - (p[:, 1] - p[:, 0]) * widths[0] / (widths[0] + widths[1])
        weights = evidence['inlet_frac'] * evidence['dx'][:, None] * evidence['dz'][None, :]
        inlet_abs = evidence['P_ref_abs'] + np.sum(inlet * weights) / weights.sum()
        specified = getattr(cfg, 'fluid_' + side).P_in_Pa
        assert abs(inlet_abs / specified - 1.) < (1e-4 if side == 'A' else 1e-12)
    if case_name == 'sco2-floor':
        assert result.fields['P_report_B'].min() > 7.9e6
    balance = result.metadata['diagnostics']['true_h_balance']
    assert balance['converged'] and balance['equation_energy_balance']['ratio'] <= .001
