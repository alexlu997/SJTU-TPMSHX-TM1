"""Pytest gate — MMS Phase B4: conservative HO kernel is 2nd-order.

Checks recorded evidence that the strict-conservation kernel branch
(cfg['conservative_ltne']=True, face-shared SOU + telescoping a_P) kept
2nd-order accuracy. Current-code order is checked by the new-run CLI gates,
not by rereading this historical table. Reads the persisted CSV from
``validation/cases/mms_phase_b4_order.py`` (the h-refinement sweep is not re-run in
CI; new comparisons use ``python -m sjtu_tpmshx.validation.cases.mms_phase_b4_order``
and write separately under .cache/validation/mms_phase_b4-*/).

Hard gates (B-plan B4 §3):
    p_obs (L2_A) >= 1.8
    p_obs (L2_B) >= 1.8
    p_obs (L2_s) >= 1.8
    R^2 >= 0.99      # clean log-log fit
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
