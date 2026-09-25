"""Prepared physical geometry and returned face fluxes share the SIMPLE frame."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, ExtrapPolicy, GeometryConfig, PartialBCConfig, SolverConfig,
    ZoneInputConfig,
)
from sjtu_tpmshx.models.field_coordinates_3d import _solver_staggered_to_real
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.preprocess.three_d import preparation
from sjtu_tpmshx.solvers.backends.python.three_d import runtime
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.three_d.flux import _face_flux_weights
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes


def _solver_indices(shape, direction):
    """Independent cell index oracle: local j counts from the physical inlet."""
    order = (1, 0, 2) if direction < 2 else ((0, 1, 2) if direction < 4 else (0, 2, 1))
    for local in np.ndindex(tuple(shape[axis] for axis in order)):
        real = [0, 0, 0]
        for axis, value in zip(order, local):
            real[axis] = value
        if direction % 2:
            real[direction // 2] = shape[direction // 2] - 1 - local[1]
        yield local, tuple(real)


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('design_mode', ['uniform', 'grid', 'continuous', 'continuous_xyz'])
def test_initial_geometry_and_returned_faces_share_physical_frame(monkeypatch, direction, design_mode):
    shape, lengths = (8, 7, 6), (.04, .05, .06)
    # Every axis is asymmetric, so a missing stream reflection cannot hide
    # behind equal widths. Only mesh generation and numerical sweeps are
    # substituted; preparation, immutable Case handoff and construction run.
    widths = tuple(np.arange(1., count + 1.) * length / sum(range(1, count + 1))
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation, '_build_grid_3d', lambda *args: (*widths, *shape))
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *args, **kwargs: None)
    cells = [dict(x0=x0, x1=x1, y0=y0, y1=y1, L=cell, t=.3)
             for x0, x1, y0, y1, cell in (
                 (0., .4, 0., .6, 4.), (.4, 1., 0., .6, 6.),
                 (0., .4, .6, 1., 7.), (.4, 1., .6, 1., 8.))]
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1],
                                Lz_m=lengths[2], L_cell_mm=6., t_wall_mm=.3),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], Nz=shape[2]),
        bc_A=PartialBCConfig(dir=direction), bc_B=PartialBCConfig(dir=direction),
        extrap=ExtrapPolicy(allow=True))
    if design_mode == 'grid':
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}))
    elif design_mode == 'continuous':
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [5., 5.4, 5.8, 5.3, 5.7, 6.1, 5.6, 6., 6.4] +
                          [.4, .42, .44, .41, .43, .45, .42, .44, .46],
            'n_ctrl_x': 3, 'n_ctrl_y': 3, 'symmetric_y': False,
            'spline_order': 2, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    elif design_mode == 'continuous_xyz':
        x, y, z = np.meshgrid(*([np.linspace(0., 1., 3)] * 3), indexing='ij')
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': np.r_[(5. + .3*x + .4*y + .5*z).ravel(),
                                (.35 + .04*x + .02*y + .06*z).ravel()].tolist(),
            'n_ctrl_x': 3, 'n_ctrl_y': 3, 'n_ctrl_z': 3, 'symmetric_y': False,
            'spline_order': 2, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    case = prepare_case(config, case_id='initial-direction-frame')
    if design_mode == 'continuous_xyz':
        for values in case.design_fields.values():
            assert np.any(values[:, :, 0] != values[:, :, -1])
    params, prepared = build_execution_inputs(case)
    problem = runtime.build_problem(params, prepared)
    for side, solver, axes in (('A', problem.sA, problem.axis_map),
                               ('B', problem.sB, problem.axis_map_B)):
        for local_axis, real_axis in enumerate((axes['cross1_real_axis'], direction // 2,
                                                axes['cross2_real_axis'])):
            indices = list(range(shape[real_axis]))
            if local_axis == 1 and direction % 2:
                indices.reverse()
            np.testing.assert_array_equal((solver.dx, solver.dy, solver.dz)[local_axis],
                                          widths[real_axis][indices])
        mapped = {key: np.empty_like(solver.eps_field)
                  for key in ('eps_arr', 'K_m2', 'cF_per_m')}
        expected_pressure = np.empty(shape)
        for local, real in _solver_indices(shape, direction):
            for key, array in mapped.items():
                array[local] = case.design_fields[key][real]
            solver.P[local] = 1. + real[0] + 2.*real[1] + 3.*real[2]
            expected_pressure[real] = solver.P_ref_abs + solver.P[local]
        np.testing.assert_array_equal(solver.eps_field, mapped['eps_arr'])
        np.testing.assert_array_equal(solver._mu_eff_field, solver.mu_field / mapped['eps_arr'])
        # Both sides consume the full field; a mean is only a pressure seed.
        for key, actual, scalar in (('K_m2', solver.K_arr, problem.K_pred_B),
                                    ('cF_per_m', solver.cF_arr, problem.cF_pred_B)):
            np.testing.assert_array_equal(actual, mapped[key])
            assert scalar == pytest.approx(float(case.design_fields[key].mean()), rel=1e-15)
        np.testing.assert_array_equal(runtime._pressure_real_3d(solver, axes, solver.P_ref_abs),
                                      expected_pressure)
        # A native staggered velocity contains the opening fraction already.
        # Compare actual solver-face reductions to mapped physical mass faces,
        # at both ends, using the untouched physical eps/grid fields.
        i, j, k = np.indices(solver.v.shape)
        solver.v[:] = 1. + .1*i + .01*j + .2*k
        solver.u[:] = 0.
        solver.w[:] = 0.
        real_velocity = _solver_staggered_to_real(solver, axes, shape)
        mass_faces = face_mass_fluxes(
            *real_velocity, np.full(shape, solver.rho_field.flat[0]),
            case.design_fields['eps_arr'] / 2., *widths)
        for end, index in (('inlet', -1 if direction % 2 else 0),
                           ('outlet', 0 if direction % 2 else -1)):
            actual = np.abs(np.take(mass_faces[direction // 2], index, axis=direction // 2))
            expected = _face_flux_weights(solver, face='real_' + end)
            np.testing.assert_allclose(actual, expected, rtol=3e-15, atol=0.)
        for array in (solver.K_arr, solver.cF_arr, solver.eps_field,
                      solver.dx, solver.dy, solver.dz):
            assert array.flags.c_contiguous

    # Follow the actual final reporting path too: its output fields feed both
    # display and saved results. Testing only _pressure_real_3d would miss a
    # caller that still transposes A pressure without reflecting its stream.
    zero = np.zeros(shape)
    outer = runtime._OuterState(
        K_ffB=zero, Ta=np.full(shape, problem.T_inA),
        Tb=np.full(shape, problem.T_inB), Ts=np.full(shape, 350.),
        _and_A=None, _and_B=None,
        _assemble_real_velocity=lambda: (zero, zero, zero),
        _eps_A_strict=None, _eps_A_strict_cellmax=None,
        _eps_B_strict=None, _eps_B_strict_cellmax=None,
        _ltne_mask_A=None, _ltne_mask_B=None,
        _outer_converged=False, _outer_dT_hist=[], _outer_last_iter=0,
        _use_outer_and=False, h_vA_field=zero, h_vB_field=zero,
        rho_cp_fA=np.full(shape, problem.rho_A * problem.cp_A),
        rho_cp_fB=np.full(shape, problem.rho_B * problem.cp_B),
        native_evidence=None)
    metrics = runtime._extract_3d_metrics(problem, outer)
    result, diagnostics = runtime._assemble_3d_verdict(problem, outer, metrics)
    i, j, k = np.indices(shape)
    gauge_real = 1. + i + 2.*j + 3.*k
    expected_A = problem.P_inA - metrics.dP + gauge_real
    expected_B = problem.P_inB - metrics.dP_B + gauge_real
    np.testing.assert_array_equal(result['P_Pa'], expected_A)
    np.testing.assert_array_equal(result['P_kPa'], expected_A / 1000.)
    np.testing.assert_array_equal(result['P_Pa_B'], expected_B)
    assert diagnostics['dP_A'] == runtime.SIMPLESolver3D.extract_dP_face_extrap(problem.sA)
    assert diagnostics['dP_B'] == runtime.SIMPLESolver3D.extract_dP_face_extrap(problem.sB)
