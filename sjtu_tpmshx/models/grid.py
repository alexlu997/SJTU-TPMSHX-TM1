"""Physical grid construction, independent of numerical kernels."""
import numpy as np


def _aligned_grid(N, L, breakpoints):
    """Generate 1D grid with cell edges aligned to breakpoint positions.

    Breakpoints are positions where inlet/outlet meets wall. Cell edges
    are guaranteed to fall exactly on these positions, eliminating the
    velocity discontinuity within any single cell.

    Parameters
    ----------
    N : int — total number of cells
    L : float — domain length [m]
    breakpoints : iterable of float — positions [m] to align cell edges to

    Returns
    -------
    dx_arr : (N,) array — cell widths [m]
    """
    # Build sorted unique segment boundaries [0, bp1, bp2, ..., L]
    eps_b = L * 0.001
    bps = sorted(set([0.0] + [bp for bp in breakpoints
                               if eps_b < bp < L - eps_b] + [L]))

    if len(bps) <= 2:
        return np.full(N, L / N, dtype=np.float64)

    # Segments and their lengths
    segments = [(bps[i], bps[i + 1]) for i in range(len(bps) - 1)]
    if N < 2 * len(segments):
        raise ValueError(f"Increase N to at least {2 * len(segments)} to align all segments")
    lengths = [s[1] - s[0] for s in segments]
    total = sum(lengths)

    # Distribute cells proportional to segment length (min 2 per segment)
    n_cells = [max(2, round(N * l / total)) for l in lengths]
    # Adjust last segment to match total N
    diff = N - sum(n_cells)
    n_cells[-1] += diff
    # Borrow from as many segments as needed without breaking their minimum.
    if n_cells[-1] < 2:
        deficit = 2 - n_cells[-1]
        n_cells[-1] = 2
        while deficit:
            big = max(range(len(n_cells) - 1), key=lambda k: n_cells[k])
            borrowed = min(deficit, n_cells[big] - 2)
            n_cells[big] -= borrowed
            deficit -= borrowed

    # Anchor each segment end despite cumulative roundoff in uniform widths.
    dx_list = []
    position = 0.0
    for (lo, hi), nc in zip(segments, n_cells):
        seg_dx = (hi - lo) / nc
        for _ in range(nc - 1):
            dx_list.append(seg_dx)
            position += seg_dx
        dx_list.append(hi - position)
        position += dx_list[-1]

    return np.array(dx_list, dtype=np.float64)


def build_wall_refined_1d(W, N_bulk, n_refine=8, first_cell=0.02e-3, growth=1.8):
    """Build a 1D cross-stream grid with geometric refinement at both walls.

    Layout: [refine_fine → refine_coarse | uniform bulk | refine_coarse → refine_fine]
    Total cells = 2*n_refine + N_bulk.

    Parameters
    ----------
    W : float — domain width (cross-stream extent) [m]
    N_bulk : int — number of uniform bulk cells in the interior
    n_refine : int — refinement layers per wall (default 8)
    first_cell : float — thickness of cell touching the wall [m] (default 0.02 mm)
    growth : float — geometric growth ratio (default 1.8)

    Returns
    -------
    dx_arr : np.ndarray shape (2*n_refine + N_bulk,), sum == W

    Used to resolve Brinkman boundary layer at outer housing walls. See
    vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §12.
    """
    refine_sizes = np.array([first_cell * growth**k for k in range(n_refine)], dtype=np.float64)
    total_refine = 2.0 * refine_sizes.sum()
    bulk_width = W - total_refine
    if bulk_width <= 0:
        raise ValueError(
            f"build_wall_refined_1d: refinement {total_refine*1000:.3f}mm exceeds "
            f"domain width {W*1000:.3f}mm. Reduce n_refine or first_cell.")
    bulk_cell = bulk_width / N_bulk
    bulk = np.full(N_bulk, bulk_cell, dtype=np.float64)
    return np.concatenate([refine_sizes, bulk, refine_sizes[::-1]])


def build_master_refined_grid(L_dom: float, H_dom: float,
                               Nx_user: int, Ny_user: int,
                               n_refine: int = 8,
                               first_cell: float = 0.02e-3,
                               growth: float = 1.8
                               ) -> tuple[np.ndarray, np.ndarray, int, int]:
    """构造"主加密网格"：真实坐标 x/y 两端都加密，四面墙 BL 都解析。

    返回 (dx_arr, dy_arr, Nx_refined, Ny_refined)
      dx_arr (m): 沿实际 x 方向，共 Nx_user + 2*n_refine 个单元，∑=L_dom
      dy_arr (m): 沿实际 y 方向，共 Ny_user + 2*n_refine 个单元，∑=H_dom

    映射到 SIMPLE 坐标：
      Fluid A (+x 流向): SIMPLE internal dx_arr = dy_refined, dy_arr = dx_refined
      Fluid B (-y 流向): SIMPLE internal dx_arr = dx_refined, dy_arr = dy_refined

    za 数组和 solve_full_domain 都直接用 (Nx_refined, Ny_refined) 这个网格。
    """
    dx_refined = build_wall_refined_1d(L_dom, Nx_user, n_refine=n_refine,
                                        first_cell=first_cell, growth=growth)
    dy_refined = build_wall_refined_1d(H_dom, Ny_user, n_refine=n_refine,
                                        first_cell=first_cell, growth=growth)
    return dx_refined, dy_refined, len(dx_refined), len(dy_refined)



def _port_overlap_1d(widths, lo, hi, *, staggered=False):
    """Exact interval overlap on primary CVs or CVs between adjacent centres."""
    x_lo_edge = np.concatenate(([0.0], np.cumsum(widths[:-1])))
    x_hi_edge = np.cumsum(widths)
    if staggered:
        centres = x_hi_edge - np.asarray(widths) / 2
        x_lo_edge = np.r_[0., centres]
        x_hi_edge = np.r_[centres, x_hi_edge[-1]]
        widths = x_hi_edge - x_lo_edge
    return np.clip((np.minimum(x_hi_edge, hi) - np.maximum(x_lo_edge, lo)) / widths,
                   0.0, 1.0)


def _port_fractions_1d(widths, lo, hi):
    """Return physical overlap and the existing four-cell tapered profile."""
    raw = _port_overlap_1d(widths, lo, hi)
    profile = raw.copy()
    for i in range(len(widths)):
        if raw[i] > 0.99:
            for d in range(1, 5):
                if (i - d >= 0 and raw[i - d] < 0.01) or \
                   (i + d < len(widths) and raw[i + d] < 0.01):
                    profile[i] = 1.0 - 0.8 * np.exp(-1.0 * d)
                    break
    return raw, profile
