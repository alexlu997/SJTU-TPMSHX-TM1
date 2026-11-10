"""Keep independent grid-transfer references used only by regression tests."""
import numpy as np


def cell_average(field, *widths):
    """Physical area/volume average, independent of how cells are subdivided."""
    value = np.asarray(field)
    if value.ndim == 0:
        return float(value)
    for axis_widths in widths:
        value = np.average(value, axis=0, weights=axis_widths)
    return float(value)


def split_cells(widths):
    """Bisect each cell while keeping its physical end point."""
    result = []
    position = 0.
    for width, end in zip(widths, np.cumsum(widths)):
        result.append(width / 2)
        position += result[-1]
        result.append(end - position)
        position += result[-1]
    return np.asarray(result)

