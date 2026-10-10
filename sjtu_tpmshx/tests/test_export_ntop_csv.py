"""
test_export_ntop_csv.py — Round-trip + format checks for the nTop CSV
exporter in optimization/export_ntop_csv.py.

Avoids hitting the live SIMPLE / energy stack — these tests work entirely
on synthetic decision vectors and parsed CSVs.
"""

from __future__ import annotations

import json
import csv
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.optimization import export_ntop_csv
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


ARCHIVED_GEOMETRY = dict(tpms_type='Diamond', k_s=17., L_domain=.1, H_domain=.05,
    n_ctrl_x=4, n_ctrl_y=4, symmetric_y=True, spline_order=3,
    L_bounds=DEFAULT_L_BOUNDS, t_bounds=DEFAULT_T_BOUNDS)


def _uniform_decision_vector():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    return encode_decision_vector(fc.L_ctrl, fc.t_ctrl, symmetric_y=True)


# ─── export_decision_vector basics ──────────────────────────────────


def test_xyz_export_keeps_depth_variation_and_full_precision(tmp_path):
    x, y, z = np.meshgrid(*([np.linspace(0., 1., 3)] * 3), indexing='ij')
    controls = np.r_[(6.5 + .2*x + .3*y + .7*z).ravel(),
                      (.4 + .03*x + .05*z).ravel()]
    info = export_decision_vector(controls, str(tmp_path), n_ctrl_x=3, n_ctrl_y=3,
        n_ctrl_z=3, symmetric_y=False, spline_order=2, L_domain_m=.182,
        H_domain_m=.042, Lz_domain_m=.042, Nx_export=5, Ny_export=4, Nz_export=6)
    assert info['dimension'] == 3 and info['decision_vector'] == controls.tolist()
    for name, formula in [('L', lambda a, b, c: 6.5+.2*a+.3*b+.7*c),
                          ('t', lambda a, b, c: .4+.03*a+.05*c)]:
        path = tmp_path / f'{name}field.csv'
        assert path.read_text().splitlines()[0] == f'x_mm,y_mm,z_mm,{name}_mm'
        rows = np.loadtxt(path, delimiter=',', skiprows=1)
        assert rows.shape == (5*4*6, 4)
        expected = formula(rows[:, 0]/182., rows[:, 1]/42., rows[:, 2]/42.)
        np.testing.assert_allclose(rows[:, 3], expected, rtol=2e-14, atol=2e-14)
        assert len(np.unique(rows[:, 2])) == 6


def test_boundary_geometry_and_exact_controls_share_physical_coordinates(tmp_path):
    # One x control fixes that direction; y/z retain independent gradients.
    y, z = np.meshgrid([0., 1.], [0., .5, 1.], indexing='ij')
    L = (5. + y + z)[None, :, :]
    t = (.35 + .1*z)[None, :, :]
    decisions = encode_decision_vector(L, t, False)
    result = export_decision_vector(decisions, tmp_path, n_ctrl_x=1, n_ctrl_y=2,
        n_ctrl_z=3, symmetric_y=False, spline_order=3, L_domain_m=.182,
        H_domain_m=.042, Lz_domain_m=.06, Nx_export=1, Ny_export=4, Nz_export=5,
        sampling='boundaries')
    data = np.loadtxt(result['csv_geometry'], delimiter=',', skiprows=1)
    assert data.shape == (20, 5)
    assert np.all(data[:, 0] == 91.)
    assert [data[:, 1].min(), data[:, 1].max()] == [0., 42.]
    assert [data[:, 2].min(), data[:, 2].max()] == [0., 60.]
    np.testing.assert_allclose(data[:, 3], 5.+data[:, 1]/42.+data[:, 2]/60., atol=1e-13)
    controls = np.loadtxt(result['csv_controls'], delimiter=',', skiprows=1)
    np.testing.assert_array_equal(controls[:, 3], L.ravel(order='F'))
    np.testing.assert_array_equal(controls[:, 4], t.ravel(order='F'))
    assert result['sampling'] == 'boundaries' and result['coordinate_units'] == 'mm'


@pytest.mark.parametrize('counts', [(0, 5), (True, 5), (999, 999, 999)])
def test_invalid_or_oversized_export_is_rejected_before_field_allocation(tmp_path, monkeypatch, counts):
    monkeypatch.setattr(export_ntop_csv, 'from_decision_vector',
                        lambda *a, **k: pytest.fail('invalid sampling allocated a field'))
    with pytest.raises(ValueError, match='counts|sampling points'):
        export_decision_vector([], tmp_path / 'unused', Nx_export=counts[0], Ny_export=counts[1],
            **(dict(Nz_export=counts[2], n_ctrl_z=3) if len(counts) == 3 else {}))
    assert not (tmp_path / 'unused').exists()


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
    summary = export_decision_vector(x, str(out), Nx_export=10, Ny_export=10)
    with open(out / 'provenance.json') as f:
        data = json.load(f)
    assert data['Nx_export'] == 10
    assert data['Ny_export'] == 10
    assert data['tpms_type'] == 'Diamond'
    assert abs(data['L_avg_mm'] - 6.0) < 1e-6
    assert abs(data['t_avg_mm'] - 0.4) < 1e-6
    assert data['decision_vector'] == x.tolist()
    assert data['csv_L'] == summary['csv_L'] == str(out / 'Lfield.csv')
    assert data['csv_t'] == summary['csv_t'] == str(out / 'tfield.csv')


@pytest.mark.parametrize('failed_file', ['tfield.csv', 'provenance.json'])
def test_failed_reexport_preserves_complete_previous_export(tmp_path, monkeypatch, failed_file):
    options = dict(n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                   Nx_export=3, Ny_export=2)
    original = np.r_[np.full(9, 6.), np.full(9, .4)]
    replacement = np.r_[np.full(9, 7.5), np.full(9, .55)]
    export_decision_vector(original, str(tmp_path), **options)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    message = f'injected partial write: {failed_file}'

    if failed_file == 'tfield.csv':
        write_csv = export_ntop_csv._write_scalar_field_csv

        def fail_second_csv(path, *args, **kwargs):
            if Path(path).name == failed_file:
                Path(path).write_text('x_mm,y_mm,t_mm\npartial')
                raise OSError(message)
            return write_csv(path, *args, **kwargs)

        monkeypatch.setattr(export_ntop_csv, '_write_scalar_field_csv', fail_second_csv)
    else:
        def fail_json(_summary, stream, **_kwargs):
            stream.write('{"partial":')
            raise OSError(message)

        monkeypatch.setattr(export_ntop_csv.json, 'dump', fail_json)

    with pytest.raises(OSError, match=message):
        export_decision_vector(replacement, str(tmp_path), **options)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


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
                                 config=ARCHIVED_GEOMETRY)
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


@pytest.mark.parametrize('dimension', [16, 36])
def test_historical_export_restores_named_decisions(tmp_path, monkeypatch, dimension):
    values = {f'x{i}': float(i + 1) for i in range(dimension)}
    values.update(Q_W_per_m=1234., dP_Pa=567.)
    path = tmp_path / 'pareto.csv'
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, list(reversed(values)))
        writer.writeheader()
        writer.writerow(values)
    captured = []
    monkeypatch.setattr(export_ntop_csv, 'export_decision_vector',
                        lambda x, *a, **kw: captured.append((x, kw['extra_metadata'])))
    cfg = {**ARCHIVED_GEOMETRY, 'n_ctrl_x': 6 if dimension == 36 else 4,
           'n_ctrl_y': 6 if dimension == 36 else 4}
    export_pareto_row(str(path), 0, str(tmp_path / 'out'), config=cfg)
    np.testing.assert_array_equal(captured[0][0], np.arange(1., dimension + 1.))
    assert captured[0][1]['pareto_Q_W_m'] == 1234.
    assert captured[0][1]['pareto_dP_Pa'] == 567.


@pytest.mark.parametrize('config', [{}, [], {k: v for k, v in ARCHIVED_GEOMETRY.items() if k != 'L_domain'}])
def test_export_rejects_incomplete_geometry_metadata(tmp_path, monkeypatch, config):
    path = tmp_path / 'pareto.csv'
    path.write_text(','.join([*(f'x{i}' for i in range(16)), 'Q_W_per_m', 'dP_Pa'])
                    + '\n' + ','.join(['1'] * 18) + '\n')
    monkeypatch.setattr(export_ntop_csv, 'export_decision_vector',
                        lambda *a, **kw: pytest.fail('invalid metadata exported'))
    with pytest.raises(ValueError, match='configuration'):
        export_pareto_row(str(path), 0, str(tmp_path / 'out'), config=config)
    assert not (tmp_path / 'out').exists()


def test_historical_geometry_export_keeps_failure_verdict(tmp_path):
    path = tmp_path / 'history.csv'
    x = _uniform_decision_vector()
    np.savetxt(path, np.r_[x, 10., 20.][None, :], delimiter=',',
               header=','.join([*(f'x{i}' for i in range(x.size)), 'Q_W_per_m', 'dP_Pa']),
               comments='')
    status = dict(evaluation=1, status='failed', reason='original solve failure')
    path.with_name('history_status.json').write_text(json.dumps([status]))
    result = export_pareto_row(str(path), 0, str(tmp_path / 'geometry'),
        config=ARCHIVED_GEOMETRY, Nx_export=4, Ny_export=4)
    assert result['source']['evaluation_status'] == status
