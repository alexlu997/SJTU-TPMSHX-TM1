"""One-sided geometric-grid reference used only by grid research tests."""
import numpy as np


def build_inlet_stretched_1d(L, N, first_cell, end='lo'):
    """One-sided geometric STREAMWISE grid: fine at the inlet end, coarsening
    smoothly downstream (no cell-size jump). ``cell[0]=first_cell``,
    ``cell[k]=first_cell·r**k``; the growth ratio ``r>1`` is solved so the N
    cells sum exactly to ``L``.

    Purpose: resolve a steep inlet thermal-entry without a globally fine grid.
    This is the OPT-IN streamwise counterpart of :func:`build_wall_refined_1d`
    (which refines the two CROSS-STREAM walls). It is NOT wired into the default
    solver path — ``_aligned_grid`` (uniform) remains the default. The per-cell
    ``dx_arr`` kernels (``ltne_energy._gs_full_chunk``, ``simple_solver``'s
    momentum sweep) already consume a non-uniform 1-D array, so a graded
    ``dx_arr`` from here plugs in with no kernel change.

    Parameters
    ----------
    L : float — domain length along this (streamwise) axis [m]
    N : int — number of cells
    first_cell : float — width of the cell at the inlet end [m]. Must be < L/N
        to actually refine; otherwise the function returns a uniform grid.
    end : {'lo', 'hi'} — 'lo' puts the fine cells at x=0 (dir 0/2 inlet),
        'hi' mirrors them to x=L (dir 1/3 inlet).

    Returns
    -------
    dx_arr : (N,) float64 array, ``sum == L`` (renormalised to machine
        precision), geometrically graded from ``first_cell``.

    Notes
    -----
    The growth ratio is whatever the (L, N, first_cell) triple implies; a very
    small ``first_cell`` forces a steep ratio. For low truncation error on the
    second-order-upwind convection term, keep the implied ratio modest
    (≈≤1.2–1.3 per cell) — i.e. choose ``first_cell`` not far below ``L/N``.
    """
    N = int(N)
    if N < 2 or first_cell <= 0 or first_cell * N >= L:
        # Cannot refine (first cell already ≥ the uniform width) → uniform.
        return np.full(N, L / float(N), dtype=np.float64)
    # Solve first_cell·(r**N − 1)/(r − 1) = L for r>1 by bisection. The
    # geometric-sum S(r)=(r**N−1)/(r−1) is monotonic increasing in r with
    # S(1+)=N < L/first_cell (guaranteed by the guard above), so a root r>1
    # exists; cap the bracket at a steep r=8 (renormalisation absorbs any
    # residual so the sum is always exact even if the root is clamped).
    target = L / first_cell
    lo, hi = 1.0 + 1e-12, 8.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        s = (mid ** N - 1.0) / (mid - 1.0)
        if s < target:
            lo = mid
        else:
            hi = mid
    r = 0.5 * (lo + hi)
    dx = first_cell * r ** np.arange(N, dtype=np.float64)
    dx *= L / dx.sum()                      # renormalise → exact sum == L
    return dx[::-1].copy() if end == 'hi' else dx

