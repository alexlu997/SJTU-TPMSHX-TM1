"""Layout-hygiene locks (openspec ui-layout-fixes, 2026-07-03).

1. Param pages never scroll horizontally (labels word-wrap instead of
   widening the grid past the panel viewport).
2. The Fluid A/B ResponsiveRow stacks below its width threshold.
3. The canvas empty state carries the structured 3-step guidance.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QScrollArea  # noqa: E402


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    import sjtu_tpmshx.controllers.session_manager as sm_mod

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
    app = QApplication.instance() or QApplication([])
    from sjtu_tpmshx.main import Main_Menu
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


def test_fluids_row_is_responsive(win):
    from sjtu_tpmshx.ui.responsive import ResponsiveRow
    assert isinstance(getattr(win, "_fluids_row", None), ResponsiveRow)


def test_responsive_row_direction_flips():
    """Standalone instance — a layout-managed widget can't be resized freely
    (the parent layout re-imposes geometry), so the flip is tested on a
    top-level ResponsiveRow."""
    from PySide6.QtWidgets import QLabel
    from sjtu_tpmshx.ui.responsive import ResponsiveRow
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
    assert box is not None and box.isVisibleTo(win)
    txt = " ".join(l.text() for l in box.findChildren(QLabel))
    for marker in (">1<", ">2<", ">3<", "计算"):
        assert marker in txt, f"empty state missing {marker!r}"
    btn = getattr(win, "_empty_state_preset_btn", None)
    assert btn is not None and btn.isVisibleTo(win)


def test_empty_state_preset_button_applies_shanghai(win):
    app = QApplication.instance()
    win._empty_state_preset_btn.click()
    app.processEvents()
    assert getattr(win, "_active_preset_name", None) == "Shanghai (3D Gyroid)"


def test_sticky_cta_outside_scroll(win):
    """btn_compute lives in the fixed bottom bar, not inside the scroll —
    it stays visible however far the params scroll."""
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
    assert getattr(win, "_cta_bar", None) is not None


# ── ui-ia-batch1: four workflow accordion groups ─────────────────────

_EXPECTED_GROUPS = {
    "几何与结构": True,
    "流体": True,
    "网格与求解器": False,
    "边界细节与高级": False,
}


def test_four_workflow_groups_with_default_states(win):
    groups = getattr(win, "_accordion_groups", {})
    assert set(groups) == set(_EXPECTED_GROUPS)
    for name, open_ in _EXPECTED_GROUPS.items():
        assert groups[name].isChecked() == open_, name


def test_left_panel_has_single_scroll_area(win):
    """Nested page scroll shells were dropped — one outer scroll only."""
    outer = win._splitter.widget(0) if hasattr(win, "_splitter") else None
    assert outer is not None
    scrolls = [s for s in outer.findChildren(QScrollArea) if s.isVisible()]
    assert len(scrolls) <= 1, [s.objectName() or repr(s) for s in scrolls]


def test_tpms_computed_collapsed_then_autoexpands(win):
    app = QApplication.instance()
    sec = win._ia_sections["tpms_computed"]
    frame = sec.layout().itemAt(1).widget()
    assert not frame.isVisible()          # starts collapsed
    assert win.compute_tpms()             # default inputs are valid
    app.processEvents()
    # group ① is open, so the expanded card becomes visible-to-window
    assert frame.isVisibleTo(win)
    assert win._v_eps.text() not in ("—", "")


def test_group_badge_counts_empty_field(win):
    """ui-batch3 IA-4: clearing a field inside a collapsed group surfaces
    a ⚠N badge in that group's title; fixing it clears the badge."""
    from sjtu_tpmshx.ui.ui_builders import refresh_group_badges
    grp = win._accordion_groups["网格与求解器"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert "⚠" in grp.title(), grp.title()
    assert win._group_badge_counts["网格与求解器"] >= 1
    win.le_Nx.setText(old or "40")
    refresh_group_badges(win)
    assert "⚠" not in grp.title(), grp.title()


def test_group_badge_updates_via_validator_debounce(win):
    """End-to-end: editingFinished → validator cb → debounce timer →
    badge repaint, without calling refresh directly. Uses le_L — it has a
    validator handler attached (positive+unit field); le_Nx does not."""
    import time
    app = QApplication.instance()
    grp = win._accordion_groups["几何与结构"]
    old = win.le_L.text()
    win.le_L.setText("")
    win.le_L.editingFinished.emit()
    deadline = time.monotonic() + 2.0
    while "⚠" not in grp.title() and time.monotonic() < deadline:
        app.processEvents()
    assert "⚠" in grp.title(), grp.title()
    win.le_L.setText(old or "0.182")
    win.le_L.editingFinished.emit()
    deadline = time.monotonic() + 2.0
    while "⚠" in grp.title() and time.monotonic() < deadline:
        app.processEvents()
    assert "⚠" not in grp.title(), grp.title()


def test_group_badge_survives_toggle(win):
    from sjtu_tpmshx.ui.ui_builders import refresh_group_badges
    grp = win._accordion_groups["网格与求解器"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert "⚠" in grp.title()
    grp.setChecked(True)     # expand — toggle handler re-renders title
    assert "⚠" in grp.title(), "badge wiped by expand"
    grp.setChecked(False)
    assert "⚠" in grp.title(), "badge wiped by collapse"
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
    assert win._resolve_2d_view_card() == 'pres'
    win.combo_2d_field.setCurrentIndex(0)       # reverse path
    assert win._resolve_2d_view_card() == 'temp'


def test_copy_figure_clipboard_no_data_safe(win):
    """No drawn canvas → status message, no exception, clipboard untouched."""
    win._active_tab = 'layout'
    win._drawn_tabs = set()
    win._copy_figure_clipboard()                # must not raise


# ── ui-plan3-workbench T1: three-tab toolbar + result aggregation ────

def test_workbench_toolbar_visible_set(win):
    """Toolbar exposes only the three real workbench tabs."""
    assert win.btn_tab_layout.isVisibleTo(win)
    assert win.btn_tab_result.isVisibleTo(win)
    assert win.btn_tab_pareto.isVisibleTo(win)
    for attr in ('btn_tab_temp', 'btn_tab_pres', 'btn_tab_vel',
                 'btn_tab_3d', 'btn_tab_2d_view'):
        assert not hasattr(win, attr)


def test_legacy_switch_lights_result_button(win):
    """_switch_tab('temp') (the post-compute auto-jump path) must light the
    结果 aggregate button and snap the 2D|3D toggle to 2D.

    `_has_results_2d` is a ResultCache property bridge (writing True is a
    no-op) — seed the cache instead. combo_dim is forced to 2D because the
    earlier preset test leaves the window in 3D mode."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    win._switch_tab('temp')
    assert win._active_tab == 'temp'
    assert win._result_view == '2d'
    assert win.btn_tab_result.styleSheet() == win._PTAB_ON
    win._switch_tab('layout')
    win._has_results_2d = False       # setter clears the cached result
    win._update_tab_visibility()


def test_result_view_toggle_gating(win):
    """2D side of the toggle follows the 2D rule; 3D side needs a ready
    3D view. In 2D mode with results: 2D enabled, 3D disabled."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    assert win._result_view_btns['2d'].isEnabled()
    assert not win._result_view_btns['3d'].isEnabled()
    assert win.btn_tab_result.isEnabled()
    win._has_results_2d = False
    win._update_tab_visibility()
    assert not win.btn_tab_result.isEnabled()


def test_result_summary_toggle_keeps_values_and_tab_choice(win):
    win.combo_dim.setCurrentIndex(0)
    result = {'stub': True}
    win.cache.set_result('2d', result)
    win._has_results = True
    win._update_tab_visibility()
    win._switch_tab('temp')
    assert win.btn_result_summary.isVisibleTo(win)
    assert win._result_sidebar.isVisibleTo(win)
    before = {key: label.text() for key, label in win._sb_labels.items()}
    win.btn_result_summary.click()
    assert win._result_sidebar.isHidden()
    win._switch_tab('layout')
    assert win.btn_result_summary.isHidden()
    win._switch_tab('temp')
    assert win._result_sidebar.isHidden()
    assert {key: label.text() for key, label in win._sb_labels.items()} == before
    win.btn_result_summary.click()
    assert win._result_sidebar.isVisibleTo(win)
    win._invalidate_results_for_preset_load()
    assert win._result_sidebar.isHidden()
    assert win.btn_result_summary.isHidden()


# ── ui-plan-b-wizard: Optimize tab three-page wizard ─────────────────

def test_optimize_wizard_pages(win):
    """Three wizard pages; pills flip the stack; engine stage transitions
    drive the page via _set_stage_pill(state='active')."""
    stack = win._opt_stack
    assert stack.count() == 3
    assert stack.currentIndex() == 0          # starts on 配置
    from sjtu_tpmshx.ui.optimize_panel import _set_stage_pill
    _set_stage_pill(win, 'running', 'active')
    assert stack.currentIndex() == 1
    _set_stage_pill(win, 'result', 'active')
    assert stack.currentIndex() == 2
    _set_stage_pill(win, 'config', 'active')
    assert stack.currentIndex() == 0


def test_optimize_inline_params_complete(win):
    """Page-1 inline params carry every key the launch path consumes —
    the modal dialog is only the fallback for hosts without the wizard."""
    keys = set(win._opt_inline_params)
    assert keys == {'n_init', 'n_iter', 'q_batch', 'seed', 'n_rho_loops'}
    for sp in win._opt_inline_params.values():
        assert sp.value() > 0 or sp.value() == 0   # constructed + in range


def test_optimize_zone_panel_in_wizard(win):
    """The zone panel lives inside wizard page 1 (the old splitter is
    retired)."""
    p1 = win._opt_stack.widget(0)
    assert win._zone_panel.isVisibleTo(p1) or p1.isAncestorOf(win._zone_panel)


def test_optimize_controls_fit_narrow_viewport(win):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    win.resize(1100, 760)
    win._switch_tab('pareto')
    viewport = win._canvas_scroll.viewport()
    for page, widgets in (
        (0, list(win._opt_inline_params.values()) + list(win._opt_space_params.values())),
        (1, [win._opt_kpi_gen, win._opt_kpi_q, win._opt_kpi_dp, win._opt_kpi_eta]),
    ):
        win._opt_stack.setCurrentIndex(page)
        QTest.qWait(30)
        for widget in widgets:
            position = viewport.mapFromGlobal(widget.mapToGlobal(QPoint()))
            assert position.x() >= 0
            assert position.x() + widget.width() <= viewport.width()
    win._opt_stack.setCurrentIndex(0)
    win._switch_tab('layout')
    win.resize(1600, 1000)


# ── ui-plan3a: design-token discipline ───────────────────────────────

_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "ui")

# Micro-controls whose radius is proportional to the element (sliders,
# checkbox indicators, progress chunks, scrollbar handles) and semantic
# pills/toasts are exempt — see theme.py radius policy comment.
_RADIUS_EXEMPT_FILES = {"panel_vis_3d.py", "theme.py"}


def _ui_sources():
    import glob
    for p in (glob.glob(os.path.join(_UI_DIR, "*.py"))
              + glob.glob(os.path.join(_UI_DIR, "mixins", "*.py"))):
        yield p, open(p, encoding="utf-8").read()


def test_no_stray_card_radii():
    """Card/control-level radii are 6px; 8/10/12px strays are regressions.
    Pills (14/18) and micro-controls (1-3px on tiny elements) are exempt."""
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
    `t.get('x', '#…')`, glass_panel's dark-art gradient, microanim's deep
    glow hints, docstrings/comments."""
    import re
    allow_files = {"theme.py", "glass_panel.py"}
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


def test_numeric_inputs_right_aligned(win):
    from PySide6.QtCore import Qt as _Qt
    assert win.le_L.alignment() & _Qt.AlignmentFlag.AlignRight
    assert win.le_Nx.alignment() & _Qt.AlignmentFlag.AlignRight


def test_mode_gates_survive_group_toggle(win):
    """Expanding a collapsed group must not resurrect 3D-only widgets in
    2D mode (blanket-show + re-assert)."""
    app = QApplication.instance()
    win.combo_dim.setCurrentIndex(0)      # force 2D
    app.processEvents()
    grp = win._accordion_groups["网格与求解器"]
    grp.setChecked(True)
    app.processEvents()
    assert not win.le_Nz.isVisibleTo(win), "3D-only Nz visible in 2D mode"
    grp.setChecked(False)
    app.processEvents()


def test_collapsing_and_resizing_preserves_solver_inputs(win):
    from dataclasses import asdict
    from sjtu_tpmshx.ui.window_config import config_from_window

    before = asdict(config_from_window(win))
    for width in (900, 1440):
        win.resize(width, 800)
        for group in win._accordion_groups.values():
            group.setChecked(False)
        QApplication.processEvents()
        assert asdict(config_from_window(win)) == before
        for group in win._accordion_groups.values():
            group.setChecked(True)
        QApplication.processEvents()
        assert asdict(config_from_window(win)) == before
    for name, expanded in _EXPECTED_GROUPS.items():
        win._accordion_groups[name].setChecked(expanded)


@pytest.mark.parametrize('side', ['A', 'B'])
def test_model_visibility_follows_preset_without_changing_inputs(win, side):
    from sjtu_tpmshx.ui.window_config import config_from_window

    win._apply_user_preset({'combos': {'combo_fluidA': 0, 'combo_fluidB': 1}})
    section = win._ia_sections['sco2_nu']
    assert section.isHidden()
    win._apply_user_preset({
        'combos': {f'combo_fluid{side}': 2},
        'line_edits': {f'le_u{side}': '1.8', f'le_Tin{side}': '360',
                       f'le_Pin{side}': '8000000'},
    })
    assert not section.isHidden()
    fluid = getattr(config_from_window(win), f'fluid_{side}')
    assert (fluid.type, fluid.u_mps, fluid.T_in_K, fluid.P_in_Pa) == (
        'sco2', 1.8, 360., 8e6)
    saved = win._capture_current_preset('sCO2')
    win._apply_user_preset({'combos': {'combo_fluidA': 0, 'combo_fluidB': 1}})
    assert section.isHidden()
    win._apply_user_preset(saved)
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
    from sjtu_tpmshx.ui.window_config import config_from_window

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
    """Cheat sheet lists the visible 3-tab set; retired 5-tab rows gone."""
    labels = [label for label, _key in win._SHORTCUT_ROWS]
    joined = " | ".join(labels)
    for want in ("几何布局", "结果", "优化"):
        assert any(want in s for s in labels), f"missing row for {want}"
    for stale in ("Tab — Temperature", "Tab — Pressure",
                  "Tab — Velocity", "Tab — 3D View"):
        assert stale not in joined, f"retired row survives: {stale}"


def test_cycle_tab_skips_hidden_legacy(win):
    """Ctrl+↑/↓ walks layout→result→pareto; a result-family current tab
    maps to 'result' so cycling never lands on hidden legacy buttons."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    win._switch_tab('temp')               # result family
    win._cycle_tab(+1)
    assert win._active_tab == 'pareto'
    win._cycle_tab(+1)
    assert win._active_tab == 'layout'
    win._has_results_2d = False
    win._update_tab_visibility()


def test_toggle_result_view_gated(win):
    """Ctrl+4: in 2D mode with only-2D results the 3D side is gated —
    toggling from a 2D field view is a no-op (stays 2D)."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    win._switch_tab('temp')
    assert win._result_view == '2d'
    win._toggle_result_view()
    assert win._result_view == '2d'       # 3D gated → no flip
    win._switch_tab('layout')
    win._has_results_2d = False
    win._update_tab_visibility()


def test_no_shanghai_string_in_visible_ui_sources():
    """De-branding lock: no user-visible 'Shanghai' literal in the UI
    surfaces that render text (field_menu context actions / status)."""
    import pathlib
    ui_dir = pathlib.Path(__file__).resolve().parents[1] / 'ui'
    src = (ui_dir / 'field_menu.py').read_text(encoding='utf-8')
    assert 'Revert to Shanghai' not in src
    assert 'reverted to Shanghai' not in src


def test_session_ui_state_round_trip(win):
    """_save_session stores ui_state (family key collapsed to 'result');
    _restore_session re-applies result_view + active_tab."""
    win.combo_dim.setCurrentIndex(0)
    win.cache.set_result('2d', {'stub': True})
    win._update_tab_visibility()
    win._switch_tab('temp')               # result family, view '2d'

    captured = {}
    orig_save = win.sm.save_session
    win.sm.save_session = lambda payload, ws: captured.update(payload) or True
    try:
        win._save_session()
    finally:
        win.sm.save_session = orig_save
    ui = captured.get('ui_state')
    assert ui is not None
    assert ui['active_tab'] == 'result'   # family key collapsed
    assert ui['result_view'] == '2d'
    assert ui['left_collapsed'] in (True, False)

    # Restore path: feed the captured payload back and confirm the tab
    # resolves through 'result' (→ a 2D field card) again.
    win._switch_tab('layout')
    orig_load = win.sm.load_session
    win.sm.load_session = lambda ws: dict(captured)
    try:
        win._restore_session()
    finally:
        win.sm.load_session = orig_load
    assert win._active_tab in ('temp', 'pres', 'vel')
    win._switch_tab('layout')
    win._has_results_2d = False
    win._update_tab_visibility()
