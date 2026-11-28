"""Installed desktop state survives restarts without writing into its package."""
import json
import os
import sys

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QInputDialog, QMessageBox

from tm1.applications.gui.controllers import user_storage
from tm1.applications.gui.controllers.session_manager import SessionManager
from tests.python.gui_workbench_support import win as win


@pytest.fixture
def user_locations(tmp_path, monkeypatch):
    roots = {
        QStandardPaths.StandardLocation.GenericDataLocation: tmp_path / 'data',
        QStandardPaths.StandardLocation.GenericConfigLocation: tmp_path / 'config',
        QStandardPaths.StandardLocation.DocumentsLocation: tmp_path / 'documents',
    }
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda kind: str(roots[kind]))
    return roots


def test_user_data_persists_sessions_and_presets_in_platform_data_location(user_locations):
    roots = user_locations
    data_dir = roots[QStandardPaths.StandardLocation.GenericDataLocation] / 'SJTU-TPMSHX-TM1'
    saved_input = {'line_edits': {'le_TinA': '440.5'}}
    manager = SessionManager()
    assert manager.base_dir == data_dir
    assert manager.save_session(saved_input)
    assert manager.set_active_workspace('B')
    assert manager.save_user_presets([{'name': 'my case'}])
    reloaded = SessionManager()
    assert reloaded.load_session()['line_edits'] == saved_input['line_edits']
    assert reloaded.get_active_workspace() == 'B'
    assert reloaded.load_user_presets() == [{'name': 'my case'}]
    assert reloaded.save_session({'line_edits': {'le_TinA': '450'}})
    assert SessionManager().load_session()['line_edits']['le_TinA'] == '450'


def test_appearance_uses_user_read_write_location(user_locations):
    assert user_storage.load_appearance_settings() == {}
    for name, value in {'theme': 'dark', 'density': 'cozy', 'accent': '#A1b2c3'}.items():
        assert user_storage.save_appearance_setting(name, value)
    assert user_storage.load_appearance_settings() == {
        'theme': 'dark', 'density': 'cozy', 'accent': '#A1b2c3'}

    inspector_payload = json.dumps({
        'run': {'open': True, 'tab': 0},
        'result': {'open': False, 'tab': 0},
        'opt': {'open': True, 'tab': 1},
        'qd': {'open': False, 'tab': 0},
    }, sort_keys=True)
    assert user_storage.save_appearance_setting('inspector', inspector_payload)
    assert user_storage.load_appearance_settings()['inspector'] == inspector_payload
    with pytest.raises(ValueError):
        user_storage.save_appearance_setting(
            'inspector', json.dumps({'unknown': {'open': True, 'tab': 0}})
        )


def test_colormap_and_reduced_motion_preferences_roundtrip_and_validate(user_locations):
    from tm1.applications.gui.ui.microanim import (
        apply_saved_reduced_motion, is_reduced_motion, set_reduced_motion,
    )
    from tm1.applications.gui.ui.theme import (
        apply_saved_colormaps, resolve_cmap, set_cmap,
    )

    try:
        assert user_storage.save_appearance_setting('cmap_temperature', 'cividis')
        assert user_storage.save_appearance_setting('cmap_speed', 'turbo')
        assert user_storage.save_appearance_setting('cmap_pressure', 'coolwarm')
        assert user_storage.save_appearance_setting('cmap_design', 'viridis')
        assert user_storage.save_appearance_setting('reduced_motion', 'true')
        saved = user_storage.load_appearance_settings()
        assert saved == {
            'cmap_temperature': 'cividis',
            'cmap_speed': 'turbo',
            'cmap_pressure': 'coolwarm',
            'cmap_design': 'viridis',
            'reduced_motion': 'true',
        }
        apply_saved_colormaps(saved)
        apply_saved_reduced_motion(saved)
        assert resolve_cmap('Ta') == 'cividis'
        assert resolve_cmap('vmag_A') == 'turbo'
        assert resolve_cmap('P_fB') == 'coolwarm'
        assert resolve_cmap('L_mm') == 'viridis'
        assert is_reduced_motion() is True
        with pytest.raises(ValueError):
            user_storage.save_appearance_setting('cmap_temperature', 'jet')
        with pytest.raises(ValueError):
            user_storage.save_appearance_setting('reduced_motion', 'yes')
    finally:
        for quantity in ('temperature', 'speed', 'pressure', 'design'):
            set_cmap(quantity, None)
        set_reduced_motion(False)


def test_output_directory_is_independent_of_launch_directory(user_locations, tmp_path, monkeypatch):
    roots = user_locations
    result = user_storage.optimization_output_dir()
    elsewhere = tmp_path / 'unrelated-launch'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert user_storage.optimization_output_dir() == result
    assert result == roots[QStandardPaths.StandardLocation.DocumentsLocation] / 'SJTU-TPMSHX-TM1' / 'opt_runs'
    assert result.is_dir()


def test_appearance_write_failure_does_not_replace_saved_choice(user_locations, monkeypatch):
    from tm1.applications.gui.ui.microanim import is_reduced_motion, set_reduced_motion
    from tm1.applications.gui.ui.theme import resolve_cmap, set_cmap

    assert user_storage.save_appearance_setting('theme', 'dark')
    try:
        assert set_cmap('pressure', 'cividis', persist=True) is True
        assert set_reduced_motion(True, persist=True) is True
        assert resolve_cmap('P_fA') == 'cividis'
        assert is_reduced_motion() is True

        def failed_write(*args):
            raise OSError('read only')

        monkeypatch.setattr(user_storage, '_write', failed_write)
        assert not user_storage.save_appearance_setting('theme', 'light')
        assert user_storage.load_appearance_settings()['theme'] == 'dark'
        assert set_cmap('pressure', 'turbo', persist=True) is False
        assert resolve_cmap('P_fA') == 'cividis'
        assert user_storage.load_appearance_settings()['cmap_pressure'] == 'cividis'
        assert set_reduced_motion(False, persist=True) is False
        assert is_reduced_motion() is True
        assert user_storage.load_appearance_settings()['reduced_motion'] == 'true'
        with pytest.raises(ValueError):
            user_storage.save_appearance_setting('accent', '#nothex')
    finally:
        set_cmap('pressure', None)
        set_reduced_motion(False)


@pytest.mark.parametrize('active_task', ['single_run', 'optimization', 'quick_design', 'workbench'])
def test_appearance_restart_keeps_live_tasks(win, active_task, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(os, 'execv', lambda *args: pytest.fail('replaced a live task'))
    with monkeypatch.context() as busy:
        busy.setattr(win.case_files, 'save_session', lambda: pytest.fail('restart must wait for tasks'))
        busy.setattr(getattr(win, active_task), 'is_idle', lambda: False)
        win.appearance.restart()
    assert len(messages) == 1


@pytest.mark.parametrize('frozen', [False, True])
def test_restart_saves_inputs_and_preserves_source_or_frozen_entry(win, frozen, monkeypatch):
    events = []
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, 'argv', ['/old/main.py', '--example-option'])
    monkeypatch.setattr(os, 'execv', lambda executable, args: events.append((executable, args)))
    monkeypatch.setattr(win.case_files, 'save_session', lambda: events.append('saved') or True)
    win.appearance.restart()
    from tm1.run_control.provenance import SOURCE_ROOT
    expected = [sys.executable] + ([] if frozen else [str(SOURCE_ROOT / 'main.py')]) + ['--example-option']
    assert events == ['saved', (sys.executable, expected)]


def test_restart_aborts_when_inputs_cannot_be_saved(win, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(os, 'execv', lambda *args: pytest.fail('replaced unsaved inputs'))
    with monkeypatch.context() as failed:
        failed.setattr(win.case_files, 'save_session', lambda: False)
        win.appearance.restart()
    assert len(messages) == 1


@pytest.mark.parametrize('active_task', ['single_run', 'optimization', 'quick_design', 'workbench'])
def test_workspace_switch_waits_for_active_tasks(win, active_task, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[-1]))
    with monkeypatch.context() as busy:
        busy.setattr(getattr(win, active_task), 'is_idle', lambda: False)
        busy.setattr(win.case_files, 'save_session', lambda: pytest.fail('workspace switch must wait for tasks'))
        win.case_files.switch_workspace('B')
    assert win.case_files.active_workspace == 'A'
    assert len(messages) == 1


def test_workspace_switch_keeps_unsaved_inputs_on_write_failure(win, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    with monkeypatch.context() as failed:
        failed.setattr(win.case_files, 'save_session', lambda: False)
        failed.setattr(win.case_files, 'invalidate_results_for_preset_load', lambda: pytest.fail('discarded unsaved input'))
        win.case_files.switch_workspace('B')
    assert win.case_files.active_workspace == 'A'
    assert len(messages) == 1


def test_preset_write_failure_is_reported_without_success_toast(win, monkeypatch):
    messages = []
    manager = win.case_files.store
    original = [{'name': 'old', 'line_edits': {'le_TinA': '440'}}]
    assert manager.save_user_presets(original)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('new', True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(win.history, 'rebuild_recent_menu', lambda: pytest.fail('presented an unsaved preset'))
    with monkeypatch.context() as failed:
        failed.setattr(manager, '_atomic_write_json', lambda *args: False)
        win.case_files.save_current_as_preset()
    assert manager.load_user_presets() == original
    assert len(messages) == 1
