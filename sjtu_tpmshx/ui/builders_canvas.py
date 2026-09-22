"""Canvas-area builder: tab toolbar, result summary strip, canvas cards.

Split out of ui_builders.py (Batch-2, 2026-06-10). Owns the right-hand
canvas stack (Temperature / Pressure / Velocity / Geometry / Optimize /
3D View cards), the tab-button row with split/detach affordances, and
the card zoom / re-layout helpers used by TabViewMixin.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QSizePolicy, QSlider,
    QProgressBar, QCheckBox,
)

from .matplotlib_canvas import MatplotlibCanvas
from .theme import (
    FONT_INPUT, FONT_LABEL, FONT_SECTION, RADIUS_CARD, RADIUS_INPUT,
    get_theme, glass_surface,
)
from .icons import icon

from .builders_sidebar import (
    _build_result_sidebar, update_result_sidebar_visibility,
)


class _ShiftTabBtn(QPushButton):
    """Tab button that routes Shift+click to a split callback while
    preserving normal click semantics. `_shift_cb` injected after
    construction so the subclass needs no custom __init__."""
    def mousePressEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            cb = getattr(self, '_shift_cb', None)
            if cb is not None:
                cb()
                return
        super().mousePressEvent(ev)


def _build_canvas_toolbar(window, vlay, t, theme):
    """Build canvas navigation and export controls."""
    _t = theme
    window._result_heading = QLabel("场图工作台")
    window._result_heading.setStyleSheet(
        f"color:{_t['fg']}; padding:10px 20px 4px; font-size:16pt; font-weight:600;")
    vlay.addWidget(window._result_heading)
    # ── Tab buttons + Export + Progress ──
    from .responsive import ResponsiveRow
    toolbar_host = ResponsiveRow(threshold=640, spacing=8)
    toolbar_host.layout().setContentsMargins(20, 4, 20, 8)
    primary_controls = QWidget()
    toolbar = QHBoxLayout(primary_controls)
    toolbar.setSpacing(4)
    toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    toolbar.setContentsMargins(0, 0, 0, 0)
    view_controls = QWidget()
    view_toolbar = QHBoxLayout(view_controls)
    view_toolbar.setContentsMargins(0, 0, 0, 0)
    view_toolbar.setSpacing(4)
    view_toolbar.setAlignment(Qt.AlignmentFlag.AlignRight)
    toolbar_host.addWidget(primary_controls)
    toolbar_host.addWidget(view_controls)
    window._field_toolbar = toolbar_host

    window.btn_update_geometry = QPushButton("更新几何")
    window.btn_update_geometry.setFixedHeight(28)
    window.btn_update_geometry.setStyleSheet(t.style('BTN_TERTIARY'))
    window.btn_update_geometry.setIcon(icon('box', _t['sub_fg']))
    window.btn_update_geometry.setIconSize(QSize(16, 16))
    window.btn_update_geometry.setToolTip("按当前参数重绘芯体外形和进出口位置")
    window.btn_update_geometry.clicked.connect(window._draw_layout)
    toolbar.addWidget(window.btn_update_geometry)

    # Chrome text is Chinese (ui-batch4 ①); the tab KEYS ('temp'/'pres'/…)
    # stay English — they are internal routing, not UI.
    window.btn_tab_layout = _ShiftTabBtn("几何布局")
    window.btn_tab_pareto = _ShiftTabBtn("优化")
    for b, key in ((window.btn_tab_layout, 'layout'),
                   (window.btn_tab_pareto, 'pareto')):
        b._shift_cb = (lambda k=key: window._split_with_current(k))
        b.setToolTip(b.toolTip() or f"{b.text()} 页签（Shift+点击 并排对比）")
    for b in (window.btn_tab_layout, window.btn_tab_pareto):
        b.setFixedHeight(28)
    window.btn_tab_layout.setStyleSheet(window._PTAB_ON)
    # Optimize tab is the entry point for the qNEHVI optimizer — always enabled so the
    # user can click through to the Launch button without first running a
    # single-point compute. The Pareto plot stays empty until a search
    # completes.
    window.btn_tab_pareto.setStyleSheet(window._PTAB_OFF)
    window.btn_tab_pareto.setEnabled(True)
    window.btn_tab_layout.clicked.connect(lambda: window._switch_tab('layout'))
    window.btn_tab_pareto.clicked.connect(lambda: window._switch_tab('pareto'))

    def _attach_canvas_menu(_btn, _key):
        _btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def _open_ctx(pos):
            from PySide6.QtWidgets import QMenu as _QM
            menu = _QM(_btn)
            detached = window._detached_canvases.get(_key) is not None
            if detached:
                act = menu.addAction("&Re-dock canvas")
                act.triggered.connect(
                    lambda _c=False, k=_key: window._reattach_canvas(k))
            else:
                act = menu.addAction("Open in &new window")
                act.triggered.connect(
                    lambda _c=False, k=_key: window._detach_canvas(k))
            menu.exec(_btn.mapToGlobal(pos))
        _btn.customContextMenuRequested.connect(_open_ctx)

    for _key, _btn in (('layout', window.btn_tab_layout),
                       ('pareto', window.btn_tab_pareto)):
        _attach_canvas_menu(_btn, _key)
    # The hidden combo remains the shared 2D-field state source for the
    # visible segmented buttons and tab routing.
    window.combo_2d_field = QComboBox()
    window.combo_2d_field.addItems(["Temperature", "Velocity |U|", "Pressure"])
    window.combo_2d_field.setFixedHeight(28)
    window.combo_2d_field.setFixedWidth(120)            # ★ fix #4 (cap width)
    window.combo_2d_field.setEnabled(False)             # ★ fix #1 (gate w/ btn)
    # ★ fix #4 (thin 1px border, lighter weight, 9pt to match tab buttons)
    # 2026-06-03 — was hardcoded rgba(255,255,255,*) (white border + white
    # disabled text): invisible/jarring on the light theme's near-white tab
    # strip (read as an empty white box). Theme-token it + transparent fill so
    # it blends with the flat tab buttons in both palettes.
    _ct = get_theme()
    window.combo_2d_field.setStyleSheet(
        f"QComboBox{{padding:2px 6px; color:{_ct['inp_fg']}; background:transparent;"
        f" border:1px solid {_ct['tab_off_border']}; border-radius:4px;"
        f" font-weight:normal; font-size:9pt;}}"
        f"QComboBox:hover{{border-color:{_ct['combo_hover_border']};}}"
        f"QComboBox:disabled{{color:{_ct['tab_disabled_fg']};"
        f" background:transparent; border-color:{_ct['border_subtle']};}}"
    )
    window.combo_2d_field.setToolTip(
        "Select which field to display in the 2D result view.")
    # ui-batch4: the combo is no longer visible UI — it stays as the FIELD
    # STATE SOURCE (its English item strings are internal keys consumed by
    # _resolve_2d_view_card / _switch_tab reverse-sync). The segmented
    # buttons below drive it.
    window.combo_2d_field.hide()

    def _on_2d_field_changed(_idx):
        # Re-trigger the active tab so the canvas swap honors the new combo
        # selection. The _switch_tab fast-path returns immediately when the
        # active tab is unchanged, so we explicitly call with the resolved
        # underlying tab key.
        if getattr(window, '_active_tab', None) in ('temp', 'pres', 'vel',
                                                     '2d_view'):
            window._switch_tab('2d_view')
        _paint_2d_seg()
    window.combo_2d_field.currentIndexChanged.connect(_on_2d_field_changed)

    # Segmented field switch (ui-batch4 ③): one click per field instead of
    # the two-click dropdown. Buttons drive the hidden combo; the combo's
    # currentIndexChanged repaints them, so hotkey / code paths that
    # reverse-sync the combo keep the buttons honest.
    _seg = QFrame()
    _seg.setStyleSheet(
        "QFrame{background:transparent; border:none; padding:0px;}")
    _seg_lay = QHBoxLayout(_seg)
    _seg_lay.setContentsMargins(4, 0, 0, 0)
    _seg_lay.setSpacing(0)
    _seg_qss_on = (
        f"QPushButton{{color:{_ct['inp_fg']}; background:transparent;"
        f" border:1px solid {_ct['combo_hover_border']}; padding:2px 8px;"
        f" font-size:10.5pt; font-weight:600;}}")
    _seg_qss_off = (
        f"QPushButton{{color:{_ct['tab_off_fg']}; background:transparent;"
        f" border:1px solid {_ct['tab_off_border']}; padding:2px 8px;"
        f" font-size:10.5pt; font-weight:normal;}}"
        f"QPushButton:hover{{color:{_ct['inp_fg']};}}"
        f"QPushButton:disabled{{color:{_ct['tab_disabled_fg']};"
        f" border-color:{_ct['border_subtle']};}}")
    window._2d_field_btns = []
    for i, cap in enumerate(["温度", "速度", "压力"]):
        b = QPushButton(cap)
        b.setFixedHeight(28)
        b.setToolTip("单击切换 2D 显示场")
        b.clicked.connect(
            lambda _c=False, idx=i: window.combo_2d_field.setCurrentIndex(idx))
        _seg_lay.addWidget(b)
        window._2d_field_btns.append(b)
        _attach_canvas_menu(b, ('temp', 'vel', 'pres')[i])

    def _paint_2d_seg():
        cur = window.combo_2d_field.currentIndex()
        for j, b in enumerate(window._2d_field_btns):
            b.setStyleSheet(_seg_qss_on if j == cur else _seg_qss_off)
    _paint_2d_seg()
    window._2d_field_seg = _seg
    window._paint_2d_seg = _paint_2d_seg

    window._field_phase = getattr(window, '_field_phase', 0)
    window._field_phase_seg = QFrame()
    window._field_phase_seg.setStyleSheet("QFrame{background:transparent; border:none;}")
    phase_row = QHBoxLayout(window._field_phase_seg)
    phase_row.setContentsMargins(0, 0, 12, 0)
    phase_row.setSpacing(0)
    window._field_phase_btns = []
    for index, label in enumerate(("流体 A", "流体 B", "固体")):
        button = QPushButton(label)
        button.setFixedHeight(28)
        button.setCheckable(True)
        button.setToolTip("显示该相的真实计算场；不会重新求解")
        def _pick_phase(_checked=False, i=index):
            window._field_phase = i
            refresh_field_controls(window)
            from .plot_2d_results import redraw_result_fields
            redraw_result_fields(window)
        button.clicked.connect(_pick_phase)
        phase_row.addWidget(button)
        window._field_phase_btns.append(button)
    window._phase_styles = (_seg_qss_on, _seg_qss_off)
    window._field_phase_seg.hide()

    # ── Workbench toolbar (ui-plan3-workbench T1) ─────────────────────
    # Three tabs only: 几何布局 | 结果 | 优化. The 结果 button aggregates
    # every result rendering (temp/pres/vel 2D cards + the 3D volume) via
    # _switch_tab('result'); a 2D|3D segmented control on the right picks
    # the rendering. Legacy buttons (temp/pres/vel/3d/2d_view) stay alive
    # off-toolbar — hotkeys, split view, detach menus and _switch_tab
    # routing resolve them unchanged.
    window.btn_tab_result = _ShiftTabBtn("结果")
    window.btn_tab_result.setFixedHeight(28)
    window.btn_tab_result.setStyleSheet(window._PTAB_DISABLED)
    window.btn_tab_result.setEnabled(False)
    window.btn_tab_result._shift_cb = (
        lambda: window._split_with_current('result'))
    window.btn_tab_result.setToolTip(
        "结果视图（Ctrl+2；用右侧「场图 / 三维」切换显示方式）。"
        "Shift+点击可与其他页并排对比。")
    window.btn_tab_result.clicked.connect(
        lambda: window._switch_tab('result'))
    window._result_view = '2d'

    # 2D|3D rendering toggle — enabled per side by _update_tab_visibility.
    _rv_seg = QFrame()
    _rv_seg.setObjectName('resultViewSwitch')
    _rv_seg.setStyleSheet(
        f"QFrame#resultViewSwitch{{background:{_ct['surface_elevated']};"
        f"border:1px solid {_ct['border_subtle']}; border-radius:{RADIUS_INPUT + 3}px;}}")
    _rv_lay = QHBoxLayout(_rv_seg)
    _rv_lay.setContentsMargins(3, 3, 3, 3)
    _rv_lay.setSpacing(2)
    _view_qss = (
        f"QPushButton{{border:1px solid transparent; border-radius:{RADIUS_INPUT}px;"
        f"padding:2px 12px; font-size:10.5pt; color:{_ct['sub_fg']};"
        "background:transparent;}"
        f"QPushButton:checked{{background:{_ct['accent_primary']};"
        f"color:{_ct['tab_on_fg']}; font-weight:600;}}"
        f"QPushButton:hover:!checked{{background:{_ct['btn_sec_hover_bg']};}}"
        f"QPushButton:focus{{border-color:{_ct['inp_focus']};}}"
        f"QPushButton:disabled{{color:{_ct['tab_disabled_fg']}; background:transparent;}}")
    window._result_view_btns = {}
    for key, cap in (('2d', "场图"), ('3d', "三维")):
        b = QPushButton(cap)
        b.setFixedHeight(28)
        b.setCheckable(True)
        b.setStyleSheet(_view_qss)
        b.setToolTip("切换结果显示方式（Ctrl+4），不改变计算维度或重新求解。")
        b.setEnabled(False)
        def _pick_view(_c=False, k=key):
            window._result_view = k
            window._switch_tab('result')
            window._paint_result_seg()
        b.clicked.connect(_pick_view)
        _rv_lay.addWidget(b)
        window._result_view_btns[key] = b

    btn_3d_view = window._result_view_btns['3d']
    btn_3d_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    def _open_3d_ctx(pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(btn_3d_view)
        if getattr(window, '_3d_detached_window', None) is None:
            act = menu.addAction("Open in &new window")
            act.triggered.connect(window._detach_3d_window)
        else:
            act = menu.addAction("&Re-dock 3D panel")
            act.triggered.connect(window._reattach_3d_window)
        menu.exec(btn_3d_view.mapToGlobal(pos))
    btn_3d_view.customContextMenuRequested.connect(_open_3d_ctx)

    def _paint_result_seg():
        cur = getattr(window, '_result_view', '2d')
        for k, b in window._result_view_btns.items():
            b.setChecked(k == cur)
    _paint_result_seg()
    window._paint_result_seg = _paint_result_seg

    toolbar.addWidget(window.btn_tab_layout)
    toolbar.addWidget(window.btn_tab_result)
    toolbar.addWidget(window._field_phase_seg)
    toolbar.addWidget(window._2d_field_seg)
    # Context control: hidden until a 2D field card is active (the
    # _switch_tab handler flips it per tab).
    window._2d_field_seg.hide()
    toolbar.addWidget(window.btn_tab_pareto)
    toolbar.addStretch()
    view_toolbar.addWidget(_rv_seg)
    view_toolbar.addSpacing(8)

    window.btn_result_summary = QPushButton("摘要")
    window.btn_result_summary.setFixedHeight(28)
    window.btn_result_summary.setCheckable(True)
    window.btn_result_summary.setChecked(True)
    window.btn_result_summary.setStyleSheet(
        t.style('BTN_TERTIARY')
        + f"QPushButton:checked{{color:{_t['fg']}; border-color:{_t['accent_primary']};}}")
    window.btn_result_summary.setToolTip("显示或收起结果摘要，为图表腾出空间")
    window.btn_result_summary.toggled.connect(
        lambda _checked: update_result_sidebar_visibility(window))
    window.btn_result_summary.hide()
    view_toolbar.addWidget(window.btn_result_summary)

    # Fit View restores the canvas size after Ctrl+Wheel zooming.
    btn_reset_view = QPushButton("适应视图")
    btn_reset_view.setFixedHeight(28)
    btn_reset_view.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_reset_view.setIcon(icon('fit-view', _t['sub_fg']))
    btn_reset_view.setIconSize(QSize(16, 16))
    btn_reset_view.setToolTip("让当前画布适应可用空间")
    btn_reset_view.clicked.connect(lambda: canvas_zoom_reset(window))
    view_toolbar.addWidget(btn_reset_view)
    window.btn_focus_view = QPushButton("专注")
    window.btn_focus_view.setFixedHeight(28)
    window.btn_focus_view.setCheckable(True)
    window.btn_focus_view.setStyleSheet(t.style('BTN_TERTIARY'))
    window.btn_focus_view.setIcon(icon('maximize', _t['sub_fg']))
    window.btn_focus_view.setIconSize(QSize(16, 16))
    window.btn_focus_view.setToolTip("收起参数与结果摘要，专注当前画布（F）")
    window.btn_focus_view.clicked.connect(window._toggle_3d_immersive)
    view_toolbar.addWidget(window.btn_focus_view)

    # Single Export menu — Results (data) + Figure (image) in one entry, in
    # the canvas toolbar next to the data it exports (the old header "Export
    # Results" copy was easy to miss). Gated until a compute / layout fills it.
    from PySide6.QtWidgets import QMenu as _QMenu
    from .builders_base import MenuToolButton
    btn_export = MenuToolButton(t.style('BTN_TERTIARY'))
    btn_export.setText("导出")
    btn_export.setIcon(icon('download', _t['sub_fg']))
    btn_export.setToolTip(
        "Export results (CSV + NPZ) or the current figure (PNG / SVG / PDF)")
    btn_export.setEnabled(False)
    _ex_menu = _QMenu(btn_export)
    # Theme-aware: without this the dropdown items inherited light-on-light text
    # in the white theme (unreadable). Explicit fg/bg keeps them legible in both.
    _ex_menu.setStyleSheet(
        f"QMenu {{ background:{_t['card_bg']}; color:{_t['fg']}; "
        f"border:1px solid {_t['card_border']}; border-radius:6px; padding:4px; }}"
        f"QMenu::item {{ padding:6px 20px; border-radius:4px; }}"
        f"QMenu::item:selected {{ background:{_t['accent_primary']}; color:{_t['tab_on_fg']}; }}")
    _ex_menu.addAction("导出完整结果 — CSV + NPZ", window._export_results)
    _ex_menu.addAction("导出图像 — PNG / SVG / PDF", window._export_figure)
    _ex_menu.addAction("复制当前图像", window._copy_figure_clipboard)
    btn_export.setMenu(_ex_menu)
    window.btn_export = btn_export
    view_toolbar.addWidget(btn_export)
    vlay.addWidget(toolbar_host)


def refresh_field_controls(window):
    """Show only selectors backed by the current rendered result."""
    tab = getattr(window, '_active_tab', None)
    is_field = tab in ('temp', 'pres', 'vel')
    window.btn_update_geometry.setVisible(tab == 'layout')
    result = window.cache.get_result('3d')
    b_source = 'dir_B' if tab in ('pres', 'vel') else 'Tb'
    has_b = result is None or result.fields.get(b_source) is not None
    phase = getattr(window, '_field_phase', 0)
    if (tab in ('pres', 'vel') and phase == 2) or (phase == 1 and not has_b):
        phase = window._field_phase = 0
        from .plot_2d_results import redraw_result_fields
        redraw_result_fields(window)
    window._field_phase_seg.setVisible(is_field)
    for i, btn in enumerate(window._field_phase_btns):
        btn.setVisible(i != 2 or tab == 'temp')
        btn.setEnabled(i != 1 or has_b)
        btn.setChecked(i == phase)
        btn.setStyleSheet(window._phase_styles[0 if i == phase else 1])
    slice_controls = getattr(window, '_slice_controls', None)
    if slice_controls is not None:
        slice_controls.setVisible(is_field and result is not None)
    heading = getattr(window, '_result_heading', None)
    if heading is not None:
        mode = (getattr(window, '_diag_summary', None) or {}).get('mode')
        heading.setText(
            f"本次结果 · {mode.upper()}" if tab in ('temp', 'pres', 'vel', '3d') and mode
            else {"layout": "几何与工况", "pareto": "优化设计"}.get(tab, "场图工作台"))


def _build_compute_progress(window, vlay, theme):
    """Build the progress line; result values live in the existing footer."""
    _t = theme
    window.progress = QProgressBar()
    window.progress.setFixedHeight(3)
    window.progress.setTextVisible(False)
    window.progress.setStyleSheet(
        "QProgressBar{background:transparent; border:none;}"
        f"QProgressBar::chunk{{background:{_t['prog_chunk']}; border-radius:1px;}}")
    window.progress.setValue(0)
    window.progress.hide()
    vlay.addWidget(window.progress)


def _build_optimize_panel(window, card_lay, t, theme):
    """Build the three-page Pareto optimization panel."""
    _t = theme
    from PySide6.QtWidgets import (
        QWidget as _QWop, QHBoxLayout as _HBop,
        QVBoxLayout as _VBop, QProgressBar as _PBop,
        QFrame as _QFop, QStackedWidget as _QSWop,
        QSpinBox as _QSBop, QDoubleSpinBox as _QDSBop)
    from .sparkline import Sparkline as _SLop
    _surface_ra = _t.get('surface_raised', _t['card_bg'])
    _border_sub = _t.get('border_subtle', _t['card_border'])
    _sub_fg = _t.get('sub_fg', _t['fg'])
    _mono = _t['mono_family']

    # ui-plan-b-wizard: the Optimize tab is a THREE-PAGE WIZARD
    # (配置 → 运行 → 结果) in a QStackedWidget. The engine, worker,
    # KPI/status setters and stage-pill machinery are untouched —
    # _set_stage_pill('…', 'active') now also flips the page.
    op_host = _QWop()
    op_host.setStyleSheet("QWidget { background:transparent; }")
    op_v = _VBop(op_host)
    op_v.setContentsMargins(0, 0, 0, 0); op_v.setSpacing(16)

    # ── Stage strip ────────────────────────────────────────
    _pill_base = (
        "QLabel{{padding:5px 14px; border-radius:12px;"
        "font-size:10pt; font-weight:600;"
        "font-family:" + _t['sans_family'] + ";"
        "background:{bg}; color:{fg}; border:1px solid {bd};}}")
    _pill_idle = _pill_base.format(
        bg=_surface_ra, fg=_sub_fg, bd=_border_sub)
    _pill_active = _pill_base.format(
        bg=_t.get('accent_primary', '#3B82F6'),
        fg=_t['tab_on_fg'],
        bd=_t.get('accent_primary', '#3B82F6'))
    _pill_done = _pill_base.format(
        bg=_t.get('accent_green', '#22C55E'),
        fg=_t['tab_on_fg'],
        bd=_t.get('accent_green', '#22C55E'))
    window._opt_pill_styles = (_pill_idle, _pill_active, _pill_done)

    stage_row = _HBop()
    stage_row.setSpacing(6); stage_row.setContentsMargins(0, 0, 0, 0)
    window._opt_stage_pills = {}
    stage_items = [('config', '1  配置'),
                   ('running', '2  运行'),
                   ('result', '3  结果')]
    for i, (skey, slabel) in enumerate(stage_items):
        pill = QLabel(slabel)
        pill.setStyleSheet(_pill_idle)
        # Wizard nav: pills are clickable page switches.
        pill.setCursor(Qt.CursorShape.PointingHandCursor)
        pill.mousePressEvent = (
            lambda _ev, idx=i: window._opt_stack.setCurrentIndex(idx))
        stage_row.addWidget(pill)
        window._opt_stage_pills[skey] = pill
        if i < len(stage_items) - 1:
            arr = QLabel("─")
            arr.setStyleSheet(
                f"color:{_border_sub}; font-size:12pt;"
                "background:transparent; border:none; padding:0 2px;")
            stage_row.addWidget(arr)
    stage_row.addStretch(1)
    status = QLabel("空闲 — 配置参数后点击启动")
    status.setMinimumHeight(24)
    status.setStyleSheet(
        f"color:{_sub_fg}; font-family:{_mono};"
        f"font-size:9pt; font-weight:400;"
        f"background:transparent; border:none; padding:2px 8px;")
    status.setAlignment(Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter)
    window._opt_status = status
    stage_row.addWidget(status, 0)
    op_v.addLayout(stage_row)
    # Initial stage: Config active, others idle
    window._opt_stage_pills['config'].setStyleSheet(_pill_active)

    # ── The wizard stack ──────────────────────────────────
    _stack = _QSWop()
    window._opt_stack = _stack
    op_v.addWidget(_stack, 1)

    # ═══ Page 1 · 配置 ═══
    p1 = _QWop()
    p1v = _VBop(p1)
    p1v.setContentsMargins(0, 0, 0, 0); p1v.setSpacing(16)
    from .responsive import ResponsiveRow
    p1row = ResponsiveRow(threshold=720, spacing=16)
    p1row.layout().setAlignment(Qt.AlignmentFlag.AlignTop)

    def _opt_card(title, min_w=0):
        fr = _QFop()
        fr.setStyleSheet(
            f"QFrame{{background:{_surface_ra};"
            f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
        if min_w:
            fr.setMinimumWidth(min_w)
        fl = _VBop(fr)
        fl.setContentsMargins(16, 16, 16, 16); fl.setSpacing(8)
        cap = QLabel(title)
        cap.setStyleSheet(
            f"color:{_t['fg']}; font-size:{FONT_SECTION}pt; font-weight:600;"
            "background:transparent;"
            "border:none;")
        fl.addWidget(cap)
        return fr, fl

    # Inline controls use the dimension-specific budget definition.
    from .optimize_panel import _outer_budget_parameter, _sync_outer_budget, _is_3d_mode

    par_card, par_lay = _opt_card("优化参数 (qNEHVI)", 260)
    _spin_qss = (
        f"QSpinBox{{background:{_t['inp_bg']}; color:{_t['inp_fg']};"
        f" border:1px solid {_t['inp_border']}; border-radius:6px;"
        f" padding:4px 8px; font-family:{_mono}; font-size:{FONT_INPUT}pt;}}"
        f"QSpinBox:focus{{border-color:{_t['inp_focus']};}}")
    window._opt_inline_params = {}
    budget_key, budget_value, budget_label, budget_tip = _outer_budget_parameter(window)
    _param_specs = [
        ('n_init',      "初始样本 <i>n</i><sub>init</sub>", 4, 256, 32,
         "Sobol 初始采样数（约 2×决策维度）"),
        ('n_iter',      "迭代数 <i>n</i><sub>iter</sub>", 0, 200, 24,
         "BO 迭代次数（HV 平台早停可能提前结束）"),
        ('q_batch',     "每代批量 <i>q</i><sub>batch</sub>", 1, 8, 2,
         "每次 BO 迭代的并行候选数"),
        ('seed',        "随机种子", 0, 9999, 42,
         "Sobol + BoTorch 随机种子（复现实验用）"),
        (budget_key, budget_label, 1, max(8, budget_value), budget_value, budget_tip),
    ]
    for pkey, plabel, lo, hi, dflt, tip in _param_specs:
        prow = _HBop(); prow.setSpacing(8)
        pl = QLabel(plabel)
        pl.setTextFormat(Qt.TextFormat.RichText)
        pl.setStyleSheet(f"color:{_t['fg']}; font-size:{FONT_LABEL}pt;"
                         " background:transparent; border:none;")
        sp = _QSBop(); sp.setRange(lo, hi); sp.setValue(dflt)
        sp.setToolTip(tip)
        sp.setStyleSheet(_spin_qss)
        sp.setAlignment(Qt.AlignmentFlag.AlignRight)
        sp.setFixedWidth(92)
        sp.setMinimumHeight(30)
        prow.addWidget(pl); prow.addStretch(1); prow.addWidget(sp)
        par_lay.addLayout(prow)
        window._opt_inline_params[pkey] = sp
        if pkey == budget_key:
            window._opt_outer_budget = sp
            window._opt_outer_label = pl

    def _remember_budget(value):
        key = 'max_outer_3d' if _is_3d_mode(window) else 'n_rho_loops'
        window._opt_param_cache = {**getattr(window, '_opt_param_cache', {}), key: value}

    window._opt_outer_budget.valueChanged.connect(_remember_budget)
    # Typed/script configuration may be applied after constructing the panel.
    op_host.showEvent = lambda _event: _sync_outer_budget(window)
    _eval_preview = QLabel("")
    _eval_preview.setWordWrap(True)
    _eval_preview.setStyleSheet(
        f"color:{_sub_fg}; font-size:9pt;"
        " background:transparent; border:none;")

    def _refresh_eval_preview(*_):
        ps = window._opt_inline_params
        total = (ps['n_init'].value()
                 + ps['n_iter'].value() * ps['q_batch'].value())
        dimension = '3D' if _is_3d_mode(window) else '2D'
        _eval_preview.setText(f"计划 {total} 次 {dimension} 求解（提前停止时减少）")
    for _sp in window._opt_inline_params.values():
        _sp.valueChanged.connect(_refresh_eval_preview)
    _cd0 = getattr(window, 'combo_dim', None)
    if _cd0 is not None:
        try:
            _cd0.currentIndexChanged.connect(_refresh_eval_preview)
            _cd0.currentIndexChanged.connect(lambda _: _sync_outer_budget(window))
        except Exception:
            pass
    _refresh_eval_preview()
    par_lay.addWidget(_eval_preview)
    _scope = QLabel("空气/空气 · A:+x、B:−y · 整面开口筛选")
    _scope.setWordWrap(True)
    _scope.setStyleSheet(t.style('LBL'))
    par_lay.addWidget(_scope)
    par_lay.addStretch(1)
    p1row.addWidget(par_card)

    # 搜索空间 — the optimizer's REAL search-space inputs (M0,
    # 2026-07-09). Previously this card hosted the zone panel, which
    # feeds the Compute path's zone feature and NOT the continuous-
    # field optimizer — a decorative interface. Now: L/t bounds
    # (spinbox ranges = the current CFD geometry grid, so out-of-grid
    # values are unreachable; _gather_cfg clamps again defensively),
    # control-point grid, Y-mirror toggle, field preview.
    space_card, space_lay = _opt_card("搜索空间 (连续场)", 250)
    from sjtu_tpmshx.df_surrogate._domain import (
        TRAIN_L as _hull_L, TRAIN_T as _hull_T,
    )
    _dspin_qss = (
        f"QDoubleSpinBox{{background:{_t['inp_bg']};"
        f" color:{_t['inp_fg']}; border:1px solid {_t['inp_border']};"
        f" border-radius:6px; padding:3px 8px;"
        f" font-family:{_mono}; font-size:{FONT_INPUT}pt;}}"
        f"QDoubleSpinBox:focus{{border-color:{_t['inp_focus']};}}")
    window._opt_space_params = {}

    def _space_row(label, tip, widgets):
        srow = _HBop(); srow.setSpacing(8)
        sl = QLabel(label)
        sl.setToolTip(tip)
        sl.setStyleSheet(f"color:{_t['fg']}; font-size:{FONT_LABEL}pt;"
                         " background:transparent; border:none;")
        srow.addWidget(sl); srow.addStretch(1)
        for wdg in widgets:
            srow.addWidget(wdg)
        space_lay.addLayout(srow)

    def _mk_dspin(lo, hi, val, step, dec):
        ds = _QDSBop()
        ds.setRange(lo, hi); ds.setValue(val)
        ds.setSingleStep(step); ds.setDecimals(dec)
        ds.setStyleSheet(_dspin_qss)
        ds.setAlignment(Qt.AlignmentFlag.AlignRight)
        ds.setFixedWidth(80)
        ds.setMinimumHeight(30)
        return ds

    _sp_Lmin = _mk_dspin(_hull_L[0], _hull_L[1], _hull_L[0], 0.5, 2)
    _sp_Lmax = _mk_dspin(_hull_L[0], _hull_L[1], _hull_L[1], 0.5, 2)
    _space_row("胞元 <i>L</i> 范围 [mm]",
               f"决策变量 L 的上下界；当前 CFD 几何范围 {_hull_L} mm；"
               "Nu 适用范围单独检查",
               [_sp_Lmin, _sp_Lmax])
    window._opt_space_params['L_min'] = _sp_Lmin
    window._opt_space_params['L_max'] = _sp_Lmax

    _sp_tmin = _mk_dspin(_hull_T[0], _hull_T[1], _hull_T[0], 0.05, 2)
    _sp_tmax = _mk_dspin(_hull_T[0], _hull_T[1], _hull_T[1], 0.05, 2)
    _space_row("壁厚 <i>t</i> 范围 [mm]",
               f"决策变量 t 的上下界；当前 CFD 几何范围 {_hull_T} mm（自动夹持）",
               [_sp_tmin, _sp_tmax])
    window._opt_space_params['t_min'] = _sp_tmin
    window._opt_space_params['t_max'] = _sp_tmax

    _cb_grid = QComboBox()
    _cb_grid.addItem("4 × 4（16 维）", (4, 4))
    _cb_grid.addItem("6 × 6（36 维）", (6, 6))
    _cb_grid.setToolTip(
        "B-spline 控制点网格。6×6 提高空间自由度但 GP 建模更难，"
        "建议同时加大 n_init（约 2×维数）")
    _cb_grid.setStyleSheet(t.style('COMBO'))
    _cb_grid.setMinimumHeight(30)
    _space_row("控制点网格", "决策向量维数 = 控制点数 × 2（L、t 两场）",
               [_cb_grid])
    window._opt_space_params['ctrl_grid'] = _cb_grid

    _chk_sym = QCheckBox("Y 镜像对称")
    _chk_sym.setChecked(True)
    _chk_sym.setToolTip(
        "沿 y 中线镜像控制点（对称工况减半维数）；"
        "非对称工况（两侧流体/边界不同）可关闭")
    _chk_sym.setStyleSheet(
        f"QCheckBox{{color:{_sub_fg}; font-size:9pt;"
        f" background:transparent; border:none;}}")
    space_lay.addWidget(_chk_sym)
    window._opt_space_params['symmetric_y'] = _chk_sym

    btn_field_prev = QPushButton("预览连续场  ↗")
    btn_field_prev.setFixedHeight(26)
    btn_field_prev.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_field_prev.setToolTip(
        "渲染当前 L(x,y)、t(x,y) 场热图"
        "（未选 Pareto 解时显示界中值均匀场）")

    def _preview_field(*_):
        from sjtu_tpmshx.ui.optimize_panel import show_field_preview
        show_field_preview(window)
    btn_field_prev.clicked.connect(_preview_field)
    space_lay.addWidget(btn_field_prev)
    space_lay.addStretch(1)
    p1row.addWidget(space_card)
    p1v.addWidget(p1row)

    # 分区定义 — the zone panel serves the COMPUTE path's zone
    # feature (zone_config.py is retained for exactly that); it is
    # not an optimizer input. Own clearly-labelled card, no more
    # runtime hide-and-patch.
    if getattr(window, '_zone_panel', None) is not None:
        from .builders_base import collapsible_section
        zone_grid, zone_card = collapsible_section(
            window, p1v, "单点计算分区（不参与优化搜索）",
            t.style('T_NEUTRAL'), t.style('F_NEUTRAL'), expanded=False)
        zone_grid.addWidget(window._zone_panel, 0, 0, 1, 2)
        window.chk_zones.toggled.connect(zone_card._set_expanded)
    p1v.addStretch(1)
    _stack.addWidget(p1)

    # ═══ Page 2 · 运行 ═══ (assembled below once the KPI row and
    # progress bar are built — see p2v.addLayout calls.)
    p2 = _QWop()
    p2v = _VBop(p2)
    p2v.setContentsMargins(0, 0, 0, 0); p2v.setSpacing(16)
    _stack.addWidget(p2)

    # ═══ Page 3 · 结果 ═══ (banner + Pareto canvas mounted below.)
    p3 = _QWop()
    p3v = _VBop(p3)
    p3v.setContentsMargins(0, 0, 0, 0); p3v.setSpacing(16)
    _stack.addWidget(p3)
    window._opt_page3_lay = p3v

    # ── Hero KPI row ──────────────────────────────────────
    # Display-serif stack for hero numerics — research-tool gravitas.
    # Falls through to mono if no serif installed, so builds without
    # Instrument Serif still look sharp.
    _hero_font = _t['mono_family']
    def _mk_kpi(caption, initial="—", min_w=150):
        card = _QFop()
        card.setStyleSheet(
            f"QFrame{{background:{_surface_ra};"
            f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
        card.setFixedHeight(78)
        card.setMinimumWidth(min_w)
        cl = _VBop(card)
        cl.setContentsMargins(14, 8, 14, 8); cl.setSpacing(2)
        cap = QLabel(caption)
        cap.setStyleSheet(
            f"color:{_sub_fg}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            f"font-family:{_t['sans_family']};")
        val = QLabel(initial)
        val.setStyleSheet(
            f"color:{_t['fg']}; font-family:{_hero_font};"
            f"font-size:22pt; font-weight:600;"
            "background:transparent; border:none;")
        cl.addWidget(cap); cl.addWidget(val)
        return card, val

    kpi_row = QGridLayout()
    kpi_row.setSpacing(16)
    card_gen, val_gen = _mk_kpi("阶段 · 代数", "—", 130)
    card_q,   val_q   = _mk_kpi("最优 Q [W/m]", "—", 180)
    card_dp,  val_dp  = _mk_kpi("最优 ΔP [Pa]", "—", 180)
    card_eta, val_eta = _mk_kpi("剩余时间", "—", 120)
    window._opt_kpi_gen = val_gen
    window._opt_kpi_q = val_q
    window._opt_kpi_dp = val_dp
    window._opt_kpi_eta = val_eta
    kpi_row.addWidget(card_gen, 0, 0)
    kpi_row.addWidget(card_q, 0, 1)
    kpi_row.addWidget(card_dp, 1, 0)
    kpi_row.addWidget(card_eta, 1, 1)

    # Sparkline card (flex 1)
    spark_card = _QFop()
    spark_card.setStyleSheet(
        f"QFrame{{background:{_surface_ra};"
        f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
    spark_card.setFixedHeight(72)
    spark_card.setMinimumWidth(220)
    scl = _VBop(spark_card)
    scl.setContentsMargins(14, 8, 14, 8); scl.setSpacing(2)
    spark_cap = QLabel("初始采样 · 最优 Q")
    window._opt_sparkline_caption = spark_cap
    spark_cap.setStyleSheet(
        f"color:{_sub_fg}; font-size:8pt; font-weight:700;"
        "letter-spacing:1.4px; background:transparent; border:none;"
        f"font-family:{_t['sans_family']};")
    spark = _SLop(height=40)
    window._opt_sparkline = spark
    scl.addWidget(spark_cap)
    scl.addWidget(spark, 1)
    kpi_row.addWidget(spark_card, 2, 0, 1, 2)
    p2v.addLayout(kpi_row)

    # ── Launch (inside the 优化参数 card, always above the fold)
    #    + Cancel (page 2) ──────────────────────────────────
    btn_opt = QPushButton("▶  启动 Pareto 搜索")
    btn_opt.setFixedHeight(36)
    btn_opt.setStyleSheet(t.style('BTN_LONG'))
    btn_opt.setToolTip(
        "启动 qNEHVI 多目标搜索。"
        "进度与收敛在「2 运行」页实时显示。")
    btn_opt.clicked.connect(window._run_optimize)
    window._opt_btn = btn_opt
    # Insert BEFORE the trailing stretch so the CTA sits right
    # under the eval-count preview, above the fold.
    par_lay.insertWidget(par_lay.count() - 1, btn_opt)

    btn_opt_cancel = QPushButton("✕ 取消（保留已算样本）")
    btn_opt_cancel.setFixedHeight(32)
    btn_opt_cancel.setMinimumWidth(90)
    btn_opt_cancel.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_opt_cancel.setToolTip("请求优雅取消当前搜索")
    btn_opt_cancel.setEnabled(False)
    btn_opt_cancel.clicked.connect(window._cancel_optimize)
    window._opt_cancel_btn = btn_opt_cancel
    cancel_row = _HBop()
    cancel_row.addWidget(btn_opt_cancel)
    cancel_row.addStretch(1)
    p2v.addLayout(cancel_row)
    p2v.addStretch(1)

    # ── Fat progress bar (8 px rounded pill) ─────────────
    op_pb = _PBop()
    op_pb.setFixedHeight(8)
    op_pb.setTextVisible(False)
    op_pb.setRange(0, 100); op_pb.setValue(0)
    op_pb.setStyleSheet(
        f"QProgressBar{{background:{_surface_ra};"
        f"border:1px solid {_border_sub}; border-radius:4px;}}"
        f"QProgressBar::chunk{{background:qlineargradient("
        f"x1:0,y1:0,x2:1,y2:0,"
        f"stop:0 {_t.get('accent_primary', '#3B82F6')},"
        f"stop:1 {_t.get('accent_green', '#22C55E')});"
        f"border-radius:4px;}}")
    op_pb.hide()
    window._opt_progress = op_pb
    p2v.insertWidget(1, op_pb)

    # ── Summary banner (hidden initially) ────────────────
    banner = QLabel("")
    banner.setStyleSheet(
        f"QLabel{{color:{_t.get('tab_on_fg', '#FFFFFF')};"
        f"background:{_t.get('accent_green', '#22C55E')};"
        f"border:none; border-radius:6px;"
        f"padding:10px 16px;"
        f"font-family:{_mono}; font-size:10pt; font-weight:700;"
        "letter-spacing:0.3px;}")
    banner.setWordWrap(True)
    banner.hide()
    window._opt_summary_banner = banner
    p3v.addWidget(banner)

    card_lay.addWidget(op_host)


def _build_canvas_content(window, vlay, t):
    """Build scrollable plot cards and the diagnostics sidebar."""
    # ── Scrollable canvas area with card containers ──
    _t = get_theme()

    window._canvas_scroll = QScrollArea()
    window._canvas_scroll.setWidgetResizable(True)
    window._canvas_scroll.setStyleSheet(
        f"QScrollArea{{border:none; background:{_t['scroll_bg']};}}"
        + t.style('SCROLLBAR'))
    window._canvas_scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    canvas_container = QWidget()
    canvas_container.setStyleSheet(f"background:{_t['scroll_bg']};")
    # QGridLayout backs the card area (single column; a planned two-column
    # re-pack was never built — stale _relayout_cards reference removed
    # ui-batch2. Wide-aspect field plots stack correctly in one column).
    canvas_lay = QGridLayout(canvas_container)
    canvas_lay.setContentsMargins(12, 12, 12, 12)
    canvas_lay.setHorizontalSpacing(12)
    canvas_lay.setVerticalSpacing(16)
    window._canvas_lay = canvas_lay

    # Empty state: visible until a Compute or Preview populates any card.
    # Structured three-step guidance (ui-layout-fixes) instead of a text
    # wall — verbs first, one job per line, theme-token colors.
    _acc = _t.get('accent_primary', '#3B82F6')
    _sub = _t.get('sub_fg', _t['fg'])
    _empty = QLabel(
        f"<div style='text-align:left;'>"
        f"<p style='color:{_t['fg']}; font-size:12pt; font-weight:600;"
        f" margin:0 0 14px 0;'>运行第一个算例</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc};"
        f" font-weight:700;'>1</span>&nbsp;&nbsp;在左侧面板设置几何与两侧流体</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc};"
        f" font-weight:700;'>2</span>&nbsp;&nbsp;点击 <b>开始计算</b>"
        f"（Ctrl+R），展开计算状态查看迭代与提示</p>"
        f"<p style='margin:0;'><span style='color:{_acc};"
        f" font-weight:700;'>3</span>&nbsp;&nbsp;在此查看温度 / 压力 / 速度场；"
        f"就绪后上方页签自动点亮</p>"
        f"</div>")
    _empty.setTextFormat(Qt.TextFormat.RichText)
    _empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    _empty.setStyleSheet(
        f"color:{_sub}; background:transparent; border:none;"
        f"font-size:10pt; letter-spacing:0.2px; padding:0;")
    # Container (ui-batch2 IA-5): guidance text + one-click Shanghai preset.
    # `_empty_state_label` now points at the CONTAINER — its only consumers
    # call setVisible, so text+button hide together after the first compute.
    _empty_box = QWidget()
    _empty_box.setObjectName('emptyStateCard')
    _empty_box.setStyleSheet(
        f"QWidget#emptyStateCard{{{glass_surface(_t)}}}")
    _eb_lay = QVBoxLayout(_empty_box)
    _eb_lay.setContentsMargins(48, 48, 48, 40)
    _eb_lay.setSpacing(18)
    _eb_lay.addWidget(_empty)
    _btn_preset = QPushButton("⚡  载入算例工况")
    _btn_preset.setMinimumHeight(30)
    _btn_preset.setStyleSheet(t.style('BTN_SECONDARY'))
    _btn_preset.setToolTip(
        "用已验证的基准算例填满全部字段 — 可立即点击计算。")
    _btn_preset.clicked.connect(
        lambda: window._load_named_preset("Shanghai (3D Gyroid)"))
    _eb_lay.addWidget(_btn_preset, 0, Qt.AlignmentFlag.AlignHCenter)
    # NOTE: QGridLayout.addWidget(w, 0, <alignment>) parses the alignment
    # enum as a COLUMN index (row=0, col=36) — pass row & col explicitly.
    _empty_box.setMaximumWidth(640)
    canvas_lay.addWidget(_empty_box, 0, 0,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    window._empty_state_label = _empty_box
    window._empty_state_preset_btn = _btn_preset

    window.canvas_temp   = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_pres   = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_vel    = MatplotlibCanvas(1, 1, figsize=(12, 7))
    window.canvas_layout = MatplotlibCanvas(1, 1, figsize=(10.5, 6.8))
    window.canvas_pareto = MatplotlibCanvas(1, 1, figsize=(14, 8))

    # PyVistaQt init is heavy (~1-2s VTK/OpenGL context setup).
    # Defer until user actually switches to the 3D tab → faster cold start
    # and no impact on 2D Compute Geometry / Auto-fill / Run responsiveness.
    window.canvas_3d = None
    window._vis3d_import_error = None
    import os as _os
    if (_os.environ.get('QT_QPA_PLATFORM', '').lower() == 'offscreen'
            or _os.environ.get(
                'TPMSHX_DISABLE_3D_PANEL', '').lower() in ('1', 'true', 'yes')):
        window._vis3d_import_error = 'headless/offscreen — 3D panel skipped'

    window._canvas_default_h = {}
    window._canvas_cards = {}
    _card_specs = [
        (window.canvas_temp,   'temp',   440),
        (window.canvas_pres,   'pres',   440),
        (window.canvas_vel,    'vel',    440),
        (window.canvas_layout, 'layout', 680),
        (window.canvas_pareto, 'pareto', 880),
    ]
    # 3D card inserted lazily (card reserved here as placeholder QWidget).
    # Taller card (1100 vs earlier 820) gives PyVistaQt ~950 px for the
    # plotter — the slice fills more of the available real-estate.
    from PySide6.QtWidgets import QWidget as _QW
    window._canvas_3d_placeholder = _QW()
    _card_specs.append((window._canvas_3d_placeholder, '3d', 1100))
    _card_row_order = []
    for c, key, h in _card_specs:
        if key in ('temp', 'pres', 'vel'):
            # Reserve real text extents on resize, including equal-aspect 3D
            # slices. Tight layout can retain invalid margins on short canvases.
            c.fig.set_layout_engine('compressed')
        # Card frame. 3D card skips top-accent stripe (its curved arc was
        # visually colliding with embedded toolbar labels — user report
        # 2026-04-21). Other cards keep the coloured accent.
        card = QFrame()
        card.setObjectName('plotCard')
        # No left accent stripe for layout/3d (arc collision, 2026-04-21)
        # and pareto (ui-plan-b-wizard follow-up: the card's `QFrame{…}`
        # type selector CASCADES to every unstyled descendant frame — the
        # wizard's new frames all grew amber left bars, user report).
        if key == 'pareto':
            # The optimizer owns its inner cards; its page uses the workbench background.
            card.setStyleSheet("QFrame#plotCard{background:transparent; border:none;}")
        else:
            card.setStyleSheet(
                f"QFrame#plotCard{{background:{_t['card_bg']};"
                f"border:1px solid {_t['card_border']}; border-radius:{RADIUS_CARD}px;}}")
        card_lay = QVBoxLayout(card)
        if key == '3d':
            from PySide6.QtWidgets import QLayout
            card_lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        if key == 'layout':
            card_lay.setContentsMargins(8, 8, 8, 8)
        elif key == 'pareto':
            card_lay.setContentsMargins(12, 12, 12, 12)
        else:
            card_lay.setContentsMargins(16, 16, 16, 16)
        card_lay.setSpacing(0)
        # Paint only the static outer chrome: no graphics effect on a large
        # Matplotlib/PyVista surface or blur over scientific field values.

        # Card-local mini toolbar (temperature only) — hosts the
        # "Sync colorbar across Ta/Tb/Ts" toggle so users can flip between
        # shared and independent vmin/vmax at any time without re-running
        # Compute. Signal connects to `_redraw_temp_if_ready` in main.
        if key == 'temp':
            from PySide6.QtWidgets import QWidget as _QWtb, QHBoxLayout as _HB
            tb = _QWtb()
            tbl = _HB(tb)
            tbl.setContentsMargins(0, 0, 0, 6); tbl.setSpacing(8)
            tbl.addStretch(1)
            chk = QCheckBox("各相使用相同温标")
            chk.setChecked(True)
            chk.setToolTip(
                "When on, all three panels share a common vmin/vmax so "
                "cross-panel comparison is direct. Turn off for per-panel "
                "auto-scale.")
            chk.setStyleSheet(
                f"QCheckBox{{color:{_t['fg']}; font-size:9pt; "
                f"background:transparent;}}"
                f"QCheckBox::indicator{{width:14px; height:14px;"
                f"border:1px solid {_t['chk_indicator_border']};"
                f"border-radius:3px; background:{_t['chk_bg']};}}"
                f"QCheckBox::indicator:checked{{background:{_t['chk_checked_bg']};"
                f"border-color:{_t['chk_checked_border']};}}")
            tbl.addWidget(chk, 0)
            window.chk_sync_colorbar_T = chk
            chk.toggled.connect(
                lambda _on: window._redraw_temp_if_ready())
            card_lay.addWidget(tb)

        # Optimize tab header — Pro-Max layout:
        #   [Stage strip]      Config → Running → Result
        #   [KPI row]          Gen · Best Q · ETA + convergence sparkline
        #   [Control row]      Launch + Cancel + status
        #   [Progress bar]     fat 8 px pill bar
        #   [Summary banner]   green pill, post-run
        if key == 'pareto':
            _build_optimize_panel(window, card_lay, t, _t)

        # The Pareto canvas lives in the wizard's result page.
        c.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Expanding)
        c.setStyleSheet("border-radius:6px;")
        if key == 'pareto':
            window._opt_page3_lay.addWidget(c, 1)
        else:
            card_lay.addWidget(c)

        # Keep the 3D loading placeholder; optimization results stay static
        # until the search supplies a real Pareto chart.
        if key == '3d':
            try:
                from .skeleton import Skeleton as _Sk
                skel = _Sk( parent=c)
                skel.setGeometry(0, 0, max(1, c.width()), max(1, c.height()))
                _prev_resize = c.resizeEvent
                def _on_resize(ev, s=skel, cv=c, prev=_prev_resize):
                    s.setGeometry(0, 0, max(1, cv.width()),
                                   max(1, cv.height()))
                    if prev is not None:
                        prev(ev)
                c.resizeEvent = _on_resize
                skel.start()
                window._3d_skeleton = skel
            except Exception:
                pass

        if key == 'pareto':
            card.setMinimumHeight(520)
        else:
            card.setFixedHeight(h + 44)
        _card_row_order.append((key, card))
        window._canvas_default_h[key] = h + 44
        window._canvas_cards[key] = card
        # Matplotlib canvases get custom wheel-zoom; 3D PyVistaQt keeps its own
        if key != '3d':
            c.wheelEvent = lambda evt, k=key: canvas_wheel_zoom(window, evt, k)

    # Register card ordering + initial single-column placement.
    window._canvas_card_order = [k for k, _ in _card_row_order]
    _relayout_canvas_cards(window, 1)

    # Initial state: hide all cards (shown after Compute/Preview)
    for key in ('temp', 'pres', 'vel', 'layout', 'pareto'):
        c = getattr(window, f'canvas_{key}')
        c.fig.clear()
        c.fig.patch.set_facecolor(_t['fig_bg'])
        c.draw()
    _hide_keys = ['temp', 'pres', 'vel', 'layout', 'pareto']
    if '3d' in window._canvas_cards:
        _hide_keys.append('3d')
    for key in _hide_keys:
        window._canvas_cards[key].hide()
    window._active_tab = 'layout'
    window.cache.clear()

    window._canvas_scroll.setWidget(canvas_container)
    # Result footer shares the published result labels and diagnostics.
    # It is hidden before the first result and on non-result tabs.
    _body = QVBoxLayout()
    _body.setContentsMargins(0, 0, 0, 0)
    _body.setSpacing(6)
    _body.addWidget(window._canvas_scroll, 1)
    slice_controls = QWidget()
    slice_row = QHBoxLayout(slice_controls)
    slice_row.setContentsMargins(36, 0, 36, 4)
    slice_row.setSpacing(14)
    slice_row.addWidget(QLabel("截面 z"))
    window._slice_slider = QSlider(Qt.Orientation.Horizontal)
    window._slice_slider.setTracking(False)
    window._slice_slider.setToolTip("显示已计算的真实网格截面，不重新求解")
    window._slice_slider.setStyleSheet(
        f"QSlider::groove:horizontal{{background:{_t['border_subtle']}; height:5px;}}"
        f"QSlider::handle:horizontal{{background:{_t['accent_primary']};"
        "width:15px; margin:-5px 0; border-radius:7px;}")
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
    _body.addWidget(slice_controls)
    from .run_status import RunStatusCard
    window._run_status_card = RunStatusCard()
    window._run_status_card.cancel_requested.connect(window._on_cancel_compute)
    window._run_status_card.log_requested.connect(window._show_solve_log)
    _body.addWidget(window._run_status_card)
    _body.addWidget(_build_result_sidebar(window, _t, t), 0)
    vlay.addLayout(_body, 1)


def _connect_canvas_interactions(window, vlay, theme):
    """Attach viewport sizing and hover interactions."""
    _t = theme
    # Fit cards to the viewport. The 3D controls and native viewport retain
    # their minimum size; short windows use the existing canvas scroll area.
    def _fit_3d_card_to_viewport():
        sc = getattr(window, '_canvas_scroll', None)
        if sc is None:
            return
        vh = sc.viewport().height()
        for key in ('temp', 'pres', 'vel', 'layout', '3d'):
            card = window._canvas_cards.get(key)
            if card is not None and card.isVisible() and vh > 24:
                height = vh - 24
                if key == '3d':
                    height = max(height, card.minimumSizeHint().height())
                factor = getattr(window, '_canvas_zoom_factors', {}).get(key, 1.0)
                window._canvas_default_h[key] = height
                card.setFixedHeight(int(height * factor))
    window._fit_3d_card_to_viewport = _fit_3d_card_to_viewport

    _sc = window._canvas_scroll
    _orig_sc_resize = _sc.resizeEvent
    def _sc_resize(ev, _o=_orig_sc_resize):
        if _o is not None:
            _o(ev)
        _fit_3d_card_to_viewport()
    _sc.resizeEvent = _sc_resize

    for key in ('temp', 'pres', 'vel', 'layout'):
        card = window._canvas_cards[key]
        _orig_show = card.showEvent
        def _field_show(ev, _o=_orig_show):
            _o(ev)
            _fit_3d_card_to_viewport()
        card.showEvent = _field_show

    _c3d = window._canvas_cards.get('3d')
    if _c3d is not None:
        _orig_show = _c3d.showEvent
        def _c3d_show(ev, _o=_orig_show):
            if _o is not None:
                _o(ev)
            # Keep compact controls and a usable native viewport reachable
            # when details and the result summary occupy a short window.
            window._canvas_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            _fit_3d_card_to_viewport()
        _c3d.showEvent = _c3d_show
        _orig_hide = _c3d.hideEvent
        def _c3d_hide(ev, _o=_orig_hide):
            if _o is not None:
                _o(ev)
            # Restore for the stacked, taller 2D-canvas tabs.
            window._canvas_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _c3d.hideEvent = _c3d_hide

    # ── Hover data label ──
    window._hover_label = QLabel("")
    # RichText so field names render with real subscripts (P_A → P<sub>A</sub>)
    # instead of a literal underscore in the cursor readout.
    window._hover_label.setTextFormat(Qt.TextFormat.RichText)
    window._hover_label.setStyleSheet(
        f"color:{_t['fg']}; font-size:9pt; background:transparent; padding:2px 8px;")
    window._hover_label.setFixedHeight(20)
    vlay.addWidget(window._hover_label)

    # Connect hover events
    for c in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
        c.mpl_connect('motion_notify_event', window._on_hover)

def build_canvas_area(window):
    """Ex-Main_Menu._build_canvas_area(self) -> QWidget."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
    _t = get_theme()

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(w)
    vlay.setContentsMargins(0, 0, 0, 0); vlay.setSpacing(4)

    _build_canvas_toolbar(window, vlay, t, _t)
    _build_compute_progress(window, vlay, _t)
    _build_canvas_content(window, vlay, t)
    _connect_canvas_interactions(window, vlay, _t)

    return w


def _layout_split_cards(window, keys):
    """Place exactly `keys` (two tab keys) side-by-side; hide the rest.

    Used by the Shift-click split-view flow — lets users compare e.g.
    Temperature and Pressure or Layout and Pareto without constantly
    switching tabs. Non-split cards are hidden but not destroyed so
    a subsequent single-click restores them in one op.
    """
    lay = getattr(window, '_canvas_lay', None)
    order = getattr(window, '_canvas_card_order', None)
    if lay is None or order is None or not keys:
        return
    keys = [k for k in keys if k in window._canvas_cards][:2]
    if not keys:
        return
    # Detach every card.
    for k in order:
        card = window._canvas_cards.get(k)
        if card is not None:
            lay.removeWidget(card)
            card.hide()
    # Place the two split keys on a single row.
    for i, k in enumerate(keys):
        card = window._canvas_cards.get(k)
        if card is None:
            continue
        lay.addWidget(card, 0, i)
        card.show()
    window._split_tabs = list(keys)


def _relayout_canvas_cards(window, cols):
    """Re-pack the canvas cards at `cols` columns (1 or 2). Preserves the
    user-visible order stored in `window._canvas_card_order`."""
    lay = getattr(window, '_canvas_lay', None)
    order = getattr(window, '_canvas_card_order', None)
    if lay is None or order is None:
        return
    cols = max(1, min(2, int(cols)))
    # Detach every card from its current cell.
    for key in order:
        card = window._canvas_cards.get(key)
        if card is not None:
            lay.removeWidget(card)
    # Re-add in row-major order.
    for i, key in enumerate(order):
        card = window._canvas_cards.get(key)
        if card is None:
            continue
        r, c = divmod(i, cols)
        lay.addWidget(card, r, c)


def canvas_zoom_reset(window):
    """Ex-Main_Menu._canvas_zoom_reset(self). Reset current canvas card to default height."""
    tab = window._active_tab
    if tab == '3d':
        panel = getattr(window, 'canvas_3d', None)
        if panel is not None:
            try:
                panel.fit_view()
                return
            except Exception:
                pass
    card = window._canvas_cards.get(tab)
    if card and tab in window._canvas_default_h:
        getattr(window, '_canvas_zoom_factors', {}).pop(tab, None)
        card.setFixedHeight(window._canvas_default_h[tab])


def canvas_wheel_zoom(window, event, key):
    """Scroll the active canvas stack from a wheel event.
    Ctrl + mouse wheel zoom. Without Ctrl, pass to ScrollArea for scrolling.
    """
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
        factors = getattr(window, '_canvas_zoom_factors', {})
        factors[key] = factors.get(key, 1.0) * factor
        window._canvas_zoom_factors = factors
        h = max(200, int(card.height() * factor))
        card.setFixedHeight(h)
