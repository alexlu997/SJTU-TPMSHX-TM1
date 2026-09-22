"""Installed desktop state survives restarts without writing into its package."""
import json
import os
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QInputDialog, QMessageBox

from sjtu_tpmshx.controllers import user_storage
from sjtu_tpmshx.controllers.session_manager import SessionManager
from sjtu_tpmshx.ui.mixins.appearance import AppearanceMixin
from sjtu_tpmshx.ui.mixins.session_presets import SessionPresetsMixin


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
    assert user_storage.save_appearance_setting('theme', 'dark')
    def failed_write(*args):
        raise OSError('read only')
    monkeypatch.setattr(user_storage, '_write', failed_write)
    assert not user_storage.save_appearance_setting('theme', 'light')
    assert user_storage.load_appearance_settings()['theme'] == 'dark'
    with pytest.raises(ValueError):
        user_storage.save_appearance_setting('accent', '#nothex')


@pytest.mark.parametrize('active_task', ['compute', 'optimization', 'quick_design'])
def test_appearance_restart_keeps_live_tasks(active_task, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(os, 'execv', lambda *args: pytest.fail('replaced a live task'))
    window = SimpleNamespace(_save_session=lambda: pytest.fail('restart must wait for tasks'))
    if active_task == 'compute':
        window.compute = SimpleNamespace(is_idle=lambda: False)
    elif active_task == 'optimization':
        window._opt_worker = object()
    else:
        window._qd_dialog = SimpleNamespace(_qd_worker=object())
    AppearanceMixin._restart_for_appearance(window)
    assert len(messages) == 1


@pytest.mark.parametrize('frozen', [False, True])
def test_restart_saves_inputs_and_preserves_source_or_frozen_entry(frozen, monkeypatch):
    events = []
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, 'argv', ['/old/main.py', '--example-option'])
    monkeypatch.setattr(os, 'execv', lambda executable, args: events.append((executable, args)))
    window = SimpleNamespace(_save_session=lambda: events.append('saved') or True)
    AppearanceMixin._restart_for_appearance(window)
    expected = [sys.executable] + ([] if frozen else ['-m', 'sjtu_tpmshx.main']) + ['--example-option']
    assert events == ['saved', (sys.executable, expected)]


def test_restart_aborts_when_inputs_cannot_be_saved(monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(os, 'execv', lambda *args: pytest.fail('replaced unsaved inputs'))
    AppearanceMixin._restart_for_appearance(SimpleNamespace(_save_session=lambda: False))
    assert len(messages) == 1


def test_workspace_switch_keeps_unsaved_inputs_on_write_failure(monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    window = SimpleNamespace(
        _WORKSPACES=('A', 'B', 'C'), _active_workspace='A',
        _save_session=lambda: False,
        _invalidate_results_for_preset_load=lambda: pytest.fail('discarded unsaved input'))
    SessionPresetsMixin._switch_workspace(window, 'B')
    assert window._active_workspace == 'A'
    assert len(messages) == 1


def test_preset_write_failure_is_reported_without_success_toast(tmp_path, monkeypatch):
    messages = []
    manager = SessionManager(base_dir=tmp_path)
    original = [{'name': 'old', 'line_edits': {'le_TinA': '440'}}]
    assert manager.save_user_presets(original)
    monkeypatch.setattr(manager, '_atomic_write_json', lambda *args: False)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('new', True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    class Window(SessionPresetsMixin):
        sm = manager

        def _capture_current_preset(self, name):
            return {'name': name, 'line_edits': {'le_TinA': '450'}}

        def _rebuild_recent_menu(self):
            pytest.fail('presented an unsaved preset')
    Window()._save_current_as_preset()
    assert manager.load_user_presets() == original
    assert len(messages) == 1
