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


@pytest.mark.parametrize('platform,relative', [
    ('darwin', 'native/lib/macos-arm64/libtpmshx_solver_shared.dylib'),
    ('win32', 'native/lib/windows-x64/tpmshx_solver_shared.dll'),
])
def test_source_cli_resolves_local_delivery_and_preserves_explicit_paths(
        tmp_path, monkeypatch, platform, relative):
    from sjtu_tpmshx.io import cli_options
    monkeypatch.setattr(cli_options, 'SOURCE_ROOT', tmp_path)
    monkeypatch.setattr(cli_options.sys, 'platform', platform)
    monkeypatch.setattr(cli_options.sys, 'frozen', False, raising=False)
    parser = argparse.ArgumentParser()
    add_run_control_arguments(parser)
    assert run_control_from_args(parser.parse_args(['--backend', 'cpp'])) == RunControl(
        backend='cpp', native_library=str(tmp_path / relative),
        native_table_directory=str(tmp_path / '.cache/native-deps/tables'))
    tables = tmp_path / 'selected-tables'
    actual = run_control_from_args(parser.parse_args([
        '--backend', 'cpp', '--native-table-directory', str(tables)]))
    assert actual.native_library == str(tmp_path / relative)
    assert actual.native_table_directory == str(tables)
    library = tmp_path / 'selected-library'
    assert run_control_from_args(parser.parse_args([
        '--backend', 'cpp', '--native-library', str(library)])) == RunControl(
        backend='cpp', native_library=str(library))


def test_other_source_platform_requires_explicit_library(tmp_path, monkeypatch):
    from sjtu_tpmshx.io import cli_options
    monkeypatch.setattr(cli_options.sys, 'platform', 'linux')
    monkeypatch.setattr(cli_options.sys, 'frozen', False, raising=False)
    parser = argparse.ArgumentParser()
    add_run_control_arguments(parser)
    with pytest.raises(ValueError, match='use --native-library'):
        run_control_from_args(parser.parse_args(['--backend', 'cpp']))
    library = tmp_path / 'solver.so'
    assert run_control_from_args(parser.parse_args([
        '--backend', 'cpp', '--native-library', str(library)])) == RunControl(
        backend='cpp', native_library=str(library))


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


@pytest.mark.parametrize('stage', ['run', 'resume'])
@pytest.mark.parametrize('outcome,code', [('complete', 0), ('unconverged', 2), ('paused', 3)])
def test_recoverable_cli_uses_saved_run_and_restores_sigint(stage, outcome, code,
                                                         tmp_path, monkeypatch, capsys):
    import signal
    from types import SimpleNamespace
    from sjtu_tpmshx import cli as entry
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.domain.paused_run import PausedRun
    from sjtu_tpmshx.workflows import recovery

    source = tmp_path / ('config.json' if stage == 'run' else 'checkpoint.h5')
    if stage == 'run':
        ComputeConfig().to_json(source)
    output, library = tmp_path / 'new-run', tmp_path / 'solver.so'
    previous = signal.getsignal(signal.SIGINT)
    calls = []

    def execute(value, directory, **kwargs):
        calls.append(value)
        assert directory == output
        assert kwargs['control'] == RunControl(backend='cpp', native_library=str(library))
        assert kwargs['checkpoint_interval_s'] == 42.
        assert not kwargs['pause_check']()
        if outcome == 'paused':
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            assert kwargs['pause_check']()
            raise PausedRun(output / 'checkpoint.h5')
        result = SimpleNamespace(run_status={'converged': outcome == 'complete'})
        performance = SimpleNamespace(qualification={'design': {'status': 'unverified'}},
            metrics={name: SimpleNamespace(status='available')
                     for name in ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')})
        return None, result, performance

    monkeypatch.setattr(recovery, 'compute_run' if stage == 'run' else 'resume_run', execute)
    arguments = [stage, str(source), str(output), '--native-library', str(library),
                 '--checkpoint-interval', '42']
    if stage == 'run':
        arguments += ['--case-id', 'recoverable-cli', '--backend', 'cpp']
    assert entry.main(arguments) == code
    assert signal.getsignal(signal.SIGINT) == previous
    assert len(calls) == 1
    if stage == 'resume':
        assert calls == [source]
    text = capsys.readouterr().out
    assert ('paused = ' in text) == (outcome == 'paused')
    assert ('design = ' in text) == (outcome != 'paused')


def test_recoverable_cli_restores_sigint_after_failure(tmp_path, monkeypatch):
    import signal
    from sjtu_tpmshx.workflows import recovery
    previous = signal.getsignal(signal.SIGINT)
    failure = OSError('saved state could not be read')

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(recovery, 'resume_run', fail)
    with pytest.raises(OSError) as caught:
        cli.main(['resume', str(tmp_path / 'checkpoint.h5'), str(tmp_path / 'new'),
                  '--native-library', str(tmp_path / 'solver.so'), '--checkpoint-interval', '42'])
    assert caught.value is failure
    assert signal.getsignal(signal.SIGINT) == previous
