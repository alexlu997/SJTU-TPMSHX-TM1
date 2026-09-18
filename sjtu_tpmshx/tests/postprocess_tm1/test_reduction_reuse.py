"""Lazy reductions retain side/fine isolation and expire after one evaluate."""
from collections import Counter
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.postprocess import metrics, three_d


def native_result(dimension):
    mass = (np.ones((3, 2)), np.zeros((2, 3)))
    if dimension == 2:
        def balance(q):
            return {side: dict(physical_boundary_complete=True,
                h_faces_W_per_m=(np.array([[sign*q, 0.], [0., 0.], [0., 0.]]),
                                  np.zeros((2, 3))))
                for side, sign in (('A', 1), ('B', -1))}
        flux = dict(model_h=balance(10.), fine=dict(model_h_balance=balance(13.)))
    else:
        mass = (*[face[:, :, None] for face in mass], np.zeros((2, 2, 2)))
        flux = dict(model_h={side: {'x-': np.array([-sign*10.]), 'x+': np.array([0.])}
                             for side, sign in (('A', 1), ('B', -1))})
    return FieldResult(result_id='reductions', case_id='case', backend_id='fixture',
        boundary_fluxes=dict(flux, mass_A=mass, mass_B=mass),
        metadata=dict(dimension=dimension, thermal_mode='model_h', diagnostics=dict(
            richardson_info=dict(extrapolated=True), solver_converged=False,
            residual=np.nan, model_h_balance=dict(sides={
                side: dict(physical_boundary_complete=True) for side in ('A', 'B')}))))


@pytest.mark.parametrize('dimension', [2, 3])
def test_each_successful_reduction_runs_once_per_evaluate(monkeypatch, dimension):
    owner = metrics if dimension == 2 else three_d
    heat_name = '_side_duty' if dimension == 2 else 'thermal_duty'
    original_heat, original_mass = getattr(owner, heat_name), owner._mass_flow
    calls = Counter()

    def heat(result, side, **kwargs):
        calls['heat', side, kwargs.get('fine', False)] += 1
        return original_heat(result, side, **kwargs)

    def mass(result, side):
        calls['mass', side] += 1
        return original_mass(result, side)

    monkeypatch.setattr(owner, heat_name, heat)
    monkeypatch.setattr(owner, '_mass_flow', mass)
    result = native_result(dimension)
    for invocation in (1, 2):
        values = metrics.evaluate(result).metrics
        assert values['Q'].value == values['Q_A'].value == 10.
        assert values['Q_B'].value == -10.
        assert values['energy_imbalance_rel'].value == 0.
        for side in ('A', 'B'):
            assert values['mass_flow_'+side].value == 2.
            assert values['mass_imbalance_rel_'+side].value == 0.
            assert calls['heat', side, False] == invocation
            assert calls['mass', side] == invocation
            if dimension == 2:
                assert values['Q_richardson_'+side].value == 14.
                assert calls['heat', side, True] == invocation


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('failure', ['missing', 'incomplete', 'nonfinite'])
def test_unavailable_other_side_and_fine_evidence_do_not_poison_main(dimension, failure):
    result = native_result(dimension)
    flux, metadata = mutable_data(result.boundary_fluxes), mutable_data(result.metadata)
    flux.pop('fine', None)
    if failure == 'missing':
        del flux['model_h']['B']
    elif failure == 'incomplete':
        balance = flux['model_h'] if dimension == 2 else metadata['diagnostics']['model_h_balance']['sides']
        balance['B']['physical_boundary_complete'] = False
    elif dimension == 2:
        flux['model_h']['B']['h_faces_W_per_m'][0][0, 0] = np.nan
    else:
        flux['model_h']['B']['x-'][0] = np.nan
    result = replace(result, boundary_fluxes=flux, metadata=metadata)
    unit = 'W/m' if dimension == 2 else 'W'
    single = metrics.evaluate(result, MetricSpec('Q_A', unit, 'native_boundary_v1')).metrics
    assert tuple(single) == ('Q_A',)
    assert single['Q_A'].value == 10.
    values = metrics.evaluate(result).metrics
    assert values['Q'].value == values['Q_A'].value == 10.
    status = 'insufficient_data' if failure == 'missing' else 'invalid'
    assert values['Q_B'].status == values['energy_imbalance_rel'].status == status
    if dimension == 2:
        assert values['Q_richardson_A'].status == 'insufficient_data'
        assert values['Q_richardson_B'].status == 'insufficient_data'
