"""Input restores and persistence share one explicit state boundary."""
import base64
import json
import zlib

import pytest

from sjtu_tpmshx.controllers.session_manager import SessionManager
from sjtu_tpmshx.tests.gui_io_support import win as win


@pytest.fixture(autouse=True)
def isolated_state(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(win, 'sm', SessionManager(base_dir=tmp_path, parent=win))
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *args: QMessageBox.StandardButton.Cancel)
    win._active_workspace = 'A'
    win._temp_unit = 'K'
    win._sync_temp_unit_labels()
    win._apply_shanghai_defaults()
    yield
    win._apply_shanghai_defaults()


@pytest.mark.parametrize('route', ['named', 'recent', 'share', 'session'])
def test_legacy_full_restore_never_inherits_previous_zones(win, monkeypatch, route):
    from PySide6.QtWidgets import QInputDialog
    legacy = win._capture_current_preset('old named design')
    del legacy['zone_inputs']
    legacy['checks']['chk_zones'] = True
    current = win._capture_current_preset('current zones')
    current['checks']['chk_zones'] = True
    current['zone_inputs']['rows'] = [['0', '0.5', '8', '0.3'], ['0.5', '1', '6', '0.3']]
    win._apply_user_preset(current)
    if route == 'named':
        win._load_user_preset(legacy)
    elif route == 'recent':
        win._load_recent_run({'preset': legacy, 'preset_source': 'old named design'})
    elif route == 'share':
        token = 'TPMSHX::' + base64.urlsafe_b64encode(zlib.compress(json.dumps(legacy).encode())).decode()
        monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: (token, True))
        win._load_reproducible_link()
    else:
        assert win.sm.save_session(legacy)
        win._restore_session()
    assert not win.chk_zones.isChecked()
    assert win.zone_table.rowCount() == 0
    assert win._pareto_x_decision is None


@pytest.mark.parametrize('route', ['reset', 'builtin', 'workspace'])
def test_default_restore_clears_optimization_conditions(win, route):
    from sjtu_tpmshx.tests.test_optimize_panel_wiring import condition
    preset = win._capture_current_preset('A')
    preset['optimization_conditions'] = [condition()]
    win._apply_user_preset(preset)
    if route == 'workspace':
        win._switch_workspace('B')
    elif route == 'builtin':
        win._load_named_preset('Shanghai (2D Gyroid)')
    else:
        win._apply_shanghai_defaults()
    assert win._opt_conditions is None


def test_valid_restore_refreshes_error_state_without_recording_history(win):
    valid = win._capture_current_preset('valid')
    win.le_L.setText('-1')
    win.le_L.editingFinished.emit()
    assert win.le_L.property('inpError') == 'true'
    history = list(win._field_history['le_L'])
    win._load_user_preset(valid)
    assert win.le_L.property('inpError') == 'false'
    assert win._validate_inputs_preflight()
    assert list(win._field_history['le_L']) == history


@pytest.mark.parametrize('content', ['{"presets": {"old": 1}}', '{"presets": [null]}', '{broken'])
def test_rejected_preset_library_is_preserved_before_next_save(win, content):
    path = win.sm.presets_path()
    path.write_text(content)
    assert win.sm.load_user_presets() == []
    win._rebuild_recent_menu()
    assert win.sm.save_user_presets([win._capture_current_preset('new')])
    backups = list(path.parent.glob(path.name + '.corrupt-*'))
    assert len(backups) == 1
    assert backups[0].read_text() == content


def test_failed_preset_library_backup_blocks_gui_overwrite(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    path = win.sm.presets_path()
    raw = b'{broken but recoverable'
    path.write_bytes(raw)
    original = win.sm._quarantine_corrupt
    monkeypatch.setattr(win.sm, '_quarantine_corrupt', lambda path: None)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('new', True))
    win._save_current_as_preset()
    assert path.read_bytes() == raw
    monkeypatch.setattr(win.sm, '_quarantine_corrupt', original)
    win._save_current_as_preset()
    assert json.loads(path.read_text())['presets'][0]['name'] == 'new'
    assert [p.read_bytes() for p in path.parent.glob(path.name + '.corrupt-*')] == [raw]


@pytest.mark.parametrize('route', ['save_menu', 'recent_menu'])
@pytest.mark.parametrize('invalid', ['not a number', '-1'])
def test_named_preset_rejects_invalid_draft_before_replacing_saved_entry(
        win, monkeypatch, route, invalid):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    messages = []
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('saved design', True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: messages.append(a[1:3]))
    button, label = ((win.btn_save, '保存为预设…') if route == 'save_menu'
                     else (win.btn_recent, '保存当前为预设…'))
    next(a for a in button.menu().actions() if a.text() == label).trigger()
    path = win.sm.presets_path()
    previous = path.read_bytes()
    win.le_L.setText(invalid)
    win.le_L.editingFinished.emit()
    assert win.le_L.property('inpError') == 'true'
    # Saving rebuilds the recent menu, so resolve its current QAction again.
    next(a for a in button.menu().actions() if a.text() == label).trigger()
    assert path.read_bytes() == previous
    assert messages == [('预设未保存', 'Invalid numeric field: le_L')]
    next(a for a in win.btn_recent.menu().actions() if '★ saved design' in a.text()).trigger()
    assert win.le_L.text() == '0.182'
    assert win.le_L.property('inpError') == 'false'
    assert len(messages) == 1


@pytest.mark.parametrize('text', ['200 mm', '1/5'])
def test_named_preset_commits_expression_and_replaces_valid_entry(win, monkeypatch, text):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('saved design', True))
    action = next(a for a in win.btn_save.menu().actions() if a.text() == '保存为预设…')
    action.trigger()
    win.le_L.setText(text)
    action.trigger()
    presets = json.loads(win.sm.presets_path().read_text())['presets']
    assert len(presets) == 1
    assert presets[0]['line_edits']['le_L'] == '0.2'
    assert win.statusBar().currentMessage() == 'Saved preset: saved design.'
    win.le_L.setText('0.3')
    next(a for a in win.btn_recent.menu().actions() if '★ saved design' in a.text()).trigger()
    assert win.le_L.text() == '0.2'


@pytest.mark.parametrize('text', ['200 mm', '1/5'])
def test_session_save_commits_valid_expression_before_capture(win, text):
    win.le_L.setText(text)
    assert win._save_session()
    assert json.loads(win.sm.session_path().read_text())['line_edits']['le_L'] == '0.2'
    win._apply_shanghai_defaults()
    win._restore_session()
    assert win.le_L.text() == '0.2'


def test_invalid_session_draft_does_not_replace_previous_file(win):
    assert win._save_session()
    original = win.sm.session_path().read_bytes()
    win.le_L.setText('not a number')
    assert not win._save_session()
    assert win.sm.session_path().read_bytes() == original
    assert not win.close()  # The existing warning defaults to Cancel.
    assert win.sm.session_path().read_bytes() == original


@pytest.mark.parametrize('route', ['unit', 'workspace', 'partial', 'builtin'])
def test_restore_checkpoint_drops_old_undo_and_redo(win, route):
    win._undo_stack.clear()
    if route == 'unit':
        win.le_TinA.setText('430')
        win.le_TinA.editingFinished.emit()
        win._toggle_temp_unit()
        expected = win.le_TinA.text()
        win.le_TinA.setText('160')
        win.le_TinA.editingFinished.emit()
        win._undo_stack.undo()
        assert win.le_TinA.text() == expected
        assert win._temp_to_K(win.le_TinA) == pytest.approx(430)
    else:
        win.le_L.setText('0.310')
        win.le_L.editingFinished.emit()
        win._undo_stack.undo()  # A redo command must not survive either.
        if route == 'workspace':
            win._switch_workspace('B')
        elif route == 'partial':
            win._apply_user_preset({'line_edits': {'le_L': '0.211'}}, partial=True)
        else:
            win._load_named_preset('Shanghai (2D Gyroid)')
        expected = win.le_L.text()
        assert win._undo_stack.count() == 0
        win._undo_stack.redo()
        assert win.le_L.text() == expected


def test_unit_switch_discards_only_untyped_temperature_history(win):
    win.le_TinA.setText('430')
    win.le_TinA.editingFinished.emit()
    win.le_L.setText('0.211')
    win.le_L.editingFinished.emit()
    length_history = list(win._field_history['le_L'])
    win._toggle_temp_unit()
    assert not win._field_history.get('le_TinA')
    assert not win._field_history.get('le_TinB')
    assert list(win._field_history['le_L']) == length_history


@pytest.mark.parametrize('unit,field,text,expected', [
    ('K', 'le_TinA', '430', '430 K'),
    ('C', 'le_TinA', '156.85', '156.85 °C'),
    ('K', 'le_Nx', '20', '20'),
    ('K', 'le_L', '0.2', '0.2 m'),
    ('K', 'le_Lcell', '7', '7 mm'),
])
def test_copy_menu_uses_display_units(win, unit, field, text, expected):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication
    win._temp_unit = unit
    le = getattr(win, field)
    le.setText(text)
    selected = []
    def choose():
        menu = QApplication.activePopupWidget()
        actions = menu.actions()
        try:
            action = next(a for a in actions if a.text().startswith('Copy with unit'))
            selected.append(action.text())
            action.trigger()
        finally:
            menu.close()
    QTimer.singleShot(0, choose)
    le.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(), QPoint()))
    assert selected
    assert QApplication.clipboard().text() == expected


@pytest.mark.parametrize('route', ['named', 'recent', 'scrub', 'session'])
def test_restore_uses_its_own_source_name(win, route):
    preset = win._capture_current_preset('Recent @ 12:00' if route != 'named' else 'custom source')
    entry = {'preset': preset, 'preset_source': 'custom source'}
    if route == 'named':
        win._load_user_preset(preset)
    elif route == 'recent':
        win._load_recent_run(entry)
    elif route == 'scrub':
        win._recent_runs = [entry]
        win._scrub_idx = -1
        win._scrub_recent(1)
    else:
        preset['preset_source'] = 'custom source'
        assert win.sm.save_session(preset)
        win._restore_session()
    assert win._active_preset_name == 'custom source'


@pytest.mark.parametrize('field,text,expected', [
    ('le_L', '200 mm', '0.2'), ('le_L', '1/5', '0.2'),
    # Match the existing four-significant-digit unit formatter; persistence
    # must behave exactly like a normal editingFinished commit.
    ('le_TinA', '25 C', '298.1'),
])
def test_close_with_focused_expression_restores_complete_session(
        monkeypatch, tmp_path, field, text, expected):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.main import Main_Menu
    original = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
        lambda self, base_dir=None, parent=None: original(self, base_dir=tmp_path, parent=parent))
    monkeypatch.setattr(Main_Menu, '_schedule_tpms_geometry_prewarm', lambda self: None)
    monkeypatch.setattr(Main_Menu, '_maybe_show_onboarding', lambda self: None)
    window = Main_Menu()
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    window.le_H.setText('0.111')
    edit = getattr(window, field)
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, text)
    assert QApplication.focusWidget() is edit
    assert window.close()
    restored = Main_Menu()
    try:
        assert getattr(restored, field).text() == expected
        assert restored.le_H.text() == '0.111'
        assert not list(tmp_path.glob('*.corrupt-*'))
    finally:
        restored.close()
        restored.deleteLater()
        window.deleteLater()


def test_unreadable_library_is_preserved_before_replacement(win, monkeypatch):
    import builtins
    from pathlib import Path
    path = win.sm.presets_path()
    original = b'{"presets": [{"name": "old design"}]}'
    path.write_bytes(original)
    real_open = builtins.open
    def unreadable(file, mode='r', *args, **kwargs):
        if Path(file) == path and mode == 'r':
            raise PermissionError('injected read failure')
        return real_open(file, mode, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', unreadable)
        assert win.sm.load_user_presets() == []
    assert win.sm.save_user_presets([win._capture_current_preset('new design')])
    assert [p.read_bytes() for p in path.parent.glob(path.name + '.corrupt-*')] == [original]


def test_malformed_library_members_do_not_block_window_initialization(monkeypatch, tmp_path):
    from sjtu_tpmshx.main import Main_Menu
    path = SessionManager(base_dir=tmp_path).presets_path()
    original = b'{"presets": [null]}'
    path.write_bytes(original)
    init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
        lambda self, base_dir=None, parent=None: init(self, base_dir=tmp_path, parent=parent))
    monkeypatch.setattr(Main_Menu, '_schedule_tpms_geometry_prewarm', lambda self: None)
    monkeypatch.setattr(Main_Menu, '_maybe_show_onboarding', lambda self: None)
    window = Main_Menu()
    try:
        assert window.btn_recent.menu() is not None
        assert [p.read_bytes() for p in tmp_path.glob(path.name + '.corrupt-*')] == [original]
    finally:
        window.close()
        window.deleteLater()
