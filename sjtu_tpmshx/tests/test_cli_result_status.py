"""CLI verdict and existing result messages; no numerical solve required."""
import json
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.cli import main
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult


@pytest.mark.parametrize('as_json', [False, True])
@pytest.mark.parametrize('converged,envelope,outer,messages,exit_code', [
    (True, True, True, False, 0), (True, True, True, True, 0),
    (False, True, True, True, 2), (True, False, True, True, 2),
    (True, True, False, True, 2),
])
def test_cli_result_status(tmp_path, monkeypatch, capsys, as_json,
                           converged, envelope, outer, messages, exit_code):
    import sjtu_tpmshx.controllers.compute_pipeline as pipeline

    config = tmp_path / 'config.json'
    ComputeConfig().to_json(config)
    result = ComputeResult(
        converged=converged, warnings=['经验外推,\n第二行', '警告二'] if messages else [],
        extrap_reasons=['Re 超范围'] if messages else [],
        diagnostics={'envelope_valid': envelope,
                     'convergence_detail': {'outer_converged': outer}},
    )
    monkeypatch.setattr(pipeline, 'pipeline_for', lambda cc: SimpleNamespace(run=lambda: result))
    assert main([str(config)] + (['--json'] if as_json else [])) == exit_code
    output = capsys.readouterr().out
    if as_json:
        summary = json.loads(output)
        assert summary['converged'] == converged
        assert summary['warnings'] == result.warnings
        assert summary['extrap_reasons'] == result.extrap_reasons
    else:
        assert f'\nconverged = {converged}   envelope_valid = {envelope}' in output
        for message in result.warnings + result.extrap_reasons:
            assert message in output


def test_dry_run_does_not_claim_computed_status(tmp_path, monkeypatch, capsys):
    import sjtu_tpmshx.controllers.compute_pipeline as pipeline

    config = tmp_path / 'config.json'
    ComputeConfig().to_json(config)
    monkeypatch.setattr(pipeline, 'pipeline_for', lambda cc: SimpleNamespace())
    assert main([str(config), '--dry-run', '--json']) == 0
    assert set(json.loads(capsys.readouterr().out)) == {'pipeline', 'grid'}


def test_machine_output_separates_logs_and_preserves_unavailable_status(tmp_path, monkeypatch, capsys):
    import sys
    import sjtu_tpmshx.controllers.compute_pipeline as pipeline

    config = tmp_path / 'config.json'
    ComputeConfig().to_json(config)
    result = ComputeResult(
        Q_W=float('nan'), converged=False, warnings=['热量不可用'],
        metadata={'metric_status': {'Q': 'invalid'},
                  'metric_reasons': {'Q': 'nonfinite boundary energy'},
                  'diagnostic': [float('inf'), float('-inf')]},
    )

    def run():
        print('solver progress')
        print('solver warning', file=sys.stderr)
        return result

    monkeypatch.setattr(pipeline, 'pipeline_for', lambda cc: SimpleNamespace(run=run))
    assert main([str(config), '--json']) == 2
    captured = capsys.readouterr()

    def reject_constant(value):
        raise AssertionError(f'nonstandard JSON constant: {value}')

    summary = json.loads(captured.out, parse_constant=reject_constant)
    assert summary['Q_W'] is None
    assert summary['metadata']['metric_status']['Q'] == 'invalid'
    assert summary['metadata']['metric_reasons']['Q'] == 'nonfinite boundary energy'
    assert summary['metadata']['diagnostic'] == [None, None]
    assert summary['warnings'] == ['热量不可用']
    assert 'solver progress' in captured.err and 'solver warning' in captured.err
