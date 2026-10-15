"""Saved pauses use a separate UI outcome and the common recovery workflow."""
from dataclasses import asdict, replace
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.controllers.compute_orchestrator import CancelToken
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.tests.gui_worker_support import win as win, _configure, _wait_for
from sjtu_tpmshx.tests.gui_workbench_support import _result
from sjtu_tpmshx.ui.mixins.run_controller import _run_compute


@pytest.mark.parametrize('resume', [False, True])
def test_gui_worker_uses_recovery_and_maps_only_complete_results(tmp_path, monkeypatch, resume):
    from sjtu_tpmshx.controllers import module_adapter
    from sjtu_tpmshx.workflows import recovery

    token = CancelToken()
    native, performance, display, config = object(), object(), object(), object()
    library = str(tmp_path / 'solver-library')
    checkpoint = tmp_path / 'checkpoint.h5' if resume else None
    observed, ui_iterations, original_iterations = [], [], []

    def execute(value, directory, **kwargs):
        observed.append(value)
        assert directory == tmp_path / 'new'
        assert kwargs['checkpoint_interval_s'] == 42
        assert kwargs['control'].backend == 'cpp'
        assert kwargs['control'].native_library == library
        assert not kwargs['control'].cancel_check()
        assert not kwargs['pause_check']()
        token.pause()
        assert kwargs['pause_check']()
        kwargs['control'].iteration('inner 3')
        return None, native, performance

    def convert(result, metrics):
        assert result is native and metrics is performance
        return display

    monkeypatch.setattr(recovery, 'resume_run' if resume else 'compute_run', execute)
    monkeypatch.setattr(module_adapter, 'to_compute_result', convert)
    control = replace(RunControl(backend='cpp', native_library=library),
                      iteration=original_iterations.append)
    actual = _run_compute(config, token, None, control=control,
        ui_hooks={'iter_label_cb': ui_iterations.append}, run_directory=tmp_path / 'new',
        checkpoint_interval_s=42, resume_checkpoint=checkpoint, gui_provenance={'mode': '2d'})
    assert actual is display
    assert observed == [checkpoint if resume else config]
    assert ui_iterations == original_iterations == ['inner 3']


def test_saved_pause_keeps_the_last_complete_gui_result(win, tmp_path, monkeypatch):
    config = _configure(win, monkeypatch, '2d')
    accepted = _result('2d')
    win.write_result(accepted)
    accepted = win.cache.get_result('2d')
    checkpoint = tmp_path / 'new' / 'checkpoint.h5'
    win._active_run_directory = checkpoint.parent
    entered, release = threading.Event(), threading.Event()

    def worker(cfg, token, progress_cb):
        entered.set()
        assert release.wait(5)
        assert token.pause_requested() and not token.cancelled
        print('checkpoint published')
        raise PausedRun(checkpoint)

    assert win.compute.start('2d', worker, config)
    try:
        assert entered.wait(2)
        card = win._run_status_card
        assert not card.pause_button.isHidden()
        card.pause_button.click()
        assert card.state == 'pausing'
        assert not card.pause_button.isEnabled()
        assert win.compute.is_running()
    finally:
        release.set()
        _wait_for(win.compute.is_idle)
    assert card.state == 'paused'
    assert str(checkpoint) in card.note.text()
    assert card.pause_button.isHidden() and card.cancel_button.isHidden()
    assert win.cache.get_result('2d') is accepted
    assert win._last_checkpoint_file == str(checkpoint)
    assert not win._test_error_dialogs
    assert win._run_provenance is None
    assert win.btn_compute.isEnabled()


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('from_gui', [False, True])
def test_resume_uses_saved_inputs_and_provenance_without_changing_draft(
        win, tmp_path, monkeypatch, mode, from_gui):
    from sjtu_tpmshx.workflows import recovery
    from sjtu_tpmshx.ui.mixins import run_controller

    config = _configure(win, monkeypatch, '2d')
    config = replace(config, geometry=replace(config.geometry, Lz_m=.03 if mode == '3d' else None),
                     solver=replace(config.solver, Nx=4, Ny=6, Nz=2 if mode == '3d' else 1))
    preset = win._capture_current_preset('Saved inputs')
    preset['line_edits']['le_Nx'] = '4'
    provenance = dict(preset=preset, preset_source='Saved GUI inputs') if from_gui else None
    case = SimpleNamespace(case_id='saved-physical-input', config_snapshot=asdict(config),
                           grid={'dimension': 3 if mode == '3d' else 2})
    checkpoint = tmp_path / 'old' / 'checkpoint.h5'
    monkeypatch.setattr(recovery, 'read_run_checkpoint', lambda path:
        (None, case, {'checkpoint_interval_s': 42, 'gui_provenance': provenance}))
    library = tmp_path / 'explicit-library'
    library.touch()
    win.run_control = replace(win.run_control, native_library=str(library))
    win.le_Nx.setText('99')
    win.le_uA.setText('7.77')
    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[1:3]))
    entered, release = threading.Event(), threading.Event()
    observed = []

    def worker(actual, token, progress_cb, **kwargs):
        observed.append((actual, kwargs))
        entered.set()
        assert release.wait(5)
        result = _result(mode)
        result.metadata['inlet_inputs'] = {'A': {'mass_flow_kg_s': .1, 'u_mps': .2}}
        return result

    monkeypatch.setattr(run_controller, '_run_compute', worker)
    win._resume_saved_run(checkpoint)
    try:
        assert entered.wait(2), warnings
        assert observed[0][0] == config
        kwargs = observed[0][1]
        assert kwargs['control'].backend == 'cpp'
        assert kwargs['resume_checkpoint'] == checkpoint
        assert kwargs['checkpoint_interval_s'] == 42
        assert kwargs['run_directory'].parent == tmp_path
        assert kwargs['run_directory'] != checkpoint.parent
        assert win.compute.current_mode() == mode
        win.le_Nx.setText('123')
    finally:
        release.set()
        _wait_for(win.compute.is_idle)
    result = win.cache.get_result(mode)
    saved = result.metadata['run_provenance']
    assert saved['mode'] == mode
    assert saved['input_grid'] == ([4, 6, 2] if mode == '3d' else [4, 6])
    assert saved['resumed_from'] == str(checkpoint)
    assert saved['preset'] == (preset if from_gui else None)
    assert win.le_Nx.text() == '123' and win.le_uA.text() == '7.77'
    assert win._active_run_directory is None
    if from_gui:
        assert win._recent_runs[0]['preset']['line_edits']['le_Nx'] == '4'
    else:
        assert win._recent_runs[0]['preset'] is None
    action = next(action for action in win.btn_recent.menu().actions()
                  if action.text().strip().startswith('#1'))
    assert action.isEnabled() is from_gui
    assert not win._test_error_dialogs
    assert not warnings


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('backend', ['python', 'cpp'])
def test_new_gui_run_saves_native_state_and_frozen_input_provenance(
        win, tmp_path, monkeypatch, mode, backend):
    from sjtu_tpmshx.controllers import module_adapter
    from sjtu_tpmshx.workflows import recovery

    config = _configure(win, monkeypatch, mode)
    preset = win._capture_current_preset('Run inputs')
    library = tmp_path / 'explicit-library'
    library.touch()
    win.run_control = replace(win.run_control, native_library=str(library))
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData(backend))
    assert win.run_control.backend == backend
    monkeypatch.setattr(win, '_render_compute_result', lambda: True)
    display, native, performance = _result(mode), object(), object()
    entered, release = threading.Event(), threading.Event()
    observed = []

    def execute(actual, directory=None, **kwargs):
        observed.append((actual, directory, kwargs))
        entered.set()
        assert release.wait(5)
        return (None, native, performance) if backend == 'cpp' else display

    def convert(result, metrics):
        assert result is native and metrics is performance
        return display

    monkeypatch.setattr(recovery, 'compute_run', execute)
    monkeypatch.setattr(module_adapter, 'compute_result', execute)
    monkeypatch.setattr(module_adapter, 'to_compute_result', convert)
    win.run_calculation()
    try:
        assert entered.wait(2)
        actual, directory, kwargs = observed[0]
        assert actual == config
        assert kwargs['control'].backend == backend
        if backend == 'cpp':
            assert directory.parent == win.sm.base_dir / 'runs'
            assert kwargs['checkpoint_interval_s'] == 60
            assert kwargs['gui_provenance']['preset'] == preset
            assert kwargs['gui_provenance']['mode'] == mode
            assert win._active_run_directory == directory
            assert str(directory) in win._run_status_card.note.text()
            assert not win._run_status_card.pause_button.isHidden()
        else:
            assert directory is None and 'checkpoint_interval_s' not in kwargs
            assert win._run_status_card.pause_button.isHidden()
        win.le_Nx.setText('123')
        if backend == 'cpp':
            assert kwargs['gui_provenance']['preset'] == preset
    finally:
        release.set()
        _wait_for(win.compute.is_idle)
    assert win.cache.get_result(mode).metadata['run_provenance']['preset'] == preset
    assert win._active_run_directory is None
    assert win._pending_run_provenance is None
    assert not win._test_error_dialogs


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_rejected_new_run_clears_pending_recovery_state(win, monkeypatch, mode):
    _configure(win, monkeypatch, mode)
    win.run_control = replace(win.run_control, backend='cpp')
    monkeypatch.setattr(win.compute, 'start', lambda *args, **kwargs: False)
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    win.run_calculation()
    assert win._active_run_directory is None
    assert win._pending_run_provenance is None
    assert not (win.sm.base_dir / 'runs').exists()
    assert win.compute.is_idle()


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_failed_new_run_keeps_accepted_result_and_exposes_saved_state(
        win, tmp_path, monkeypatch, mode):
    from sjtu_tpmshx.workflows import recovery

    _configure(win, monkeypatch, mode)
    win.write_result(_result(mode))
    accepted = win.cache.get_result(mode)
    library = tmp_path / 'explicit-library'
    library.touch()
    win.run_control = replace(win.run_control, native_library=str(library))
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData('cpp'))
    checkpoints = []

    def fail(config, directory, **kwargs):
        directory.mkdir(parents=True)
        checkpoint = directory / 'checkpoint.h5'
        checkpoint.touch()
        checkpoints.append(checkpoint)
        raise OSError('test storage failure after a saved state')

    monkeypatch.setattr(recovery, 'compute_run', fail)
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    assert len(checkpoints) == 1
    assert win.cache.get_result(mode) is accepted
    assert win._run_status_card.state == 'error'
    assert win._last_checkpoint_file == str(checkpoints[0])
    assert str(checkpoints[0]) in win._run_status_card.note.text()
    assert win._active_run_directory is None
    assert len(win._test_error_dialogs) == 1
