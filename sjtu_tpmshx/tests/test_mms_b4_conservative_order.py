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

ORDERS_CSV = ROOT / 'validation' / 'mms_phase_b4_orders.csv'

GATE_P = 1.8
GATE_R2 = 0.99


@pytest.fixture(scope='module')
def orders():
    if not ORDERS_CSV.exists():
        pytest.skip(f"Recorded reference missing: {ORDERS_CSV}; restore it from repository history")
    return pd.read_csv(ORDERS_CSV, comment='#')


def test_csv_covers_three_metrics(orders):
    assert set(orders['metric'].unique()) == {'L2_A', 'L2_B', 'L2_s'}


@pytest.mark.parametrize('metric', ['L2_A', 'L2_B', 'L2_s'])
def test_conservative_path_second_order(orders, metric):
    row = orders[orders['metric'] == metric]
    assert len(row) == 1
    p = float(row['p_obs'].iloc[0])
    assert p >= GATE_P, f"conservative HO {metric} p_obs={p:.3f} < {GATE_P}"


@pytest.mark.parametrize('metric', ['L2_A', 'L2_B', 'L2_s'])
def test_fit_quality(orders, metric):
    row = orders[orders['metric'] == metric]
    r2 = float(row['R2'].iloc[0])
    assert r2 >= GATE_R2, f"conservative HO {metric} R^2={r2:.4f} < {GATE_R2}"
