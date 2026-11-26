"""Canvas-area builder: Style P2 floating toolbar, colormap popover, and canvas cards."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .builders_base import MenuToolButton
from .builders_sidebar import update_result_sidebar_visibility
from .colormap_popover import ColormapPopover
from .icons import icon
from .matplotlib_canvas import MatplotlibCanvas
from .responsive import ResponsiveRow
from .theme import (
    RADIUS_BTN,
    RADIUS_CARD,
    RADIUS_INPUT,
    get_theme,
    resolve_cmap,
    set_cmap,
)

_TAB_TO_QUANTITY = {
    "temp": ("temperature", "温度"),
    "vel": ("speed", "速度"),
    "pres": ("pressure", "压力"),
}


_3D_FIELD_TO_QUANTITY = {
    "T_fA": ("temperature", "温度"),
    "T_fB": ("temperature", "温度"),
    "T_s": ("temperature", "温度"),
    "P_fA": ("pressure", "压力"),
    "P_fB": ("pressure", "压力"),
    "U_mag_A": ("speed", "速度"),
    "U_mag_B": ("speed", "速度"),
}


def _active_cmap_quantity(window) -> tuple[str, str]:
    tab = window.workbench.active_tab
    if tab == "3d":
        panel = getattr(window, "canvas_3d", None)
        field_3d = getattr(panel, "_field", None) if panel is not None else None
        if field_3d in _3D_FIELD_TO_QUANTITY:
            return _3D_FIELD_TO_QUANTITY[field_3d]
    if tab in _TAB_TO_QUANTITY:
        return _TAB_TO_QUANTITY[tab]
    card = window.workbench.resolve_2d_view_card()
    return _TAB_TO_QUANTITY.get(card, ("temperature", "温度"))


def _apply_colormap_refresh(window) -> None:
    """Propagate an accepted colormap update to 2D fields, 2D thumbnail, and 3D view."""
    from .layout_drawer import refresh_last_2d_thumbnail
    from .plot_2d_results import redraw_result_fields

    redraw_result_fields(window)
    refresh_last_2d_thumbnail(window)
    panel_3d = getattr(window, "canvas_3d", None)
    if panel_3d is not None and hasattr(panel_3d, "refresh_colormaps"):
        panel_3d.refresh_colormaps()


def _open_colormap_popover(window) -> None:
    """Open the Style P2 ColormapPopover below the 色阶 toolbar button."""
    qty_key, qty_label = _active_cmap_quantity(window)
    pop = getattr(window, "_colormap_popover", None)
    if pop is None:
        pop = ColormapPopover(
            quantity_label=qty_label,
            current_colormap=resolve_cmap(qty_key),
            sync_temp_scale=window.chk_sync_colorbar_T.isChecked(),
            shared_pressure_scale=window.chk_shared_pressure_scale.isChecked(),
            parent=window,
        )

        def _on_select(cmap_name: str) -> None:
            q_key, _ = _active_cmap_quantity(window)
            if not set_cmap(q_key, cmap_name, persist=True):
                pop.set_colormap(resolve_cmap(q_key))
                QMessageBox.warning(
                    window, "设置未保存", "无法写入色阶设置，请检查用户配置目录。"
                )
                return
            _apply_colormap_refresh(window)
            window.statusBar().showMessage(f"已切换色阶：{cmap_name}", 3000)

        def _on_reset() -> None:
            q_key, _ = _active_cmap_quantity(window)
            if not set_cmap(q_key, None, persist=True):
                pop.set_colormap(resolve_cmap(q_key))
                QMessageBox.warning(
                    window, "设置未保存", "无法重置色阶设置，请检查用户配置目录。"
                )
                return
            pop.set_colormap(resolve_cmap(q_key))
            _apply_colormap_refresh(window)
            window.statusBar().showMessage("已恢复默认色阶", 3000)

        pop.colormap_selected.connect(_on_select)
        pop.sync_temp_scale_changed.connect(window.chk_sync_colorbar_T.setChecked)
        pop.shared_pressure_scale_changed.connect(window.chk_shared_pressure_scale.setChecked)
        pop.reset_requested.connect(_on_reset)
        window._colormap_popover = pop
    else:
        pop.apply_theme(get_theme())
        pop.set_quantity_label(qty_label)
        pop.set_colormap(resolve_cmap(qty_key))
        pop.set_sync_temp_scale(window.chk_sync_colorbar_T.isChecked())
        pop.set_shared_pressure_scale(window.chk_shared_pressure_scale.isChecked())

    pop.popup_below(window.btn_colormap)


def _attach_canvas_menu(window, btn, key: str) -> None:
    btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _open_ctx(pos):
        menu = QMenu(btn)
        detached = window.workbench.detached_canvases.get(key) is not None
        if detached:
            act = menu.addAction("放回主窗口")
            act.triggered.connect(lambda _c=False, k=key: window.workbench.reattach_canvas(k))
        else:
            act = menu.addAction("在新窗口中打开")
            act.triggered.connect(lambda _c=False, k=key: window.workbench.detach_canvas(k))
        menu.exec(btn.mapToGlobal(pos))

    btn.customContextMenuRequested.connect(_open_ctx)


def _build_canvas_toolbar(window, vlay, t, theme):
    """Build Style P2 floating canvas controls for case layout and results."""
    _t = theme

    toolbar_host = ResponsiveRow(threshold=680, spacing=8)
    toolbar_host.layout().setContentsMargins(14, 10, 14, 4)
    primary_controls = QWidget()
    toolbar = QHBoxLayout(primary_controls)
    toolbar.setSpacing(6)
    toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    toolbar.setContentsMargins(0, 0, 0, 0)

    view_controls = QWidget()
    view_toolbar = QHBoxLayout(view_controls)
    view_toolbar.setContentsMargins(0, 0, 0, 0)
    view_toolbar.setSpacing(6)
    view_toolbar.setAlignment(Qt.AlignmentFlag.AlignRight)

    toolbar_host.addWidget(primary_controls)
    toolbar_host.addWidget(view_controls)
    window._field_toolbar = toolbar_host
    window._field_primary_controls = primary_controls

    seg_shell_qss = (
        f"QFrame {{ background: {_t['sunken']}; border: 1px solid {_t['border']}; "
        f"border-radius: {RADIUS_BTN}px; }}"
    )
    seg_on_qss = (
        f"QPushButton {{ background: {_t['seg_on']}; color: {_t['fg']}; "
        f"border: 1px solid {_t['border']}; border-radius: 5px; "
        "padding: 2px 10px; font-size: 9.5pt; font-weight: 600; }"
    )
    seg_off_qss = (
        f"QPushButton {{ background: transparent; color: {_t['sub']}; "
        "border: none; border-radius: 5px; padding: 2px 10px; "
        "font-size: 9.5pt; font-weight: 400; }"
        f"QPushButton:hover {{ color: {_t['fg']}; }}"
        f"QPushButton:disabled {{ color: {_t['tab_disabled_fg']}; }}"
    )

    # Hidden 2D-field combo remains the shared state source for 2D field routing.
    window.combo_2d_field = QComboBox(window)
    window.combo_2d_field.addItems(["Temperature", "Velocity |U|", "Pressure"])
    window.combo_2d_field.setEnabled(False)
    window.combo_2d_field.hide()

    def _on_2d_field_changed(_idx):
        if window.workbench.active_tab in ("temp", "pres", "vel", "2d_view"):
            window.workbench.switch_tab("2d_view")
        _paint_2d_seg()

    window.combo_2d_field.currentIndexChanged.connect(_on_2d_field_changed)

    # Segmented 2D quantity selector: 温度 | 速度 | 压力
    field_seg = QFrame()
    field_seg.setStyleSheet(seg_shell_qss)
    seg_lay = QHBoxLayout(field_seg)
    seg_lay.setContentsMargins(2, 2, 2, 2)
    seg_lay.setSpacing(2)
    window._2d_field_btns = []
    for i, cap in enumerate(("温度", "速度", "压力")):
        btn = QPushButton(cap)
        btn.setFixedHeight(24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("单击切换 2D 显示物理量")
        btn.clicked.connect(lambda _c=False, idx=i: window.combo_2d_field.setCurrentIndex(idx))
        seg_lay.addWidget(btn)
        window._2d_field_btns.append(btn)
        _attach_canvas_menu(window, btn, ("temp", "vel", "pres")[i])

    def _paint_2d_seg():
        cur = window.combo_2d_field.currentIndex()
        for j, b in enumerate(window._2d_field_btns):
            b.setStyleSheet(seg_on_qss if j == cur else seg_off_qss)

    _paint_2d_seg()
    window._2d_field_seg = field_seg
    window._paint_2d_seg = _paint_2d_seg
    field_seg.hide()

    # Segmented phase selector: 流体 A | 流体 B | 固体 | 全部
    window._field_phase = getattr(window, "_field_phase", None)
    window._field_phase_seg = QFrame()
    window._field_phase_seg.setStyleSheet(seg_shell_qss)
    phase_row = QHBoxLayout(window._field_phase_seg)
    phase_row.setContentsMargins(2, 2, 2, 2)
    phase_row.setSpacing(2)
    window._field_phase_btns = []
    window._field_phase_values = (0, 1, 2, None)
    for label, phase_val in (("流体 A", 0), ("流体 B", 1), ("固体", 2), ("全部", None)):
        button = QPushButton(label)
        button.setFixedHeight(24)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("显示该相或全部相的真实计算场；不会重新求解")

        def _pick_phase(_checked=False, pv=phase_val):
            window._field_phase = pv
            refresh_field_controls(window)
            from .plot_2d_results import redraw_result_fields

            redraw_result_fields(window)

        button.clicked.connect(_pick_phase)
        phase_row.addWidget(button)
        window._field_phase_btns.append(button)
    window._phase_styles = (seg_on_qss, seg_off_qss)
    window._field_phase_seg.hide()

    # Segmented result view switch: 场图 | 三维
    rv_seg = QFrame()
    window._result_view_switch = rv_seg
    rv_seg.setObjectName("resultViewSwitch")
    rv_seg.setStyleSheet(seg_shell_qss)
    rv_lay = QHBoxLayout(rv_seg)
    rv_lay.setContentsMargins(2, 2, 2, 2)
    rv_lay.setSpacing(2)
    view_qss = (
        f"QPushButton {{ border: 1px solid transparent; border-radius: 5px; "
        f"padding: 2px 10px; font-size: 9.5pt; color: {_t['sub']}; background: transparent; }}"
        f"QPushButton:checked {{ background: {_t['seg_on']}; color: {_t['fg']}; "
        f"border: 1px solid {_t['border']}; font-weight: 600; }}"
        f"QPushButton:hover:!checked {{ color: {_t['fg']}; }}"
        f"QPushButton:disabled {{ color: {_t['tab_disabled_fg']}; background: transparent; }}"
    )
    window._result_view_btns = {}
    for key, cap in (("2d", "场图"), ("3d", "三维")):
        b = QPushButton(cap)
        b.setFixedHeight(24)
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(view_qss)
        b.setToolTip("切换结果显示方式（Ctrl+4），不改变计算维度或重新求解。")
        b.setEnabled(False)

        def _pick_view(_c=False, k=key):
            window.workbench.result_view = k
            window.workbench.switch_tab("result")
            window._paint_result_seg()

        b.clicked.connect(_pick_view)
        rv_lay.addWidget(b)
        window._result_view_btns[key] = b

    btn_3d_view = window._result_view_btns["3d"]
    btn_3d_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _open_3d_ctx(pos):
        menu = QMenu(btn_3d_view)
        if window.workbench.detached_volume is None:
            act = menu.addAction("在新窗口中打开三维视图")
            act.triggered.connect(window.workbench.detach_3d_window)
        else:
            act = menu.addAction("放回主窗口")
            act.triggered.connect(window.workbench.reattach_3d_window)
        menu.exec(btn_3d_view.mapToGlobal(pos))

    btn_3d_view.customContextMenuRequested.connect(_open_3d_ctx)

    def _paint_result_seg():
        cur = window.workbench.result_view
        for k, b in window._result_view_btns.items():
            b.setChecked(k == cur)

    _paint_result_seg()
    window._paint_result_seg = _paint_result_seg
    rv_seg.hide()

    # Hidden pressure-scale & temp-sync state checkboxes controlled via ColormapPopover.
    window.chk_shared_pressure_scale = QCheckBox("压力共用色阶", window)
    window.chk_shared_pressure_scale.setChecked(True)
    window.chk_shared_pressure_scale.hide()

    def _set_pressure_scale():
        from .plot_2d_results import redraw_result_fields

        redraw_result_fields(window)

    window.chk_shared_pressure_scale.toggled.connect(_set_pressure_scale)

    window.chk_sync_colorbar_T = QCheckBox("各相使用相同温标", window)
    window.chk_sync_colorbar_T.setChecked(True)
    window.chk_sync_colorbar_T.hide()
    window.chk_sync_colorbar_T.toggled.connect(lambda _on: window._redraw_temp_if_ready())

    # Colormap popover trigger (色阶)
    window.btn_colormap = QPushButton("色阶 ▾")
    window.btn_colormap.setFixedHeight(28)
    window.btn_colormap.setCursor(Qt.CursorShape.PointingHandCursor)
    window.btn_colormap.setStyleSheet(t.style("BTN_TERTIARY"))
    window.btn_colormap.setToolTip("调整色阶配色、温度共用标尺与压力共用色阶")
    window.btn_colormap.clicked.connect(lambda: _open_colormap_popover(window))
    window.btn_colormap.hide()

    # Case-layout quick jump to results ("查看计算结果")
    window.btn_view_result = QPushButton("查看计算结果")
    window.btn_view_result.setFixedHeight(28)
    window.btn_view_result.setCursor(Qt.CursorShape.PointingHandCursor)
    window.btn_view_result.setStyleSheet(t.style("BTN_TERTIARY"))
    window.btn_view_result.setIcon(icon("layers", _t["sub"]))
    window.btn_view_result.setIconSize(QSize(15, 15))
    window.btn_view_result.setEnabled(False)
    window.btn_view_result.setToolTip("跳转到本次计算结果（Ctrl+2）")
    window.btn_view_result.clicked.connect(lambda: window.workbench.switch_tab("result"))

    toolbar.addWidget(field_seg)
    toolbar.addWidget(window._field_phase_seg)
    toolbar.addWidget(rv_seg)
    toolbar.addWidget(window.btn_colormap)
    toolbar.addWidget(window.btn_view_result)
    toolbar.addStretch(1)

    window.btn_result_summary = QPushButton("摘要")
    window.btn_result_summary.setFixedHeight(28)
    window.btn_result_summary.setCheckable(True)
    window.btn_result_summary.setChecked(True)
    window.btn_result_summary.setCursor(Qt.CursorShape.PointingHandCursor)
    window.btn_result_summary.setStyleSheet(
        t.style("BTN_TERTIARY")
        + f"QPushButton:checked {{ color: {_t['fg']}; border-color: {_t['accent']}; }}"
    )
    window.btn_result_summary.setToolTip("显示或收起底部读数条")
    window.btn_result_summary.toggled.connect(
        lambda _checked: update_result_sidebar_visibility(window)
    )
    window.btn_result_summary.hide()
    view_toolbar.addWidget(window.btn_result_summary)

    btn_reset_view = QPushButton("适应视图")
    btn_reset_view.setFixedHeight(28)
    btn_reset_view.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_reset_view.setStyleSheet(t.style("BTN_TERTIARY"))
    btn_reset_view.setIcon(icon("fit-view", _t["sub"]))
    btn_reset_view.setIconSize(QSize(15, 15))
    btn_reset_view.setToolTip("让当前画布适应可用空间")
    btn_reset_view.clicked.connect(lambda: canvas_zoom_reset(window))
    view_toolbar.addWidget(btn_reset_view)

    window.btn_focus_view = QPushButton("专注")
    window.btn_focus_view.setFixedHeight(28)
    window.btn_focus_view.setCheckable(True)
    window.btn_focus_view.setCursor(Qt.CursorShape.PointingHandCursor)
    window.btn_focus_view.setStyleSheet(t.style("BTN_TERTIARY"))
    window.btn_focus_view.setIcon(icon("maximize", _t["sub"]))
    window.btn_focus_view.setIconSize(QSize(15, 15))
    window.btn_focus_view.setToolTip("收起检查器与读数条，专注当前画布（F）")
    window.btn_focus_view.clicked.connect(window.appearance.toggle_focus)
    view_toolbar.addWidget(window.btn_focus_view)

    btn_export = MenuToolButton(t.style("BTN_TERTIARY"))
    btn_export.setText("导出")
    btn_export.setIcon(icon("download", _t["sub"]))
    btn_export.setToolTip("导出计算结果（CSV + NPZ）或当前图像（PNG / SVG / PDF）")
    btn_export.setEnabled(False)
    ex_menu = QMenu(btn_export)
    ex_menu.setStyleSheet(
        f"QMenu {{ background: {_t['popover']}; color: {_t['fg']}; "
        f"border: 1px solid {_t['border_strong']}; border-radius: {RADIUS_INPUT}px; padding: 4px; }}"
        "QMenu::item { padding: 6px 18px; border-radius: 5px; }"
        f"QMenu::item:selected {{ background: {_t['accent_soft']}; color: {_t['accent_fg']}; }}"
    )
    ex_menu.addAction("导出完整结果 — CSV + NPZ", window.result_export.export_results)
    ex_menu.addAction("导出图像 — PNG / SVG / PDF", window.result_export.export_figure)
    ex_menu.addAction("复制当前图像", window.result_export.copy_figure_clipboard)
    btn_export.setMenu(ex_menu)
    window.btn_export = btn_export
    view_toolbar.addWidget(btn_export)

    vlay.addWidget(toolbar_host)


def refresh_field_controls(window):
    """Refresh floating toolbar controls for the active workbench page."""
    tab = window.workbench.active_tab
    optimizing = tab == "pareto"
    is_result = tab in ("temp", "pres", "vel", "3d")
    is_field = tab in ("temp", "pres", "vel")

    window.appearance.sync_drawer_visibility()
    card = getattr(window, "_run_status_card", None)
    if card is not None:
        card.setVisible(
            (not optimizing and not window.appearance.is_focused())
            or not window.single_run.is_idle()
        )

    window._field_toolbar.setVisible(True)
    window._field_primary_controls.setVisible(not optimizing)
    if hasattr(window, "_2d_field_seg"):
        window._2d_field_seg.setVisible(is_result)
    window._result_view_switch.setVisible(is_result)
    window.btn_colormap.setVisible(is_result)
    window.btn_view_result.setVisible(tab == "layout")
    if hasattr(window, "btn_update_geometry"):
        window.btn_update_geometry.setVisible(tab == "layout")
    if optimizing:
        window.optimization.refresh_setup()

    result = window.cache.get_result("3d")
    b_source = "dir_B" if tab in ("pres", "vel") else "Tb"
    has_b = result is None or result.fields.get(b_source) is not None
    phase = getattr(window, "_field_phase", None)
    if (tab in ("pres", "vel") and phase == 2) or (phase == 1 and not has_b):
        phase = window._field_phase = 0
        from .plot_2d_results import redraw_result_fields

        redraw_result_fields(window)
    window._field_phase_seg.setVisible(is_result)
    phase_values = getattr(window, "_field_phase_values", (0, 1, 2))
    for i, btn in enumerate(window._field_phase_btns):
        pv = phase_values[i] if i < len(phase_values) else i
        btn.setVisible(pv != 2 or tab in ("temp", "3d"))
        btn.setEnabled(pv != 1 or has_b)
        active = phase == pv
        btn.setChecked(active)
        btn.setStyleSheet(window._phase_styles[0 if active else 1])

    slice_controls = getattr(window, "_slice_controls", None)
    if slice_controls is not None:
        slice_controls.setVisible(is_field and result is not None)


def _build_compute_progress(window, vlay, theme):
    """Build the slim top progress line."""
    window.progress = QProgressBar()
    window.progress.setFixedHeight(3)
    window.progress.setTextVisible(False)
    window.progress.setStyleSheet(
        "QProgressBar { background: transparent; border: none; }"
        f"QProgressBar::chunk {{ background: {theme['prog_chunk']}; border-radius: 1px; }}"
    )
    window.progress.setValue(0)
    window.progress.hide()
    vlay.addWidget(window.progress)


def _build_canvas_content(window, vlay, t):
    """Build scrollable plot cards inside the Style P2 sheet."""
    _t = get_theme()

    window._canvas_scroll = QScrollArea()
    window._canvas_scroll.setWidgetResizable(True)
    window._canvas_scroll.setStyleSheet(
        f"QScrollArea {{ border: none; background: {_t['canvas']}; }}" + t.style("SCROLLBAR")
    )
    window._canvas_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    canvas_container = QWidget()
    canvas_container.setStyleSheet(f"background: {_t['canvas']};")
    canvas_lay = QGridLayout(canvas_container)
    canvas_lay.setContentsMargins(10, 6, 10, 10)
    canvas_lay.setHorizontalSpacing(10)
    canvas_lay.setVerticalSpacing(12)
    window._canvas_lay = canvas_lay

    _acc = _t["accent_fg"]
    _sub = _t["sub"]
    _empty = QLabel(
        "<div style='text-align:left;'>"
        f"<p style='color:{_t['fg']}; font-size:12pt; font-weight:600; margin:0 0 14px 0;'>"
        "运行第一个算例</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc}; font-weight:700;'>1</span>"
        "&nbsp;&nbsp;在右侧检查器设置几何、边界与求解参数</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc}; font-weight:700;'>2</span>"
        "&nbsp;&nbsp;点击右上角 <b>开始计算</b>（Ctrl+R）运行求解</p>"
        f"<p style='margin:0;'><span style='color:{_acc}; font-weight:700;'>3</span>"
        "&nbsp;&nbsp;在“计算结果”查看温度 / 速度 / 压力场图与三维视图</p>"
        "</div>"
    )
    _empty.setTextFormat(Qt.TextFormat.RichText)
    _empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    _empty.setStyleSheet(
        f"color: {_sub}; background: transparent; border: none; font-size: 10pt; padding: 0;"
    )

    _empty_box = QWidget()
    _empty_box.setObjectName("emptyStateCard")
    _empty_box.setStyleSheet(
        f"QWidget#emptyStateCard {{ background: {_t['panel']}; "
        f"border: 1px solid {_t['border']}; border-radius: {RADIUS_CARD}px; }}"
    )
    eb_lay = QVBoxLayout(_empty_box)
    eb_lay.setContentsMargins(40, 36, 40, 32)
    eb_lay.setSpacing(16)
    eb_lay.addWidget(_empty)

    btn_preset = QPushButton("载入默认算例")
    btn_preset.setMinimumHeight(30)
    btn_preset.setStyleSheet(t.style("BTN_SECONDARY"))
    btn_preset.setToolTip("载入内置上海基准算例（3D Gyroid）")
    btn_preset.clicked.connect(lambda: window.case_files.load_named_preset("Shanghai (3D Gyroid)"))
    eb_lay.addWidget(btn_preset, 0, Qt.AlignmentFlag.AlignHCenter)
    _empty_box.setMaximumWidth(620)
    canvas_lay.addWidget(
        _empty_box, 0, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
    )
    window._empty_state_label = _empty_box
    window._empty_state_preset_btn = btn_preset

    window.canvas_temp = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_pres = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_vel = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_layout = MatplotlibCanvas(1, 1, figsize=(10.5, 6.8))
    window.canvas_3d = None

    import os as _os

    if _os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen" or _os.environ.get(
        "TPMSHX_DISABLE_3D_PANEL", ""
    ).lower() in ("1", "true", "yes"):
        window.workbench.import_error = "headless/offscreen — 3D panel skipped"

    window._canvas_default_h = {}
    window._canvas_cards = {}
    card_specs = [
        (window.canvas_temp, "temp", 440),
        (window.canvas_pres, "pres", 440),
        (window.canvas_vel, "vel", 440),
        (window.canvas_layout, "layout", 640),
        (window.optimization.pareto_canvas, "pareto", 880),
    ]
    window._canvas_3d_placeholder = QWidget()
    card_specs.append((window._canvas_3d_placeholder, "3d", 1100))

    card_row_order = []
    for c, key, h in card_specs:
        if key in ("temp", "pres", "vel"):
            c.fig.set_layout_engine("compressed")
        card = QFrame()
        card.setObjectName("plotCard")
        card.setStyleSheet("QFrame#plotCard { background: transparent; border: none; }")
        card_lay = QVBoxLayout(card)
        if key == "3d":
            from PySide6.QtWidgets import QLayout

            card_lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        card_lay.setContentsMargins(4, 4, 4, 4)
        card_lay.setSpacing(0)

        if key == "pareto":
            card_lay.addWidget(window.optimization)
        else:
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card_lay.addWidget(c)

        if key == "3d":
            try:
                from .skeleton import Skeleton as _Sk

                skel = _Sk(parent=c)
                skel.setGeometry(0, 0, max(1, c.width()), max(1, c.height()))
                prev_resize = c.resizeEvent

                def _on_resize(ev, s=skel, cv=c, prev=prev_resize):
                    s.setGeometry(0, 0, max(1, cv.width()), max(1, cv.height()))
                    if prev is not None:
                        prev(ev)

                c.resizeEvent = _on_resize
                skel.start()
                window._3d_skeleton = skel
            except Exception:
                pass

        if key == "pareto":
            card.setMinimumHeight(460)
        else:
            card.setFixedHeight(h + 24)
        card_row_order.append((key, card))
        window._canvas_default_h[key] = h + 24
        window._canvas_cards[key] = card
        if key != "3d":
            c.wheelEvent = lambda evt, k=key: canvas_wheel_zoom(window, evt, k)

    window._canvas_card_order = [k for k, _ in card_row_order]
    _relayout_canvas_cards(window, 1)

    for c in (
        window.canvas_temp,
        window.canvas_pres,
        window.canvas_vel,
        window.canvas_layout,
        window.optimization.pareto_canvas,
    ):
        c.fig.clear()
        c.fig.patch.set_facecolor(_t["fig_bg"])
        c.draw()

    for key in list(window._canvas_cards):
        window._canvas_cards[key].hide()
    window.cache.clear()

    window._canvas_scroll.setWidget(canvas_container)
    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(4)
    body.addWidget(window._canvas_scroll, 1)

    slice_controls = QWidget()
    slice_row = QHBoxLayout(slice_controls)
    slice_row.setContentsMargins(24, 0, 24, 4)
    slice_row.setSpacing(12)
    slice_row.addWidget(QLabel("截面 z"))
    window._slice_slider = QSlider(Qt.Orientation.Horizontal)
    window._slice_slider.setTracking(False)
    window._slice_slider.setToolTip("显示已计算的真实网格截面，不重新求解")
    window._slice_slider.setStyleSheet(
        f"QSlider::groove:horizontal {{ background: {_t['border']}; height: 4px; }}"
        f"QSlider::handle:horizontal {{ background: {_t['accent']}; "
        "width: 14px; margin: -5px 0; border-radius: 7px; }"
    )

    def _select_slice(index):
        window._slice_index = index
        from .plot_2d_results import redraw_result_fields

        redraw_result_fields(window)

    window._slice_slider.valueChanged.connect(_select_slice)
    slice_row.addWidget(window._slice_slider, 1)
    window._slice_label = QLabel()
    slice_row.addWidget(window._slice_label)
    window._slice_controls = slice_controls
    slice_controls.hide()
    body.addWidget(slice_controls)

    from .run_status import RunStatusCard

    window._run_status_card = RunStatusCard()
    window._run_status_card.cancel_requested.connect(window.single_run.cancel)
    window._run_status_card.pause_requested.connect(window.single_run.pause)
    window._run_status_card.log_requested.connect(window.dialogs.show_solve_log)
    body.addWidget(window._run_status_card)
    vlay.addLayout(body, 1)


def _connect_canvas_interactions(window, vlay, theme):
    """Attach viewport sizing and hover coordinate readout."""
    _t = theme

    def _fit_3d_card_to_viewport():
        sc = getattr(window, "_canvas_scroll", None)
        if sc is None:
            return
        vh = sc.viewport().height()
        for key in ("temp", "pres", "vel", "layout", "3d", "pareto"):
            card = window._canvas_cards.get(key)
            if card is not None and card.isVisible() and vh > 24:
                height = vh - 18
                if key == "pareto":
                    stack = window.optimization.stack
                    page = stack.currentWidget()
                    stack.setMinimumHeight(
                        max(page.minimumSizeHint().height(), page.heightForWidth(page.width()))
                    )
                    height = max(height, card.minimumSizeHint().height())
                if key == "3d":
                    height = max(height, card.minimumSizeHint().height())
                factor = getattr(window, "_canvas_zoom_factors", {}).get(key, 1.0)
                window._canvas_default_h[key] = height
                card.setFixedHeight(int(height * factor))

    window._fit_3d_card_to_viewport = _fit_3d_card_to_viewport
    window.optimization.fit_requested.connect(_fit_3d_card_to_viewport)

    sc = window._canvas_scroll
    orig_sc_resize = sc.resizeEvent

    def _sc_resize(ev, _o=orig_sc_resize):
        if _o is not None:
            _o(ev)
        _fit_3d_card_to_viewport()
        QTimer.singleShot(0, window, _fit_3d_card_to_viewport)

    sc.resizeEvent = _sc_resize

    for key in ("temp", "pres", "vel", "layout", "pareto"):
        card = window._canvas_cards[key]
        orig_show = card.showEvent

        def _field_show(ev, _o=orig_show):
            _o(ev)
            _fit_3d_card_to_viewport()

        card.showEvent = _field_show

    c3d = window._canvas_cards.get("3d")
    if c3d is not None:
        orig_show = c3d.showEvent

        def _c3d_show(ev, _o=orig_show):
            if _o is not None:
                _o(ev)
            window._canvas_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            _fit_3d_card_to_viewport()

        c3d.showEvent = _c3d_show

    window._hover_label = QLabel("")
    window._hover_label.setTextFormat(Qt.TextFormat.RichText)
    window._hover_label.setStyleSheet(
        f"color: {_t['sub']}; font-size: 9pt; background: transparent; padding: 2px 12px;"
    )
    window._hover_label.setFixedHeight(20)
    vlay.addWidget(window._hover_label)

    for c in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
        c.mpl_connect("motion_notify_event", window.workbench.on_hover)
        c.mpl_connect("button_press_event", window.workbench.on_canvas_click)


def build_canvas_area(window):
    """Build the canvas stack hosted inside the Style P2 workbench sheet."""
    from .field_factory import default_factory

    f = default_factory()
    t = f.theme
    _t = get_theme()

    w = QWidget()
    w.setStyleSheet(f"background: {_t['canvas']};")
    vlay = QVBoxLayout(w)
    vlay.setContentsMargins(0, 0, 0, 0)
    vlay.setSpacing(2)

    _build_canvas_toolbar(window, vlay, t, _t)
    _build_compute_progress(window, vlay, _t)
    _build_canvas_content(window, vlay, t)
    _connect_canvas_interactions(window, vlay, _t)
    return w


def _layout_split_cards(window, keys):
    """Place exactly two tab keys side-by-side and hide the rest."""
    lay = getattr(window, "_canvas_lay", None)
    order = getattr(window, "_canvas_card_order", None)
    if lay is None or order is None or not keys:
        return
    keys = [k for k in keys if k in window._canvas_cards][:2]
    if not keys:
        return
    for k in order:
        card = window._canvas_cards.get(k)
        if card is not None:
            lay.removeWidget(card)
            card.hide()
    for i, k in enumerate(keys):
        card = window._canvas_cards.get(k)
        if card is None:
            continue
        lay.addWidget(card, 0, i)
        card.show()
    window.workbench.split_tabs = list(keys)


def _relayout_canvas_cards(window, cols):
    """Re-pack the canvas cards at 1 or 2 columns."""
    lay = getattr(window, "_canvas_lay", None)
    order = getattr(window, "_canvas_card_order", None)
    if lay is None or order is None:
        return
    cols = max(1, min(2, int(cols)))
    for key in order:
        card = window._canvas_cards.get(key)
        if card is not None:
            lay.removeWidget(card)
    for i, key in enumerate(order):
        card = window._canvas_cards.get(key)
        if card is None:
            continue
        r, c = divmod(i, cols)
        lay.addWidget(card, r, c)


def canvas_zoom_reset(window):
    """Reset the active canvas card to its viewport-fitted height."""
    tab = window.workbench.active_tab
    panel = None
    if tab == "3d":
        panel = getattr(window, "canvas_3d", None)
    elif (
        tab == "pareto"
        and window.optimization.result_tabs.currentWidget() is window.optimization.volume_host
    ):
        panel = window.optimization.volume_panel
    if panel is not None:
        try:
            panel.fit_view()
            return
        except Exception:
            pass
    card = window._canvas_cards.get(tab)
    if card and tab in window._canvas_default_h:
        getattr(window, "_canvas_zoom_factors", {}).pop(tab, None)
        card.setFixedHeight(window._canvas_default_h[tab])


def canvas_wheel_zoom(window, event, key):
    """Zoom a 2D plot card on Ctrl+Wheel; pass plain wheel to the scroll area."""
    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
        window._canvas_scroll.wheelEvent(event)
        return
    delta = event.angleDelta().y()
    if delta > 0:
        factor = 1.1
    elif delta < 0:
        factor = 0.9
    else:
        return
    card = window._canvas_cards.get(key)
    if card:
        factors = getattr(window, "_canvas_zoom_factors", {})
        factors[key] = factors.get(key, 1.0) * factor
        window._canvas_zoom_factors = factors
        h = max(200, int(card.height() * factor))
        card.setFixedHeight(h)
