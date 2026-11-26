"""Installed desktop state survives restarts without writing into its package."""
import json
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QInputDialog, QMessageBox

from sjtu_tpmshx.applications.gui.controllers import user_storage
from sjtu_tpmshx.applications.gui.controllers.session_manager import SessionManager
from tests.python.gui_workbench_support import win as win


def test_legacy_inputs_keep_the_original_package_directory():
    assert user_storage._LEGACY_PACKAGE_DIR == Path(__file__).resolve().parents[2] / 'sjtu_tpmshx'


@pytest.fixture
def user_locations(tmp_path, monkeypatch):
    roots = {
        QStandardPaths.StandardLocation.GenericDataLocation: tmp_path / 'data',
        QStandardPaths.StandardLocation.GenericConfigLocation: tmp_path / 'config',
        QStandardPaths.StandardLocation.DocumentsLocation: tmp_path / 'documents',
    }
    monkeypatch.setattr(QStandardPaths, 'writableLocation', lambda kind: str(roots[kind]))
    legacy = tmp_path / 'read-only-package'
    (legacy / 'ui' / 'mixins').mkdir(parents=True)
    monkeypatch.setattr(user_storage, '_LEGACY_PACKAGE_DIR', legacy)
    return legacy, roots


def test_existing_inputs_move_to_user_data_without_overwriting_either_source(user_locations):
    legacy, _ = user_locations
    saved_input = {'line_edits': {'le_TinA': '440.5'}}
    (legacy / '.last_session.json').write_text(json.dumps(saved_input))
    (legacy / '.workspace').write_text('B')
    (legacy / '.user_presets.json').write_text(json.dumps({'presets': [{'name': 'my case'}]}))
    (legacy / '.session_timeline.jsonl').write_text('{"Q": "42"}\n')
    (legacy / '.first_run_done').write_text('1')
    manager = SessionManager()
    assert manager.base_dir != legacy
    assert manager.load_session()['line_edits'] == saved_input['line_edits']
    assert manager.get_active_workspace() == 'B'
    assert manager.load_user_presets() == [{'name': 'my case'}]
    assert (manager.base_dir / '.session_timeline.jsonl').read_text() == '{"Q": "42"}\n'
    assert (manager.base_dir / '.first_run_done').read_text() == '1'
    assert manager.save_session({'line_edits': {'le_TinA': '450'}})
    assert SessionManager().load_session()['line_edits']['le_TinA'] == '450'
    assert json.loads((legacy / '.last_session.json').read_text()) == saved_input


def test_appearance_uses_user_read_write_location_without_legacy_scan(user_locations):
    legacy, _ = user_locations
    (legacy / '.theme').write_text('dark')
    old_menu = legacy / 'ui' / 'mixins' / '.theme'
    old_menu.write_text('light')
    os.utime(legacy / '.theme', (100, 100))
    os.utime(old_menu, (200, 200))
    assert user_storage.load_appearance_settings() == {}
    for name, value in {'theme': 'dark', 'density': 'cozy', 'accent': '#A1b2c3'}.items():
        assert user_storage.save_appearance_setting(name, value)
    assert user_storage.load_appearance_settings() == {
        'theme': 'dark', 'density': 'cozy', 'accent': '#A1b2c3'}
    assert old_menu.read_text() == 'light'
    assert not (legacy / '.density').exists()
    assert not (legacy / 'ui' / 'mixins' / '.accent').exists()


def test_colormap_and_reduced_motion_preferences_roundtrip_and_validate(user_locations):
    from sjtu_tpmshx.applications.gui.ui.microanim import (
        apply_saved_reduced_motion, is_reduced_motion, set_reduced_motion,
    )
    from sjtu_tpmshx.applications.gui.ui.theme import (
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
    _, roots = user_locations
    result = user_storage.optimization_output_dir()
    elsewhere = tmp_path / 'unrelated-launch'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert user_storage.optimization_output_dir() == result
    assert result == roots[QStandardPaths.StandardLocation.DocumentsLocation] / 'SJTU-TPMSHX-TM1' / 'opt_runs'
    assert result.is_dir()


def test_appearance_write_failure_does_not_replace_saved_choice(user_locations, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui.microanim import is_reduced_motion, set_reduced_motion
    from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap, set_cmap

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
        win._restart_for_appearance()
    assert len(messages) == 1


@pytest.mark.parametrize('frozen', [False, True])
def test_restart_saves_inputs_and_preserves_source_or_frozen_entry(win, frozen, monkeypatch):
    events = []
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, 'argv', ['/old/main.py', '--example-option'])
    monkeypatch.setattr(os, 'execv', lambda executable, args: events.append((executable, args)))
    monkeypatch.setattr(win.case_files, 'save_session', lambda: events.append('saved') or True)
    win._restart_for_appearance()
    expected = [sys.executable] + ([] if frozen else ['-m', 'sjtu_tpmshx.main']) + ['--example-option']
    assert events == ['saved', (sys.executable, expected)]


def test_restart_aborts_when_inputs_cannot_be_saved(win, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(os, 'execv', lambda *args: pytest.fail('replaced unsaved inputs'))
    with monkeypatch.context() as failed:
        failed.setattr(win.case_files, 'save_session', lambda: False)
        win._restart_for_appearance()
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
    monkeypatch.setattr(win, '_rebuild_recent_menu', lambda: pytest.fail('presented an unsaved preset'))
    with monkeypatch.context() as failed:
        failed.setattr(manager, '_atomic_write_json', lambda *args: False)
        win.case_files.save_current_as_preset()
    assert manager.load_user_presets() == original
    assert len(messages) == 1
