"""Thermal face edits must not change the completed SIMPLE state."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models.field_coordinates_3d import (
    _balance_stream_outflow, _solver_staggered_to_real,
)
from sjtu_tpmshx.models.grid_3d import _resolve_axis_map


@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('shape', [(3, 4, 5), (1, 4, 1)])
def test_thermal_face_balancing_preserves_simple_state(direction, shape):
    widths = tuple(np.arange(1., n + 1.) for n in shape)
    axes = _resolve_axis_map(dict(dir=direction), *shape,
                             *(a.sum() for a in widths), *widths)
    nx, ny, nz = (axes['solver_init'][key] for key in ('Nx', 'Ny', 'Nz'))
    solver = SimpleNamespace(
        u=np.full((nx + 1, ny, nz), .2),
        v=np.broadcast_to(np.linspace(1., 2., ny + 1)[None, :, None],
                          (nx, ny + 1, nz)).copy(),
        w=np.full((nx, ny, nz + 1), .3))
    original = [a.copy() for a in (solver.u, solver.v, solver.w)]
    faces = _solver_staggered_to_real(solver, axes, shape)
    before = [a.copy() for a in faces]
    _balance_stream_outflow(faces, axes, np.ones(shape), *widths)

    axis = direction // 2
    outlet = 0 if direction % 2 else -1
    sign = -1. if direction % 2 else 1.
    np.testing.assert_allclose(np.take(faces[axis], outlet, axis=axis), sign)
    expected = before[axis].copy()
    end = [slice(None)] * 3
    end[axis] = outlet
    expected[tuple(end)] = sign
    np.testing.assert_array_equal(faces[axis], expected)
    for current, saved in zip((solver.u, solver.v, solver.w), original):
        np.testing.assert_array_equal(current, saved)
    for face in faces:
        assert face.flags.c_contiguous
        face += 10.  # Transverse faces must also belong to thermal preparation.
    for current, saved in zip((solver.u, solver.v, solver.w), original):
        np.testing.assert_array_equal(current, saved)
