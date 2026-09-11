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
    window.le_L        = row(window, g, 0, "Length <i>L</i> [m]",                     "0.182")
    window.le_H        = row(window, g, 1, "Width <i>H</i> [m]",                      "0.042")
    window.le_Lz       = row(window, g, 2, "Depth <i>L<sub>z</sub></i> [m] (3D only)", "0.042")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Lz, window._lbl_Lz]

    # Update edge labels when L or H changes
    window.le_L.editingFinished.connect(window._update_edge_combos)
    window.le_H.editingFinished.connect(window._update_edge_combos)

    # Domain shape selector
    window.combo_shape = QComboBox()
    window.combo_shape.addItems(["Rectangle", "Hexagon", "Octagon"])
    window.combo_shape.setStyleSheet(_COMBO)
    window.combo_shape.currentIndexChanged.connect(window._on_shape_changed)
    add_row(window, g, 3, "Domain shape", right_align_combo(window.combo_shape))

    # Dimensionality (2D / 3D MVP) — dispatch in run_calculation
    window.combo_dim = QComboBox()
    window.combo_dim.addItems(["2D", "3D"])
    window.combo_dim.setStyleSheet(_COMBO)
    window.combo_dim.currentIndexChanged.connect(
        lambda *_: _on_dim_changed(window))
    add_row(window, g, 4, "Dimensionality", right_align_combo(window.combo_dim))

    # ── TPMS Structure ──
    g0, _sec_tp = section(window, lay, "  TPMS 结构", _T_NEUTRAL, _F_NEUTRAL)
    window._ia_sections['tpms_structure'] = _sec_tp
    window.combo_tpms = QComboBox()
    window.combo_tpms.addItems(["Diamond", "Gyroid"])
    window.combo_tpms.setCurrentIndex(1)  # default Gyroid
    window.combo_tpms.setStyleSheet(_COMBO)
    add_row(window, g0, 0, "Type", right_align_combo(window.combo_tpms))
    window.le_Lcell = row(window, g0, 1, "<i>L</i><sub>cell</sub> [mm]", "7.0")
    # t=0.6 mm is the Shanghai specimen and a supported fixed-CFD node.
    window.le_t     = row(window, g0, 2, "<i>t</i> [mm]", "0.6")
    window.le_ks    = row(window, g0, 3, "<i>k</i><sub>s</sub> [W/(m·K)]", "16.0")
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
    window.le_Nx = row(window, g4, 0, "Grid <i>N<sub>x</sub></i>", "30")
    window.le_Ny = row(window, g4, 1, "Grid <i>N<sub>y</sub></i>", "20")
    window.le_Nz = row(window, g4, 2, "Grid <i>N<sub>z</sub></i> (3D only)", "5")
    window._lbl_Nz = g4.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Nz, window._lbl_Nz]

    # ── Advanced (collapsed by default) ──────────────────────────────
    # Rarely-touched switches relocated out of the TPMS / Grid sections so
    # the core inputs (L/H · TPMS · Nx/Ny/Nz · ρ_s) read clean. Click the
    # header to expand. The 3D-only members register below exactly as before;
    # the collapse composes with `_on_dim_changed` (see collapsible_section).
    g_adv, _sec_adv = collapsible_section(
        window, lay, "高级", _T_NEUTRAL, _F_NEUTRAL, expanded=False,
        on_toggle=lambda _open: _on_dim_changed(window))
    window._ia_sections['advanced_flags'] = _sec_adv

    # One shared style for every Advanced checkbox so the rows read as a
    # uniform set (boxed card · 10pt bold · 16px indicator). Previously
    # `chk_allow_extrap` carried a smaller bespoke style and looked out of
    # place next to the boxed 3D toggles.
    _tc = get_theme()
    _chk_box_qss = f"""
        QCheckBox {{
            color: {_tc['fg']};
            font-size: 10pt;
            font-weight: bold;
            background: {_tc['chk_bg']};
            border: 1px solid {_tc['chk_border']};
            border-radius: 6px;
            padding: 6px 10px;
            spacing: 8px;
        }}
        QCheckBox:hover {{ border-color: {_tc['chk_hover_border']}; background: {_tc['chk_hover_bg']}; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1.5px solid {_tc['chk_indicator_border']};
            border-radius: 3px;
            background: {_tc['chk_bg']};
        }}
        QCheckBox::indicator:hover {{ border-color: {_tc['chk_hover_border']}; }}
        QCheckBox::indicator:checked {{
            background: {_tc['chk_checked_bg']};
            border-color: {_tc['chk_checked_border']};
            image: none;
        }}
        QCheckBox:focus {{
            outline: 0;
            border: 2px solid {_tc['inp_focus']};
        }}
    """

    # Geometry cannot extrapolate beyond the fixed CFD grid. This switch only
    # downgrades a fluid-specific Nu Reynolds-window violation to a warning.
    window.chk_allow_extrap = QCheckBox("Allow Nu correlation extrapolation")
    window.chk_allow_extrap.setChecked(True)
    window.chk_allow_extrap.setToolTip(
        "D-F 几何范围: 4 ≤ L ≤ 8 mm, 0.3 ≤ t ≤ 0.6 mm；"
        "节点之间双线性插值。\n"
        "未勾选: 超出当前工质 Nu 的 Re 拟合窗口时拒绝运行。\n"
        "勾选: 超出 Re 窗口时继续运行，并在结果中告警。"
    )
    window.chk_allow_extrap.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_allow_extrap, 0, 0, 1, 2)

    # 3D wall-refine checkbox — adds 8 BL cells near each wall (all 6 faces).
    # OFF by default (5-15× faster, ~1pp accuracy cost). Turn ON for production
    # validation runs where dP near-wall BL matters more than UX speed.
    window.chk_wall_refine_3d = QCheckBox("6-wall BL refine (3D)")
    window.chk_wall_refine_3d.setChecked(False)
    window.chk_wall_refine_3d.setToolTip(
        "Enable six-wall boundary-layer refinement for 3D solves. "
        "Adds 8 cells per wall (first_cell=0.02 mm, growth 1.8). "
        "ON: 5-15× slower, ~+1pp dP accuracy. OFF: production-fast (default).")
    window.chk_wall_refine_3d.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_wall_refine_3d, 1, 0, 1, 2)
    window._3d_only_widgets.append(window.chk_wall_refine_3d)
    # NOTE: legacy `_chk_wall_refine_3d` alias removed 2026-05-05 audit;
    # no remaining readers (grep confirmed). Use `chk_wall_refine_3d`.

    # 3D variable-rho_cp checkbox — LTNE energy kernel builds gas density from
    # SIMPLE's LOCAL cell pressure ρ(P_local,T) instead of inlet ρ(T,P_in).
    # Conserves COMPRESSIBLE reverse-dir flow (Q_A≈Q_B); strict certificate
    # machine-zero; Shanghai bit-identical. ON by default (2026-06-09) — uncheck
    # for the legacy inlet-pressure density.
    window.chk_var_rhocp = QCheckBox("Local-P gas density (3D)")
    window.chk_var_rhocp.setChecked(True)
    window.chk_var_rhocp.setToolTip(
        "3D LTNE energy kernel: gas density ρ=P/RT from the LOCAL cell pressure "
        "(SIMPLE) instead of the inlet pressure. Conserves energy for "
        "compressible reverse-dir flow (Q_A≈Q_B). Strict conservation stays "
        "machine-zero; 算例工况 bit-identical; low-ΔP cases unchanged. "
        "ON = default; uncheck for the legacy inlet-pressure density.")
    window.chk_var_rhocp.setStyleSheet(_chk_box_qss)
    g_adv.addWidget(window.chk_var_rhocp, 2, 0, 1, 2)
    window._3d_only_widgets.append(window.chk_var_rhocp)

    # CPU cores for the parallel (red-black) energy GS kernel. Default = all
    # cores (Numba pool); lower it to leave cores for other work. Funnels
    # through solvers.threads.set_solver_threads (clamped to the pool size); the
    # count is global to every parallel @njit kernel. Headless/batch runs use
    # the TPMSHX_NUM_THREADS env var instead. GS is memory-bandwidth bound, so
    # gains taper past ~8-16 cores.
    from PySide6.QtWidgets import QSpinBox, QHBoxLayout
    from sjtu_tpmshx.solvers.threads import (max_threads as _max_threads,
                                 get_solver_threads as _get_threads,
                                 set_solver_threads as _set_threads)
    _mx_cores = _max_threads()
    # Wrap label + spinbox in a bordered card so this row matches the checkbox
    # boxes above (identical outer frame). The spinbox stays fully editable —
    # type a value, or use the −/+ buttons added below.
    _cpu_card = QFrame()
    _cpu_card.setStyleSheet(
        f"QFrame {{ background:{_tc['chk_bg']}; border:1px solid {_tc['chk_border']};"
        f" border-radius:6px; }}"
        f"QFrame:hover {{ border-color:{_tc['chk_hover_border']};"
        f" background:{_tc['chk_hover_bg']}; }}")
    _cpu_h = QHBoxLayout(_cpu_card)
    _cpu_h.setContentsMargins(10, 6, 10, 6)
    _cpu_h.setSpacing(8)
    _lbl_cores = QLabel("CPU cores (energy ‖)")
    _lbl_cores.setStyleSheet(
        f"QLabel {{ color:{_tc['fg']}; font-size:10pt; font-weight:bold;"
        f" background:transparent; border:none; padding:0; }}")
    window.spin_cpu_cores = QSpinBox()
    window.spin_cpu_cores.setRange(1, _mx_cores)
    window.spin_cpu_cores.setValue(_get_threads())
    window.spin_cpu_cores.setToolTip(
        f"CPU cores for the parallel energy kernel (red-black GS), 1–{_mx_cores}. "
        "Default = all cores; lower it to leave cores for other work. The count "
        "is global to every parallel kernel. GS is memory-bandwidth bound, so "
        "gains taper past ~8–16 cores. Headless / batch runs can set the "
        "env var TPMSHX_NUM_THREADS instead.")
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
    for _b, _fn, _tip in ((_btn_dn, window.spin_cpu_cores.stepDown, "Fewer cores"),
                          (_btn_up, window.spin_cpu_cores.stepUp,   "More cores")):
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
    g_adv.addWidget(_cpu_card, 3, 0, 1, 2)
    # Register the CARD (one widget) for 3D-only visibility — hiding it hides
    # the label + spinbox together; no separate child entries needed.
    window._3d_only_widgets.append(_cpu_card)

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
