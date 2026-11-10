"""Frozen centre expressions from the phase-3 source audit."""
import numpy as np


def continuous_centres(count, length, widths):
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 1:
        raise ValueError('grid counts must be positive integers')
    if widths is None:
        return (np.arange(count) + 0.5) * (length / count)
    widths = np.asarray(widths, dtype=np.float64)
    if (widths.shape != (count,) or not np.all(np.isfinite(widths) & (widths > 0))
            or not np.isclose(widths.sum(), length, rtol=1e-12, atol=0.)):
        raise ValueError('cell widths must be finite, positive and cover the field domain')
    edges = np.r_[0., np.cumsum(widths)]
    return 0.5 * (edges[:-1] + edges[1:])


def sigmoid_centres(count, length, widths):
    if widths is not None:
        return (np.cumsum(widths) - widths / 2) / length
    return np.linspace(0.5 / count, 1.0 - 0.5 / count, count)


def ntop_centres(count, length):
    return (np.arange(count) + .5) * length / count
