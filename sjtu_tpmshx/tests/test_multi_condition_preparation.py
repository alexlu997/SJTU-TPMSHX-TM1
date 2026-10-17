"""Fixed mass-flow preparation agrees with the native 2D/3D inlet faces."""
from dataclasses import asdict, replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig, ExtrapPolicy,
)
from sjtu_tpmshx.optimization.multi_condition import prepare_fixed_mass_flow_case
from sjtu_tpmshx.preprocess.three_d import preparation
from sjtu_tpmshx.preprocess.api import prepare_case, prepare_inlet_mass_capacities, resolve_fixed_mass_flow_config
from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.module_ports import resolve_control
from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('design_mode', ['uniform', 'grid', 'continuous'])
@pytest.mark.parametrize('input_mode', ['explicit_batch', 'configured_flow'])
def test_fixed_flow_matches_native_faces_after_density_update(monkeypatch, direction, design_mode, input_mode):
    shape, lengths = (6, 5, 4), (.04, .05, .06)
    widths = tuple(np.arange(1., count + 1.) * length / sum(range(1, count + 1))
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation, '_build_grid_3d', lambda *args: (*widths, *shape))
    port = PartialBCConfig(in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021,
                           in_z_ctr=.020, in_z_w=.031, out_z_ctr=.024, out_z_w=.019)
    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=340., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1],
                                Lz_m=lengths[2], L_cell_mm=6., t_wall_mm=.4),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], Nz=shape[2],
                            max_iter_simple=1, max_outer_ltne=2),
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
    if input_mode == 'configured_flow':
        config = replace(config, **{'fluid_' + side: replace(getattr(config, 'fluid_' + side),
                         u_mps=-1., mass_flow_kg_s=targets[side]) for side in 'AB'})
        original = asdict(config)
        case = prepare_case(config, case_id='fixed-mass-flow')
    else:
        case = prepare_fixed_mass_flow_case(
            config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
            case_id='fixed-mass-flow')
    assert asdict(config) == original
    assert case.case_id == 'fixed-mass-flow'
    assert dict(case.config_snapshot['geometry']) == original['geometry']
    assert case.config_snapshot['df_mode'] == config.df_mode
    params, prepared = build_execution_inputs(case)
    raw = NativeFull3DDriver(resolve_control(RunControl()).native_library).run_prepared(params, prepared)
    for index, side in enumerate('AB'):
        flow, axes = raw['flow'][index], prepared['axes'][side]
        fluid = getattr(config, 'fluid_' + side)
        snapshot = case.config_snapshot['fluid_' + side]
        assert dict(snapshot) == {**asdict(fluid), 'u_mps': params['u_' + side]}
        assert snapshot['u_mps'] != fluid.u_mps
        assert dict(case.config_snapshot['bc_' + side]) == original['bc_' + side]
        fractions = prepared['openings'][side]['inlet']
        assert np.any((fractions > 0.) & (fractions < 1.))
        if design_mode != 'uniform':
            assert np.ptp(case.design_fields['eps_' + side]) > 0.
        axis, edge = axes['stream_real_axis'], -1 if axes['is_reverse'] else 0
        inward_sign = -1 if axes['is_reverse'] else 1
        inlet = np.take(raw['mass'][index][axis], edge, axis=axis)
        assert inward_sign*inlet.sum() == pytest.approx(targets[side], rel=2e-14)
        # The returned flow has a later density update than the thermal input.
        final_inlet = (flow['v'][:, 0, :]*flow['density'][:, 0, :]*(flow['epsilon'][:, 0, :]/2.)
                       *flow['widths'][0][:, None]*flow['widths'][2][None, :])
        assert final_inlet.sum() == pytest.approx(targets[side], rel=2e-14)


@pytest.mark.parametrize('direction', range(4))
@pytest.mark.parametrize('design_mode', ['uniform', 'continuous'])
@pytest.mark.parametrize('port_profile', ['full', 'uniform-partial', 'tapered-partial'])
def test_fixed_flow_2d_preserves_prescribed_inlet_after_density_update(monkeypatch, direction, design_mode,
                                                port_profile):
    from sjtu_tpmshx.preprocess.two_d import preparation as preparation_2d
    from sjtu_tpmshx.tests.native.prepared_snapshot import native_prepared_state

    shape, lengths = (9, 10), (.04, .05)
    widths = tuple(np.linspace(.3, 1.7, count) * length / count
                   for count, length in zip(shape, lengths))
    monkeypatch.setattr(preparation_2d, '_prepare_mesh', lambda cfg: dict(
        energy_dx=widths[0], energy_dy=widths[1], _x_breaks=(), _y_breaks=()))

    def port(d):
        span = lengths[1 if d < 2 else 0]
        full = port_profile == 'full'
        return PartialBCConfig(
            dir=d, in_ctr=(.5 if full else .47) * span,
            in_w=(1. if full else .53) * span,
            out_ctr=(.5 if full else .55) * span,
            out_w=(1. if full else .49) * span,
            uniform_inlet_2d=port_profile == 'uniform-partial')

    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1], Lz_m=.02),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], max_iter_simple=1, max_outer_ltne=2),
        bc_A=port(direction), bc_B=port((direction + 1) % 4),
        extrap=ExtrapPolicy(allow=True))
    if design_mode == 'continuous':
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [5., 6., 7., 7.5, .3, .4, .45, .6],
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    targets = {'A': .001, 'B': .03}
    case = prepare_fixed_mass_flow_case(
        config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
        case_id='fixed-mass-2d')
    cfg, grid, state = native_prepared_state(case)
    for index, side in enumerate('AB'):
        prefix = f'state.result.flow.{index}.'
        shape = (len(state[prefix+'dx']), len(state[prefix+'dy']))
        flow = {name: state[prefix+name].reshape(shape) for name in ('density', 'epsilon')}
        flow.update({name: state[prefix+name] for name in ('inlet_velocity', 'dx')})
        flow['taper_flux_scale'] = state[prefix+'taper_flux_scale'][0]
        d = cfg['cfg'+side]['dir']
        if port_profile == 'tapered-partial':
            assert flow['taper_flux_scale'] > 1.
        else:
            assert flow['taper_flux_scale'] == 1.
        eps = np.asarray(case.design_fields['eps_arr']) / 2.
        if design_mode == 'continuous':
            assert np.ptp(np.take(eps, -1 if d % 2 else 0, axis=d//2)) > 0.
        # A capped SIMPLE return precedes the next boundary application.
        # Check its updated prescribed speed, as the original target test did.
        opening = cfg['boundary_openings'][side]['in_profile_frac']
        actual = np.sum(flow['inlet_velocity']*flow['density'][:, 0]
                        *flow['epsilon'][:, 0]/2.*opening*flow['dx'])*.02
        assert actual == pytest.approx(targets[side], rel=2e-14)


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


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('design_mode', ['uniform', 'continuous'])
@pytest.mark.parametrize('df_mode', ['cfd_smooth', 'experimental'])
def test_fixed_flow_uses_only_resolved_velocities(monkeypatch, dimension, design_mode, df_mode):
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.182, H_dom_m=.042, Lz_m=.042),
        solver=SolverConfig(Nx=4, Ny=4, Nz=2 if dimension == 3 else 1),
        fluid_A=FluidConfig(type='air', u_mps=6., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        df_mode=df_mode)
    if design_mode == 'continuous':
        count = 4 if dimension == 2 else 8
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': np.linspace(6.8, 7.2, count).tolist()
                          + np.linspace(.5, .58, count).tolist(),
            'n_ctrl_x': 2, 'n_ctrl_y': 2, 'symmetric_y': False,
            'spline_order': 1, 'L_bounds': [4., 8.], 't_bounds': [.3, .6],
            **({'n_ctrl_z': 2} if dimension == 3 else {})})
    reference = prepare_case(config, case_id='reference')
    targets = {'mass_flow_' + side + '_kg_s': getattr(config, 'fluid_' + side).u_mps
               * total_inlet_mass_capacity(reference.design_fields, reference.parameters,
                                          reference.grid, side) for side in ('A', 'B')}
    expected = prepare_case(resolve_fixed_mass_flow_config(config, **targets), case_id='fixed')
    old = replace(config, fluid_A=replace(config.fluid_A, u_mps=.001),
                  fluid_B=replace(config.fluid_B, u_mps=.00001))
    snapshot = asdict(old)
    from unittest.mock import patch
    from sjtu_tpmshx.preprocess.two_d import preparation as prep2d
    with patch.object(preparation, '_prepare_geometry_data', wraps=preparation._prepare_geometry_data) as geometry, \
         patch.object(prep2d, '_prepare_mesh', wraps=prep2d._prepare_mesh) as mesh, \
         patch.object(prep2d, '_build_zone_arrays', wraps=prep2d._build_zone_arrays) as zones:
        actual = prepare_fixed_mass_flow_case(old, **targets, case_id='fixed')
    if dimension == 3:
        assert geometry.call_count == 1
    else:
        assert mesh.call_count == 1
        assert zones.call_count == 2  # Final inlet geometry, then original nominal validation.
        assert zones.call_args_list[0].kwargs['geometry_only']
        assert actual.design_fields['eps_arr'].shape != (4, 4)
    assert asdict(old) == snapshot
    assert actual.config_snapshot == expected.config_snapshot
    assert actual.metadata['warnings'] == expected.metadata['warnings']
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import compare
    compare(actual.parameters, expected.parameters)
    compare(actual.grid, expected.grid)
    assert actual.model_refs == expected.model_refs
    for key in expected.design_fields:
        np.testing.assert_equal(actual.design_fields[key], expected.design_fields[key])
    for side in ('A', 'B'):
        assert actual.parameters['u_' + side] == pytest.approx(getattr(config, 'fluid_' + side).u_mps)
    # The resolved velocity still passes through both original physical gates.
    invalid = {**targets, 'mass_flow_A_kg_s': targets['mass_flow_A_kg_s'] * 1e-6}
    message = 'HX experiment calibration' if df_mode == 'experimental' and design_mode == 'uniform' else 'outside air Nu window'
    with pytest.raises(ValueError, match=message):
        prepare_fixed_mass_flow_case(old, **invalid, case_id='invalid-final-speed')


@pytest.mark.parametrize('design_mode', ['x', 'y', 'grid', 'sigmoid'])
def test_fixed_flow_preserves_legacy_2d_geometry_and_input(monkeypatch, tmp_path, design_mode):
    from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig

    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=.04, H_dom_m=.05, Lz_m=.02),
        solver=SolverConfig(Nx=12, Ny=12),
        fluid_A=FluidConfig(u_mps=5., T_in_K=380., P_in_Pa=160000.),
        fluid_B=FluidConfig(u_mps=5., T_in_K=300., P_in_Pa=200000.),
        bc_A=PartialBCConfig(dir=1, in_ctr=.023, in_w=.021, out_ctr=.025, out_w=.019),
        bc_B=PartialBCConfig(dir=3, in_ctr=.018, in_w=.027, out_ctr=.023, out_w=.021))
    config.zones = ZoneInputConfig(enabled=True, axis='grid' if design_mode == 'sigmoid' else design_mode)
    if design_mode in ('x', 'y'):
        config.zones.config = ZoneConfig([
            Zone('outlet', .5, 1., 7., .5), Zone('inlet', 0., .5, 6., .4)], 'Gyroid', 16.)
    else:
        config.zones.grid = {'cells': [
            dict(x0=0., x1=.5, y0=0., y1=1., L=6., t=.4),
            dict(x0=.5, x1=1., y0=0., y1=1., L=7., t=.5)],
            'tpms_type': 'Gyroid', 'k_s': 16.}
    if design_mode == 'sigmoid':
        from sjtu_tpmshx.models import sigmoid_field
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=3, N=16, cache_dir=str(tmp_path))
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *_: lut)
        config.zones.pareto_x_decision = [value for cell in np.linspace(6., 7., 18)
                                        for value in (float(cell), .4)]
    snapshot = asdict(config)
    reference = prepare_case(config, case_id='legacy-reference')
    assert 'optimizer' not in reference.config_snapshot
    assert 'optimizer' not in reference.parameters['run_settings']
    targets = {'mass_flow_' + side + '_kg_s': getattr(config, 'fluid_' + side).u_mps
               * total_inlet_mass_capacity(reference.design_fields, reference.parameters,
                                          reference.grid, side) for side in ('A', 'B')}
    old = replace(config, fluid_A=replace(config.fluid_A, u_mps=.001))
    expected = prepare_case(resolve_fixed_mass_flow_config(old, **targets), case_id='legacy-fixed')
    from sjtu_tpmshx.preprocess.two_d import preparation as prep2d
    from sjtu_tpmshx.tests.native.test_cpp_full_3d import compare
    from unittest.mock import patch
    with patch.object(prep2d, '_prepare_mesh', wraps=prep2d._prepare_mesh) as mesh:
        actual = prepare_fixed_mass_flow_case(old, **targets, case_id='legacy-fixed')
    assert mesh.call_count == 1
    assert asdict(config) == snapshot
    assert old.fluid_A.u_mps == .001
    assert actual.config_snapshot == expected.config_snapshot
    assert actual.metadata['warnings'] == expected.metadata['warnings']
    compare(actual.parameters, expected.parameters)
    compare(actual.grid, expected.grid)
    for key in reference.design_fields:
        np.testing.assert_equal(actual.design_fields[key], reference.design_fields[key])
    for side in ('A', 'B'):
        assert actual.parameters['u_' + side] == pytest.approx(5.)


def test_capacity_preparation_validates_static_inputs_before_building_fields(monkeypatch):
    from sjtu_tpmshx.preprocess.two_d import preparation as preparation_2d

    def forbidden(*args):
        raise AssertionError('invalid static input reached field construction')

    monkeypatch.setattr(preparation_2d, '_prepare_inlet_data', forbidden)
    monkeypatch.setattr(preparation, '_prepare_geometry_data', forbidden)
    for dimension in (2, 3):
        config = ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
                               solver=SolverConfig(Nz=dimension - 1))
        invalid = (
            (replace(config, solver=replace(config.solver, Nx=True)), 'must be an integer'),
            (replace(config, geometry=replace(config.geometry, L_cell_mm=9.)), 'V2 geometry'),
            (replace(config, fluid_B=replace(config.fluid_B, T_in_K=np.nan)), 'T_in_K'),
        )
        for candidate, message in invalid:
            with pytest.raises(ValueError, match=message):
                prepare_inlet_mass_capacities(candidate)
            with pytest.raises(ValueError, match=message):
                prepare_fixed_mass_flow_case(candidate, mass_flow_A_kg_s=.01,
                                             mass_flow_B_kg_s=.02, case_id='invalid-static')


@pytest.mark.parametrize('continuous', [False, True])
def test_fixed_flow_retains_only_reused_inlet_geometry(monkeypatch, continuous):
    import weakref
    from sjtu_tpmshx.preprocess.two_d import preparation as prep2d

    config = ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
                           solver=SolverConfig(Nx=4, Ny=4), extrap=ExtrapPolicy(allow=True))
    if continuous:
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [7.] * 4 + [.6] * 4, 'n_ctrl_x': 2, 'n_ctrl_y': 2,
            'symmetric_y': False, 'spline_order': 1,
            'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    inlet, finish = prep2d._prepare_inlet_data, prep2d._prepare_case
    references = []

    def tracked_inlet(config):
        data = inlet(config)
        references.append(weakref.ref(data[0]['eps_arr']))
        return data

    def tracked_finish(*args, **kwargs):
        assert (references[0]() is not None) == continuous
        return finish(*args, **kwargs)

    monkeypatch.setattr(prep2d, '_prepare_inlet_data', tracked_inlet)
    monkeypatch.setattr(prep2d, '_prepare_case', tracked_finish)
    prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=.01,
                                 mass_flow_B_kg_s=.02, case_id='inlet-lifetime')
    assert references[0]() is None
