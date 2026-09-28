"""Zero reference objectives remain reportable without invented denominators."""
import csv
import json

import pytest

from sjtu_tpmshx.models.continuous_field import decision_dim
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
from sjtu_tpmshx.validation.cases import verify_pareto_3d as verify


@pytest.mark.parametrize('q_ref,q_3d,dp_ref,dp_3d,q_text,dp_text', [
    (0., 0., 2., 2., 'undefined (zero 2D reference)', '+0.00 %'),
    (0., 1., 0., 1., 'undefined (zero 2D reference)', 'undefined (zero 2D reference)'),
    (100., 4.62, .5, 1., '+10.00 %', '+100.00 %'),
])
def test_verification_reports_zero_and_small_reference_objectives(
        tmp_path, monkeypatch, capsys, q_ref, q_3d, dp_ref, dp_3d, q_text, dp_text):
    config = {**DEFAULT_CONFIG, 'T_inA': 300., 'T_inB': 300.}
    (tmp_path / 'config.json').write_text(json.dumps(config))
    dimension = decision_dim(**{key: config[key] for key in
                               ('n_ctrl_x', 'n_ctrl_y', 'symmetric_y')})
    path = tmp_path / 'pareto.csv'
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow([*(f'x{i}' for i in range(dimension)), 'Q_W_per_m', 'dP_Pa'])
        writer.writerow([*([7.] * (dimension // 2)), *([.5] * (dimension // 2)), q_ref, dp_ref])
    calls = []

    def evaluate(*args, **kwargs):
        calls.append(1)
        return dict(converged=True, finite=True, simple_A_converged=True,
                    simple_B_converged=True, ltne_inner_converged=True,
                    outer_converged=True, Q_3D_W=q_3d, dP_total_Pa=dp_3d,
                    dP_A_Pa=dp_3d / 2., dP_B_Pa=dp_3d / 2., mass_kg=.2)

    monkeypatch.setattr(verify, 'evaluate_3d', evaluate)
    assert verify.main(['--pareto', str(path)]) == 0
    output = capsys.readouterr().out
    assert calls == [1]
    assert any('ΔQ rel' in line and q_text in line for line in output.splitlines())
    assert any('ΔdP rel' in line and dp_text in line for line in output.splitlines())
    assert 'mass' in output and 'Q_3D' in output and 'dP_A_3D' in output
