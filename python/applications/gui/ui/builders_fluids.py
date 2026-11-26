"""Build unified 2D/3D fluid, model, and port sections in Style P2."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .inspector_drawer import CollapsibleBand
from .symbols import SYM
from .theme import RADIUS_BTN, get_theme
from .window_config import LINE_EDITS

LABEL_COL_MIN_W = 118

_DIR_ITEMS = [
    "+x  左 → 右",
    "−x  右 → 左",
    "+y  下 → 上",
    "−y  上 → 下",
    "+z  前 → 后 (3D)",
    "−z  后 → 前 (3D)",
]


def sync_direction_items(window, is_3d: bool) -> None:
    """Expose 4 planar directions in 2D and all 6 directions in 3D."""
    items = _DIR_ITEMS if is_3d else _DIR_ITEMS[:4]
    for side, fallback in (("A", 0), ("B", 3)):
        combo = getattr(window, f"combo_dir{side}", None)
        if combo is None or combo.count() == len(items):
            continue
        current = combo.currentIndex()
        next_idx = current if 0 <= current < len(items) else fallback
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItems(items)
            combo.setCurrentIndex(next_idx)
        if next_idx != current and hasattr(window, "_on_dir_changed"):
            window._on_dir_changed()


def refresh_fluid_model_visibility(window):
    """Show sCO2 and CO2 model notes when selected; never clear saved values."""
    relevant = (
        window.combo_fluidA.currentIndex() == 2
        or window.combo_fluidB.currentIndex() == 2
        or window.combo_sco2_nu_mode.currentData() != "cfd_smooth"
    )
    window._ia_sections["sco2_nu"].setVisible(relevant)
    window._co2_fixed_notice.setVisible(
        any(combo.currentIndex() == 3 for combo in (window.combo_fluidA, window.combo_fluidB))
    )


def refresh_inlet_mode(window, side):
    """Switch velocity vs mass-flow editability on one side."""
    from .window_config import mass_flow_active

    active = mass_flow_active(window, side)
    getattr(window, "le_u" + side).setReadOnly(active)
    getattr(window, "le_mass_flow" + side).setEnabled(active)
    title = "上次解析速度" if active else "入口速度"
    label, _ = LINE_EDITS[f"le_u{side}"].editor_text(title, side)
    from .field_factory import _split_trailing_unit

    clean_label, _ = _split_trailing_unit(label)
    getattr(window, "_lbl_u" + side).setText(clean_label)
    window._kick_badge_timer()


def _make_band_grid(
    title: str,
    *,
    first: bool = False,
    expanded: bool = True,
    actions=(),
) -> tuple[QGridLayout, CollapsibleBand]:
    band = CollapsibleBand(
        title,
        first=first,
        collapsible=True,
        expanded=expanded,
        actions=actions,
    )
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    grid = QGridLayout(body)
    grid.setContentsMargins(16, 10, 16, 12)
    grid.setVerticalSpacing(8)
    grid.setHorizontalSpacing(10)
    grid.setColumnMinimumWidth(0, LABEL_COL_MIN_W)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 1)
    band.set_body(body)
    return grid, band


def _build_pipe_section(window, lay, side, *, combo_style, dir_index):
    """Build compact paired center/width port rows; flow direction updates axis labels."""
    from .field_factory import default_factory

    f = default_factory()
    theme = get_theme()
    gio, sec = _make_band_grid(f"端口 {side}")
    gio.setColumnStretch(1, 1)
    gio.setColumnStretch(2, 1)
    window._ia_sections[f"pipe_{side.lower()}"] = sec
    combo = QComboBox()
    is_3d = hasattr(window, "combo_dim") and window.combo_dim.currentIndex() == 1
    combo.addItems(_DIR_ITEMS if is_3d else _DIR_ITEMS[:4])
    combo.setCurrentIndex(dir_index if dir_index < combo.count() else 0)
    combo.setStyleSheet(combo_style)
    combo.currentIndexChanged.connect(window._on_dir_changed)
    setattr(window, f"combo_dir{side}", combo)
    dir_lbl = f.label("流动方向")
    gio.addWidget(dir_lbl, 0, 0)
    gio.addWidget(combo, 0, 1, 1, 2)

    hdr_css = f"color: {theme['tert']}; font-size: 11px; font-weight: 500; background: transparent; border: none;"
    for col, heading in ((1, "中心"), (2, "宽度")):
        h = QLabel(heading)
        h.setStyleSheet(hdr_css)
        gio.addWidget(h, 1, col)

    pair_defs = (
        ("in", "", "入口", False),
        ("in", "z_", "入口", True),
        ("out", "", "出口", False),
        ("out", "z_", "出口", True),
    )
    for row_offset, (end, key, port_title, is_3d_pair) in enumerate(pair_defs, start=2):
        ctr_spec = LINE_EDITS[f"le_pipe{side}_{end}_{key}ctr"]
        w_spec = LINE_EDITS[f"le_pipe{side}_{end}_{key}w"]
        row_lbl = f.label(f"{port_title} {'z' if is_3d_pair else 'x'}")
        gio.addWidget(row_lbl, row_offset, 0)
        setattr(window, f"_lbl_pipe{side}_{end}_{key}row", row_lbl)
        setattr(window, f"_lbl_pipe{side}_{end}_{key}ctr", row_lbl)
        setattr(window, f"_lbl_pipe{side}_{end}_{key}w", row_lbl)

        ctr_le = f.line_edit("" if ctr_spec.default is None else str(ctr_spec.default), unit="m")
        ctr_le.set_display_unit("mm", 1e3)
        w_le = f.line_edit("" if w_spec.default is None else str(w_spec.default), unit="m")
        w_le.set_display_unit("mm", 1e3)
        gio.addWidget(ctr_le, row_offset, 1)
        gio.addWidget(w_le, row_offset, 2)
        setattr(window, ctr_spec.widget, ctr_le)
        setattr(window, w_spec.widget, w_le)
        if is_3d_pair:
            window._3d_only_widgets += [row_lbl, ctr_le, w_le]

    combo.setToolTip("入口速度在指定几何开口内均匀施加；开口外为壁面。")
    lay.addWidget(sec)


def _build_fluid_io_rows(window, g, side, t):
    """Build fluid state inputs and collapsible property preview for one side."""
    from .field_factory import default_factory

    f = default_factory()
    s = side
    mode = QComboBox()
    mode.addItem("速度 [m/s]", "velocity")
    mode.addItem("总质量流量 [kg/s]", "mass_flow")
    mode.setStyleSheet(t.style("COMBO"))
    setattr(window, f"combo_inlet_mode{s}", mode)
    f.add_row(g, 1, "入口输入", mode)
    window._3d_only_widgets += [
        g.itemAtPosition(1, 0).widget(),
        g.itemAtPosition(1, 1).widget(),
    ]

    velocity = LINE_EDITS[f"le_u{s}"]
    setattr(window, velocity.widget, f.row(g, 2, *velocity.editor_text("入口速度", s)))
    setattr(window, f"_lbl_u{s}", g.itemAtPosition(2, 0).widget())

    mass_flow = LINE_EDITS[f"le_mass_flow{s}"]
    flow = f.row(g, 3, *mass_flow.editor_text("总质量流量", s))
    flow.setPlaceholderText("输入正数")
    flow.setToolTip("按实际入口孔隙率和开口积分换算；计算或自动填充时更新速度。")
    setattr(window, f"le_mass_flow{s}", flow)
    window._3d_only_widgets += [flow, g.itemAtPosition(3, 0).widget()]
    mode.currentIndexChanged.connect(lambda: refresh_inlet_mode(window, side))
    refresh_inlet_mode(window, side)

    inlet_temp = LINE_EDITS[f"le_Tin{s}"]
    setattr(window, inlet_temp.widget, f.row(g, 4, *inlet_temp.editor_text("入口温度", s)))
    setattr(window, f"_lbl_Tin{s}_unit", g.itemAtPosition(4, 0).widget())

    pressure = LINE_EDITS[f"le_Pin{s}"]
    pin_le = f.row(g, 5, *pressure.editor_text("入口绝压", s))
    pin_le.set_display_unit("kPa", 1e-3)
    setattr(window, pressure.widget, pin_le)

    gd, computed = _make_band_grid("物性预览", expanded=False)
    computed._set_expanded = computed.set_expanded
    setattr(window, f"_fluid_computed_{s}", computed)
    setattr(window, f"_v_rho{s}", f.res_row(gd, 0, f"{SYM['rho']} [kg/m³]"))
    setattr(window, f"_v_Re{s}", f.res_row(gd, 1, SYM["Re"]))
    setattr(window, f"_v_Nu{s}", f.res_row(gd, 2, SYM["Nu"]))
    setattr(window, f"_v_dPL{s}", f.res_row(gd, 3, "d<i>P</i>/d<i>L</i> [Pa/m]"))
    g.addWidget(computed, 6, 0, 1, 2)


def build_fluid_sections(window, lay):
    """Build solver-model bands and the unified [流体 A | 流体 B] boundary panel."""
    from .field_factory import default_factory

    f = default_factory()
    t = f.theme
    theme = get_theme()
    combo_qss = t.style("COMBO")

    # Darcy-Forchheimer model band (placed in 求解 tab)
    g_method, method_section = _make_band_grid("Darcy–Forchheimer 求解方法")
    window._ia_sections["df_method"] = method_section
    window.combo_df_mode = QComboBox()
    window.combo_df_mode.addItem("CFD 光滑壁面", "cfd_smooth")
    window.combo_df_mode.addItem("实验标定", "experimental")
    window.combo_df_mode.setStyleSheet(combo_qss)
    window.combo_df_mode.setToolTip(
        "内置上海预设默认使用实验标定。"
        "实验标定使用与具体实验 campaign、边界和压降定义绑定的有效修正；"
        "数据集选择不代表已证实的工质本征效应。"
    )
    f.add_row(g_method, 0, "方法", window.combo_df_mode)
    window._co2_fixed_notice = QLabel(
        "CO₂：单相 HEOS；阻力 ×2.5、Nu ×1.28 为固定修正，独立于上方选择。"
        "两侧共用 CO₂ CFD 几何。"
    )
    window._co2_fixed_notice.setWordWrap(True)
    window._co2_fixed_notice.setStyleSheet(
        f"color: {theme['sub']}; font-size: 9pt; background: transparent; border: none;"
    )
    g_method.addWidget(window._co2_fixed_notice, 1, 0, 1, 2)
    lay.addWidget(method_section)

    # sCO2 Nu model band (placed in 求解 tab)
    g_nu, nu_section = _make_band_grid("sCO₂ Nu 换热模型")
    window._ia_sections["sco2_nu"] = nu_section
    window.combo_sco2_nu_mode = QComboBox()
    window.combo_sco2_nu_mode.addItem("CFD 光滑壁面（默认）", "cfd_smooth")
    window.combo_sco2_nu_mode.addItem("有效系数标定", "experimental")
    window.combo_sco2_nu_mode.setStyleSheet(combo_qss)
    window.combo_sco2_nu_mode.setToolTip("独立于 D-F；选择现行有效系数，或导入带来源的参数。")
    f.add_row(g_nu, 0, "方法", window.combo_sco2_nu_mode)
    window.btn_sco2_nu_current = QPushButton("使用现行有效系数")
    window.btn_sco2_nu_current.setStyleSheet(t.style("BTN_SECONDARY"))
    window.btn_sco2_nu_current.setToolTip("Gyroid 为换热量标定；Diamond 为同倍率迁移。适用范围见参数来源。")
    window.btn_sco2_nu_current.clicked.connect(window.case_files.use_current_sco2_nu_parameters)
    f.add_row(g_nu, 1, "现行参数", window.btn_sco2_nu_current)
    window.btn_sco2_nu_parameters = QPushButton("导入标定参数…")
    window.btn_sco2_nu_parameters.setStyleSheet(t.style("BTN_SECONDARY"))
    window.btn_sco2_nu_parameters.clicked.connect(window.case_files.load_sco2_nu_parameters)
    f.add_row(g_nu, 2, "其他参数", window.btn_sco2_nu_parameters)
    window.lbl_sco2_nu_parameters = QLabel("未导入标定参数")
    window.lbl_sco2_nu_parameters.setStyleSheet(t.style("LBL"))
    window.lbl_sco2_nu_parameters.setWordWrap(True)
    f.add_row(g_nu, 3, "来源", window.lbl_sco2_nu_parameters)
    lay.addWidget(nu_section)

    # Unified [流体 A | 流体 B] boundary panel for both 2D and 3D
    boundary_host = QWidget()
    boundary_host.setStyleSheet("background: transparent;")
    b_lay = QVBoxLayout(boundary_host)
    b_lay.setContentsMargins(0, 0, 0, 0)
    b_lay.setSpacing(0)

    seg_wrap = QWidget()
    seg_wrap.setStyleSheet("background: transparent;")
    sw_lay = QHBoxLayout(seg_wrap)
    sw_lay.setContentsMargins(16, 10, 16, 10)
    sw_lay.setSpacing(0)
    seg_frame = QFrame()
    seg_frame.setStyleSheet(
        f"QFrame {{ background: {theme['sunken']}; border: none; border-radius: {RADIUS_BTN}px; }}"
    )
    sf_lay = QHBoxLayout(seg_frame)
    sf_lay.setContentsMargins(2, 2, 2, 2)
    sf_lay.setSpacing(2)

    seg_on_qss = (
        f"QPushButton {{ background: {theme['seg_on']}; color: {theme['fg']}; "
        f"border: 1px solid {theme['border']}; border-radius: 5px; "
        "font-size: 12px; font-weight: 600; }"
    )
    seg_off_qss = (
        f"QPushButton {{ background: transparent; color: {theme['sub']}; "
        "border: none; border-radius: 5px; font-size: 12px; font-weight: 400; }"
        f"QPushButton:hover {{ color: {theme['fg']}; }}"
    )

    side_stack = QStackedWidget()
    side_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
    window._fluid_side_stack = side_stack
    window._fluid_side_btns = []
    window._fluid_side_pages = {}

    def select_fluid_side(idx: int) -> None:
        side_stack.setCurrentIndex(idx)
        for i, btn in enumerate(window._fluid_side_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(seg_on_qss if i == idx else seg_off_qss)

    window._select_fluid_side = select_fluid_side

    for idx, label in enumerate(("流体 A", "流体 B")):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFixedHeight(26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, i=idx: select_fluid_side(i))
        sf_lay.addWidget(btn, 1)
        window._fluid_side_btns.append(btn)

    sw_lay.addWidget(seg_frame, 1)
    b_lay.addWidget(seg_wrap)
    b_lay.addWidget(side_stack, 1)

    fluid_types = ["Air", "Water", "sCO₂", "CO₂"]
    for side, default_fluid, default_dir in (("A", 0, 0), ("B", 1, 3)):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        p_lay = QVBoxLayout(page)
        p_lay.setContentsMargins(0, 0, 0, 0)
        p_lay.setSpacing(0)

        auto_fill_cb = getattr(window, f"auto_fill_fluid_{side.lower()}")
        g_fl, band_fl = _make_band_grid(
            f"流体 {side}",
            actions=[("自动填充", auto_fill_cb)],
        )
        window._ia_sections[f"fluid_{side.lower()}"] = band_fl

        combo = QComboBox()
        combo.addItems(fluid_types)
        combo.setCurrentIndex(default_fluid)
        combo.setStyleSheet(combo_qss)
        combo.setToolTip(
            f"Fluid {side} supports Air, Water, sCO₂ and single-phase CO₂ (2D + 3D)."
        )
        setattr(window, f"combo_fluid{side}", combo)
        f.add_row(g_fl, 0, "流体类型", combo)
        _build_fluid_io_rows(window, g_fl, side, t)
        p_lay.addWidget(band_fl)

        _build_pipe_section(
            window,
            p_lay,
            side,
            combo_style=combo_qss,
            dir_index=default_dir,
        )
        p_lay.addStretch(1)
        side_stack.addWidget(page)
        window._fluid_side_pages[side] = page

    select_fluid_side(0)
    window._fluids_row = boundary_host
    window._ia_sections["fluids_row"] = boundary_host
    lay.addWidget(boundary_host)

    def clear_df_preview():
        for side in ("A", "B"):
            getattr(window, f"_v_dPL{side}").setText("—")

    window.combo_df_mode.currentIndexChanged.connect(clear_df_preview)
    for combo in (window.combo_fluidA, window.combo_fluidB, window.combo_sco2_nu_mode):
        combo.currentIndexChanged.connect(lambda *_: refresh_fluid_model_visibility(window))
    refresh_fluid_model_visibility(window)

    try:
        window._on_dir_changed()
    except Exception:
        pass
