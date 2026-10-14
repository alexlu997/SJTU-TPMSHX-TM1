"""Physical ports and borrowed ledger arrays retain their declared meaning."""
import ctypes as ct
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers.physical_ledger import ports_complete
from sjtu_tpmshx.solvers.backends.cpp.physical_ledger import HeatLedger, copy_heat_ledger, heat_ledger_query
from sjtu_tpmshx.solvers.backends.cpp.model_h import _Array


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


def test_unavailable_ledger_and_missing_native_capability_are_explicit():
    assert copy_heat_ledger(HeatLedger(), (2, 2, 1), 2) is None
    with pytest.raises(ValueError, match='lacks physical heat ledgers; rebuild'):
        heat_ledger_query(SimpleNamespace(), 2, ct.c_int)


def test_native_arrays_are_detached_and_bad_extents_fail():
    shape = (2, 2, 1)
    ledger = HeatLedger(available=1, physical_dimension=2, boundary_complete=1)
    ledger.solved[:] = (1, 0, 1)
    storage = []
    def view(size, value):
        array = np.full(size, value, dtype=np.float64)
        storage.append(array)
        return _Array(array.ctypes.data_as(ct.POINTER(ct.c_double)), size)
    for phase in (0, 2):
        ledger.residual[phase] = view(4, phase + 1.)
        for face, size in enumerate((2, 2, 2, 2, 4, 4)):
            ledger.advective_out[phase][face] = view(size, -face)
            ledger.diffusive_out[phase][face] = view(size, face)
    result = copy_heat_ledger(ledger, shape, 2)
    for array in storage:
        array[:] = 99.
    assert np.all(result['residual']['A'] == 1.)
    assert np.all(result['advective_out']['solid']['x+'] == -1.)
    assert result['residual']['B'] is result['source_integral']['B'] is None
    ledger.residual[0].size = 3
    with pytest.raises(RuntimeError, match='extent disagrees'):
        copy_heat_ledger(ledger, shape, 2)
