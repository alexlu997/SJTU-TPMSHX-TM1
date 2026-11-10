"""Shared physical 3D grid, axis-map and extruded zone-field builders."""

from __future__ import annotations
import numpy as np


def _resolve_axis_map(fA: dict, Nx: int, Ny: int, Nz: int,
                      L: float, H: float, Lz: float,
                      dx: np.ndarray, dy: np.ndarray,
                      dz: np.ndarray) -> dict:
    """Pack native axis metadata and retain the original width objects."""
    from sjtu_tpmshx.shared.models import _native_grid
    cross1, stream, cross2, p0, p1, p2, reverse = _native_grid.axis_map(fA['dir'])
    counts, lengths, widths = (Nx, Ny, Nz), (L, H, Lz), (dx, dy, dz)
    return dict(
        is_x_stream=stream == 0, is_y_stream=stream == 1, is_z_stream=stream == 2,
        is_reverse=bool(reverse),
        solver_init=dict(Lx=lengths[cross1], Ly=lengths[stream], Lz=lengths[cross2],
                         Nx=counts[cross1], Ny=counts[stream], Nz=counts[cross2]),
        N_stream=counts[stream], N_cross1=counts[cross1], N_cross2=counts[cross2],
        L_stream=lengths[stream], L_cross1=lengths[cross1], L_cross2=lengths[cross2],
        dstream=widths[stream], dcross1=widths[cross1], dcross2=widths[cross2],
        stream_real_axis=stream, cross1_real_axis=cross1, cross2_real_axis=cross2,
        solver_to_real_perm=(p0, p1, p2),
    )


def _build_zone_fields_3d(cells: list[dict], dx: np.ndarray, dy: np.ndarray, Nz: int,
                           tpms_type: str, k_s: float,
                           default_L: float, default_t: float,
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map 2D grid zones to 3D (Nx, Ny, Nz) L/t/eps fields (z-uniform).

    **3D geometry is currently a z-uniform extrusion of the 2D design** —
    a design change in (x, y) propagates identically through all Nz
    layers. This matches the "extrude the 2D TPMS pattern along z" MVP
    assumption. True 3D zoning (design varies along z as well) would
    require an Nz-dimensional decision vector in the optimiser and a
    different cell list shape — not wired in yet.

    cells: list of dicts {y0, y1, x0, x1, L, t} with physical x/y fractions.
    dx/dy: actual physical cell widths. Uncovered cells retain the defaults;
    later rectangles override earlier ones where they overlap. The existing
    sigma=2 Gaussian smoothing remains in grid-index units, including on a
    nonuniform mesh; this function does not change its smoothing length rule.
    Returns L_field / t_field / eps_field (mm, mm, 0-1).
    """
    from . import _native_zones
    from .tpms_props import geometry_fields
    dx, dy = np.asarray(dx), np.asarray(dy)
    Nx, Ny = len(dx), len(dy)
    ids = _native_zones.assign(
        2, Nx, Ny, [(cell['x0'], cell['x1'], cell['y0'], cell['y1']) for cell in cells],
        dx=dx, dy=dy)
    L_2d = _native_zones.gaussian(np.asarray(
        [float(cell['L']) for cell in cells] + [float(default_L)])[ids])
    t_2d = _native_zones.gaussian(np.asarray(
        [float(cell['t']) for cell in cells] + [float(default_t)])[ids])
    eps_2d = geometry_fields(tpms_type, L_2d, t_2d, float(k_s))['epsilon']
    L_field = np.broadcast_to(L_2d[:, :, None], (Nx, Ny, Nz)).copy()
    t_field = np.broadcast_to(t_2d[:, :, None], (Nx, Ny, Nz)).copy()
    eps_field = np.broadcast_to(eps_2d[:, :, None], (Nx, Ny, Nz)).copy()
    return L_field, t_field, eps_field


def _build_grid_3d(L: float, H: float, Lz: float,
                   Nx_u: int, Ny_u: int, Nz_u: int,
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                              int, int, int]:
    """Return native uniform widths and the original requested counts."""
    from sjtu_tpmshx.shared.models import _native_grid
    dx = _native_grid.uniform(Nx_u, L)
    dy = _native_grid.uniform(Ny_u, H)
    dz = _native_grid.uniform(Nz_u, Lz)
    return dx, dy, dz, Nx_u, Ny_u, Nz_u
