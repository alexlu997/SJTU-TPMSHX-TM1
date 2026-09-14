"""Physical grid construction, independent of numerical kernels."""
import numpy as np

SHANGHAI_GRID_2D = (84, 24, 1)
SHANGHAI_GRID_3D = (92, 14, 10)


def cell_average(field, *widths):
    """Physical area/volume average, independent of how cells are subdivided."""
    value = np.asarray(field)
    if value.ndim == 0:
        return float(value)
    for axis_widths in widths:
        value = np.average(value, axis=0, weights=axis_widths)
    return float(value)


def split_cells(widths):
    """Bisect each cell while keeping its physical end point."""
    result = []
    position = 0.
    for width, end in zip(widths, np.cumsum(widths)):
        result.append(width / 2)
        position += result[-1]
        result.append(end - position)
        position += result[-1]
    return np.asarray(result)


def build_port_wall_grid(lengths, counts, ports):
    """Port-aligned, graded cells; counts include all wall and port layers.

    The Shanghai mesh study uses 0.2 mm first cells at port edges, and
    20 um (2D) / 56 um (3D) first cells at uninterrupted housing walls.
    Other geometries require their own mesh-convergence assessment.
    """
    breaks = [set() for _ in lengths]
    for port in ports:
        if port is None:  # Prepared 3D side B uses None for a full-face opening.
            continue
        cross_axes = [axis for axis in range(len(lengths)) if axis != port['dir'] // 2]
        for axis, suffix in zip(cross_axes, ('', '_z')):
            for end in ('in', 'out'):
                centre = port.get(f'{end}{suffix}_ctr', lengths[axis] / 2)
                width = port.get(f'{end}{suffix}_w', lengths[axis])
                for edge in (centre - width / 2, centre + width / 2):
                    if lengths[axis] * .001 < edge < lengths[axis] * .999:
                        breaks[axis].add(edge)
    result = []
    for length, count, knots in zip(lengths, counts, breaks):
        knots = sorted(knots)
        if knots:
            layers, first, growth = 4, .2e-3, 1.8
        elif len(lengths) == 2:
            layers, first, growth = 8, .02e-3, 1.8
        else:
            layers, first, growth = 4, .02e-3 * (1 + 1.8), 1.8**2
        segments = len(knots) + 1
        bulk_count = count - 2 * layers * segments
        if bulk_count < 2 * segments:
            raise ValueError(f'Port/wall grid needs at least {2 * (layers + 1) * segments} cells on this axis; got {count}')
        bulk = _aligned_grid(bulk_count, length, knots)
        edges = np.r_[0., np.cumsum(bulk)]
        bounds = [0., *knots, length]
        widths = []
        position = 0.
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            n = np.count_nonzero((edges[:-1] >= lo - 1e-12) & (edges[:-1] < hi - 1e-12))
            segment = build_wall_refined_1d(hi - lo, n, layers, first, growth)
            for width in segment[:-1]:
                widths.append(width)
                position += width
            widths.append(hi - position)
            position += widths[-1]
        result.append(np.asarray(widths))
    return tuple(result)


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
    overlap = np.minimum(x_hi_edge, hi) - np.maximum(x_lo_edge, lo)
    # A rounded shared edge must not turn a wall into a pressure outlet.
    # Use spatial ULPs, not a fraction threshold that erases real small ports.
    roundoff = 8 * np.spacing(max(abs(lo), abs(hi), abs(x_hi_edge[-1])))
    overlap = np.where(np.abs(overlap) <= roundoff, 0., overlap)
    return np.clip(overlap / widths, 0.0, 1.0)


def _port_fractions_1d(widths, lo, hi, *, uniform=False):
    """Return geometric overlap and the selected imposed port profile."""
    raw = _port_overlap_1d(widths, lo, hi)
    profile = raw.copy()
    if uniform:
        return raw, profile
    for i in range(len(widths)):
        if raw[i] > 0.99:
            for d in range(1, 5):
                if (i - d >= 0 and raw[i - d] < 0.01) or \
                   (i + d < len(widths) and raw[i + d] < 0.01):
                    profile[i] = 1.0 - 0.8 * np.exp(-1.0 * d)
                    break
    return raw, profile


def build_master_refined_grid_3d(L_dom: float, H_dom: float, D_dom: float,
                                   Nx_user: int, Ny_user: int, Nz_user: int,
                                   n_refine: int = 8,
                                   first_cell: float = 0.02e-3,
                                   growth: float = 1.8
                                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                              int, int, int]:
    """Six-wall tensor-product refined grid (3D).

    Returns (dx_arr, dy_arr, dz_arr, Nx_refined, Ny_refined, Nz_refined).
    Uses build_wall_refined_1d for each axis independently.
    """
    dx = build_wall_refined_1d(L_dom, Nx_user, n_refine=n_refine,
                                first_cell=first_cell, growth=growth)
    dy = build_wall_refined_1d(H_dom, Ny_user, n_refine=n_refine,
                                first_cell=first_cell, growth=growth)
    dz = build_wall_refined_1d(D_dom, Nz_user, n_refine=n_refine,
                                first_cell=first_cell, growth=growth)
    return dx, dy, dz, len(dx), len(dy), len(dz)
