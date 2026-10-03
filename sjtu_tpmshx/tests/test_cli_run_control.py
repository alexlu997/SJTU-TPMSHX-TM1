"""CLI execution choices belong to RunControl, not portable configuration."""
import argparse

import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.cli_options import add_run_control_arguments, run_control_from_args
from sjtu_tpmshx.workflows import cli


def test_default_and_relative_native_cli_paths(tmp_path, monkeypatch):
    parser = argparse.ArgumentParser()
    add_run_control_arguments(parser)
    assert run_control_from_args(parser.parse_args([])) == RunControl()
    monkeypatch.chdir(tmp_path)
    args = parser.parse_args(['--backend', 'cpp', '--native-library', 'solver.so',
                              '--native-table-directory', 'tables'])
    assert run_control_from_args(args) == RunControl(
        backend='cpp', native_library=str(tmp_path / 'solver.so'),
        native_table_directory=str(tmp_path / 'tables'))


@pytest.mark.parametrize('platform,name', [('darwin', 'libtpmshx_solver_shared.dylib'),
                                         ('win32', 'tpmshx_solver_shared.dll')])
def test_frozen_cli_uses_only_explicit_or_bundled_library(tmp_path, monkeypatch, platform, name):
    import sys
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(sys, 'platform', platform)
    parser = argparse.ArgumentParser()
    add_run_control_arguments(parser)
    assert run_control_from_args(parser.parse_args([])) == RunControl()
    assert run_control_from_args(parser.parse_args(['--backend', 'cpp'])) == RunControl(
        backend='cpp', native_library=str(tmp_path / 'native' / name))
    explicit = tmp_path / 'selected' / name
    actual = run_control_from_args(parser.parse_args([
        '--backend', 'cpp', '--native-library', str(explicit)]))
    assert actual.native_library == str(explicit)


@pytest.mark.parametrize('option', ['--native-library', '--native-table-directory'])
@pytest.mark.parametrize('explicit_python', [False, True])
def test_native_paths_require_explicit_cpp_backend(option, explicit_python):
    parser = argparse.ArgumentParser()
    add_run_control_arguments(parser)
    arguments = [option, 'native-path'] + (['--backend', 'python'] if explicit_python else [])
    with pytest.raises(ValueError, match='require --backend cpp'):
        run_control_from_args(parser.parse_args(arguments))


@pytest.mark.parametrize('stage', ['solve', 'run'])
@pytest.mark.parametrize('backend', ['python', 'cpp'])
def test_workflow_control_reaches_execution_and_cancellation_keeps_output(
        stage, backend, tmp_path, monkeypatch):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.tests.io_tm1.test_case_io import sample_case
    from sjtu_tpmshx.solvers import api
    import importlib

    source = tmp_path / ('case.h5' if stage == 'solve' else 'config.json')
    output = tmp_path / ('result.h5' if stage == 'solve' else 'run')
    if stage == 'solve':
        save_case(sample_case(), source)
        saved = output
    else:
        ComputeConfig().to_json(source)
        output.mkdir()
        saved = output / 'results.h5'
    saved.write_bytes(b'existing result')
    previous_input = source.read_bytes()
    calls = []

    def cancel(value, *, control, **kwargs):
        calls.append(control)
        raise CancelledError('cancel before saving')

    if stage == 'solve':
        monkeypatch.setattr(api, 'run_case', cancel)
    else:
        monkeypatch.setattr(importlib.import_module('sjtu_tpmshx.workflows.compute'),
                            'compute', cancel)
    library, tables = tmp_path / 'solver.so', tmp_path / 'tables'
    arguments = [stage, str(source), str(output), '--backend', backend]
    if backend == 'cpp':
        arguments += ['--native-library', str(library), '--native-table-directory', str(tables)]
    if stage == 'run':
        arguments += ['--case-id', 'cli-control']
    assert cli.main(arguments) == 130
    assert calls == [RunControl(backend=backend,
        native_library=str(library) if backend == 'cpp' else None,
        native_table_directory=str(tables) if backend == 'cpp' else None)]
    assert saved.read_bytes() == b'existing result'
    assert source.read_bytes() == previous_input


@pytest.mark.parametrize('stage', ['prepare', 'postprocess'])
def test_numerical_control_flags_are_limited_to_execution_stages(stage, tmp_path):
    arguments = [stage, str(tmp_path / 'input'), str(tmp_path / 'output'),
                 '--backend', 'cpp']
    if stage == 'prepare':
        arguments += ['--case-id', 'cli-control']
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments)
    assert caught.value.code == 2
    assert not (tmp_path / 'output').exists()
