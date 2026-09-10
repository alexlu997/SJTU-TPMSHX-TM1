"""
df_projection.py — 投影 2D 几何设计到 SIMPLE 1D K/c_F 数组 + master 加密网格

用于 optimizer 和 runs 共享。SIMPLE 内核的 K/c_F 数组是 1D (Ny_sim,) 行向，
这里把 2D grid_cells 或 sigmoid 连续场投影到 SIMPLE 的流向轴。

核心原则（2026-04-17）：生产 dP 路径严格走 SIMPLE，不允许任何解析公式
（1D D-F、f-Re、compute_dP_continuous 等）绕过 SIMPLE。

对应报告：vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11-§12
"""
from __future__ import annotations
from typing import Any, List, Optional, Tuple

import numpy as np
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
from .tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.models.grid import build_wall_refined_1d  # noqa: F401 - existing public name


from sjtu_tpmshx.models.grid import build_master_refined_grid  # noqa: F401


def project_cells_to_streamwise_K_cF(grid_cells: List[dict],
                                       tpms_type: str,
                                       k_s: float,
                                       Ny_sim: int,
                                       fluid: str,
                                       streamwise_dx: Optional[np.ndarray] = None
                                       ) -> Tuple[np.ndarray, np.ndarray]:
    """Project 2D grid_cells onto streamwise axis for SIMPLE's 1D K/c_F arrays.

    For fluid A (+x streamwise): SIMPLE's y-axis maps to real x. For each SIMPLE
    row j, find grid_cells at real x_frac (streamwise cell-centre position) and
    average (L, t) weighted by cross-stream (y) overlap.

    For fluid B (-y streamwise): SIMPLE's y-axis is flipped relative to real y
    (SIMPLE y=0 is fluid B's inlet = real y_frac=1). Real y_frac = 1 - s_frac.

    streamwise_dx : 1D array of shape (Ny_sim,), cell widths along SIMPLE's y
        (streamwise). If None, assume uniform spacing. Pass for non-uniform
        (wall-refined) streamwise grid so s_frac reflects actual cell centre
        positions, not uniform (j+0.5)/Ny_sim.

    Returns (K_arr, cF_arr) both shape (Ny_sim,) float64.

    This loses cross-stream variation but is the best 1D projection available
    under SIMPLE's current K/c_F array shape limitation.
    """

    # Cell-centre s_frac: uniform or from streamwise_dx (B2 2.3 helper)
    s_fracs = _cell_centre_fracs(Ny_sim, streamwise_dx)

    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)

    for j in range(Ny_sim):
        s_frac = float(s_fracs[j])
        if fluid == 'A':
            real_x = s_frac
            cells_at = [gc for gc in grid_cells if gc['x0'] <= real_x < gc['x1']]
            cs_key_lo = 'y0'; cs_key_hi = 'y1'
        elif fluid == 'B':
            real_y = 1.0 - s_frac   # flip
            cells_at = [gc for gc in grid_cells if gc['y0'] <= real_y < gc['y1']]
            cs_key_lo = 'x0'; cs_key_hi = 'x1'
        else:
            raise ValueError(f"fluid must be 'A' or 'B', got {fluid!r}")

        if not cells_at:
            cells_at = [grid_cells[0]]

        total_w = 0.0; L_sum = 0.0; t_sum = 0.0
        for gc in cells_at:
            w = gc[cs_key_hi] - gc[cs_key_lo]
            L_sum += gc['L'] * w; t_sum += gc['t'] * w
            total_w += w
        L_avg = L_sum / total_w if total_w > 0 else cells_at[0]['L']
        t_avg = t_sum / total_w if total_w > 0 else cells_at[0]['t']

        g = tpms_geometry(tpms_type, L_avg, t_avg, k_s)
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = g['epsilon'] / 2.0

    K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_row)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)


def _cell_centre_fracs(n_target: int,
                       widths: Optional[np.ndarray]) -> np.ndarray:
    """Cell-centre fractional coordinates of a target axis (B2 2.3 —
    single source for the block previously copy-pasted in the 2D
    projector, the 3D streamwise axis and the 3D z axis). ``widths``
    None → uniform; else non-uniform cell widths (wall-refined grids)."""
    if widths is None:
        return (np.arange(n_target) + 0.5) / n_target
    w = np.asarray(widths, dtype=np.float64)
    cum = np.concatenate([[0.0], np.cumsum(w)])
    return 0.5 * (cum[:-1] + cum[1:]) / w.sum()


def _nearest_src_idx(fracs: np.ndarray, src_n: int) -> np.ndarray:
    """Nearest-neighbour source indices for fractional probe points."""
    return np.clip((fracs * src_n).astype(int), 0, src_n - 1)


def _stream_profile(fields: Tuple[np.ndarray, ...], fluid: str
                    ) -> Tuple[Tuple[np.ndarray, ...], int]:
    """Streamwise 1-lower-dim profiles of ``fields`` for one fluid:
    A = mean over real y (axis 1); B = mean over real x (axis 0) then
    flip (B flows -y). Returns (profiles, src_stream_n)."""
    if fluid == 'A':
        prof = tuple(f.mean(axis=1) for f in fields)
        return prof, fields[0].shape[0]
    if fluid == 'B':
        prof = tuple(f.mean(axis=0)[::-1].copy() for f in fields)
        return prof, fields[0].shape[1]
    raise ValueError(f"fluid must be 'A' or 'B', got {fluid!r}")


def project_fields_to_streamwise_K_cF(L_field: np.ndarray,
                                       t_field: np.ndarray,
                                       tpms_type: str,
                                       k_s: float,
                                       Nx_field: int,
                                       Ny_field: int,
                                       Ny_sim: int,
                                       fluid: str,
                                       streamwise_dx: Optional[np.ndarray] = None
                                       ) -> Tuple[np.ndarray, np.ndarray]:
    """Project 2D sigmoid fields onto streamwise axis for SIMPLE's K/c_F arrays.

    L_field, t_field shape: (Nx_field, Ny_field) in real coords.
    For fluid A: average along real y at each real x, then resample to Ny_sim.
    For fluid B: average along real x at each real y, flip, then resample.

    Returns (K_arr, cF_arr) both shape (Ny_sim,) float64.
    """

    (L_1d, t_1d), _src_n = _stream_profile((L_field, t_field), fluid)
    del Nx_field, Ny_field   # kept in the signature for call-site compat
    src_n = _src_n

    s_fracs = _cell_centre_fracs(Ny_sim, streamwise_dx)
    src_idx = _nearest_src_idx(s_fracs, src_n)

    # Per-cell loop kept loop-form: eps_f derives from tpms_geometry per
    # (L, t) probe and the float evaluation order is gate-pinned.
    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)
    for j in range(Ny_sim):
        L_avg = float(L_1d[src_idx[j]]); t_avg = float(t_1d[src_idx[j]])
        g = tpms_geometry(tpms_type, L_avg, t_avg, k_s)
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = g['epsilon'] / 2.0

    K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_row)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)


def override_simple_K_cF(sim: Any,
                          tpms_type: str,
                          k_s: float,
                          Ny_sim: int,
                          grid_cells: Optional[List[dict]],
                          L_field: Optional[np.ndarray],
                          t_field: Optional[np.ndarray],
                          fluid: str) -> None:
    """Project design geometry to streamwise axis, override sim._K_arr/_cF_arr.

    Reads sim.dy_arr (SIMPLE internal streamwise widths) to handle non-uniform
    grids correctly. No-op if neither grid_cells nor fields provided.
    """
    if grid_cells is None and L_field is None:
        return
    streamwise_dx = sim.dy_arr if sim.dy_arr is not None else None
    if grid_cells is not None:
        K_arr, cF_arr = project_cells_to_streamwise_K_cF(
            grid_cells, tpms_type, k_s, Ny_sim, fluid,
            streamwise_dx=streamwise_dx)
    else:
        Nx_field, Ny_field = L_field.shape
        K_arr, cF_arr = project_fields_to_streamwise_K_cF(
            L_field, t_field, tpms_type, k_s,
            Nx_field, Ny_field, Ny_sim, fluid,
            streamwise_dx=streamwise_dx)
    sim._K_arr[:] = K_arr
    sim._cF_arr[:] = cF_arr


from sjtu_tpmshx.models.grid import build_master_refined_grid_3d  # noqa: F401


def project_fields_to_streamwise_K_cF_3d(L_field: np.ndarray,
                                          t_field: np.ndarray,
                                          eps_f_field: np.ndarray,
                                          tpms_type: str,
                                          Ny_sim: int,
                                          Nz_sim: int,
                                          fluid: str,
                                          streamwise_dx: Optional[np.ndarray] = None,
                                          z_dx: Optional[np.ndarray] = None
                                          ) -> Tuple[np.ndarray, np.ndarray]:
    """Project 3D sigmoid fields onto SIMPLE 3D (Ny_sim, Nz_sim) K / c_F arrays.

    Fluid A: +x streamwise. Mean over real y (axis 1) → (Nx, Nz) then resample to
             (Ny_sim, Nz_sim).
    Fluid B: -y streamwise. Mean over real x (axis 0) → (Ny, Nz), flip along 0,
             resample to (Ny_sim, Nz_sim).

    L_field, t_field, eps_f_field shape: (Nx, Ny, Nz).
    streamwise_dx, z_dx: optional 1D arrays of SIMPLE-internal cell widths along
        the SIMPLE y (streamwise) and SIMPLE z axes respectively. Used to place
        resample probe points.

    Returns (K_arr, cF_arr) both shape (Ny_sim, Nz_sim) float64.
    """

    (L2, t2, e2), src_stream = _stream_profile(
        (L_field, t_field, eps_f_field), fluid)
    src_z = L_field.shape[2]

    # Nearest-neighbor resample on (stream, z) probe indices (B2 2.3:
    # fraction + index blocks via the shared helpers)
    s_idx = _nearest_src_idx(_cell_centre_fracs(Ny_sim, streamwise_dx),
                             src_stream)
    z_idx = _nearest_src_idx(_cell_centre_fracs(Nz_sim, z_dx), src_z)

    L_proj = L2[np.ix_(s_idx, z_idx)]
    t_proj = t2[np.ix_(s_idx, z_idx)]
    eps_proj = e2[np.ix_(s_idx, z_idx)]

    K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_proj, t_proj, eps_proj)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)


def extract_dP_from_simple(s: Any) -> float:
    """Extract inlet/outlet-averaged dP from a converged SIMPLE instance.

    Uses the inlet_frac/outlet_frac weighting (same convention as the Shanghai
    2D validation, now validate_shanghai_aligned.py) to handle partial
    inlet/outlet openings correctly. Geometric open-area
    weights — see `extract_dP_mass_flux_from_simple` for the ρ·|v| variant.
    """
    wA_in = s.inlet_frac; wA_out = s.outlet_frac
    mI = wA_in > 0.01; mO = wA_out > 0.5
    if not (mI.any() and mO.any()):
        return 0.0
    return float(np.average(s.P[mI, 0], weights=wA_in[mI])
               - np.average(s.P[mO, -1], weights=wA_out[mO]))


def extract_dP_mass_flux_from_simple(s: Any) -> float:
    """Mass-flux-weighted inlet/outlet dP.

    Weights each face cell by ρ·|v| so high-mass-flux streams dominate the
    reduction — closer to the physical inlet/outlet pressure the fluid
    actually "feels" when the profile is skewed. Falls back to
    `extract_dP_from_simple` when mass flux is zero (cold solution).

    SIMPLE 2D axis convention: P[i, j], streamwise = j, inlet face at
    j=0, outlet at j=Ny-1. v is staggered along j.
    """
    import numpy as _np
    v_in = s.v[:, 0] if s.v.shape[1] > 0 else _np.zeros(s.P.shape[0])
    v_out = s.v[:, -1] if s.v.shape[1] > 0 else _np.zeros(s.P.shape[0])
    rho_in = s.rho_field[:, 0]
    rho_out = s.rho_field[:, -1]
    wI = rho_in * _np.abs(v_in) * s.inlet_frac
    wO = rho_out * _np.abs(v_out) * s.outlet_frac
    mI = wI > 1e-9; mO = wO > 1e-9
    if not (mI.any() and mO.any()):
        return extract_dP_from_simple(s)
    return float(_np.average(s.P[mI, 0], weights=wI[mI])
               - _np.average(s.P[mO, -1], weights=wO[mO]))
