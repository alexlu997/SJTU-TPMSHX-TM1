"""Share scalar preparation caches with native stage checkpoints."""

from collections import OrderedDict, namedtuple
from functools import wraps
from threading import RLock


_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')
_KEYWORDS = object()


def _call_key(args, kwargs):
    """Return an untyped key, so equal argument values share one entry.

    The native bridge looks up Python calls with positional tuples, so both paths use this key.
    Keyword names and values follow a marker in call order. Thus a positional call, a keyword
    call, and a different keyword order are different entries, as in lru_cache(typed=False).
    One int or str argument uses the same rule; lru_cache keeps it apart from other types.
    """
    if not kwargs:
        return tuple(args)
    return (*args, _KEYWORDS, *(item for pair in kwargs.items() for item in pair))


class _ScalarCache:
    """Own one bounded cache shared by a scalar function and native callbacks."""

    def __init__(self, maxsize):
        self._missing = object()
        self.maxsize = maxsize
        self.values = OrderedDict()
        self.lock = RLock()
        self.hits = self.misses = 0

    def lookup(self, args, kwargs=None):
        key = _call_key(args, kwargs)
        with self.lock:
            value = self.values.get(key, self._missing)
            if value is self._missing:
                self.misses += 1
                return False, None
            self.values.move_to_end(key)
            self.hits += 1
            return True, value

    def store(self, args, kwargs, value):
        key = _call_key(args, kwargs)
        with self.lock:
            # A concurrent caller can publish this key first.
            if key not in self.values:
                self.values[key] = value
                if len(self.values) > self.maxsize:
                    self.values.popitem(last=False)

    def clear(self):
        with self.lock:
            self.values.clear()
            self.hits = self.misses = 0

    def info(self):
        with self.lock:
            return _CacheInfo(self.hits, self.misses, self.maxsize, len(self.values))

    def wrap(self, function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            found, value = self.lookup(args, kwargs)
            if not found:
                value = function(*args, **kwargs)
                self.store(args, kwargs, value)
            return value

        wrapped.lookup = self.lookup
        wrapped.store = self.store
        wrapped.cache_clear = self.clear
        wrapped.cache_info = self.info
        wrapped.cache_parameters = lambda: {'maxsize': self.maxsize, 'typed': False}
        return wrapped


def scalar_cache(*, maxsize: int):
    """Give each decorated function an independent scalar cache."""
    if not isinstance(maxsize, int) or maxsize <= 0:
        raise ValueError('maxsize must be a positive integer')
    return lambda function: _ScalarCache(maxsize).wrap(function)


geometry_cache = _ScalarCache(32768)
inlet_cache = _ScalarCache(4096)


class _InletCacheValue(tuple):
    """Keep native-only intermediate values outside the public property mapping."""
    def __new__(cls, values, records, cp, pr):
        result = super().__new__(cls, (values, records))
        result.cp, result.pr = cp, pr
        return result
