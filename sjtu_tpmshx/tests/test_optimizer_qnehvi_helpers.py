"""Pure-numeric tests for optimizer_qnehvi public helpers (no torch needed).

Covers:
  * _pareto_mask_max — Pareto front extraction under maximization
  * hv_plateau_detected — early-stop trigger logic
  * _save_pareto_csv — round-trip via numpy load

These are the parts of the BO loop that don't require BoTorch/Sobol bootstrapping
and so can be CI-stable on any machine.
"""
from __future__ import annotations


import numpy as np
import pytest

from sjtu_tpmshx.optimization.optimizer_qnehvi import (
    _pareto_mask_max,
    hv_plateau_detected,
    _save_pareto_csv,
)


@pytest.mark.parametrize('n_jobs', [1, 2])
def test_cancellation_keeps_active_wave_but_launches_no_more(n_jobs, tmp_path):
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _evaluation_results
    def evaluate(x, cfg):
        (tmp_path / f'{int(x[0])}.txt').write_text('evaluated')
        return -float(x[0] + 1), 10., 1.
    cancelled = False
    rows = _evaluation_results(np.arange(6).reshape(-1, 1), {}, 100., evaluate,
                               n_jobs, lambda: cancelled)
    first = next(rows)
    cancelled = True
    completed = [first, *rows]
    assert len(completed) == n_jobs
    assert len(list(tmp_path.glob('*.txt'))) == n_jobs
    assert all(row[2] is None for row in completed)


# ─── _pareto_mask_max — Pareto under MAX ───────────────────────────


def test_pareto_max_single_point():
    Y = np.array([[1.0, 2.0]])
    mask = _pareto_mask_max(Y)
    assert mask.tolist() == [True]


def test_pareto_max_clearly_dominated_filtered():
    """Row 1 dominates row 0 on both axes → row 0 should be removed."""
    Y = np.array([[1.0, 1.0],
                  [2.0, 2.0]])
    mask = _pareto_mask_max(Y)
    assert mask.tolist() == [False, True]


def test_pareto_max_anti_correlated_kept_both():
    """Two anti-correlated rows (high-Q low-other vs low-Q high-other) both
    stay on the front."""
    Y = np.array([[10.0, 1.0],
                  [1.0, 10.0]])
    mask = _pareto_mask_max(Y)
    assert mask.tolist() == [True, True]


def test_pareto_max_three_points_one_dominated():
    """Tie-break case: middle point dominated by extremes."""
    Y = np.array([[10.0, 1.0],
                  [1.0, 10.0],
                  [0.5, 0.5]])
    mask = _pareto_mask_max(Y)
    assert mask.tolist() == [True, True, False]


def test_pareto_max_duplicate_rows_at_least_one_kept():
    """Duplicate non-dominated rows: at least one survives."""
    Y = np.array([[5.0, 5.0],
                  [5.0, 5.0]])
    mask = _pareto_mask_max(Y)
    # Implementation may keep first or both — key invariant: ≥1 kept.
    assert mask.sum() >= 1


# ─── hv_plateau_detected ───────────────────────────────────────────


def test_hv_plateau_short_history_returns_false():
    """Need at least window+1 entries; less → not plateaued."""
    assert hv_plateau_detected([1.0, 1.001], hv_tol=0.01, hv_window=3) is False


def test_hv_plateau_clear_plateau_returns_true():
    """Three consecutive sub-tolerance deltas → plateau."""
    hist = [1.0, 1.001, 1.002, 1.003]   # rel deltas all ~0.001 < 0.01
    assert hv_plateau_detected(hist, hv_tol=0.01, hv_window=3) is True


def test_hv_plateau_one_big_delta_breaks_plateau():
    """A single delta above tol → not plateaued."""
    hist = [1.0, 1.001, 1.05, 1.051]    # middle delta ~5% >> 1%
    assert hv_plateau_detected(hist, hv_tol=0.01, hv_window=3) is False


def test_hv_plateau_zero_tol_only_plateaus_on_no_change():
    """tol=0 means ANY positive delta breaks plateau."""
    hist = [1.0, 1.0, 1.0, 1.0001]
    assert hv_plateau_detected(hist, hv_tol=0.0, hv_window=3) is False


# ─── _save_pareto_csv ──────────────────────────────────────────────


def test_save_pareto_csv_roundtrip(tmp_path):
    """Saved CSV reads back with negated Q + correct dP."""
    X = np.array([[0.5, 0.6], [0.3, 0.7]])
    # F_min internal form: (-Q, dP). Q=8000 → -8000; Q=9000 → -9000.
    F_min = np.array([[-8000.0, 12000.0],
                      [-9000.0, 15000.0]])
    csv_path = tmp_path / "pareto_test.csv"
    _save_pareto_csv(str(csv_path), X, F_min)
    data = np.loadtxt(csv_path, delimiter=',', skiprows=1)
    # Layout: [x0, x1, Q, dP]
    assert data.shape == (2, 4)
    assert data[0, 2] == pytest.approx(8000.0, rel=1e-4)
    assert data[0, 3] == pytest.approx(12000.0, rel=1e-4)
    assert data[1, 2] == pytest.approx(9000.0, rel=1e-4)
    assert data[1, 3] == pytest.approx(15000.0, rel=1e-4)


def test_save_pareto_csv_header_has_x_and_objective_columns(tmp_path):
    """Header line should reflect decision dims + objective names."""
    X = np.zeros((3, 5))
    F_min = np.zeros((3, 2))
    csv_path = tmp_path / "pareto_header.csv"
    _save_pareto_csv(str(csv_path), X, F_min)
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().strip()
    parts = header.split(',')
    assert parts[:5] == ['x0', 'x1', 'x2', 'x3', 'x4']
    assert 'Q_W_per_m' in parts
    assert 'dP_Pa' in parts


# ── P3.3: _resolve_core_budget (env parse/clamp/visibility) ──────────────────

def test_core_budget_default_unset(monkeypatch):
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _resolve_core_budget
    import os
    monkeypatch.delenv('TPMSHX_BO_CORE_BUDGET', raising=False)
    cores, src = _resolve_core_budget()
    assert cores == (os.cpu_count() or 4)
    assert src == 'default'


@pytest.mark.parametrize('raw,expect', [
    ('2', (2, 'env')),                     # honored (any box has >= 2 logical)
    ('0', (1, 'env-clamped')),             # floor
    ('-8', (1, 'env-clamped')),            # floor
    ('99999999', (None, 'env-clamped')),   # ceil to whole machine
    ('garbage', (None, 'invalid-env-default')),  # pre-P3.3 fallback kept
    ('', (None, 'default')),
])
def test_core_budget_parse_matrix(monkeypatch, raw, expect):
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _resolve_core_budget
    import os
    monkeypatch.setenv('TPMSHX_BO_CORE_BUDGET', raw)
    cores, src = _resolve_core_budget()
    want_cores, want_src = expect
    if want_cores is None:
        want_cores = os.cpu_count() or 4
    assert (cores, src) == (want_cores, want_src)
