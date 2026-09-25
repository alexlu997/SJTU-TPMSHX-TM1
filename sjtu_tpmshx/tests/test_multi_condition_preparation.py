"""Fixed mass-flow preparation agrees with the native 3D inlet faces."""
from dataclasses import asdict, replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig,
)
from sjtu_tpmshx.models.field_coordinates_3d import _solver_staggered_to_real
from sjtu_tpmshx.optimization.multi_condition import prepare_fixed_mass_flow_case
from sjtu_tpmshx.preprocess.three_d import preparation
from sjtu_tpmshx.solvers.backends.python.three_d import runtime
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('design_mode', ['uniform', 'grid', 'continuous'])
def test_fixed_flow_matches_native_faces_after_density_update(monkeypatch, direction, design_mode):
    shape, lengths = (6, 5, 4), (.04, .05, .06)
    widths = tuple(np.arange(1., count + 1.) * length / sum(range(1, count + 1))
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation, '_build_grid_3d', lambda *args: (*widths, *shape))
    # Construct the real SIMPLE objects but do not run a numerical sweep.
    monkeypatch.setattr(runtime, '_run_two_simple', lambda *args, **kwargs: None)
    port = PartialBCConfig(in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021,
                           in_z_ctr=.020, in_z_w=.031, out_z_ctr=.024, out_z_w=.019)
    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=340., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1],
                                Lz_m=lengths[2], L_cell_mm=6., t_wall_mm=.4),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], Nz=shape[2]),
        # direction=0 includes the Shanghai A:+x / B:-y orientation.
        bc_A=replace(port, dir=direction), bc_B=replace(port, dir=(direction + 3) % 6))
    if design_mode == 'grid':
        cells = [dict(x0=x0, x1=x1, y0=y0, y1=y1, L=cell, t=wall)
                 for x0, x1, y0, y1, cell, wall in (
                     (0., .4, 0., .6, 4., .3), (.4, 1., 0., .6, 6., .4),
                     (0., .4, .6, 1., 7., .5), (.4, 1., .6, 1., 8., .4))]
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}))
    elif design_mode == 'continuous':
        config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [5., 5.4, 5.8, 5.3, 5.7, 6.1, 5.6, 6., 6.4] +
                          [.4, .42, .44, .41, .43, .45, .42, .44, .46],
            'n_ctrl_x': 3, 'n_ctrl_y': 3, 'symmetric_y': False,
            'spline_order': 2, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]}))
    original = asdict(config)
    targets = {'A': .002, 'B': .03}
    case = prepare_fixed_mass_flow_case(
        config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
        case_id='fixed-mass-flow')
    assert asdict(config) == original
    assert case.case_id == 'fixed-mass-flow'
    assert dict(case.config_snapshot['geometry']) == original['geometry']
    assert case.config_snapshot['df_mode'] == config.df_mode
    params, prepared = build_execution_inputs(case)
    problem = runtime.build_problem(params, prepared)
    for side, solver, axes in (('A', problem.sA, problem.axis_map),
                               ('B', problem.sB, problem.axis_map_B)):
        fluid = getattr(config, 'fluid_' + side)
        snapshot = case.config_snapshot['fluid_' + side]
        assert dict(snapshot) == {**asdict(fluid), 'u_mps': params['u_' + side]}
        assert snapshot['u_mps'] != fluid.u_mps
        assert dict(case.config_snapshot['bc_' + side]) == original['bc_' + side]
        fractions = prepared['openings'][side]['inlet']
        assert np.any((fractions > 0.) & (fractions < 1.))
        if design_mode != 'uniform':
            assert np.ptp(case.design_fields['eps_' + side]) > 0.
        # Air normally captures this target at solve() entry; the numerical
        # solve is deliberately skipped. Water's target is built by runtime.
        if side == 'A':
            solver._massflux_target = (solver.v_inlet_field * solver.rho_field[:, 0, :]).copy()
        assert hasattr(solver, '_massflux_target')
        for update_density in (False, True):
            if update_density:
                i, j, k = np.indices(solver.rho_field.shape)
                solver.rho_field *= 1.3 + .1*i + .02*j + .03*k
                solver._apply_massflux_inlet()
                solver.v[:, 0, :] = solver.v_inlet_field
            rho_real = solver.rho_field.transpose(axes['solver_to_real_perm'])
            if axes['is_reverse']:
                rho_real = np.flip(rho_real, axis=axes['stream_real_axis'])
            native_faces = face_mass_fluxes(
                *_solver_staggered_to_real(solver, axes, shape), rho_real,
                case.design_fields['eps_' + side], *widths)
            inward_sign = -1 if axes['is_reverse'] else 1
            inlet = np.take(native_faces[axes['stream_real_axis']],
                            -1 if axes['is_reverse'] else 0, axis=axes['stream_real_axis'])
            assert inward_sign * inlet.sum() == pytest.approx(targets[side], rel=2e-14)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('invalid', [0., -1., np.inf, np.nan])
def test_fixed_flow_rejects_invalid_targets(side, invalid):
    targets = {'mass_flow_A_kg_s': .01, 'mass_flow_B_kg_s': .02}
    targets['mass_flow_' + side + '_kg_s'] = invalid
    with pytest.raises(ValueError, match='mass_flow_' + side + '_kg_s must be finite and positive'):
        prepare_fixed_mass_flow_case(
            ComputeConfig(solver=SolverConfig(Nz=2)), **targets, case_id='invalid-flow')


@pytest.mark.parametrize('config, message', [(ComputeConfig(), 'positive physical Lz_m'),
    (ComputeConfig(solver=SolverConfig(Nz=2), fluid_B=None), 'dual-fluid')])
def test_fixed_flow_requires_dual_fluid_and_explicit_2d_depth(config, message):
    with pytest.raises(ValueError, match=message):
        prepare_fixed_mass_flow_case(
            config, mass_flow_A_kg_s=.01, mass_flow_B_kg_s=.02, case_id='invalid-config')
