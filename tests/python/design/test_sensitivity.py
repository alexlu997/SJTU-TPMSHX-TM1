"""Air sensitivity estimates for a fixed screening case."""
import numpy as np

from tm1.applications.design.sensitivity import sweep_axis, sweep_row
from tm1.physical_models.tpms_calc import compute


def test_ratio_grid_matches_air_point_queries():
    fixed = dict(tpms='Gyroid', u_A=12., T_in=365., P_in=101325.)
    thicknesses = sweep_axis('t', 3)
    for size in sweep_axis('L_cell', 3):
        row, failures, first_error = sweep_row(fixed, 'L_cell', size, 't', thicknesses, 'ratio')
        assert failures == 0 and first_error == ''
        expected = []
        for thickness in thicknesses:
            point = compute('Gyroid', size, thickness, 12., 365., 101325., 16.)
            expected.append(point['H_sf'] * point['A_0'] / point['dP_per_L'])
        np.testing.assert_array_equal(row.view(np.uint64), np.array(expected).view(np.uint64))
