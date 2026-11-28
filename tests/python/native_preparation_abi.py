"""Shared ctypes helpers, configurations and checks for the native preparation tests."""
import ctypes as ct

import numpy as np

from tm1.cpp_interface import _native_preparation_case as abi
from tm1.cpp_interface.stage_libraries import preparation_library
from tm1.data_types.compute_config import ComputeConfig, ZoneInputConfig
from tests.python.solver_tm1.test_prepared_zoned_thermal_2d import _config


_library_path = preparation_library.path
_U, _S = ct.c_uint32, ct.c_size_t
_Failure = abi._Failure


def supply_sigmoid_table(monkeypatch, table):
    """Pack the private axes, table values and flags for a real sigmoid operation."""
    from tm1.cpp_interface import native_preparation
    from tm1.cpp_interface._native_values import borrow_array

    original = native_preparation.pack_input

    def pack(*args):
        source, error = original(*args)
        if isinstance(source, abi._SigmoidInput):
            arrays, flags = table.preparation_arrays()
            source.lut = abi._LUTView(*(borrow_array(a, source._buffers) for a in arrays), *flags)
            source.model.load_default_lut = 0
        return source, error

    monkeypatch.setattr(native_preparation, 'pack_input', pack)


def _text(value):
    return ct.string_at(value.data, value.size).decode()


def _array(value):
    return np.ctypeslib.as_array(value.data, shape=(value.size,)).copy() if value.size else np.array([], dtype=float)


def _same(actual, expected, name):
    actual = np.asarray(actual, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    assert actual.shape == expected.shape, name
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)


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
        from tm1.model_configs.model_parameters import load_preparation_df_parameters
        data = load_preparation_df_parameters()['hx']
        for side in 'AB':
            fluid = getattr(config, 'fluid_' + side)
            if fluid.type != 'co2':
                bounds = data['application_u_mps'][fluid.type][topology]
                fluid.u_mps = sum(bounds) / 2.
    return config


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


def _visible_buffers(value, path='result'):
    """Enumerate public views without using the native owner's private layout."""
    counts = {'data': 'size', 'ranges': 'range_count', 'warnings': 'warning_count',
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
                    size = value.range_count
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


def _configuration_3d(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth'):
    config = _configuration_fluids(topology, pair, mode)
    config.geometry.Lz_m = .042
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    return config


def _configuration_spatial_3d(topology='Gyroid', pair=('air', 'water'), *, spatial=True, delta=.12,
                              mode='cfd_smooth'):
    """Return a 3D grid-zone configuration, or a uniform one when spatial is false."""
    config = _configuration_3d(topology, pair, mode)
    config.geometry.delta_levelset = delta
    if spatial:
        config.zones = ZoneInputConfig(enabled=True, axis='grid', grid={'cells': [
            dict(x0=0., x1=.65, y0=0., y1=.55, L=4.25, t=.33),
            dict(x0=.35, x1=.85, y0=.2, y1=.9, L=7.5, t=.54),
            dict(x0=0., x1=1., y0=.4, y1=.6, L=5.5, t=.42)]})
    return config


def _configuration_continuous_3d(topology='Gyroid', pair=('air', 'water'), mode='cfd_smooth', *,
                                 nx=4, ny=5, nz=None, mirror=True, order=3):
    """Return a 3D continuous-field configuration. Without nz, the XY field extrudes along z."""
    config = _configuration_3d(topology, pair, mode)
    count = nx * ((ny + 1) // 2 if mirror else ny) * (1 if nz is None else nz)
    spec = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=mirror, spline_order=order,
        L_bounds=[4., 8.], t_bounds=[.3, .6],
        x_decision=[float(value) for value in np.r_[
            np.linspace(4.2, 7.8, count), np.linspace(.57, .32, count)]])
    if nz is not None:
        spec['n_ctrl_z'] = nz
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    return config
