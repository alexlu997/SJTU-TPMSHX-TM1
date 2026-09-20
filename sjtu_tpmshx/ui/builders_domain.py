"""Domain-page builder (Geometry accordion group) + dimensionality toggle.

Split out of ui_builders.py (Batch-2, 2026-06-10). Builds the Domain
Geometry / TPMS Structure / Material / Grid Settings / Results sections
and owns ``_on_dim_changed`` — the 2D↔3D visibility toggle for the
3D-only widgets created here and in builders_fluids.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QScrollArea, QFrame, QCheckBox,
)

from .theme import get_theme
from .builders_base import (section, collapsible_section, row, res_row, add_row, right_align_combo)
from .window_config import DOMAIN_SHAPE_NOTICE


def _res_ab_row(window, rg, r, label, attr_a, attr_b, *, unit_lbl_attrs=None):
    """One A/B result-row pair in the results grid (B1 1.4): same label,
    column 0 for Fluid A and column 2 for Fluid B. ``unit_lbl_attrs``
    optionally captures the two label widgets (for the K/°C unit toggle).
    """
    setattr(window, attr_a, res_row(window, rg, r, label, 0))
    setattr(window, attr_b, res_row(window, rg, r, label, 2))
    if unit_lbl_attrs is not None:
        try:
            for col, lbl_attr in zip((0, 2), unit_lbl_attrs):
                item = rg.itemAtPosition(r, col)
                if item is not None:
                    setattr(window, lbl_attr, item.widget())
        except Exception:
            pass


def _on_dim_changed(window):
    """Toggle visibility of 3D-only inputs based on Dimensionality combo.

    Iterates the ``window._3d_only_widgets`` registry — populated by
    ``build_page_domain`` (Lz/Nz rows + 3D checkboxes) and
    ``builders_fluids.build_page_fluids`` (z-partial BC rows) as the
    widgets are created. New 3D-only widgets just register themselves;
    no hardcoded attribute list to keep in sync.
    """
    is_3d = window.combo_dim.currentIndex() == 1
    for w in getattr(window, '_3d_only_widgets', []):
        w.setVisible(is_3d)
    # Mode change also reveals/hides the result tabs for the current mode
    if hasattr(window, '_update_tab_visibility'):
        window._update_tab_visibility()


def build_page_domain(window):
    """Ex-Main_Menu._build_page_domain(self) -> QScrollArea."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
    _T_NEUTRAL = t.style('T_NEUTRAL')
    _F_NEUTRAL = t.style('F_NEUTRAL')
    _COMBO = t.style('COMBO')
    _BTN_TPMS = t.style('BTN_TPMS')
    _LBL = t.style('LBL')
    _VAL = t.style('VAL')

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    # ui-layout-fixes: labels word-wrap instead of widening the card, so a
    # horizontal scrollbar can only mean clipped inputs — forbid it.
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12); lay.setContentsMargins(6, 4, 8, 6)

    # 3D-only widget registry — reset here because the domain page builds
    # first on every (re)build; builders_fluids appends its z-partial rows.
    window._3d_only_widgets = []
    # ui-ia-batch1: section-container registry. The page builders create the
    # widgets; build_param_tabs re-homes these containers into the four
    # workflow accordion groups (the page scroll shells are discarded).
    window._ia_sections = {}

    # Domain Geometry
    g, _sec_dg = section(window, lay, "  域几何", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['domain_geometry'] = _sec_dg
    window.le_L        = row(window, g, 0, "长度 <i>L</i> [m]", "0.182")
    window.le_H        = row(window, g, 1, "横向尺寸 <i>H</i> [m]", "0.042")
    window.le_Lz       = row(window, g, 2, "厚度 <i>L<sub>z</sub></i> [m]", "0.042")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Lz, window._lbl_Lz]

    # Update edge labels when L or H changes
    window.le_L.editingFinished.connect(window._update_edge_combos)
    window.le_H.editingFinished.connect(window._update_edge_combos)

    # Domain shape selector
    window.combo_shape = QComboBox()
    window.combo_shape.addItems(["Rectangle", "Hexagon", "Octagon"])
    # Keep saved shape indices; unavailable polygons must not become rectangles.
    for index in (1, 2):
        window.combo_shape.model().item(index).setEnabled(False)
        window.combo_shape.setItemData(index, DOMAIN_SHAPE_NOTICE, Qt.ItemDataRole.ToolTipRole)
    window.combo_shape.setToolTip(DOMAIN_SHAPE_NOTICE)
    window.combo_shape.setStyleSheet(_COMBO)
    window.combo_shape.currentIndexChanged.connect(window._on_shape_changed)
    add_row(window, g, 3, "计算域形状", right_align_combo(window.combo_shape))

    # Dimensionality (2D / 3D MVP) — dispatch in run_calculation
    window.combo_dim = QComboBox()
    window.combo_dim.addItems(["2D", "3D"])
    window.combo_dim.setStyleSheet(_COMBO)
    window.combo_dim.currentIndexChanged.connect(
        lambda *_: _on_dim_changed(window))
    window.combo_dim.setToolTip("选择求解器的计算维度；结果中的场图 / 三维只切换显示方式。")
    add_row(window, g, 4, "计算维度", right_align_combo(window.combo_dim))

    # ── TPMS Structure ──
    g0, _sec_tp = section(window, lay, "  TPMS 结构", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['tpms_structure'] = _sec_tp
    window.combo_tpms = QComboBox()
    window.combo_tpms.addItems(["Diamond", "Gyroid"])
    window.combo_tpms.setCurrentIndex(1)  # default Gyroid
    window.combo_tpms.setStyleSheet(_COMBO)
    add_row(window, g0, 0, "拓扑类型", right_align_combo(window.combo_tpms))
    window.le_Lcell = row(window, g0, 1, "胞元 <i>L</i><sub>cell</sub> [mm]", "7.0")
    # t=0.6 mm is the Shanghai specimen and a supported fixed-CFD node.
    window.le_t     = row(window, g0, 2, "壁厚 <i>t</i> [mm]", "0.6")
    window.le_ks    = row(window, g0, 3, "热导率 <i>k</i><sub>s</sub> [W/(m·K)]", "16.0")
    btn_tpms = QPushButton("计算 TPMS 几何")
    btn_tpms.setFixedHeight(28); btn_tpms.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_tpms.setToolTip("Compute porosity, specific area, hydraulic diameter, k_ss from current L_cell / t")
    btn_tpms.clicked.connect(window.compute_tpms)
    g0.addWidget(btn_tpms, 4, 0, 1, 2)
    # Computed outputs — own collapsible card (ui-ia-batch1 / IA-2): starts
    # collapsed so the input flow reads clean; compute_tpms auto-expands it
    # via container._set_expanded once values exist.
    gC, _sec_tc = collapsible_section(
        window, lay, "几何计算值", _T_NEUTRAL, _F_NEUTRAL,
        expanded=False)
    window._ia_sections['tpms_computed'] = _sec_tc
    window._v_eps  = res_row(window, gC, 0, "<i>&epsilon;</i>")
    window._v_A0   = res_row(window, gC, 1, "<i>A</i><sub>0</sub> [m<sup>-1</sup>]")
    window._v_Dh   = res_row(window, gC, 2, "<i>D<sub>h</sub></i> [mm]")
    window._v_Kss  = res_row(window, gC, 3, "<i>K</i><sub>ss</sub> [W/(m·K)]")
    # NOTE: `chk_allow_extrap` used to live here; relocated to the
    # collapsible "Advanced" sub-section built right after Grid Settings
    # (2026-06-25 UI declutter). Construction is unchanged — just reparented.

    # Material — only rho_s remains (k_s is in the solver/geometry panel).
    # cp_s and cp_f were removed: no solver path reads them. Solid cp is a
    # per-material constant hardcoded downstream; fluid cp is computed
    # per-cell via air_cp(T) inside tpms_calc.
    g2, _sec_mat = section(window, lay, "  材料属性", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['material'] = _sec_mat
    window.le_rho_s = row(window, g2, 0, "<i>&rho;</i><sub>s</sub> [kg/m³]", "7900")
    # rho_s is NOT consumed by the steady-state LTNE energy equation
    # (∂T_s/∂t is dropped → ρ_s·cp_s prefactor disappears). It is saved with
    # the session config for forward compatibility with a future transient
    # extension (kernel would add ρ_s·cp_s·(T_s^{n+1}−T_s^n)/Δt).
    window.le_rho_s.setToolTip(
        "Solid density. Saved with session config but NOT read by the "
        "current steady-state LTNE solver (no ∂T_s/∂t term in the solid "
        "energy equation). Reserved for a future transient extension.")
    # T_s_init removed from UI (2026-04-29) -- was numerical iteration seed
    # only, not a physical parameter. Solver auto-seeds at 0.5*(T_inA+T_inB);
    # converged Ts is independent of seed within solver tolerance. Removed to
    # avoid user confusion. _parse_inputs falls back to None when le_TsInit
    # absent via getattr().

    # ── Grid Settings (rect mode) ──
    g4, sec_solver_rect = section(window, lay, "  网格设置", _T_NEUTRAL, _F_NEUTRAL)
    window._rect_only_widgets.append(sec_solver_rect)
    window._ia_sections['grid_rect'] = sec_solver_rect
    window.le_Nx = row(window, g4, 0, "网格 <i>N<sub>x</sub></i>", "30")
    window.le_Ny = row(window, g4, 1, "网格 <i>N<sub>y</sub></i>", "20")
    window.le_Nz = row(window, g4, 2, "网格 <i>N<sub>z</sub></i>（三维）", "5")
    window._lbl_Nz = g4.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Nz, window._lbl_Nz]

    # Research controls keep their existing values and preset keys, but stay
    # folded away from the everyday compute-resource control below.
    g_adv, _sec_adv = collapsible_section(
        window, lay, "专家设置", _T_NEUTRAL, _F_NEUTRAL, expanded=False,
        on_toggle=lambda _open: _on_dim_changed(window))
    window._ia_sections['advanced_flags'] = _sec_adv

    # Keep advanced options as regular-weight rows inside their shared card.
    # Native indicators preserve a visible checkmark and keyboard feedback.
    _tc = get_theme()
    _chk_box_qss = f"""
        QCheckBox {{
            color: {_tc['fg']};
            font-size: 10pt;
            font-weight: 400;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 6px 10px;
            spacing: 8px;
        }}
        QCheckBox:hover {{ border-color: {_tc['chk_hover_border']}; background: {_tc['chk_hover_bg']}; }}
        QCheckBox:focus {{
            outline: 0;
            border: 1px solid {_tc['inp_focus']};
        }}
    """

    # Geometry cannot extrapolate beyond the fixed CFD grid. This switch only
    # downgrades a fluid-specific Nu Reynolds-window violation to a warning.
    window.chk_allow_extrap = QCheckBox("允许入口 Nu 超范围")
    window.chk_allow_extrap.setChecked(True)
    window.chk_allow_extrap.setToolTip(
        "入口 Re 超出 Nu 关联式拟合范围时继续计算并告警，关闭则拒绝该入口工况。\n"
        "此选项不修正 Nu，不放宽 D-F 几何范围，也不保证芯体内所有局部状态都在验证域。"
    )
    window.chk_allow_extrap.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_allow_extrap, 0, 0, 1, 2)

    # 3D wall-refine checkbox — adds 8 BL cells near each wall (all 6 faces).
    # Kept for explicit six-wall studies; Shanghai uses the port-aligned option.
    window.chk_wall_refine_3d = QCheckBox("六壁面加密（3D）")
    window.chk_wall_refine_3d.setChecked(False)
    window.chk_wall_refine_3d.setToolTip(
        "六个壁面各增加 8 层网格，三轴实际格数各增加 16，与端口/壁面加密互斥。\n"
        "用于特定网格研究，计算代价与精度需结合实际网格检查。")
    window.chk_wall_refine_3d.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_wall_refine_3d, 1, 0, 1, 2)
    window._3d_only_widgets.append(window.chk_wall_refine_3d)
    window.chk_port_wall_refine = QCheckBox("端口与壁面加密（2D / 3D）")
    window.chk_port_wall_refine.setToolTip(
        "在端口边缘和壁面集中布置网格，Nx/Ny/Nz 包含全部加密单元。\n"
        "上海水—空气推荐网格由预设提供；修改几何后需重新检查网格精度。")
    window.chk_port_wall_refine.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_port_wall_refine, 2, 0, 1, 2)
    window.chk_port_wall_refine.toggled.connect(
        lambda checked: window.chk_wall_refine_3d.setChecked(False) if checked else None)
    window.chk_wall_refine_3d.toggled.connect(
        lambda checked: window.chk_port_wall_refine.setChecked(False) if checked else None)
    # NOTE: legacy `_chk_wall_refine_3d` alias removed 2026-05-05 audit;
    # no remaining readers (grep confirmed). Use `chk_wall_refine_3d`.

    # This also gates the eligible air/water model-h transport path; it is
    # not the master switch for sCO2 variable properties or true-h transport.
    window.chk_var_rhocp = QCheckBox("局部密度热输运（3D）")
    window.chk_var_rhocp.setChecked(True)
    window.chk_var_rhocp.setToolTip(
        "使用局部流场密度参与 3D 热输运，并在满足条件的空气/水组合中启用对应质量通量路径。\n"
        "默认开启；关闭用于旧路径对照，不是 sCO₂ 变物性的总开关。")
    window.chk_var_rhocp.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_var_rhocp, 3, 0, 1, 2)
    window._3d_only_widgets.append(window.chk_var_rhocp)

    # The ordinary compute orchestrator captures this thread-local Numba
    # mask at launch and applies it in the worker. Optimization has its own
    # resource policy; headless runs use TPMSHX_NUM_THREADS.
    from PySide6.QtWidgets import QSpinBox, QHBoxLayout
    from sjtu_tpmshx.solvers.threads import (max_threads as _max_threads,
                                 get_solver_threads as _get_threads,
                                 set_solver_threads as _set_threads)
    _mx_cores = _max_threads()
    g_cpu, sec_cpu = section(window, lay, "计算资源", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['compute_resources'] = sec_cpu
    # Separate the resource control from numerical switches. The spinbox
    # supports both keyboard entry and the −/+ buttons below.
    _cpu_card = QFrame()
    _cpu_card.setStyleSheet("QFrame { background:transparent; border:none; }")
    _cpu_h = QHBoxLayout(_cpu_card)
    _cpu_h.setContentsMargins(0, 0, 0, 0)
    _cpu_h.setSpacing(8)
    _lbl_cores = QLabel("计算线程数")
    _lbl_cores.setStyleSheet(
        f"QLabel {{ color:{_tc['fg']}; font-size:10pt; font-weight:400;"
        f" background:transparent; border:none; padding:0; }}")
    window.spin_cpu_cores = QSpinBox()
    window.spin_cpu_cores.setRange(1, _mx_cores)
    window.spin_cpu_cores.setValue(_get_threads())
    window.spin_cpu_cores.setToolTip(
        f"设置下一次普通计算使用的 Numba 并行核线程数（1–{_mx_cores}），小网格可能使用串行核。\n"
        "它不限制整个应用的 CPU 占用，也不控制优化任务数量。")
    _lbl_cores.setToolTip(window.spin_cpu_cores.toolTip())
    # Native QSpinBox arrows can't be themed reliably here: an ANCESTOR
    # stylesheet forces every descendant onto QStyleSheetStyle, and a QSS-styled
    # spin button with no ::up-arrow/::down-arrow IMAGE renders invisible (the
    # exact symptom: "no buttons, only manual input"). So drop the native arrows
    # and drive the value with two real QPushButtons — always visible, always
    # clickable, fully themeable. The field stays editable for keyboard entry;
    # stepUp/stepDown honour the [1, max] range.
    window.spin_cpu_cores.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    window.spin_cpu_cores.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.spin_cpu_cores.setFixedWidth(48)
    window.spin_cpu_cores.setMinimumHeight(24)
    window.spin_cpu_cores.setStyleSheet(
        f"QSpinBox {{ background:{_tc['inp_bg']}; color:{_tc['inp_fg']};"
        f" border:1px solid {_tc['inp_border']}; border-radius:4px; padding:2px 4px; }}"
        f"QSpinBox:focus {{ border-color:{_tc['inp_focus']}; }}")
    window.spin_cpu_cores.valueChanged.connect(lambda n: _set_threads(int(n)))

    _step_qss = (
        f"QPushButton {{ background:{_tc['surface_elevated']}; color:{_tc['fg']};"
        f" border:1px solid {_tc['inp_border']}; border-radius:4px;"
        f" font-size:12pt; font-weight:bold; padding:0; }}"
        f"QPushButton:hover {{ border-color:{_tc['chk_hover_border']};"
        f" background:{_tc['chk_hover_bg']}; }}"
        f"QPushButton:pressed {{ background:{_tc['inp_bg']}; }}")
    _btn_dn = QPushButton("−")            # U+2212 MINUS SIGN
    _btn_up = QPushButton("+")
    window._spin_cpu_btns = (_btn_dn, _btn_up)
    for _b, _fn, _tip in ((_btn_dn, window.spin_cpu_cores.stepDown, "减少线程数"),
                          (_btn_up, window.spin_cpu_cores.stepUp,   "增加线程数")):
        _b.setFixedSize(24, 24)
        _b.setStyleSheet(_step_qss)
        _b.setToolTip(_tip)
        _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _b.clicked.connect(_fn)

    _cpu_h.addWidget(_lbl_cores)
    _cpu_h.addStretch(1)
    _cpu_h.addWidget(_btn_dn)
    _cpu_h.addWidget(window.spin_cpu_cores)
    _cpu_h.addWidget(_btn_up)
    g_cpu.addWidget(_cpu_card, 0, 0, 1, 2)
    # Hide the heading too when this 3D-only control is unavailable.
    window._3d_only_widgets.append(sec_cpu)

    # Hide 3D-only inputs by default (2D mode)
    _on_dim_changed(window)

    # ── Solver Settings (polygon mode) ──
    gp, sec_solver_poly = section(window, lay, "  网格划分", _T_NEUTRAL, _F_NEUTRAL)
    window._poly_only_widgets.append(sec_solver_poly)
    window._ia_sections['mesh_poly'] = sec_solver_poly
    sec_solver_poly.hide()  # hidden by default (rect mode)
    window.le_mesh_density = row(window, gp, 0, "Target cells", "auto")
    window._v_mesh_actual  = res_row(window, gp, 1, "Actual cells")

    # ── Results ──
    res_frame = QFrame()
    res_frame.setStyleSheet(_F_NEUTRAL)
    rg = QGridLayout(res_frame)
    rg.setContentsMargins(14, 8, 14, 8)
    rg.setHorizontalSpacing(20); rg.setVerticalSpacing(6)
    rg.setColumnStretch(0, 2); rg.setColumnStretch(1, 1)
    rg.setColumnStretch(2, 2); rg.setColumnStretch(3, 1)
    for c, txt in enumerate(["── Fluid A ──", "── Fluid B ──"]):
        h = QLabel(txt)
        h.setStyleSheet(_LBL)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rg.addWidget(h, 0, c * 2, 1, 2)
    # A/B result rows via the shared mirror helper (B1 1.4).
    # 2026-05-20 UI sweep: the T_out unit labels are captured so the K/°C
    # toggle (`_sync_temp_unit_labels` in main.py) can rewrite the `[K]`
    # suffix when the user flips the header unit button.
    _res_ab_row(window, rg, 1, "<i>T</i><sub>out</sub> [K]",
                '_r_ToutA', '_r_ToutB',
                unit_lbl_attrs=('_lbl_ToutA_unit', '_lbl_ToutB_unit'))
    _res_ab_row(window, rg, 2, "Δ<i>P</i><sub>total</sub> [Pa]",
                '_r_dP_A', '_r_dP_B')
    window._r_Q     = res_row(window, rg, 3, "<i>Q</i><sub>total</sub> [W/m]", 0)
    window._lbl_Q_unit = rg.itemAtPosition(3, 0).widget()
    window._r_Q.setToolTip(
        '换热量来自本次运行的工程指标。二维按单位深度展示（W/m），三维展示总量（W）。')
    lay.addWidget(res_frame, 0)
    window._ia_sections['results'] = res_frame

    lay.addStretch()
    scroll.setWidget(w)
    return scroll
