"""Check frozen MMS references from the retired Python research drivers.

The recorded CSV values and their original gates remain unchanged.
Version 0.1 retains the producers in Git history. Current C++ MMS
coverage is in tests/native/test_temperature_mms.py.
These historical tests do not execute a current numerical solver.
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
