"""Stored native 3D face arrays drive metrics, including physical W units."""
import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.metrics import evaluate


def test_three_d_native_faces_and_pressure():
    pressure = dict(P=np.array([[[100.], [20.]]]), dx=np.array([1.]),
                    dy=np.array([1., 1.]), dz=np.array([1.]),
                    inlet_frac=np.ones((1, 1)), outlet_frac=np.ones((1, 1)))
    report = dict(inlet_weights=np.ones((1, 1)), outlet_weights=np.ones((1, 1)), direction=0)
    result = FieldResult(result_id='3d-native', case_id='case', backend_id='fixture',
        grid={'dx': np.ones(2), 'dy': np.ones(1), 'dz': np.ones(1)},
        fields={'Ta': np.array([[[350.]], [[320.]]]), 'Tb': np.array([[[310.]], [[330.]]])},
        boundary_fluxes={'model_h': {'A': {'x-': np.array([-20.]), 'x+': np.array([10.])},
                                    'B': {'x-': np.array([-10.]), 'x+': np.array([20.])}},
                         'report': {'A': report, 'B': {**report, 'direction': 1}}},
        pressure_evidence={'A': pressure, 'B': pressure},
        metadata={'dimension': 3, 'thermal_mode': 'model_h',
                  'diagnostics': {'model_h_balance': {'sides': {'A': {'physical_boundary_complete': True}}}},
                  'reporting_reference': {'Q': -999., 'dP_A': -999., 'T_out_A': -999.}})
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == 10.
    assert metrics['Q'].spec.unit == 'W'
    assert metrics['dP_A'].value == 160.
    assert metrics['T_out_A'].value == 320.
    assert metrics['T_out_B'].value == 310.
    assert metrics['energy_imbalance_rel'].value == 0.
    assert metrics['mass'].status == 'insufficient_data'
