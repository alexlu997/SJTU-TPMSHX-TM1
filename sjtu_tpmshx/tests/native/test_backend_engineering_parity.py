"""User acceptance: 0.1% duties/pressure/flow and 0.01 K temperatures.

Both public backends consume one prepared case and must independently satisfy
their physical gates. These checks supplement the existing tighter regressions.
"""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.native import test_cpp_full_3d as native_3d
from sjtu_tpmshx.tests.native.test_native_execution import _config

native_path = native_3d.native_path


def _physical_gates(result):
    assert result.run_status['converged'], result.run_status
    diagnostics = result.metadata['diagnostics']
    if result.metadata['thermal_mode'] == 'true_h':
        balance = diagnostics['true_h_balance']
        assert balance['converged']
        assert max(balance['enthalpy_clip_counts']['total']) == 0
        settings = balance['effective_settings']
        for name in ('coupled', 'equation'):
            assert balance[name+'_energy_balance']['ratio'] <= settings[name+'_energy_tol']
    else:
        balance = diagnostics['model_h_balance']
        if 'main' in balance:
            assert balance['main']['passed'] and balance['fine']['passed']
        else:
            assert balance['converged'] and balance['physical_boundary_complete']
            for side in balance['sides'].values():
                scale = side['strict_normalization_W']
                assert abs(side['residual_sum_W']) / scale < .01
                assert side['residual_max_abs_W'] * balance['cell_count'] / scale < .01


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('pair', ['air-air', 'air-water', 'water-air', 'air-sco2',
                                  'sco2-air', 'water-sco2', 'sco2-water', 'sco2-sco2'])
def test_public_backends_meet_engineering_limits(native_path, dimension, pair, record_property):
    def fluid(name, side):
        return FluidConfig(type=name, u_mps=3. if name == 'air' else .2,
            T_in_K=(350. if name == 'water' else 500.) if side == 0 else 300.,
            P_in_Pa={'air': 2e5, 'water': 2e6, 'sco2': 12e6}[name])

    names = pair.split('-')
    config = replace(_config(dimension, True), fluid_A=fluid(names[0], 0), fluid_B=fluid(names[1], 1))
    prepared = prepare_case(config, case_id=f'backend-parity-{dimension}d-{pair}')
    python = run_case(prepared, RunControl())
    cpp = run_case(prepared, native_3d.control(native_path))
    for result in (python, cpp):
        _physical_gates(result)
    temperature_max = 0.
    for key in ('Ta', 'Tb', 'Ts'):
        assert cpp.fields[key].shape == python.fields[key].shape
        delta = float(np.max(np.abs(cpp.fields[key] - python.fields[key])))
        temperature_max = max(temperature_max, delta)
        assert np.isfinite(delta) and delta <= .01, (key, delta)
    cpp_metrics, python_metrics = evaluate(cpp).metrics, evaluate(python).metrics
    relative_max = outlet_max = 0.
    for key in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'mass_flow_A', 'mass_flow_B', 'T_out_A', 'T_out_B'):
        a, b = cpp_metrics[key], python_metrics[key]
        assert a.status == b.status == 'available', (key, a.reason, b.reason)
        assert a.spec.unit == b.spec.unit and np.isfinite([a.value, b.value]).all()
        delta = abs(a.value-b.value)
        if key.startswith('T_out'):
            outlet_max = max(outlet_max, delta)
            assert delta <= .01, (key, delta)
        else:
            scale = max(abs(a.value), abs(b.value))
            relative_max = max(relative_max, delta/scale if scale else 0.)
            assert delta <= .001 * scale, (key, a.value, b.value)
    record_property('max_temperature_difference_K', temperature_max)
    record_property('max_outlet_difference_K', outlet_max)
    record_property('max_metric_relative_difference', relative_max)
