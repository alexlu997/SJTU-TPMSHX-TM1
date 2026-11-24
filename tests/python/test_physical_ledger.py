"""Physical ports retain their declared meaning."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.physical_ledger import ports_complete


@pytest.mark.parametrize('dimension,direction', [(d, direction) for d in (2, 3) for direction in range(2*d)])
def test_actual_boundary_mass_requires_open_prescribed_ports(dimension, direction):
    shape = (2,) * dimension
    mass = [np.zeros(tuple(n + (d == axis) for d, n in enumerate(shape)))
            for axis in range(dimension)]
    plane_shape = tuple(n for d, n in enumerate(shape) if d != direction // 2)
    opening = np.ones(plane_shape)
    stream = mass[direction // 2]
    stream[:] = 1. if direction % 2 == 0 else -1.
    assert ports_complete(mass, direction, opening, opening)
    closed = opening.copy()
    closed.flat[0] = 0.
    assert not ports_complete(mass, direction, closed, opening)
    assert not ports_complete(mass, direction, opening, closed)
    stream *= -1.
    assert not ports_complete(mass, direction, opening, opening)
    stream *= -1.
    other = (direction // 2 + 1) % dimension
    mass[other].flat[0] = 1.
    assert not ports_complete(mass, direction, opening, opening)
