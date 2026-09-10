"""
df_projection.py — 投影 2D 几何设计到 SIMPLE 1D K/c_F 数组 + master 加密网格

用于 optimizer 和 runs 共享。SIMPLE 内核的 K/c_F 数组是 1D (Ny_sim,) 行向，
这里把 2D grid_cells 或 sigmoid 连续场投影到 SIMPLE 的流向轴。

核心原则（2026-04-17）：生产 dP 路径严格走 SIMPLE，不允许任何解析公式
（1D D-F、f-Re、compute_dP_continuous 等）绕过 SIMPLE。

对应报告：vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11-§12
"""
from __future__ import annotations
from typing import Any, List, Optional

import numpy as np
from sjtu_tpmshx.models.grid import build_wall_refined_1d  # noqa: F401 - existing public name


from sjtu_tpmshx.models.grid import build_master_refined_grid  # noqa: F401


from sjtu_tpmshx.models.df_projection import (
    project_cells_to_streamwise_K_cF as project_cells_to_streamwise_K_cF,
    project_fields_to_streamwise_K_cF as project_fields_to_streamwise_K_cF,
    project_fields_to_streamwise_K_cF_3d as project_fields_to_streamwise_K_cF_3d,
    _cell_centre_fracs as _cell_centre_fracs,
    _nearest_src_idx as _nearest_src_idx,
    _stream_profile as _stream_profile,
)


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
