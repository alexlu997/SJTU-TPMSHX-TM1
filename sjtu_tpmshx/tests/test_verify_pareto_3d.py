"""Pareto verification reads the original field layout and named objectives."""
import csv
import json

import numpy as np
import pytest

from sjtu_tpmshx.models.continuous_field import decision_dim
from sjtu_tpmshx.validation.cases import verify_pareto_3d as verify


def _write_pareto(path, dimension):
    values = {f'x{i}': float(i + 1) for i in range(dimension)}
    values.update(Q_W_per_m=1234., dP_Pa=567.)
    # Reordered columns must not turn a decision variable into an objective.
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(reversed(values)))
        writer.writeheader()
        writer.writerow(values)
    return np.arange(1., dimension + 1)


@pytest.mark.parametrize('nx,ny,symmetric', [(4, 4, True), (4, 4, False), (6, 6, True)])
def test_configured_layout_and_override_reach_verification(tmp_path, monkeypatch,
                                                         nx, ny, symmetric, capsys):
    cfg = dict(n_ctrl_x=4, n_ctrl_y=4, symmetric_y=True, u_A=10.)
    (tmp_path / 'config.json').write_text(json.dumps(cfg))
    layout = dict(n_ctrl_x=nx, n_ctrl_y=ny, symmetric_y=symmetric)
    path = tmp_path / 'pareto_final.csv'
    expected = _write_pareto(path, decision_dim(**layout))
    calls = []

    def evaluate(x, received_cfg, **kwargs):
        np.testing.assert_array_equal(x, expected)
        assert received_cfg == {**cfg, **layout}
        assert kwargs['convergence_mode'] == 'f2' and kwargs['max_outer'] == 12
        calls.append(x)
        return dict(converged=True, Q_3D_W=12.34, dP_total_Pa=567.,
                    dP_A_Pa=300., dP_B_Pa=267., mass_kg=.2)

    monkeypatch.setattr(verify, 'evaluate_3d', evaluate)
    assert verify.main(['--pareto', str(path), '--cfg-override', json.dumps(layout),
                        '--Lz', '.01']) == 0
    assert len(calls) == 1
    assert 'Q = 1234 W/m   dP = 567 Pa' in capsys.readouterr().out


@pytest.mark.parametrize('damage', ['dimension', 'duplicate', 'missing', 'extra', 'nonfinite'])
def test_bad_pareto_is_rejected_before_solver(tmp_path, monkeypatch, damage):
    path = tmp_path / 'pareto_final.csv'
    _write_pareto(path, 36 if damage == 'dimension' else 16)
    with path.open(newline='') as source:
        header, row = list(csv.reader(source))
    if damage == 'duplicate':
        header[-1] = header[-2]
    elif damage == 'missing':
        row.pop()
    elif damage == 'extra':
        row.append('1')
    elif damage == 'nonfinite':
        row[0] = 'nan'
    with path.open('w', newline='') as target:
        csv.writer(target).writerows([header, row])
    monkeypatch.setattr(verify, 'evaluate_3d', lambda *a, **k: pytest.fail('invalid CSV launched'))
    with pytest.raises(ValueError, match='Pareto'):
        verify.main(['--pareto', str(path)])


@pytest.mark.parametrize('row', [-1, 1])
def test_pareto_row_index_bounds(tmp_path, row):
    path = tmp_path / 'pareto_final.csv'
    _write_pareto(path, 16)
    with pytest.raises(IndexError, match='out of range'):
        verify._load_pareto_row(str(path), row, 16)
