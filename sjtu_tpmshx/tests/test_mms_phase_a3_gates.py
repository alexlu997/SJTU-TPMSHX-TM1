"""Pytest gate-check for MMS Phase A.3 — 5-grid h-refinement order.

Checks the recorded V&V Standard Tier Phase A.3 evidence against its
original thresholds. It does not recompute the current discretisation;
the CLI applies these gates to each new sweep separately.

The expensive 5-grid sweep itself (~5 hr wall on a laptop) is **not**
re-run here. This test reads the persisted CSV produced by
``validation/cases/mms_phase_a3_h_refine.py`` and asserts the same hard gates
that the script's own console output checks.

Hard gates (per plan #4 §3.5 V&V scope):
    p_obs (L2_A) >= 1.5
    p_obs (L2_B) >= 1.5
    p_obs (L2_s) >= 1.8       # pure diffusion expects 2nd-order
    L2 (grid 30) < 1.0%       # absolute error floor
    R^2 >= 0.999               # log-log fit must be clean

To obtain a separate new run for comparison:
    python -m sjtu_tpmshx.validation.cases.mms_phase_a3_h_refine
Outputs go to .cache/validation/mms_phase_a3-*/. This test continues to read
the recorded reference; do not replace it or loosen gates to conceal failures.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

ORDERS_CSV = ROOT / 'validation' / 'mms_phase_a3_orders.csv'

# Plan-locked thresholds. Higher == stricter. Tighten only after
# regenerating the CSV (don't chase noise downward).
GATE_P_A = 1.5
GATE_P_B = 1.5
GATE_P_S = 1.8       # pure diffusion phase
GATE_L2_G30 = 0.010  # 1% on grid-30 L2
GATE_R2 = 0.999


@pytest.fixture(scope='module')
def orders():
    if not ORDERS_CSV.exists():
        pytest.skip(f"Recorded reference missing: {ORDERS_CSV}; restore it from repository history")
    # comment='#' skips the C.4 provenance header (script/commit/date)
    return pd.read_csv(ORDERS_CSV, comment='#')


# ---------------------------------------------------------------- coverage


def test_csv_covers_all_three_cases(orders):
    """1d / 2d / 3d × {L2_A, L2_B, L2_s, Linf_*} = 18 rows."""
    cases = set(orders['case'].unique())
    assert cases == {'1d', '2d', '3d'}


# ---------------------------------------------------------------- order gates


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
def test_p_obs_L2_A_meets_gate(orders, case):
    row = orders[(orders['case'] == case) & (orders['metric'] == 'L2_A')]
    assert len(row) == 1
    p = float(row['p_obs'].iloc[0])
    assert p >= GATE_P_A, f"{case} L2_A p_obs={p:.3f} < {GATE_P_A}"


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
def test_p_obs_L2_B_meets_gate(orders, case):
    row = orders[(orders['case'] == case) & (orders['metric'] == 'L2_B')]
    assert len(row) == 1
    p = float(row['p_obs'].iloc[0])
    assert p >= GATE_P_B, f"{case} L2_B p_obs={p:.3f} < {GATE_P_B}"


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
def test_p_obs_L2_s_meets_gate(orders, case):
    row = orders[(orders['case'] == case) & (orders['metric'] == 'L2_s')]
    assert len(row) == 1
    p = float(row['p_obs'].iloc[0])
    assert p >= GATE_P_S, f"{case} L2_s p_obs={p:.3f} < {GATE_P_S}"


# ---------------------------------------------------------------- absolute err


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
@pytest.mark.parametrize('metric', ['L2_A', 'L2_B', 'L2_s'])
def test_grid30_L2_below_one_percent(orders, case, metric):
    row = orders[(orders['case'] == case) & (orders['metric'] == metric)]
    assert len(row) == 1
    v = float(row['val_g30'].iloc[0])
    assert v < GATE_L2_G30, (
        f"{case} {metric} L2(grid 30) = {v:.3e} >= {GATE_L2_G30}")


# ---------------------------------------------------------------- fit quality


@pytest.mark.parametrize('case', ['1d', '2d', '3d'])
@pytest.mark.parametrize('metric', ['L2_A', 'L2_B', 'L2_s'])
def test_log_log_fit_R2(orders, case, metric):
    row = orders[(orders['case'] == case) & (orders['metric'] == metric)]
    assert len(row) == 1
    r2 = float(row['R2'].iloc[0])
    assert r2 >= GATE_R2, f"{case} {metric} R^2={r2:.5f} < {GATE_R2}"
