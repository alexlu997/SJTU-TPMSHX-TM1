"""Compare shared preparation cache behavior with functools.lru_cache."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from threading import Event

import numpy as np
import pytest

from tm1.physical_models.preparation_cache import _ScalarCache


def inlet_cache(*, maxsize):
    return _ScalarCache(maxsize).wrap


class _String(str):
    pass


@pytest.mark.parametrize('calls', [
    [((1, 2), {}), ((1,), {'b': 2}), ((), {'a': 1, 'b': 2}),
     ((), {'b': 2, 'a': 1}), ((1, 2), {}), ((), {'a': 1, 'b': 2})],
    [(('Gyroid', value, .5), {}) for value in
     (np.float16(7), 7., np.float32(7), 7, np.float64(7))],
    [(('Gyroid', value, .5), {}) for value in
     (7., np.float16(7), np.float32(7), 7, np.float64(7))],
    [((value,), {}) for value in (None, None, (1, 2), (1., 2.))],
    [((), {'a': value}) for value in (1, True, 1., np.int32(1))],
], ids=['call-shapes', 'numpy-first', 'python-first', 'none-and-tuple', 'keyword-number'])
def test_call_keys_match_functools(calls):
    def describe(*args, **kwargs):
        return tuple(type(value) for value in args), tuple(
            (name, type(value)) for name, value in kwargs.items())

    cached = inlet_cache(maxsize=16)(describe)
    reference = lru_cache(maxsize=16)(describe)
    for args, kwargs in calls:
        assert cached(*args, **kwargs) == reference(*args, **kwargs)
        assert cached.cache_info() == reference.cache_info()


INLET = ('Gyroid', 7., .5, 5., 380., 101325., 'air', None, False)


@pytest.mark.parametrize('calls,misses', [
    ([INLET, INLET[:-1] + (0,), INLET[:-1] + (np.bool_(False),), INLET[:-1] + (True,),
      INLET[:-1] + (1,), INLET[:-1] + (1.,)], 2),
    ([INLET, INLET[:-2] + (_String('x'), False), INLET[:6] + ('water', None, False)], 3),
    ([(value,) for value in (1, True, 1., np.int64(1), np.bool_(True))], 1),
    ([(value,) for value in ('x', _String('x'))], 1),
], ids=['inlet-bool', 'inlet-text',
        'single-number', 'single-string'])
def test_equal_arguments_hit_and_distinct_arguments_miss(calls, misses):
    """Use value equality for every call shape, as the cached physical functions need."""
    cached = inlet_cache(maxsize=16)(lambda *args: args)
    results = [cached(*args) for args in calls]
    assert cached.cache_info() == (len(calls) - misses, misses, 16, misses)
    assert all(result == args for result, args in zip(results, calls))


def test_native_entries_serve_equal_python_calls():
    @inlet_cache(maxsize=2)
    def cached(*args):
        pytest.fail('The native entry must satisfy the equal Python call')

    cached.store(INLET, None, 'native inlet')
    assert cached('Gyroid', np.float64(7), np.float64(.5), *INLET[3:]) == 'native inlet'
    assert cached.lookup(INLET) == (True, 'native inlet')
    assert cached.lookup(INLET[:-1], {'co2_geometry': False}) == (False, None)
    assert cached.cache_info() == (2, 1, 2, 1)


@pytest.mark.parametrize('value', [[], {}, np.array([1])], ids=['list', 'dict', 'array'])
def test_unhashable_calls_do_not_change_statistics(value):
    for decorate in (inlet_cache, lru_cache):
        @decorate(maxsize=2)
        def cached(item):
            pytest.fail('Unhashable arguments must fail before calculation')

        with pytest.raises(TypeError, match='unhashable'):
            cached(value)
        assert cached.cache_info() == (0, 0, 2, 0)


def test_cache_management_and_exception_behavior_match_functools():
    def calculate(value):
        """Return the argument or reject a failed calculation."""
        if value == 'failure':
            raise ValueError('failed calculation')
        return value

    cached = inlet_cache(maxsize=2)(calculate)
    reference = lru_cache(maxsize=2)(calculate)
    assert cached.__wrapped__ is calculate
    assert cached.__name__ == calculate.__name__
    assert cached.__doc__ == calculate.__doc__
    assert cached.cache_parameters() == reference.cache_parameters()
    parameters = cached.cache_parameters()
    parameters['maxsize'] = 99
    assert cached.cache_parameters()['maxsize'] == 2
    for value in ('a', 'b', 'a', 'c', 'a', 'b', 'failure', 'failure'):
        if value == 'failure':
            for function in (cached, reference):
                with pytest.raises(ValueError, match='failed calculation'):
                    function(value)
        else:
            assert cached(value) == reference(value)
        assert cached.cache_info() == reference.cache_info()
    for function in (cached, reference):
        function.cache_clear()
    assert cached.cache_info() == reference.cache_info() == (0, 0, 2, 0)
    assert cached('a') == reference('a')
    assert cached.cache_info() == reference.cache_info()


def test_native_lookup_and_store_share_results_and_lru_order():
    @inlet_cache(maxsize=2)
    def cached(*args, **kwargs):
        pytest.fail('The native result must satisfy the Python call')

    @lru_cache(maxsize=2)
    def reference(*args, **kwargs):
        return kwargs.get('value', args[0] if args else None)

    for args, kwargs in [((1,), {}), ((), {'value': None}), ((1,), {}),
                         ((2,), {}), ((1,), {}), ((), {'value': None})]:
        before = reference.cache_info()
        expected = reference(*args, **kwargs)
        found, value = cached.lookup(args, kwargs)
        assert found == (reference.cache_info().hits > before.hits)
        if found:
            assert value == expected
        else:
            cached.store(args, kwargs, expected)
        assert cached.cache_info() == reference.cache_info()
        assert cached(*args, **kwargs) == reference(*args, **kwargs)
        assert cached.cache_info() == reference.cache_info()

    cached.cache_clear()
    cached.store(('a',), None, 'first')
    cached.store(('b',), None, 'second')
    cached.store(('a',), None, 'replacement')
    assert cached.cache_info() == (0, 0, 2, 2)
    cached.store(('c',), None, 'third')
    assert cached.lookup(('a',)) == (False, None)
    assert cached.lookup(('b',)) == (True, 'second')
    assert cached.lookup(('c',)) == (True, 'third')


def _concurrent_calls(decorate, clear=False):
    started = Event()
    release = Event()

    @decorate(maxsize=2)
    def cached(value):
        if value == 'a' and not started.is_set():
            started.set()
            assert release.wait(5)
            return 'late result'
        return value

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(cached, 'a')
        try:
            assert started.wait(5)
            if clear:
                cached.cache_clear()
            else:
                assert pool.submit(cached, 'a').result(timeout=5) == 'a'
                assert pool.submit(cached, 'b').result(timeout=5) == 'b'
        finally:
            release.set()
        assert pending.result(timeout=5) == 'late result'
    before = cached.cache_info()
    results = [cached(value) for value in ('c', 'b', 'a', 'a')]
    return before, results, cached.cache_info()


@pytest.mark.parametrize('clear', [False, True], ids=['concurrent-miss', 'concurrent-clear'])
def test_concurrent_publication_and_clear_match_functools(clear):
    assert _concurrent_calls(inlet_cache, clear) == _concurrent_calls(lru_cache, clear)


def test_native_publication_wins_over_a_pending_python_result():
    started = Event()
    release = Event()

    @inlet_cache(maxsize=2)
    def cached(value):
        started.set()
        assert release.wait(5)
        return 'python result'

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cached, 'a')
        try:
            assert started.wait(5)
            assert cached.lookup(('a',)) == (False, None)
            cached.store(('a',), None, 'native result')
        finally:
            release.set()
        assert pending.result(timeout=5) == 'python result'
    assert cached('a') == 'native result'
    assert cached.cache_info() == (1, 2, 2, 1)
