"""Pytest gate-check for MMS Phase A.4 — boundary stencil order.

Locks in V&V Standard Tier Phase A.4 results: per-region order analysis
(inlet Dirichlet / outlet Neumann / lateral wall / interior). The
expensive 3-grid {16, 20, 30} sweep is **not** re-run here; this test
reads the persisted CSVs and asserts the same hard gates as the
script's console output.

Hard gates (per script):
    inlet machine-eps:   L2 (g=30) < 1e-12   for own-phase Dirichlet BC
    outlet order:        p_obs >= 0.8        (one-sided 1st-order stencil)
    lateral L2_s order:  p_obs >= 1.5        (cosine BC, adiabatic-compat)
    interior all phases: p_obs >= 1.8 AND L2 < 1.0%

Generate a separate new comparison run via:
    python -m sjtu_tpmshx.validation.cases.mms_phase_a4_boundary
Outputs go to .cache/validation/mms_phase_a4-*/; the recorded CSVs and gates
remain unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

ORDERS_CSV = ROOT / 'validation' / 'mms_phase_a4_orders.csv'
H_REFINE_CSV = ROOT / 'validation' / 'mms_phase_a4_boundary.csv'

# Plan-locked thresholds.
GATE_INLET_EPS = 1e-12
GATE_OUTLET_P = 0.8
GATE_LAT_S_P = 1.5
GATE_INTERIOR_P = 1.8
GATE_INTERIOR_L2 = 0.010   # 1%


@pytest.fixture(scope='module')
def orders():
    if not ORDERS_CSV.exists():
        pytest.skip(f"Recorded reference missing: {ORDERS_CSV}; restore it from repository history")
    # comment='#' skips the C.4 provenance header (script/commit/date)
    return pd.read_csv(ORDERS_CSV, comment='#')


@pytest.fixture(scope='module')
def h_refine():
    if not H_REFINE_CSV.exists():
        pytest.skip(f"Recorded reference missing: {H_REFINE_CSV}; restore it from repository history")
    return pd.read_csv(H_REFINE_CSV, comment='#')


# ---------------------------------------------------------------- inlet


@pytest.mark.parametrize('phase', ['A', 'B'])
def test_inlet_own_phase_machine_eps(h_refine, phase):
    """At inlet of phase X, exact Dirichlet → L2_X must be machine zero."""
    last = h_refine.iloc[-1]
    col = f'L2_{phase}_inlet_{phase}'
    assert col in h_refine.columns, f"missing {col}"
    v = float(last[col])
    assert v < GATE_INLET_EPS, f"inlet_{phase} {col} = {v:.3e}"


# ---------------------------------------------------------------- outlet


@pytest.mark.parametrize('phase', ['A', 'B'])
def test_outlet_order_meets_gate(orders, phase):
    sub = orders[(orders['region'] == f'outlet_{phase}') &
                 (orders['phase'] == phase)]
    assert len(sub) == 1
    p = float(sub['p_obs'].iloc[0])
    assert p >= GATE_OUTLET_P, f"outlet_{phase} p_obs={p:.3f}"


# ---------------------------------------------------------------- lateral


def test_lateral_solid_order_meets_gate(orders):
    sub = orders[(orders['region'] == 'lat_z') &
                 (orders['phase'] == 's')]
    assert len(sub) == 1
    p = float(sub['p_obs'].iloc[0])
    assert p >= GATE_LAT_S_P, f"lat_z L2_s p_obs={p:.3f}"


# ---------------------------------------------------------------- interior


@pytest.mark.parametrize('phase', ['A', 'B', 's'])
def test_interior_order_meets_gate(orders, phase):
    sub = orders[(orders['region'] == 'interior') &
                 (orders['phase'] == phase)]
    assert len(sub) == 1
    p = float(sub['p_obs'].iloc[0])
    assert p >= GATE_INTERIOR_P, f"interior {phase} p_obs={p:.3f}"


@pytest.mark.parametrize('phase', ['A', 'B', 's'])
def test_interior_L2_below_one_percent(orders, phase):
    sub = orders[(orders['region'] == 'interior') &
                 (orders['phase'] == phase)]
    assert len(sub) == 1
    v = float(sub['L2_g_max'].iloc[0])
    assert v < GATE_INTERIOR_L2, f"interior {phase} L2_max={v:.3e}"
