"""Stored native 3D face arrays drive metrics, including physical W units."""
import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.metrics import evaluate


def test_three_d_native_faces_and_pressure():
    pressure = dict(P=np.array([[[100.], [20.]]]), dx=np.array([1.]),
                    dy=np.array([1., 1.]), dz=np.array([1.]),
                    inlet_frac=np.ones((1, 1)), outlet_frac=np.ones((1, 1)))
    report = dict(inlet_weights=np.ones((1, 1))*99., outlet_weights=np.ones((1, 1))*99., direction=0)
    mass = (np.ones((3, 1, 1)), np.zeros((2, 2, 1)), np.zeros((2, 1, 2)))
    result = FieldResult(result_id='3d-native', case_id='case', backend_id='fixture',
        grid={'dx': np.ones(2), 'dy': np.ones(1), 'dz': np.ones(1)},
        fields={'Ta': np.array([[[350.]], [[320.]]]), 'Tb': np.array([[[310.]], [[330.]]])},
        boundary_fluxes={'model_h': {'A': {'x-': np.array([-20.]), 'x+': np.array([10.])},
                                    'B': {'x-': np.array([-10.]), 'x+': np.array([20.])}},
                         'mass_A': mass, 'mass_B': tuple(-face for face in mass),
                         'report': {'A': report, 'B': {**report, 'direction': 1}}},
        pressure_evidence={'A': pressure, 'B': pressure},
        metadata={'dimension': 3, 'thermal_mode': 'model_h',
                  'diagnostics': {'model_h_balance': {'sides': {side: {'physical_boundary_complete': True} for side in ('A', 'B')}}},
                  'reporting_reference': {'Q': -999., 'dP_A': -999., 'T_out_A': -999.}})
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == 10.
    assert metrics['Q'].spec.unit == 'W'
    assert metrics['dP_A'].value == 160.
    assert metrics['T_out_A'].value == 320.
    assert metrics['T_out_B'].value == 310.
    assert metrics['mass_flow_A'].value == 1.
    assert metrics['energy_imbalance_rel'].value == 0.
    assert metrics['mass'].status == 'insufficient_data'


def test_three_d_outlet_ignores_reverse_flow_and_uses_native_enthalpy():
    from dataclasses import replace
    mx = np.array([[[2.], [0.]], [[2.], [-1.]]])
    mass = (mx, np.zeros((1, 3, 1)), np.zeros((1, 2, 2)))
    report = dict(direction=0, inlet_weights=np.ones((2, 1))*99.,
                  outlet_weights=np.array([[2.], [1.]]), h_in_J_kg=999., h_out_J_kg=np.zeros((2, 1)))
    result = FieldResult(result_id='reverse', case_id='case', backend_id='fixture',
        grid={'dx': np.ones(1), 'dy': np.ones(2), 'dz': np.ones(1)},
        fields={'Ta': np.array([[[300.], [900.]]]), 'Tb': np.array([[[350.], [600.]]])},
        boundary_fluxes={'mass_A': mass, 'mass_B': mass, 'report': {'A': report, 'B': report},
            'true_h': {**{f'mass_flux_{side}': mass for side in ('A', 'B')},
                       'h_A': np.array([[[100.], [900.]]]), 'h_B': np.array([[[150.], [600.]]]),
                       'h_in_A': 200., 'h_in_B': 100.}},
        metadata={'dimension': 3, 'thermal_mode': 'true_h'})
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == 400.  # 3 kg/s enters at h=200; 2 leaves at h=100.
    assert metrics['Q_A'].value == 400.
    assert metrics['Q_B'].value == 0.
    assert metrics['T_out_A'].value == 300.
    assert metrics['mass_flow_A'].value == 3.
    assert metrics['mass_imbalance_rel_A'].value == 1./3.
    assert metrics['energy_imbalance_rel'].value == 1.
    bad = [face.copy() for face in mass]
    bad[0][-1, 0, 0] = np.nan
    invalid = evaluate(replace(result, boundary_fluxes={**result.boundary_fluxes, 'mass_A': tuple(bad)})).metrics
    assert invalid['T_out_A'].status == 'invalid'
