"""Detach immutable contract data for private execution state."""
from collections.abc import Mapping

import numpy as np


def mutable_data(value):
    if isinstance(value, Mapping):
        return {key: mutable_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [mutable_data(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.copy()
    return value
