"""Historical Darcy-Forchheimer and LTNE kernels on triangular meshes.

Retained for the legacy polygon implementation; polygon GUI compute is disabled.
Velocity solves div(U) = 0 with U = -grad(P) / R(|U|), where
R = mu/K + rho*c_F*|U|. Velocity and D-F coefficients use the interstitial
convention. The energy kernel couples two fluids and one solid.
"""

import numpy as np
from numba import njit
from scipy import sparse
from scipy.sparse.linalg import spsolve
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, predict_K_cF_vec
from .tpms_calc import (air_density, air_conductivity, P_atm,
                       nu_from_Re)
from .unstructured_mesh import (BC_INTERIOR, BC_INLET_A, BC_OUTLET_A,
                               BC_INLET_B, BC_OUTLET_B)

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ===================================================================
#  Porous resistance (Darcy-Forchheimer)
# ===================================================================

@njit(cache=True)
def _resistance(umag, K, cF, mu, rho):
    """Porous resistance R [kg/(m³·s)]: source = R·U.

    D-F closure: R = μ/K + ρ·c_F·|u|. K and c_F are interstitial-form
    coefficients supplied by the caller (scalar or per-cell array).
    """
    if umag < 1e-10:
        return mu / K  # pure Darcy when velocity vanishes
    return mu / K + rho * cF * umag


# ===================================================================
#  Darcy-Forchheimer velocity solver (replaces SIMPLE for porous media)
# ===================================================================

def solve_velocity_darcy(mesh, tpms_type, L_mm, t_mm, eps, r_h,
                         rho, mu, T_in,
                         u_in, edge_in, bc_inlet, bc_outlet,
                         max_iter=30, tol=1e-3, verbose=True,
                         K_arr=None, cF_arr=None,
                         **_ignored):
    """
    Darcy-Forchheimer velocity solver for fully porous domain.

    Solves the pressure Poisson equation directly:
        nabla·(D·nabla P) = 0,   D = 1/R(|U|)
        U = -D·nabla P

    D-F closure via ConstDF-v1 surrogate (df_surrogate.predict.predict_K_cF).
    Supports per-cell (K, c_F) via optional K_arr / cF_arr (shape [n_cells]).
    If not provided, uniform (L_mm, t_mm, eps) is used and broadcast.

    Returns: u_cell, v_cell, P_cell, face_Un
    """
    nc = mesh.n_cells

    # Build per-cell (K, c_F) arrays from ConstDF-v1 surrogate
    if (K_arr is None) ^ (cF_arr is None):
        raise ValueError("Provide both K_arr and cF_arr, or neither.")
    if K_arr is None:
        K_val, cF_val = predict_K_cF(tpms_type, float(L_mm), float(t_mm),
                                     float(eps) / 2.0)
        K_arr = np.full(nc, K_val, dtype=np.float64)
        cF_arr = np.full(nc, cF_val, dtype=np.float64)

    # Inlet velocity direction (inward normal of inlet edge)
    in_n = mesh.inlet_normal(edge_in)
    u_in_x = u_in * in_n[0]
    u_in_y = u_in * in_n[1]

    # Initial R from inlet velocity (per-cell from zone params)
    R_cell = np.empty(nc)
    for ci in range(nc):
        R_cell[ci] = _resistance(u_in, K_arr[ci], cF_arr[ci], mu, rho)

    P = np.zeros(nc)
    u_cell = np.zeros(nc)
    v_cell = np.zeros(nc)
    face_Un = np.zeros((nc, 3))

    for it in range(1, max_iter + 1):
        D_cell = 1.0 / np.maximum(R_cell, 1e-10)

        # ── Assemble: nabla·(D nabla P) = 0 ──
        rows, cols, vals = [], [], []
        b = np.zeros(nc)

        for ci in range(nc):
            diag = 0.0
            for fi in range(3):
                j  = mesh.nbr[ci, fi]
                bc = mesh.bc_type[ci, fi]
                fl = mesh.face_len[ci, fi]
                d  = max(mesh.dCF[ci, fi], 1e-12)

                if bc == BC_INTERIOR:
                    D_f = 0.5 * (D_cell[ci] + D_cell[j])
                    coeff = D_f * fl / d
                    diag += coeff
                    rows.append(ci); cols.append(j); vals.append(-coeff)

                elif bc == bc_inlet:
                    # Neumann: known velocity flux = U·n * S_f
                    # Since D·dP/dn = -U_n, boundary flux = -U_n * fl
                    Un_in = (u_in_x * mesh.face_nx[ci, fi]
                             + u_in_y * mesh.face_ny[ci, fi])
                    b[ci] -= Un_in * fl

                elif bc == bc_outlet:
                    # Dirichlet: P = 0 (gauge)
                    D_f = D_cell[ci]
                    coeff = D_f * fl / d
                    diag += coeff

                # Wall: zero flux → no contribution

            rows.append(ci); cols.append(ci); vals.append(max(diag, 1e-20))

        A = sparse.coo_matrix((vals, (rows, cols)), shape=(nc, nc)).tocsr()
        P = spsolve(A, b)

        # ── Compute face-normal velocity from P differences ──
        face_Un[:] = 0.0
        for ci in range(nc):
            D_ci = D_cell[ci]
            for fi in range(3):
                j  = mesh.nbr[ci, fi]
                bc = mesh.bc_type[ci, fi]
                d  = max(mesh.dCF[ci, fi], 1e-12)

                if bc == BC_INTERIOR:
                    D_f = 0.5 * (D_cell[ci] + D_cell[j])
                    face_Un[ci, fi] = -D_f * (P[j] - P[ci]) / d
                elif bc == bc_inlet:
                    nx = mesh.face_nx[ci, fi]
                    ny = mesh.face_ny[ci, fi]
                    face_Un[ci, fi] = u_in_x * nx + u_in_y * ny
                elif bc == bc_outlet:
                    face_Un[ci, fi] = -D_ci * (0.0 - P[ci]) / d
                # wall: 0

        # ── Cell velocity: Green-Gauss for R update, lstsq for display ──
        u_cell[:] = 0.0
        v_cell[:] = 0.0
        _umag_gg = np.empty(nc)   # Green-Gauss |U| (robust, for R)

        # Physical velocity cap: no cell should exceed 20× inlet speed
        _umag_cap = u_in * 20.0
        _vol_min = np.percentile(mesh.cell_areas, 5) * 0.1  # robust floor

        for ci in range(nc):
            vol = max(mesh.cell_areas[ci], _vol_min)
            D_ci = D_cell[ci]

            # Green-Gauss gradient of P → velocity (robust for R)
            gradP_x = 0.0; gradP_y = 0.0
            for fi in range(3):
                j  = mesh.nbr[ci, fi]
                bc = mesh.bc_type[ci, fi]
                if bc == BC_INTERIOR:
                    Pf = 0.5 * (P[ci] + P[j])
                elif bc == bc_outlet:
                    Pf = 0.0
                else:
                    Pf = P[ci]
                gradP_x += Pf * mesh.face_nx[ci, fi] * mesh.face_len[ci, fi]
                gradP_y += Pf * mesh.face_ny[ci, fi] * mesh.face_len[ci, fi]
            gradP_x /= vol; gradP_y /= vol
            ug = -D_ci * gradP_x
            vg = -D_ci * gradP_y
            umag_gg = np.sqrt(ug * ug + vg * vg)

            # Clamp degenerate cells
            if umag_gg > _umag_cap and umag_gg > 0:
                scale = _umag_cap / umag_gg
                ug *= scale; vg *= scale
                umag_gg = _umag_cap
            _umag_gg[ci] = umag_gg

            # Least-squares from face normals (for display)
            a00 = a01 = a11 = r0 = r1 = 0.0
            for fi in range(3):
                nx = mesh.face_nx[ci, fi]
                ny = mesh.face_ny[ci, fi]
                Un = face_Un[ci, fi]
                a00 += nx * nx; a01 += nx * ny; a11 += ny * ny
                r0  += nx * Un; r1  += ny * Un
            det = a00 * a11 - a01 * a01
            if abs(det) > 1e-20:
                u_cell[ci] = ( a11 * r0 - a01 * r1) / det
                v_cell[ci] = (-a01 * r0 + a00 * r1) / det
                # Also clamp lstsq result
                umag_ls = np.sqrt(u_cell[ci]**2 + v_cell[ci]**2)
                if umag_ls > _umag_cap and umag_ls > 0:
                    scale = _umag_cap / umag_ls
                    u_cell[ci] *= scale; v_cell[ci] *= scale
            else:
                # Degenerate triangle: use clamped Green-Gauss
                u_cell[ci] = ug
                v_cell[ci] = vg

        # ── Update R(|U|) using Green-Gauss |U| (always non-zero) ──
        R_new = np.empty(nc)
        for ci in range(nc):
            umag = max(_umag_gg[ci], 0.01)
            R_new[ci] = _resistance(umag, K_arr[ci], cF_arr[ci], mu, rho)

        dR = np.abs(R_new - R_cell) / np.maximum(R_cell, 1e-10)
        max_dR = dR.max()
        R_cell = 0.7 * R_cell + 0.3 * R_new   # under-relax

        if verbose and (it <= 3 or it % 5 == 0):
            _log.info(f"  Darcy iter {it:3d}: max(dR/R)={max_dR:.3e}, "
                      f"|U|=[{_umag_gg.min():.3f}, {_umag_gg.max():.3f}]")

        if max_dR < tol and it > 1:
            if verbose:
                _log.info(f"  [OK] Darcy converged at iter {it}")
            break

    if verbose:
        umag = np.sqrt(u_cell**2 + v_cell**2)
        _log.info(f"  |U|: [{umag.min():.3f}, {umag.max():.3f}], mean={umag.mean():.3f}")

    return u_cell, v_cell, P, face_Un


# ===================================================================
#  LTNE Energy solver (face-velocity based, unchanged)
# ===================================================================

@njit(cache=True)
def _energy_sweep(Ta, Tb, Ts,
                  face_Un_A, face_Un_B,
                  nbr, face_len, dCF, bc_type,
                  cell_areas, n_cells,
                  K_ffA_arr, K_ffB_arr, K_ss_arr,
                  h_vA, h_vB,
                  eps_f_arr, rho_cp_fA, rho_cp_fB,
                  T_inA, T_inB,
                  n_iters):
    """Gauss-Seidel LTNE energy solve.

    K_ffA_arr, K_ffB_arr, K_ss_arr, eps_f_arr: 1D per-cell arrays [n_cells].
    h_vA, h_vB: 1D per-cell arrays [n_cells].
    Uses harmonic-mean face conductivity at zone interfaces.
    """
    max_chg = 0.0

    for _it in range(n_iters):
        max_chg = 0.0

        # ── Sweep Fluid A ──
        for ci in range(n_cells):
            vol = cell_areas[ci]
            hvA = h_vA[ci]
            Ka = K_ffA_arr[ci]
            ef = eps_f_arr[ci]
            aP = hvA * vol
            rhs = hvA * vol * Ts[ci]

            for fi in range(3):
                j = nbr[ci, fi]
                bc = bc_type[ci, fi]
                d_inv = face_len[ci, fi] / max(dCF[ci, fi], 1e-10)

                if bc == BC_INTERIOR:
                    Kj = K_ffA_arr[j]
                    Kf = 2.0 * Ka * Kj / (Ka + Kj + 1e-30)
                    Df = Kf * d_inv
                    Ff = ef * rho_cp_fA * face_Un_A[ci, fi] * face_len[ci, fi]
                    aP  += Df + max(Ff, 0.0)
                    rhs += (Df + max(-Ff, 0.0)) * Ta[j]
                elif bc == BC_INLET_A:
                    Df = Ka * d_inv
                    Ff = ef * rho_cp_fA * face_Un_A[ci, fi] * face_len[ci, fi]
                    aP  += Df + max(Ff, 0.0)
                    rhs += (Df + max(-Ff, 0.0)) * T_inA
                elif bc == BC_OUTLET_A:
                    Ff = ef * rho_cp_fA * face_Un_A[ci, fi] * face_len[ci, fi]
                    aP += max(Ff, 0.0)

            if aP > 1e-30:
                new_val = rhs / aP
                chg = abs(new_val - Ta[ci])
                if chg > max_chg: max_chg = chg
                Ta[ci] = new_val

        # ── Sweep Fluid B ──
        for ci in range(n_cells):
            vol = cell_areas[ci]
            hvB = h_vB[ci]
            Kb = K_ffB_arr[ci]
            ef = eps_f_arr[ci]
            aP = hvB * vol
            rhs = hvB * vol * Ts[ci]

            for fi in range(3):
                j = nbr[ci, fi]
                bc = bc_type[ci, fi]
                d_inv = face_len[ci, fi] / max(dCF[ci, fi], 1e-10)

                if bc == BC_INTERIOR:
                    Kj = K_ffB_arr[j]
                    Kf = 2.0 * Kb * Kj / (Kb + Kj + 1e-30)
                    Df = Kf * d_inv
                    Ff = ef * rho_cp_fB * face_Un_B[ci, fi] * face_len[ci, fi]
                    aP  += Df + max(Ff, 0.0)
                    rhs += (Df + max(-Ff, 0.0)) * Tb[j]
                elif bc == BC_INLET_B:
                    Df = Kb * d_inv
                    Ff = ef * rho_cp_fB * face_Un_B[ci, fi] * face_len[ci, fi]
                    aP  += Df + max(Ff, 0.0)
                    rhs += (Df + max(-Ff, 0.0)) * T_inB
                elif bc == BC_OUTLET_B:
                    Ff = ef * rho_cp_fB * face_Un_B[ci, fi] * face_len[ci, fi]
                    aP += max(Ff, 0.0)

            if aP > 1e-30:
                new_val = rhs / aP
                chg = abs(new_val - Tb[ci])
                if chg > max_chg: max_chg = chg
                Tb[ci] = new_val

        # ── Sweep Solid ──
        for ci in range(n_cells):
            vol = cell_areas[ci]
            hvA = h_vA[ci]; hvB = h_vB[ci]
            Ks = K_ss_arr[ci]
            aP = (hvA + hvB) * vol
            rhs = (hvA * Ta[ci] + hvB * Tb[ci]) * vol

            for fi in range(3):
                j = nbr[ci, fi]
                bc = bc_type[ci, fi]
                d_inv = face_len[ci, fi] / max(dCF[ci, fi], 1e-10)
                if bc == BC_INTERIOR:
                    Kj = K_ss_arr[j]
                    Kf = 2.0 * Ks * Kj / (Ks + Kj + 1e-30)
                    Ds = Kf * d_inv
                    aP += Ds
                    rhs += Ds * Ts[j]

            if aP > 1e-30:
                new_val = rhs / aP
                chg = abs(new_val - Ts[ci])
                if chg > max_chg: max_chg = chg
                Ts[ci] = new_val

        if max_chg < 1e-10:
            break

    return max_chg


def solve_energy(mesh, face_Un_A, face_Un_B,
                 K_ffA, K_ffB, K_ss, h_vA, h_vB,
                 rho_cp_fA, rho_cp_fB, epsilon,
                 T_inA, T_inB,
                 max_iter=50000, tol=1e-6, progress_cb=None):
    """LTNE energy solve on triangular mesh.

    K_ffA, K_ffB, K_ss, epsilon: scalar or 1D array [n_cells].
    h_vA, h_vB: 1D array [n_cells] (always per-cell).

    Returns Ta, Tb, Ts.
    """
    nc = mesh.n_cells

    # Promote scalars to per-cell arrays
    def _to_1d(val):
        if np.ndim(val) == 0:
            return np.full(nc, float(val), dtype=np.float64)
        return np.ascontiguousarray(np.asarray(val, dtype=np.float64))

    K_ffA_arr = _to_1d(K_ffA)
    K_ffB_arr = _to_1d(K_ffB)
    K_ss_arr  = _to_1d(K_ss)
    h_vA_arr  = _to_1d(h_vA)
    h_vB_arr  = _to_1d(h_vB)

    if np.ndim(epsilon) == 0:
        eps_f_arr = np.full(nc, float(epsilon) / 2.0, dtype=np.float64)
    else:
        eps_f_arr = np.ascontiguousarray(
            np.asarray(epsilon, dtype=np.float64) / 2.0)

    Ta = np.full(nc, 0.5 * (T_inA + T_inB))
    Tb = Ta.copy(); Ts = Ta.copy()

    for ci in range(nc):
        for fi in range(3):
            if mesh.bc_type[ci, fi] == BC_INLET_A: Ta[ci] = T_inA
            if mesh.bc_type[ci, fi] == BC_INLET_B: Tb[ci] = T_inB

    chunk = 500
    done = 0
    while done < max_iter:
        n = min(chunk, max_iter - done)
        chg = _energy_sweep(
            Ta, Tb, Ts, face_Un_A, face_Un_B,
            mesh.nbr, mesh.face_len, mesh.dCF, mesh.bc_type,
            mesh.cell_areas, nc,
            K_ffA_arr, K_ffB_arr, K_ss_arr, h_vA_arr, h_vB_arr,
            eps_f_arr, rho_cp_fA, rho_cp_fB, T_inA, T_inB, n)
        done += n
        if progress_cb: progress_cb(done, max_iter)
        if chg < tol: break

    return Ta, Tb, Ts


# ===================================================================
#  High-level wrapper
# ===================================================================

_RE_FLOOR = 800.0   # Nu correlation validated for D_h-Re >= 800 (post-refit 2026-04-26;
                     # = 2·400 since training Excel Re used r_h convention)


def _compute_local_hv(umag, tpms_type, L_mm, t_mm, eps, A_0, D_h,
                      rho, mu, T_in):
    """Compute per-cell volumetric HTC from local velocity magnitude.

    Re(x,y) → Nu(x,y) → h_sf(x,y) → h_v(x,y) = h_sf * A_0

    Re is clamped to _RE_FLOOR (800) at the lower end so that the
    Nu correlation is never extrapolated below its validated range.
    In low-velocity regions this gives a *conservative* (upper-bound)
    estimate of h_v, which is physically safer than extrapolating
    the power-law to near-zero Re.
    """
    rho_ref = air_density(T_in, P_atm)
    k_f = air_conductivity(T_in)
    D_h_mm = D_h * 1000.0
    eps_A = 0.5 * eps   # per-stream void fraction (post-refit 2026-04-26)
    nc = len(umag)
    h_v = np.empty(nc)
    n_clamped = 0

    for ci in range(nc):
        u_local = max(umag[ci], 0.01)
        # D_h-based Re (single-stream u): matches refit Nu correlation
        Re_local = rho_ref * u_local * D_h / mu
        if Re_local < _RE_FLOOR:
            Re_local = _RE_FLOOR
            n_clamped += 1
        Nu = nu_from_Re(tpms_type, Re_local, eps_A, L_mm, D_h_mm)
        h_sf = Nu * k_f / D_h
        h_v[ci] = h_sf * A_0

    if n_clamped > 0:
        import warnings
        pct = n_clamped / nc * 100
        warnings.warn(
            f"{pct:.0f}% of cells have Re < {_RE_FLOOR:.0f} "
            f"(Nu clamped to Re={_RE_FLOOR:.0f} value).",
            UserWarning, stacklevel=2)

    return h_v


def solve_polygon_domain(mesh, tpms_type, L_mm, t_mm, eps, D_h,
                         rho_A, mu_A, rho_B, mu_B,
                         T_inA, T_inB, u_A, u_B,
                         edge_inA, edge_inB,
                         K_ffA, K_ffB, K_ss, h_vA, h_vB, cp_f,
                         A_0=None,
                         max_iter_energy=50000,
                         progress_cb=None, verbose=True,
                         zone_config=None, **_ignored):
    """Complete solve: Darcy velocity (both fluids) + LTNE energy.

    If A_0 is provided, h_vA/h_vB are recomputed per-cell from the
    local velocity field (spatially varying h_v). Otherwise the scalar
    h_vA/h_vB passed by the caller are broadcast to all cells.

    If zone_config is provided, per-cell porous parameters are built
    from zone definitions (overrides scalar eps, K_ff, K_ss, h_v, etc.).
    """
    nc = mesh.n_cells
    r_h = D_h / 2.0

    # Build per-cell zone arrays if zone_config is provided
    darcy_kw_A = {}
    darcy_kw_B = {}
    energy_kw = {}
    if zone_config is not None:
        # Determine domain height from mesh
        ymin = mesh.cell_centers[:, 1].min()
        ymax = mesh.cell_centers[:, 1].max()
        H_mesh = ymax - ymin
        if H_mesh < 1e-12:
            H_mesh = 1.0  # fallback

        za = zone_config.build_unstructured_arrays(
            mesh.cell_centers[:, 1] - ymin, nc, H_mesh)

        # Darcy solver: per-cell (K, c_F) via ConstDF-v1 surrogate
        L_row = np.empty(nc, dtype=np.float64)
        t_row = np.empty(nc, dtype=np.float64)
        for ci in range(nc):
            zi = za['zone_id'][ci]
            zp = za['zone_params'][zi]
            L_row[ci] = zp['L_mm']
            t_row[ci] = zp['t_mm']
        eps_f_arr = za['eps_arr'] / 2.0  # single-channel porosity
        K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_arr)

        darcy_kw_A = dict(K_arr=K_arr, cF_arr=cF_arr)
        darcy_kw_B = dict(darcy_kw_A)  # shallow copy to avoid aliasing

        energy_kw = dict(
            K_ffA=za['K_ffA_arr'], K_ffB=za['K_ffB_arr'],
            K_ss=za['K_ss_arr'], epsilon=za['eps_arr'],
        )

    if verbose: _log.info("=== Darcy solver: Fluid A ===")
    uA, vA, PA, fUnA = solve_velocity_darcy(
        mesh, tpms_type, L_mm, t_mm, eps, r_h,
        rho_A, mu_A, T_inA, u_A, edge_inA,
        BC_INLET_A, BC_OUTLET_A, verbose=verbose, **darcy_kw_A)

    if verbose: _log.info("=== Darcy solver: Fluid B ===")
    uB, vB, PB, fUnB = solve_velocity_darcy(
        mesh, tpms_type, L_mm, t_mm, eps, r_h,
        rho_B, mu_B, T_inB, u_B, edge_inB,
        BC_INLET_B, BC_OUTLET_B, verbose=verbose, **darcy_kw_B)

    # ── Compute spatially-varying h_v from local velocity ──
    if zone_config is not None:
        # Per-cell h_v from zone properties (already in zone arrays)
        h_vA_arr = za['h_vA_arr'].copy()
        h_vB_arr = za['h_vB_arr'].copy()
    elif A_0 is not None:
        umag_A = np.sqrt(uA**2 + vA**2)
        umag_B = np.sqrt(uB**2 + vB**2)
        h_vA_arr = _compute_local_hv(umag_A, tpms_type, L_mm, t_mm,
                                     eps, A_0, D_h, rho_A, mu_A, T_inA)
        h_vB_arr = _compute_local_hv(umag_B, tpms_type, L_mm, t_mm,
                                     eps, A_0, D_h, rho_B, mu_B, T_inB)
    else:
        h_vA_arr = np.full(nc, h_vA)
        h_vB_arr = np.full(nc, h_vB)

    if verbose:
        _log.info(f"  h_vA: [{h_vA_arr.min():.0f}, {h_vA_arr.max():.0f}] W/(m3.K)")
        _log.info(f"  h_vB: [{h_vB_arr.min():.0f}, {h_vB_arr.max():.0f}] W/(m3.K)")

    # Energy solver params
    e_K_ffA = energy_kw.get('K_ffA', K_ffA)
    e_K_ffB = energy_kw.get('K_ffB', K_ffB)
    e_K_ss  = energy_kw.get('K_ss', K_ss)
    e_eps   = energy_kw.get('epsilon', eps)

    if verbose: _log.info("=== Solving energy (LTNE) ===")
    Ta, Tb, Ts = solve_energy(
        mesh, fUnA, fUnB,
        e_K_ffA, e_K_ffB, e_K_ss, h_vA_arr, h_vB_arr,
        rho_A * cp_f, rho_B * cp_f, e_eps,
        T_inA, T_inB,
        max_iter=max_iter_energy, progress_cb=progress_cb)

    if verbose:
        _log.info(f"  Ta: [{Ta.min():.1f}, {Ta.max():.1f}] K")
        _log.info(f"  Tb: [{Tb.min():.1f}, {Tb.max():.1f}] K")
        _log.info(f"  Ts: [{Ts.min():.1f}, {Ts.max():.1f}] K")

    return {'u_A': uA, 'v_A': vA, 'P_A': PA, 'face_Un_A': fUnA,
            'u_B': uB, 'v_B': vB, 'P_B': PB, 'face_Un_B': fUnB,
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts}
