"""Layout-hygiene locks (openspec ui-layout-fixes, 2026-07-03).

1. Param pages never scroll horizontally (labels word-wrap instead of
   widening the grid past the panel viewport).
2. The Fluid A/B ResponsiveRow stacks below its width threshold.
3. The canvas empty state carries the structured 3-step guidance.
"""
from __future__ import annotations

import os

import pytest

from tm1.data_types.compute_result import ComputeResult

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QScrollArea  # noqa: E402


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    import tm1.applications.gui.controllers.session_manager as sm_mod
    import tm1.applications.gui.controllers.user_storage as storage_mod

    session_dir = tmp_path_factory.mktemp("ui-layout-session")
    original_init = sm_mod.SessionManager.__init__
    patch = pytest.MonkeyPatch()

    def _init(self, base_dir=None, parent=None):
        original_init(
            self,
            base_dir=base_dir if base_dir is not None else session_dir,
            parent=parent,
        )

    patch.setattr(sm_mod.SessionManager, '__init__', _init)
    patch.setattr(storage_mod, '_appearance_dir', lambda: session_dir)
    app = QApplication.instance() or QApplication([])
    from tm1.applications.gui.ui.main_window import Main_Menu
    w = Main_Menu()
    w.resize(1600, 1000)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()
    patch.undo()


def test_param_pages_have_no_horizontal_scroll(win):
    app = QApplication.instance()
    app.processEvents()
    scrolls = win.findChildren(QScrollArea)
    assert scrolls, "no scroll areas found"
    offenders = [
        s.objectName() or repr(s.widget())
        for s in scrolls
        if s.isVisible() and s.horizontalScrollBar().maximum() > 0
        and s.horizontalScrollBarPolicy().name != 'ScrollBarAlwaysOff'
    ]
    assert not offenders, f"horizontal scroll present in: {offenders}"


def test_fluids_row_has_unified_side_switch(win):
    assert len(win._fluid_side_btns) == 2
    assert [b.text() for b in win._fluid_side_btns] == ["流体 A", "流体 B"]
    assert win._fluid_side_stack.count() == 2


def test_responsive_row_direction_flips():
    """Standalone instance — a layout-managed widget can't be resized freely
    (the parent layout re-imposes geometry), so the flip is tested on a
    top-level ResponsiveRow."""
    from PySide6.QtWidgets import QLabel
    from tm1.applications.gui.ui.responsive import ResponsiveRow
    app = QApplication.instance() or QApplication([])
    row = ResponsiveRow(threshold=520)
    row.addWidget(QLabel("A"))
    row.addWidget(QLabel("B"))
    row.show()
    row.resize(400, 200)
    app.processEvents()
    assert row.direction == QBoxLayout.Direction.TopToBottom
    row.resize(800, 200)
    app.processEvents()
    assert row.direction == QBoxLayout.Direction.LeftToRight
    row.close()


def test_empty_state_has_three_steps_and_preset(win):
    from PySide6.QtWidgets import QLabel
    box = getattr(win, "_empty_state_label", None)   # container since batch2
    assert box is not None
    assert not box.isVisibleTo(win)
    assert win._canvas_cards['layout'].isVisibleTo(win)
    assert 'layout' in win.cache.get_drawn_tabs()
    txt = " ".join(l.text() for l in box.findChildren(QLabel))
    for marker in (">1<", ">2<", ">3<", "计算"):
        assert marker in txt, f"empty state missing {marker!r}"
    btn = getattr(win, "_empty_state_preset_btn", None)
    assert btn is not None and btn.isVisibleTo(box)


def test_initial_geometry_skips_invalid_draft(win, monkeypatch):
    original = win.le_L.text()
    draws = []
    monkeypatch.setattr(win, '_draw_layout', lambda: draws.append(True))
    try:
        for text in ('', 'bad', '-1', 'nan', 'inf'):
            win.le_L.setText(text)
            win._preview_initial_geometry()
        assert not draws
        win.le_L.setText(original)
        win._preview_initial_geometry()
        assert draws == [True]
    finally:
        win.le_L.setText(original)


def test_empty_state_preset_button_applies_shanghai(win):
    app = QApplication.instance()
    win._empty_state_preset_btn.click()
    app.processEvents()
    assert getattr(win.case_files, "active_preset_name", None) == "Shanghai (3D Gyroid)"


def test_sticky_cta_outside_scroll(win):
    """btn_compute lives in the fixed header bar, not inside a scroll area."""
    from PySide6.QtWidgets import QScrollArea
    assert win.btn_compute.isVisibleTo(win)
    p = win.btn_compute.parentWidget()
    inside_scroll = False
    while p is not None:
        if isinstance(p, QScrollArea):
            inside_scroll = True
            break
        p = p.parentWidget()
    assert not inside_scroll


_EXPECTED_BANDS = {
    "domain_geometry": True,
    "tpms_structure": True,
    "tpms_computed": True,
    "fluid_a": True,
    "pipe_a": True,
    "fluid_b": True,
    "pipe_b": True,
    "grid_rect": True,
    "df_method": True,
    "sco2_nu": True,
    "correlation_policy": True,
    "compute_resources": True,
}


def test_drawer_bands_with_default_states(win):
    bands = getattr(win, "_drawer_bands", {})
    assert set(bands) == set(_EXPECTED_BANDS)
    for name, open_ in _EXPECTED_BANDS.items():
        _tab_idx, band = bands[name]
        assert band.is_expanded() == open_, name


def test_parameter_inspector_has_single_visible_scroll_area(win):
    outer = win.inspector_drawer
    assert outer is not None
    scrolls = [s for s in outer.findChildren(QScrollArea) if s.isVisible()]
    assert len(scrolls) <= 1, [s.objectName() or repr(s) for s in scrolls]


def test_tpms_computed_is_visible_before_and_after_calculation(win):
    app = QApplication.instance()
    win._select_param_page(0)
    sec = win._ia_sections["tpms_computed"]
    assert sec.is_expanded()
    assert sec._body.isVisibleTo(win)
    assert win.compute_tpms()
    app.processEvents()
    assert sec._body.isVisibleTo(win)
    assert win._v_eps.text() not in ("—", "")
    win._select_param_page(1)


def test_diagnostics_reachable_via_run_info_and_dialogs(win, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton
    from tm1.data_types.compute_result import ComputeResult

    calls = []
    monkeypatch.setattr(win.results, 'show_diag_dialog', lambda: calls.append(True))
    win.results.publish(ComputeResult(Q_W=42.0, converged=True, diagnostics={'mode': '2d'}))
    win.results.refresh_summary()
    app = QApplication.instance()

    for drawer_open in (True, False):
        win.appearance.set_drawer_open(drawer_open)
        app.processEvents()
        assert win.btn_run_info.isVisibleTo(win)
        win.btn_run_info.click()
        app.processEvents()
        pop = win._run_info_popover
        assert pop.isVisible()
        diag_btn = next(
            b for b in pop.findChildren(QPushButton)
            if any(lbl.text() == "诊断详情…" for lbl in b.findChildren(QLabel))
        )
        assert diag_btn.isEnabled()
        diag_btn.click()
        app.processEvents()
        pop.close()
    assert len(calls) == 2
    win.appearance.set_drawer_open(True)


def test_group_badge_counts_empty_field(win):
    from tm1.applications.gui.ui.ui_builders import refresh_group_badges
    _tab_idx, band = win._drawer_bands["grid_rect"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert band.header._badge_label.isVisibleTo(band.header)
    assert "⚠" in band.header._badge_label.text()
    assert win._group_badge_counts["grid_rect"] >= 1
    win.le_Nx.setText(old or "40")
    refresh_group_badges(win)
    assert not band.header._badge_label.isVisibleTo(band.header)


def test_group_badge_updates_via_validator_debounce(win):
    from PySide6.QtTest import QSignalSpy

    _tab_idx, band = win._drawer_bands["domain_geometry"]
    old = win.le_L.text()
    win.le_L.setText("")
    win.le_L.editingFinished.emit()
    assert win._badge_timer.isActive()
    assert QSignalSpy(win._badge_timer.timeout).wait(2000)
    assert win._group_badge_counts["domain_geometry"] >= 1
    assert band.header._badge_label.isVisibleTo(band.header)
    assert "⚠" in band.header._badge_label.text()
    win.le_L.setText(old or "0.182")
    win.le_L.editingFinished.emit()
    assert win._badge_timer.isActive()
    assert QSignalSpy(win._badge_timer.timeout).wait(2000)
    assert win._group_badge_counts["domain_geometry"] == 0
    assert not band.header._badge_label.isVisibleTo(band.header)


def test_group_badge_survives_toggle(win):
    from tm1.applications.gui.ui.ui_builders import refresh_group_badges
    _tab_idx, band = win._drawer_bands["grid_rect"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert "⚠" in band.header._badge_label.text()
    band.set_expanded(False)
    assert "⚠" in band.header._badge_label.text(), "badge wiped by collapse"
    band.set_expanded(True)
    assert "⚠" in band.header._badge_label.text(), "badge wiped by expand"
    win.le_Nx.setText(old or "40")
    refresh_group_badges(win)


def test_2d_field_segment_drives_combo(win):
    """ui-batch4 ③: the 温度/速度/压力 segmented buttons drive the hidden
    combo (state source); reverse-sync repaints the buttons."""
    btns = getattr(win, "_2d_field_btns", None)
    assert btns and len(btns) == 3
    assert not win.combo_2d_field.isVisible()   # demoted to state source
    win._2d_field_seg.setEnabled(True)
    btns[2].click()                             # 压力
    assert win.combo_2d_field.currentIndex() == 2
    assert win.workbench.resolve_2d_view_card() == 'pres'
    win.combo_2d_field.setCurrentIndex(0)       # reverse path
    assert win.workbench.resolve_2d_view_card() == 'temp'


def test_copy_figure_clipboard_no_data_safe(win):
    """No drawn canvas → status message, no exception, clipboard untouched."""
    win.workbench.active_tab = 'layout'
    win.cache.replace_drawn_tabs(set())
    win.result_export.copy_figure_clipboard()                # must not raise


# ── ui-plan3-workbench T1: three-tab toolbar + result aggregation ────

def test_workbench_toolbar_visible_set(win):
    """Toolbar exposes only the three real workbench tabs."""
    assert win.btn_tab_layout.isVisibleTo(win)
    assert win.btn_tab_result.isVisibleTo(win)
    assert win.btn_tab_pareto.isVisibleTo(win)
    for attr in ('btn_tab_temp', 'btn_tab_pres', 'btn_tab_vel',
                 'btn_tab_3d', 'btn_tab_2d_view'):
        assert not hasattr(win, attr)


def test_temperature_card_selects_the_2d_result_button(win):
    """A request for the temperature card selects the result page and its 2D view."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    assert win.workbench.active_tab == 'temp'
    assert win.workbench.result_view == '2d'
    assert win.nav_rail.active_page() == 'result'
    win.workbench.switch_tab('layout')
    win.cache.clear('2d')
    win.workbench.update_tab_visibility()


def test_result_view_toggle_gating(win):
    """2D side of the toggle follows the 2D rule; 3D side needs a ready
    3D view. In 2D mode with results: 2D enabled, 3D disabled."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})  # These layout stubs represent rendered fields.
    win.workbench.update_tab_visibility()
    assert win._result_view_btns['2d'].isEnabled()
    assert not win._result_view_btns['3d'].isEnabled()
    assert win.btn_tab_result.isEnabled()
    for _ in range(2):
        win._result_view_btns['2d'].click()
        assert win._result_view_btns['2d'].isChecked()
        assert not win._result_view_btns['3d'].isChecked()
    win.cache.clear('2d')
    win.workbench.update_tab_visibility()
    assert not win.btn_tab_result.isEnabled()


def test_result_summary_toggle_keeps_values_and_tab_choice(win):
    win.combo_dim.setCurrentIndex(0)
    result = ComputeResult()
    win.cache.set_result('2d', result)
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    assert win.btn_result_summary.isVisibleTo(win)
    assert win.readout_strip.isVisibleTo(win)
    before = {key: label.text() for key, label in win._sb_labels.items()}
    win.btn_result_summary.click()
    assert win.readout_strip.isHidden()
    win.workbench.switch_tab('layout')
    assert win.btn_result_summary.isHidden()
    win.workbench.switch_tab('temp')
    assert win.readout_strip.isHidden()
    assert {key: label.text() for key, label in win._sb_labels.items()} == before
    win.btn_result_summary.click()
    assert win.readout_strip.isVisibleTo(win)
    win.case_files.invalidate_results_for_preset_load()
    assert win.readout_strip.isHidden()
    assert win.btn_result_summary.isHidden()


# ── ui-plan-b-wizard: Optimize tab three-page wizard ─────────────────


def test_optimize_wizard_pages(win):
    """A stage change selects its wizard page."""
    stack = win.optimization.stack
    assert stack.count() == 3
    assert stack.currentIndex() == 0          # starts on 配置
    win.optimization.set_stage('running', 'active')
    assert stack.currentIndex() == 1
    win.optimization.set_stage('result', 'active')
    assert stack.currentIndex() == 2
    win.optimization.set_stage('config', 'active')
    assert stack.currentIndex() == 0


def test_optimize_inline_params_complete(win):
    """Page-1 inline params carry every key the launch path consumes —
    the modal dialog is only the fallback for hosts without the wizard."""
    keys = set(win.optimization.parameters)
    assert keys == {'n_init', 'n_iter', 'q_batch', 'seed'}
    for sp in win.optimization.parameters.values():
        assert sp.value() > 0 or sp.value() == 0   # constructed + in range


def test_optimize_zone_panel_in_wizard(win):
    """The zone panel lives inside wizard page 1 (the old splitter is
    retired)."""
    p1 = win.optimization.stack.widget(0)
    assert win._zone_panel.isVisibleTo(p1) or p1.isAncestorOf(win._zone_panel)


# ── ui-plan3a: design-token discipline ───────────────────────────────

_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "python", "applications", "gui", "ui")

# Micro-controls whose radius is proportional to the element (sliders,
# checkbox indicators, progress chunks, scrollbar handles) and semantic
# pills/toasts are exempt — see theme.py radius policy comment.
_RADIUS_EXEMPT_FILES = {"panel_vis_3d.py", "theme.py"}


def _ui_sources():
    import glob
    paths = (glob.glob(os.path.join(_UI_DIR, "*.py"))
             + glob.glob(os.path.join(_UI_DIR, "mixins", "*.py")))
    assert paths, f"no UI sources found under {_UI_DIR}"
    for p in paths:
        with open(p, encoding="utf-8") as handle:
            yield p, handle.read()


def test_no_stray_card_radii():
    """New card/control radii use theme tokens, not stray 8/10/12px literals.
    Existing pills and micro-controls retain their proportional geometry."""
    import re
    bad = []
    for p, src in _ui_sources():
        name = os.path.basename(p)
        if name in _RADIUS_EXEMPT_FILES:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = re.search(r"border-radius:\s*(8|10|12)px", line)
            # builders_canvas pill badge (padding 5px 14px chip) is the one
            # sanctioned 12px pill outside the exempt files.
            if m and "padding:5px 14px" not in line:
                bad.append(f"{name}:{i}: {line.strip()}")
    assert not bad, "stray card radii:\n" + "\n".join(bad)


def test_no_raw_hex_outside_theme():
    """UI colors flow through theme tokens. Allowed: token fallbacks in
    `t.get('x', '#…')`, microanim's deep
    glow hints, docstrings/comments."""
    import re
    allow_files = {"theme.py"}
    bad = []
    for p, src in _ui_sources():
        name = os.path.basename(p)
        if name in allow_files:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#")[0] if not re.search(
                r"['\"]#[0-9A-Fa-f]{6}", line) else line
            for m in re.finditer(r"['\"](#[0-9A-Fa-f]{6})['\"]", code):
                seg = code[:m.start()]
                # token fallback pattern: .get('tok', '#hex') — compliant
                if re.search(r"\.get\(\s*['\"][\w]+['\"]\s*,\s*$", seg):
                    continue
                # microanim deep glow hints tuple: ('#tok-resolved', '#deep', '…')
                if name == "microanim.py":
                    continue
                bad.append(f"{name}:{i}: {line.strip()[:90]}")
    assert not bad, "raw hex outside theme:\n" + "\n".join(bad)


def test_numeric_inputs_rule_a_left_aligned_with_unit_suffix(win):
    from PySide6.QtCore import Qt as _Qt
    from tm1.applications.gui.ui.field_factory import UnitLineEdit
    orig_dim = win.combo_dim.currentIndex()
    win.combo_dim.setCurrentIndex(0)
    assert isinstance(win.le_L, UnitLineEdit)
    assert win.le_L.alignment() & _Qt.AlignmentFlag.AlignLeft
    assert win.le_L.unit() == 'm'
    assert win.le_Nx.alignment() & _Qt.AlignmentFlag.AlignLeft

    # B09: expressions and high-precision decimals edit in the displayed unit (kPa / mm)
    # and convert once to canonical SI without premature 15-digit storage rounding.
    orig_pin = win.le_PinA.text()
    orig_ctr = win.le_pipeA_in_ctr.text()
    orig_tin = win.le_TinA.text()
    orig_ua = win.le_uA.text()
    try:
        from PySide6.QtWidgets import QLineEdit
        QLineEdit.setText(win.le_PinA, '100+2')
        win.le_PinA.editingFinished.emit()
        assert win.le_PinA.text() == '102000'
        assert win.le_PinA.raw_display_text() == '102'

        QLineEdit.setText(win.le_PinA, '101.123456789012345')
        win.le_PinA.editingFinished.emit()
        assert win.le_PinA.text() == '101123.456789012345'
        assert win.le_PinA.formatted_display_text() == '101.123'

        QLineEdit.setText(win.le_PinA, '101.123456789012345 kPa')
        win.le_PinA.editingFinished.emit()
        assert win.le_PinA.text() == '101123.456789012345'
        assert win.le_PinA.formatted_display_text() == '101.123'

        QLineEdit.setText(win.le_pipeA_in_ctr, '20+22')
        win.le_pipeA_in_ctr.editingFinished.emit()
        assert win.le_pipeA_in_ctr.text() == '0.042'
        assert win.le_pipeA_in_ctr.raw_display_text() == '42'

        QLineEdit.setText(win.le_pipeA_in_ctr, '41.23456789')
        win.le_pipeA_in_ctr.editingFinished.emit()
        assert win.le_pipeA_in_ctr.text() == '0.04123456789'

        QLineEdit.setText(win.le_pipeA_in_ctr, '41.23456789 mm')
        win.le_pipeA_in_ctr.editingFinished.emit()
        assert win.le_pipeA_in_ctr.text() == '0.04123456789'
        assert win.le_pipeA_in_ctr.formatted_display_text() == '41.2346'

        QLineEdit.setText(win.le_TinA, '300.123456789012345 K')
        win.le_TinA.editingFinished.emit()
        assert win.le_TinA.text() == '300.123456789012345'
        assert win.le_TinA.formatted_display_text() == '300.123'

        QLineEdit.setText(win.le_uA, '1.08 km/h')
        win.le_uA.editingFinished.emit()
        assert win.le_uA.text() == '0.3'

        from tm1.applications.gui.ui.window_config import config_from_window
        QLineEdit.setText(win.le_TinA, '70 F')
        win.le_TinA.editingFinished.emit()
        t_in_k_from_k = config_from_window(win, strict=True).fluid_A.T_in_K
        win._toggle_temp_unit()
        try:
            assert win._temp_unit == 'C'
            QLineEdit.setText(win.le_TinA, '70 F')
            win.le_TinA.editingFinished.emit()
            t_in_k_from_c = config_from_window(win, strict=True).fluid_A.T_in_K
        finally:
            win._toggle_temp_unit()
        assert t_in_k_from_k == t_in_k_from_c
    finally:
        win.le_PinA.setText(orig_pin)
        win.le_pipeA_in_ctr.setText(orig_ctr)
        win.le_TinA.setText(orig_tin)
        win.le_uA.setText(orig_ua)
        win.combo_dim.setCurrentIndex(orig_dim)


def test_dialog_theme_applies_first_and_changed_styles_only(monkeypatch):
    from unittest.mock import Mock
    from tm1.applications.gui.ui.shell_dialogs import ShellDialogs
    from tm1.applications.gui.ui.theme import get_theme, get_theme_name, set_theme

    app = QApplication.instance() or QApplication([])
    previous_style, previous_theme = app.styleSheet(), get_theme_name()
    dialogs = ShellDialogs(None)
    try:
        app.setStyleSheet('')
        set_theme('light')
        with monkeypatch.context() as patch:
            setter = Mock(wraps=app.setStyleSheet)
            patch.setattr(app, 'setStyleSheet', setter)
            dialogs.install_dialog_theme()
            assert setter.call_count == 1
            assert f"QMessageBox{{background:{get_theme()['window']};}}" in app.styleSheet()
            light_style = app.styleSheet()
            dialogs.install_dialog_theme()
            assert setter.call_count == 1

            set_theme('dark')
            dialogs.install_dialog_theme()
            assert setter.call_count == 2
            assert app.styleSheet() != light_style
            assert f"QMessageBox{{background:{get_theme()['window']};}}" in app.styleSheet()
            dialogs.install_dialog_theme()
            assert setter.call_count == 2
    finally:
        set_theme(previous_theme)
        app.setStyleSheet(previous_style)


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
def test_preflight_dialogs_use_active_theme_tokens(win, monkeypatch, theme_name):
    """Input and grid preflight HTML must use active theme tokens."""
    from PySide6.QtWidgets import QMessageBox
    from tm1.preprocess.preflight import Preflight
    from tm1.applications.gui.ui.theme import get_theme, get_theme_name, set_theme
    from tm1.applications.gui.ui.window_config import config_from_window

    previous_theme = get_theme_name()
    original_L = win.le_L.text()
    original_page = win._param_page
    dialogs = []
    monkeypatch.setattr(
        QMessageBox, 'exec',
        lambda box: dialogs.append(box.text()) or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(
        'tm1.preprocess.preflight.preflight_config',
        lambda _config: Preflight(
            errors=['grid error'], warnings=['grid warning'], info=['grid info']))
    try:
        cfg = config_from_window(win, strict=True)
        set_theme('dark' if theme_name == 'light' else 'light')
        other_tokens = get_theme()
        set_theme(theme_name)
        tokens = get_theme()

        win.le_L.setText('')
        assert not win.single_run.validate_inputs()
        assert not win.single_run.preflight_grid(cfg)
    finally:
        set_theme(previous_theme)
        win.le_L.setText(original_L)
        win._refresh_field_validation()
        win._select_param_page(original_page)

    assert len(dialogs) == 2
    input_html, grid_html = dialogs
    for key in ('err', 'search_hl', 'sub_fg'):
        assert tokens[key] != other_tokens[key]

    assert f"color:{tokens['sub_fg']};'><code>le_L</code>" in input_html
    assert f"color:{tokens['sub_fg']};'>运行计算前请先修正下列字段" in input_html
    assert f"color:{tokens['err']};'>(empty)" in input_html
    assert other_tokens['err'] not in input_html
    assert other_tokens['sub_fg'] not in input_html

    assert f"color:{tokens['err']};'>1 error</h4>" in grid_html
    assert f"color:{tokens['err']};'>grid error</li>" in grid_html
    assert f"color:{tokens['search_hl']};'>1 warning</h4>" in grid_html
    assert f"color:{tokens['search_hl']};'>grid warning</li>" in grid_html
    assert f"color:{tokens['sub_fg']};'>Info</h4>" in grid_html
    assert f"color:{tokens['sub_fg']};'>grid info</li>" in grid_html
    assert f"color:{tokens['sub_fg']};'>Reviewed wall-refine fit" in grid_html
    for key in ('err', 'search_hl', 'sub_fg'):
        assert other_tokens[key] not in grid_html


def test_result_label_state_and_unit_hint():
    from PySide6.QtWidgets import QGridLayout, QWidget
    from tm1.applications.gui.ui.field_factory import FieldFactory
    from tm1.applications.gui.ui.theme_manager import ThemeManager

    QApplication.instance() or QApplication([])
    host = QWidget()
    try:
        val = FieldFactory(ThemeManager()).res_row(QGridLayout(host), 0, 'T<sub>in</sub> [K]')
        assert val.text() == '—'
        assert val.property('valState') == 'empty'
        assert val._unit_hint == 'K'
        val.setText('298.15')
        assert val.property('valState') == 'filled'
    finally:
        host.close()
        host.deleteLater()
        QApplication.processEvents()


def test_mode_gates_survive_group_toggle(win):
    """Expanding a collapsed band must not resurrect 3D-only widgets in 2D mode."""
    app = QApplication.instance()
    win._select_param_page(2)
    win.combo_dim.setCurrentIndex(0)
    app.processEvents()
    _tab_idx, band = win._drawer_bands["grid_rect"]
    band.set_expanded(False)
    band.set_expanded(True)
    app.processEvents()
    assert not win.le_Nz.isVisibleTo(win), "3D-only Nz visible in 2D mode"
    win._select_param_page(1)


def test_collapsing_and_resizing_preserves_solver_inputs(win):
    from dataclasses import asdict
    from tm1.applications.gui.ui.window_config import config_from_window

    before = asdict(config_from_window(win))
    for width in (900, 1440):
        win.resize(width, 800)
        for idx in (0, 1, 2):
            win._select_param_page(idx)
            QApplication.processEvents()
            assert asdict(config_from_window(win)) == before
        for _tab_idx, band in win._drawer_bands.values():
            band.set_expanded(False)
        QApplication.processEvents()
        assert asdict(config_from_window(win)) == before
        for _tab_idx, band in win._drawer_bands.values():
            band.set_expanded(True)
        QApplication.processEvents()
        assert asdict(config_from_window(win)) == before
    win._select_param_page(1)


def test_reveal_invalid_input_opens_its_page_and_inspector(win):
    from tm1.applications.gui.ui.ui_builders import reveal_parameter

    win._select_param_page(1)
    win._drawer_bands['grid_rect'][1].set_expanded(False)
    win.appearance.toggle_drawer()
    assert win.inspector_drawer.isHidden()
    reveal_parameter(win, win.le_Nx)
    QApplication.processEvents()
    assert win._param_page == 2
    assert win.le_Nx.isVisibleTo(win)
    assert win.inspector_drawer.isVisibleTo(win)
    assert win._workbench_canvas.isVisibleTo(win)
    assert win.btn_compute.isVisibleTo(win)
    win._select_param_page(1)


@pytest.mark.parametrize('side', ['A', 'B'])
def test_model_visibility_follows_preset_without_changing_inputs(win, side):
    from tm1.applications.gui.ui.window_config import config_from_window

    win.case_files.apply_user_preset({'combos': {'combo_fluidA': 0, 'combo_fluidB': 1}})
    section = win._ia_sections['sco2_nu']
    assert section.isHidden()
    win.case_files.apply_user_preset({
        'combos': {f'combo_fluid{side}': 2},
        'line_edits': {f'le_u{side}': '1.8', f'le_Tin{side}': '360',
                       f'le_Pin{side}': '8000000'},
    })
    assert not section.isHidden()
    fluid = getattr(config_from_window(win), f'fluid_{side}')
    assert (fluid.type, fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa) == (
        'sco2', 1.8, 360., 8e6)
    saved = win.case_files.capture_current_preset('sCO2')
    win.case_files.apply_user_preset({'combos': {'combo_fluidA': 0, 'combo_fluidB': 1}})
    assert section.isHidden()
    win.case_files.apply_user_preset(saved)
    assert not section.isHidden()
    assert getattr(config_from_window(win), f'fluid_{side}') == fluid
    # A selected experimental model remains reachable even without sCO2.
    win.combo_sco2_nu_mode.setCurrentIndex(1)
    getattr(win, f'combo_fluid{side}').setCurrentIndex(0)
    assert not section.isHidden()
    assert win.combo_sco2_nu_mode.currentData() == 'experimental'
    win.combo_sco2_nu_mode.setCurrentIndex(0)


def test_property_preview_keyboard_toggle_keeps_inputs(win):
    from dataclasses import asdict
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from tm1.applications.gui.ui.window_config import config_from_window

    section = win._fluid_computed_A
    header = section.layout().itemAt(0).widget()
    body = section.layout().itemAt(1).widget()
    section._set_expanded(False)
    before = asdict(config_from_window(win))
    header.setFocus()
    QTest.keyClick(header, Qt.Key.Key_Space)
    assert not body.isHidden()
    QTest.keyClick(header, Qt.Key.Key_Space)
    assert body.isHidden()
    assert asdict(config_from_window(win)) == before


# ── ui-shortcuts-persist: workbench shortcuts + session ui_state ──────

def test_shortcut_cheatsheet_matches_workbench(win):
    """Cheat sheet lists Style P2 page labels; retired 5-tab rows gone."""
    labels = [label for label, _key in win.dialogs.SHORTCUT_ROWS]
    joined = " | ".join(labels)
    for want in ("算例计算", "计算结果", "优化设计", "快速设计"):
        assert any(want in s for s in labels), f"missing row for {want}"
    for stale in ("Tab — Temperature", "Tab — Pressure",
                  "Tab — Velocity", "Tab — 3D View"):
        assert stale not in joined, f"retired row survives: {stale}"


def test_cycle_tab_skips_hidden_legacy(win):
    """Ctrl+↑/↓ walks layout→result→pareto→qd; result family collapses to 'result'."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    win.shortcuts.cycle_tab(+1)
    assert win.workbench.active_tab == 'pareto'
    win.shortcuts.cycle_tab(+1)
    assert win.page_stack.currentWidget() is win.quick_design
    win.shortcuts.cycle_tab(+1)
    assert win.workbench.active_tab == 'layout'
    win.cache.clear('2d')
    win.workbench.update_tab_visibility()


def test_toggle_result_view_gated(win):
    """Ctrl+4: in 2D mode with only-2D results the 3D side is gated —
    toggling from a 2D field view is a no-op (stays 2D)."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})  # These layout stubs represent rendered fields.
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')
    assert win.workbench.result_view == '2d'
    win.workbench.toggle_result_view()
    assert win.workbench.result_view == '2d'       # 3D gated → no flip
    win.workbench.switch_tab('layout')
    win.cache.clear('2d')
    win.workbench.update_tab_visibility()


def test_field_menu_revert_is_debranded(win):
    """The field context menu and its status message show no brand name."""
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent

    texts = []

    def choose():
        menu = QApplication.activePopupWidget()
        try:
            texts.extend(action.text() for action in menu.actions())
            next(a for a in menu.actions() if a.text() == '恢复默认算例值').trigger()
        finally:
            menu.close()

    win.le_L.setText('0.1')
    QTimer.singleShot(0, choose)
    win.le_L.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(), QPoint()))
    message = win.dialogs.last_notice
    assert '恢复默认算例值' in texts
    assert '已恢复默认算例值' in message
    assert not any('Shanghai' in text for text in [*texts, message])


def test_session_ui_state_round_trip(win):
    """Save and restore a result card through its group and view."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', ComputeResult())
    win.cache.replace_drawn_tabs({'temp', 'pres', 'vel'})  # These layout stubs represent rendered fields.
    win.workbench.update_tab_visibility()
    win.workbench.switch_tab('temp')               # result family, view '2d'

    captured = {}
    orig_save = win.case_files.store.save_session
    win.case_files.store.save_session = lambda payload, ws: captured.update(payload) or True
    try:
        win.case_files.save_session()
    finally:
        win.case_files.store.save_session = orig_save
    ui = captured.get('ui_state')
    assert ui is not None
    assert ui['active_tab'] == 'result'   # family key collapsed
    assert ui['result_view'] == '2d'
    assert ui['left_collapsed'] in (True, False)

    # Restoring inputs invalidates the old field cache; a saved result tab
    # therefore falls back to layout until this restored case is computed.
    win.workbench.switch_tab('layout')
    orig_load = win.case_files.store.load_session
    win.case_files.store.load_session = lambda ws: dict(captured)
    try:
        win.case_files.restore_session()
    finally:
        win.case_files.store.load_session = orig_load
    assert win.workbench.active_tab == 'layout'
    assert not win.cache.has_results('2d')
    win.workbench.switch_tab('layout')
    win.cache.clear('2d')
    win.workbench.update_tab_visibility()
