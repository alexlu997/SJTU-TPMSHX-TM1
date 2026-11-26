"""Build geometry, TPMS, grid, and compute-resource input bands in Style P2."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from .inspector_drawer import CollapsibleBand
from .symbols import SYM
from .theme import get_theme
from .window_config import LINE_EDITS

LABEL_COL_MIN_W = 118


def _on_dim_changed(window):
    """Toggle visibility of 3D-only inputs and valid flow directions by dimension."""
    is_3d = window.combo_dim.currentIndex() == 1
    window.lbl_domain_shape.setText("长方体" if is_3d else "矩形")
    for widget in getattr(window, "_3d_only_widgets", []):
        widget.setVisible(is_3d)
    from .builders_fluids import refresh_inlet_mode, sync_direction_items

    sync_direction_items(window, is_3d)
    for side in "AB":
        if hasattr(window, "le_mass_flow" + side):
            refresh_inlet_mode(window, side)
    window.workbench.update_tab_visibility()
    if (
        getattr(window, "canvas_layout", None) is not None
        and window.isVisible()
        and window.workbench.active_tab == "layout"
        and window.page_stack.currentIndex() == 0
    ):
        from .layout_drawer import draw_layout

        draw_layout(window, switch_tab=False)


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


def build_domain_sections(window, lay):
    """Build and register geometry, TPMS, grid, and resource bands."""
    from .field_factory import default_factory

    f = default_factory()
    t = f.theme
    combo_qss = t.style("COMBO")
    lbl_qss = t.style("LBL")

    # Reset the 3D-only widget registry; builders_fluids appends its 3D rows.
    window._3d_only_widgets = []
    window._ia_sections = {}

    # Domain geometry
    g_dom, sec_dom = _make_band_grid("域几何", first=True)
    window._ia_sections["domain_geometry"] = sec_dom
    window.le_L = f.row(g_dom, 0, *LINE_EDITS["le_L"].editor_text("长度"))
    window.le_H = f.row(g_dom, 1, *LINE_EDITS["le_H"].editor_text("横向尺寸"))
    window.le_Lz = f.row(g_dom, 2, *LINE_EDITS["le_Lz"].editor_text("厚度"))
    window._lbl_Lz = g_dom.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Lz, window._lbl_Lz]

    window.lbl_domain_shape = QLabel("矩形")
    window.lbl_domain_shape.setStyleSheet(lbl_qss)
    window.lbl_domain_shape.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    f.add_row(g_dom, 3, "计算域形状", window.lbl_domain_shape)

    window.combo_dim = QComboBox()
    window.combo_dim.addItems(["2D", "3D"])
    window.combo_dim.setStyleSheet(combo_qss)
    window.combo_dim.currentIndexChanged.connect(lambda *_: _on_dim_changed(window))
    window.combo_dim.setToolTip("选择求解器的计算维度；结果中的场图 / 三维只切换显示方式。")
    f.add_row(g_dom, 4, "计算维度", window.combo_dim)
    lay.addWidget(sec_dom)

    # TPMS structure (solid k_s lives here in 几何)
    g_tpms, sec_tpms = _make_band_grid(
        "TPMS 结构",
        actions=[("计算几何", window.compute_tpms)],
    )
    window._ia_sections["tpms_structure"] = sec_tpms
    window.combo_tpms = QComboBox()
    window.combo_tpms.addItems(["Diamond", "Gyroid"])
    window.combo_tpms.setCurrentIndex(1)
    window.combo_tpms.setStyleSheet(combo_qss)
    f.add_row(g_tpms, 0, "拓扑类型", window.combo_tpms)
    window.le_Lcell = f.row(g_tpms, 1, *LINE_EDITS["le_Lcell"].editor_text("胞元"))
    window.le_t = f.row(g_tpms, 2, *LINE_EDITS["le_t"].editor_text("壁厚"))
    window.le_ks = f.row(g_tpms, 3, *LINE_EDITS["le_ks"].editor_text("热导率"))
    lay.addWidget(sec_tpms)

    # Computed TPMS geometry metrics
    g_calc, sec_calc = _make_band_grid("几何计算值")
    window._ia_sections["tpms_computed"] = sec_calc
    window._v_eps = f.res_row(g_calc, 0, SYM["eps"])
    window._v_A0 = f.res_row(g_calc, 1, f"{SYM['A_0']} [m<sup>−1</sup>]")
    window._v_Dh = f.res_row(g_calc, 2, f"{SYM['D_h']} [mm]")
    window._v_Kss = f.res_row(g_calc, 3, f"{SYM['K_ss']} [W/(m·K)]")
    lay.addWidget(sec_calc)

    # Grid settings
    g_grid, sec_grid = _make_band_grid("网格设置", first=True)
    window._ia_sections["grid_rect"] = sec_grid
    window.le_Nx = f.row(g_grid, 0, *LINE_EDITS["le_Nx"].editor_text("网格"))
    window.le_Ny = f.row(g_grid, 1, *LINE_EDITS["le_Ny"].editor_text("网格"))
    window.le_Nz = f.row(g_grid, 2, *LINE_EDITS["le_Nz"].editor_text("三维网格"))
    window._lbl_Nz = g_grid.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Nz, window._lbl_Nz]

    window.combo_grid = QComboBox()
    window.combo_grid.addItem("常规网格", False)
    window.combo_grid.addItem("端口与壁面加密", True)
    window.combo_grid.setStyleSheet(combo_qss)
    window.combo_grid.setToolTip(
        "端口与壁面加密在开口边缘和壁面集中布置网格，Nx/Ny/Nz 包含全部加密单元。\n"
        "上海水—空气预设使用端口加密；修改几何后需重新检查网格精度。"
    )
    f.add_row(g_grid, 3, "网格方案", window.combo_grid)
    lay.addWidget(sec_grid)

    # Correlation applicability policy
    g_policy, sec_policy = _make_band_grid("关联式适用范围")
    window._ia_sections["correlation_policy"] = sec_policy
    tc = get_theme()
    chk_qss = (
        f"QCheckBox {{ color: {tc['fg']}; font-size: 10pt; font-weight: 400; "
        "background: transparent; border: 1px solid transparent; "
        "border-radius: 6px; padding: 4px 6px; spacing: 8px; }"
        f"QCheckBox:hover {{ border-color: {tc['chk_hover_border']}; "
        f"background: {tc['chk_hover_bg']}; }}"
        f"QCheckBox:focus {{ outline: 0; border: 1px solid {tc['inp_focus']}; }}"
    )
    window.chk_allow_extrap = QCheckBox("允许入口 Nu 超范围")
    window.chk_allow_extrap.setChecked(True)
    window.chk_allow_extrap.setToolTip(
        "入口 Re 超出 Nu 关联式拟合范围时继续计算并告警，关闭则拒绝该入口工况。\n"
        "此选项不修正 Nu，不放宽 D-F 几何范围，也不保证芯体内所有局部状态都在验证域。"
    )
    window.chk_allow_extrap.setStyleSheet(chk_qss)
    g_policy.addWidget(window.chk_allow_extrap, 0, 0, 1, 2)
    lay.addWidget(sec_policy)

    # Compute resources (3D only)
    g_cpu, sec_cpu = _make_band_grid("计算资源")
    window._ia_sections["compute_resources"] = sec_cpu
    cpu_card = QFrame()
    window._cpu_card = cpu_card
    cpu_card.setStyleSheet("QFrame { background: transparent; border: none; }")
    cpu_h = QHBoxLayout(cpu_card)
    cpu_h.setContentsMargins(0, 0, 0, 0)
    cpu_h.setSpacing(6)
    lbl_cores = QLabel("计算线程数")
    lbl_cores.setStyleSheet(
        f"QLabel {{ color: {tc['sub']}; font-size: 10pt; font-weight: 400; "
        "background: transparent; border: none; padding: 0; }"
    )
    window.spin_cpu_cores = QSpinBox()
    window.spin_cpu_cores.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.spin_cpu_cores.setFixedWidth(72)
    window.spin_cpu_cores.setMinimumHeight(26)
    window.spin_cpu_cores.setStyleSheet(
        f"QSpinBox {{ background: {tc['inp_bg']}; color: {tc['inp_fg']}; "
        f"border: 1px solid {tc['inp_border']}; border-radius: 5px; padding: 2px 4px; }}"
        f"QSpinBox:focus {{ border-color: {tc['inp_focus']}; }}"
        "QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }"
    )
    step_qss = (
        f"QPushButton {{ background: {tc['popover']}; color: {tc['fg']}; "
        f"border: 1px solid {tc['border_strong']}; border-radius: 5px; "
        "font-size: 11pt; font-weight: 600; padding: 0; }"
        f"QPushButton:hover {{ border-color: {tc['accent']}; background: {tc['hover']}; }}"
        f"QPushButton:pressed {{ background: {tc['sunken']}; }}"
    )
    btn_dn = QPushButton("−")
    btn_up = QPushButton("+")
    for btn, fn, tip in (
        (btn_dn, window.spin_cpu_cores.stepDown, "减少线程数"),
        (btn_up, window.spin_cpu_cores.stepUp, "增加线程数"),
    ):
        btn.setFixedSize(26, 26)
        btn.setStyleSheet(step_qss)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(fn)

    cpu_h.addWidget(lbl_cores)
    cpu_h.addStretch(1)
    cpu_h.addWidget(btn_dn)
    cpu_h.addWidget(window.spin_cpu_cores)
    cpu_h.addWidget(btn_up)
    g_cpu.addWidget(cpu_card, 0, 0, 1, 2)
    window._3d_only_widgets.append(sec_cpu)
    lay.addWidget(sec_cpu)

    _on_dim_changed(window)
