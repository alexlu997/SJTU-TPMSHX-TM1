"""Compare production MC side areas and diameters with independent skimage.

The reference retains the pre-port scalar types, bounds and side fractions.
Mesh generation and area reduction come from the locked scikit-image 0.26 build.
The public API supports isotropic dx=L/N. Unequal-axis spacing remains an
isolated MC-kernel check; this module adds no compiler or mesh API.
"""
import numpy as np
import pytest
from skimage import measure

from sjtu_tpmshx.development.tests import geometry_reference
from sjtu_tpmshx.shared.models import _native_geometry, asym_geometry, tpms_geometry


_SPACING_CASES = [pytest.param(1., 1., id='unit-dx'),
                  pytest.param(.007, 13.5, id='physical-independent-N')]


def _reference_sides(phi, C, delta, length_m, N):
    """Retain the original raw-array arithmetic without native expected values."""
    dx = length_m / N
    volume = length_m ** 3
    minimum, maximum = float(phi.min()), float(phi.max())
    areas = []
    for level in (delta - C, delta + C):
        if level <= minimum or level >= maximum:
            area = 0.
        else:
            vertices, faces, _, _ = measure.marching_cubes(
                phi, level=level, spacing=(dx, dx, dx), method='lewiner',
                gradient_direction='descent', step_size=1, allow_degenerate=True)
            area = float(measure.mesh_surface_area(vertices, faces))
        areas.append(area / volume)
    epsilon = (float(np.mean(phi < (delta - C))), float(np.mean(phi > (delta + C))))
    diameter = tuple(4. * eps / area if area > 0. else 0. for eps, area in zip(epsilon, areas))
    return np.asarray(areas), np.asarray(diameter)


def _compare_sides(phi, C, delta, length_m, N, identifier):
    operations = (
        lambda: asym_geometry.a0_sides_mc(phi, C, delta, length_m, N),
        lambda: asym_geometry.dh_sides(phi, C, delta, length_m, N, mc=True),
    )
    try:
        expected = _reference_sides(phi, C, delta, length_m, N)
    except (ValueError, RuntimeError) as reference_error:
        for operation in operations:
            with pytest.raises(type(reference_error)) as actual_error:
                operation()
            assert str(actual_error.value) == str(reference_error), identifier
        return None
    for operation, reference in zip(operations, expected):
        np.testing.assert_array_equal(operation(), reference, err_msg=identifier)
    return expected


@pytest.mark.parametrize('length_m,N', _SPACING_CASES)
def test_all_256_corner_classifications(length_m, N):
    for bits in range(256):
        phi = np.array([1. if bits & (1 << corner) else -1. for corner in range(8)]).reshape(2, 2, 2)
        _compare_sides(phi, .37, .12, length_m, N, f'corner-{bits}')


@pytest.mark.parametrize('length_m,N', _SPACING_CASES)
def test_near_zero_case13_keeps_the_adjacent_valid_surface(length_m, N):
    # The first cube reaches the diagnostic branch; the next cube still has a surface.
    phi = np.array([
        [[-1.5e-14, 1e-14, 1.], [1., -.75, 1.]],
        [[1e-14, -2e-14, 1.], [-1., 1., 1.]],
    ])
    expected = _compare_sides(phi, 0., 0., length_m, N, 'case13-near-zero-continue')
    assert expected is not None and np.all(expected[0] > 0.)


@pytest.mark.parametrize('length_m,N', _SPACING_CASES)
@pytest.mark.parametrize('level', [0., 1., -1., np.nextafter(0., 1.), np.nextafter(0., -1.)])
def test_exact_and_adjacent_level_ties(length_m, N, level):
    x, y, _ = np.indices((4, 5, 6))
    phi = (x - y).astype(np.float64)
    _compare_sides(phi, 0., level, length_m, N, f'tie-{level}')


@pytest.mark.parametrize('length_m,N', _SPACING_CASES)
def test_random_noncubic_and_noncontiguous_phi(length_m, N):
    rng = np.random.default_rng(20261110)
    for number, shape in enumerate(((3, 4, 5), (5, 3, 6), (4, 6, 3), (3, 5, 4))):
        phi = rng.normal(size=shape)
        if number % 2:
            phi = phi[:, :, ::-1]
        before = phi.copy()
        _compare_sides(phi, .23, .12, length_m, N, f'random-{shape}-{number}')
        np.testing.assert_array_equal(phi, before)


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('length_m,N', _SPACING_CASES)
def test_mc_conversion_accepts_supported_input_precisions(dtype, length_m, N):
    rng = np.random.default_rng(20261111)
    phi = rng.normal(size=(4, 3, 5)).astype(dtype)
    before = phi.copy()
    _compare_sides(phi, .31, -.11, length_m, N, f'conversion-{dtype.__name__}')
    np.testing.assert_array_equal(phi, before)


@pytest.mark.parametrize('level', [1., 1. + 1e-10])
def test_float32_collapse_preserves_the_original_error(level):
    phi = np.array([1. - 1e-9, 1. + 1e-9] * 4).reshape(2, 2, 2)
    assert float(phi.min()) < level < float(phi.max())
    assert np.unique(phi.astype(np.float32)).size == 1
    with pytest.raises(RuntimeError, match='No surface found at the given iso value.'):
        _reference_sides(phi, 0., level, .007, 13.5)
    assert _compare_sides(phi, 0., level, .007, 13.5, 'float32-collapse') is None


@pytest.mark.parametrize('C,delta', [(3., 0.), (.3, 5.), (.3, -5.)])
def test_disappeared_interfaces_remain_zero(C, delta):
    phi = np.linspace(-1., 1., 24).reshape(2, 3, 4)
    expected = _compare_sides(phi, C, delta, .007, 13.5, 'disappeared-interface')
    assert expected is not None
    np.testing.assert_array_equal(expected[0], [0., 0.])
    np.testing.assert_array_equal(expected[1], [0., 0.])


@pytest.mark.parametrize('topology,N', [('Diamond', 16), ('Gyroid', 16), ('Diamond', 32), ('Gyroid', 32)])
@pytest.mark.parametrize('delta', [.22, -.17])
def test_tpms_phi_uses_both_distinct_side_surfaces(topology, N, delta):
    reference_phi = geometry_reference._phi_grid(topology, N)
    phi = tpms_geometry._phi_grid(topology, N)
    np.testing.assert_array_equal(phi, reference_phi)
    C = float(geometry_reference._C_from_tL(topology, .6 / 7.))
    expected = _compare_sides(phi, C, delta, .007, N, f'{topology}-{N}-{delta}')
    assert expected is not None and np.all(expected[0] > 0.)
    assert expected[0][0] != expected[0][1]


def _reference_voxel(phi, C, delta, length_m, N):
    lower, upper = delta - C, delta + C
    solid = (phi >= lower) & (phi <= upper)
    a, b = phi < lower, phi > upper
    epsilon = (float(np.mean(a)), float(np.mean(b)))
    areas = []
    for phase in (a, b):
        faces = 0
        for axis in range(3):
            first, second = [slice(None)] * 3, [slice(None)] * 3
            first[axis], second[axis] = slice(None, -1), slice(1, None)
            first, second = tuple(first), tuple(second)
            faces += int(np.sum(solid[first] & phase[second]))
            faces += int(np.sum(phase[first] & solid[second]))
        areas.append(faces * (length_m / N) ** 2 / (length_m ** 3 * tpms_geometry._AREA_CORRECTION))
    diameters = tuple(4. * eps / area if area > 0. else 0. for eps, area in zip(epsilon, areas))
    wall_area = .5 * (areas[0] + areas[1])
    thickness = (1. - sum(epsilon)) / wall_area if wall_area > 0. else 0.
    return (*epsilon, sum(epsilon)), areas, diameters, thickness


def _compare_voxel(phi, C, delta, length_m=.007, N=13.5):
    epsilon, areas, diameters, thickness = _reference_voxel(phi, C, delta, length_m, N)
    np.testing.assert_array_equal(asym_geometry.eps_sides(phi, C, delta), epsilon)
    np.testing.assert_array_equal(asym_geometry.a0_sides(phi, C, delta, length_m, N), areas)
    np.testing.assert_array_equal(asym_geometry.dh_sides(phi, C, delta, length_m, N), diameters)
    assert asym_geometry.wall_thickness(phi, C, delta, length_m, N) == thickness


def test_float32_negative_C_uses_the_original_weak_comparison():
    phi = np.array([-.75, .5, 1., 1.] * 2, dtype=np.float32).reshape(2, 2, 2)
    C = -.5 - 1e-10
    assert _reference_voxel(phi, C, 0., .007, 13.5)[0] == (.25, .75, 1.)
    _compare_voxel(phi, C, 0.)
    _compare_sides(phi, C, 0., .007, 13.5, 'float32-negative-C')


_SCALAR_TYPES = [float, np.float16, np.float32, np.float64]


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('C_type', _SCALAR_TYPES)
@pytest.mark.parametrize('delta_type', _SCALAR_TYPES)
def test_raw_array_and_scalar_precision_combinations(dtype, C_type, delta_type):
    phi = np.array([-1., -.75, -.5, -.375, .375, .5, .625, 1.], dtype=dtype).reshape(2, 2, 2)
    C, delta = C_type(.5 + 1e-10), delta_type(.125 + 1e-10)
    _compare_voxel(phi, C, delta)
    _compare_sides(phi, C, delta, .007, 13.5, 'array-scalar-precision')
    epsilon, areas, _, _ = _reference_voxel(phi, C, delta, .007, 13.5)
    _, diameters = _reference_sides(phi, C, delta, .007, 13.5)
    _, reference_areas, _, _ = _reference_voxel(phi, C, 0., .007, 13.5)
    _, reference_diameters = _reference_sides(phi, C, 0., .007, 13.5)
    expected_split = epsilon[0] / (epsilon[0] + epsilon[1])
    assert _native_geometry.split_a(phi, C, delta) == expected_split
    prepared = _native_geometry.prepare_raw_sides(
        phi, C, delta, .007, 13.5, tpms_geometry._AREA_CORRECTION)
    assert prepared['split_A'] == expected_split
    for number, side in enumerate(('A', 'B')):
        np.testing.assert_array_equal(prepared['side_geometry'][side],
                                      (areas[number], diameters[number],
                                       reference_areas[number], reference_diameters[number]))


@pytest.mark.parametrize('scalar_type,value,offset', [
    (np.float16, -1., 1e-5), (np.float16, 1., 1e-5),
    (np.float16, 0., 2. ** -26), (np.float16, 2. ** -24, 2. ** -26),
    (np.float16, 2. ** -14, 2. ** -26), (np.float16, 65504., 1.),
    (np.float32, -1., 1e-9), (np.float32, 1., 1e-9),
    (np.float32, 2. ** -149, 2. ** -151),
])
def test_numpy_level_scalar_retains_its_outer_extrema_comparison(scalar_type, value, offset):
    phi = np.array([value - offset, value + offset] * 4).reshape(2, 2, 2)
    level = scalar_type(value)
    expected = _compare_sides(phi, scalar_type(0.), level, .007, 13.5, 'scalar-extrema-guard')
    assert expected is not None
    np.testing.assert_array_equal(expected[0], [0., 0.])


@pytest.mark.parametrize('value', [1., 1. + 2. ** -10, 1. + 2. ** -9])
def test_half_precision_outer_guard_rounds_ties_to_even(value):
    phi = np.array([value - 2. ** -11, value + 2. ** -11] * 4).reshape(2, 2, 2)
    _compare_sides(phi, np.float16(0.), np.float16(value), .007, 13.5, 'half-tie-extrema')


@pytest.mark.parametrize('scalar_type', _SCALAR_TYPES)
def test_raw_zero_delta_has_no_side_geometry(scalar_type):
    prepared = _native_geometry.prepare_raw_sides(
        np.empty((0, 0, 0), dtype=np.float32), scalar_type(.5), scalar_type(0.), 0., 0., 0.)
    assert prepared == {'split_A': .5, 'side_geometry': None}
