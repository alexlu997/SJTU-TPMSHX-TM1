from pathlib import Path

import pytest

from sjtu_tpmshx.io.file_set import staged_files


@pytest.mark.parametrize('existing', [False, True])
def test_final_publish_failure_restores_whole_set(tmp_path, monkeypatch, existing):
    from sjtu_tpmshx.io import file_set
    targets = [tmp_path / name for name in ('case.h5', 'case.yaml', 'metrics.json')]
    if existing:
        for target in targets:
            target.write_text('old-' + target.name)
    original = file_set.os.replace
    failed = False

    def replace(source, target):
        nonlocal failed
        if Path(target) == targets[-1] and Path(source).parent.name.startswith('.tm1-publish-') and not failed:
            failed = True
            raise OSError('final publish denied')
        return original(source, target)

    monkeypatch.setattr(file_set.os, 'replace', replace)
    with pytest.raises(OSError, match='final publish denied'):
        with staged_files(targets) as stage:
            for target in targets:
                (stage / target.name).write_text('new-' + target.name)
    assert failed
    for target in targets:
        if existing:
            assert target.read_text() == 'old-' + target.name
        else:
            assert not target.exists()
    assert not list(tmp_path.glob('.tm1-publish-*'))


def test_successful_2d_replacement_removes_stale_3d_companion(tmp_path):
    csv, npz = tmp_path / 'results.csv', tmp_path / 'results_fields.npz'
    csv.write_text('old-3d')
    npz.write_text('old-3d-fields')
    with staged_files([csv], remove=[npz]) as stage:
        (stage / csv.name).write_text('new-2d')
    assert csv.read_text() == 'new-2d'
    assert not npz.exists()


def test_failed_rollback_retains_recovery_files(tmp_path, monkeypatch):
    from sjtu_tpmshx.io import file_set
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_text('previous A')
    b.write_text('previous B')
    original = file_set.os.replace
    def replace(source, target):
        if Path(target) == b:
            raise OSError('target inaccessible during publish and recovery')
        return original(source, target)
    monkeypatch.setattr(file_set.os, 'replace', replace)
    with pytest.raises(OSError, match='retained files:') as error:
        with staged_files([a, b]) as stage:
            (stage / 'a').write_text('new A')
            (stage / 'b').write_text('new B')
    assert str(stage) in str(error.value)
    assert (stage / 'previous' / 'a').read_text() == 'previous A'
    assert (stage / 'previous' / 'b').read_text() == 'previous B'


def test_file_export_never_replaces_a_directory(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_text('old A')
    b.mkdir()
    (b / 'keep').write_text('user file')
    with pytest.raises(IsADirectoryError):
        with staged_files([a, b]) as stage:
            (stage / 'a').write_text('new A')
            (stage / 'b').write_text('new B')
    assert a.read_text() == 'old A'
    assert (b / 'keep').read_text() == 'user file'


def test_workflow_last_write_failure_keeps_previous_run_identities(tmp_path, monkeypatch):
    from dataclasses import replace
    from importlib import import_module
    from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case
    from sjtu_tpmshx.domain.field_result import FieldResult
    from sjtu_tpmshx.domain.metric_spec import MetricSpec
    from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
    from sjtu_tpmshx.io import metrics_io, yaml_config
    from sjtu_tpmshx.io.case_io import load_case
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.workflows.cli import main
    original = metrics_io.save_metrics

    def compute(config, case_id):
        case = replace(sample_case(), case_id=case_id)
        result = FieldResult(case_id + '-result', case_id, 'synthetic', grid=case.grid,
                             run_status={'execution': 'completed', 'converged': True})
        performance = PerformanceResult(case_id + '-metrics', result.result_id,
            {key: MetricValue(1., MetricSpec(key, unit)) for key, unit in
             (('Q', 'W/m'), ('dP_A', 'Pa'), ('dP_B', 'Pa'), ('T_out_A', 'K'), ('T_out_B', 'K'))})
        return case, result, performance

    monkeypatch.setattr(import_module('sjtu_tpmshx.workflows.compute'), 'compute', compute)
    monkeypatch.setattr(yaml_config, 'load_config', lambda path: None)
    output = tmp_path / 'run'
    args = ['run', 'unused.yaml', str(output), '--case-id']
    assert main(args + ['old']) == 0
    def fail(*args):
        raise OSError('metrics write failed')
    monkeypatch.setattr(metrics_io, 'save_metrics', fail)
    with pytest.raises(OSError, match='metrics write failed'):
        main(args + ['new'])
    assert load_case(output / 'case.yaml').case_id == 'old'
    assert load_result(output / 'results.h5').case_id == 'old'
    assert metrics_io.load_metrics(output / 'metrics.json').source_result_id == 'old-result'
    monkeypatch.setattr(metrics_io, 'save_metrics', original)
    assert main(args + ['new']) == 0
    assert load_case(output / 'case.yaml').case_id == load_result(output / 'results.h5').case_id == 'new'
    assert metrics_io.load_metrics(output / 'metrics.json').source_result_id == 'new-result'
    assert not list(output.glob('.tm1-publish-*'))
