"""Shared ctypes layouts, configurations and checks for the native preparation ABI tests."""
import ctypes as ct
import warnings

import numpy as np

from sjtu_tpmshx.cpp_interface import _native_grid as grid
from sjtu_tpmshx.cpp_interface import _native_preparation_3d as three
from sjtu_tpmshx.cpp_interface import _native_preparation_case as abi
from sjtu_tpmshx.cpp_interface._native_values import GridPort, read_text
from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, PartialBCConfig, ZoneInputConfig
from sjtu_tpmshx.run_control.run_warnings import range_observations, warning_messages
from tests.python.solver_tm1.test_prepared_zoned_thermal_2d import _config


_library_path = preparation_library.path
_U, _S, _D = ct.c_uint32, ct.c_size_t, ct.c_double


def _structure(name, fields):
    return type(name, (ct.Structure,), {'_fields_': fields})


_Array = _structure('Array', [('data', ct.POINTER(_D)), ('size', _S)])
_Text = _structure('Text', [('data', ct.POINTER(ct.c_char)), ('size', _S)])


def _text(value):
    return ct.string_at(value.data, value.size).decode()


def _array(value):
    return np.ctypeslib.as_array(value.data, shape=(value.size,)).copy() if value.size else np.array([], dtype=float)


def _same(actual, expected, name):
    actual = np.asarray(actual, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    assert actual.shape == expected.shape, name
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)


def _struct_values(value):
    if isinstance(value, ct.Structure):
        return {name: _struct_values(getattr(value, name)) for name, _ in value._fields_}
    if isinstance(value, ct.Array):
        return [_struct_values(item) for item in value]
    return value.hex() if isinstance(value, float) else value


def _range(value, *, last=False):
    shape = tuple(value.shape[index] for index in range(value.rank))
    sample = value.last if last else value.sample

    def extreme(name):
        if not sample.have_finite:
            return None
        flat = getattr(sample, name + '_index')
        index = tuple(int(item) for item in np.unravel_index(flat, shape)) if shape else ()
        return getattr(sample, name), index

    return {'source': tuple(_text(value.source[index]) for index in range(value.source_count)),
        **{name: _text(getattr(value, name)) for name in ('side', 'stage', 'layout', 'quantity', 'unit')},
        'shape': shape, 'bounds': tuple(value.bounds), 'captured': True,
        'minimum': extreme('minimum'), 'maximum': extreme('maximum'),
        **{name: getattr(sample, name) for name in ('low', 'high', 'size', 'nonfinite')}}


_Nu = abi._Nu
_Cause = abi._Cause
_Failure = abi._Failure
_Drag = abi._ContinuousDrag


def _configuration_fluids(topology, pair, mode='cfd_smooth'):
    config = ComputeConfig()
    config.solver.Nx, config.solver.Ny = 6, 8
    config.geometry.tpms = topology
    config.bc_B.dir = 3
    config.extrap.allow = True
    config.df_mode = mode
    states = {'air': (350., 200000., 6.), 'water': (320., 200000., .02), 'sco2': (400., 8e6, .15), 'co2': (400., 8e6, .15)}
    for index, side in enumerate('AB'):
        fluid = getattr(config, 'fluid_' + side)
        fluid.type = pair[index]
        fluid.T_in_K, fluid.P_in_Pa, fluid.u_mps = states[fluid.type]
    if mode == 'experimental':
        from sjtu_tpmshx.model_configs.model_parameters import load_preparation_df_parameters
        data = load_preparation_df_parameters()['hx']
        for side in 'AB':
            fluid = getattr(config, 'fluid_' + side)
            if fluid.type != 'co2':
                bounds = data['application_u_mps'][fluid.type][topology]
                fluid.u_mps = sum(bounds) / 2.
    return config


def _error_kind(error):
    if type(error).__name__ == 'WaterStateError':
        return 2
    return 1 if isinstance(error, ValueError) else 3


def _events(evidence):
    return [(item.kind, _text(item.logger), _text(item.message), item.floating_event)
            for item in evidence.events[:evidence.event_count]]


def _configuration_mass_flow(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = _configuration_fluids(topology, pair, mode)
    config.geometry.Lz_m = .042
    return config


def _configuration_continuous(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth', *, nx=4, ny=5, mirror=True, order=3):
    config = _configuration_mass_flow(topology, pair, mode)
    count = nx * ((ny + 1) // 2 if mirror else ny)
    spec = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=mirror, spline_order=order,
        L_bounds=[4., 8.], t_bounds=[.3, .6],
        x_decision=[float(value) for value in np.r_[np.linspace(4.2, 7.8, count), np.linspace(.57, .32, count)]])
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    return config


def _host_events(events):
    from sjtu_tpmshx.cpp_interface._native_properties import _floating_events
    result = []
    for event in events:
        if event[0] != 2:
            result.append(event)
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _floating_events([event[3]])
        result.extend((1, '', str(item.message), 0) for item in caught)
    return result


def _visible_buffers(value, path='result'):
    """Enumerate public views without using the native owner's private layout."""
    counts = {'ranges': 'range_count', 'warnings': 'warning_count',
              'events': 'event_count', 'source': 'source_count', 'shape': 'rank',
              'notices': 'notice_count', 'calibration': 'calibration_count',
              'regions': 'region_count', 'zone_id': 'cell_count', 'cells': 'cell_count'}
    if [name for name, _ in getattr(value, '_fields_', ())] == ['data', 'size']:
        if value.size:
            yield path, ct.cast(value.data, ct.c_void_p).value, value.size * ct.sizeof(value.data._type_)
    elif isinstance(value, ct.Structure):
        for name, field in value._fields_:
            item, label = getattr(value, name), path + '.' + name
            if issubclass(field, ct._Pointer):
                if name == 'range_bounds_list':
                    size = getattr(value, 'values', value).range_count
                else:
                    assert name in counts, label
                    size = getattr(value, counts[name])
                if size:
                    yield label, ct.cast(item, ct.c_void_p).value, size * ct.sizeof(field._type_)
                    if issubclass(field._type_, ct.Structure):
                        for index in range(size):
                            yield from _visible_buffers(item[index], f'{label}[{index}]')
            elif isinstance(item, (ct.Structure, ct.Array)):
                yield from _visible_buffers(item, label)
    elif isinstance(value, ct.Array):
        for index, item in enumerate(value):
            yield from _visible_buffers(item, f'{path}[{index}]')


def _check_owned_aliases(call, result, destination):
    buffers = list(_visible_buffers(result))
    assert buffers
    before = [(label, address, ct.string_at(address, size)) for label, address, size in buffers]
    outer = bytes(result)
    for label, address, saved in before:
        failure = _Failure(2, ct.sizeof(_Failure))
        error = ct.create_string_buffer(b'unchanged', 4096)
        failure_before, error_before = bytes(failure), bytes(error)
        failure_pointer = ct.cast(address, ct.POINTER(_Failure)) if destination == 'failure' else ct.byref(failure)
        error_pointer, capacity = error, len(error)
        if destination == 'error':
            offset = next((index for index, byte in enumerate(saved) if byte), None)
            error_pointer = ct.cast(address + (offset or 0), ct.POINTER(ct.c_char))
            capacity = 1 if offset is not None else min(2, len(saved))
        status = call(failure_pointer, error_pointer, capacity)
        assert status == 1, label
        assert bytes(result) == outer, label
        assert bytes(failure) == failure_before and bytes(error) == error_before, label
        for name, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, (label, name)
    return [label for label, _, _ in buffers]


def _configuration_sigmoid(topology='Gyroid', *, constant=False):
    config = _config('grid')
    config.geometry.tpms = topology
    config.zones.config.tpms_type = topology
    config.zones.grid['tpms_type'] = topology
    lengths = np.full(18, 7.) if constant else np.linspace(5., 7.8, 18)
    walls = np.full(18, .4) if constant else np.linspace(.32, .58, 18)
    config.zones.pareto_x_decision = np.column_stack((lengths, walls)).ravel().tolist()
    return config


def _configuration_spatial(mode, topology='Gyroid'):
    config = _configuration_sigmoid(topology) if mode == 'sigmoid' else _config(mode)
    config.geometry.tpms = topology
    config.zones.config.tpms_type = topology
    config.zones.grid['tpms_type'] = topology
    config.geometry.Lz_m = .042
    return config


_visible_buffers_spatial = _visible_buffers


def _check_owned_aliases_spatial(call, result, destination):
    buffers = list(_visible_buffers(result))
    assert buffers
    before = [(label, address, ct.string_at(address, size)) for label, address, size in buffers]
    outer = bytes(result)
    for label, address, _ in buffers:
        failure = _Failure(2, ct.sizeof(_Failure))
        error = ct.create_string_buffer(b'unchanged', 4096)
        failure_before, error_before = bytes(failure), bytes(error)
        failure_pointer = ct.cast(address, ct.POINTER(_Failure)) if destination == 'failure' else ct.byref(failure)
        error_pointer = ct.cast(address, ct.POINTER(ct.c_char)) if destination == 'error' else error
        status = call(failure_pointer, error_pointer, 1 if destination == 'error' else len(error))
        assert status == 1, label
        assert bytes(result) == outer, label
        assert bytes(failure) == failure_before and bytes(error) == error_before, label
        for name, pointer, saved in before:
            assert ct.string_at(pointer, len(saved)) == saved, (label, name)
    return [label for label, _, _ in buffers]


_Inlet = three._Inlet
_Input_3d = three._Input
_Side = three._Side
_Result = three._Result
_Input_flow_3d = three._FlowInput
_Flow = three._Flow


def _input_3d(config):
    geometry = config.geometry
    source = _Input_3d(1, ct.sizeof(_Input_3d))
    source.lengths_m[:] = (float(geometry.L_dom_m), float(geometry.H_dom_m), float(geometry.Lz_m))
    source.counts[:] = (config.solver.Nx, config.solver.Ny, config.solver.Nz)
    source.max_cells, source.port_wall_refine = 2_000_000, config.flags.port_wall_refine
    source.topology = ('Diamond', 'Gyroid').index(geometry.tpms)
    source.cell_length_mm, source.wall_thickness_mm = float(geometry.L_cell_mm), float(geometry.t_wall_mm)
    source.solid_conductivity_W_mK, source.delta_levelset = float(geometry.k_s_W_mK), float(geometry.delta_levelset)
    source.geometry_mode, source.df_mode = int(config.zones.enabled), int(config.df_mode == 'experimental')
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        raw_port = GridPort(port.dir, 1)
        raw_port.set_windows(lambda key: getattr(port, key), full_width=port.in_w <= 0. and port.out_w <= 0.)
        source.sides[index] = _Inlet(abi._FLUIDS.index(fluid.type), float(fluid.u_mps),
            float(fluid.T_in_K), float(fluid.P_in_Pa), raw_port,
            fluid.mass_flow_kg_s is not None, float(fluid.mass_flow_kg_s or 0.))
    settings = config.sco2_nu
    source.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(settings, name)
        source.sco2_nu.have_alpha[index], source.sco2_nu.alpha[index] = value is not None, float(value or 0.)
    source._buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        buffer = ct.create_string_buffer(getattr(settings, name).encode('utf-8'))
        source._buffers.append(buffer)
        setattr(source.sco2_nu, name, abi._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(buffer.value)))
    return source


def _input_flow_3d(config, targets=None):
    source = _input_3d(config)
    result = _Input_flow_3d(2, ct.sizeof(_Input_flow_3d), source)
    result._source = source
    result.have_explicit_targets = targets is not None
    if targets is not None:
        result.explicit_targets_kg_s[:] = (float(targets[0]), float(targets[1]))
    return result


def _configuration_3d(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = _configuration_fluids(topology, pair, mode)
    config.geometry.Lz_m = .042
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    return config


def _partial_ports(config, direction, cross2=True):
    lengths = (config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m)
    for side, selected in (('A', direction), ('B', (direction + 3) % 6)):
        cross1, _, second, *_ = grid.axis_map(selected)
        span, depth = lengths[cross1], lengths[second]
        port = PartialBCConfig(dir=selected, in_ctr=.43 * span, in_w=.57 * span,
            out_ctr=.59 * span, out_w=.49 * span)
        if cross2:
            port.in_z_ctr, port.in_z_w = .44 * depth, .63 * depth
            port.out_z_ctr, port.out_z_w = .62 * depth, .45 * depth
        setattr(config, 'bc_' + side, port)


def _evidence(actual, records):
    for last in (False, True):
        rows = []
        for index in range(actual.range_count):
            row = _range(actual.ranges[index], last=last)
            if actual.range_bounds_list[index]:
                row['bounds'] = list(row['bounds'])
            rows.append(row)
        assert rows == range_observations(records, last=last)
    assert [read_text(item) for item in actual.warnings[:actual.warning_count]] == list(warning_messages(records))


def _resolved(actual, expected):
    for index, side in enumerate('AB'):
        inlet, fluid = actual.input.sides[index], getattr(expected, 'fluid_' + side)
        _same(inlet.velocity_m_s, fluid.u_mps, side + ' resolved speed')
        assert bool(inlet.have_mass_flow) == (fluid.mass_flow_kg_s is not None)
        if inlet.have_mass_flow:
            _same(inlet.mass_flow_kg_s, fluid.mass_flow_kg_s, side + ' stored target')
        _same(actual.speeds[index], fluid.u_mps, side + ' flow speed')


_OWNED_FLOW_CASES = [('prepare_inlet_mass_capacities', True), ('resolve_inlet_flow', True),
                     ('prepare_flow_case', True), ('resolve_inlet_flow', False)]
