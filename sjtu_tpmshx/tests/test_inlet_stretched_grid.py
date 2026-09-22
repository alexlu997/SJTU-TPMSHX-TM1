"""Unit tests for ``build_inlet_stretched_1d`` — the opt-in one-sided
streamwise inlet-graded mesh generator (paths-1/2 foundation, 2026-06-25).

The function is NOT wired into the default solver path; these tests pin its
contract so it can be used to resolve a steep inlet thermal-entry without a
globally fine grid (the per-cell ``dx_arr`` kernels already consume it).
"""
from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.tests.inlet_stretched_reference import build_inlet_stretched_1d


def test_sum_exact_and_shape():
    L, N, fc = 0.182, 40, 0.182 / 40 / 4.0   # first cell = 1/4 of uniform
    dx = build_inlet_stretched_1d(L, N, fc, end='lo')
    assert dx.shape == (N,)
    assert dx.dtype == np.float64
    assert dx.sum() == pytest.approx(L, rel=1e-12)


def test_lo_fine_at_inlet_monotone_coarsening():
    dx = build_inlet_stretched_1d(0.182, 40, 0.182 / 40 / 4.0, end='lo')
    assert dx[0] < dx[-1]                      # fine at x=0
    assert np.all(np.diff(dx) > 0)             # smooth monotone coarsening
    # first cell substantially finer than uniform
    assert dx[0] < 0.5 * (0.182 / 40)


def test_hi_is_mirror_of_lo():
    L, N, fc = 0.1, 30, 0.1 / 30 / 3.0
    lo = build_inlet_stretched_1d(L, N, fc, end='lo')
    hi = build_inlet_stretched_1d(L, N, fc, end='hi')
    assert np.allclose(hi, lo[::-1])
    assert hi[-1] < hi[0]                      # fine at x=L
    assert hi.sum() == pytest.approx(L, rel=1e-12)


def test_degenerate_first_cell_falls_back_uniform():
    # first_cell >= L/N (here == L) cannot refine → uniform grid.
    dx = build_inlet_stretched_1d(0.1, 10, 0.1, end='lo')
    assert np.allclose(dx, 0.1 / 10)


@pytest.mark.parametrize('N', [2, 5, 12, 40, 100])
def test_sum_exact_across_sizes(N):
    L, fc = 0.05, 0.05 / N / 3.0
    dx = build_inlet_stretched_1d(L, N, fc, end='lo')
    assert dx.sum() == pytest.approx(L, rel=1e-12)
    assert np.all(dx > 0)
