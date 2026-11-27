"""Style P2 desktop shell assembly, inspector drawer, and zone configuration."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .builders_canvas import build_canvas_area
from .builders_domain import build_domain_sections
from .builders_fluids import build_fluid_sections
from .builders_sidebar import (
    build_result_drawer_content,
    refresh_header_status,
    refresh_stale_indicator,
)
from .icons import icon
from .inspector_drawer import CollapsibleBand, InspectorDrawer
from .nav_rail import ExpandedNavRail, NavRail
from .readout_strip import ReadoutStrip
from .run_info_popover import RunInfoPopover
from .theme import RADIUS_CARD, get_theme


class _WorkbenchSheet(QFrame):
    """Rounded canvas sheet container hosting the active page and bottom readout strip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workbenchSheet")
        self.setStyleSheet("QFrame#workbenchSheet { background: transparent; border: none; }")

    def paintEvent(self, event) -> None:
        theme = get_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(theme["canvas"]))
        painter.setPen(QPen(QColor(theme["border"]), 0.5))
        painter.drawRoundedRect(rect, float(RADIUS_CARD), float(RADIUS_CARD))
        painter.end()


class _RailScrim(QWidget):
    """Translucent backdrop behind the 232 px expanded navigation rail overlay."""

    def __init__(self, on_click, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self.hide()

    def paintEvent(self, event) -> None:
        scrim_rgba = get_theme()["scrim"]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(*scrim_rgba))
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


def _open_run_info_popover(window) -> None:
    """Open the floating RunInfoPopover below the header status pill."""
    scope = window.dialogs.run_info_directory_scope()
    folder = window.dialogs.resolve_output_directory(scope=scope)
    data = window.history.build_run_info_data(folder_path=folder)
    pop = getattr(window, "_run_info_popover", None)
    if pop is None:
        pop = RunInfoPopover(data, parent=window)
        pop._folder_path = folder
        pop.log_requested.connect(window.dialogs.show_solve_log)
        pop.diagnostics_requested.connect(window.results.show_diag_dialog)
        pop.open_folder_requested.connect(
            lambda: pop._folder_path is not None
            and window.dialogs.open_output_folder(pop._folder_path)
        )
        window._run_info_popover = pop
    else:
        pop._folder_path = folder
        pop.apply_theme(get_theme())
        pop.set_data(data)
    pop.popup_below(window.btn_run_info)


def build_ui(window):
    """Build the Style P2 desktop workbench shell."""
    from .field_factory import default_factory
    from .optimize_panel import OptimizationPage
    from .quick_design_panel import QuickDesignPage

    t = default_factory().theme
    theme = get_theme()
    cw = window.centralWidget()
    cw.setStyleSheet(f"background: {theme['window']}; color: {theme['fg']};")

    outer = QHBoxLayout(cw)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    # 1. Left navigation rail (64 px collapsed + 232 px expanded overlay)
    nav_rail = NavRail(active_page="run", parent=cw)
    window.nav_rail = nav_rail
    outer.addWidget(nav_rail)

    # Alias real NavRail page buttons so existing tests, pulse_glow, and accessibility
    # target the actual visible controls without hidden duplicate buttons.
    window.btn_tab_layout = nav_rail.page_button("run")
    window.btn_tab_result = nav_rail.page_button("result")
    window.btn_tab_pareto = nav_rail.page_button("opt")
    window.btn_quick_design = nav_rail.page_button("qd")
    window.btn_command_search = nav_rail.action_button("search")
    window.btn_recent = nav_rail.action_button("open")
    window.btn_save = nav_rail.action_button("save")
    window.btn_more = nav_rail.action_button("more")
    nav_rail.set_page_enabled("result", False)

    # Build inputs first so canvas and optimization pages can read their references.
    drawer = build_param_tabs(window)
    window.optimization = OptimizationPage(window)
    window.quick_design = QuickDesignPage(window)
    canvas = build_canvas_area(window)
    window._workbench_canvas = canvas

    # Wire NavRail page switching, Shift+click split, right-click detach, and actions.
    def _on_nav_page(key: str) -> None:
        if window.appearance.is_rail_expanded():
            window.appearance.set_rail_expanded(False)
        if key == "run":
            window.workbench.switch_tab("layout")
        elif key == "result":
            window.workbench.switch_tab("result")
        elif key == "opt":
            window.workbench.switch_tab("pareto")
        elif key == "qd":
            window.workbench.show_quick_design()

    def _on_nav_split(key: str) -> None:
        mapping = {"run": "layout", "result": "result", "opt": "pareto"}
        target = mapping.get(key)
        if target is not None:
            window.workbench.split_with_current(target)

    def _on_nav_action(key: str) -> None:
        if key == "search":
            if window.appearance.is_rail_expanded():
                window.appearance.set_rail_expanded(False)
            window.dialogs.open_command_palette()
        elif key == "open":
            window.history.show_load_menu()
        elif key == "save":
            window.history.show_save_menu()
        elif key == "more":
            window.appearance.show_settings_popover()
        elif key == "expand":
            window.appearance.toggle_rail()

    nav_rail.page_selected.connect(_on_nav_page)
    nav_rail.page_split_requested.connect(_on_nav_split)
    nav_rail.action_triggered.connect(_on_nav_action)

    # Context menu for detaching layout / pareto canvases from rail page buttons
    for page_key, tab_key in (("run", "layout"), ("opt", "pareto")):
        btn = nav_rail.page_button(page_key)
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _ctx_menu(pos, b=btn, k=tab_key):
            menu = QMenu(b)
            if window.workbench.detached_canvases.get(k) is not None:
                act = menu.addAction("放回主窗口")
                act.triggered.connect(lambda _c=False, key=k: window.workbench.reattach_canvas(key))
            else:
                act = menu.addAction("在新窗口中打开")
                act.triggered.connect(lambda _c=False, key=k: window.workbench.detach_canvas(key))
            menu.exec(b.mapToGlobal(pos))

        btn.customContextMenuRequested.connect(_ctx_menu)

    # 2. Right column: Header bar + [Sheet | Push InspectorDrawer]
    right_col = QVBoxLayout()
    right_col.setContentsMargins(0, 8, 8, 8)
    right_col.setSpacing(8)

    header = QWidget()
    header.setObjectName("workbenchHeader")
    header.setFixedHeight(36)
    header.setStyleSheet("QWidget#workbenchHeader { background: transparent; border: none; }")
    h_lay = QHBoxLayout(header)
    h_lay.setContentsMargins(4, 0, 4, 0)
    h_lay.setSpacing(8)

    page_title = QLabel("算例计算")
    page_title.setStyleSheet(
        f"color: {theme['fg']}; font-size: 13pt; font-weight: 600; "
        "background: transparent; border: none;"
    )
    window._page_title = page_title
    h_lay.addWidget(page_title)

    btn_run_info = QPushButton("●  尚未计算  ▾")
    btn_run_info.setFixedHeight(28)
    btn_run_info.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_run_info.setToolTip("查看当前运行信息、求解状态、日志、诊断与运行目录")
    btn_run_info.clicked.connect(lambda: _open_run_info_popover(window))
    window.btn_run_info = btn_run_info
    h_lay.addWidget(btn_run_info)
    refresh_header_status(window)

    h_lay.addStretch(1)

    window.btn_update_geometry = QPushButton("更新几何")
    window.btn_update_geometry.setFixedHeight(30)
    window.btn_update_geometry.setCursor(Qt.CursorShape.PointingHandCursor)
    window.btn_update_geometry.setStyleSheet(t.style("BTN_SECONDARY"))
    window.btn_update_geometry.setIcon(icon("box", theme["sub"]))
    window.btn_update_geometry.setIconSize(QSize(15, 15))
    window.btn_update_geometry.setToolTip("按当前参数重绘芯体外形和进出口位置")
    window.btn_update_geometry.clicked.connect(window._draw_layout)
    h_lay.addWidget(window.btn_update_geometry)

    btn_run = QPushButton("开始计算")
    btn_run.setIcon(icon("play", theme["primary_fg"]))
    btn_run.setIconSize(QSize(14, 14))
    btn_run.setFixedHeight(30)
    btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_run.setStyleSheet(t.style("BTN_PRIMARY"))
    btn_run.setToolTip("开始算例计算 (Ctrl+R)")
    btn_run.clicked.connect(window.single_run.toggle)
    window.btn_compute = btn_run
    h_lay.addWidget(btn_run)

    window.btn_export.setFixedHeight(30)
    window.btn_export.apply_button_style(t.style("BTN_SECONDARY"))
    window.btn_export.hide()
    h_lay.addWidget(window.btn_export)

    btn_drawer = QPushButton("检查器")
    btn_drawer.setCheckable(True)
    btn_drawer.setChecked(True)
    btn_drawer.setFixedHeight(30)
    btn_drawer.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_drawer.setIcon(icon("panel-left-close", theme["sub"]))
    btn_drawer.setIconSize(QSize(15, 15))
    btn_drawer.setStyleSheet(t.style("BTN_TERTIARY"))
    btn_drawer.setToolTip("收起检查器  Ctrl+]")
    btn_drawer.clicked.connect(window.appearance.toggle_drawer)
    window.btn_toggle_drawer = btn_drawer
    window.btn_collapse_parameters = btn_drawer
    h_lay.addWidget(btn_drawer)

    right_col.addWidget(header)

    # Workspace row: rounded Sheet (left, expanding) + push InspectorDrawer (right)
    workspace_row = QHBoxLayout()
    workspace_row.setContentsMargins(0, 0, 0, 0)
    workspace_row.setSpacing(8)

    sheet = _WorkbenchSheet()
    sheet_lay = QVBoxLayout(sheet)
    sheet_lay.setContentsMargins(1, 1, 1, 1)
    sheet_lay.setSpacing(0)

    window.page_stack = QStackedWidget()
    window.page_stack.addWidget(canvas)
    window.page_stack.addWidget(window.quick_design)
    sheet_lay.addWidget(window.page_stack, 1)

    window.readout_strip = ReadoutStrip()
    window.readout_strip.hide()
    sheet_lay.addWidget(window.readout_strip, 0)
    window._workbench_sheet = sheet

    workspace_row.addWidget(sheet, 1)
    workspace_row.addWidget(drawer, 0)
    right_col.addLayout(workspace_row, 1)
    outer.addLayout(right_col, 1)

    # 3. Overlay 232 px expanded rail + scrim (children of centralWidget)
    scrim = _RailScrim(lambda: window.appearance.set_rail_expanded(False), parent=cw)
    expanded = ExpandedNavRail(
        active_page="run",
        workspaces=window.case_files.WORKSPACES,
        active_workspace=window.case_files.active_workspace,
        parent=cw,
    )
    expanded.set_page_enabled("result", False)
    expanded.hide()
    expanded.page_selected.connect(_on_nav_page)
    expanded.action_triggered.connect(_on_nav_action)
    expanded.workspace_selected.connect(
        lambda name: (
            window.appearance.set_rail_expanded(False),
            window.case_files.switch_workspace(name),
        )
    )
    expanded.recent_run_selected.connect(
        lambda rid: (
            window.appearance.set_rail_expanded(False),
            window.history.load_recent_by_index(rid),
        )
    )
    expanded.collapse_requested.connect(lambda: window.appearance.set_rail_expanded(False))
    window._rail_scrim = scrim
    window.expanded_nav_rail = expanded

    def refresh_navigation():
        in_qd = window.page_stack.currentWidget() is window.quick_design
        if in_qd:
            active_key = "qd"
        elif window.workbench.active_tab == "pareto":
            active_key = "opt"
        elif window.workbench.active_tab in ("temp", "pres", "vel", "3d"):
            active_key = "result"
        else:
            active_key = "run"
        nav_rail.set_active_page(active_key)
        expanded.set_active_page(active_key)
        expanded.set_workspaces(window.case_files.WORKSPACES, window.case_files.active_workspace)

        has_result = window.cache.has_any_results()
        d = window.results.summary() if has_result else {}
        dots: dict[str, str | None] = {}
        if not window.single_run.is_idle():
            dots["run"] = "run"
        elif has_result:
            if d.get("converged") is False:
                dots["result"] = "err"
            elif d.get("warnings") or d.get("extrap"):
                dots["result"] = "warn"
            else:
                dots["result"] = "ok"
        nav_rail.set_status_dots(dots)

        page_meta: dict[str, tuple[str | None, str]] = {}
        if dots.get("run") == "run":
            page_meta["run"] = ("run", "求解中")
        if has_result:
            page_meta["result"] = (
                dots.get("result"),
                str(d.get("mode", "")).upper(),
            )
        opt_rep = getattr(window.optimization, "report", None)
        if not window.optimization.is_idle():
            page_meta["opt"] = ("run", "搜索中")
        elif isinstance(opt_rep, dict):
            n_feas = opt_rep.get("n_feasible")
            n_tot = len(opt_rep.get("history") or ())
            if isinstance(n_feas, int) and n_feas > 0:
                page_meta["opt"] = ("ok", f"{n_feas} 可行")
            elif n_tot > 0:
                page_meta["opt"] = ("warn", f"{n_tot} 方案")
        if not window.quick_design.is_idle():
            page_meta["qd"] = ("run", "筛选中")
        else:
            qd_res = getattr(window.quick_design, "last_result", None)
            if isinstance(qd_res, dict):
                feasible = qd_res.get("feasible") or ()
                all_cands = qd_res.get("all") or ()
                if feasible:
                    page_meta["qd"] = ("ok", f"{len(feasible)} 可行")
                elif all_cands:
                    page_meta["qd"] = ("warn", "0 可行")
        expanded.set_page_meta(page_meta)

    window._refresh_workbench_navigation = refresh_navigation
    refresh_navigation()


def refresh_group_badges(window):
    """Update validation error badge counts on collapsible bands and drawer tabs."""
    from .window_config import blank_second_span, inlet_input_active

    bands = getattr(window, "_drawer_bands", None)
    if not bands:
        return

    tab_totals = {0: 0, 1: 0, 2: 0}
    counts: dict[str, int] = {}
    for key, (tab_idx, band) in bands.items():
        body = band._body
        n = 0
        for name in window.case_files.SESSION_LINE_EDITS:
            if not inlet_input_active(window, name):
                continue
            le = getattr(window, name, None)
            if le is None or not body.isAncestorOf(le):
                continue
            if not le.isVisibleTo(body):
                continue
            if le.property("inpError") == "true" or (
                not le.text().strip() and not blank_second_span(window, name)
            ):
                n += 1
        counts[key] = n
        band.set_badge_count(n)
        tab_totals[tab_idx] = tab_totals.get(tab_idx, 0) + n

    window._group_badge_counts = counts
    drawer = getattr(window, "inspector_drawer", None)
    if drawer is not None:
        for idx, total in tab_totals.items():
            drawer.tab_strip.set_tab_badge(idx, total)

    refresh_stale_indicator(window)


def build_param_tabs(window) -> InspectorDrawer:
    """Build the Style P2 push InspectorDrawer with 几何, 边界, 求解, and 结果 tabs."""
    staging = QWidget()
    staging_lay = QVBoxLayout(staging)
    staging_lay.setContentsMargins(0, 0, 0, 0)
    staging_lay.setSpacing(0)

    build_domain_sections(window, staging_lay)
    build_fluid_sections(window, staging_lay)
    window._zone_panel = build_page_zones(window)

    sec = window._ia_sections

    def _pack_page(keys: list[str]) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for k in keys:
            w = sec.get(k)
            if w is not None:
                lay.addWidget(w)
        lay.addStretch(1)
        return page

    geo_page = _pack_page(["domain_geometry", "tpms_structure", "tpms_computed"])
    boundary_page = _pack_page(["fluids_row"])
    solver_page = _pack_page(
        ["grid_rect", "df_method", "sco2_nu", "correlation_policy", "compute_resources"]
    )
    result_page = build_result_drawer_content(window)

    # Register collapsible bands for validation badge counting & reveal_parameter.
    window._drawer_bands = {}
    band_pages = (
        (0, ("domain_geometry", "tpms_structure", "tpms_computed")),
        (1, ("fluid_a", "pipe_a", "fluid_b", "pipe_b")),
        (2, ("grid_rect", "df_method", "sco2_nu", "correlation_policy", "compute_resources")),
    )
    for tab_idx, keys in band_pages:
        for key in keys:
            w = sec.get(key)
            if isinstance(w, CollapsibleBand):
                window._drawer_bands[key] = (tab_idx, w)

    # Re-assert 2D/3D visibility when a band expands.
    for _key, (_tab_idx, band) in window._drawer_bands.items():
        def _on_band_toggled(expanded: bool):
            if expanded:
                try:
                    from .builders_domain import _on_dim_changed

                    _on_dim_changed(window)
                except Exception:
                    pass
            refresh_group_badges(window)

        band.toggled.connect(_on_band_toggled)

    drawer = InspectorDrawer(
        tabs=(
            ("几何", geo_page),
            ("边界", boundary_page),
            ("求解", solver_page),
            ("结果", result_page),
        ),
        current_index=0,
        opened=window.appearance.is_drawer_open("run"),
    )
    window.inspector_drawer = drawer
    window._param_panel = drawer
    window._param_page = window.appearance.drawer_tab_for("run")

    # Compact parameter sub-bar shown only when inspecting 参数 from the 结果 page.
    theme = get_theme()
    subbar = QWidget()
    subbar.setStyleSheet(f"background: {theme['panel']}; border: none;")
    sb_lay = QHBoxLayout(subbar)
    sb_lay.setContentsMargins(16, 6, 16, 6)
    sb_lay.setSpacing(4)
    sub_on = (
        f"QPushButton {{ background: {theme['seg_on']}; color: {theme['fg']}; "
        f"border: 1px solid {theme['border']}; border-radius: 5px; "
        "font-size: 11px; font-weight: 600; padding: 2px 10px; }"
    )
    sub_off = (
        f"QPushButton {{ background: transparent; color: {theme['sub']}; "
        "border: none; border-radius: 5px; font-size: 11px; font-weight: 400; "
        "padding: 2px 10px; }"
        f"QPushButton:hover {{ color: {theme['fg']}; }}"
    )
    sub_btns: list[QPushButton] = []

    def _sync_result_param_btns() -> None:
        cur = getattr(window, "_param_page", 0)
        for j, b in enumerate(sub_btns):
            b.setChecked(j == cur)
            b.setStyleSheet(sub_on if j == cur else sub_off)

    def _pick_result_param(idx: int) -> None:
        window._param_page = idx
        drawer.set_stack_index(idx)
        _sync_result_param_btns()

    for idx, cap in enumerate(("几何", "边界", "求解")):
        btn = QPushButton(cap)
        btn.setCheckable(True)
        btn.setFixedHeight(22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, i=idx: _pick_result_param(i))
        sb_lay.addWidget(btn)
        sub_btns.append(btn)
    sb_lay.addStretch(1)
    subbar.hide()
    drawer.layout().insertWidget(2, subbar)
    window._result_param_subbar = subbar
    window._sync_result_param_btns = _sync_result_param_btns
    _sync_result_param_btns()

    drawer.tab_changed.connect(window.appearance.record_drawer_tab)
    drawer.close_requested.connect(lambda: window.appearance.set_drawer_open(False))

    def select_param_page(index: int) -> None:
        idx = max(0, min(2, int(index)))
        window._param_page = idx
        if window.workbench.active_tab in ("temp", "pres", "vel", "3d"):
            drawer.set_strip_entries([("结果", 3), ("参数", idx)], active_strip_index=1)
            window.appearance.record_drawer_tab(1)
            _sync_result_param_btns()
        else:
            drawer.set_current_index(idx)
            window.appearance.record_drawer_tab(idx)
        if hasattr(window, "_refresh_workbench_navigation"):
            window._refresh_workbench_navigation()

    window._select_param_page = select_param_page
    window.appearance.sync_drawer_visibility()
    refresh_group_badges(window)
    return drawer


def reveal_parameter(window, widget):
    """Open the inspector drawer, switch to the owning tab/side, and expand the band."""
    drawer = getattr(window, "inspector_drawer", None)
    if drawer is None:
        return
    if not window.appearance.is_drawer_open():
        window.appearance.set_drawer_open(True)

    # Switch [流体 A | 流体 B] if the widget belongs to one of the fluid side pages.
    side_pages = getattr(window, "_fluid_side_pages", {})
    for idx, side in enumerate(("A", "B")):
        page = side_pages.get(side)
        if page is not None and page.isAncestorOf(widget):
            window._select_fluid_side(idx)
            break

    for _key, (tab_idx, band) in getattr(window, "_drawer_bands", {}).items():
        if band.isAncestorOf(widget):
            window._select_param_page(tab_idx)
            band.set_expanded(True)
            scroll = drawer._stack.widget(tab_idx)
            if isinstance(scroll, QScrollArea):
                scroll.ensureWidgetVisible(widget)
            break


def build_page_zones(window):
    """Build the Zone Layout configuration panel mounted inside the Optimize page."""
    from .field_factory import default_factory

    f = default_factory()
    t = f.theme
    _t = get_theme()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("border: none; background: transparent;")

    w = QWidget()
    w.setStyleSheet(f"background: {t.style('BG')};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12)
    lay.setContentsMargins(6, 4, 8, 6)

    sec_zone = QWidget()
    sec_zone.setStyleSheet("background: transparent;")
    cz_lay = QVBoxLayout(sec_zone)
    cz_lay.setContentsMargins(0, 4, 0, 0)
    cz_lay.setSpacing(0)
    cz_frame = QFrame()
    cz_frame.setStyleSheet(t.style("F_NEUTRAL"))
    g_zone = QGridLayout(cz_frame)
    g_zone.setContentsMargins(12, 10, 12, 10)
    g_zone.setVerticalSpacing(8)
    g_zone.setHorizontalSpacing(10)
    g_zone.setColumnStretch(0, 3)
    g_zone.setColumnStretch(1, 2)
    cz_lay.addWidget(cz_frame)
    lay.addWidget(sec_zone)

    window.chk_zones = QCheckBox("Enable zone partitioning")
    window.chk_zones.setStyleSheet(
        f"QCheckBox {{ color: {_t['fg']}; font-size: 10pt; font-weight: bold; "
        "background: transparent; spacing: 8px; }"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; "
        f"border: 1.5px solid {_t['chk_indicator_border']}; "
        f"border-radius: 3px; background: {_t['chk_bg']}; }}"
        f"QCheckBox::indicator:hover {{ border-color: {_t['chk_hover_border']}; }}"
        f"QCheckBox::indicator:checked {{ background: {_t['chk_checked_bg']}; "
        f"border-color: {_t['chk_checked_border']}; }}"
        "QCheckBox:focus { outline: 0; }"
    )
    window.chk_zones.setChecked(False)

    def _toggle_zone_table(checked):
        for w_z in (window.zone_table, nz_row, window.combo_zone_axis):
            try:
                w_z.setVisible(checked)
            except Exception:
                pass

    window.chk_zones.toggled.connect(_toggle_zone_table)
    window.combo_zone_axis = QComboBox()
    window.combo_zone_axis.addItems(["Along Y", "Along X", "Grid Y×X"])
    window.combo_zone_axis.setFixedHeight(32)
    window.combo_zone_axis.setStyleSheet(t.style("INP"))
    window.combo_zone_axis.currentIndexChanged.connect(window._zone_mode_changed)
    g_zone.addWidget(window.chk_zones, 0, 0)
    g_zone.addWidget(window.combo_zone_axis, 0, 1)

    nz_row = QWidget()
    nz_lay = QHBoxLayout(nz_row)
    nz_lay.setContentsMargins(0, 0, 0, 0)
    nz_lay.setSpacing(4)
    btn_add = QPushButton("+Row")
    btn_rm = QPushButton("-Row")
    btn_tert = t.style("BTN_TERTIARY")
    for b in (btn_add, btn_rm):
        b.setFixedHeight(32)
        b.setMinimumWidth(48)
        b.setStyleSheet(btn_tert)
    btn_add.setToolTip("Add a row (split the last zone in half)")
    btn_rm.setToolTip("Remove the last row")
    btn_add.clicked.connect(window._zone_add_row)
    btn_rm.clicked.connect(window._zone_remove_row)
    window.lbl_nx = QLabel("Col:")
    window.lbl_nx.setStyleSheet(t.style("LBL"))
    window.btn_add_x = QPushButton("+Col")
    window.btn_rm_x = QPushButton("-Col")
    for b in (window.btn_add_x, window.btn_rm_x):
        b.setFixedHeight(32)
        b.setMinimumWidth(48)
        b.setStyleSheet(btn_tert)
    window.btn_add_x.setToolTip("Add a column (split the last column in half)")
    window.btn_rm_x.setToolTip("Remove the last column")
    window.btn_add_x.clicked.connect(window._zone_add_col)
    window.btn_rm_x.clicked.connect(window._zone_remove_col)
    window.lbl_nx.hide()
    window.btn_add_x.hide()
    window.btn_rm_x.hide()
    nz_lay.addWidget(btn_add)
    nz_lay.addWidget(btn_rm)
    nz_lay.addStretch()
    nz_lay.addWidget(window.lbl_nx)
    nz_lay.addWidget(window.btn_add_x)
    nz_lay.addWidget(window.btn_rm_x)
    g_zone.addWidget(nz_row, 1, 0, 1, 2)
    window._grid_nx = 2

    window.zone_table = QTableWidget(3, 4)
    window.zone_table.setHorizontalHeaderLabels(["START %", "END %", "L [mm]", "t [mm]"])
    window.zone_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.zone_table.verticalHeader().setVisible(True)
    window.zone_table.verticalHeader().setDefaultSectionSize(34)
    window.zone_table.verticalHeader().setStyleSheet(
        f"QHeaderView::section {{ background: {_t['sunken']}; color: {_t['sub']}; "
        f"font-family: {_t['mono_family']}; font-size: 9pt; font-weight: 700; "
        f"border: none; border-right: 1px solid {_t['border']}; padding: 0 6px; }}"
    )
    window.zone_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    window.zone_table.setMinimumHeight(220)
    window.zone_table.setAlternatingRowColors(True)
    window.zone_table.setShowGrid(False)
    window.zone_table.horizontalHeader().setHighlightSections(False)
    window.zone_table.verticalHeader().setHighlightSections(False)
    window._zone_swatches = list(_t["canvas_accents"])
    window.zone_table.setStyleSheet(
        f"QTableWidget {{ background: {_t['panel']}; color: {_t['fg']}; "
        "font-size: 10pt; gridline-color: transparent; "
        f"alternate-background-color: {_t['sunken']}; "
        f"border: 1px solid {_t['border']}; border-radius: 6px; }}"
        f"QHeaderView::section {{ background: transparent; color: {_t['sub']}; font-size: 9pt; "
        f"font-weight: 700; padding: 8px 6px; border: none; "
        f"border-bottom: 1px solid {_t['border_strong']}; }}"
        f"QTableWidget::item {{ padding: 6px 10px; font-family: {_t['mono_family']}; "
        f"border-right: 1px solid {_t['border']}; }}"
        f"QTableWidget::item:hover {{ background: {_t['hover']}; }}"
        f"QTableWidget::item:selected {{ background: {_t['accent_soft']}; color: {_t['accent_fg']}; }}"
        f"QTableCornerButton::section {{ background: {_t['sunken']}; border: none; }}"
    )
    from .delegates import SelectAllDelegate

    window.zone_table.setItemDelegate(SelectAllDelegate(window.zone_table))

    def _repaint_zone_swatches():
        pal = window._zone_swatches
        for r in range(window.zone_table.rowCount()):
            col = QColor(pal[r % len(pal)])
            item = QTableWidgetItem(f" ● #{r + 1} ")
            item.setForeground(QBrush(col))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            window.zone_table.setVerticalHeaderItem(r, item)

    window._repaint_zone_swatches = _repaint_zone_swatches
    model = window.zone_table.model()
    model.rowsInserted.connect(lambda *a: _repaint_zone_swatches())
    model.rowsRemoved.connect(lambda *a: _repaint_zone_swatches())

    window._zone_init_1d(3)
    _repaint_zone_swatches()
    g_zone.addWidget(window.zone_table, 2, 0, 1, 2)

    window.zone_table.setVisible(False)
    nz_row.setVisible(False)
    window.combo_zone_axis.setVisible(False)
    window.zone_table.setEditTriggers(
        QAbstractItemView.EditTrigger.DoubleClicked
        | QAbstractItemView.EditTrigger.SelectedClicked
        | QAbstractItemView.EditTrigger.EditKeyPressed
        | QAbstractItemView.EditTrigger.AnyKeyPressed
    )

    def _zone_cell_validate(row, col):
        item = window.zone_table.item(row, col)
        if item is None:
            return
        txt = item.text().strip()
        if txt.startswith("="):
            from .expr_eval import eval_expr

            val = eval_expr(txt[1:])
            if val is not None:
                window.zone_table.blockSignals(True)
                item.setText(f"{val:.6g}")
                window.zone_table.blockSignals(False)
                txt = item.text().strip()
        bad = False
        percent_columns = window.zone_table.columnCount() - 2
        try:
            v = float(txt)
            if col < percent_columns:
                if v < 0 or v > 100:
                    bad = True
            elif v <= 0:
                bad = True
        except Exception:
            bad = True
        new = "true" if bad else "false"
        if item.data(Qt.ItemDataRole.UserRole + 1) != new:
            item.setData(Qt.ItemDataRole.UserRole + 1, new)
        if bad:
            item.setBackground(QBrush(QColor(get_theme()["err_soft"])))
            item.setToolTip("Value out of range" if col < percent_columns else "Value must be > 0")
        else:
            item.setBackground(QBrush())
            item.setToolTip("")

    window.zone_table.cellChanged.connect(_zone_cell_validate)

    btn_preview_z = QPushButton("预览布局  ↗")
    btn_preview_z.setFixedHeight(28)
    btn_preview_z.setStyleSheet(t.style("BTN_SECONDARY"))
    btn_preview_z.setToolTip("在算例画布上预览分区布局")

    def _preview_and_switch():
        window._draw_layout()
        try:
            window.workbench.switch_tab("layout")
        except Exception:
            pass

    btn_preview_z.clicked.connect(_preview_and_switch)
    lay.addWidget(btn_preview_z)
    lay.addStretch()
    scroll.setWidget(w)
    return scroll
