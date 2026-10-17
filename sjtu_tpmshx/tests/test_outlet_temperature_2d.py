"""Outlet reporting contract; controlled fields, no PDE solves."""

import numpy as np
import pytest

from sjtu_tpmshx.result_math import _outlet_temperature_2d


@pytest.mark.parametrize('direction', range(4))
def test_real_face_mass_partial_nonuniform_outlet(direction):
    cross = np.array([.1, .2, .3, .15, .25])
    fraction = np.array([0., .2, .8, 1., .5])
    shape = (2, 5) if direction < 2 else (5, 2)
    temperature = np.full(shape, 290.)
    mass = [np.zeros((shape[0]+1, shape[1])), np.zeros((shape[0], shape[1]+1))]
    axis, edge = direction//2, 0 if direction % 2 else -1
    target = [slice(None), slice(None)]
    target[axis] = edge
    temperature[tuple(target)] = [999., 310., 370., 600., 800.]
    outward = 2*np.array([.2, .3, .4, .5, .6])*np.array([99., 3., 4., -2., 0.])*fraction*cross
    outward[0] = 99.  # A closed-face leak must not enter the reported outlet.
    mass[axis][tuple(target)] = outward * (-1 if direction % 2 else 1)
    snapshots = tuple(face.copy() for face in mass)
    # rho * single-side eps * (speed * opening fraction) * transverse width.
    m1, m2 = 2*.3*3*.2*.2, 2*.4*4*.8*.3
    expected = (m1*310. + m2*370.) / (m1+m2)
    assert _outlet_temperature_2d(temperature, mass, direction, fraction) == pytest.approx(expected)
    for actual, saved in zip(mass, snapshots):
        np.testing.assert_array_equal(actual, saved)


@pytest.mark.parametrize('outward', [0., -1., np.nan, np.inf])
def test_no_positive_outflow_or_nonfinite_mass_is_an_error(outward):
    mass = (np.full((3, 2), outward), np.zeros((2, 3)))
    with pytest.raises(ValueError, match='finite positive outward mass flow'):
        _outlet_temperature_2d(np.full((2, 2), 310.), mass, 0, np.ones(2))


def test_nonfinite_flowing_temperature_is_an_error():
    mass = (np.ones((3, 2)), np.zeros((2, 3)))
    with pytest.raises(ValueError, match='temperature is non-finite'):
        _outlet_temperature_2d(np.full((2, 2), np.nan), mass, 0, np.ones(2))
