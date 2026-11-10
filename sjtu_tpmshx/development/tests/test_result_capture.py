"""The model-h capture uses the independent original area reduction."""
import ctypes as ct

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.cpp import model_h


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
@pytest.mark.parametrize('reverse', [False, True])
def test_model_h_capture_area_keeps_original_reduction(dtype, reverse):
    widths = [np.array([.001, .0023, .00017], dtype=dtype),
              np.array([.00051, .0017], dtype=dtype)]
    if reverse:
        widths = [values[::-1] for values in widths]
    masses = [np.zeros((4, 2)), np.zeros((3, 3))]
    result = model_h._Result()
    owners = []
    empty = (ct.c_double * 1)()
    result.plane.solid_residual.data = empty
    for side in result.plane.sides:
        for view in (*side.boundary_mass_out, *side.boundary_h_out,
                     side.inlet_conduction_faces, side.residual, side.linearization_defect):
            view.data = empty
        for view, mass in zip(side.h_faces, masses):
            owner = (ct.c_double * mass.size)()
            owners.append(owner)
            view.data, view.size = owner, mass.size
    captured = model_h._plane_info(result, (3, 2), widths, (masses, masses))
    assert captured['area_m2'] == float(np.sum(widths[0][:, None] * widths[1][None, :]))
    assert captured['cell_count'] == 6
    assert captured['dx_m'] == widths[0].tolist()
    assert captured['dy_m'] == widths[1].tolist()
