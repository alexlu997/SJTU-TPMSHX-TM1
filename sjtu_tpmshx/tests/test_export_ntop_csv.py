"""
test_export_ntop_csv.py — Round-trip + format checks for the nTop CSV
exporter in optimization/export_ntop_csv.py.

Avoids hitting the live SIMPLE / energy stack — these tests work entirely
on synthetic decision vectors and parsed CSVs.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
from sjtu_tpmshx.optimization.export_ntop_csv import (
    DEFAULT_GRID_NX,
    DEFAULT_GRID_NY,
    export_decision_vector,
    export_pareto_row,
)
from sjtu_tpmshx.models.continuous_field import (
    DEFAULT_L_BOUNDS,
    DEFAULT_T_BOUNDS,
    encode_decision_vector,
    uniform_field,
)


def _uniform_decision_vector():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    return encode_decision_vector(fc.L_ctrl, fc.t_ctrl, symmetric_y=True)


# ─── export_decision_vector basics ──────────────────────────────────


def test_uniform_field_export_writes_three_files(tmp_path):
    x = _uniform_decision_vector()
    out = tmp_path / 'export'
    export_decision_vector(x, str(out))
    assert (out / 'Lfield.csv').exists()
    assert (out / 'tfield.csv').exists()
    assert (out / 'provenance.json').exists()
    # Default grid → header + Nx*Ny rows
    L_lines = (out / 'Lfield.csv').read_text().splitlines()
    assert len(L_lines) == 1 + DEFAULT_GRID_NX * DEFAULT_GRID_NY
    assert L_lines[0] == 'x_mm,y_mm,L_mm'


def test_uniform_field_csv_values_are_constant(tmp_path):
    """Uniform decision vector → both fields constant at the seed values."""
    x = _uniform_decision_vector()
    out = tmp_path / 'uniform'
    export_decision_vector(x, str(out), Nx_export=10, Ny_export=8)
    L = np.loadtxt(out / 'Lfield.csv', delimiter=',', skiprows=1)
    t = np.loadtxt(out / 'tfield.csv', delimiter=',', skiprows=1)
    assert L.shape == (80, 3)
    assert np.allclose(L[:, 2], 6.0, atol=1e-6)
    assert np.allclose(t[:, 2], 0.4, atol=1e-6)


def test_provenance_records_decision_and_summary(tmp_path):
    x = _uniform_decision_vector()
    out = tmp_path / 'prov'
    export_decision_vector(x, str(out), Nx_export=10, Ny_export=10)
    with open(out / 'provenance.json') as f:
        data = json.load(f)
    assert data['Nx_export'] == 10
    assert data['Ny_export'] == 10
    assert data['tpms_type'] == 'Diamond'
    assert abs(data['L_avg_mm'] - 6.0) < 1e-6
    assert abs(data['t_avg_mm'] - 0.4) < 1e-6
    assert len(data['decision_vector']) == x.size


def test_export_clamps_to_surrogate_window(tmp_path):
    """Out-of-bounds control points should be clamped to L_BOUNDS / T_BOUNDS
    by the spline-evaluation guard. Verify CSV values respect those bounds.
    """
    L_ctrl = np.array([[100.0]*4]*4, dtype=np.float64)   # absurdly high
    t_ctrl = np.full((4, 4), -10.0)                       # absurdly low
    x = encode_decision_vector(L_ctrl, t_ctrl, symmetric_y=True)
    out = tmp_path / 'clamp'
    export_decision_vector(x, str(out), Nx_export=20, Ny_export=10)
    L = np.loadtxt(out / 'Lfield.csv', delimiter=',', skiprows=1)
    t = np.loadtxt(out / 'tfield.csv', delimiter=',', skiprows=1)
    assert L[:, 2].max() <= DEFAULT_L_BOUNDS[1] + 1e-9
    assert L[:, 2].min() >= DEFAULT_L_BOUNDS[0] - 1e-9
    assert t[:, 2].max() <= DEFAULT_T_BOUNDS[1] + 1e-9
    assert t[:, 2].min() >= DEFAULT_T_BOUNDS[0] - 1e-9


# ─── export_pareto_row plumbing ─────────────────────────────────────


def test_pareto_row_loads_decision_vector(tmp_path):
    """Construct a tiny synthetic pareto_final.csv with one row, route through
    export_pareto_row, verify the same decisions came out.
    """
    x = _uniform_decision_vector()
    Q_dummy  = 8044.0
    dP_dummy = 11916.0

    csv_path = tmp_path / 'fake_pareto.csv'
    header = ','.join(f"x{i}" for i in range(x.size)) + ',Q_W_per_m,dP_Pa'
    row = list(map(str, x.tolist())) + [str(Q_dummy), str(dP_dummy)]
    csv_path.write_text(header + '\n' + ','.join(row) + '\n')

    out = tmp_path / 'export'
    summary = export_pareto_row(str(csv_path), 0, str(out),
                                 Nx_export=10, Ny_export=8,
                                 config=DEFAULT_CONFIG)
    assert summary['source']['pareto_Q_W_m'] == Q_dummy
    assert summary['source']['pareto_dP_Pa'] == dP_dummy
    assert summary['Nx_export'] == 10


def test_pareto_row_invalid_index_raises(tmp_path):
    x = _uniform_decision_vector()
    csv_path = tmp_path / 'fake.csv'
    header = ','.join(f"x{i}" for i in range(x.size)) + ',Q_W_per_m,dP_Pa'
    row = list(map(str, x.tolist())) + ['1', '1']
    csv_path.write_text(header + '\n' + ','.join(row) + '\n')
    with pytest.raises(IndexError):
        export_pareto_row(str(csv_path), 5, str(tmp_path / 'nope'))
