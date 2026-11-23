"""Verify raw 3D continuous XY and XYZ native preparation ABI contracts and invariants."""
import ctypes as ct
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import os

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface import _native_grid
from sjtu_tpmshx.cpp_interface import _native_preparation_3d as three
from sjtu_tpmshx.cpp_interface import _native_preparation_case as abi
from sjtu_tpmshx.cpp_interface._native_values import copy_array, read_text
from sjtu_tpmshx.data_types.compute_config import ZoneInputConfig
from tests.python import native_preparation_abi, property_reference as prop_ref


_U, _S, _D = abi._U, abi._S, abi._D
_Controls = three._Controls
_Input = three._ContinuousInput
_Flow = three._ContinuousFlow
_Result = three._ContinuousCase
_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')
_SYMBOLS = {
    'prepare_inlet_mass_capacities': 'tpmshx_preparation_3d_continuous_capacities_v1',
    'resolve_inlet_flow': 'tpmshx_preparation_3d_continuous_resolve_flow_v1',
    'prepare_flow_case': 'tpmshx_preparation_3d_continuous_prepare_case_v1',
}


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', native_preparation_abi._library_path()))
    version = library.tpmshx_preparation_abi_version_v1
    version.argtypes, version.restype = [], _U
    assert version() == 3
    for operation, symbol in _SYMBOLS.items():
        result = _Result if operation == 'prepare_flow_case' else _Flow
        function = getattr(library, symbol)
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
            ct.POINTER(abi._Callbacks), ct.POINTER(result), ct.POINTER(abi._Failure),
            ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    for name, result in (('flow', _Flow), ('case', _Result)):
        release = getattr(library, 'tpmshx_preparation_3d_continuous_' + name + '_release_v1')
        release.argtypes, release.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _configuration(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth', *,
                   nx=4, ny=5, nz=None, mirror=True, order=3):
    config = native_preparation_abi._configuration_3d(topology, pair, mode)
    count = nx * ((ny + 1) // 2 if mirror else ny) * (1 if nz is None else nz)
    spec = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=mirror, spline_order=order,
        L_bounds=[4., 8.], t_bounds=[.3, .6],
        x_decision=[float(value) for value in np.r_[
            np.linspace(4.2, 7.8, count), np.linspace(.57, .32, count)]])
    if nz is not None:
        spec['n_ctrl_z'] = nz
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    return config


def _input(config, targets=None):
    base = native_preparation_abi._input_3d(config)
    base.geometry_mode = 1
    have_targets = targets is not None
    explicit = (_D * 2)(float(targets[0]), float(targets[1])) if have_targets else (_D * 2)()
    spec = config.zones.config
    decision = np.asarray(spec['x_decision'], dtype=np.float64)
    controls = _Controls(spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
        'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'],
        (_D * 2)(*spec['L_bounds']), (_D * 2)(*spec['t_bounds']),
        abi._Array(decision.ctypes.data_as(ct.POINTER(_D)), decision.size))
    source = _Input(1, ct.sizeof(_Input), base, have_targets, explicit, controls)
    source._buffers, source._decision = base._buffers, decision
    return source


def _call(native, operation, config, targets=None, *, source=None, chi=None, reject_event=False):
    source = _input(config, targets) if source is None else source
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(1, ct.sizeof(result_type))
    failure = abi._Failure(2, ct.sizeof(abi._Failure))
    options = abi._Options(1, ct.sizeof(abi._Options), chi is not None, config.extrap.allow, chi or 0.)
    error, events = ct.create_string_buffer(4096), []

    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, read_text(item.logger), read_text(item.message), item.floating_event))
        return int(reject_event)

    callback = abi._EventFunction(event)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), None, 0, callback)
    buffers = source._buffers
    before, decisions = (bytes(source), [bytes(buffer) for buffer in buffers]), source._decision.copy()
    status = getattr(native, _SYMBOLS[operation])(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert (bytes(source), [bytes(buffer) for buffer in buffers]) == before
    native_preparation_abi._same(source._decision, decisions, 'unchanged control input')
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'case' if isinstance(result, _Result) else 'flow'
    release = getattr(native, 'tpmshx_preparation_3d_continuous_' + name + '_release_v1')
    release(ct.byref(result))
    assert not result.owner
    release(ct.byref(result))


def _snapshot(controls, config):
    spec = config.zones.config
    assert (controls.n_ctrl_x, controls.n_ctrl_y, controls.n_ctrl_z,
            bool(controls.have_ctrl_z), controls.spline_order, bool(controls.symmetric_y)) == (
        spec['n_ctrl_x'], spec['n_ctrl_y'], spec.get('n_ctrl_z', 1),
        'n_ctrl_z' in spec, spec['spline_order'], spec['symmetric_y'])
    native_preparation_abi._same(controls.L_bounds_mm, spec['L_bounds'], 'L bounds')
    native_preparation_abi._same(controls.t_bounds_mm, spec['t_bounds'], 't bounds')
    native_preparation_abi._same(copy_array(controls.decision_mm), spec['x_decision'], 'owned controls')


def _full(native, config, targets=None, *, chi=None):
    before = deepcopy(asdict(config))
    status, result, failure, error, live, source = _call(
        native, 'prepare_flow_case', config, targets, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not failure.kind
        _snapshot(result.controls, config)
        source._decision[:] = -1.
        source.input.cell_length_mm = -1.
        for buffer in source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        _snapshot(result.controls, config)
        assert result.prepared.input.cell_length_mm == float(config.geometry.L_cell_mm)
        lengths = (float(config.geometry.L_dom_m), float(config.geometry.H_dom_m), float(config.geometry.Lz_m))
        widths = [copy_array(result.prepared.widths[i]) for i in range(3)]
        shape = tuple(w.size for w in widths)
        for w, length in zip(widths, lengths):
            assert np.all(w > 0.) and w.sum() == pytest.approx(length, rel=1e-12)
        L_field = copy_array(result.prepared.cell_length, shape)
        t_field = copy_array(result.prepared.wall_thickness, shape)
        eps_total = copy_array(result.prepared.total_porosity, shape)
        eps_side = copy_array(result.prepared.side_porosity, shape)
        area_density = copy_array(result.area_density_per_m, shape)
        hydraulic_diameter = copy_array(result.hydraulic_diameter_m, shape)
        thermal_porosity = copy_array(result.thermal_porosity, shape)
        for arr in (L_field, t_field, eps_total, eps_side, area_density, hydraulic_diameter, thermal_porosity):
            assert np.all(np.isfinite(arr)) and np.all(arr > 0.)
        np.testing.assert_allclose(eps_side, .5 * eps_total, rtol=1e-14, atol=1e-14)
        for index, side in enumerate('AB'):
            fluid = getattr(config, 'fluid_' + side)
            props = prop_ref.fluid_props(fluid.type, float(fluid.T_in_K), float(fluid.P_in_Pa))
            recorded = result.prepared.sides[index]
            assert recorded.rho == pytest.approx(props.rho, rel=1e-12)
            assert recorded.mu == pytest.approx(props.mu, rel=1e-12)
            assert recorded.k_f == pytest.approx(props.k, rel=1e-12)
        have_targets = targets is not None or any(
            getattr(config, 'fluid_' + side).mass_flow_kg_s is not None for side in 'AB')
        assert bool(result.flow.have_capacities) == have_targets
        if have_targets:
            for index, side in enumerate('AB'):
                assert result.flow.capacities[index] > 0.
                target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
                if target is not None:
                    assert result.flow.speeds[index] == pytest.approx(
                        float(target) / result.flow.capacities[index], rel=1e-13)
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.event_count == 0
        summary = dict(widths=widths, L_field=L_field, t_field=t_field, eps_total=eps_total,
            area_density=area_density, hydraulic_diameter=hydraulic_diameter,
            thermal_porosity=thermal_porosity, speeds=tuple(result.flow.speeds),
            capacities=tuple(result.flow.capacities),
            sco2_nu_source=read_text(result.prepared.input.sco2_nu.source),
            sco2_nu_version=read_text(result.prepared.input.sco2_nu.parameter_version),
            events=live)
    finally:
        _release(native, result)
    assert asdict(config) == before
    return summary


def _query(native, operation, config, targets=None):
    status, result, failure, error, live, source = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.owner and not failure.kind
        _snapshot(result.controls, config)
        source._decision[:] = -1.
        _snapshot(result.controls, config)
        assert native_preparation_abi._events(result.flow.evidence) == live
        if operation == 'prepare_inlet_mass_capacities':
            assert result.flow.have_capacities
            out = {'A': result.flow.capacities[0], 'B': result.flow.capacities[1]}
            assert out['A'] > 0. and out['B'] > 0.
        else:
            out = tuple(result.flow.speeds)
            for index, side in enumerate('AB'):
                target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
                if target is not None:
                    assert out[index] == pytest.approx(float(target) / result.flow.capacities[index], rel=1e-13)
    finally:
        _release(native, result)
    return out, live


@pytest.mark.parametrize('nz', [None, 3], ids=['xy', 'xyz'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(abi._FLUIDS, repeat=2)))
def test_continuous_3d_pair_capacity_resolve_and_full(native, topology, pair, nz):
    config = _configuration(topology, pair, nz=nz)
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
        fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    speeds, _ = _query(native, 'resolve_inlet_flow', stale, targets)
    summary = _full(native, stale, targets)
    assert speeds[0] == pytest.approx(config.fluid_A.u_mps, rel=1e-13)
    assert speeds[1] == pytest.approx(config.fluid_B.u_mps, rel=1e-13)
    assert summary['speeds'] == speeds


@pytest.mark.parametrize('layout', [
    (1, 1, None, False, 1), (1, 5, None, True, 3), (4, 1, None, False, 2),
    (4, 4, None, True, 2), (4, 5, None, False, 3),
    (4, 5, 1, True, 3), (1, 4, 3, False, 3), (4, 1, 3, True, 2),
    (1, 1, 1, True, 3), (4, 4, 2, True, 1), (4, 5, 3, False, 2),
])
def test_continuous_3d_control_layouts_and_orders(native, layout):
    nx, ny, nz, mirror, order = layout
    config = _configuration(nx=nx, ny=ny, nz=nz, mirror=mirror, order=order)
    summary = _full(native, config)
    if nz is None:
        values = summary['L_field']
        native_preparation_abi._same(values, np.repeat(values[:, :, :1], values.shape[2], axis=2), 'XY extrusion')


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
def test_continuous_3d_configured_and_mixed_flow_ports(native, direction, sides):
    config = _configuration(nz=None if direction % 2 else 3)
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    native_preparation_abi._partial_ports(config, direction)
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config)
    original_speeds = {'A': config.fluid_A.u_mps, 'B': config.fluid_B.u_mps}
    for side in sides:
        fluid = getattr(config, 'fluid_' + side)
        setattr(config, 'fluid_' + side, replace(fluid,
            u_mps=-99., mass_flow_kg_s=float(capacities[side] * fluid.u_mps)))
    speeds, _ = _query(native, 'resolve_inlet_flow', config)
    summary = _full(native, config)
    for index, side in enumerate('AB'):
        assert speeds[index] == pytest.approx(original_speeds[side], rel=1e-13)
        assert summary['speeds'][index] == pytest.approx(original_speeds[side], rel=1e-13)


@pytest.mark.parametrize('nz,direction', [(None, 0), (3, 5)])
def test_continuous_3d_samples_refined_physical_centres(native, nz, direction):
    config = _configuration(nz=nz)
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .081, .063, .047
    native_preparation_abi._partial_ports(config, direction)
    lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
    for side in 'AB':
        port = getattr(config, 'bc_' + side)
        depth = lengths[_native_grid.axis_map(port.dir)[2]]
        port.in_z_ctr, port.in_z_w = .43 * depth, .57 * depth
        port.out_z_ctr, port.out_z_w = .59 * depth, .49 * depth
    config.flags.port_wall_refine = True
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 52, 54, 56
    summary = _full(native, config)
    assert any(np.ptp(w) > 0 for w in summary['widths'])


@pytest.mark.parametrize('nz', [None, 3])
@pytest.mark.parametrize('topology,pair', [
    ('Gyroid', ('air', 'water')), ('Gyroid', ('co2', 'co2')), ('Diamond', ('co2', 'co2'))])
def test_continuous_3d_existing_experimental_scope(native, topology, pair, nz):
    config = _configuration(topology, pair, 'experimental', nz=nz)
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _full(native, config)
    _full(native, config, targets)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'material-array', 'inlet', 'grid-port'])
def test_continuous_3d_float64_normalization(native, dtype, selection):
    def make_config(cast):
        config = _configuration('Diamond', ('co2', 'water'), nz=3)
        if selection == 'geometry':
            config.geometry.L_cell_mm, config.geometry.t_wall_mm = cast(6.125), cast(.42)
        elif selection == 'material-array':
            config.geometry.k_s_W_mK = np.asarray(cast(1.337))
        elif selection == 'inlet':
            config.fluid_A.u_mps, config.fluid_A.T_in_K = cast(.125), cast(401.13)
            config.fluid_B.u_mps, config.fluid_B.T_in_K = cast(.03125), cast(321.13)
        else:
            config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(cast, (.081, .063, .047))
            native_preparation_abi._partial_ports(config, 5)
            for side in 'AB':
                port = getattr(config, 'bc_' + side)
                for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
                    setattr(port, name, cast(getattr(port, name)))
        return config

    actual = _full(native, make_config(dtype), chi=.73)
    expected = _full(native, make_config(lambda v: float(dtype(v))), chi=.73)
    native_preparation_abi._same(actual['eps_total'], expected['eps_total'], 'float64 normalized porosity')
    native_preparation_abi._same(actual['L_field'], expected['L_field'], 'float64 normalized L_field')


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_continuous_3d_target_types(native, dtype, array):
    config = _configuration(nz=1)
    values = (1, 2) if dtype is np.int16 else (.003, .03)
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value) for value in values)
    _query(native, 'resolve_inlet_flow', config, targets)
    _full(native, config, targets)


@pytest.mark.parametrize('nz', [None, 3])
def test_continuous_3d_owned_provenance_and_nu_selection(native, nz):
    config = _configuration(pair=('sco2', 'co2'), nz=nz)
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
        parameter_version='saved continuous version', source='保留来源', applicability='保留范围')
    summary = _full(native, config)
    assert summary['sco2_nu_source'] == '保留来源'
    assert summary['sco2_nu_version'] == 'saved continuous version'


@pytest.mark.parametrize('operation', ['prepare_inlet_mass_capacities', 'resolve_inlet_flow'])
def test_continuous_3d_query_emits_out_of_range_evidence(native, operation):
    from sjtu_tpmshx.physical_models import tpms_props
    config = _configuration(nz=3)
    config.fluid_A.T_in_K = min(tpms_props._AIR_T_RANGE[0], tpms_props._AIR_CP_RANGE[0]) - 10.
    targets = (.003, .03) if operation == 'resolve_inlet_flow' else None
    status, result, _, error, _, _ = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.flow.evidence.range_count > 0
        assert result.flow.evidence.warning_count > 0
    finally:
        _release(native, result)


def test_continuous_3d_capacity_ignores_speeds_and_explicit_targets(native):
    config = _configuration(mode='experimental', nz=3)
    config.fluid_A.u_mps, config.fluid_B.u_mps, config.extrap.allow = -99., float('nan'), False
    _query(native, 'prepare_inlet_mass_capacities', config, (-1., float('nan')))


def test_continuous_3d_no_target_resolution_keeps_unvalidated_owned_input(native):
    config = _configuration(nz=1)
    config.fluid_A.T_in_K = -1.
    config.zones.config['spline_order'] = 0
    config.sco2_nu = replace(config.sco2_nu, source='retained source')
    status, result, failure, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not failure.kind and not result.flow.have_capacities and not live
        assert result.flow.evidence.range_count == result.flow.evidence.warning_count == result.flow.evidence.event_count == 0
        for name, _ in native_preparation_abi._Input_3d._fields_:
            if name != 'sco2_nu':
                assert native_preparation_abi._struct_values(getattr(result.flow.input, name)) == native_preparation_abi._struct_values(getattr(source.input, name))
        source._decision[:] = -1.
        _snapshot(result.controls, config)
        for buffer in source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert read_text(result.flow.input.sco2_nu.source) == config.sco2_nu.source
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation,selection', [
    (operation, selection)
    for operation in _OPERATIONS
    for selection in ('order', 'counts', 'z-count', 'L-bounds', 't-bounds',
        'decision-length', 'control-domain', 'control-nan', 'nan-before-bounds', 'bounds-nan',
        'delta', 'experimental-pair', 'experimental-nominal', 'experimental-domain',
        'depth-before-controls', 'target-before-controls', 'water-before-grid', 'co2-critical')
    if operation != 'prepare_inlet_mass_capacities' or not selection.startswith('experimental-')
])
def test_continuous_3d_first_error_and_failure_atomicity(native, operation, selection):
    config, targets = _configuration(nz=3), (.003, .03)
    spec = config.zones.config
    if selection == 'order': spec['spline_order'] = 0
    elif selection == 'counts': spec['n_ctrl_x'] = 0
    elif selection == 'z-count': spec['n_ctrl_z'] = 0
    elif selection == 'L-bounds': spec['L_bounds'] = [3., 9.]
    elif selection == 't-bounds': spec['t_bounds'] = [.2, .7]
    elif selection == 'decision-length': spec['x_decision'].pop()
    elif selection == 'control-domain': spec['x_decision'][0] = 3.
    elif selection == 'control-nan': spec['x_decision'][0] = float('nan')
    elif selection == 'nan-before-bounds': spec['x_decision'][0], spec['L_bounds'] = float('nan'), [3., 9.]
    elif selection == 'bounds-nan': spec['L_bounds'][0] = float('nan')
    elif selection == 'delta': config.geometry.delta_levelset = .1
    elif selection == 'experimental-pair': config.df_mode, config.fluid_A.type = 'experimental', 'water'
    elif selection == 'experimental-nominal': config.df_mode, config.geometry.L_cell_mm = 'experimental', 6.
    elif selection == 'experimental-domain': config.df_mode, config.geometry.L_dom_m = 'experimental', .18
    elif selection == 'depth-before-controls': config.geometry.Lz_m, spec['spline_order'] = 0., 0
    elif selection == 'target-before-controls': spec['spline_order'], targets = 0, (float('nan'), .03)
    elif selection == 'water-before-grid': config.fluid_B.T_in_K, config.solver.Nx = 500., 0
    else:
        config.fluid_A.type = 'co2'
        config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = 304.1282, 7377298.373
    status, result, failure, error, _, _ = _call(native, operation, config, targets)
    assert status != 0 and error
    assert failure.kind in (1, 2)
    assert bytes(result) == bytes(type(result)(1, ct.sizeof(result)))
    _release(native, result)


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_continuous_3d_callback_failure_keeps_output(native, operation):
    config = _configuration(nz=3)
    config.fluid_A.T_in_K = np.float64(1e308)
    status, result, failure, error, events, _ = _call(
        native, operation, config, (.003, .03), reject_event=True)
    assert status != 0 and error and failure.kind == 3
    assert len(events) == 1
    assert bytes(result) == bytes(type(result)(1, ct.sizeof(result)))


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['decision-output', 'decision-failure', 'decision-error',
    'source-output', 'source-error', 'output-error', 'failure-error', 'text-output'])
def test_continuous_3d_overlapping_storage_is_unchanged(native, operation, selection):
    source = _input(_configuration(nz=3), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(1, ct.sizeof(result_type)), abi._Failure(2, ct.sizeof(abi._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    result_pointer, error_pointer, capacity = ct.pointer(result), error, len(error)
    if selection.startswith('decision-'):
        target = {'decision-output': result, 'decision-failure': failure, 'decision-error': error}[selection]
        source.controls.decision_mm = abi._Array(ct.cast(ct.pointer(target), ct.POINTER(_D)), 1)
    elif selection.endswith('-error'):
        target = {'source-error': source, 'output-error': result, 'failure-error': failure}[selection]
        error_pointer, capacity = ct.cast(ct.byref(target, 8), ct.POINTER(ct.c_char)), 16
    elif selection == 'source-output':
        result_pointer = ct.cast(ct.pointer(source), ct.POINTER(result_type))
    else:
        source.input.sco2_nu.source = abi._Text(ct.cast(ct.pointer(result), ct.POINTER(ct.c_char)), 16)
    objects = (source, result, failure, error)
    before = [bytes(value) for value in objects]
    assert getattr(native, _SYMBOLS[operation])(
        ct.byref(source), None, None, result_pointer, ct.byref(failure), error_pointer, capacity) != 0
    assert [bytes(value) for value in objects] == before


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_continuous_3d_owned_result_requires_release(native, operation):
    status, result, failure, error, _, source = _call(native, operation, _configuration(), (.003, .03))
    assert status == 0, error
    before, decisions = bytes(result), copy_array(result.controls.decision_mm)
    error = ct.create_string_buffer(4096)
    try:
        assert getattr(native, _SYMBOLS[operation])(
            ct.byref(source), None, None, ct.byref(result), ct.byref(failure), error, len(error)) != 0
        assert 'release' in error.value.decode()
        assert bytes(result) == before
        native_preparation_abi._same(copy_array(result.controls.decision_mm), decisions, 'retained owner')
    finally:
        _release(native, result)


@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_continuous_3d_co2_common_and_thermal_geometry_differ(native, pair):
    config = _configuration(pair=pair, nx=3, ny=4, nz=3, mirror=False)
    summary = _full(native, config)
    if pair[0] == 'co2':
        assert np.any(summary['eps_total'] != summary['thermal_porosity'])
    else:
        np.testing.assert_allclose(summary['eps_total'], summary['thermal_porosity'], rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('record', ['input', 'case', 'result', 'options', 'callbacks', 'failure'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_continuous_3d_rejects_incompatible_records(native, operation, record, field):
    source = _input(_configuration(nz=3), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(1, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks))
    selected = {'input': source, 'case': source.input,
        'result': result, 'options': options, 'callbacks': callbacks, 'failure': failure}[record]
    setattr(selected, field, 99 if field == 'abi_version' else 1)
    before = bytes(result)
    assert getattr(native, _SYMBOLS[operation])(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error)) != 0
    assert error.value and bytes(result) == before


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('nz', [None, 1, 3])
@pytest.mark.parametrize('nx', [1, 4])
def test_continuous_3d_typed_grid_with_exact_width_coverage(native, dtype, nz, nx):
    config = _configuration(nx=nx, nz=nz)
    config.solver.Nx = config.solver.Ny = config.solver.Nz = 4
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
    _full(native, config)


@pytest.mark.parametrize('operation,targets', native_preparation_abi._OWNED_FLOW_CASES)
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', ['none', 'source_abi', 'source_size',
    'input_abi', 'input_size', 'result_abi', 'result_size'])
def test_continuous_3d_owned_views_reject_diagnostic_aliases(native, operation, targets, destination, invalid):
    config = _configuration(nz=1)
    config.sco2_nu = replace(config.sco2_nu, parameter_version='saved version',
                            source='saved source', applicability='saved range')
    if not targets:
        config.fluid_A.T_in_K = -1.
        config.zones.config['spline_order'] = 0
    status, result, _, error, _, source = _call(native, operation, config, (.003, .03) if targets else None)
    assert status == 0, error
    target = (source.input if invalid.startswith('input') else source if invalid.startswith('source') else result)
    if invalid != 'none':
        setattr(target, 'abi_version' if invalid.endswith('abi') else 'struct_size', 0)
    before = bytes(source), [bytes(buffer) for buffer in source._buffers], source._decision.tobytes()
    try:
        labels = native_preparation_abi._check_owned_aliases(lambda failure, error, capacity:
            getattr(native, _SYMBOLS[operation])(ct.byref(source), None, None,
                ct.byref(result), ct.cast(failure, ct.POINTER(abi._Failure)), error, capacity), result, destination)
        assert any('.controls.decision_mm' in label for label in labels)
        assert any('.flow.input.sco2_nu.source' in label for label in labels)
        if targets:
            assert any('.flow.evidence.ranges' in label for label in labels)
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.warning_count == result.flow.evidence.event_count == 0
        if operation == 'prepare_flow_case':
            for name in ('prepared.permeability', 'area_density_per_m', 'hydraulic_diameter_m', 'thermal_porosity'):
                assert any('.' + name in label for label in labels), name
        assert (bytes(source), [bytes(buffer) for buffer in source._buffers], source._decision.tobytes()) == before
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation,targets', native_preparation_abi._OWNED_FLOW_CASES)
def test_continuous_3d_owned_output_keeps_safe_reuse_diagnostics(native, operation, targets):
    config = _configuration(nz=1)
    config.sco2_nu = replace(config.sco2_nu, source='saved source')
    if not targets:
        config.fluid_A.T_in_K = -1.
        config.zones.config['spline_order'] = 0
    status, result, _, error, _, source = _call(native, operation, config, (.003, .03) if targets else None)
    assert status == 0, error
    try:
        outer = bytes(result)
        before = [(label, pointer, ct.string_at(pointer, size)) for label, pointer, size in native_preparation_abi._visible_buffers(result)]
        failure, error, events = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096), []
        event = abi._EventFunction(lambda context, pointer: events.append(1) or 0)
        callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), None, 0, event)
        status = getattr(native, _SYMBOLS[operation])(ct.byref(source), None,
            ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
        assert status == 1 and failure.kind == 1 and b'release' in error.value
        assert not events and bytes(result) == outer
        assert before
        for label, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, label
    finally:
        _release(native, result)


@pytest.mark.parametrize('destination', ['error', 'failure'])
def test_continuous_3d_owned_drag_text_rejects_diagnostic_aliases(native, destination):
    config = _configuration(mode='experimental', nz=3)
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = .182, .042, .042
    status, result, _, error, _, source = _call(native, 'prepare_flow_case', config)
    assert status == 0, error
    try:
        labels = native_preparation_abi._check_owned_aliases(lambda failure, error, capacity:
            native.tpmshx_preparation_3d_continuous_prepare_case_v1(ct.byref(source), None, None,
                ct.byref(result), ct.cast(failure, ct.POINTER(abi._Failure)), error, capacity), result, destination)
        for side in range(2):
            for name in ('transfer_policy', 'geometry_application'):
                assert any(f'.drag[{side}].{name}' in label for label in labels), (side, name)
    finally:
        _release(native, result)
