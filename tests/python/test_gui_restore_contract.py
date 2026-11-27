"""Input restores and persistence share one explicit state boundary."""
import base64
import json
import zlib

import pytest

from sjtu_tpmshx.applications.gui.controllers.session_manager import SessionManager
from tests.python.gui_io_support import win as win


@pytest.fixture(autouse=True)
def isolated_state(win, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(win.case_files, 'store', SessionManager(base_dir=tmp_path, parent=win))
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *args: QMessageBox.StandardButton.Cancel)
    win.case_files.active_workspace = 'A'
    win._temp_unit = 'K'
    win._sync_temp_unit_labels()
    win._apply_shanghai_defaults()
    yield
    win._apply_shanghai_defaults()


@pytest.mark.parametrize('route', ['named', 'recent', 'share', 'session'])
def test_legacy_full_restore_never_inherits_previous_zones(win, monkeypatch, route):
    from PySide6.QtWidgets import QInputDialog
    legacy = win.case_files.capture_current_preset('old named design')
    del legacy['zone_inputs']
    legacy['checks']['chk_zones'] = True
    current = win.case_files.capture_current_preset('current zones')
    current['checks']['chk_zones'] = True
    current['zone_inputs']['rows'] = [['0', '0.5', '8', '0.3'], ['0.5', '1', '6', '0.3']]
    win.case_files.apply_user_preset(current)
    if route == 'named':
        win.history.load_user_preset(legacy)
    elif route == 'recent':
        win.history.load_recent_run({'preset': legacy, 'preset_source': 'old named design'})
    elif route == 'share':
        token = 'TPMSHX::' + base64.urlsafe_b64encode(zlib.compress(json.dumps(legacy).encode())).decode()
        monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: (token, True))
        win.history.load_reproducible_link()
    else:
        assert win.case_files.store.save_session(legacy)
        win.case_files.restore_session()
    assert not win.chk_zones.isChecked()
    assert win.zone_table.rowCount() == 0
    assert win._pareto_x_decision is None


@pytest.mark.parametrize('route', ['reset', 'builtin', 'workspace'])
def test_default_restore_clears_optimization_conditions(win, route):
    from tests.python.optimization_support import condition
    preset = win.case_files.capture_current_preset('A')
    preset['optimization_conditions'] = [condition()]
    from tests.python.test_mass_design import requirements
    preset['optimization_mass_requirements'] = requirements(('one',))
    win.case_files.apply_user_preset(preset)
    if route == 'workspace':
        win.case_files.switch_workspace('B')
    elif route == 'builtin':
        win.case_files.load_named_preset('Shanghai (2D Gyroid)')
    else:
        win._apply_shanghai_defaults()
    assert win.optimization.conditions is None and win.optimization.mass_requirements is None


def test_valid_restore_refreshes_error_state_without_recording_history(win):
    valid = win.case_files.capture_current_preset('valid')
    win.le_L.setText('-1')
    win.le_L.editingFinished.emit()
    assert win.le_L.property('inpError') == 'true'
    history = list(win._field_history['le_L'])
    win.history.load_user_preset(valid)
    assert win.le_L.property('inpError') == 'false'
    assert win.single_run.validate_inputs()
    assert list(win._field_history['le_L']) == history


@pytest.mark.parametrize('unit,text', [
    ('K', '0'), ('C', '-273.15'),
    ('K', '0 K'), ('C', '0 K'),
    ('K', '-273.15 degC'), ('C', '-273.15 degC'),
    ('C', '-0.001 K'), ('C', '(-273.15)'),
])
def test_inlet_keeps_rejected_temperature_on_refresh(win, unit, text):
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window

    if unit == 'C':
        win._toggle_temp_unit()
    field = win.le_TinA
    field.setText(text)
    for validate in (field.editingFinished.emit, win._refresh_field_validation):
        validate()
        assert field.property('inpError') == 'true'
        assert 'Must be above 0 K' in field.toolTip()
        assert field.text() == text
    with pytest.raises(ValueError, match=r'Inlet Temp A|fluid_A\.T_in_K'):
        config_from_window(win, strict=True).validate()


@pytest.mark.parametrize('unit,text,display,kelvin', [
    ('K', '0.05 K', '0.05', 0.05), ('C', '0.05 K', '-273.1', 0.05),
    ('K', '300 K', '300', 300), ('C', '300 K', '26.85', 300),
])
def test_inlet_keeps_valid_temperature_format_and_value(win, unit, text, display, kelvin):
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window

    if unit == 'C':
        win._toggle_temp_unit()
    field = win.le_TinB
    field.setText(text)
    field.editingFinished.emit()
    win._refresh_field_validation()
    assert field.property('inpError') == 'false'
    assert field.text() == display
    assert config_from_window(win, strict=True).fluid_B.T_in_K == pytest.approx(kelvin)


@pytest.mark.parametrize('unit,zero,normal,switched', [
    ('K', '(0)', '150 * 2', '26.85'),
    ('C', '(-273.15)', '25 + 1.85', '300'),
])
def test_unit_switch_keeps_rejected_temperature_expression_at_absolute_zero(win, unit, zero, normal, switched):
    if unit == 'C':
        win._toggle_temp_unit()
    win.le_TinA.setText(zero)
    win.le_TinA.editingFinished.emit()
    win.le_TinB.setText(normal)
    win._toggle_temp_unit()
    assert win.le_TinB.text() == switched
    assert win.le_TinB.property('inpError') == 'false'
    assert win._temp_to_K(win.le_TinB) == 300
    assert win.le_TinA.property('inpError') == 'true'
    assert 'Must be above 0 K' in win.le_TinA.toolTip()
    assert win._temp_to_K(win.le_TinA) == 0


@pytest.mark.parametrize('side,unit,zero', [('A', 'K', '(0)'), ('B', 'C', '(-273.15)')])
def test_save_config_preserves_file_for_rejected_switched_inlet(win, monkeypatch, tmp_path, side, unit, zero):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    path = tmp_path / 'inlets.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda parent, title, text: errors.append(text))
    if unit == 'C':
        win._toggle_temp_unit()
    field = getattr(win, 'le_Tin' + side)
    field.setText('0.05 K')
    field.editingFinished.emit()
    kelvin = win._temp_to_K(field)
    assert win.case_files.save_config()
    original = path.read_bytes()

    field.setText(zero)
    win._toggle_temp_unit()
    assert field.property('inpError') == 'true'
    assert not win.case_files.save_config()
    assert 'Must be above 0 K' in errors[-1]
    assert path.read_bytes() == original
    assert win.case_files.load_config_path(path)
    assert win._temp_unit == unit
    assert win._temp_to_K(field) == kelvin > 0


@pytest.mark.parametrize('route', ['config', 'session'])
@pytest.mark.parametrize('side,unit,zero', [('A', 'K', 0), ('B', 'C', -273.15)])
def test_numeric_zero_in_saved_unit_preserves_active_design(win, tmp_path, side, unit, zero, route):
    from PySide6.QtWidgets import QApplication

    if unit == 'C':
        win._toggle_temp_unit()
    saved = win.case_files.capture_current_preset('invalid inlet')
    saved['line_edits']['le_Tin' + side] = zero
    saved['line_edits']['le_L'] = '0.333'
    win._toggle_temp_unit()
    before = win.case_files.capture_current_preset('active')
    if route == 'config':
        path = tmp_path / 'invalid.json'
        path.write_text(json.dumps({'config_format': 1, 'preset': saved}))
        assert not win.case_files.load_config_path(path)
    else:
        assert win.case_files.store.save_session(saved)
        win.case_files.restore_session()
        QApplication.processEvents()
    assert win.case_files.capture_current_preset('active') == before


@pytest.mark.parametrize('content', ['{"presets": {"old": 1}}', '{"presets": [null]}', '{broken'])
def test_rejected_preset_library_is_preserved_before_next_save(win, content):
    path = win.case_files.store.presets_path()
    path.write_text(content)
    assert win.case_files.store.load_user_presets() == []
    win.history.rebuild_recent_menu()
    assert win.case_files.store.save_user_presets([win.case_files.capture_current_preset('new')])
    backups = list(path.parent.glob(path.name + '.corrupt-*'))
    assert len(backups) == 1
    assert backups[0].read_text() == content


def test_failed_preset_library_backup_blocks_gui_overwrite(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    path = win.case_files.store.presets_path()
    raw = b'{broken but recoverable'
    path.write_bytes(raw)
    original = win.case_files.store._quarantine_corrupt
    monkeypatch.setattr(win.case_files.store, '_quarantine_corrupt', lambda path: None)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('new', True))
    win.case_files.save_current_as_preset()
    assert path.read_bytes() == raw
    monkeypatch.setattr(win.case_files.store, '_quarantine_corrupt', original)
    win.case_files.save_current_as_preset()
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
    button, label = ((win.btn_save, '保存当前为预设…') if route == 'save_menu'
                     else (win.btn_recent, '保存当前为预设…'))
    next(a for a in button.menu().actions() if a.text() == label).trigger()
    path = win.case_files.store.presets_path()
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
    action = next(a for a in win.btn_save.menu().actions() if a.text() == '保存当前为预设…')
    action.trigger()
    win.le_L.setText(text)
    next(a for a in win.btn_save.menu().actions() if a.text() == '保存当前为预设…').trigger()
    presets = json.loads(win.case_files.store.presets_path().read_text())['presets']
    assert len(presets) == 1
    assert presets[0]['line_edits']['le_L'] == '0.2'
    assert win.dialogs.last_notice == 'Saved preset: saved design.'
    win.le_L.setText('0.3')
    next(a for a in win.btn_recent.menu().actions() if '★ saved design' in a.text()).trigger()
    assert win.le_L.text() == '0.2'


@pytest.mark.parametrize('text', ['200 mm', '1/5'])
def test_session_save_commits_valid_expression_before_capture(win, text):
    win.le_L.setText(text)
    assert win.case_files.save_session()
    assert json.loads(win.case_files.store.session_path().read_text())['line_edits']['le_L'] == '0.2'
    win._apply_shanghai_defaults()
    win.case_files.restore_session()
    assert win.le_L.text() == '0.2'


def test_invalid_session_draft_does_not_replace_previous_file(win):
    assert win.case_files.save_session()
    original = win.case_files.store.session_path().read_bytes()
    win.le_L.setText('not a number')
    assert not win.case_files.save_session()
    assert win.case_files.store.session_path().read_bytes() == original
    assert not win.close()  # The existing warning defaults to Cancel.
    assert win.case_files.store.session_path().read_bytes() == original


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
            win.case_files.switch_workspace('B')
        elif route == 'partial':
            win.case_files.apply_user_preset({'line_edits': {'le_L': '0.211'}}, partial=True)
        else:
            win.case_files.load_named_preset('Shanghai (2D Gyroid)')
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
    ('K', 'le_pipeB_out_z_w', '0.021', '0.021 m'),
    ('K', 'le_mass_flowA', '0.02', '0.02 kg/s'),
    ('K', 'le_ks', '16', '16 W/(m·K)'),
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


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
def test_field_menu_uses_current_theme_colors(win, monkeypatch, theme_name):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent, QPalette
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.applications.gui.ui.theme import _THEMES

    colors = _THEMES[theme_name]
    monkeypatch.setattr(win.theme, 'palette', lambda: colors)
    observed = []

    def inspect_menu():
        menu = QApplication.activePopupWidget()
        try:
            palette = menu.palette()
            observed.append((palette.color(QPalette.ColorRole.Window).name(),
                             palette.color(QPalette.ColorRole.WindowText).name()))
        finally:
            menu.close()

    QTimer.singleShot(0, inspect_menu)
    win.le_L.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(), QPoint()))
    assert observed == [(colors['card_bg'], colors['fg'])]


@pytest.mark.parametrize('route', ['named', 'recent', 'scrub', 'session'])
def test_restore_uses_its_own_source_name(win, route):
    preset = win.case_files.capture_current_preset('Recent @ 12:00' if route != 'named' else 'custom source')
    entry = {'preset': preset, 'preset_source': 'custom source'}
    if route == 'named':
        win.history.load_user_preset(preset)
    elif route == 'recent':
        win.history.load_recent_run(entry)
    elif route == 'scrub':
        win.history.recent_runs.clear()
        win.history.recent_runs.append(entry)
        win.shortcuts._scrub_idx = -1
        win.shortcuts.scrub_recent(1)
    else:
        preset['preset_source'] = 'custom source'
        assert win.case_files.store.save_session(preset)
        win.case_files.restore_session()
    assert win.case_files.active_preset_name == 'custom source'


@pytest.mark.parametrize('field,text,expected', [
    ('le_L', '200 mm', '0.2'), ('le_L', '1/5', '0.2'),
    # Full-precision unit conversion; persistence must behave exactly like a
    # normal editingFinished commit.
    ('le_TinA', '25 C', '298.15'),
])
def test_close_with_focused_expression_restores_complete_session(
        monkeypatch, tmp_path, field, text, expected):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.applications.gui.ui.main_window import Main_Menu
    from sjtu_tpmshx.applications.gui.ui.shell_dialogs import ShellDialogs
    from sjtu_tpmshx.applications.gui.ui.ui_builders import reveal_parameter
    original = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
        lambda self, base_dir=None, parent=None: original(self, base_dir=tmp_path, parent=parent))
    monkeypatch.setattr(Main_Menu, '_schedule_tpms_geometry_prewarm', lambda self: None)
    monkeypatch.setattr(ShellDialogs, 'maybe_show_onboarding', lambda self: None)
    window = Main_Menu()
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    window.le_H.setText('0.111')
    edit = getattr(window, field)
    reveal_parameter(window, edit)
    QApplication.processEvents()
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
    path = win.case_files.store.presets_path()
    original = b'{"presets": [{"name": "old design"}]}'
    path.write_bytes(original)
    real_open = builtins.open
    def unreadable(file, mode='r', *args, **kwargs):
        if Path(file) == path and mode == 'r':
            raise PermissionError('injected read failure')
        return real_open(file, mode, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', unreadable)
        assert win.case_files.store.load_user_presets() == []
    assert win.case_files.store.save_user_presets([win.case_files.capture_current_preset('new design')])
    assert [p.read_bytes() for p in path.parent.glob(path.name + '.corrupt-*')] == [original]


def test_malformed_library_members_do_not_block_window_initialization(monkeypatch, tmp_path):
    from sjtu_tpmshx.applications.gui.ui.main_window import Main_Menu
    from sjtu_tpmshx.applications.gui.ui.shell_dialogs import ShellDialogs
    path = SessionManager(base_dir=tmp_path).presets_path()
    original = b'{"presets": [null]}'
    path.write_bytes(original)
    init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
        lambda self, base_dir=None, parent=None: init(self, base_dir=tmp_path, parent=parent))
    monkeypatch.setattr(Main_Menu, '_schedule_tpms_geometry_prewarm', lambda self: None)
    monkeypatch.setattr(ShellDialogs, 'maybe_show_onboarding', lambda self: None)
    window = Main_Menu()
    try:
        assert window.btn_recent.menu() is not None
        assert [p.read_bytes() for p in tmp_path.glob(path.name + '.corrupt-*')] == [original]
    finally:
        window.close()
        window.deleteLater()


def test_mass_requirements_survive_session_and_reject_mismatched_conditions(win):
    from tests.python.optimization_support import condition
    from tests.python.test_mass_design import requirements
    preset = win.case_files.capture_current_preset('mass design')
    preset.update(optimization_conditions=[condition()],
                  optimization_mass_requirements=requirements(('one',)),
                  optimization_bounds={'L': [7., 7.], 't': [.3, .6]})
    win.case_files.apply_user_preset(preset)
    assert win.case_files.store.save_session(win.case_files.capture_current_preset('mass design'))
    win._apply_shanghai_defaults()
    win.case_files.restore_session()
    assert win.optimization.mass_requirements == preset['optimization_mass_requirements']
    assert win.optimization.method.currentData() == 'qlognei'
    assert win.case_files.capture_current_preset('bounds')['optimization_bounds'] == preset['optimization_bounds']
    assert '27 个变量' in win.optimization.field_layout.text()
    before = win.case_files.capture_current_preset('before')
    preset['optimization_mass_requirements']['conditions']['wrong-id'] = (
        preset['optimization_mass_requirements']['conditions'].pop('one'))
    with pytest.raises(ValueError, match='condition IDs'):
        win.case_files.apply_user_preset(preset)
    assert win.case_files.capture_current_preset('before') == before


@pytest.mark.parametrize('bounds', [None, {'L': [], 't': [.3, .6]},
    {'L': [7., 7.], 't': [.6, .3]}, {'L': [7., float('nan')], 't': [.3, .6]}])
def test_invalid_optimization_bounds_do_not_change_inputs(win, bounds):
    before = win.case_files.capture_current_preset('before')
    damaged = dict(before, optimization_bounds=bounds)
    with pytest.raises(ValueError):
        win.case_files.apply_user_preset(damaged)
    assert win.case_files.capture_current_preset('before') == before
