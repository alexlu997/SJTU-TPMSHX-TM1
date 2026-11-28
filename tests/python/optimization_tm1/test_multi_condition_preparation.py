"""Fixed mass-flow preparation agrees with the native 2D/3D inlet faces."""
from dataclasses import asdict, replace

import numpy as np
import pytest

from tm1.data_types.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig,
    SolverConfig, ZoneInputConfig, ExtrapPolicy, FeatureFlags,
)
from tm1.applications.optimization.multi_condition import prepare_fixed_mass_flow_case
from tm1.preprocess.three_d import preparation
from tm1.preprocess.api import prepare_case, prepare_inlet_mass_capacities, resolve_fixed_mass_flow_config
from tm1.preprocess.inlet_flow import total_inlet_mass_capacity
from tm1.run_control.module_ports import RunControl
from tm1.run_control.module_ports import resolve_control


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('design_mode', ['uniform', 'grid', 'continuous'])
def test_fixed_flow_matches_native_faces_after_density_update(direction, design_mode):
    from tests.python.native_adapters.test_native_prepare_adapter import _same

    shape, lengths = (30, 30, 30), (.04, .05, .06)

    def port(selected):
        cross = lengths[1 if selected < 2 else 0]
        other = lengths[2 if selected < 4 else 1]
        return PartialBCConfig(dir=selected,
            in_ctr=.5 * cross, in_w=.5 * cross, out_ctr=.5 * cross, out_w=.5 * cross,
            in_z_ctr=.5 * other, in_z_w=.5 * other, out_z_ctr=.5 * other, out_z_w=.5 * other)
    config = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5., T_in_K=340., P_in_Pa=160000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
        geometry=GeometryConfig(L_dom_m=lengths[0], H_dom_m=lengths[1],
                                Lz_m=lengths[2], L_cell_mm=6., t_wall_mm=.4),
        flags=FeatureFlags(port_wall_refine=True),
        solver=SolverConfig(Nx=shape[0], Ny=shape[1], Nz=shape[2],
                            max_iter_simple=1, max_outer_ltne=2),
        # direction=0 includes the Shanghai A:+x / B:-y orientation.
        bc_A=port(direction), bc_B=port((direction + 3) % 6))
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
    targets = {'A': .002, 'B': .03}
    configured = replace(config, **{
        'fluid_' + side: replace(getattr(config, 'fluid_' + side),
                                 u_mps=-1., mass_flow_kg_s=targets[side]) for side in 'AB'})
    original, draft = asdict(config), asdict(configured)
    case = prepare_fixed_mass_flow_case(
        config, mass_flow_A_kg_s=targets['A'], mass_flow_B_kg_s=targets['B'],
        case_id='fixed-mass-flow')
    configured_case = prepare_case(configured, case_id='fixed-mass-flow')
    assert asdict(config) == original and asdict(configured) == draft
    for current, source in ((case, original), (configured_case, draft)):
        assert current.case_id == 'fixed-mass-flow'
        assert dict(current.config_snapshot['geometry']) == source['geometry']
        assert current.config_snapshot['df_mode'] == source['df_mode']
        for side in 'AB':
            name = 'fluid_' + side
            speed = current.parameters['u_' + side]
            assert speed != source[name]['u_mps']
            assert dict(current.config_snapshot[name]) == {**source[name], 'u_mps': speed}
            boundary = 'bc_' + side
            assert dict(current.config_snapshot[boundary]) == source[boundary]

    _same(configured_case.model_refs, case.model_refs)
    _same(configured_case.metadata['model_roles'], case.metadata['model_roles'])
    # The native call uses saved values, not host records.
    host_values = {'inlet_inputs'}
    _same({name: value for name, value in configured_case.parameters.items() if name not in host_values},
          {name: value for name, value in case.parameters.items() if name not in host_values})
    _same(configured_case.grid, case.grid)
    _same(configured_case.design_fields, case.design_fields)
    prepared = case.parameters['prepared']
    # Test each flow direction and both signs for every layout across six solves.
    if direction not in {'uniform': (0, 3), 'grid': (1, 4), 'continuous': (2, 5)}[design_mode]:
        return
    from tests.python.native.stage_interception import run_stage
    control = resolve_control(RunControl(cpu_threads=2))
    # The audit option detaches the returned solver-axis flow fields.
    raw = run_stage(replace(case, parameters=dict(case.parameters, _emit_audit=True)), control).native
    for index, side in enumerate('AB'):
        flow, axes = raw['flow'][index], prepared['axes'][side]
        fractions = prepared['openings'][side]['inlet']
        assert np.any(fractions > 0.)
        assert any(np.ptp(case.grid['d' + axis]) > 0. for axis in 'xyz')
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
def test_fixed_flow_2d_preserves_prescribed_inlet_after_density_update(direction, design_mode,
                                                port_profile):
    from tests.python.native.prepared_snapshot import native_prepared_state

    # The native stage builds the physical grid and aligns all port segments.
    shape, lengths = (12, 12), (.04, .05)

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
    assert np.ptp(case.grid['dx']) > 0. or np.ptp(case.grid['dy']) > 0.
    cfg, state = case.parameters, native_prepared_state(case)
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
    from tm1.preprocess.two_d import preparation as prep2d
    from tm1.cpp_interface import preparation_host as native
    with patch.object(native, 'volume_operation', wraps=native.volume_operation) as geometry, \
         patch.object(prep2d, 'prepare_case', side_effect=AssertionError('fixed flow prepared twice')) as full, \
         patch.object(native, 'operation', wraps=native.operation) as stage:
        actual = prepare_fixed_mass_flow_case(old, **targets, case_id='fixed')
    if dimension == 3:
        assert geometry.call_count == 1 and geometry.call_args.args[0] == 'prepare_flow_case'
    else:
        assert stage.call_count == 1 and stage.call_args.args[0] == 'prepare_flow_case'
        full.assert_not_called()
        assert actual.design_fields['eps_arr'].shape != (4, 4)
    assert asdict(old) == snapshot
    assert actual.config_snapshot == expected.config_snapshot
    assert actual.metadata['warnings'] == expected.metadata['warnings']
    from tests.python.native.test_cpp_full_3d import compare
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
def test_fixed_flow_preserves_spatial_2d_geometry_and_input(monkeypatch, tmp_path, design_mode):
    from tm1.physical_models.zone_config import Zone, ZoneConfig

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
        from tm1.physical_models import sigmoid_field
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=3, N=16, cache_dir=str(tmp_path))
        from tests.python.native_preparation_abi import supply_sigmoid_table
        supply_sigmoid_table(monkeypatch, lut)
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
    from tm1.preprocess.two_d import preparation as prep2d
    from tests.python.native.test_cpp_full_3d import compare
    from unittest.mock import patch
    from tm1.cpp_interface import preparation_host as native
    with patch.object(prep2d, 'prepare_case', side_effect=AssertionError('fixed flow prepared twice')) as full, \
         patch.object(native, 'operation', wraps=native.operation) as stage:
        actual = prepare_fixed_mass_flow_case(old, **targets, case_id='legacy-fixed')
    full.assert_not_called()
    assert stage.call_count == 1 and stage.call_args.args[0] == 'prepare_flow_case'
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
    from tm1.preprocess.two_d import preparation as preparation_2d

    def forbidden(*args):
        raise AssertionError('invalid static input reached field construction')

    monkeypatch.setattr(preparation_2d, '_execute', forbidden)
    monkeypatch.setattr(preparation, '_execute', forbidden)
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
@pytest.mark.parametrize('entry', ['public', 'direct-2d'])
def test_fixed_flow_releases_native_owner_after_copy(monkeypatch, continuous, entry):
    from contextlib import contextmanager
    from tm1.cpp_interface import preparation_host as native
    from tm1.preprocess.two_d.preparation import prepare_mass_flow_case
    from tm1.run_control.run_warnings import current_warnings, warning_scope

    config = ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
                           solver=SolverConfig(Nx=4, Ny=4), extrap=ExtrapPolicy(allow=True))
    if continuous:
        config.zones = ZoneInputConfig(enabled=True, axis='continuous', config={
            'x_decision': [7.] * 4 + [.6] * 4, 'n_ctrl_x': 2, 'n_ctrl_y': 2,
            'symmetric_y': False, 'spline_order': 1,
            'L_bounds': [4., 8.], 't_bounds': [.3, .6]})
    original = native.operation
    owners = []

    @contextmanager
    def tracked(*args, **kwargs):
        with original(*args, **kwargs) as result:
            owners.append(result)
            assert result.owner
            yield result
            assert result.owner

    monkeypatch.setattr(native, 'operation', tracked)
    with warning_scope({}) as records:
        if entry == 'direct-2d':
            case = prepare_mass_flow_case(config, {'A': .01, 'B': .02}, case_id='inlet-lifetime')
        else:
            case = prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=.01,
                                               mass_flow_B_kg_s=.02, case_id='inlet-lifetime')
        assert current_warnings() is records
    assert len(owners) == 1 and not owners[0].owner
    assert case.metadata['provenance']['code']['package_version']
    assert np.all(np.isfinite(case.design_fields['eps_arr']))
    assert not case.design_fields['eps_arr'].flags.writeable
