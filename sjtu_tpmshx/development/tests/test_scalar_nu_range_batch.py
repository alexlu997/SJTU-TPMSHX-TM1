"""Batch notices must preserve the original sequence of scalar observations."""
from contextlib import nullcontext
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.shared.domain.run_warnings import (
    cache_warning_records, merge_warnings, range_context, range_observations,
    warning_messages, warning_scope,
)
from sjtu_tpmshx.shared.models import nu_correlations as nu
from sjtu_tpmshx.development.tests.result_warning_reference import record_range


def _scalar_loop(tpms_type, values):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(nu, 'record_range', record_range)
        for raw in np.asarray(values, dtype=np.float64).flat:
            value = float(raw)
            nu._warn_extrap(tpms_type, value, value, value)


def _capture(monkeypatch, evaluate, values, *, run, cache, surrounding=False,
             registry=()):
    monkeypatch.setattr(nu, '_EXTRAP_WARNED', set(registry))
    records = {} if run else None
    cached = {} if cache else None
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always')
        with warning_scope(records), (
                cache_warning_records(cached) if cache else nullcontext()):
            with range_context(side='A', stage='inlet', layout='scalar-zoned-call'):
                if surrounding:
                    _scalar_loop('Gyroid', [20_000., np.nan])
                evaluate('Gyroid', values)
                if surrounding:
                    _scalar_loop('Gyroid', [600.])
    replayed = {}
    with range_context(side='B', stage='replayed', layout='scalar-zoned-call'):
        merge_warnings(replayed, [cached or {}], bind_context=True)
    return dict(
        records=records, cached=cached, replayed=replayed,
        observations=range_observations(records or {}),
        last=range_observations(records or {}, last=True),
        messages=list(warning_messages(records or {})),
        replay_observations=range_observations(replayed),
        replay_last=range_observations(replayed, last=True),
        replay_messages=list(warning_messages(replayed)),
        notices=[(notice.category, str(notice.message)) for notice in notices],
        registry=nu._EXTRAP_WARNED.copy())


_VALUES = [
    pytest.param(np.array([]), id='empty'),
    pytest.param(np.array(500.), id='scalar'),
    pytest.param(np.array([400., 16_000., 500., 400.]), id='bounds'),
    pytest.param(np.array([700., 20_000., 300., 500.]), id='first-high'),
    pytest.param(np.array([700., 300., 20_000., 200.]), id='first-low'),
    pytest.param(np.array([-0., 0., 20_000., -0., 20_000.]), id='ties'),
    pytest.param(np.array([np.nan, np.inf, -np.inf, np.nan]), id='all-nonfinite'),
    pytest.param(np.array([np.inf, -np.inf, 800., 300., 20_000., np.nan]),
                 id='nonfinite-before-finite-worst'),
    pytest.param(np.array([0., .1, 500.]), id='raw-before-floor'),
    pytest.param(np.array([
        [np.nan, 500., 30_000.], [300., np.inf, 400.],
        [-np.inf, 30_000., 300.],
    ]).T[::-1], id='noncontiguous-multidimensional'),
]


@pytest.mark.parametrize('values', _VALUES)
@pytest.mark.parametrize('run,cache', [(False, False), (True, False),
                                     (False, True), (True, True)])
@pytest.mark.parametrize('surrounding', [False, True])
def test_batch_matches_scalar_records_replay_and_notices(
        monkeypatch, values, run, cache, surrounding):
    before = values.copy()
    expected = _capture(monkeypatch, _scalar_loop, values, run=run, cache=cache,
                        surrounding=surrounding)
    actual = _capture(monkeypatch, nu.record_air_nu_scalar_ranges, values,
                      run=run, cache=cache, surrounding=surrounding)
    assert actual == expected
    np.testing.assert_array_equal(values, before)


@pytest.mark.parametrize('cache', [False, True])
@pytest.mark.parametrize('registry', [(), (('Gyroid', 'lo'),),
                                    (('Gyroid', 'hi'),),
                                    (('Gyroid', 'lo'), ('Gyroid', 'hi'))])
def test_batch_keeps_standalone_first_warning_text_and_order(
        monkeypatch, cache, registry):
    values = np.array([np.nan, np.inf, 20_000., -np.inf, 300., 800.])
    expected = _capture(monkeypatch, _scalar_loop, values, run=False,
                        cache=cache, registry=registry)
    actual = _capture(monkeypatch, nu.record_air_nu_scalar_ranges, values,
                      run=False, cache=cache, registry=registry)
    assert actual == expected


def test_batch_keeps_scalar_worst_and_final_sample():
    with warning_scope({}) as records, range_context(
            side='A', stage='inlet', layout='scalar-zoned-call'):
        nu.record_air_nu_scalar_ranges('Diamond', [800., 20_000., 0., np.inf, 500.])
    row, = range_observations(records)
    assert row['shape'] == ()
    assert row['minimum'] == (0., ()) and row['maximum'] == (20_000., ())
    assert (row['low'], row['high'], row['size'], row['nonfinite']) == (0, 1, 1, 1)
    last, = range_observations(records, last=True)
    assert last['minimum'] == last['maximum'] == (500., ())
    assert (last['low'], last['high'], last['size'], last['nonfinite']) == (0, 0, 1, 0)


def test_batch_records_a_bounded_number_of_scalar_samples(monkeypatch):
    calls = []
    original = nu._warn_extrap

    def observe(tpms_type, minimum, maximum, raw):
        calls.append(raw)
        return original(tpms_type, minimum, maximum, raw)

    monkeypatch.setattr(nu, '_warn_extrap', observe)
    values = np.tile([np.nan, np.inf, -np.inf, 300., 20_000., 500., 600., 700.], 1000)
    with warning_scope({}):
        nu.record_air_nu_scalar_ranges('Gyroid', values.reshape(20, 20, 20))
    assert 1 <= len(calls) <= 8
    assert calls[-1] == values[-1]
