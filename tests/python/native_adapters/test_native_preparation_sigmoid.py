"""Compare the active cold sigmoid geometry LUT entry with raw voxel scans."""
import ctypes as ct

import numpy as np
import pytest

from tm1.cpp_interface import _native_preparation_case as abi
from tests.python import geometry_reference
from tests.python.native_preparation_abi import (
    _S, _U, _array, _check_owned_aliases, _library_path, _same, _visible_buffers,
)

_LUT = abi._SigmoidLUT


@pytest.fixture(scope='module')
def native():
    library = ct.CDLL(_library_path())
    library.tpmshx_preparation_sigmoid_lut_create_v7.argtypes = [_U, _S, _S, _S,
        ct.POINTER(_LUT), ct.POINTER(ct.c_char), _S]
    library.tpmshx_preparation_sigmoid_lut_create_v7.restype = ct.c_int
    library.tpmshx_preparation_sigmoid_lut_release_v7.argtypes = [ct.POINTER(_LUT)]
    library.tpmshx_preparation_sigmoid_lut_release_v7.restype = None
    return library


def _raw_tables(topology, cells, walls, resolution):
    """Scan the frozen voxel field; no production geometry supplies these values."""
    absolute = np.abs(geometry_reference._phi_grid(topology, resolution))
    epsilon, area = (np.empty((len(cells), len(walls))) for _ in range(2))
    for i, cell in enumerate(cells):
        for j, wall in enumerate(walls):
            threshold = geometry_reference._C_from_tL(topology, wall / cell)
            solid = absolute <= threshold
            epsilon[i, j] = 1. - solid.mean()
            area[i, j] = geometry_reference._area_from_solid(solid, cell / 1000., resolution)
    return epsilon, area


def _release(native, value):
    native.tpmshx_preparation_sigmoid_lut_release_v7(ct.byref(value))


def _cold(native, topology, *, shape=(2, 2), resolution=16):
    result, error = _LUT(1, ct.sizeof(_LUT)), ct.create_string_buffer(4096)
    status = native.tpmshx_preparation_sigmoid_lut_create_v7(
        int(topology == 'Gyroid'), *shape, resolution, ct.byref(result), error, len(error))
    assert status == 0, error.value.decode()
    assert result.owner and (result.porosity_fast, result.area_fast) == (1, 1)
    return result


def _check_cold(result, topology, shape, resolution):
    cells, walls = np.linspace(4., 8., shape[0]), np.linspace(.3, .6, shape[1])
    _same(_array(result.cell_mm), cells, 'cold cell axis')
    _same(_array(result.wall_mm), walls, 'cold wall axis')
    epsilon, area = _raw_tables(topology, cells, walls, resolution)
    _same(_array(result.porosity).reshape(shape), epsilon, 'cold porosity')
    _same(_array(result.area_density_per_m).reshape(shape), area, 'cold area')


@pytest.fixture(autouse=True)
def clear_reference_caches():
    yield
    geometry_reference._phi_grid.cache_clear()


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('shape,resolution', [((2, 2), 16), ((1, 1), 1), ((0, 3), 1), ((3, 1), 13)])
def test_sigmoid_cold_lut_matches_raw_voxel_nodes(native, topology, shape, resolution):
    result = _cold(native, topology, shape=shape, resolution=resolution)
    try:
        if 0 in shape:
            _same(_array(result.cell_mm), np.linspace(4., 8., shape[0]), 'empty axis')
            assert result.porosity.size == result.area_density_per_m.size == 0
        else:
            _check_cold(result, topology, shape, resolution)
        if topology == 'Diamond' and resolution == 1 and shape == (1, 1):
            _same(_array(result.porosity), [0.], 'raw degenerate porosity')
            _same(_array(result.area_density_per_m), [0.], 'raw degenerate area')
    finally:
        _release(native, result)
    assert bytes(result) == bytes(_LUT())
    _release(native, result)
    native.tpmshx_preparation_sigmoid_lut_release_v7(None)


@pytest.mark.parametrize('selection', ['zero-resolution', 'extent-overflow', 'voxel-overflow',
    'topology', 'version', 'size'])
def test_sigmoid_cold_lut_failure_preserves_result(native, selection):
    result, error = _LUT(1, ct.sizeof(_LUT)), ct.create_string_buffer(4096)
    topology, cells, walls, resolution = 1, 2, 2, 16
    if selection == 'zero-resolution':
        resolution = 0
    elif selection == 'extent-overflow':
        cells = _S(-1).value
    elif selection == 'voxel-overflow':
        resolution = _S(-1).value
    elif selection == 'topology':
        topology = 2
    elif selection == 'version':
        result.abi_version = 0
    else:
        result.struct_size = 0
    before = bytes(result)
    status = native.tpmshx_preparation_sigmoid_lut_create_v7(topology, cells, walls,
        resolution, ct.byref(result), error, len(error))
    assert status == 1 and error.value and bytes(result) == before


def test_sigmoid_cold_lut_reuse_and_error_overlap(native):
    resource = _cold(native, 'Gyroid')
    before, error = bytes(resource), ct.create_string_buffer(4096)
    try:
        status = native.tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16,
            ct.byref(resource), error, len(error))
        assert status == 1 and b'release' in error.value and bytes(resource) == before
        status = native.tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16,
            ct.byref(resource), ct.cast(ct.byref(resource), ct.POINTER(ct.c_char)), ct.sizeof(resource))
        assert status == 1 and bytes(resource) == before
    finally:
        _release(native, resource)


@pytest.mark.slow
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_sigmoid_production_cold_nodes(native, topology):
    """Check all 1,271 N=256 nodes; small transport fixtures cannot replace this check."""
    resource = _cold(native, topology, shape=(41, 31), resolution=256)
    try:
        _check_cold(resource, topology, (41, 31), 256)
    finally:
        _release(native, resource)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('invalid', ['none', 'version', 'size'])
def test_standalone_lut_owned_views_reject_error_aliases(native, topology, invalid):
    result = _cold(native, topology)
    topology_id = int(topology == 'Gyroid')
    call = lambda _failure, error, capacity: native.tpmshx_preparation_sigmoid_lut_create_v7(
        topology_id, 2, 2, 16, ct.byref(result), error, capacity)
    try:
        if invalid != 'none':
            setattr(result, 'struct_size' if invalid == 'size' else 'abi_version', 0)
        assert set(_check_owned_aliases(call, result, 'error')) == {
            'result.' + name for name in ('cell_mm', 'wall_mm', 'porosity', 'area_density_per_m')}
        result.abi_version, result.struct_size = 1, ct.sizeof(result)
        before = [(address, ct.string_at(address, size)) for _, address, size in _visible_buffers(result)]
        outer, error = bytes(result), ct.create_string_buffer(4096)
        assert call(None, error, len(error)) == 1 and b'release' in error.value
        assert bytes(result) == outer
        assert all(ct.string_at(address, len(saved)) == saved for address, saved in before)
    finally:
        _release(native, result)


def test_imported_lut_keeps_its_file_fields_when_error_storage_overlaps():
    from tm1.cpp_interface._native_lut import table_value

    axes = np.array([4., 8.]), np.array([.3, .6])
    tables = np.full((2, 2), .7, dtype='f4'), np.full((2, 2), 1000, dtype='u8')
    held = table_value('Gyroid', 16, axes, tables=tables, private=True)
    try:
        def call(_failure, error, capacity):
            return held.binding.table(0, 1, 16, ct.byref(abi._LUTView()), None, ct.byref(held.view), error, capacity)
        names = _check_owned_aliases(call, held.view, 'error')
        for index in range(2):
            assert f'result.file_fields[{index}].data' in names
            assert f'result.file_fields[{index}].dtype' in names
    finally:
        held.close()
