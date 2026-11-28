"""Synthetic, explicitly non-physical CaseData shared by file tests."""
import numpy as np

from tm1.data_types.case_data import CaseData
from tm1.data_types.model_refs import ModelRef


def sample_case():
    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'))
    for axis in 'xy':
        grid['d' + axis] = np.array([.1, .2])
        grid[axis + '_edges'] = np.r_[0., np.cumsum(grid['d' + axis])]
    return CaseData('synthetic', grid=grid, design_fields={'eps_arr': np.full((2, 2), .7)},
                    model_refs=(ModelRef('geometry', 'v2-5f1cafb'),),
                    metadata={'warning': '人工样例', 'diagnostic': float('nan'), 'bytes': b'abc',
                              'collision': {'array': 'ordinary user mapping'}})
