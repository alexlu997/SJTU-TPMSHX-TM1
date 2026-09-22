"""Build geometry, TPMS, material, grid and compute-resource input sections.

The dimensionality toggle controls the shared registry of 3D-only widgets.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QPushButton, QComboBox,
    QFrame, QCheckBox,
)

from .theme import get_theme
from .builders_base import (section, row, res_row, add_row, right_align_combo)




def _on_dim_changed(window):
    """Toggle visibility of 3D-only inputs based on Dimensionality combo.

    Iterates the ``window._3d_only_widgets`` registry — populated by
    ``build_domain_sections`` (Lz/Nz rows + 3D checkboxes) and
    ``builders_fluids.build_fluid_sections`` (z-partial BC rows) as the
    widgets are created. New 3D-only widgets just register themselves;
    no hardcoded attribute list to keep in sync.
    """
    is_3d = window.combo_dim.currentIndex() == 1
    window.lbl_domain_shape.setText("长方体" if is_3d else "矩形")
    for w in getattr(window, '_3d_only_widgets', []):
        w.setVisible(is_3d)
    # Mode change also reveals/hides the result tabs for the current mode
    if hasattr(window, '_update_tab_visibility'):
        window._update_tab_visibility()


def build_domain_sections(window, lay):
    """Build and register sections in the existing parameter container."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _T_NEUTRAL = t.style('T_NEUTRAL')
    _F_NEUTRAL = t.style('F_NEUTRAL')
    _COMBO = t.style('COMBO')
    _LBL = t.style('LBL')
    _VAL = t.style('VAL')


    # 3D-only widget registry — reset here because the domain page builds
    # first on every (re)build; builders_fluids appends its z-partial rows.
    window._3d_only_widgets = []
    # build_param_tabs groups these parent-owned sections by workflow.
    window._ia_sections = {}

    # Domain Geometry
    g, _sec_dg = section(window, lay, "  域几何", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['domain_geometry'] = _sec_dg
    window.le_L        = row(window, g, 0, "长度 <i>L</i> [m]", "0.182")
    window.le_H        = row(window, g, 1, "横向尺寸 <i>H</i> [m]", "0.042")
    window.le_Lz       = row(window, g, 2, "厚度 <i>L<sub>z</sub></i> [m]", "0.042")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Lz, window._lbl_Lz]

    window.lbl_domain_shape = QLabel("矩形")
    window.lbl_domain_shape.setStyleSheet(_LBL)
    window.lbl_domain_shape.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    add_row(window, g, 3, "计算域形状", window.lbl_domain_shape)

    # Dimensionality (2D / 3D) — dispatch in run_calculation
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
    # Computed outputs use the same always-visible card as the geometry inputs.
    gC, _sec_tc = section(
        window, lay, "  几何计算值", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['tpms_computed'] = _sec_tc
    window._v_eps  = res_row(window, gC, 0, "<i>&epsilon;</i>")
    window._v_A0   = res_row(window, gC, 1, "<i>A</i><sub>0</sub> [m<sup>-1</sup>]")
    window._v_Dh   = res_row(window, gC, 2, "<i>D<sub>h</sub></i> [mm]")
    window._v_Kss  = res_row(window, gC, 3, "<i>K</i><sub>ss</sub> [W/(m·K)]")
    # Material density is used for mass; fluid cp comes from the property model.
    # Steady LTNE has no solid heat-storage term.
    g2, _sec_mat = section(window, lay, "  材料属性", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['material'] = _sec_mat
    window.le_rho_s = row(window, g2, 0, "<i>&rho;</i><sub>s</sub> [kg/m³]", "7900")
    # Optimization uses rho_s for solid mass; steady LTNE has no solid storage term.
    window.le_rho_s.setToolTip(
        "固体密度：用于优化设计的质量计算，并随工况保存。"
        "当前稳态 LTNE 固体能量方程没有储热项，不直接使用该密度。")
    # ── Grid Settings (rect mode) ──
    g4, sec_solver_rect = section(window, lay, "  网格设置", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['grid_rect'] = sec_solver_rect
    window.le_Nx = row(window, g4, 0, "网格 <i>N<sub>x</sub></i>", "30")
    window.le_Ny = row(window, g4, 1, "网格 <i>N<sub>y</sub></i>", "20")
    window.le_Nz = row(window, g4, 2, "网格 <i>N<sub>z</sub></i>（三维）", "5")
    window._lbl_Nz = g4.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Nz, window._lbl_Nz]

    window.combo_grid = QComboBox()
    window.combo_grid.addItem("常规网格", False)
    window.combo_grid.addItem("端口与壁面加密", True)
    window.combo_grid.setStyleSheet(_COMBO)
    window.combo_grid.setToolTip(
        "端口与壁面加密在开口边缘和壁面集中布置网格，Nx/Ny/Nz 包含全部加密单元。\n"
        "上海水—空气预设使用端口加密；修改几何后需重新检查网格精度。")
    add_row(window, g4, 3, "网格方案", right_align_combo(window.combo_grid))

    g_policy, sec_policy = section(window, lay, "关联式适用范围", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['correlation_policy'] = sec_policy

    # Keep the applicability gate visible alongside the solver settings.
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
    g_policy.addWidget(window.chk_allow_extrap, 0, 0, 1, 2)

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
