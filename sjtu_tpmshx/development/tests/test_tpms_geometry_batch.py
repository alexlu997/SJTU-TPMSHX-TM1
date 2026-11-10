"""Batch geometry keeps exact scalar arithmetic, units and result ownership."""
import numpy as np
import pytest

from sjtu_tpmshx.shared.models import tpms_geometry, tpms_props
from sjtu_tpmshx.development.tests import geometry_reference as reference


# Retained graded-field inputs exposed array-power rounding differences.
_LENGTHS = np.array([4., 7., 8., 6.8216277173913022,
                     6.8705650510204093, 6.9158631876663712])
_WALLS = np.array([.3, .6, .3, .54622559073723997,
                   .55005178571428581, .55492907439913597])


def _scan_reference(tpms, length, wall, n):
    """Keep the original scalar powers and direct voxel scans independent."""
    length, wall = float(length), float(wall)
    a, b = reference._C_COEFFS[tpms]
    ratio = wall / length
    threshold = max(a * ratio + b * ratio**2, 0.)
    phi = reference._phi_grid(tpms, n)
    epsilon = reference._eps_from_C(phi, threshold)
    area = reference._A0_from_C(phi, threshold, length / 1000., n)
    side = .5 * epsilon
    return dict(epsilon=epsilon, epsilon_A=side, epsilon_B=side,
                A_0=area, D_h=4. * side / area)


@pytest.mark.parametrize('tpms', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('shape', [(6,), (2, 3), (1, 2, 3)])
@pytest.mark.parametrize('n', [32, 128])
def test_geometry_fields_equal_independent_scalar_scans(tpms, shape, n):
    lengths, walls = _LENGTHS.reshape(shape), _WALLS.reshape(shape)
    actual = tpms_geometry.compute_geometry_fields(tpms, lengths, walls, N=n)
    expected = {key: np.empty(shape) for key in actual}
    for index in np.ndindex(shape):
        reference = _scan_reference(tpms, lengths[index], walls[index], n)
        scalar = tpms_geometry.compute_geometry(
            tpms, float(lengths[index]), float(walls[index]), N=n)
        assert scalar == reference
        for key in actual:
            expected[key][index] = reference[key]
    for key in actual:
        np.testing.assert_array_equal(actual[key], expected[key])
        assert actual[key].flags.c_contiguous
        assert actual[key].flags.writeable


@pytest.mark.parametrize('layout', ['slice', 'fortran'])
def test_geometry_fields_own_inputs_and_outputs(layout):
    lengths, walls = _LENGTHS.reshape(2, 3), _WALLS.reshape(2, 3)
    if layout == 'slice':
        lengths, walls = (np.repeat(values, 2, axis=1)[:, ::2] for values in (lengths, walls))
    else:
        lengths, walls = np.asfortranarray(lengths), np.asfortranarray(walls)
    original_length, original_wall = lengths.copy(), walls.copy()
    first = tpms_props.geometry_fields('Gyroid', lengths, walls, 16.)
    second = tpms_props.geometry_fields('Gyroid', lengths, walls, 16.)
    for key in first:
        np.testing.assert_array_equal(first[key], second[key])
        assert first[key].flags.c_contiguous
        assert first[key].flags.writeable
        assert not np.shares_memory(first[key], second[key])
        assert not np.shares_memory(first[key], lengths)
        assert not np.shares_memory(first[key], walls)
    first['epsilon_A'][0, 0] = -1.
    assert first['epsilon_B'][0, 0] > 0.
    for values in first.values():
        values.fill(-1.)
    third = tpms_props.geometry_fields('Gyroid', lengths, walls, 16.)
    for key in third:
        np.testing.assert_array_equal(third[key], second[key])
    np.testing.assert_array_equal(lengths, original_length)
    np.testing.assert_array_equal(walls, original_wall)


@pytest.mark.parametrize('tpms', ['Diamond', 'Gyroid'])
def test_material_fields_follow_scalar_chi_priority_on_each_call(tpms, monkeypatch):
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    cases = [(None, None), ('.5', None), ('1.', None), ('invalid', .25)]
    for override, explicit in cases:
        if override is None:
            monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
        else:
            monkeypatch.setenv('TPMSHX_CHI_S', override)
        actual = tpms_props.geometry_fields(tpms, _LENGTHS, _WALLS, 22., chi_s=explicit)
        expected = {key: np.empty(_LENGTHS.shape) for key in actual}
        for index, (length, wall) in enumerate(zip(_LENGTHS, _WALLS)):
            scalar = tpms_props.geometry(tpms, float(length), float(wall), 22., chi_s=explicit)
            for key in expected:
                expected[key][index] = scalar[key]
        for key in actual:
            np.testing.assert_array_equal(actual[key], expected[key])
    monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    with pytest.raises(ValueError):
        tpms_props.geometry_fields(tpms, _LENGTHS, _WALLS, 22.)


@pytest.mark.parametrize('shape', [(0,), (2, 0), (2, 0, 3)])
def test_empty_geometry_fields_keep_shape(shape):
    fields = tpms_props.geometry_fields('Gyroid', np.empty(shape), np.empty(shape), 16.)
    assert set(fields) == {'epsilon', 'epsilon_A', 'epsilon_B', 'A_0', 'D_h', 'K_ss'}
    for values in fields.values():
        assert values.shape == shape
        assert values.dtype == np.float64
        assert values.flags.c_contiguous
        assert values.flags.writeable


@pytest.mark.parametrize('lengths,walls,match', [
    ([7., 8.], [.4], 'same array shape'),
    (7., .4, 'same array shape'),
    ([np.nan], [.4], 'finite'),
    ([7.], [np.inf], 'finite'),
    ([0.], [.4], 'L_mm must be positive'),
    ([7.], [0.], 't_mm must be positive'),
    ([4.], [2.], r'2\*t < L'),
    ([4.], [1.99], 'Degenerate TPMS geometry'),
])
def test_geometry_fields_reject_invalid_inputs(lengths, walls, match):
    with pytest.raises(ValueError, match=match):
        tpms_geometry.compute_geometry_fields('Gyroid', lengths, walls)


def test_geometry_fields_reject_unknown_topology():
    with pytest.raises(ValueError, match='Diamond.*Gyroid'):
        tpms_geometry.compute_geometry_fields('unknown', [7.], [.4])


@pytest.mark.parametrize('n', [0, True, 1.5])
def test_geometry_fields_reject_invalid_resolution(n):
    with pytest.raises(ValueError, match='positive integer'):
        tpms_geometry.compute_geometry_fields('Gyroid', [7.], [.4], N=n)
