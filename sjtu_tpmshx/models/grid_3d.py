"""models/grid_3d.py — shared 3D grid / axis-map / zone-field builders.

Moved verbatim from stages_3d.py (openspec split-pipelines, 2026-07-03);
behavior bit-identical.
"""

from __future__ import annotations
import numpy as np

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


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


def _build_zone_fields_3d(cells: list[dict], Nx: int, Ny: int, Nz: int,
                           L: float, H: float, tpms_type: str, k_s: float,
                           default_L: float, default_t: float,
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map 2D grid zones to 3D (Nx, Ny, Nz) L/t/eps fields (z-uniform).

    **3D geometry is currently a z-uniform extrusion of the 2D design** —
    a design change in (x, y) propagates identically through all Nz
    layers. This matches the "extrude the 2D TPMS pattern along z" MVP
    assumption. True 3D zoning (design varies along z as well) would
    require an Nz-dimensional decision vector in the optimiser and a
    different cell list shape — not wired in yet.

    cells: list of dicts {y0, y1, x0, x1, L, t} with 0-1 normalised x/y.
    Returns L_field / t_field / eps_field (mm, mm, 0-1).
    """
    from scipy.ndimage import gaussian_filter
    from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
    L_2d = np.full((Nx, Ny), float(default_L), dtype=np.float64)
    t_2d = np.full((Nx, Ny), float(default_t), dtype=np.float64)
    for cell in cells:
        x_lo = int(round(cell['x0'] * Nx)); x_hi = int(round(cell['x1'] * Nx))
        y_lo = int(round(cell['y0'] * Ny)); y_hi = int(round(cell['y1'] * Ny))
        x_lo = max(0, min(x_lo, Nx)); x_hi = max(0, min(x_hi, Nx))
        y_lo = max(0, min(y_lo, Ny)); y_hi = max(0, min(y_hi, Ny))
        L_2d[x_lo:x_hi, y_lo:y_hi] = float(cell['L'])
        t_2d[x_lo:x_hi, y_lo:y_hi] = float(cell['t'])
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


def _build_grid_3d(wall_refine: bool, L: float, H: float, Lz: float,
                   Nx_u: int, Ny_u: int, Nz_u: int,
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                              int, int, int]:
    """Build 3D cell-spacing arrays + grid counts (extracted from _run_3d_stack,
    2026-06-09 F1). Uniform user spacing, or 6-wall boundary-layer refinement
    when ``wall_refine`` (expands user N by ~+2·n_refine per axis; first cell
    0.02 mm, growth 1.8). Returns ``(dx, dy, dz, Nx, Ny, Nz)``.

    2026-06-09 E1: the refined non-uniform spacing now reaches BOTH stages —
    the LTNE energy solve AND the SIMPLE momentum/pressure solve (via
    SIMPLESolver3D's dx_arr/dy_arr/dz_arr). Previously SIMPLE silently ran on
    a uniform grid under wall_refine. (The E1-era "kernels were already
    non-uniform-aware" claim was wrong for the momentum DIFFUSION terms —
    corrected 2026-07-07, N4: conductances now use actual neighbour-node
    distances; guarded by test_wall_refine_3d.py.)
    """
    if wall_refine:
        from sjtu_tpmshx.models.grid import build_master_refined_grid_3d
        try:
            dx, dy, dz, Nx, Ny, Nz = build_master_refined_grid_3d(
                L, H, Lz, Nx_u, Ny_u, Nz_u,
                n_refine=8, first_cell=0.02e-3, growth=1.8)
            _log.info(f"[3D grid] wall-refine: user {Nx_u}x{Ny_u}x{Nz_u} -> "
                      f"actual {Nx}x{Ny}x{Nz}")
        except ValueError as e:
            _log.warning(f"[3D grid] wall-refine skipped ({e}); using uniform")
            dx = np.full(Nx_u, L / Nx_u, dtype=np.float64)
            dy = np.full(Ny_u, H / Ny_u, dtype=np.float64)
            dz = np.full(Nz_u, Lz / Nz_u, dtype=np.float64)
            Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    else:
        dx = np.full(Nx_u, L / Nx_u, dtype=np.float64)
        dy = np.full(Ny_u, H / Ny_u, dtype=np.float64)
        dz = np.full(Nz_u, Lz / Nz_u, dtype=np.float64)
        Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    return dx, dy, dz, Nx, Ny, Nz


def _solver_spacings(dx: np.ndarray, dy: np.ndarray, dz: np.ndarray,
                     perm: tuple[int, int, int],
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map real-coords cell-spacing arrays onto a SIMPLE solver's axis order.

    The solver↔real mapping is ``real = solver.transpose(perm)`` (perm =
    solver_to_real_perm), so solver axis ``s`` spans real axis ``perm.index(s)``.
    Returns ``(sdx, sdy, sdz)`` in solver-axis order. Used to feed the refined
    non-uniform grid into SIMPLESolver3D under wall_refine (E1, 2026-06-09)."""
    real = (dx, dy, dz)
    return (real[perm.index(0)], real[perm.index(1)], real[perm.index(2)])
