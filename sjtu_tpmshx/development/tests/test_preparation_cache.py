"""Compare shared preparation cache behavior with functools.lru_cache."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from threading import Event

import numpy as np
import pytest

from sjtu_tpmshx.shared.models.preparation_cache import scalar_cache


class _String(str):
    pass


@pytest.mark.parametrize('calls', [
    [((1, 2), {}), ((1,), {'b': 2}), ((), {'a': 1, 'b': 2}),
     ((), {'b': 2, 'a': 1}), ((1, 2), {}), ((), {'a': 1, 'b': 2})],
    [((value,), {}) for value in
     (1, True, 1., np.int64(1), np.float16(1), np.bool_(True), 1, True)],
    [((value,), {}) for value in ('x', _String('x'), 'x', _String('x'))],
    [(('Gyroid', value, .5), {}) for value in
     (np.float16(7), 7., np.float32(7), 7, np.float64(7))],
    [(('Gyroid', value, .5), {}) for value in
     (7., np.float16(7), np.float32(7), 7, np.float64(7))],
    [((value,), {}) for value in (None, None, (1, 2), (1., 2.))],
    [((), {'a': value}) for value in (1, True, 1., np.int32(1))],
], ids=['call-shapes', 'single-number', 'single-string', 'numpy-first',
        'python-first', 'none-and-tuple', 'keyword-number'])
def test_call_keys_match_functools(calls):
    def describe(*args, **kwargs):
        return tuple(type(value) for value in args), tuple(
            (name, type(value)) for name, value in kwargs.items())

    cached = scalar_cache(maxsize=16)(describe)
    reference = lru_cache(maxsize=16)(describe)
    for args, kwargs in calls:
        assert cached(*args, **kwargs) == reference(*args, **kwargs)
        assert cached.cache_info() == reference.cache_info()


@pytest.mark.parametrize('value', [[], {}, np.array([1])], ids=['list', 'dict', 'array'])
def test_unhashable_calls_do_not_change_statistics(value):
    for decorate in (scalar_cache, lru_cache):
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

    cached = scalar_cache(maxsize=2)(calculate)
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
    @scalar_cache(maxsize=2)
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
    assert _concurrent_calls(scalar_cache, clear) == _concurrent_calls(lru_cache, clear)


def test_native_publication_wins_over_a_pending_python_result():
    started = Event()
    release = Event()

    @scalar_cache(maxsize=2)
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


@pytest.mark.parametrize('maxsize', [0, -1, None, 1.5])
def test_cache_size_must_be_positive(maxsize):
    with pytest.raises(ValueError, match='positive integer'):
        scalar_cache(maxsize=maxsize)
