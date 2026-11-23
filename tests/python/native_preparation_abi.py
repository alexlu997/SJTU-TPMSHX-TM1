"""Shared ctypes layouts, configurations and checks for the native preparation ABI tests."""
from contextlib import contextmanager, nullcontext
import ctypes as ct
import warnings

import numpy as np

from sjtu_tpmshx.cpp_interface import _native_flow
from sjtu_tpmshx.cpp_interface import _native_grid as grid
from sjtu_tpmshx.cpp_interface import _native_preparation_case as abi
from sjtu_tpmshx.cpp_interface._native_properties import _Failure as _PropertyFailure
from sjtu_tpmshx.cpp_interface._native_values import copy_array
from sjtu_tpmshx.cpp_interface._native_values import read_text
from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.data_types.compute_config import PartialBCConfig
from sjtu_tpmshx.data_types.compute_config import ZoneInputConfig
from sjtu_tpmshx.run_control.run_warnings import RangeRecord
from sjtu_tpmshx.run_control.run_warnings import current_warnings
from sjtu_tpmshx.run_control.run_warnings import range_observations
from sjtu_tpmshx.run_control.run_warnings import warning_messages
from sjtu_tpmshx.run_control.run_warnings import warning_scope
from tests.python import preparation_3d_reference as preparation
from tests.python import preparation_api_reference as api
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


_Kind = _structure('Kind', [(name, _U) for name in ('precision', 'strong', 'layout')])


_InletKinds = _structure('InletKinds', [(name, _Kind) for name in ('velocity', 'temperature', 'pressure')])


_Nu = _structure('Nu', [('mode', _U), ('have_alpha', _U * 2), ('alpha', _D * 2)] + [(name, _Text) for name in ('parameter_version', 'source', 'applicability')])


_Cause = _structure('Cause', [('kind', _U), ('message', ct.c_char * 4096)])


_Failure = _structure('Failure', [('abi_version', _U), ('struct_size', _S)] + [(name, _U) for name in ('kind', 'side', 'have_property', 'cause_count')] + [('property', _PropertyFailure), ('causes', _Cause * 2)])


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


def _scalar(actual, expected):
    _same(actual.value, expected, 'typed scalar')
    kind = _native_flow._scalar(expected)
    assert (actual.precision, actual.strong) == (kind.precision, kind.strong)


def _configuration_mass_flow(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = _configuration_fluids(topology, pair, mode)
    config.geometry.Lz_m = .042
    return config


_Drag = _structure('ContinuousDrag', [('transfer_policy', _Text),
    ('geometry_application', _Text), ('have_reference_geometry', _U), ('reference_geometry_mm', _D * 2)])


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
    if getattr(value, '_fields_', None) in (_Array._fields_, _Text._fields_):
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
            # A one-byte error clears a nonzero byte; zero arrays need message space.
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


def _visible_buffers_spatial(value, path='result'):
    """Enumerate public views without using the native owner's private layout."""
    counts = {'ranges': 'range_count', 'warnings': 'warning_count',
              'events': 'event_count', 'source': 'source_count', 'shape': 'rank',
              'notices': 'notice_count', 'regions': 'region_count',
              'zone_id': 'cell_count', 'calibration': 'calibration_count'}
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
                            yield from _visible_buffers_spatial(item[index], f'{label}[{index}]')
            elif isinstance(item, (ct.Structure, ct.Array)):
                yield from _visible_buffers_spatial(item, label)
    elif isinstance(value, ct.Array):
        for index, item in enumerate(value):
            yield from _visible_buffers_spatial(item, f'{path}[{index}]')


def _check_owned_aliases_spatial(call, result, destination):
    buffers = list(_visible_buffers_spatial(result))
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


_Inlet = _structure('Inlet3D', [('fluid', _U), *abi._doubles('velocity_m_s temperature_K pressure_Pa'),
    ('port', grid._Port), ('have_mass_flow', _U), ('mass_flow_kg_s', _D)])


_Input_3d = _structure('Input3D', [('abi_version', _U), ('struct_size', _S),
    ('lengths_m', grid._Scalar * 3), ('counts', _S * 3), ('max_cells', _S),
    ('port_wall_refine', _U), ('topology', _U),
    *abi._doubles('cell_length_mm wall_thickness_mm solid_conductivity_W_mK delta_levelset'),
    ('sides', _Inlet * 2), ('geometry_mode', _U), ('df_mode', _U),
    ('kinds', abi._Kinds), ('sco2_nu', abi._Nu)])


_Side = _structure('Side3D', [('axes', ct.c_int32 * 7),
    ('inlet_opening', abi._Array), ('outlet_opening', abi._Array),
    *abi._doubles('rho mu cp k_f'), ('have_drag_application', _U),
    ('drag_evidence', abi._DragEvidence), ('drag_selection', abi._Drag)])


_Result = _structure('Result3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input_3d), ('options', abi._Options), ('widths', abi._Array * 3),
    ('edges', abi._Array * 3), ('geometry', abi._GeometryCache),
    ('uniform_solid_conductivity', _D),
    *((name, abi._Array) for name in ('cell_length', 'wall_thickness', 'total_porosity',
        'side_porosity', 'permeability', 'forchheimer', 'solid_conductivity')),
    ('length_kinds', abi._Kind * 2), ('sides', _Side * 2), ('models', abi._Model * 4),
    ('evidence', abi._Evidence), ('sco2_nu_model_version', abi._Text),
    ('sco2_nu_interpretation', abi._Text), ('sco2_nu_coefficients', (_D * 3) * 2),
    ('co2', abi._Co2), ('notices', ct.POINTER(abi._Text)), ('notice_count', _S),
    ('owner', ct.c_void_p)])


def _kind(value):
    if isinstance(value, np.ndarray):
        return abi._Kind(value.dtype.itemsize * 8, 1, 2)
    if isinstance(value, np.floating):
        return abi._Kind(value.dtype.itemsize * 8, 1, 1)
    return abi._Kind(64, 0, 0)


def _input_3d(config):
    geometry = config.geometry
    source = _Input_3d(1, ct.sizeof(_Input_3d))
    source.lengths_m[:] = tuple(grid._scalar(value) for value in
        (geometry.L_dom_m, geometry.H_dom_m, geometry.Lz_m))
    source.counts[:] = (config.solver.Nx, config.solver.Ny, config.solver.Nz)
    source.max_cells, source.port_wall_refine = 2_000_000, config.flags.port_wall_refine
    source.topology = ('Diamond', 'Gyroid').index(geometry.tpms)
    source.cell_length_mm, source.wall_thickness_mm = geometry.L_cell_mm, geometry.t_wall_mm
    source.solid_conductivity_W_mK, source.delta_levelset = geometry.k_s_W_mK, geometry.delta_levelset
    source.geometry_mode, source.df_mode = int(config.zones.enabled), int(config.df_mode == 'experimental')
    source.kinds = abi._Kinds(*map(_kind, (geometry.L_cell_mm, geometry.t_wall_mm, geometry.k_s_W_mK)))
    for index, side in enumerate('AB'):
        fluid, port = getattr(config, 'fluid_' + side), getattr(config, 'bc_' + side)
        raw_port = {'dir': port.dir}
        for name in ('in_ctr', 'in_w', 'out_ctr', 'out_w', 'in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
            raw_port[name] = getattr(port, name)
        source.sides[index] = _Inlet(abi._FLUIDS.index(fluid.type), fluid.u_mps,
            fluid.T_in_K, fluid.P_in_Pa, grid._port(raw_port),
            fluid.mass_flow_kg_s is not None, fluid.mass_flow_kg_s or 0.)
        source.kinds.sides[index] = abi._InletKinds(*map(_kind,
            (fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa)))
    settings = config.sco2_nu
    source.sco2_nu.mode = int(settings.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(settings, name)
        source.sco2_nu.have_alpha[index], source.sco2_nu.alpha[index] = value is not None, value or 0.
    source._buffers = []
    for name in ('parameter_version', 'source', 'applicability'):
        buffer = ct.create_string_buffer(getattr(settings, name).encode('utf-8'))
        source._buffers.append(buffer)
        setattr(source.sco2_nu, name, abi._Text(ct.cast(buffer, ct.POINTER(ct.c_char)), len(buffer.value)))
    return source


def _configuration_3d(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = _configuration_fluids(topology, pair, mode)
    config.geometry.Lz_m = .042
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    return config


def _check_drag(value, metadata, side):
    assert bool(value.have_drag_application) == (metadata is not None), side
    if metadata is None:
        return
    drag = value.drag_evidence
    for name, key in [('base_permeability', 'base_K'), ('base_forchheimer', 'base_cF'),
                      ('applied_permeability', 'applied_K'), ('applied_forchheimer', 'applied_cF')]:
        summary, expected = getattr(drag, name), metadata[key]
        assert bool(summary.scalar) == isinstance(expected, float), side + key
        _same(summary.minimum, expected if summary.scalar else expected['min'], side + key + '.min')
        _same(summary.maximum, expected if summary.scalar else expected['max'], side + key + '.max')
    for name, key in [('scale_permeability', 'scale_K'), ('scale_forchheimer', 'scale_F')]:
        _same(getattr(drag, name), metadata[key], side + key)
    for name in ('campaign', 'scope'):
        assert read_text(getattr(drag, name)) == metadata[name], side + name
    selected = value.drag_selection
    assert read_text(selected.fluid) == metadata.get('fluid', ''), side
    assert read_text(selected.application_scope) == metadata.get('application_scope', ''), side
    assert {read_text(item.key): read_text(item.value) for item in selected.calibration[:selected.calibration_count]} == metadata.get('calibration', {})
    if 'velocity_window_mps' in metadata:
        for name, key in [('application_u', 'velocity_window_mps'),
                          ('calibration_u', 'calibration_velocity_window_mps'),
                          ('runtime_u', 'calibration_runtime_velocity_window_mps')]:
            _same(getattr(selected.selection, name),
                  [metadata[key]['min'], metadata[key]['max']], side + key)
        assert bool(selected.selection.flags & 2) == metadata['extrapolated']


def _check_values(result, expected, config, *, side_b_porosity=None):
    shape = tuple(len(expected.grid['d' + axis]) for axis in 'xyz')
    assert tuple(result.input.counts) == shape
    for index, axis in enumerate('xyz'):
        _same(copy_array(result.widths[index]), expected.grid['d' + axis], 'd' + axis)
        _same(copy_array(result.edges[index]), expected.grid[axis + '_edges'], axis + '_edges')
    for name, key in [('cell_length', 'L_field_m'), ('wall_thickness', 't_field_m'),
        ('total_porosity', 'eps_arr'), ('side_porosity', 'eps_A'),
        ('permeability', 'K_m2'), ('forchheimer', 'cF_per_m'), ('solid_conductivity', 'K_ss')]:
        _same(copy_array(getattr(result, name), shape), expected.design_fields[key], key)
    _same(copy_array(result.side_porosity if side_b_porosity is None else side_b_porosity, shape),
          expected.design_fields['eps_B'], 'eps_B')
    for index, key in enumerate(('L_field_m', 't_field_m')):
        assert result.length_kinds[index].precision == expected.design_fields[key].dtype.itemsize * 8, key
    params, prepared = expected.parameters, expected.parameters['prepared']
    for name, key in [('epsilon', 'epsilon'), ('epsilon_a', 'epsilon_A'), ('epsilon_b', 'epsilon_B'),
                      ('area_density_per_m', 'A_0'), ('hydraulic_diameter_m', 'D_h')]:
        _same(getattr(result.geometry, name), prepared['geometry'][key], key)
    _same(result.uniform_solid_conductivity, prepared['geometry']['K_ss'], 'nominal K_ss')
    for index, side in enumerate('AB'):
        actual, axis = result.sides[index], prepared['axes'][side]
        assert tuple(actual.axes) == (axis['cross1_real_axis'], axis['stream_real_axis'],
            axis['cross2_real_axis'], *axis['solver_to_real_perm'], int(axis['is_reverse']))
        cross_shape = (axis['N_cross1'], axis['N_cross2'])
        for end in ('inlet', 'outlet'):
            _same(copy_array(getattr(actual, end + '_opening'), cross_shape),
                  prepared['openings'][side][end], side + end)
        for name, key in [('rho', 'rho'), ('mu', 'mu'), ('cp', 'cp'), ('k_f', 'k')]:
            _same(getattr(actual, name), prepared['properties'][side][key], side + key)
        metadata = (params['df_application'] or {}).get(side)
        _check_drag(actual, metadata, side)
        assert bool(actual.drag_selection.have_selection) == (config.df_mode == 'experimental'
            and getattr(config, 'fluid_' + side).type != 'co2')
    assert [(read_text(item.name), read_text(item.version), read_text(item.side)) for item in result.models] == [
        (item.name, item.version, 'AB'[index] if index < 2 else '')
        for index, item in enumerate(expected.model_refs)]


def _check_evidence(result, expected, records, events, live, config):
    actual = result.evidence
    assert [_range(actual.ranges[i]) for i in range(actual.range_count)] == list(expected.metadata['applicability_inputs'])
    for last in (False, True):
        observations = []
        for index in range(actual.range_count):
            row = _range(actual.ranges[index], last=last)
            if actual.range_bounds_list[index]:
                row['bounds'] = list(row['bounds'])
            observations.append(row)
        assert observations == range_observations(records, last=last)
    assert [read_text(actual.ranges[i].label) for i in range(actual.range_count)] == [
        value.label for value in records.values() if isinstance(value, RangeRecord)]
    assert [read_text(item) for item in actual.warnings[:actual.warning_count]] == list(expected.metadata['warnings'])
    saved = [(item.kind, read_text(item.logger), read_text(item.message), item.floating_event)
             for item in actual.events[:actual.event_count]]
    assert saved == live
    assert _host_events(saved) == events
    assert [read_text(item) for item in result.notices[:result.notice_count]] == list(expected.metadata['notices'])
    selected = config.sco2_nu
    assert result.input.sco2_nu.mode == (selected.mode == 'experimental')
    for index, name in enumerate(('alpha_D', 'alpha_G')):
        value = getattr(selected, name)
        assert bool(result.input.sco2_nu.have_alpha[index]) == (value is not None)
        if value is not None:
            _same(result.input.sco2_nu.alpha[index], value, name)
    for name in ('parameter_version', 'source', 'applicability'):
        assert read_text(getattr(result.input.sco2_nu, name)) == getattr(selected, name)
    model = expected.metadata['model_metadata']['sco2_nu']
    assert read_text(result.sco2_nu_model_version) == model['model_version']
    if selected.mode == 'experimental':
        assert read_text(result.sco2_nu_interpretation) == model['interpretation']
    else:
        for index, topology in enumerate(('Diamond', 'Gyroid')):
            _same(result.sco2_nu_coefficients[index],
                  [model['coefficients'][topology][key] for key in ('c', 'a', 'd')], topology)
    model = expected.metadata['model_metadata'].get('co2')
    assert bool(result.co2.active) == (model is not None)
    if model is not None:
        assert ['AB'[i] for i, flag in enumerate(result.co2.sides) if flag] == list(model['sides'])
        for name in ('version', 'application_version', 'pressure_model', 'correction_source', 'property_model', 'common_geometry'):
            assert read_text(getattr(result.co2, name)) == model[name]
        for name in ('pressure_multiplier', 'scale_K', 'scale_F', 'nu_multiplier', 'nu_floor_multiplier'):
            _same(getattr(result.co2, name), model[name], name)
        _same(result.co2.re_range, model['Re_range'], 'CO2 Re range')
        _same(result.co2.pr_range, model['Pr_range'], 'CO2 Pr range')


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


_Input_flow_3d = _structure('FlowInput3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input_3d), ('target_kinds', abi._Kind * 2),
    ('have_explicit_targets', _U), ('explicit_targets_kg_s', _D * 2)])


_Flow = _structure('Flow3D', [('abi_version', _U), ('struct_size', _S),
    ('input', _Input_3d), ('have_capacities', _U),
    ('capacities', _native_flow._Scalar * 2), ('speeds', _native_flow._Scalar * 2),
    ('evidence', abi._Evidence), ('owner', ct.c_void_p)])


def _input_flow_3d(config, targets=None):
    source = _input_3d(config)
    result = _Input_flow_3d(2, ct.sizeof(_Input_flow_3d), source)
    result._source = source
    result.have_explicit_targets = targets is not None
    for index, side in enumerate('AB'):
        target = targets[index] if targets is not None else getattr(config, 'fluid_' + side).mass_flow_kg_s
        kind = _native_flow._scalar(0. if target is None else target)
        result.target_kinds[index] = abi._Kind(kind.precision, kind.strong, int(bool(kind.strong)))
        if targets is not None:
            result.explicit_targets_kg_s[index] = target
    return result


def _reference(monkeypatch, operation, config, targets=None, *, scoped=False, state=None):
    from tests.python.property_reference import compute
    from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    state = {} if state is None else state
    state.update(records={}, capacity_records={}, events=[], capacity_events=[],
                 resolved=config, geometry_calls=0)

    @contextmanager
    def capture_scope(initial):
        with warning_scope(initial) as records:
            try:
                yield records
            finally:
                state['records'].update(records)

    original_geometry, original_finish = preparation._prepare_geometry_data, preparation._finish_problem_data

    def geometry(*args, **kwargs):
        state['geometry_calls'] += 1
        prepared = original_geometry(*args, **kwargs)
        state['capacity_records'] = dict(current_warnings() or {})
        state['capacity_events'] = list(state['events'])
        return prepared

    def finish(prepared):
        state['resolved'] = prepared['cfg']['compute_cfg']
        return original_finish(prepared)

    with monkeypatch.context() as patch, warnings.catch_warnings():
        patch.setattr(api, 'warning_scope', capture_scope)
        patch.setattr(preparation, '_prepare_geometry_data', geometry)
        patch.setattr(preparation, '_finish_problem_data', finish)
        warnings.simplefilter('always')
        patch.setattr(warnings, 'showwarning', lambda message, *args, **kwargs:
            state['events'].append((1, '', str(message), 0)))
        with capture_scope({}) if scoped else nullcontext():
            if operation == 'prepare_inlet_mass_capacities':
                expected = api.prepare_inlet_mass_capacities(config)
            elif operation == 'resolve_inlet_flow':
                expected = (api.resolve_inlet_flow_config(config) if targets is None else
                    api.resolve_fixed_mass_flow_config(config,
                        mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1]))
                state['resolved'] = expected
            else:
                expected = (api.prepare_case(config, case_id='native-3d-flow-reference') if targets is None else
                    api.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=targets[0],
                        mass_flow_B_kg_s=targets[1], case_id='native-3d-flow-reference'))
    return expected, state


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
        assert _struct_values(actual.input.kinds.sides[index].velocity) == _struct_values(_kind(fluid.u_mps))
        _scalar(actual.speeds[index], fluid.u_mps)


_OWNED_FLOW_CASES = [('prepare_inlet_mass_capacities', True), ('resolve_inlet_flow', True),
                     ('prepare_flow_case', True), ('resolve_inlet_flow', False)]
