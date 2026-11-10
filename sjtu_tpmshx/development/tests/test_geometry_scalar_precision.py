"""Keep pre-port scalar rounding, material types and prepared field types.

The reference follows 9fb5401d geometry, props, CO2 and QD source bodies.
Only phi and node data are cached. Geometry results are never cached.
"""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import geometry_reference as frozen
from sjtu_tpmshx.shared.models import co2_correlations, tpms_calc, tpms_geometry, tpms_props


_TOPOLOGIES = ('Diamond', 'Gyroid')
_TYPES = (float, np.float16, np.float32, np.float64)
_SCALARS = [
    pytest.param(float, float, id='python'),
    pytest.param(np.float16, np.float16, id='half'),
    pytest.param(np.float32, np.float32, id='single'),
    pytest.param(np.float64, np.float64, id='double'),
    pytest.param(float, np.float16, id='python-half'),
    pytest.param(np.float16, float, id='half-python'),
    pytest.param(np.float32, np.float64, id='single-double'),
    pytest.param(np.float64, np.float32, id='double-single'),
]


@pytest.fixture(autouse=True)
def clear_public_caches():
    tpms_geometry.compute_geometry.cache_clear()
    tpms_calc.compute.cache_clear()
    yield
    tpms_geometry.compute_geometry.cache_clear()
    tpms_calc.compute.cache_clear()


def _threshold(topology, ratio):
    a, b = frozen._C_COEFFS[topology]
    return a * ratio + b * np.float_power(ratio, 2)


def _counts(phi, threshold):
    solid = np.abs(phi) <= threshold
    occupied = np.intp(np.count_nonzero(solid))
    faces = 0
    faces += np.sum(solid[:-1, :, :] != solid[1:, :, :])
    faces += np.sum(solid[:, :-1, :] != solid[:, 1:, :])
    faces += np.sum(solid[:, :, :-1] != solid[:, :, 1:])
    return occupied, faces


def _raw(topology, length, wall, n):
    # Preserve weak scalar arithmetic before float_power promotes its operand.
    length_m = length / 1000.0
    ratio = wall / length
    threshold = np.maximum(_threshold(topology, ratio), 0.0)
    phi = frozen._phi_grid(topology, n)
    if np.ndim(threshold) == 0:
        occupied, faces = _counts(phi, threshold)
    else:
        occupied = np.empty(threshold.shape, dtype=np.intp)
        faces = np.empty(threshold.shape, dtype=np.int64)
        for index in np.ndindex(threshold.shape):
            occupied[index], faces[index] = _counts(phi, threshold[index])
    epsilon = 1.0 - occupied / phi.size
    area = faces * np.float_power(length_m / n, 2) / (
        2.0 * np.float_power(length_m, 3) * frozen._AREA_CORRECTION)
    return epsilon, area


def _scalar_geometry(topology, length, wall, n):
    epsilon, area = _raw(topology, length, wall, n)
    epsilon = float(epsilon)
    return dict(epsilon=epsilon, epsilon_A=.5 * epsilon, epsilon_B=.5 * epsilon,
                A_0=area, D_h=4.0 * (.5 * epsilon) / area)


def _chi(topology, epsilon, override):
    if override is not None:
        return float(override)
    c0, c1 = frozen._CHI_S_FIT[topology]
    result = c0 + c1 * (1.0 - np.asarray(epsilon, dtype=np.float64))
    return float(result) if result.ndim == 0 else result


def _material(topology, geometry, conductivity, override=None):
    result = dict(geometry)
    result['K_ss'] = _chi(topology, result['epsilon'], override) * (
        1.0 - result['epsilon']) * conductivity
    return result


def _field_geometry(topology, length, wall, conductivity, n, override=None):
    # The public field entry converted the original input arrays to float64.
    length = np.asarray(length, dtype=np.float64)
    wall = np.asarray(wall, dtype=np.float64)
    epsilon, area = _raw(topology, length, wall, n)
    geometry = dict(epsilon=epsilon, epsilon_A=.5 * epsilon, epsilon_B=.5 * epsilon,
                    A_0=area, D_h=4.0 * (.5 * epsilon) / area)
    return {key: np.ascontiguousarray(value) for key, value in
            _material(topology, geometry, conductivity, override).items()}


def _assert_scalars(actual, expected):
    assert actual.keys() == expected.keys()
    for key in expected:
        assert type(actual[key]) is type(expected[key]), key
        np.testing.assert_array_equal(actual[key], expected[key], err_msg=key)


def _assert_arrays(actual, expected):
    assert actual.keys() == expected.keys()
    for key in expected:
        assert actual[key].dtype == expected[key].dtype, key
        np.testing.assert_array_equal(actual[key], expected[key], err_msg=key)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('n', [13, 32])
@pytest.mark.parametrize('length_type,wall_type', _SCALARS)
def test_scalar_geometry_keeps_input_arithmetic(topology, n, length_type, wall_type):
    length, wall = length_type(7.), wall_type(.6)
    expected = _scalar_geometry(topology, length, wall, n)
    actual = tpms_geometry.compute_geometry(topology, length, wall, N=n)
    _assert_scalars(actual, expected)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('scalar_type', _TYPES)
def test_scalar_threshold_keeps_weak_product_rounding(topology, scalar_type):
    centre = scalar_type(.0857)
    for ratio in (scalar_type(np.nextafter(centre, scalar_type(0.))), centre,
                  scalar_type(np.nextafter(centre, scalar_type(1.)))):
        expected = _threshold(topology, ratio)
        actual = tpms_geometry._C_from_tL(topology, ratio)
        assert type(actual) is type(expected)
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_array_threshold_keeps_input_precision(topology, dtype):
    centre = dtype(.0857)
    ratios = np.array([.03, np.nextafter(centre, dtype(0.)), centre,
                       np.nextafter(centre, dtype(1.)), .2], dtype=dtype)
    expected = _threshold(topology, ratios)
    actual = tpms_geometry._C_from_tL(topology, ratios)
    assert actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
def test_half_precision_neighbors_at_sampled_threshold(topology):
    n = 32
    absolute = np.abs(frozen._phi_grid(topology, n))
    target = absolute.flat[np.argmin(np.abs(absolute - .4))]
    a, b = frozen._C_COEFFS[topology]
    ratio = np.float16((-a + np.sqrt(a*a + 4*b*target)) / (2*b))
    length = np.float16(7.)
    wall = ratio * length
    for value in (np.nextafter(wall, np.float16(0.)), wall,
                  np.nextafter(wall, np.float16(1.))):
        tpms_geometry.compute_geometry.cache_clear()
        expected = _scalar_geometry(topology, length, value, n)
        actual = tpms_geometry.compute_geometry(topology, length, value, N=n)
        _assert_scalars(actual, expected)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('conductivity_type', _TYPES)
@pytest.mark.parametrize('selection', ['fit', 'environment', 'explicit'])
def test_scalar_material_keeps_weak_conductivity_type(
        monkeypatch, topology, conductivity_type, selection):
    conductivity = conductivity_type(16.3)
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    override, kwargs = None, {}
    if selection == 'environment':
        monkeypatch.setenv('TPMSHX_CHI_S', '.7')
        override = .7
    elif selection == 'explicit':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
        override = np.float16(.65)
        kwargs['chi_s'] = override
    expected = _material(topology, _scalar_geometry(topology, 7., .6, 13),
                         conductivity, override)
    actual = tpms_props.geometry(topology, 7., .6, conductivity, N=13, **kwargs)
    _assert_scalars(actual, expected)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_fields_promote_inputs_before_geometry_and_material(monkeypatch, topology, dtype):
    monkeypatch.setenv('TPMSHX_CHI_S', '.7')
    length = np.array([[7., 6.25], [5.5, 8.]], dtype=dtype, order='F')
    wall = np.array([[.6, .42], [.35, .5]], dtype=dtype, order='F')
    conductivity = dtype(16.3)
    expected = _field_geometry(topology, length, wall, conductivity, 13, .7)
    actual = tpms_props.geometry_fields(topology, length, wall, conductivity, N=13)
    _assert_arrays(actual, expected)
    assert all(value.dtype == np.float64 for value in actual.values())


@pytest.mark.parametrize('conductivity_type', [np.float16, np.float32, np.float64])
def test_compute_cache_hits_keep_current_chi_and_conductivity_type(monkeypatch, conductivity_type):
    conductivity = conductivity_type(16.3)
    geometry = _scalar_geometry('Gyroid', 7., .5, 128)
    for override in (.7, .5):
        monkeypatch.setenv('TPMSHX_CHI_S', str(override))
        expected = _material('Gyroid', geometry, conductivity, override)['K_ss']
        actual = tpms_calc.compute('Gyroid', 7., .5, 8.5, 380., 160000., conductivity)
        assert type(actual['K_ss']) is type(expected)
        np.testing.assert_array_equal(actual['K_ss'], expected)
    assert tpms_calc.compute.cache_info().misses == 1
    assert tpms_calc.compute.cache_info().hits == 1


@lru_cache(maxsize=2)
def _co2_table(topology):
    path = Path(__file__).resolve().parents[2] / 'shared/configs/co2_segment2_v1.json'
    nodes = json.loads(path.read_text(encoding='utf-8'))['topologies'][topology]['geometry_nodes']
    lengths = sorted({node['L_mm'] for node in nodes})
    walls = sorted({node['t_mm'] for node in nodes})
    lookup = {(node['L_mm'], node['t_mm']): node for node in nodes}
    table = np.empty((len(lengths), len(walls), 3))
    for i, length in enumerate(lengths):
        for j, wall in enumerate(walls):
            node = lookup[length, wall]
            cell = length * 1e-3
            table[i, j] = (node['epsilon_single'], node['Dh_m'] / cell,
                           node['A0_single_per_m'] * cell)
    table.flags.writeable = False
    return lengths, walls, table


def _co2_bracket(value, nodes):
    value = float(value)
    value = min(max(value, nodes[0]), nodes[-1])
    upper = int(np.searchsorted(nodes, value))
    if upper == 0 or abs(value - nodes[upper]) < 1e-12:
        return upper, upper, 0.
    return upper - 1, upper, (value - nodes[upper - 1]) / (nodes[upper] - nodes[upper - 1])


def _co2_geometry(topology, length, wall, conductivity, override):
    lengths, walls, table = _co2_table(topology)
    i0, i1, wl = _co2_bracket(length, lengths)
    j0, j1, wt = _co2_bracket(wall, walls)
    epsilon, diameter, area = ((1-wt) * ((1-wl)*table[i0, j0] + wl*table[i1, j0])
                              + wt * ((1-wl)*table[i0, j1] + wl*table[i1, j1]))
    cell = float(length) * 1e-3
    return dict(epsilon=2*epsilon, epsilon_A=epsilon, epsilon_B=epsilon,
                D_h=diameter*cell, A_0=area/cell,
                K_ss=_chi(topology, 2*epsilon, override) * (1-2*epsilon) * conductivity)


@pytest.mark.parametrize('topology', _TOPOLOGIES)
@pytest.mark.parametrize('dtype', _TYPES)
@pytest.mark.parametrize('override', [None, .7])
def test_co2_keeps_strong_double_intermediates(monkeypatch, topology, dtype, override):
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    if override is not None:
        monkeypatch.setenv('TPMSHX_CHI_S', str(override))
    length, wall, conductivity = dtype(6.3), dtype(.42), dtype(16.3)
    expected = _co2_geometry(topology, length, wall, conductivity, override)
    actual = co2_correlations.geometry(topology, length, wall, conductivity)
    _assert_scalars(actual, expected)
    assert all(type(value) is np.float64 for value in actual.values())


@pytest.mark.parametrize('first_type,second_type', [
    (np.float16, float), (float, np.float16),
], ids=['half-first', 'python-first'])
def test_untyped_scalar_cache_keeps_first_equal_input(first_type, second_type):
    first = (first_type(7.), first_type(.5))
    second = (second_type(7.), second_type(.5))
    expected = _scalar_geometry('Gyroid', *first, 13)
    initial = tpms_geometry.compute_geometry('Gyroid', *first, N=13)
    hit = tpms_geometry.compute_geometry('Gyroid', *second, N=13)
    _assert_scalars(initial, expected)
    _assert_scalars(hit, expected)
    assert initial is not hit
    assert tpms_geometry.compute_geometry.cache_info().misses == 1
    assert tpms_geometry.compute_geometry.cache_info().hits == 1


def _archived_scalar(value):
    if isinstance(value, np.generic) and not isinstance(value, (bool, int, float)):
        return value.item()
    return value


@pytest.mark.parametrize('conductivity_type', [np.float16, np.float32])
@pytest.mark.parametrize('mode', ['full_2d', 'quick_design'])
def test_public_preparation_keeps_material_values_and_field_dtype(
        monkeypatch, conductivity_type, mode):
    from sjtu_tpmshx.preprocess.api import prepare_case, prepare_quick_design
    from sjtu_tpmshx.shared.domain.compute_config import (
        ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
    )

    conductivity = conductivity_type(16.3)
    monkeypatch.setenv('TPMSHX_CHI_S', '.7')
    topology = 'Gyroid' if mode == 'full_2d' else 'Diamond'
    expected = _material(topology, _scalar_geometry(topology, 7., .5, 128),
                         conductivity, .7)
    if mode == 'full_2d':
        config = ComputeConfig(
            geometry=GeometryConfig(tpms=topology, L_cell_mm=7., t_wall_mm=.5,
                                    k_s_W_mK=conductivity, Lz_m=.042),
            fluid_A=FluidConfig(type='air', u_mps=8.5, T_in_K=380., P_in_Pa=160000.),
            fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=200000.),
            solver=SolverConfig(Nx=4, Ny=3, Nz=1),
            bc_A=PartialBCConfig(dir=0, in_ctr=.021, in_w=.042,
                                out_ctr=.021, out_w=.042, uniform_inlet_2d=True),
            bc_B=PartialBCConfig(dir=3, in_ctr=.091, in_w=.182,
                                out_ctr=.091, out_w=.182, uniform_inlet_2d=True))
        case = prepare_case(config, case_id='scalar-material-2d')
        shape = (len(case.grid['dx']), len(case.grid['dy']))
        _assert_scalars(case.parameters['static_properties']['geometry'],
                        {key: _archived_scalar(value) for key, value in expected.items()})
        _assert_scalars(case.parameters['thermal_geometry']['uniform'],
                        {key: _archived_scalar(value) for key, value in expected.items()})
        arrays = dict(eps_arr=np.full(shape, expected['epsilon']),
                      K_ss_arr=np.full(shape, expected['K_ss']),
                      r_h_arr=np.full(shape, expected['D_h'] / 2.),
                      L_field_m=np.full(shape, 7. * 1e-3),
                      t_field_m=np.full(shape, .5 * 1e-3))
    else:
        from sjtu_tpmshx.applications.design.cases import DesignCase
        from sjtu_tpmshx.preprocess.app_modes import quick_design as preparation

        monkeypatch.setattr(preparation, 'NX', 8)
        monkeypatch.setitem(preparation._ARR, 'cross', {**preparation._ARR['cross'], 'ny': 6})
        condition = DesignCase(1, 'air', 688.23, 1088700., .2855,
                               'water', 320., 200000., .5, 30000., .075, .05)
        case = prepare_quick_design(condition, topology, 7., .5, .084, .025,
                                    k_s=conductivity, case_id='scalar-material-qd')
        shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
        assert case.parameters['A_0'] == expected['A_0']
        assert case.parameters['D_h'] == expected['D_h']
        # The original QD solid model fixes chi=1, independent of the environment.
        solid = (1. - expected['epsilon']) * conductivity
        arrays = dict(eps=np.full(shape, expected['epsilon']),
                      eps_A=np.full(shape, expected['epsilon_A']), K_ss=np.full(shape, solid))
    _assert_arrays(case.design_fields, arrays)
