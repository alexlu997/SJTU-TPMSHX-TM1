"""Shared physical 3D grid, axis-map and extruded zone-field builders."""

from __future__ import annotations
import numpy as np


def _resolve_axis_map(fA: dict, Nx: int, Ny: int, Nz: int,
                      L: float, H: float, Lz: float,
                      dx: np.ndarray, dy: np.ndarray,
                      dz: np.ndarray) -> dict:
    """Map fluid-A direction code to SIMPLE3D solver axes + mask geometry.

    `dir_A`: 0=+x 1=-x 2=+y 3=-y  (matches 2D `_dir_int` convention).

    Maps fluid direction (0/1=±x, 2/3=±y, 4/5=±z) to SIMPLESolver3D axes.
    SIMPLE3D enforces streamwise = solver Y axis, inlet at solver y=0.
    We permute real (x, y, z) → solver (X_sol, Y_sol=stream, Z_sol) so the
    streamwise face is at solver y=0, then transpose fields back for visualisation.

    Returns dict with:
      is_x_stream (dir ∈ {0,1}), is_y_stream (2,3), is_z_stream (4,5)
      is_reverse (dir ∈ {1,3,5}: negative direction)
      solver_init, N_stream, N_cross1, N_cross2, L_stream, L_cross1, L_cross2
      dstream, dcross1, dcross2
      stream_real_axis (0, 1, or 2)
      cross1_real_axis, cross2_real_axis
      solver_to_real_perm : tuple for arr.transpose() mapping solver → real
    """
    d = fA['dir']
    is_reverse = d in (1, 3, 5)
    if d in (0, 1):
        # Streamwise real x.  Solver Ly=L(x), Lx=H(y), Lz=Lz(z).
        return dict(
            is_x_stream=True, is_y_stream=False, is_z_stream=False,
            is_reverse=is_reverse,
            solver_init=dict(Lx=H, Ly=L, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz),
            N_stream=Nx, N_cross1=Ny, N_cross2=Nz,
            L_stream=L, L_cross1=H, L_cross2=Lz,
            dstream=dx, dcross1=dy, dcross2=dz,
            stream_real_axis=0, cross1_real_axis=1, cross2_real_axis=2,
            solver_to_real_perm=(1, 0, 2),   # solver (Ny,Nx,Nz) → real (Nx,Ny,Nz)
        )
    if d in (2, 3):
        # Streamwise real y.  Solver Ly=H(y), Lx=L(x), Lz=Lz(z).
        return dict(
            is_x_stream=False, is_y_stream=True, is_z_stream=False,
            is_reverse=is_reverse,
            solver_init=dict(Lx=L, Ly=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz),
            N_stream=Ny, N_cross1=Nx, N_cross2=Nz,
            L_stream=H, L_cross1=L, L_cross2=Lz,
            dstream=dy, dcross1=dx, dcross2=dz,
            stream_real_axis=1, cross1_real_axis=0, cross2_real_axis=2,
            solver_to_real_perm=(0, 1, 2),   # solver (Nx,Ny,Nz) = real (Nx,Ny,Nz)
        )
    # d in (4, 5): streamwise real z.  Solver Ly=Lz(z), Lx=L(x), Lz=H(y).
    return dict(
        is_x_stream=False, is_y_stream=False, is_z_stream=True,
        is_reverse=is_reverse,
        solver_init=dict(Lx=L, Ly=Lz, Lz=H, Nx=Nx, Ny=Nz, Nz=Ny),
        N_stream=Nz, N_cross1=Nx, N_cross2=Ny,
        L_stream=Lz, L_cross1=L, L_cross2=H,
        dstream=dz, dcross1=dx, dcross2=dy,
        stream_real_axis=2, cross1_real_axis=0, cross2_real_axis=1,
        solver_to_real_perm=(0, 2, 1),   # solver (Nx,Nz,Ny) → real (Nx,Ny,Nz)
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
    from scipy.ndimage import gaussian_filter
    from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
    dx, dy = np.asarray(dx), np.asarray(dy)
    Nx, Ny = len(dx), len(dy)
    xf = (np.cumsum(dx) - dx / 2.) / dx.sum()
    yf = (np.cumsum(dy) - dy / 2.) / dy.sum()
    L_2d = np.full((Nx, Ny), float(default_L), dtype=np.float64)
    t_2d = np.full((Nx, Ny), float(default_t), dtype=np.float64)
    for cell in cells:
        selected = np.ix_((cell['x0'] <= xf) & (xf < cell['x1']),
                          (cell['y0'] <= yf) & (yf < cell['y1']))
        L_2d[selected] = float(cell['L'])
        t_2d[selected] = float(cell['t'])
    L_2d = gaussian_filter(L_2d, sigma=2.0)
    t_2d = gaussian_filter(t_2d, sigma=2.0)
    eps_2d = np.empty_like(L_2d)
    for i in range(Nx):
        for j in range(Ny):
            g = tpms_geometry(tpms_type, float(L_2d[i, j]),
                              float(t_2d[i, j]), float(k_s))
            eps_2d[i, j] = g['epsilon']
    L_field = np.broadcast_to(L_2d[:, :, None], (Nx, Ny, Nz)).copy()
    t_field = np.broadcast_to(t_2d[:, :, None], (Nx, Ny, Nz)).copy()
    eps_field = np.broadcast_to(eps_2d[:, :, None], (Nx, Ny, Nz)).copy()
    return L_field, t_field, eps_field


def _build_grid_3d(L: float, H: float, Lz: float,
                   Nx_u: int, Ny_u: int, Nz_u: int,
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                              int, int, int]:
    """Return uniform physical widths and the requested cell counts."""
    dx = np.full(Nx_u, L / Nx_u, dtype=np.float64)
    dy = np.full(Ny_u, H / Ny_u, dtype=np.float64)
    dz = np.full(Nz_u, Lz / Nz_u, dtype=np.float64)
    return dx, dy, dz, Nx_u, Ny_u, Nz_u
