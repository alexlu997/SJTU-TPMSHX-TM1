"""Lazy reductions retain side/fine isolation and expire after one evaluate."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.shared.domain.field_result import FieldResult
from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec
from sjtu_tpmshx.shared.domain.portable_data import mutable_data
from sjtu_tpmshx.postprocess import api
from sjtu_tpmshx.development.tests.native.result_reference import api as reference


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
        flux = dict(model_h={side: {'x-': np.array([[-sign*10.], [0.]]), 'x+': np.zeros((2, 1)),
                                  **{name: np.zeros(shape) for name, shape in (
                                      ('y-', (2, 1)), ('y+', (2, 1)),
                                      ('z-', (2, 2)), ('z+', (2, 2)))}}
                             for side, sign in (('A', 1), ('B', -1))})
    return FieldResult(result_id='reductions', case_id='case', backend_id='fixture',
        boundary_fluxes=dict(flux, mass_A=mass, mass_B=mass),
        metadata=dict(dimension=dimension, thermal_mode='model_h', diagnostics=dict(
            richardson_info=dict(extrapolated=True), solver_converged=False,
            residual=np.nan, model_h_balance=dict(sides={
                side: dict(physical_boundary_complete=True) for side in ('A', 'B')}))))


@pytest.mark.parametrize('dimension', [2, 3])
def test_side_and_fine_reductions_are_isolated_across_evaluations(dimension):
    result = native_result(dimension)
    for _ in range(2):
        values = api.evaluate(result).metrics
        assert values['Q'].value == values['Q_A'].value == 10.
        assert values['Q_B'].value == -10.
        assert values['energy_imbalance_rel'].value == 0.
        for side in ('A', 'B'):
            assert values['mass_flow_'+side].value == 2.
            assert values['mass_imbalance_rel_'+side].value == 0.
            if dimension == 2:
                assert values['Q_richardson_'+side].value == 14.


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('callback_fails', [False, True])
def test_reduction_event_counts_match_success_and_failure_cache(dimension, callback_fails):
    result = native_result(dimension)
    flux = mutable_data(result.boundary_fluxes)
    for level in (flux, flux['fine']) if dimension == 2 else (flux,):
        balance = level.get('model_h', level.get('model_h_balance'))
        for side in ('A', 'B'):
            if dimension == 2:
                balance[side]['h_faces_W_per_m'][0][0, :] = np.finfo(float).max
            else:
                balance[side]['x-'][:] = np.finfo(float).max
    result = replace(result, boundary_fluxes=flux)

    def count(evaluate):
        events = []
        def callback(message, flag):
            events.append((message, flag))
            if callback_fails:
                raise ValueError('test reduction callback')
        previous = np.geterrcall()
        np.seterrcall(callback)
        try:
            with np.errstate(over='call', invalid='ignore'):
                evaluate(result)
                first = len(events)
                evaluate(result)
            assert first and len(events) == 2 * first
            return events
        finally:
            np.seterrcall(previous)

    assert count(api.evaluate) == count(reference.evaluate)


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
    single = api.evaluate(result, MetricSpec('Q_A', unit, 'native_boundary_v1')).metrics
    assert tuple(single) == ('Q_A',)
    assert single['Q_A'].value == 10.
    values = api.evaluate(result).metrics
    assert values['Q'].value == values['Q_A'].value == 10.
    status = 'insufficient_data' if failure == 'missing' else 'invalid'
    assert values['Q_B'].status == values['energy_imbalance_rel'].status == status
    if dimension == 2:
        assert values['Q_richardson_A'].status == 'insufficient_data'
        assert values['Q_richardson_B'].status == 'insufficient_data'
