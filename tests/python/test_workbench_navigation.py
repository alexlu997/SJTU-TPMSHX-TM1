"""Real Qt checks for parameter storage and reversible canvas focus."""
import pytest

from sjtu_tpmshx.data_types.compute_result import ComputeResult

pytest.importorskip('PySide6')

from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from tests.python.gui_workbench_support import win as win  # noqa: E402


def test_workbench_teardown_destroys_window_and_hidden_field_selector(tmp_path, monkeypatch):
    import weakref
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    lifecycle = win.__wrapped__(tmp_path, monkeypatch)
    window = next(lifecycle)
    field = weakref.ref(window.combo_2d_field)
    try:
        with pytest.raises(StopIteration):
            next(lifecycle)
        assert (isValid(window), field() is not None and isValid(field())) == (False, False)
    finally:
        if isValid(window):
            assert window.close()
            window.deleteLater()
        if field() is not None and isValid(field()) and field().parent() is None:
            field().deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_workbench_teardown_preserves_window_if_close_is_declined(tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QMessageBox
    from shiboken6 import isValid

    lifecycle = win.__wrapped__(tmp_path, monkeypatch)
    window = next(lifecycle)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(window.case_files, 'save_session', lambda: False)
            patch.setattr(QMessageBox, 'warning', lambda *a: QMessageBox.StandardButton.Cancel)
            with pytest.raises(AssertionError, match='workbench window refused to close'):
                next(lifecycle)
            assert isValid(window) and isValid(window.combo_2d_field)
            assert window.isEnabled()
    finally:
        if isValid(window):
            assert window.close()
            field = window.combo_2d_field
            window.deleteLater()
            if field.parent() is None:
                field.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_unified_boundary_sides_contain_fluid_and_port_bands(win):
    for side in ('A', 'B'):
        page = win._fluid_side_pages[side]
        assert page.isAncestorOf(win._ia_sections[f'fluid_{side.lower()}'])
        assert page.isAncestorOf(win._ia_sections[f'pipe_{side.lower()}'])


def test_fit_view_targets_the_active_optimization_volume(win, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from sjtu_tpmshx.applications.gui.ui.builders_canvas import canvas_zoom_reset

    main_panel, optimization_panel = (SimpleNamespace(
        fit_view=Mock(), cleanup=Mock(), color_range_state=lambda: {'mode': 'global', 'ranges': {}}) for _ in range(2))
    monkeypatch.setattr(win, 'canvas_3d', main_panel)
    monkeypatch.setattr(win.optimization, 'volume_panel', optimization_panel)
    win.optimization.result_tabs.setCurrentWidget(win.optimization.volume_host)
    win.workbench.active_tab = 'pareto'
    canvas_zoom_reset(win)
    optimization_panel.fit_view.assert_called_once_with()
    main_panel.fit_view.assert_not_called()
    win.optimization.result_tabs.setCurrentWidget(win.optimization.pareto_canvas)
    canvas_zoom_reset(win)
    optimization_panel.fit_view.assert_called_once_with()
    win.workbench.active_tab = '3d'
    canvas_zoom_reset(win)
    main_panel.fit_view.assert_called_once_with()


def test_window_close_cleans_both_volume_plotters_and_their_popups(win):
    from types import MethodType, SimpleNamespace
    from unittest.mock import Mock
    from PySide6.QtWidgets import QDialog
    from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel

    panels = []
    popups = []
    for owner, name in ((win, 'canvas_3d'), (win.optimization, 'volume_panel')):
        popup = QDialog(win)
        popup.show()
        panel = SimpleNamespace(_popup_dialogs=[popup], _stop_camera_tween=Mock(),
                                plotter=Mock(), color_range_state=lambda: {'mode': 'global', 'ranges': {}})
        panel.cleanup = MethodType(ThreeDVisPanel.cleanup, panel)
        setattr(owner, name, panel)
        panels.append(panel)
        popups.append(popup)
    win.close()
    for panel, popup in zip(panels, popups):
        panel.plotter.close.assert_called_once_with()
        panel._stop_camera_tween.assert_called_once_with()
        assert panel._popup_dialogs == [] and not popup.isVisible()


def test_appearance_settings_toggle_units_theme_and_reduced_motion(win, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui.microanim import is_reduced_motion, set_reduced_motion
    from sjtu_tpmshx.applications.gui.ui.theme import get_theme_name, set_theme

    original_theme = get_theme_name()
    original_unit, inlet = win._temp_unit, float(win.le_TinA.text())
    win._toggle_temp_unit()
    expected_unit = 'C' if original_unit == 'K' else 'K'
    assert win._temp_unit == expected_unit
    assert win.le_TinA.unit() == ('°C' if expected_unit == 'C' else 'K')
    assert float(win.le_TinA.text()) == pytest.approx(
        inlet - 273.15 if expected_unit == 'C' else inlet + 273.15, abs=.005)
    win._toggle_temp_unit()
    assert float(win.le_TinA.text()) == pytest.approx(inlet, abs=.005)

    restart_notices = []
    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.shell_appearance.save_appearance_setting',
                        lambda *_: True)
    monkeypatch.setattr(win.appearance, 'offer_restart', restart_notices.append)
    try:
        win.appearance.toggle_theme()
        assert get_theme_name() != original_theme
        assert restart_notices
    finally:
        set_theme(original_theme)

    monkeypatch.setattr(
        'sjtu_tpmshx.applications.gui.controllers.user_storage.save_appearance_setting',
        lambda *_: True,
    )
    prev_motion = is_reduced_motion()
    try:
        assert win.appearance.set_reduced_motion(True)
        assert is_reduced_motion() is True
        assert win.appearance.set_reduced_motion(False)
        assert is_reduced_motion() is False
    finally:
        set_reduced_motion(prev_motion)


def test_load_menu_workspace_switch_preserves_each_workspace_inputs(win):
    menu = win.history.build_load_menu()
    ws_b = next(a for a in menu.actions() if '工作区 B' in a.text())
    win.le_Nx.setText('37')
    ws_b.trigger()
    assert win.case_files.active_workspace == 'B'
    win.le_Nx.setText('45')
    menu = win.history.build_load_menu()
    ws_a = next(a for a in menu.actions() if '工作区 A' in a.text())
    ws_a.trigger()
    assert win.case_files.active_workspace == 'A'
    assert win.le_Nx.text() == '37'
    menu = win.history.build_load_menu()
    next(a for a in menu.actions() if '工作区 B' in a.text()).trigger()
    assert win.le_Nx.text() == '45'


def test_drawer_collapse_restore_preserves_fields_and_page(win):
    win._select_param_page(1)
    win.le_Nx.setText('37')
    QApplication.processEvents()

    win.btn_toggle_drawer.click()
    QApplication.processEvents()
    assert not win.appearance.is_drawer_open()
    assert not win.inspector_drawer.isVisibleTo(win)
    win.btn_toggle_drawer.click()
    QApplication.processEvents()
    assert win.appearance.is_drawer_open()
    assert win.inspector_drawer.isVisibleTo(win)
    assert win._param_page == 1
    assert win.le_Nx.text() == '37'

    win.appearance.toggle_drawer()
    assert not win.appearance.is_drawer_open()
    win.appearance.toggle_drawer()
    assert win.appearance.is_drawer_open()


@pytest.mark.parametrize('collapsed', [False, True])
def test_optimization_space_restores_drawer_state_and_keeps_active_cancel(win, collapsed, monkeypatch):
    win._select_param_page(1)
    win.le_Nx.setText('37')
    win.appearance.set_drawer_open(not collapsed)
    QApplication.processEvents()
    win.workbench.switch_tab('pareto')
    QApplication.processEvents()
    assert not win.inspector_drawer.isVisibleTo(win)
    assert not win._run_status_card.isVisibleTo(win)
    assert not win._result_view_switch.isVisibleTo(win)
    assert win.btn_focus_view.isVisibleTo(win)
    win.appearance.toggle_focus()
    win.appearance.toggle_focus()
    assert not win.inspector_drawer.isVisibleTo(win)
    with monkeypatch.context() as running:
        running.setattr(win.single_run, 'is_idle', lambda: False)
        win._run_status_card.start('2d')
        win.workbench.switch_tab('pareto')
        assert win._run_status_card.cancel_button.isVisibleTo(win)
    win._run_status_card.finish('cancelled', 0.)
    win.workbench.switch_tab('layout')
    QApplication.processEvents()
    assert win.inspector_drawer.isVisibleTo(win) == (not collapsed)
    assert win.appearance.is_drawer_open() == (not collapsed) and win._param_page == 1
    assert win.le_Nx.text() == '37'


def test_optimization_page_buttons_work_by_keyboard_and_public_edit_keeps_values(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win.le_Nx.setText('37')
    win.appearance.set_drawer_open(False)
    win.workbench.switch_tab('pareto')
    for index, key in enumerate(('config', 'running', 'result')):
        button = win.optimization.stage_pills[key]
        assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert win.optimization.stack.currentIndex() == index
    win.optimization.stack.setCurrentIndex(0)
    win.appearance.toggle_focus()
    win.optimization.edit_common_button.click()
    QApplication.processEvents()
    assert win.workbench.active_tab == 'layout' and not win.appearance.is_focused()
    assert win.inspector_drawer.isVisibleTo(win) and win.appearance.is_drawer_open()
    assert win.le_Nx.text() == '37'


@pytest.mark.parametrize('collapsed', [False, True])
@pytest.mark.parametrize('restore_tab', ['layout', 'pareto'])
def test_optimization_session_restores_saved_drawer_state(win, monkeypatch, collapsed, restore_tab):
    win.appearance.set_drawer_open(not collapsed, page_key='run')
    win.workbench.switch_tab('pareto')
    QApplication.processEvents()
    saved = {}
    monkeypatch.setattr(win.case_files.store, 'save_session', lambda payload, ws: saved.update(payload) or True)
    assert win.case_files.save_session()
    assert saved['ui_state']['left_collapsed'] == collapsed
    win.workbench.switch_tab(restore_tab)
    saved.pop('geometry')
    monkeypatch.setattr(win.case_files.store, 'load_session', lambda ws: saved)
    win.case_files.restore_session()
    QApplication.processEvents()
    assert win.workbench.active_tab == 'pareto' and win.appearance.is_drawer_open('run') == (not collapsed)


def test_optimization_figure_menu_keeps_copy_and_export_reachable(win, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QInputDialog
    from tests.python.optimization_support import report
    win.workbench.switch_tab('pareto')
    win.optimization.show_pareto(report(win))
    QApplication.processEvents()
    assert win.btn_export.isVisibleTo(win) and win.btn_export.isEnabled()
    copied, choices = [], []
    monkeypatch.setattr(QGuiApplication, 'clipboard', lambda: SimpleNamespace(setImage=copied.append))
    monkeypatch.setattr(QInputDialog, 'getItem',
                        lambda parent, title, prompt, items, *args: (choices.extend(items) or '', False))
    actions = {action.text(): action for action in win.btn_export.menu().actions()}
    actions['复制当前图像'].trigger()
    assert len(copied) == 1 and not copied[0].isNull()
    actions['导出图像 — PNG / SVG / PDF'].trigger()
    assert 'Pareto / 优化' in choices


@pytest.mark.parametrize('collapsed,summary', [(False, True), (True, False)])
def test_focus_restores_preferences_and_does_not_persist_transient_hiding(
        win, monkeypatch, collapsed, summary):
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    win.appearance.set_drawer_open(not collapsed)
    win.btn_result_summary.setChecked(summary)
    previous_height = win._canvas_cards['temp'].height()
    saved = {}
    monkeypatch.setattr(win.case_files.store, 'save_session', lambda payload, ws: saved.update(payload) or True)

    win.appearance.toggle_focus()
    QApplication.processEvents()
    assert win.btn_focus_view.isChecked()
    assert win.inspector_drawer.isHidden()
    assert win._run_status_card.isHidden()
    assert win.readout_strip.isHidden()
    assert previous_height <= win._canvas_cards['temp'].height() <= win._canvas_scroll.viewport().height()
    win.case_files.save_session()
    assert saved['ui_state']['left_collapsed'] == collapsed
    assert saved['ui_state']['result_summary_visible'] == summary
    win.workbench.switch_tab('pres')
    assert win.readout_strip.isHidden()

    win.appearance.toggle_focus()
    QApplication.processEvents()
    assert not win.btn_focus_view.isChecked()
    assert win.inspector_drawer.isVisibleTo(win) == (not collapsed)
    assert win.appearance.is_drawer_open() == (not collapsed)
    assert win.btn_result_summary.isChecked() == summary
    assert win.readout_strip.isVisibleTo(win) == summary


def test_session_restores_drawer_page_and_legacy_defaults(win, monkeypatch):
    win._select_param_page(2)
    win.btn_result_summary.setChecked(False)
    win.appearance.set_drawer_open(False, page_key='run')
    win.appearance.set_drawer_open(True, page_key='result')
    QApplication.processEvents()
    saved = {}
    monkeypatch.setattr(win.case_files.store, 'save_session', lambda payload, ws: saved.update(payload) or True)
    win.case_files.save_session()
    win.btn_result_summary.setChecked(True)
    saved.pop('geometry')
    # Legacy global left_collapsed in session must not overwrite per-page inspector state.
    saved['ui_state']['left_collapsed'] = False
    saved['ui_state']['parameter_page'] = 0
    monkeypatch.setattr(win.case_files.store, 'load_session', lambda ws: saved)
    win.case_files.restore_session()
    QApplication.processEvents()
    assert not win.appearance.is_drawer_open('run')
    assert win.appearance.is_drawer_open('result')
    assert win._param_page == 2
    assert not win.btn_result_summary.isChecked()

    saved.pop('ui_state')
    win.case_files.restore_session()
    QApplication.processEvents()
    assert not win.appearance.is_drawer_open('run')
    assert win.appearance.is_drawer_open('result')
    assert win._param_page == 2
    assert win.btn_result_summary.isChecked()


def test_palette_field_selection_updates_visible_buttons(win):
    from tests.python.gui_workbench_support import _result
    from sjtu_tpmshx.applications.gui.ui.command_palette import build_actions

    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', _result('2d'))
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    buttons = win._2d_field_btns
    selected, unselected = buttons[0].styleSheet(), buttons[1].styleSheet()
    assert selected != unselected
    actions = {action.keywords[0]: action for action in build_actions(win)
               if action.category == '页面'}

    for field, index in (('pres', 2), ('vel', 1), ('temp', 0)):
        actions[field].callback()
        assert win.workbench.active_tab == field
        assert win.combo_2d_field.currentIndex() == index
        assert win._canvas_cards[field].isVisibleTo(win)
        assert [button.styleSheet() for button in buttons] == [
            selected if i == index else unselected for i in range(3)]


def test_palette_enter_runs_selected_command_once(win, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sjtu_tpmshx.applications.gui.ui.command_palette import CommandPalette

    calls = []
    monkeypatch.setattr(win.result_export, 'export_results', lambda: calls.append('export'))
    palette = CommandPalette(win)
    palette.open_palette()
    palette._input.setText('导出计算结果')
    QApplication.processEvents()
    QTest.keyClick(palette._input, Qt.Key.Key_Return)
    assert calls == ['export']


def test_quick_design_keeps_its_page_and_valid_result_route(win):
    from tests.python.gui_workbench_support import _result

    win.btn_quick_design.click()
    assert not win.btn_tab_result.isEnabled()
    assert win.results.present(_result('2d'), mode='2d', provenance=None, elapsed=1)
    assert win.page_stack.currentWidget() is win.quick_design
    assert win.btn_tab_result.isEnabled()

    win.btn_tab_result.click()
    win.btn_quick_design.click()
    shortcut = next(item for item in win.findChildren(QShortcut) if item.key() == QKeySequence('Ctrl+4'))
    shortcut.activated.emit()
    assert win._canvas_cards['temp'].isVisibleTo(win)
    assert win.workbench.active_tab == 'temp'

    win.btn_quick_design.click()
    win.case_files.load_named_preset('Shanghai (2D Gyroid)')
    assert win.page_stack.currentWidget() is win.quick_design
    assert win.workbench.active_tab == 'layout'
    assert win.case_files.save_session()
    assert win.case_files.store.load_session()['ui_state']['active_tab'] == 'layout'


def test_volume_only_result_enables_the_result_tab(win):
    from tests.python.gui_workbench_support import _result

    win.results.publish(_result('3d'))
    win.workbench.update_tab_visibility()
    assert not win.workbench.rendered_slices
    assert win.workbench.result_view == '3d'
    assert win.btn_tab_result.isEnabled()


def test_same_field_refreshes_result_dimension_and_slice_controls(win):
    from tests.python.gui_workbench_support import _result
    from sjtu_tpmshx.applications.gui.ui.plot_2d_results import finalize_plots
    from sjtu_tpmshx.applications.gui.ui.plot_3d_results import _render_2d_slices_from_3d

    for mode in ('2d', '3d', '2d'):
        result = _result(mode)
        win.results.publish(result)
        if mode == '3d':
            _render_2d_slices_from_3d(win, result, field='temp')
            win.workbench.rendered_slices = win.cache.is_drawn('temp')
        else:
            finalize_plots(win, field='temp')
        win.workbench.update_tab_visibility()
        win.workbench.switch_tab('temp')
        QApplication.processEvents()
        assert win._page_title.text() == '计算结果'
        assert win._slice_controls.isVisibleTo(win) == (mode == '3d')


def test_rail_and_drawer_shortcuts_are_bound_to_appearance_toggles(win):
    rail_sc = next(item for item in win.findChildren(QShortcut)
                   if item.key() == QKeySequence('Ctrl+\\'))
    rail_sc.activated.emit()
    assert win.appearance.is_rail_expanded()
    rail_sc.activated.emit()
    assert not win.appearance.is_rail_expanded()

    drawer_sc = next(item for item in win.findChildren(QShortcut)
                     if item.key() == QKeySequence('Ctrl+]'))
    drawer_sc.activated.emit()
    assert not win.appearance.is_drawer_open()
    drawer_sc.activated.emit()
    assert win.appearance.is_drawer_open()


def test_current_solver_controls_are_visible_and_roundtrip(win):
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window

    win.combo_dim.setCurrentIndex(1)
    win._select_param_page(2)
    QApplication.processEvents()
    assert win.spin_cpu_cores.isVisibleTo(win)
    assert win.combo_grid.isVisibleTo(win)
    assert win.chk_allow_extrap.isVisibleTo(win)
    for name in ('chk_wall_refine_3d', 'chk_var_rhocp', 'chk_port_wall_refine',
                 'chk_uniform_inletA_2d', 'chk_uniform_inletB_2d'):
        assert not hasattr(win, name)
    assert 'advanced_flags' not in win._ia_sections
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    win.chk_allow_extrap.setChecked(False)
    before = config_from_window(win)
    preset = win.case_files.capture_current_preset('current settings')
    assert not before.flags.port_wall_refine
    assert before.flags.variable_rho_cp
    assert before.bc_A.uniform_inlet_2d and before.bc_B.uniform_inlet_2d
    win.combo_dim.setCurrentIndex(0)
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(True))
    win.chk_allow_extrap.setChecked(True)
    win.case_files.apply_user_preset(preset)
    after = config_from_window(win)
    assert after.flags == before.flags
    assert after.extrap == before.extrap


def test_fast_drawer_tab_switches_keep_latest_page_and_editable_fields(win):
    win.le_Nx.setText('37')
    win.inspector_drawer.tab_strip._buttons[1].click()
    win.inspector_drawer.tab_strip._buttons[2].click()
    assert win._param_page == 2
    assert win.inspector_drawer.current_index() == 2
    assert win.le_Nx.isEnabled()
    win.le_Nx.setText('41')
    assert win.le_Nx.text() == '41'


def test_first_show_reveal_is_once_and_keeps_restored_page_and_values(win, monkeypatch):
    win._select_param_page(2)
    win.le_Nx.setText('41')
    win.hide()
    QApplication.processEvents()
    calls = []
    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.shell_appearance.reveal', calls.append)
    win.appearance._initial_reveal_scheduled = False
    win.show()
    QApplication.processEvents()
    assert calls == [win.inspector_drawer]
    assert win._param_page == 2 and win.le_Nx.text() == '41'
    win.hide()
    win.show()
    QApplication.processEvents()
    assert len(calls) == 1


def test_stale_readout_badge_and_co2_run_info_provenance(win):
    from tests.python.gui_workbench_support import _result

    win.combo_dim.setCurrentIndex(0)
    preset = win.case_files.capture_current_preset('Run inputs')
    result = _result('2d')
    result.metadata['run_provenance'] = dict(
        preset=preset, preset_source='Shanghai (2D Gyroid)', mode='2d',
        input_grid=['20', '20'], actual_grid=[4, 3],
    )
    win.results.publish(result)
    win.results.refresh_summary()
    assert not win.readout_strip.is_stale()

    # Editing inputs updates stale badge via actual widget signals (no manual refresh).
    win.chk_allow_extrap.setChecked(not win.chk_allow_extrap.isChecked())
    assert win.readout_strip.is_stale()
    win.chk_allow_extrap.setChecked(not win.chk_allow_extrap.isChecked())
    assert not win.readout_strip.is_stale()
    win.le_L.setText('0.25')
    assert win.readout_strip.is_stale()

    # Non-CO2 accepted result must NOT show CO2 CFD source when draft is changed to CO2.
    win.combo_fluidA.setCurrentIndex(3)
    info_air = win.history.build_run_info_data()
    assert not any('CO₂ CFD 查表' in row.value for row in info_air.info_rows)

    # Accepted CO2 result shows CO2 CFD source even if draft is switched back to Air.
    co2_result = _result('2d')
    co2_result.metadata['run_provenance'] = dict(
        preset=preset, preset_source='Shanghai (2D Gyroid)', mode='2d',
        input_grid=['20', '20'], actual_grid=[4, 3],
    )
    co2_result.metadata['co2'] = dict(sides=['A'], common_geometry='co2_cfd')
    win.results.publish(co2_result)
    win.combo_fluidA.setCurrentIndex(0)
    info_co2 = win.history.build_run_info_data()
    assert any('CO₂ CFD 查表' in row.value for row in info_co2.info_rows)
