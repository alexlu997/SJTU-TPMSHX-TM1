"""Share scalar preparation caches with native stage checkpoints."""

from collections import OrderedDict, namedtuple
from functools import _make_key, wraps
from threading import RLock


_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


def scalar_cache(*, maxsize: int):
    """Cache scalar calls and expose lookup/store for native calculations.

    The cache size must be positive. The private functools key builder keeps
    the existing untyped call keys, including keyword order and scalar types.
    """
    if not isinstance(maxsize, int) or maxsize <= 0:
        raise ValueError('maxsize must be a positive integer')

    def decorate(function):
        cache = OrderedDict()
        lock = RLock()
        missing = object()
        hits = misses = 0

        def lookup(args: tuple, kwargs: dict | None = None):
            """Return (found, value) and update statistics and access order."""
            nonlocal hits, misses
            key = _make_key(args, {} if kwargs is None else kwargs, typed=False)
            with lock:
                result = cache.get(key, missing)
                if result is missing:
                    misses += 1
                    return False, None
                cache.move_to_end(key)
                hits += 1
                return True, result

        def store(args: tuple, kwargs: dict | None, value):
            """Store a successful result without changing lookup statistics."""
            key = _make_key(args, {} if kwargs is None else kwargs, typed=False)
            with lock:
                # A concurrent calculation can have stored this key first.
                if key not in cache:
                    cache[key] = value
                    if len(cache) > maxsize:
                        cache.popitem(last=False)

        @wraps(function)
        def wrapped(*args, **kwargs):
            found, result = lookup(args, kwargs)
            if found:
                return result
            result = function(*args, **kwargs)
            store(args, kwargs, result)
            return result

        def cache_clear():
            nonlocal hits, misses
            with lock:
                cache.clear()
                hits = misses = 0

        def cache_info():
            with lock:
                return _CacheInfo(hits, misses, maxsize, len(cache))

        wrapped.lookup = lookup
        wrapped.store = store
        wrapped.cache_clear = cache_clear
        wrapped.cache_info = cache_info
        wrapped.cache_parameters = lambda: {'maxsize': maxsize, 'typed': False}
        return wrapped

    return decorate
