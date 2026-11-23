"""Verify raw 3D grid and offset native preparation ABI contracts and invariants."""
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
_Cell = three._Cell
_Input = three._SpatialInput
_Flow = three._SpatialFlow
_Result = three._SpatialCase
_OPERATIONS = ('prepare_inlet_mass_capacities', 'resolve_inlet_flow', 'prepare_flow_case')


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(os.environ.get('TPMSHX_PREPARATION_CASE_LIBRARY', native_preparation_abi._library_path()))
    version = library.tpmshx_preparation_spatial_3d_abi_version_v4
    version.argtypes, version.restype = [], _U
    assert version() == 4
    for operation in _OPERATIONS:
        result = _Result if operation == 'prepare_flow_case' else _Flow
        function = getattr(library, 'tpmshx_' + operation + '_3d_v4')
        function.argtypes = [ct.POINTER(_Input), ct.POINTER(abi._Options),
            ct.POINTER(abi._Callbacks), ct.POINTER(result), ct.POINTER(abi._Failure),
            ct.POINTER(ct.c_char), _S]
        function.restype = ct.c_int
    for name, result in (('flow', _Flow), ('case', _Result)):
        release = getattr(library, 'tpmshx_preparation_spatial_' + name + '_3d_release_v4')
        release.argtypes, release.restype = [ct.POINTER(result)], None
    return library


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)


def _configuration(topology='Gyroid', pair=('air', 'water'), *, spatial=True, delta=.12,
                   mode='cfd_smooth'):
    config = native_preparation_abi._configuration_3d(topology, pair, mode)
    config.geometry.delta_levelset = delta
    if spatial:
        config.zones = ZoneInputConfig(enabled=True, axis='grid', grid={'cells': [
            dict(x0=0., x1=.65, y0=0., y1=.55, L=4.25, t=.33),
            dict(x0=.35, x1=.85, y0=.2, y1=.9, L=7.5, t=.54),
            dict(x0=0., x1=1., y0=.4, y1=.6, L=5.5, t=.42)]})
    return config


def _input(config, targets=None):
    values = native_preparation_abi._input_flow_3d(config, targets)
    values.input.geometry_mode = 2 if config.zones.enabled else 0
    rows = config.zones.grid['cells'] if config.zones.enabled else []
    cells = (_Cell * len(rows))()
    for index, row in enumerate(rows):
        cells[index].bounds[:] = [float(row[key]) for key in ('x0', 'x1', 'y0', 'y1')]
        cells[index].cell_length_mm, cells[index].wall_thickness_mm = float(row['L']), float(row['t'])
    source = _Input(4, ct.sizeof(_Input), values, cells, len(cells))
    source._values, source._cells = values, cells
    return source


def _call(native, operation, config, targets=None, *, source=None, chi=None, reject_event=False):
    source = _input(config, targets) if source is None else source
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(4, ct.sizeof(result_type))
    failure = abi._Failure(2, ct.sizeof(abi._Failure))
    options = abi._Options(1, ct.sizeof(abi._Options), chi is not None, config.extrap.allow, chi or 0.)
    error, events = ct.create_string_buffer(4096), []

    def event(_context, pointer):
        item = pointer.contents
        events.append((item.kind, read_text(item.logger), read_text(item.message), item.floating_event))
        return int(reject_event)

    callback = abi._EventFunction(event)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), callback, None)
    buffers = source._values._source._buffers
    before = bytes(source), bytes(source._cells), [bytes(buffer) for buffer in buffers]
    status = getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error))
    assert (bytes(source), bytes(source._cells), [bytes(buffer) for buffer in buffers]) == before
    return status, result, failure, error.value.decode(), events, source


def _release(native, result):
    name = 'case' if isinstance(result, _Result) else 'flow'
    release = getattr(native, 'tpmshx_preparation_spatial_' + name + '_3d_release_v4')
    release(ct.byref(result))
    assert not result.owner
    release(ct.byref(result))


def _snapshot(result, config):
    rows = config.zones.grid['cells'] if config.zones.enabled else []
    assert result.cell_count == len(rows)
    for index, row in enumerate(rows):
        actual = result.cells[index]
        native_preparation_abi._same(actual.bounds, [float(row[key]) for key in ('x0', 'x1', 'y0', 'y1')],
            'owned bounds ' + str(index))
        native_preparation_abi._same([actual.cell_length_mm, actual.wall_thickness_mm],
            [float(row['L']), float(row['t'])], 'owned rectangle ' + str(index))


def _full(native, config, targets=None, *, chi=None):
    before = deepcopy(asdict(config))
    status, result, failure, error, live, source = _call(
        native, 'prepare_flow_case', config, targets, chi=chi)
    assert status == 0, error
    try:
        assert result.owner and not result.prepared.owner and not result.flow.owner and not failure.kind
        _snapshot(result, config)
        if source.cell_count:
            source._cells[0].cell_length_mm = -1.
            source._cells[0].bounds[0] = -1.
        source.values.input.cell_length_mm = -1.
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        _snapshot(result, config)
        assert result.prepared.input.cell_length_mm == float(config.geometry.L_cell_mm)
        lengths = (float(config.geometry.L_dom_m), float(config.geometry.H_dom_m), float(config.geometry.Lz_m))
        widths = [copy_array(result.prepared.widths[i]) for i in range(3)]
        shape = tuple(w.size for w in widths)
        for w, length in zip(widths, lengths):
            assert np.all(w > 0.) and w.sum() == pytest.approx(length, rel=1e-12)
        L_field = copy_array(result.prepared.cell_length, shape)
        t_field = copy_array(result.prepared.wall_thickness, shape)
        eps_arr = copy_array(result.prepared.total_porosity, shape)
        eps_A = copy_array(result.prepared.side_porosity, shape)
        eps_B = copy_array(result.side_b_porosity, shape)
        K_m2 = copy_array(result.prepared.permeability, shape)
        cF_per_m = copy_array(result.prepared.forchheimer, shape)
        for arr in (L_field, t_field, eps_arr, eps_A, eps_B, K_m2, cF_per_m):
            assert np.all(np.isfinite(arr))
        np.testing.assert_allclose(eps_A + eps_B, eps_arr, rtol=1e-14, atol=1e-14)
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
        delta = float(config.geometry.delta_levelset)
        assert bool(result.have_side_geometry) == (delta != 0.)
        if delta == 0.:
            assert result.split_a == .5
        elif delta > 0.:
            assert result.split_a > .5
        else:
            assert result.split_a < .5
        for name in ('area_density_per_m', 'hydraulic_diameter_m', 'thermal_porosity'):
            if not config.zones.enabled:
                assert getattr(result, name).size == 0
            else:
                values = copy_array(getattr(result, name), shape)
                assert np.all(np.isfinite(values)) and np.all(values > 0.)
        address_a = ct.cast(result.prepared.side_porosity.data, ct.c_void_p).value
        address_b = ct.cast(result.side_b_porosity.data, ct.c_void_p).value
        assert (address_a == address_b) == (delta == 0.)
        assert result.side_b_porosity.size == result.prepared.side_porosity.size
        summary = dict(widths=widths, L_field=L_field, t_field=t_field, eps_arr=eps_arr,
            eps_A=eps_A, eps_B=eps_B, K_m2=K_m2, cF_per_m=cF_per_m, split_a=result.split_a,
            have_side_geometry=bool(result.have_side_geometry),
            speeds=tuple(result.flow.speeds), events=live)
    finally:
        _release(native, result)
    assert asdict(config) == before
    return summary


def _query(native, operation, config, targets=None):
    before = deepcopy(asdict(config))
    status, result, failure, error, live, source = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.owner and not result.flow.owner and not failure.kind
        _snapshot(result, config)
        if source.cell_count:
            source._cells[0].cell_length_mm = -1.
        _snapshot(result, config)
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
    assert asdict(config) == before
    return out, live


def _failure(native, operation, config, targets=None, *, source=None, expected_kind=None):
    status, result, failure, error, _, _ = _call(native, operation, config, targets, source=source)
    assert status != 0 and error
    if expected_kind is not None:
        assert failure.kind == expected_kind
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))
    _release(native, result)
    return error, failure.kind


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water'), repeat=2)))
@pytest.mark.parametrize('spatial', [False, True], ids=['uniform', 'grid'])
@pytest.mark.parametrize('delta', [0., .12])
def test_spatial_3d_fields_satisfy_invariants(native, topology, pair, spatial, delta):
    _full(native, _configuration(topology, pair, spatial=spatial, delta=delta))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('spatial', [False, True])
def test_spatial_3d_negative_offset_keeps_both_global_surfaces(native, topology, spatial):
    config = _configuration(topology, spatial=spatial, delta=-.12)
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.25, .45
    summary = _full(native, config)
    assert summary['split_a'] < .5
    assert np.all(summary['eps_A'] < summary['eps_B'])


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('delta', [-.12, .12])
def test_spatial_3d_explicit_capacity_resolve_and_full(native, topology, spatial, delta):
    config = _configuration(topology, spatial=spatial, delta=delta)
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    stale = replace(config, fluid_A=replace(config.fluid_A, u_mps=-99., mass_flow_kg_s=.9),
        fluid_B=replace(config.fluid_B, u_mps=-88., mass_flow_kg_s=.8))
    speeds, _ = _query(native, 'resolve_inlet_flow', stale, targets)
    summary = _full(native, stale, targets)
    assert speeds[0] == pytest.approx(config.fluid_A.u_mps, rel=1e-13)
    assert speeds[1] == pytest.approx(config.fluid_B.u_mps, rel=1e-13)
    assert summary['speeds'] == speeds


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('sides', [('A',), ('B',), ('A', 'B')])
def test_spatial_3d_configured_and_mixed_flow_ports(native, direction, sides):
    config = _configuration(delta=.12 if direction % 2 else -.12)
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


@pytest.mark.parametrize('direction,delta', [(0, 0.), (5, .12)])
def test_spatial_3d_uses_actual_refined_xy_centres(native, direction, delta):
    config = _configuration(delta=delta)
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
    for key in ('L_field', 't_field', 'eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m'):
        values = summary[key]
        native_preparation_abi._same(values, np.repeat(values[:, :, :1], values.shape[2], axis=2), key + ' extrusion')


@pytest.mark.parametrize('selection', ['gaps', 'reverse-overlap', 'no-hit', 'overwritten-nan', 'overwritten-domain'])
def test_spatial_3d_rectangle_defaults_and_late_overwrite(native, selection):
    config = _configuration(delta=0.)
    rows = config.zones.grid['cells']
    if selection == 'gaps':
        del rows[1:]
    elif selection == 'reverse-overlap':
        rows.reverse()
    elif selection == 'no-hit':
        rows.append(dict(x0=0., x1=.001, y0=0., y1=1., L=float('nan'), t=float('nan')))
    else:
        value = float('nan') if selection == 'overwritten-nan' else 9.
        rows[:] = [dict(x0=0., x1=1., y0=0., y1=1., L=value, t=.4),
                   dict(x0=0., x1=1., y0=0., y1=1., L=6.25, t=.45)]
    _full(native, config)


def test_spatial_3d_only_smoothed_local_values_enter_the_cfd_table(native):
    config = _configuration(delta=0.)
    config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=0., y1=1., L=6., t=.4),
        dict(x0=0., x1=.1, y0=0., y1=.11, L=9., t=.4)]
    summary = _full(native, config)
    assert np.all((summary['L_field'] >= .004) & (summary['L_field'] <= .008))


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_spatial_3d_normalizes_rectangle_bounds_to_float64(native, dtype):
    def make_config(cast):
        config = _configuration(delta=0.)
        for row in config.zones.grid['cells']:
            for key in ('x0', 'x1', 'y0', 'y1'):
                row[key] = cast(row[key])
            row['L'], row['t'] = cast(row['L']), cast(row['t'])
        return config

    actual = _full(native, make_config(dtype))
    expected = _full(native, make_config(lambda v: float(dtype(v))))
    native_preparation_abi._same(actual['L_field'], expected['L_field'], 'normalized L_field')
    native_preparation_abi._same(actual['eps_arr'], expected['eps_arr'], 'normalized eps_arr')


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'material-array', 'inlet', 'grid-port'])
def test_spatial_3d_normalizes_nominal_and_grid_scalars(native, dtype, selection):
    def make_config(cast):
        config = _configuration('Diamond')
        if selection == 'geometry':
            config.geometry.L_cell_mm, config.geometry.t_wall_mm = cast(6.125), cast(.42)
        elif selection == 'material-array':
            config.geometry.k_s_W_mK = np.asarray(cast(1.337))
        elif selection == 'inlet':
            config.fluid_A.u_mps, config.fluid_A.T_in_K = cast(5.125), cast(351.13)
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
    native_preparation_abi._same(actual['eps_arr'], expected['eps_arr'], 'normalized eps_arr')


@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_spatial_3d_target_types(native, dtype, array):
    config = _configuration(spatial=False)
    values = (1, 2) if dtype is np.int16 else (.003, .03)
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value) for value in values)
    _query(native, 'resolve_inlet_flow', config, targets)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_spatial_3d_uniform_core_air_experiment_keeps_nonzero_offset(native, topology):
    config = _configuration(topology, ('air', 'air'), spatial=False, mode='experimental')
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.5, .4
    _full(native, config)
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config)
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    _full(native, config, targets)


def test_spatial_3d_hx_capacity_precedes_delta_application_rejection(native):
    config = _configuration(spatial=False, mode='experimental')
    speeds = config.fluid_A.u_mps, config.fluid_B.u_mps
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., float('nan')
    capacities, _ = _query(native, 'prepare_inlet_mass_capacities', config, (-1., float('nan')))
    targets = tuple(capacities[side] * speed for side, speed in zip('AB', speeds))
    for operation in ('resolve_inlet_flow', 'prepare_flow_case'):
        error, kind = _failure(native, operation, config, targets)
        assert kind == 1 and 'requires delta=0' in error


@pytest.mark.parametrize('delta', [-0., 0.])
def test_spatial_3d_zero_offset_keeps_alias_and_no_side_geometry(native, delta):
    summary = _full(native, _configuration(delta=delta))
    assert not summary['have_side_geometry']
    assert summary['split_a'] == .5


@pytest.mark.parametrize('operation', ['prepare_inlet_mass_capacities', 'resolve_inlet_flow'])
def test_spatial_3d_query_emits_out_of_range_evidence(native, operation):
    from sjtu_tpmshx.physical_models import tpms_props
    config = _configuration(delta=0.)
    config.fluid_A.T_in_K = min(tpms_props._AIR_T_RANGE[0], tpms_props._AIR_CP_RANGE[0]) - 10.
    targets = (.003, .03) if operation == 'resolve_inlet_flow' else None
    status, result, _, error, _, _ = _call(native, operation, config, targets)
    assert status == 0, error
    try:
        assert result.flow.evidence.range_count > 0
        assert result.flow.evidence.warning_count > 0
    finally:
        _release(native, result)


def test_spatial_3d_no_target_resolution_keeps_unvalidated_owned_input(native):
    config = _configuration()
    config.fluid_A.T_in_K = -1.
    config.zones.grid['cells'][0]['x1'] = -1.
    config.sco2_nu = replace(config.sco2_nu, source='retained spatial source')
    status, result, failure, error, live, source = _call(native, 'resolve_inlet_flow', config)
    assert status == 0, error
    try:
        assert not failure.kind and not result.flow.have_capacities and not live
        assert result.flow.evidence.range_count == result.flow.evidence.warning_count == result.flow.evidence.event_count == 0
        for name, _ in native_preparation_abi._Input_3d._fields_:
            if name != 'sco2_nu':
                assert native_preparation_abi._struct_values(getattr(result.flow.input, name)) == native_preparation_abi._struct_values(getattr(source.values.input, name))
        source._cells[0].bounds[0] = -5.
        source._cells[0].cell_length_mm = -1.
        _snapshot(result, config)
        for buffer in source._values._source._buffers:
            if len(buffer) > 1:
                buffer[0] = b'X'
        assert read_text(result.flow.input.sco2_nu.source) == config.sco2_nu.source
    finally:
        _release(native, result)


def _entry(config, entry):
    if entry == 'capacity':
        return 'prepare_inlet_mass_capacities', None
    if entry == 'prescribed':
        return 'prepare_flow_case', None
    if entry == 'configured':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .003, .03
        return 'prepare_flow_case', None
    return ('resolve_inlet_flow' if entry == 'resolve' else 'prepare_flow_case'), (.003, .03)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed', 'configured'])
@pytest.mark.parametrize('selection', ['empty', 'rectangle-x', 'rectangle-y-before-next-x',
    'nominal', 'local-nan', 'local-length', 'local-wall', 'local-pore', 'local-df',
    'water-before-local', 'experimental-grid', 'experimental-water', 'experimental-speed',
    'sco2-grid', 'sco2-temperature', 'sco2-delta', 'co2-grid', 'co2-delta',
    'sco2-before-co2', 'local-before-delta', 'delta-before-df'])
def test_spatial_3d_first_failure_is_atomic(native, entry, selection):
    config = _configuration()
    operation, targets = _entry(config, entry)
    rows = config.zones.grid['cells']
    if selection == 'empty': rows.clear()
    elif selection == 'rectangle-x':
        rows[0]['x1'], config.geometry.L_cell_mm, config.fluid_B.T_in_K = -1., -1., 500.
    elif selection == 'rectangle-y-before-next-x': rows[0]['y1'], rows[1]['x1'] = -1., -1.
    elif selection == 'nominal': config.geometry.L_cell_mm = 3.
    elif selection.startswith('local-') or selection == 'delta-before-df':
        length, wall = {
            'local-nan': (float('nan'), -.4), 'local-length': (-1., .4),
            'local-wall': (6., -.4), 'local-pore': (.5, .3), 'local-df': (9., .4),
            'local-before-delta': (float('nan'), .4), 'delta-before-df': (9., .4),
        }[selection]
        rows[:] = [dict(x0=0., x1=1., y0=0., y1=1., L=length, t=wall)]
        if selection in ('local-before-delta', 'delta-before-df'):
            config.geometry.delta_levelset = float('nan')
    elif selection == 'water-before-local':
        config.fluid_B.T_in_K, rows[0]['L'] = 500., float('nan')
    elif selection.startswith('experimental-'):
        config.df_mode = 'experimental'
        if selection == 'experimental-water': config.fluid_B.T_in_K = 500.
        if selection == 'experimental-speed': config.fluid_A.u_mps = -1.
    else:
        config.fluid_A.type, config.fluid_A.T_in_K, config.fluid_A.P_in_Pa = (
            'sco2' if selection.startswith('sco2') else 'co2', 400., 8e6)
        if selection.endswith('-delta'): config.zones.enabled = False
        if selection == 'sco2-temperature': config.fluid_A.T_in_K = 250.
        if selection == 'sco2-before-co2':
            config.fluid_A.type = 'co2'
            config.fluid_B.type, config.fluid_B.T_in_K, config.fluid_B.P_in_Pa = 'sco2', 250., 8e6
    _, kind = _failure(native, operation, config, targets)
    assert kind in ((1, 2) if selection in ('water-before-local', 'experimental-water')
                    else (1, 3) if selection == 'delta-before-df' else (1,))


@pytest.mark.parametrize('entry', ['resolve', 'fixed', 'configured'])
def test_spatial_3d_target_and_rectangle_failure_priority(native, entry):
    config = _configuration()
    operation, targets = _entry(config, entry)
    config.zones.grid['cells'][0]['x1'] = -1.
    if entry == 'configured':
        config.fluid_A.mass_flow_kg_s = -1.
    else:
        targets = (float('nan'), .03)
    _failure(native, operation, config, targets, expected_kind=1)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed'])
def test_spatial_3d_nominal_preflight_and_local_df_failure_priority(native, entry):
    config = _configuration(delta=0.)
    config.extrap.allow, config.fluid_A.u_mps = False, 1e-20
    config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=0., y1=1., L=9., t=.4)]
    operation, targets = _entry(config, entry)
    _failure(native, operation, config, targets, expected_kind=1)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
def test_spatial_3d_discrete_fluid_rejection_on_each_side(native, side, fluid):
    config = _configuration()
    inlet = getattr(config, 'fluid_' + side)
    inlet.type, inlet.T_in_K, inlet.P_in_Pa = fluid, 400., 8e6
    _failure(native, 'prepare_flow_case', config, expected_kind=1)


@pytest.mark.parametrize('delta', [-100., 100.])
def test_spatial_3d_closed_side_reaches_capacity_boundary(native, delta):
    config = _configuration(delta=delta)
    summary = _full(native, config)
    assert summary['split_a'] == (1. if delta > 0 else 0.)
    error, kind = _failure(native, 'prepare_inlet_mass_capacities', config)
    assert kind == 1 and 'inlet density times open pore area' in error


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_3d_callback_failure_keeps_output(native, operation):
    config = _configuration(delta=0.)
    config.fluid_A.T_in_K = np.float64(1e308)
    status, result, failure, error, events, _ = _call(
        native, operation, config, (.003, .03), reject_event=True)
    assert status != 0 and error and failure.kind == 3
    assert len(events) == 1
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['cells-output', 'cells-failure', 'cells-error',
    'source-output', 'source-error', 'output-error', 'failure-error', 'text-output'])
def test_spatial_3d_overlapping_storage_is_unchanged(native, operation, selection):
    source = _input(_configuration(delta=0.), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result, failure = result_type(4, ct.sizeof(result_type)), abi._Failure(2, ct.sizeof(abi._Failure))
    error = ct.create_string_buffer(b'unchanged', 4096)
    result_pointer, error_pointer, capacity = ct.pointer(result), error, len(error)
    if selection.startswith('cells-'):
        target = {'cells-output': result, 'cells-failure': failure, 'cells-error': error}[selection]
        source.cells, source.cell_count = ct.cast(ct.pointer(target), ct.POINTER(_Cell)), 1
    elif selection.endswith('-error'):
        target = {'source-error': source, 'output-error': result, 'failure-error': failure}[selection]
        error_pointer, capacity = ct.cast(ct.byref(target, 8), ct.POINTER(ct.c_char)), 16
    elif selection == 'source-output':
        result_pointer = ct.cast(ct.pointer(source), ct.POINTER(result_type))
    else:
        source.values.input.sco2_nu.source = abi._Text(ct.cast(ct.pointer(result), ct.POINTER(ct.c_char)), 16)
    objects = (source, result, failure, error)
    before = [bytes(value) for value in objects]
    assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), None, None, result_pointer, ct.byref(failure), error_pointer, capacity) != 0
    assert [bytes(value) for value in objects] == before


@pytest.mark.parametrize('operation', _OPERATIONS)
def test_spatial_3d_owned_result_requires_release(native, operation):
    config = _configuration(delta=0.)
    status, result, failure, error, _, source = _call(native, operation, config, (.003, .03))
    assert status == 0, error
    before = bytes(result)
    error = ct.create_string_buffer(4096)
    try:
        assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
            ct.byref(source), None, None, ct.byref(result), ct.byref(failure), error, len(error)) != 0
        assert 'release' in error.value.decode() and bytes(result) == before
        _snapshot(result, config)
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('record', ['input', 'values', 'case', 'result', 'options', 'callbacks', 'failure'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_spatial_3d_rejects_incompatible_records(native, operation, record, field):
    source = _input(_configuration(delta=0.), (.003, .03))
    result_type = _Result if operation == 'prepare_flow_case' else _Flow
    result = result_type(4, ct.sizeof(result_type))
    failure, error = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096)
    options = abi._Options(1, ct.sizeof(abi._Options), 0, 1, 0.)
    callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks))
    selected = {'input': source, 'values': source.values, 'case': source.values.input,
        'result': result, 'options': options, 'callbacks': callbacks, 'failure': failure}[record]
    setattr(selected, field, 99 if field == 'abi_version' else 1)
    before = bytes(result)
    assert getattr(native, 'tpmshx_' + operation + '_3d_v4')(
        ct.byref(source), ct.byref(options), ct.byref(callbacks), ct.byref(result),
        ct.byref(failure), error, len(error)) != 0
    assert error.value and bytes(result) == before


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('spatial', [False, True])
def test_spatial_3d_typed_grid_keeps_exact_width_coverage(native, dtype, spatial):
    config = _configuration(spatial=spatial, delta=0.)
    config.solver.Nx = config.solver.Ny = config.solver.Nz = 4
    config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m = map(dtype, (.081, .063, .047))
    _full(native, config)


@pytest.mark.parametrize('entry', ['prescribed', 'capacity', 'resolve', 'fixed'])
@pytest.mark.parametrize('selection', ['local-nan', 'delta-nan'])
def test_spatial_3d_grid_cap_precedes_local_geometry_and_offset(native, monkeypatch, entry, selection):
    config = _configuration()
    if selection == 'local-nan':
        config.zones.grid['cells'][0]['L'] = float('nan')
    else:
        config.geometry.delta_levelset = float('nan')
    operation, targets = _entry(config, entry)
    source = _input(config, targets)
    source.values.input.max_cells = 119
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '119')
    error, kind = _failure(native, operation, config, targets, source=source)
    assert kind == 1 and error == '3D grid 6x5x4 exceeds the 119-cell cap'


@pytest.mark.parametrize('operation', _OPERATIONS)
@pytest.mark.parametrize('selection', ['missing-cells', 'uniform-cells', 'continuous-mode'])
def test_spatial_3d_rejects_invalid_raw_transport(native, operation, selection):
    config = _configuration(delta=0.)
    source = _input(config, (.003, .03))
    if selection == 'missing-cells':
        source.cells = ct.POINTER(_Cell)()
    elif selection == 'uniform-cells':
        source.values.input.geometry_mode = 0
    else:
        source.values.input.geometry_mode = 1
    status, result, failure, error, events, _ = _call(native, operation, config,
        (.003, .03), source=source)
    assert status != 0 and not events
    if selection == 'missing-cells':
        assert not error and not failure.kind
    else:
        assert error and failure.kind == 1
    assert bytes(result) == bytes(type(result)(4, ct.sizeof(result)))
    _release(native, result)


@pytest.mark.parametrize('operation,targets', native_preparation_abi._OWNED_FLOW_CASES)
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('spatial,invalid', [pytest.param(True, invalid, id='grid-' + invalid)
    for invalid in ('none', 'source_abi', 'source_size', 'values_abi', 'values_size',
                    'input_abi', 'input_size', 'result_abi', 'result_size')]
    + [pytest.param(False, 'none', id='uniform-none')])
def test_spatial_3d_owned_views_reject_diagnostic_aliases(native, operation, targets, destination, spatial, invalid):
    from tests.python.native_preparation_abi import _check_owned_aliases

    config = _configuration(spatial=spatial, delta=.12 if spatial else 0.)
    config.sco2_nu = replace(config.sco2_nu, parameter_version='saved version',
                            source='saved source', applicability='saved range')
    if not targets:
        config.fluid_A.T_in_K = -1.
        if spatial:
            config.zones.grid['cells'][0]['x1'] = -1.
    status, result, _, error, _, source = _call(native, operation, config, (.003, .03) if targets else None)
    assert status == 0, error
    target = (source.values.input if invalid.startswith('input') else source.values
        if invalid.startswith('values') else source if invalid.startswith('source') else result)
    if invalid != 'none':
        setattr(target, 'abi_version' if invalid.endswith('abi') else 'struct_size', 0)
    before = bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]
    try:
        labels = _check_owned_aliases(lambda failure, error, capacity:
            getattr(native, 'tpmshx_' + operation + '_3d_v4')(ct.byref(source), None, None,
                ct.byref(result), ct.cast(failure, ct.POINTER(abi._Failure)), error, capacity), result, destination)
        assert ('result.cells' in labels) == spatial
        assert result.cell_count == (len(config.zones.grid['cells']) if spatial else 0)
        assert bool(result.cells) == spatial
        for name in ('parameter_version', 'source', 'applicability'):
            assert 'result.flow.input.sco2_nu.' + name in labels
        assert not result.flow.owner
        if targets:
            assert any('.flow.evidence.ranges' in label for label in labels)
        else:
            assert result.flow.evidence.range_count == result.flow.evidence.warning_count == result.flow.evidence.event_count == 0
        if operation == 'prepare_flow_case':
            assert not result.prepared.owner
            for name in ('prepared.permeability', 'side_b_porosity'):
                assert 'result.' + name in labels
            for name in ('area_density_per_m', 'hydraulic_diameter_m', 'thermal_porosity'):
                assert ('result.' + name in labels) == spatial
                assert bool(getattr(result, name).data) == spatial
                assert bool(getattr(result, name).size) == spatial
            address_a = ct.cast(result.prepared.side_porosity.data, ct.c_void_p).value
            address_b = ct.cast(result.side_b_porosity.data, ct.c_void_p).value
            assert (address_a == address_b) == (not spatial)
        assert (bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]) == before
    finally:
        _release(native, result)


@pytest.mark.parametrize('operation,targets', native_preparation_abi._OWNED_FLOW_CASES)
@pytest.mark.parametrize('spatial', [True, False], ids=['grid-offset', 'uniform-zero'])
def test_spatial_3d_owned_output_keeps_safe_reuse_diagnostics(native, operation, targets, spatial):
    from tests.python.native_preparation_abi import _visible_buffers

    config = _configuration(spatial=spatial, delta=.12 if spatial else 0.)
    config.sco2_nu = replace(config.sco2_nu, parameter_version='saved version',
                            source='saved source', applicability='saved range')
    if not targets:
        config.fluid_A.T_in_K = -1.
        if spatial:
            config.zones.grid['cells'][0]['x1'] = -1.
    status, result, _, error, _, source = _call(native, operation, config, (.003, .03) if targets else None)
    assert status == 0, error
    source_before = bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]
    try:
        outer = bytes(result)
        before = [(label, pointer, ct.string_at(pointer, size)) for label, pointer, size in _visible_buffers(result)]
        failure, error, events = abi._Failure(2, ct.sizeof(abi._Failure)), ct.create_string_buffer(4096), []
        event = abi._EventFunction(lambda context, pointer: events.append(1) or 0)
        callbacks = abi._Callbacks(1, ct.sizeof(abi._Callbacks), event, None)
        status = getattr(native, 'tpmshx_' + operation + '_3d_v4')(ct.byref(source), None,
            ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
        assert status == 1 and failure.kind == 1
        assert error.value == b'release the previous prepared case before reusing its result'
        assert not events and bytes(result) == outer
        assert before
        for label, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, label
        assert (bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]) == source_before
    finally:
        _release(native, result)


@pytest.mark.parametrize('view', ['cells', 'side_b_porosity', 'area_density_per_m'])
def test_spatial_3d_owned_spatial_views_reject_error_aliases(native, view):
    from tests.python.native_preparation_abi import _visible_buffers

    config = _configuration()
    config.sco2_nu = replace(config.sco2_nu, parameter_version='saved version',
                            source='saved source', applicability='saved range')
    status, result, _, error, _, source = _call(native, 'prepare_flow_case', config, (.003, .03))
    assert status == 0, error
    source_before = bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]
    try:
        outer = bytes(result)
        before = [(label, pointer, ct.string_at(pointer, size)) for label, pointer, size in _visible_buffers(result)]
        address, saved = next((pointer, saved) for label, pointer, saved in before if label == 'result.' + view)
        address += next(index for index, value in enumerate(saved) if value)
        failure = abi._Failure(2, ct.sizeof(abi._Failure))
        failure_before = bytes(failure)
        status = native.tpmshx_prepare_flow_case_3d_v4(ct.byref(source), None, None,
            ct.byref(result), ct.byref(failure), ct.cast(address, ct.POINTER(ct.c_char)), 1)
        assert status == 1 and bytes(result) == outer
        for label, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, label
        assert bytes(failure) == failure_before
        assert (bytes(source), bytes(source._cells), [bytes(buffer) for buffer in source._values._source._buffers]) == source_before
    finally:
        _release(native, result)
