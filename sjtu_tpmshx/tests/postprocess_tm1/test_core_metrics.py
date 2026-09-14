"""Hand-checkable native fields, independent from solver-reported scalars."""
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.metrics import evaluate


def test_native_metrics_ignore_display_and_reported_scalars():
    def balance(q):
        return {'A': {'physical_boundary_complete': True, 'h_faces_W_per_m': (np.array([[q, q], [0., 0.], [q/2, q/2]]), np.zeros((2, 3)))},
                'B': {'physical_boundary_complete': True, 'h_faces_W_per_m': (np.array([[q/2, q/2], [0., 0.], [q, q]]), np.zeros((2, 3)))}}
    pressure = {'inlet_gauge_Pa': np.array([100., 200.]), 'outlet_gauge_Pa': np.array([10., 20.]),
                'inlet_fraction': np.array([.25, .75]), 'outlet_fraction': np.array([.5, .5]),
                'outlet_geom_frac': np.array([.3, .9])}
    mass = (np.array([[1., 3.], [1., 3.], [1., 3.]]), np.zeros((2, 3)))
    result = FieldResult(
        result_id='native', case_id='case', backend_id='fixture',
        grid={'dx': np.array([.1, .1]), 'dy': np.array([.1, .1])},
        fields={'Ta': np.array([[350., 360.], [300., 320.]]), 'Tb': np.ones((2, 2))*300.,
                'Ta_display': np.ones((2, 2))*1000.,
                'P_report_A': np.array([[100., 100.], [20., 20.]]),
                'P_report_B': np.array([[100., 100.], [20., 20.]])},
        boundary_fluxes={'mass_A': mass, 'mass_B': mass,
                         'model_h': balance(10.), 'fine': {'model_h_balance': balance(13.)}},
        pressure_evidence={'A': pressure, 'B': pressure},
        metadata={'dimension': 2, 'thermal_mode': 'model_h',
                  'parameters': {'dir_A': 0, 'dir_B': 0, 'boundary_openings': {
                      side: {'in_geom_frac': np.array([.25, .75]),
                             'out_geom_frac': np.array([.3, .9])} for side in ('A', 'B')}},
                  'diagnostics': {'richardson_info': {'extrapolated': True}},
                  'reporting_reference': {'Q_total': -999., 'T_out_A_K': -999.}})
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == 10.
    assert metrics['Q_A'].value == 10.
    assert metrics['Q_B'].value == -10.
    assert metrics['Q_richardson_A'].value == metrics['Q_richardson_B'].value == 14.
    assert metrics['Q'].spec.definition_version == 'native_boundary_v1'
    assert metrics['dP_A'].value == 160.
    assert metrics['dP_A'].spec.definition_version == 'pressure_face_v1'
    assert metrics['T_out_A'].value == 315.
    assert metrics['mass_flow_A'].value == 4.
    assert metrics['mass_imbalance_rel_A'].value == 0.
    assert metrics['energy_imbalance_rel'].value == 0.
    assert metrics['mass'].status == 'insufficient_data'
    missing = evaluate(replace(result, boundary_fluxes={})).metrics
    assert missing['Q'].status == 'insufficient_data'
    assert missing['T_out_A'].status == 'insufficient_data'
    bad = balance(10.)
    bad['A']['h_faces_W_per_m'][0][0, 0] = np.nan
    invalid = evaluate(replace(result, boundary_fluxes={**result.boundary_fluxes, 'model_h': bad})).metrics
    assert invalid['Q'].status == 'invalid'
    assert invalid['Q_B'].value == -10.  # A may not borrow the finite B duty.
    from sjtu_tpmshx.domain.metric_spec import MetricSpec
    old_definition = evaluate(result, MetricSpec('Q', 'W/m')).metrics['Q']
    assert old_definition.status == 'unsupported'


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_pressure_uses_physical_faces_and_open_area_on_nonuniform_grid(direction):
    from sjtu_tpmshx.domain.metric_spec import MetricSpec
    stream, cross = np.array([.1, .3]), np.array([.02, .06, .12])
    sc, cc = np.cumsum(stream) - stream/2, np.cumsum(cross) - cross/2
    if direction in (1, 3):
        sc = stream.sum() - sc
    p = 1000. - 100.*sc[None, :] + 20.*cc[:, None]
    dx, dy = cross, stream
    if direction in (0, 1):
        p, dx, dy = p.T, dy, dx
    result = FieldResult(result_id='pressure', case_id='case', backend_id='fixture',
        grid={'dx': dx, 'dy': dy}, fields={'P_report_A': p, 'P_report_B': p},
        metadata={'dimension': 2, 'parameters': {'dir_A': direction, 'dir_B': direction,
            'boundary_openings': {side: {'in_geom_frac': np.array([1., 1., 0.]),
                                        'out_geom_frac': np.array([0., 1., 1.])}
                                  for side in ('A', 'B')}}})
    metrics = evaluate(result, MetricSpec('dP', 'Pa', definition_version='pressure_face_v1')).metrics
    # Exact means of a linear pressure field over inlet [0,.08] and outlet [.02,.2].
    assert metrics['dP_A'].value == pytest.approx(100.*.4 + 20.*(.04-.11))
    assert metrics['dP_B'].value == pytest.approx(metrics['dP_A'].value)


def test_postprocessing_imports_no_backend():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from sjtu_tpmshx.postprocess.metrics import evaluate
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
'''], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
