"""Independent mass and residual checks on returned native fields."""
import numpy as np


def momentum_component_residuals(nums, dens, floor_fraction=1e-3):
    if not np.isfinite((*nums, *dens)).all():
        return (float('nan'),) * len(nums)
    floor = floor_fraction * max(dens)
    return tuple(n / max(d, floor) if max(d, floor) > 0. else 0.
                 for n, d in zip(nums, dens))


def raw_faces(s):
    density = s.rho_field * s.eps_field
    ndim = density.ndim
    widths = (s.dx_arr, s.dy_arr) if ndim == 2 else (s.dx, s.dy, s.dz)
    result = []
    for axis, name in enumerate('uvw'[:ndim]):
        lower, upper = [[(0, 0)] * ndim for _ in range(2)]
        lower[axis], upper[axis] = (1, 0), (0, 1)
        average = .5 * (np.pad(density, lower, mode='edge')
                        + np.pad(density, upper, mode='edge'))
        area = 1.
        for direction, width in enumerate(widths):
            if direction != axis:
                shape = [1] * ndim
                shape[direction] = len(width)
                area = area * width.reshape(shape)
        result.append(average * getattr(s, name) * area)
    return result


def mass_balance(s, *, exclude_outlet=False):
    faces = raw_faces(s)
    net, through = np.zeros_like(s.P), np.zeros_like(s.P)
    for axis, flux in enumerate(faces):
        low, high = [slice(None)] * s.P.ndim, [slice(None)] * s.P.ndim
        low[axis], high[axis] = slice(None, -1), slice(1, None)
        net += flux[tuple(high)] - flux[tuple(low)]
        through += np.abs(flux[tuple(high)]) + np.abs(flux[tuple(low)])
    counted = through > 0.
    if exclude_outlet:
        counted[:, -1] &= s.outlet_geom_frac <= 0.
    local = np.max(np.abs(net[counted]) / through[counted]) if counted.any() else 0.
    inlet, outlet = faces[1][:, 0], faces[1][:, -1]
    mi, mo = float(inlet.sum()), float(outlet.sum())
    global_residual = abs(mo - mi) / abs(mi) if abs(mi) > 1e-14 else 0.
    total = float(np.abs(outlet).sum())
    backflow = float(-outlet[outlet < 0.].sum()) / total if total else 0.
    return np.array([local, global_residual, backflow, mi, mo]), int(counted.sum()), net
