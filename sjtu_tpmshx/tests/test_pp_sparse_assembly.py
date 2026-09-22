"""Regression test for the fast pressure-Poisson sparse assembler.

Verifies that the new _solve_pp_sparse_fast produces numerically equivalent
sparse matrices and solutions to the reference _solve_pp_sparse, across three
representative grids drawn from the Shanghai Electric validation cases.

Run from the repository root through pytest with the configured interpreter.
"""

import numpy as np
import pytest
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve


def test_singular_pp_records_nonfinite_fact_without_changing_solution():
    from scipy.sparse.linalg import MatrixRankWarning
    from sjtu_tpmshx.domain.run_warnings import warning_scope
    from sjtu_tpmshx.solvers.simple_solver import (
        _solve_pp_sparse_fast, _build_pp_sparsity_pattern,
    )

    # Two connected cells with no pressure reference: [[1, -1], [-1, 1]].
    u, v, d_u, d_v, rho, outlet, dx, dy = _make_test_grid(1, 2, seed=7)
    for array in (d_u, d_v, rho, dx, dy):
        array.fill(1)
    outlet.fill(0)
    sparsity = _build_pp_sparsity_pattern(1, 2, outlet)
    correction = np.zeros((1, 2))
    with warning_scope({}) as records, pytest.warns(MatrixRankWarning):
        _solve_pp_sparse_fast(correction, u, v, d_u, d_v, outlet,
                              1, 2, dx, dy, rho, sparsity)
    assert np.isnan(correction).all()
    assert list(records.values()) == [
        'pressure-Poisson solve returned non-finite corrections']

# The retired production assembler remains an independent test reference.
def _solve_pp_sparse_reference(Pp, u, v, d_u, d_v, outlet_frac,
                                Nx, Ny, dx_arr, dy_arr, rho_field):
    """Exact copy of the pre-Task-3 _solve_pp_sparse, kept for regression."""
    N = Nx * Ny
    rows, cols, vals = [], [], []
    rhs = np.zeros(N)
    def idx(i, j): return i * Ny + j
    for i in range(Nx):
        for j in range(Ny):
            k = idx(i, j)
            if j == Ny - 1 and outlet_frac[i] > 0.01:
                rows.append(k); cols.append(k); vals.append(1.0)
                rhs[k] = 0.0
                continue
            dxi = dx_arr[i]; dyj = dy_arr[j]
            rho_e = 0.5 * (rho_field[i, j] + rho_field[i+1, j]) if i < Nx-1 else rho_field[i, j]
            rho_w = 0.5 * (rho_field[i-1, j] + rho_field[i, j]) if i > 0 else rho_field[i, j]
            rho_n = 0.5 * (rho_field[i, j] + rho_field[i, j+1]) if j < Ny-1 else rho_field[i, j]
            rho_s = 0.5 * (rho_field[i, j-1] + rho_field[i, j]) if j > 0 else rho_field[i, j]
            aE = rho_e * d_u[i + 1, j] * dyj if i < Nx - 1 else 0.0
            aW = rho_w * d_u[i, j] * dyj     if i > 0      else 0.0
            aN = rho_n * d_v[i, j + 1] * dxi if j < Ny - 1 else 0.0
            aS = rho_s * d_v[i, j] * dxi     if j > 0      else 0.0
            aP = aE + aW + aN + aS
            if aP < 1e-30:
                rows.append(k); cols.append(k); vals.append(1.0)
                rhs[k] = 0.0
                continue
            rows.append(k); cols.append(k); vals.append(aP)
            if aE > 0:
                rows.append(k); cols.append(idx(i+1, j)); vals.append(-aE)
            if aW > 0:
                rows.append(k); cols.append(idx(i-1, j)); vals.append(-aW)
            if aN > 0:
                rows.append(k); cols.append(idx(i, j+1)); vals.append(-aN)
            if aS > 0:
                rows.append(k); cols.append(idx(i, j-1)); vals.append(-aS)
            rhs[k] = -((rho_e * u[i+1,j] - rho_w * u[i,j]) * dyj
                     + (rho_n * v[i,j+1] - rho_s * v[i,j]) * dxi)
    A = csr_matrix((vals, (rows, cols)), shape=(N, N))
    pp_flat = spsolve(A, rhs)
    Pp[:, :] = pp_flat.reshape(Nx, Ny)
    return A, rhs


def _make_test_grid(Nx, Ny, seed):
    """Construct a self-consistent test case: random (bounded) velocity,
    density, and d_u/d_v fields; realistic outlet_frac."""
    rng = np.random.default_rng(seed)
    u = rng.uniform(-2.0, 5.0, size=(Nx+1, Ny))
    v = rng.uniform(-1.0, 1.0, size=(Nx, Ny+1))
    d_u = rng.uniform(0.01, 0.1, size=(Nx+1, Ny))
    d_v = rng.uniform(0.01, 0.1, size=(Nx, Ny+1))
    rho_field = rng.uniform(0.8, 1.2, size=(Nx, Ny))
    outlet_frac = np.zeros(Nx)
    outlet_frac[Nx//4 : 3*Nx//4] = 1.0  # partial outlet in middle
    dx_arr = np.full(Nx, 1.5e-3)
    dy_arr = np.full(Ny, 1.4e-3)
    return u, v, d_u, d_v, rho_field, outlet_frac, dx_arr, dy_arr


def _run_both(Nx, Ny, seed):
    """Run reference and fast implementations on the same inputs; return both."""
    u, v, d_u, d_v, rho_field, outlet_frac, dx_arr, dy_arr = _make_test_grid(Nx, Ny, seed)
    Pp_ref = np.zeros((Nx, Ny))
    A_ref, rhs_ref = _solve_pp_sparse_reference(
        Pp_ref, u, v, d_u, d_v, outlet_frac, Nx, Ny, dx_arr, dy_arr, rho_field)

    from sjtu_tpmshx.solvers.simple_solver import _solve_pp_sparse_fast, _build_pp_sparsity_pattern
    sparsity = _build_pp_sparsity_pattern(Nx, Ny, outlet_frac)
    Pp_fast = np.zeros((Nx, Ny))
    A_fast, rhs_fast = _solve_pp_sparse_fast(
        Pp_fast, u, v, d_u, d_v, outlet_frac,
        Nx, Ny, dx_arr, dy_arr, rho_field, sparsity)
    return (Pp_ref, A_ref, rhs_ref), (Pp_fast, A_fast, rhs_fast)


def test_169x31_shanghai_grid():
    """The exact grid used by the Shanghai 2D validation
    (validate_shanghai_aligned.py; historically validate_shanghai.py)."""
    (Pp_r, A_r, rhs_r), (Pp_f, A_f, rhs_f) = _run_both(169, 31, seed=42)
    # rhs must match exactly (same input, same math)
    assert np.allclose(rhs_r, rhs_f, rtol=1e-14, atol=1e-20), \
        f"RHS mismatch: max |d| = {np.max(np.abs(rhs_r - rhs_f)):.3e}"
    max_A_diff = np.max(np.abs((A_r - A_f).data), initial=0.0)
    assert max_A_diff < 1e-12, f"A matrix mismatch: max |d| = {max_A_diff:.3e}"
    # Solution Pp
    max_Pp_diff = np.max(np.abs(Pp_r - Pp_f))
    assert max_Pp_diff < 1e-10, f"Pp solution mismatch: max |d| = {max_Pp_diff:.3e}"
    print("test_169x31_shanghai_grid PASS")


def test_40x20_small_grid():
    """Small grid for faster test loop + edge-case coverage."""
    (Pp_r, _, _), (Pp_f, _, _) = _run_both(40, 20, seed=7)
    max_Pp_diff = np.max(np.abs(Pp_r - Pp_f))
    assert max_Pp_diff < 1e-10, f"40x20 mismatch: max |d| = {max_Pp_diff:.3e}"
    print("test_40x20_small_grid PASS")


def test_100x10_elongated_grid():
    """Elongated grid: stresses the aspect-ratio of dx/dy in coefficient computation."""
    (Pp_r, _, _), (Pp_f, _, _) = _run_both(100, 10, seed=99)
    max_Pp_diff = np.max(np.abs(Pp_r - Pp_f))
    assert max_Pp_diff < 1e-10, f"100x10 mismatch: max |d| = {max_Pp_diff:.3e}"
    print("test_100x10_elongated_grid PASS")


if __name__ == '__main__':
    test_169x31_shanghai_grid()
    test_40x20_small_grid()
    test_100x10_elongated_grid()
    print("\nAll pp_sparse_assembly tests PASS")
