"""Validate and assemble physical grids with the native numerical core."""
import math

import numpy as np

from sjtu_tpmshx.shared.models import _native_grid

SHANGHAI_GRID_2D = (84, 24, 1)
SHANGHAI_GRID_3D = (92, 14, 10)


def _port_wall_axes(lengths, ports):
    """Keep Python set order and use native edges and layer rules."""
    ports = tuple(ports)
    for axis in range(len(lengths)):
        knots = sorted(set(_native_grid.port_edges(lengths, ports, axis)))
        yield knots, *_native_grid.wall_spec(len(lengths), len(knots))


def port_wall_min_counts(lengths, ports):
    """Return the required total counts for each physical axis."""
    return tuple(spec[-1] for spec in _port_wall_axes(lengths, ports))


def suggest_grid_3d(L_dom: float, H_dom: float, Lz_dom: float,
                    D_h: float, max_cells: int = 50_000, *,
                    port_wall_refine: bool = False, ports=()) -> tuple[int, int, int]:
    """Suggest total counts within the budget and native wall-layer limits.

    Hydraulic-diameter spacing is a heuristic. It is not an accuracy guarantee.
    """
    lengths = (L_dom, H_dom, Lz_dom)
    for name, value in zip(('L_dom', 'H_dom', 'Lz_dom', 'D_h'), (*lengths, D_h)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and > 0, got {value}')
    minimum = (14, 8, 3)
    if port_wall_refine:
        minimum = tuple(max(base, needed) for base, needed in
                        zip(minimum, port_wall_min_counts(lengths, ports)))
    if max_cells < math.prod(minimum):
        raise ValueError(f'Grid budget {max_cells} is below the required minimum '
                         f'{minimum} ({math.prod(minimum)} cells)')
    return _native_grid.suggest(lengths, D_h, max_cells, minimum)


def build_port_wall_grid(lengths, counts, ports):
    """Build port-aligned widths with all wall layers in the requested counts.

    The Shanghai study uses 0.2 mm first cells at port edges.
    Housing-wall first cells are 20 um in 2D and 56 um in 3D.
    Other geometries need a separate grid-convergence assessment.
    """
    result = []
    for axis, (length, count, spec) in enumerate(zip(lengths, counts, _port_wall_axes(lengths, ports))):
        knots, _, _, _, _ = spec
        bounds = [0., *knots, length]
        bulk_bounds = _native_grid.aligned_bounds(length, knots)
        result.append(_native_grid.port_wall_axis(len(lengths), axis, count, bounds, bulk_bounds))
    return tuple(result)


def _aligned_grid(N, L, breakpoints):
    """Build float64 widths with cell edges at the accepted breakpoints."""
    return _native_grid.aligned(N, _native_grid.aligned_bounds(L, breakpoints))


def build_wall_refined_1d(W, N_bulk, n_refine=8, first_cell=0.02e-3, growth=1.8):
    """Build wall layers and uniform bulk cells for a metre-scale span."""
    return _native_grid.wall(W, N_bulk, n_refine, first_cell, growth)


def build_master_refined_grid(L_dom: float, H_dom: float,
                               Nx_user: int, Ny_user: int,
                               n_refine: int = 8,
                               first_cell: float = 0.02e-3,
                               growth: float = 1.8
                               ) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Build physical x/y widths with wall layers at both ends."""
    dx = build_wall_refined_1d(L_dom, Nx_user, n_refine, first_cell, growth)
    dy = build_wall_refined_1d(H_dom, Ny_user, n_refine, first_cell, growth)
    return dx, dy, len(dx), len(dy)


def build_grid_2d(L, H, Nx, Ny, ports, *, zone_axis=None, port_wall_refine=False):
    """Build physical widths and retain the existing refinement error flow."""
    ports = tuple(ports)
    rows = []
    for port in ports:
        row = dict(port)
        for end in ('in', 'out'):
            row[f'{end}_ctr'] = port.get(f'{end}_ctr', port['in_ctr'])
            row[f'{end}_w'] = port.get(f'{end}_w', port['in_w'])
        rows.append(row)
    x_breaks = set(_native_grid.breaks_2d((L, H), rows, 0))
    y_breaks = set(_native_grid.breaks_2d((L, H), rows, 1))
    refinement_error = None
    if port_wall_refine:
        dx, dy = build_port_wall_grid((L, H), (Nx, Ny), ports)
    else:
        if not x_breaks and not y_breaks and zone_axis in (None, 'continuous'):
            try:
                dx, dy, _, _ = build_master_refined_grid(L, H, Nx, Ny)
                return dx, dy, (), (), None
            except ValueError as error:
                refinement_error = str(error)
        dx = _aligned_grid(Nx, L, list(x_breaks))
        dy = _aligned_grid(Ny, H, list(y_breaks))
    return dx, dy, tuple(sorted(x_breaks)), tuple(sorted(y_breaks)), refinement_error


def _port_overlap_1d(widths, lo, hi, *, staggered=False):
    """Return native interval overlap on cells or between adjacent centres."""
    return _native_grid.overlap(widths, lo, hi, staggered=staggered)


def _port_fractions_1d(widths, lo, hi, *, uniform=False):
    """Return native geometric overlap and the selected imposed profile."""
    return _native_grid.fractions(widths, lo, hi, uniform=uniform)
