"""Real Qt checks for parameter storage and reversible canvas focus."""
import pytest

pytest.importorskip('PySide6')

from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    from sjtu_tpmshx.main import Main_Menu

    original_init = SessionManager.__init__

    def local_session(self, base_dir=None, parent=None):
        original_init(self, base_dir=base_dir or tmp_path, parent=parent)

    monkeypatch.setattr(SessionManager, '__init__', local_session)
    window = Main_Menu()
    window.showNormal()
    window.resize(1300, 760)
    QApplication.processEvents()
    yield window
    window.close()
    QApplication.processEvents()


def test_collapse_restore_preserves_fields_page_scroll_and_width(win):
    win._select_param_page(1)
    win._accordion_groups['边界细节与高级'].setChecked(True)
    win._splitter.setSizes([426, 850])
    win.le_Nx.setText('37')
    QApplication.processEvents()
    scroll = win._param_scroll.verticalScrollBar()
    scroll.setValue(min(120, scroll.maximum()))
    assert scroll.value() > 0
    position, width = scroll.value(), win._parameter_host.width()

    win.btn_collapse_parameters.click()
    QApplication.processEvents()
    assert win._left_collapsed
    assert win._parameter_host.width() == 56
    assert win._param_rail.isVisibleTo(win)
    assert not win._param_panel.isVisibleTo(win)
    win.btn_expand_parameters.click()
    QApplication.processEvents()
    assert not win._left_collapsed
    assert win._parameter_host.width() == width
    assert win._param_page == 1
    assert scroll.value() == position
    assert win.le_Nx.text() == '37'

    win._toggle_left_panel()
    win._param_rail_btns[0].click()
    assert not win._left_collapsed
    assert win._param_page == 0


@pytest.mark.parametrize('collapsed,summary', [(False, True), (True, False)])
def test_focus_restores_preferences_and_does_not_persist_transient_hiding(
        win, monkeypatch, collapsed, summary):
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    win._switch_tab('temp')
    win._set_parameter_panel_collapsed(collapsed)
    win.btn_result_summary.setChecked(summary)
    previous_height = win._canvas_cards['temp'].height()
    saved = {}
    monkeypatch.setattr(win.sm, 'save_session', lambda payload, ws: saved.update(payload) or True)

    win._toggle_3d_immersive()
    QApplication.processEvents()
    assert win.btn_focus_view.isChecked()
    assert win._parameter_host.isHidden()
    assert win._run_status_card.isHidden()
    assert win._result_sidebar.isHidden()
    assert previous_height <= win._canvas_cards['temp'].height() <= win._canvas_scroll.viewport().height()
    win._save_session()
    assert saved['ui_state']['left_collapsed'] == collapsed
    assert saved['ui_state']['result_summary_visible'] == summary
    win._switch_tab('pres')
    assert win._result_sidebar.isHidden()

    win._toggle_3d_immersive()
    QApplication.processEvents()
    assert not win.btn_focus_view.isChecked()
    assert win._parameter_host.isVisibleTo(win)
    assert win._left_collapsed == collapsed
    assert win.btn_result_summary.isChecked() == summary
    assert win._result_sidebar.isVisibleTo(win) == summary


def test_session_restores_width_page_and_legacy_defaults(win, monkeypatch):
    win._splitter.setSizes([450, 850])
    win._select_param_page(2)
    win.btn_result_summary.setChecked(False)
    QApplication.processEvents()
    width = win._parameter_host.width()
    win._toggle_left_panel()
    saved = {}
    monkeypatch.setattr(win.sm, 'save_session', lambda payload, ws: saved.update(payload) or True)
    win._save_session()
    win._toggle_left_panel()
    win._splitter.setSizes([320, 980])
    win._select_param_page(0)
    win.btn_result_summary.setChecked(True)
    # Keep this sidebar-state test at its 1300 px viewport. Qt otherwise
    # clamps restored window geometry to the offscreen backend's small screen,
    # where the chart's minimum width prevents a 450 px parameter panel.
    saved.pop('geometry')
    monkeypatch.setattr(win.sm, 'load_session', lambda ws: saved)
    win._restore_session()
    QApplication.processEvents()
    assert win._left_collapsed
    assert win._param_width == width
    assert win._param_page == 2
    assert not win.btn_result_summary.isChecked()
    win._toggle_left_panel()
    QApplication.processEvents()
    assert win._parameter_host.width() == width

    saved.pop('ui_state')
    win._restore_session()
    QApplication.processEvents()
    assert not win._left_collapsed
    assert win._param_page == 0
    assert win.btn_result_summary.isChecked()


def test_parameter_shortcut_is_bound_to_the_same_toggle(win):
    shortcut = next(item for item in win.findChildren(QShortcut)
                    if item.key() == QKeySequence('Ctrl+\\'))
    shortcut.activated.emit()
    assert win._left_collapsed
    shortcut.activated.emit()
    assert not win._left_collapsed


def test_expert_controls_stay_folded_and_preserve_preset_values(win):
    from sjtu_tpmshx.ui.window_config import config_from_window

    win.combo_dim.setCurrentIndex(1)
    win._select_param_page(2)
    QApplication.processEvents()
    resources = win._ia_sections['compute_resources']
    expert = win._ia_sections['advanced_flags']
    assert win._accordion_groups['网格与求解器'].isAncestorOf(resources)
    assert resources.isVisibleTo(win)
    assert win.spin_cpu_cores.isVisibleTo(win)

    win._select_param_page(1)
    win._accordion_groups['边界细节与高级'].setChecked(True)
    assert expert.isVisibleTo(win)
    assert not win.chk_allow_extrap.isVisibleTo(win)
    expert._set_expanded(True)
    assert win.chk_allow_extrap.isVisibleTo(win)
    assert win.chk_wall_refine_3d.isVisibleTo(win)
    win.chk_allow_extrap.setChecked(False)
    win.chk_wall_refine_3d.setChecked(True)
    win.chk_var_rhocp.setChecked(False)
    before = config_from_window(win)
    preset = win._capture_current_preset('expert settings')
    assert before.flags.wall_refine_3d and not before.flags.port_wall_refine

    win.combo_dim.setCurrentIndex(0)
    assert win.chk_allow_extrap.isVisibleTo(win)
    assert win.chk_port_wall_refine.isVisibleTo(win)
    assert not win.chk_wall_refine_3d.isVisibleTo(win)
    assert not win.chk_var_rhocp.isVisibleTo(win)
    win._select_param_page(2)
    assert resources.isHidden()  # No empty CPU heading in 2D.
    expert._set_expanded(False)
    win.chk_allow_extrap.setChecked(True)
    win.chk_port_wall_refine.setChecked(True)
    win.chk_var_rhocp.setChecked(True)
    win._apply_user_preset(preset)
    after = config_from_window(win)
    assert after.flags == before.flags
    assert after.extrap == before.extrap
    win._select_param_page(1)
    assert not win.chk_allow_extrap.isVisibleTo(win)
    assert not win.chk_wall_refine_3d.isVisibleTo(win)
    win._select_param_page(2)
    assert win.spin_cpu_cores.isVisibleTo(win)


@pytest.mark.parametrize('width', [900, 1440])
def test_header_menu_chevron_and_search_fit_their_buttons(win, width):
    from PySide6.QtCore import QSize
    from sjtu_tpmshx.ui.icons import icon

    win.resize(width, 900)
    QApplication.processEvents()
    menus = (win.btn_recent, win.btn_save, win.btn_export, win.btn_more)
    search = win.btn_command_search
    assert search.size() == QSize(36, 36)
    assert search.iconSize() == QSize(20, 20)
    for button in menus:
        assert button.menu() is not None and button.menu().actions()
        assert button.height() == search.height()
        assert button.width() >= button.sizeHint().width()
        assert button.iconSize() == QSize(18, 18)
        assert button.geometry().center().y() == search.geometry().center().y()
        assert button.parentWidget().rect().contains(button.geometry())
    assert search.parentWidget().rect().contains(search.geometry())

    # Give the arrow a unique tint and inspect its actual rendered bounds:
    # this catches the reported oversized, bottom-right menu indicator.
    button = win.btn_save
    button._menu_chevron = icon('chevron-down', '#ff00ff')
    pixmap = button.grab()
    image = pixmap.toImage()
    pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
              if image.pixelColor(x, y).red() - image.pixelColor(x, y).green() > 30
              and image.pixelColor(x, y).blue() - image.pixelColor(x, y).green() > 30]
    assert pixels
    xs, ys = zip(*pixels)
    scale = pixmap.devicePixelRatio()
    assert min(xs) / scale > button.width() / 2
    assert max(xs) - min(xs) + 1 <= 12 * scale
    assert abs((min(ys) + max(ys)) / (2 * scale) - button.height() / 2) < 2


def test_fast_parameter_switches_keep_latest_page_and_editable_fields(win):
    from PySide6.QtCore import QPropertyAnimation
    from shiboken6 import isValid

    win.le_Nx.setText('37')
    win._param_btns[1].click()
    old_effect = win._param_scroll.viewport().graphicsEffect()
    win._param_btns[2].click()
    assert not isValid(old_effect)
    assert win._param_page == 2
    assert win._accordion_groups['网格与求解器'].isVisibleTo(win)
    assert win._accordion_groups['流体'].isHidden()
    assert win._accordion_groups['几何与结构'].isHidden()
    assert win.le_Nx.isEnabled()
    win.le_Nx.setText('41')  # transition does not lock editing
    effect = win._param_scroll.viewport().graphicsEffect()
    win._param_btns[2].click()
    assert win._param_scroll.viewport().graphicsEffect() is effect
    animation = effect.findChild(QPropertyAnimation)
    animation.pause()
    animation.setCurrentTime(animation.duration())
    assert win._param_scroll.viewport().graphicsEffect() is None
    assert win.le_Nx.text() == '41'


def test_first_show_reveal_is_once_and_keeps_restored_page_and_values(win, monkeypatch):
    win._select_param_page(2)
    win.le_Nx.setText('41')
    win.hide()
    QApplication.processEvents()
    calls = []
    monkeypatch.setattr('sjtu_tpmshx.ui.microanim.reveal', calls.append)
    win._initial_reveal_scheduled = False
    win.show()
    QApplication.processEvents()
    assert calls == [win._param_scroll.viewport()]
    assert win._param_page == 2 and win.le_Nx.text() == '41'
    win.hide()
    win.show()
    QApplication.processEvents()
    assert len(calls) == 1
