"""Coarse-grid bootstrap for 3D SIMPLE solver (Phase C acceleration).

Strategy: build a half-resolution SIMPLE solver (Nx//2, Ny//2, Nz//2),
run a bounded F2 solve, trilinear-interpolate (u, v, w, P) onto the fine
staggered grid, and inject an initial guess. A capped coarse solve supplies
only a seed; the fine solver must still satisfy its own F2 gates.

Geometry coefficients (K_arr, cF_arr, eps) are
block-averaged onto the coarse grid — geometry is NOT re-evaluated via
the TPMS sigmoid because the coarse grid is purely a bootstrap
device, not a physical answer.
Ports are rebuilt from their physical rectangles; inlet mass is transferred
by open-area intersection, including nonuniform and odd-sized fine grids.

Final correctness is preserved: the fine solver still converges to its
own F2 gates. Coarse bootstrap is opt-in via `solver_fine.use_coarse_bootstrap`.

Skips silently if the coarse grid would be too small to be useful
(any axis < 4 cells).
"""
from __future__ import annotations
import numpy as np

from ._solve_common import f2_state_is_finite


def _block_average_2d(arr: np.ndarray, fy: int, fz: int) -> np.ndarray:
    """Average non-overlapping (fy × fz) blocks of a 2-D array."""
    Ny, Nz = arr.shape
    Ny_c = Ny // fy
    Nz_c = Nz // fz
    trim = arr[:Ny_c * fy, :Nz_c * fz]
    return trim.reshape(Ny_c, fy, Nz_c, fz).mean(axis=(1, 3))


def _block_average_3d(arr: np.ndarray, fx: int, fy: int, fz: int) -> np.ndarray:
    """Average non-overlapping (fx × fy × fz) blocks of a 3-D array."""
    Nx, Ny, Nz = arr.shape
    Nx_c = Nx // fx
    Ny_c = Ny // fy
    Nz_c = Nz // fz
    trim = arr[:Nx_c * fx, :Ny_c * fy, :Nz_c * fz]
    return trim.reshape(Nx_c, fx, Ny_c, fy, Nz_c, fz).mean(axis=(1, 3, 5))


def _trilinear_zoom(arr: np.ndarray, target_shape: tuple) -> np.ndarray:
    """Trilinear interpolate ``arr`` to the requested target shape."""
    from scipy.ndimage import zoom
    factors = tuple(t / s for t, s in zip(target_shape, arr.shape))
    return zoom(arr, factors, order=1, mode='nearest')


def _open_intersections(fine_widths, coarse_widths, lo, hi):
    """Open lengths shared by each coarse/fine face interval."""
    fine = np.r_[0., np.cumsum(fine_widths)]
    coarse = np.r_[0., np.cumsum(coarse_widths)]
    left = np.maximum(np.maximum(coarse[:-1, None], fine[None, :-1]), lo)
    right = np.minimum(np.minimum(coarse[1:, None], fine[None, 1:]), hi)
    return np.maximum(right - left, 0.)


def bootstrap_simple_3d(solver_fine, max_iter_coarse: int = 200,
                         min_coarse_axis: int = 4,
                         verbose: bool = False, *, cancel_check=None) -> dict:
    """Run a coarse SIMPLE solve, prolongate (u,v,w,P) into ``solver_fine``.

    Parameters
    ----------
    solver_fine : SIMPLESolver3D
        The fine-grid solver instance to seed. Modified in-place: u, v, w,
        P arrays are overwritten with prolongated coarse fields.
    max_iter_coarse : int
        Cap on coarse SIMPLE iterations.
    min_coarse_axis : int
        Skip bootstrap if any coarse axis would be smaller than this.
    verbose : bool
        Print coarse solve summary.
    cancel_check : callable, optional
        Forward the parent's cooperative cancellation to the coarse solve.

    Returns
    -------
    info : dict with keys 'applied' (bool), 'coarse_iters' (int),
        'coarse_converged' (bool), 'coarse_residual' (float),
        'coarse_shape' (tuple), 'reason' (str if not applied).
    """
    Nx_c = solver_fine.Nx // 2
    Ny_c = solver_fine.Ny // 2
    Nz_c = solver_fine.Nz // 2

    if min(Nx_c, Ny_c, Nz_c) < min_coarse_axis:
        return {'applied': False, 'reason': 'coarse-too-small',
                'coarse_shape': (Nx_c, Ny_c, Nz_c)}

    # Defer import to dodge circular import (anderson lives in same package)
    from .simple_solver_3d import SIMPLESolver3D

    fx = solver_fine.Nx // Nx_c   # exactly 2 by construction
    fy = solver_fine.Ny // Ny_c
    fz = solver_fine.Nz // Nz_c

    # Block-average geometry coefficients onto coarse grid.
    K_arr_c = _block_average_2d(solver_fine.K_arr, fy, fz)
    cF_arr_c = _block_average_2d(solver_fine.cF_arr, fy, fz)

    # eps may be uniform (scalar) or zoned (3D array).
    eps_uniform = float(solver_fine.eps)
    has_zoned_eps = (solver_fine.eps_field.std() > 1e-12)
    if has_zoned_eps:
        eps_c_field = _block_average_3d(solver_fine.eps_field, fx, fy, fz)
        eps_scalar = float(eps_c_field.mean())
    else:
        eps_c_field = None
        eps_scalar = eps_uniform

    # Reuse mean rho for ideal-gas init (compressible re-establishes inside).
    rho_init = float(solver_fine.rho_field.mean())

    solver_coarse = SIMPLESolver3D(
        Lx=solver_fine.Lx, Ly=solver_fine.Ly, Lz=solver_fine.Lz,
        Nx=Nx_c, Ny=Ny_c, Nz=Nz_c,
        rho=rho_init, mu=solver_fine.mu,
        T_in=solver_fine.T_in,
        v_inlet=np.zeros((Nx_c, Nz_c)),
        eps=eps_scalar,
        K_arr=K_arr_c, cF_arr=cF_arr_c,
        P_ref_abs=solver_fine.P_ref_abs,
        alpha_u=solver_fine.alpha_u,
        alpha_p=solver_fine.alpha_p,
        fluid_type=solver_fine.fluid_type,
        R_gas=solver_fine.R_gas,
        alpha_rho=solver_fine.alpha_rho,
        inlet_rect=solver_fine.inlet_rect,
        outlet_rect=solver_fine.outlet_rect,
    )
    if eps_c_field is not None:
        solver_coarse.eps_field = np.ascontiguousarray(
            eps_c_field, dtype=np.float64)
        solver_coarse._mu_eff_field = np.ascontiguousarray(
            solver_fine.mu / eps_c_field, dtype=np.float64)

    # Fine velocity already contains its open fraction. Divide once to obtain
    # flux on the physical opening, then integrate onto actual coarse faces.
    flux = getattr(solver_fine, '_massflux_target',
                   solver_fine.rho_field[:, 0, :] * solver_fine.v_inlet_field)
    mass_open = np.divide(
        flux * solver_fine.eps_field[:, 0, :], solver_fine.inlet_frac,
        out=np.zeros_like(flux), where=solver_fine.inlet_frac > 0.)
    xlo, xhi, zlo, zhi = solver_fine.inlet_rect
    ox = _open_intersections(solver_fine.dx, solver_coarse.dx, xlo, xhi)
    oz = _open_intersections(solver_fine.dz, solver_coarse.dz, zlo, zhi)
    area = solver_coarse.dx[:, None] * solver_coarse.dz[None, :]
    solver_coarse.v_inlet_field = np.ascontiguousarray(
        (ox @ mass_open @ oz.T) / (area * rho_init * solver_coarse.eps_field[:, 0, :]))
    solver_coarse.v_inlet = float(solver_coarse.v_inlet_field.mean())
    solver_coarse.v[:, 0, :] = solver_coarse.v_inlet_field

    # Inherit the supported adaptive pressure tolerance policy.
    solver_coarse.use_adaptive_amg_tol = getattr(
        solver_fine, 'use_adaptive_amg_tol', True)
    solver_coarse.convergence_mode = 'f2'  # Parent already validated its captured choice.

    converged, iters = solver_coarse.solve(
        max_iter=max_iter_coarse, verbose=verbose, cancel_check=cancel_check)
    res_final = float(solver_coarse.residuals[-1]) if solver_coarse.residuals else float('nan')

    # Prolongate (u, v, w, P) onto fine staggered shapes.
    solver_fine.u[:] = _trilinear_zoom(solver_coarse.u, solver_fine.u.shape)
    solver_fine.v[:] = _trilinear_zoom(solver_coarse.v, solver_fine.v.shape)
    solver_fine.w[:] = _trilinear_zoom(solver_coarse.w, solver_fine.w.shape)
    solver_fine.P[:] = _trilinear_zoom(solver_coarse.P, solver_fine.P.shape)

    # Preserve any invalid prolonged field for the parent F2 exit guard.
    # Neither density clipping nor reapplying a boundary may erase it.
    if f2_state_is_finite(
            solver_fine, (solver_fine.u, solver_fine.v, solver_fine.w)):
        solver_fine.v[:, 0, :] = solver_fine.v_inlet_field
        if solver_fine.fluid_type == 'ideal_gas':
            solver_fine._update_density()

    # Prolongation can smear a partial outlet across its edge. Reapply the
    # fine solver's existing boundary closure using the fine physical support.
    from ._kernels_simple_3d import _v_bc_3d
    if f2_state_is_finite(
            solver_fine, (solver_fine.u, solver_fine.v, solver_fine.w)):
        _v_bc_3d(solver_fine.u, solver_fine.v, solver_fine.w,
                 solver_fine.v_inlet_field, solver_fine.rho_field,
                 solver_fine.eps_field, solver_fine.outlet_mask_ij,
                 solver_fine.Nx, solver_fine.Ny, solver_fine.Nz,
                 solver_fine.dx, solver_fine.dy, solver_fine.dz)

    return {
        'applied': True,
        'coarse_iters': int(iters),
        'coarse_converged': bool(converged),
        'coarse_residual': res_final,
        'coarse_shape': (Nx_c, Ny_c, Nz_c),
    }
