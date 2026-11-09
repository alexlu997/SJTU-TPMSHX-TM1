"""Run-local closure warnings, independent of Python's global warning filters."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

import numpy as np


_current = ContextVar('run_warnings', default=None)
_cache_records = ContextVar('cached_warnings', default=None)
_range_context = ContextVar('range_context', default=('unbound', 'unbound', 'source'))


@contextmanager
def range_context(*, side=None, stage=None, layout=None):
    """Override supplied labels, retaining enclosing side/stage for nested sources."""
    token = _range_context.set(tuple(
        old if new is None else new
        for old, new in zip(_range_context.get(), (side, stage, layout))))
    try:
        yield
    finally:
        _range_context.reset(token)


@dataclass(frozen=True)
class RangeRecord:
    """Finite extrema and one worst snapshot, never accumulated cell counts."""
    label: str
    quantity: str
    unit: str
    bounds: tuple
    minimum: tuple | None  # (value, source-array index); None if all nonfinite
    maximum: tuple | None
    low: int
    high: int
    size: int
    nonfinite: int  # peak count in a single observation of this same shape
    last: dict | None = None

    def merged(self, other):
        minimum = self.minimum
        maximum = self.maximum
        if other.minimum is not None and (minimum is None or other.minimum[0] < minimum[0]):
            minimum = other.minimum
        if other.maximum is not None and (maximum is None or other.maximum[0] > maximum[0]):
            maximum = other.maximum
        # Keys include shape: equal fractions retain the first joined snapshot.
        worst = other if other.low + other.high > self.low + self.high else self
        return replace(worst, minimum=minimum, maximum=maximum,
                       nonfinite=max(self.nonfinite, other.nonfinite), last=other.last)


def record_range(source, values, bounds, *, label, quantity, unit):
    """Observe source values before its floor; return whether this run owns notices."""
    records, cached = _current.get(), _cache_records.get()
    if records is None and cached is None:
        return False
    array = np.asarray(values, dtype=float)
    if not array.size:
        return records is not None
    finite = np.isfinite(array)
    indices = np.flatnonzero(finite)
    minimum = maximum = None
    if indices.size:
        valid = array.flat[indices]
        i_min, i_max = indices[valid.argmin()], indices[valid.argmax()]
        minimum = (float(array.flat[i_min]), tuple(int(i) for i in np.unravel_index(i_min, array.shape)))
        maximum = (float(array.flat[i_max]), tuple(int(i) for i in np.unravel_index(i_max, array.shape)))
    lo, hi = bounds
    value = RangeRecord(label, quantity, unit, bounds, minimum, maximum,
                        int(np.count_nonzero(finite & (array < lo))),
                        int(np.count_nonzero(finite & (array > hi))),
                        int(array.size), int(array.size - indices.size))
    value = replace(value, last={name: getattr(value, name) for name in _SAMPLE_FIELDS})
    # Cache facts carry shape, but never the originating run's side/stage/layout.
    key = (*source, array.shape)
    if cached is not None:
        previous = cached.get(key)
        cached[key] = value if previous is None else previous.merged(value)
    if records is not None:
        key = (*key, _range_context.get())
        previous = records.get(key)
        records[key] = value if previous is None else previous.merged(value)
    return records is not None



_SAMPLE_FIELDS = ('minimum', 'maximum', 'low', 'high', 'size', 'nonfinite')


def range_observations(records, *, last=False):
    """Copy source bounds and either aggregate or last-call observations."""
    rows = []
    for key, value in records.items():
        if not isinstance(value, RangeRecord):
            continue
        shape, (side, stage, layout) = key[-2:]
        sample = value.last if last else {name: getattr(value, name) for name in _SAMPLE_FIELDS}
        rows.append(dict(source=key[:-2], side=side, stage=stage, layout=layout,
                         shape=shape, quantity=value.quantity, unit=value.unit,
                         bounds=value.bounds, captured=sample is not None,
                         **({} if sample is None else sample)))
    return rows


def warning_messages(records):
    """Keep ComputeResult/UI/export on their existing list-of-strings contract."""
    for key, value in records.items():
        if not isinstance(value, RangeRecord):
            yield value
            continue
        if not (value.low or value.high or value.nonfinite):
            continue
        shape, (side, stage, layout) = key[-2:]
        sample = 'scalar' if not shape else f'array{shape}'
        yield (
            f'{value.label}: {value.quantity} source range {value.bounds} {value.unit}; '
            f'view={key[0]}, side={side}, stage={stage}, layout={layout}, sample={sample}; '
            f'finite extrema across observations: min={value.minimum}, max={value.maximum} '
            '(value, index); '
            f'worst single snapshot: low={value.low}, high={value.high}, '
            f'outside={value.low + value.high}/{value.size} '
            f'({(value.low + value.high) / value.size:.2%} of sampled values); '
            f'peak nonfinite in one snapshot={value.nonfinite}/{value.size} '
            '(not classified inside range).'
        )


def current_warnings():
    return _current.get()


@contextmanager
def warning_scope(records):
    """Install a run/worker's dict, or None for standalone warning behavior."""
    token = _current.set(records)
    try:
        yield records
    finally:
        _current.reset(token)


def record_warning(key, message):
    """True means this run owns the warning, including an already-seen key."""
    cached = _cache_records.get()
    if cached is not None:
        cached.setdefault(key, message)
    records = _current.get()
    if records is None:
        return False
    records.setdefault(key, message)
    return True


@contextmanager
def cache_warning_records(records):
    """Inside lru_cache, retain source notices even on a standalone cache miss.

    Recording here does not take ownership: standalone warning emission and
    its once-per-session registries still run at their original call sites.
    """
    token = _cache_records.set(records)
    try:
        yield records
    finally:
        _cache_records.reset(token)


def merge_warnings(target, sources, *, bind_context=False):
    """Merge workers in join order; bind unowned cache facts only on replay."""
    if target is not None:
        for source in sources:
            for key, value in source.items():
                if isinstance(value, RangeRecord):
                    if bind_context:
                        key = (*key, _range_context.get())
                    previous = target.get(key)
                    target[key] = value if previous is None else previous.merged(value)
                else:
                    target.setdefault(key, value)
