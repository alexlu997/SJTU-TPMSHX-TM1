"""Keep the pre-port zone formulas and the independent SciPy filter.

These bodies were read on 2026-11-10, before the batch-3 replacement.
Sources: shared/models/zone_config.py and shared/models/grid_3d.py.
The batch-2 merge is 8f850367. This file imports no tested numerical code.
Rows contain x0, x1, y0, y1. Stripe rows use only their first two values.
Stripe rows have already passed the Python configuration sort and validation.
The extra 3D IDs expose the old selection masks for direct comparison.
They were not a public output of the old 3D builder.
"""

import numpy as np
from scipy.ndimage import gaussian_filter


def stripe_ids(nx, ny, rows, *, axis=1, domain=1., dx=None, dy=None):
    """Keep strong NumPy points in the original stripe comparisons."""
    n_axis = ny if axis == 1 else nx
    widths = dy if axis == 1 else dx
    if widths is None:
        d_axis = domain / n_axis
        fractions = np.array([(k + 0.5) * d_axis / domain for k in range(n_axis)])
    else:
        widths = np.asarray(widths, dtype=np.float64)
        fractions = (np.cumsum(widths) - 0.5 * widths) / domain

    ids_1d = np.zeros(n_axis, dtype=np.int32)
    for k in range(n_axis):
        for index, row in enumerate(rows):
            if row[0] <= fractions[k] < row[1]:
                ids_1d[k] = index
                break
        else:
            ids_1d[k] = len(rows) - 1
    return np.broadcast_to(ids_1d if axis == 1 else ids_1d[:, None], (nx, ny)).copy()


def rectangle_ids_2d(nx, ny, rows, *, dx=None, dy=None):
    """Keep weak Python points and the first-row uncovered value."""
    if dx is not None:
        dx = np.asarray(dx, dtype=np.float64)
        x_total = dx.sum()
        x_cum = np.concatenate([[0.0], np.cumsum(dx)])
        x_centres = 0.5 * (x_cum[:-1] + x_cum[1:]) / x_total
    else:
        x_centres = (np.arange(nx) + 0.5) / nx
    if dy is not None:
        dy = np.asarray(dy, dtype=np.float64)
        y_total = dy.sum()
        y_cum = np.concatenate([[0.0], np.cumsum(dy)])
        y_centres = 0.5 * (y_cum[:-1] + y_cum[1:]) / y_total
    else:
        y_centres = (np.arange(ny) + 0.5) / ny

    ids = np.zeros((nx, ny), dtype=np.int32)
    for i in range(nx):
        xf = float(x_centres[i])
        for j in range(ny):
            yf = float(y_centres[j])
            for index, row in enumerate(rows):
                if row[0] <= xf < row[1] and row[2] <= yf < row[3]:
                    ids[i, j] = index
                    break
    return ids


def rectangle_ids_3d(nx, ny, rows, *, dx, dy):
    """Keep strong array comparisons and the last matching rectangle."""
    dx, dy = np.asarray(dx), np.asarray(dy)
    xf = (np.cumsum(dx) - dx / 2.) / dx.sum()
    yf = (np.cumsum(dy) - dy / 2.) / dy.sum()
    ids = np.full((nx, ny), -1, dtype=np.int32)
    for index, row in enumerate(rows):
        selected = np.ix_((row[0] <= xf) & (xf < row[1]),
                          (row[2] <= yf) & (yf < row[3]))
        ids[selected] = index
    return ids


def assign(kind, nx, ny, rows, *, axis=1, domain=1., dx=None, dy=None):
    """Select the frozen body without a production numerical import."""
    if kind == 0:
        return stripe_ids(nx, ny, rows, axis=axis, domain=domain, dx=dx, dy=dy)
    if kind == 1:
        return rectangle_ids_2d(nx, ny, rows, dx=dx, dy=dy)
    if kind == 2:
        return rectangle_ids_3d(nx, ny, rows, dx=dx, dy=dy)
    raise ValueError('unknown reference zone kind')


def rectangle_fields_3d(rows, dx, dy, default_length, default_wall):
    """Keep the old L/t overwrite, float conversion and smoothing order.

    Rows contain x0, x1, y0, y1, L_mm and t_mm.
    Geometry evaluation is outside this assignment reference.
    """
    dx, dy = np.asarray(dx), np.asarray(dy)
    nx, ny = len(dx), len(dy)
    xf = (np.cumsum(dx) - dx / 2.) / dx.sum()
    yf = (np.cumsum(dy) - dy / 2.) / dy.sum()
    length = np.full((nx, ny), float(default_length), dtype=np.float64)
    wall = np.full((nx, ny), float(default_wall), dtype=np.float64)
    for row in rows:
        selected = np.ix_((row[0] <= xf) & (xf < row[1]),
                          (row[2] <= yf) & (yf < row[3]))
        length[selected] = float(row[4])
        wall[selected] = float(row[5])
    return gaussian_filter(length, sigma=2.0), gaussian_filter(wall, sigma=2.0)


def gaussian(values):
    """Use the old SciPy sigma=2 default filter as the reference."""
    return gaussian_filter(values, sigma=2.0)
