"""Original NumPy range collector, frozen before result migration at 46076afd.

Only context and data ownership are shared with production. No production
numerical collector or native binding supplies these reference observations.
"""
from dataclasses import replace

import numpy as np

from sjtu_tpmshx.shared.domain.run_warnings import (
    RangeRecord, _SAMPLE_FIELDS, _cache_records, _current, _range_context,
)


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
