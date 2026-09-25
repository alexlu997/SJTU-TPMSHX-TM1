"""CLI path protection with real native files and no numerical evaluation."""
from dataclasses import replace
from importlib import import_module
from unittest.mock import Mock

import pytest
import yaml

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.cli import main
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.metrics_io import load_metrics, save_metrics
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case


@pytest.fixture
def native_stages(monkeypatch):
    case = sample_case()
    result = FieldResult('new-result', case.case_id, 'synthetic', grid=case.grid,
                         run_status={'execution': 'completed', 'converged': True})
    performance = PerformanceResult('new-metrics', result.result_id, {
        key: MetricValue(1., MetricSpec(kind, unit)) for key, kind, unit in
        (('Q', 'Q', 'W/m'), ('dP_A', 'dP', 'Pa'), ('dP_B', 'dP', 'Pa'),
         ('T_out_A', 'T_out', 'K'), ('T_out_B', 'T_out', 'K'))})
    calls = []
    for module, name, value in (
        ('sjtu_tpmshx.preprocess.api', 'prepare_case', case),
        ('sjtu_tpmshx.solvers.api', 'run_case', result),
        ('sjtu_tpmshx.postprocess.api', 'evaluate', performance),
        ('sjtu_tpmshx.workflows.compute', 'compute', (case, result, performance)),
    ):
        call = Mock(return_value=value)
        monkeypatch.setattr(import_module(module), name, call)
        calls.append(call)
    return case, result, performance, calls


@pytest.mark.parametrize('alias', ['direct', 'input_symlink', 'output_symlink'])
@pytest.mark.parametrize('stage,overlap', [
    ('prepare', 'config.yaml'), ('prepare', 'config.h5'),
    ('solve', 'case.yaml'), ('solve', 'payload.h5'), ('solve', 'direct.h5'),
    ('postprocess', 'results.h5'),
    ('run', 'case.yaml'), ('run', 'case.h5'),
    ('run', 'results.h5'), ('run', 'metrics.json'),
])
def test_cli_rejects_input_collision_before_work(
        tmp_path, capsys, native_stages, stage, overlap, alias):
    case, result, _, calls = native_stages
    if stage == 'prepare':
        source = tmp_path / overlap
        ComputeConfig().to_json(source)
        output = source.with_suffix('.yaml')
        collision = source
    elif stage == 'solve':
        source = tmp_path / 'case.yaml'
        save_case(case, source)
        payload = tmp_path / 'payload.h5'
        source.with_suffix('.h5').rename(payload)
        manifest = yaml.safe_load(source.read_text())
        manifest['hdf5'] = payload.name
        source.write_text(yaml.safe_dump(manifest), encoding='utf-8')
        if overlap == 'direct.h5':
            source = payload
            output = payload
        else:
            output = tmp_path / overlap
        collision = output
    elif stage == 'postprocess':
        source = output = collision = tmp_path / 'results.h5'
        save_result(result, source)
    else:
        output = tmp_path / 'run'
        output.mkdir()
        source = collision = output / overlap
        ComputeConfig().to_json(source)

    if alias == 'input_symlink':
        link = source.with_name('input-alias' + source.suffix)
        link.symlink_to(source)
        source = link
    elif alias == 'output_symlink':
        if stage == 'run':
            output = tmp_path / 'output-alias'
            output.mkdir()
            (output / overlap).symlink_to(collision)
        else:
            output = tmp_path / ('output-alias.yaml' if stage == 'prepare' else 'output-alias.h5')
            link = output.with_suffix('.h5') if stage == 'prepare' and overlap.endswith('.h5') else output
            link.symlink_to(collision)

    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    args = [stage, str(source), str(output)]
    if stage in ('prepare', 'run'):
        args += ['--case-id', case.case_id]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert 'output overlaps input' in capsys.readouterr().err
    for call in calls:
        call.assert_not_called()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize('stage', ['prepare', 'solve', 'postprocess', 'run'])
def test_cli_can_replace_independent_old_outputs(tmp_path, native_stages, stage):
    case, result, performance, _ = native_stages
    old_case = replace(case, case_id='old-case')
    old_result = replace(result, result_id='old-result', case_id=old_case.case_id)
    old_metrics = replace(performance, result_id='old-metrics', source_result_id=old_result.result_id)
    if stage in ('prepare', 'run'):
        source = tmp_path / 'config.json'
        ComputeConfig().to_json(source)
        output = tmp_path / ('output.yaml' if stage == 'prepare' else 'run')
        if stage == 'prepare':
            save_case(old_case, output)
        else:
            output.mkdir()
            save_case(old_case, output / 'case.yaml')
            save_result(old_result, output / 'results.h5')
            save_metrics(old_metrics, output / 'metrics.json')
    elif stage == 'solve':
        source, output = tmp_path / 'case.yaml', tmp_path / 'results.h5'
        save_case(case, source)
        save_result(old_result, output)
    else:
        source, output = tmp_path / 'results.h5', tmp_path / 'metrics.json'
        save_result(result, source)
        save_metrics(old_metrics, output)
    original = source.read_bytes()
    args = [stage, str(source), str(output)]
    if stage in ('prepare', 'run'):
        args += ['--case-id', case.case_id]
    assert main(args) == 0
    assert source.read_bytes() == original
    if stage == 'prepare':
        assert load_case(output).case_id == case.case_id
    elif stage == 'solve':
        assert load_case(source).case_id == load_result(output).case_id == case.case_id
    elif stage == 'postprocess':
        assert load_metrics(output).source_result_id == load_result(source).result_id
    else:
        assert load_case(output / 'case.yaml').case_id == load_result(output / 'results.h5').case_id
        assert load_metrics(output / 'metrics.json').source_result_id == result.result_id
