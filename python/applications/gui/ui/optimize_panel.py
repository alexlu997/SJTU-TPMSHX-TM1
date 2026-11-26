"""Optimization setup, study results, and continuous-field previews."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from sjtu_tpmshx.applications.gui.controllers.user_storage import optimization_output_dir
from sjtu_tpmshx.applications.optimization import optimization_job as study
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.model_configs.df_domain import TRAIN_L, TRAIN_T
from sjtu_tpmshx.run_control.logutil import get_logger

from .builders_base import collapsible_section
from .matplotlib_canvas import MatplotlibCanvas
from .optimize_job import OptimizationJob
from .responsive import ResponsiveRow
from .sparkline import Sparkline
from .theme import FONT_INPUT, FONT_LABEL, FONT_SECTION, RADIUS_CARD, get_theme, resolve_cmap
from .window_config import config_from_window

_log = get_logger(__name__)


class OptimizationPage(QWidget):
    """Own the study controls, the active job, and the selected result."""

    activity_changed = Signal()
    figures_changed = Signal()
    fit_requested = Signal()

    def __init__(self, form):
        super().__init__(form)
        self._form = form
        self.conditions = None
        self.mass_requirements = None
        self.report = None
        self.last_output_dir = None
        self.selected_index = None
        self._plot_indices = []
        self._front_line = None
        self._pick_id = None
        self.volume_panel = None
        self.volume_data = None
        self._volume_ready = False
        self._volume_loading = False
        self._volume_ranges = {}
        self._job = None
        self._launching = False
        self._stop_requested = self._pause_requested = False
        self._live_update = None
        self._last_drawn = -1
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._draw_live)
        self._build(form)
        self.stack.currentChanged.connect(self._fit_page)
        self.refresh_setup()

    def _build(self, form):
        t = form.theme
        _t = t.palette()
        _surface_ra = _t['surface_raised']
        _border_sub = _t['border_subtle']
        _sub_fg = _t['sub_fg']
        _mono = _t['mono_family']

        self.setStyleSheet("QWidget { background:transparent; }")
        op_v = QVBoxLayout(self)
        op_v.setContentsMargins(0, 0, 0, 0); op_v.setSpacing(12)

        _pill_base = (
            "QPushButton{{padding:5px 14px; border-radius:12px;"
            "font-size:10pt; font-weight:600;"
            "font-family:" + _t['sans_family'] + ";"
            "background:{bg}; color:{fg}; border:1px solid {bd};}}"
            "QPushButton:focus{{border:2px solid " + _t['inp_focus']
            + "; padding:4px 13px;}}")
        _pill_idle = _pill_base.format(
            bg=_surface_ra, fg=_sub_fg, bd=_border_sub)
        _pill_active = _pill_base.format(
            bg=_t['accent_primary'],
            fg=_t['tab_on_fg'],
            bd=_t['accent_primary'])
        _pill_done = _pill_base.format(
            bg=_t['accent_green'],
            fg=_t['tab_on_fg'],
            bd=_t['accent_green'])
        self._pill_styles = (_pill_idle, _pill_active, _pill_done)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(6); stage_row.setContentsMargins(0, 0, 0, 0)
        self.stage_pills = {}
        stage_items = [('config', '1  配置'),
                       ('running', '2  运行'),
                       ('result', '3  结果')]
        for i, (skey, slabel) in enumerate(stage_items):
            pill = QPushButton(slabel)
            pill.setStyleSheet(_pill_idle)
            pill.setAccessibleName(slabel)
            pill.clicked.connect(lambda _checked=False, idx=i: self.stack.setCurrentIndex(idx))
            stage_row.addWidget(pill)
            self.stage_pills[skey] = pill
            if i < len(stage_items) - 1:
                arr = QLabel("─")
                arr.setStyleSheet(
                    f"color:{_border_sub}; font-size:12pt;"
                    "background:transparent; border:none; padding:0 2px;")
                stage_row.addWidget(arr)
        status = QLabel("空闲 — 配置参数后点击启动")
        status.setMinimumHeight(24)
        status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status.setWordWrap(True)
        status.setStyleSheet(
            f"color:{_sub_fg}; font-family:{_mono};"
            f"font-size:9pt; font-weight:400;"
            f"background:transparent; border:none; padding:2px 8px;")
        status.setAlignment(Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter)
        self.status = status
        stage_row.addWidget(status, 1)
        op_v.addLayout(stage_row)
        self.stage_pills['config'].setStyleSheet(_pill_active)

        _stack = QStackedWidget()
        _stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.stack = _stack
        op_v.addWidget(_stack, 1)

        p1 = QWidget()
        p1v = QVBoxLayout(p1)
        p1v.setContentsMargins(0, 0, 0, 0); p1v.setSpacing(12)
        p1row = ResponsiveRow(threshold=720, spacing=16)
        p1row.layout().setAlignment(Qt.AlignmentFlag.AlignTop)

        def _opt_card(title, min_w=0):
            fr = QFrame()
            fr.setObjectName('optimizationCard')
            fr.setStyleSheet(
                f"QFrame#optimizationCard{{background:{_surface_ra};"
                f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
            if min_w:
                fr.setMinimumWidth(min_w)
            fl = QVBoxLayout(fr)
            fl.setContentsMargins(12, 12, 12, 12); fl.setSpacing(8)
            cap = QLabel(title)
            cap.setStyleSheet(
                f"color:{_t['fg']}; font-size:{FONT_SECTION}pt; font-weight:600;"
                "background:transparent;"
                "border:none;")
            fl.addWidget(cap)
            return fr, fl

        common_row = ResponsiveRow(threshold=640, spacing=12)
        self.public_summary = QLabel()
        self.public_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.public_summary.setWordWrap(True)
        self.public_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        common_row.addWidget(self.public_summary)
        self.edit_common_button = QPushButton('编辑公共工况')
        self.edit_common_button.setStyleSheet(t.style('BTN_SECONDARY'))
        self.edit_common_button.setMinimumHeight(30)
        self.edit_common_button.clicked.connect(self.edit_common_settings)
        common_row.addWidget(self.edit_common_button)
        common_row.layout().setStretch(0, 1)
        p1v.addWidget(common_row)
        par_card, par_lay = _opt_card("优化参数", 260)
        _spin_qss = (
            f"QAbstractSpinBox{{background:{_t['inp_bg']};"
            f" color:{_t['inp_fg']}; border:1px solid {_t['inp_border']};"
            f" border-radius:6px; padding:3px 8px;"
            f" font-family:{_mono}; font-size:{FONT_INPUT}pt;}}"
            f"QAbstractSpinBox:focus{{border-color:{_t['inp_focus']};}}")
        self.method = QComboBox()
        for label, key in (("qLogNEHVI", "qlognehvi"), ("qLogNParEGO", "qlognparego"),
                           ("qLogNEI · 芯体减重", "qlognei"), ("Sobol", "sobol")):
            self.method.addItem(label, key)
        self.method.setStyleSheet(t.style('COMBO'))
        self.method.currentIndexChanged.connect(self.refresh_setup)
        par_lay.addWidget(self.method)
        self.parameters = {}
        for key, label, low, high, default in (
                ('n_init', '初始候选数', 1, 256, 16), ('n_iter', '迭代数', 0, 200, 8),
                ('q_batch', '每轮候选数', 1, 8, 1), ('seed', '随机种子', 0, 9999, 0)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label)); row.addStretch(1)
            spin = QSpinBox(); spin.setRange(low, high); spin.setValue(default)
            spin.setStyleSheet(_spin_qss)
            spin.setFixedWidth(80)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setMinimumHeight(30)
            row.addWidget(spin); par_lay.addLayout(row)
            self.parameters[key] = spin
            spin.valueChanged.connect(self.refresh_setup)
        self.eval_preview = QLabel()
        self.eval_preview.setWordWrap(True)
        par_lay.addWidget(self.eval_preview)
        condition_row = QHBoxLayout()
        import_button = QPushButton('导入工况 / 减重要求 JSON')
        import_button.clicked.connect(self.import_conditions)
        current_button = QPushButton('使用当前单工况')
        current_button.clicked.connect(self.use_current_condition)
        for button in (import_button, current_button):
            button.setStyleSheet(t.style('BTN_SECONDARY'))
            button.setMinimumHeight(30)
        condition_row.addWidget(import_button); condition_row.addWidget(current_button)
        par_lay.addLayout(condition_row)
        self.condition_summary = QLabel()
        self.condition_summary.setWordWrap(True)
        self.condition_summary.setToolTip(
            'JSON: {"conditions": [{"condition_id": "1", "T_in_A_K": 400, '
            '"P_in_A_Pa": 120000, "mass_flow_A_kg_s": 0.005, '
            '"T_in_B_K": 300, "P_in_B_Pa": 110000, "mass_flow_B_kg_s": 0.02}]}\n'
            '减重时增加 mass_requirements：solid_density_kg_m3 与 conditions；'
            '按 condition_id 给出 Q_min_W、dP_A_max_Pa、dP_B_max_Pa。')
        par_lay.addWidget(self.condition_summary)
        self.depth_label = QLabel('2D 总质量流量换算厚度 [m]')
        self.depth = QLineEdit(form.le_Lz.text())
        self.depth.setStyleSheet(t.style('INP'))
        self.depth.setFixedWidth(80)
        self.depth.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.depth.setMinimumHeight(30)
        self.depth.setToolTip('物理厚度用于 kg/s 与二维单位深度流量换算；不改变二维网格。')
        depth_row = QHBoxLayout()
        depth_row.addWidget(self.depth_label)
        depth_row.addStretch(1)
        depth_row.addWidget(self.depth)
        par_lay.addLayout(depth_row)
        scope = QLabel('支持空气 A / 水 B，以及含 CO₂ 或 sCO₂ 的双流体组合。'
                       '换热目标为 B 侧吸热，基准 B 侧必须吸热。')
        scope.setWordWrap(True); par_lay.addWidget(scope)
        form.combo_dim.currentIndexChanged.connect(self.refresh_setup)
        par_lay.addStretch(1)
        p1row.addWidget(par_card)

        space_card, space_lay = _opt_card("搜索空间 (连续场)", 250)
        self.bounds = {}

        def _space_row(label, tip, widgets):
            srow = QHBoxLayout(); srow.setSpacing(8)
            sl = QLabel(label)
            sl.setToolTip(tip)
            sl.setStyleSheet(f"color:{_t['fg']}; font-size:{FONT_LABEL}pt;"
                             " background:transparent; border:none;")
            srow.addWidget(sl); srow.addStretch(1)
            for wdg in widgets:
                srow.addWidget(wdg)
            space_lay.addLayout(srow)

        def _mk_dspin(lo, hi, val, step, dec):
            ds = QDoubleSpinBox()
            ds.setRange(lo, hi); ds.setValue(val)
            ds.setSingleStep(step); ds.setDecimals(dec)
            ds.setStyleSheet(_spin_qss)
            ds.setAlignment(Qt.AlignmentFlag.AlignRight)
            ds.setFixedWidth(max(80, ds.sizeHint().width()))
            ds.setMinimumHeight(30)
            return ds

        _sp_Lmin = _mk_dspin(TRAIN_L[0], TRAIN_L[1], TRAIN_L[0], 0.5, 2)
        _sp_Lmax = _mk_dspin(TRAIN_L[0], TRAIN_L[1], TRAIN_L[1], 0.5, 2)
        _space_row("胞元 <i>L</i> 范围 [mm]",
                   f"决策变量 L 的上下界；当前 CFD 几何范围 {TRAIN_L} mm；"
                   "上下界相同则固定胞元尺寸；Nu 适用范围单独检查",
                   [_sp_Lmin, _sp_Lmax])
        self.bounds['L_min'] = _sp_Lmin
        self.bounds['L_max'] = _sp_Lmax

        _sp_tmin = _mk_dspin(TRAIN_T[0], TRAIN_T[1], TRAIN_T[0], 0.05, 2)
        _sp_tmax = _mk_dspin(TRAIN_T[0], TRAIN_T[1], TRAIN_T[1], 0.05, 2)
        _space_row("壁厚 <i>t</i> 范围 [mm]",
                   f"决策变量 t 的上下界；当前 CFD 几何范围 {TRAIN_T} mm（自动夹持）",
                   [_sp_tmin, _sp_tmax])
        self.bounds['t_min'] = _sp_tmin
        self.bounds['t_max'] = _sp_tmax
        for edit in self.bounds.values():
            edit.valueChanged.connect(self.refresh_setup)

        self.controls = {}
        for axis in 'xyz':
            row = QHBoxLayout()
            label = QLabel(f'{axis.upper()} 控制点')
            edit = QSpinBox()
            edit.setRange(1, 99)
            edit.setValue(3)
            edit.setStyleSheet(_spin_qss)
            edit.setFixedWidth(80)
            edit.setMinimumHeight(30)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            edit.setToolTip('1 点为该轴恒定；2 点线性；更多点使用当前样条阶数。')
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(edit)
            space_lay.addLayout(row)
            self.controls[axis] = edit
            if axis == 'z':
                self.control_z_label = label
            edit.valueChanged.connect(self.refresh_setup)
        self.field_layout = QLabel()
        self.field_layout.setWordWrap(True)
        space_lay.addWidget(self.field_layout)
        self.selected_field = QLabel()
        self.selected_field.setWordWrap(True)
        space_lay.addWidget(self.selected_field)
        clear_field = QPushButton('恢复均匀设计')
        clear_field.setStyleSheet(t.style('BTN_SECONDARY'))
        clear_field.setMinimumHeight(30)
        clear_field.clicked.connect(self.clear_continuous_field)
        space_lay.addWidget(clear_field)

        form.chk_zones.toggled.connect(self._zone_changed)

        btn_field_prev = QPushButton("预览连续场")
        btn_field_prev.setFixedHeight(26)
        btn_field_prev.setStyleSheet(t.style('BTN_SECONDARY'))
        btn_field_prev.setToolTip(
            "预览二维连续场；三维可查看中面切片与交互体视图"
            "（未选 Pareto 解时显示界中值均匀场）")

        btn_field_prev.clicked.connect(lambda: self.show_field_preview())
        space_lay.addWidget(btn_field_prev)
        space_lay.addStretch(1)
        p1row.addWidget(space_card)
        p1v.addWidget(p1row)

        zone_grid, zone_card = collapsible_section(
            p1v, "单点计算分区（不参与优化搜索）",
            t.style('T_NEUTRAL'), t.style('F_NEUTRAL'), expanded=False)
        zone_grid.addWidget(form._zone_panel, 0, 0, 1, 2)
        form.chk_zones.toggled.connect(zone_card._set_expanded)
        p1v.addStretch(1)
        _stack.addWidget(p1)

        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.setContentsMargins(0, 0, 0, 0); p2v.setSpacing(16)
        _stack.addWidget(p2)

        p3 = QWidget()
        p3v = QVBoxLayout(p3)
        p3v.setContentsMargins(0, 0, 0, 0); p3v.setSpacing(8)
        _stack.addWidget(p3)

        _hero_font = _t['mono_family']
        def _mk_kpi(caption, initial="—", min_w=150):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame{{background:{_surface_ra};"
                f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
            card.setFixedHeight(78)
            card.setMinimumWidth(min_w)
            cl = QVBoxLayout(card)
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
            return card, val, cap

        kpi_row = QGridLayout()
        kpi_row.setSpacing(16)
        card_gen, val_gen, _ = _mk_kpi("已评估候选 / 预算", "—", 130)
        card_q, val_q, self.kpi_q_caption = _mk_kpi("最大换热提升 [%]", "—", 180)
        card_dp, val_dp, self.kpi_dp_caption = _mk_kpi("最小相对压降 [1]", "—", 180)
        card_eta, val_eta, _ = _mk_kpi("剩余时间", "—", 120)
        self.kpi_gen = val_gen
        self.kpi_q = val_q
        self.kpi_dp = val_dp
        self.kpi_eta = val_eta
        kpi_row.addWidget(card_gen, 0, 0)
        kpi_row.addWidget(card_q, 0, 1)
        kpi_row.addWidget(card_dp, 1, 0)
        kpi_row.addWidget(card_eta, 1, 1)

        spark_card = QFrame()
        spark_card.setStyleSheet(
            f"QFrame{{background:{_surface_ra};"
            f"border:1px solid {_border_sub}; border-radius:{RADIUS_CARD}px;}}")
        spark_card.setFixedHeight(72)
        spark_card.setMinimumWidth(220)
        scl = QVBoxLayout(spark_card)
        scl.setContentsMargins(14, 8, 14, 8); scl.setSpacing(2)
        spark_cap = QLabel("总预算进度 [%]（含均匀基准）")
        spark_cap.setStyleSheet(
            f"color:{_sub_fg}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            f"font-family:{_t['sans_family']};")
        spark = Sparkline(height=40)
        self.sparkline = spark
        scl.addWidget(spark_cap)
        scl.addWidget(spark, 1)
        kpi_row.addWidget(spark_card, 2, 0, 1, 2)
        p2v.addLayout(kpi_row)
        self.live_details = QLabel()
        self.live_details.setTextFormat(Qt.TextFormat.PlainText)
        self.live_details.setWordWrap(True)
        self.live_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.live_details.setStyleSheet(
            f"color:{_t['fg']}; font-size:10pt; background:transparent;")
        p2v.addWidget(self.live_details)

        btn_opt = QPushButton("▶  启动 Pareto 搜索")
        btn_opt.setFixedHeight(36)
        btn_opt.setStyleSheet(t.style('BTN_LONG'))
        btn_opt.setToolTip(
            "启动多工况连续场搜索。"
            "进度与收敛在「2 运行」页实时显示。")
        btn_opt.clicked.connect(self.start)
        self.start_button = btn_opt
        par_lay.insertWidget(par_lay.count() - 1, btn_opt)
        self.resume_button = QPushButton("继续已有任务…")
        self.resume_button.setStyleSheet(t.style('BTN_TERTIARY'))
        self.resume_button.setToolTip("读取 optimization.json，在新目录继续；使用保存的工况和搜索设置。")
        self.resume_button.clicked.connect(self.resume)
        par_lay.insertWidget(par_lay.count() - 1, self.resume_button)

        btn_opt_cancel = QPushButton("✕ 取消（保留已算样本）")
        btn_opt_cancel.setFixedHeight(32)
        btn_opt_cancel.setMinimumWidth(90)
        btn_opt_cancel.setStyleSheet(t.style('BTN_TERTIARY'))
        btn_opt_cancel.setToolTip("请求优雅取消当前搜索")
        btn_opt_cancel.setEnabled(False)
        btn_opt_cancel.clicked.connect(self.cancel)
        self.cancel_button = btn_opt_cancel
        cancel_row = QHBoxLayout()
        self.pause_button = QPushButton("暂停并保存")
        self.pause_button.setFixedHeight(32)
        self.pause_button.setStyleSheet(t.style('BTN_TERTIARY'))
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.pause)
        cancel_row.addWidget(self.pause_button)
        cancel_row.addWidget(btn_opt_cancel)
        cancel_row.addStretch(1)
        p2v.addLayout(cancel_row)
        p2v.addStretch(1)

        op_pb = QProgressBar()
        op_pb.setFixedHeight(8)
        op_pb.setTextVisible(False)
        op_pb.setRange(0, 100); op_pb.setValue(0)
        op_pb.setStyleSheet(
            f"QProgressBar{{background:{_surface_ra};"
            f"border:1px solid {_border_sub}; border-radius:4px;}}"
            f"QProgressBar::chunk{{background:qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {_t['accent_primary']},"
            f"stop:1 {_t['accent_green']});"
            f"border-radius:4px;}}")
        op_pb.hide()
        self.progress_bar = op_pb
        p2v.insertWidget(1, op_pb)

        banner = QLabel("")
        banner.setStyleSheet(
            f"QLabel{{color:{_t['tab_on_fg']};"
            f"background:{_t['accent_green']};"
            f"border:none; border-radius:6px;"
            f"padding:10px 16px;"
            f"font-family:{_mono}; font-size:10pt; font-weight:700;"
            "letter-spacing:0.3px;}")
        banner.setWordWrap(True)
        banner.hide()
        self.summary_banner = banner
        p3v.addWidget(banner)

        export_row = ResponsiveRow(threshold=560, spacing=8)
        self.export_pareto_button = QPushButton('导出 Pareto 数据')
        self.export_pareto_button.setToolTip('导出数值合格方案：CSV / XLSX')
        self.export_pareto_button.setStyleSheet(t.style('BTN_SECONDARY'))
        self.export_pareto_button.setMinimumHeight(30)
        self.export_pareto_button.setEnabled(False)
        self.export_pareto_button.clicked.connect(self.export_pareto_data)
        export_row.addWidget(self.export_pareto_button)
        self.load_button = QPushButton('载入所选方案')
        self.load_button.setStyleSheet(t.style('BTN_SECONDARY'))
        self.load_button.setMinimumHeight(30)
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_selected)
        export_row.addWidget(self.load_button)
        self.export_geometry_button = QPushButton('导出所选方案建模坐标')
        self.export_geometry_button.setToolTip('导出所选连续设计场的建模坐标：CSV')
        self.export_geometry_button.setStyleSheet(t.style('BTN_SECONDARY'))
        self.export_geometry_button.setMinimumHeight(30)
        self.export_geometry_button.setEnabled(False)
        self.export_geometry_button.clicked.connect(self.export_geometry)
        export_row.addWidget(self.export_geometry_button)
        p3v.addWidget(export_row)

        self.pareto_canvas = MatplotlibCanvas(1, 1, figsize=(14, 8))
        self.pareto_canvas.fig.set_layout_engine('compressed')
        self.pareto_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pareto_canvas.setStyleSheet("border-radius:6px;")
        self.field_canvas = MatplotlibCanvas(1, 1, figsize=(10.5, 6.8))
        self.field_canvas.fig.clear()
        self.field_canvas.fig.set_layout_engine('compressed')
        tabs = QTabWidget()
        # Keep the plot inside the workbench viewport as the page changes.
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        tabs.setMinimumHeight(320)
        tabs.setStyleSheet(
            f"QTabWidget::pane{{border:none; background:{_t['fig_bg']};}}"
            f"QTabBar::tab{{background:{_t['surface_raised']}; color:{_t['sub_fg']};"
            "padding:8px 16px; border:none;}"
            f"QTabBar::tab:selected{{color:{_t['fg']};"
            f"border-bottom:2px solid {_t['accent_primary']};}}")
        tabs.addTab(self.pareto_canvas, 'Pareto 前沿')
        tabs.addTab(self.field_canvas, '尺寸 / 壁厚场')
        tabs.setTabEnabled(1, False)
        tabs.setTabToolTip(1, '点击 Pareto 方案查看其连续场，或在配置页预览当前场')
        self.volume_host = QWidget()
        volume_layout = QVBoxLayout(self.volume_host)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(4)
        note = QLabel('连续设计场预览 · 可旋转、缩放和切片 · L / t 参数分布')
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{_t['sub_fg']}; padding:4px 8px;")
        volume_layout.addWidget(note)
        self.volume_placeholder = QLabel('选择三维连续场后可查看体视图')
        self.volume_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_placeholder.setWordWrap(True)
        volume_layout.addWidget(self.volume_placeholder, 1)
        tabs.addTab(self.volume_host, '三维尺寸 / 壁厚场')
        tabs.setTabEnabled(2, False)
        tabs.setTabToolTip(2, '显示三维连续场；选择 L 或 t，旋转或按物理坐标切片')
        self.result_tabs = tabs
        tabs.currentChanged.connect(self.show_field_volume)
        p3v.addWidget(tabs, 1)

    def capture_case(self):
        config = config_from_window(self._form, strict=True)
        if config.is_3d:
            return config
        depth = study.positive_number(self.depth.text(), '2D total-flow depth [m]')
        return replace(config, geometry=replace(config.geometry, Lz_m=depth))

    def field_spec(self):
        from scipy.stats import qmc
        from sjtu_tpmshx.physical_models.continuous_field import decision_bounds, decision_dim
        widgets = self.bounds
        controls = self.controls
        spec = dict(n_ctrl_x=controls['x'].value(), n_ctrl_y=controls['y'].value(),
                    symmetric_y=False, spline_order=2,
                    L_bounds=[widgets['L_min'].value(), widgets['L_max'].value()],
                    t_bounds=[widgets['t_min'].value(), widgets['t_max'].value()])
        if self._form.combo_dim.currentIndex() == 1:
            spec['n_ctrl_z'] = controls['z'].value()
        count = decision_dim(spec['n_ctrl_x'], spec['n_ctrl_y'], False, n_ctrl_z=spec.get('n_ctrl_z'))
        if count > qmc.Sobol.MAXDIM:
            raise ValueError(f'当前控制点包含 {count} 个变量；优化初始化最多支持 {qmc.Sobol.MAXDIM} 个')
        low, high = decision_bounds(spec['n_ctrl_x'], spec['n_ctrl_y'], False, spec['L_bounds'], spec['t_bounds'],
                                    n_ctrl_z=spec.get('n_ctrl_z'))
        ZoneInputConfig(enabled=True, axis='continuous',
                        config={**spec, 'x_decision': ((low+high)/2).tolist()}).validate()
        return spec

    def import_conditions(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, '导入优化工况表', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as source:
                payload = json.load(source)
                rows = study.validate_condition_table(payload)
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f'工况导入失败：{exc}')
            return
        self.conditions = rows
        self.mass_requirements = deepcopy(payload.get('mass_requirements'))
        if self.mass_requirements is not None:
            self.method.setCurrentIndex(self.method.findData('qlognei'))
        elif self.method.currentData() == 'qlognei':
            self.method.setCurrentIndex(self.method.findData('qlognehvi'))
        self.refresh_setup()
        self.status.setText(f'已导入 {len(rows)} 个工况：{Path(path).name}')

    def use_current_condition(self):
        self.conditions = None
        self.mass_requirements = None
        if self.method.currentData() == 'qlognei':
            self.method.setCurrentIndex(self.method.findData('qlognehvi'))
        self.refresh_setup()

    def capture_study(self):
        state = {}
        if self.conditions is not None:
            state['optimization_conditions'] = deepcopy(self.conditions)
        if self.mass_requirements is not None:
            state['optimization_mass_requirements'] = deepcopy(self.mass_requirements)
        state['optimization_controls'] = {axis: edit.value() for axis, edit in self.controls.items()}
        state['optimization_bounds'] = {
            name: [self.bounds[name + '_' + end].value() for end in ('min', 'max')]
            for name in ('L', 't')}
        return state

    def restore_study(self, preset, *, partial=False):
        self.conditions = deepcopy(preset.get('optimization_conditions'))
        self.mass_requirements = deepcopy(preset.get('optimization_mass_requirements'))
        if self.mass_requirements is not None:
            if not partial or self.method.currentData() not in ('qlognei', 'sobol'):
                self.method.setCurrentIndex(self.method.findData('qlognei'))
        elif self.method.currentData() == 'qlognei':
            self.method.setCurrentIndex(self.method.findData('qlognehvi'))
        controls = preset.get('optimization_controls', {})
        for axis, edit in self.controls.items():
            edit.setValue(controls.get(axis, 3))
        bounds = preset.get('optimization_bounds', {'L': TRAIN_L, 't': TRAIN_T})
        for name in ('L', 't'):
            for end, value in zip(('min', 'max'), bounds[name]):
                self.bounds[name + '_' + end].setValue(value)
        self.refresh_setup()

    def edit_common_settings(self):
        form = self._form
        if form.btn_focus_view.isChecked():
            form._toggle_3d_immersive()
        form.workbench.switch_tab('layout')
        if form._param_panel.isHidden():
            form._set_parameter_panel_collapsed(False)
        form._param_scroll.setFocus()

    def _zone_changed(self, enabled):
        if not enabled:
            self._form._continuous_field_spec = None
        self.refresh_setup()

    def clear_continuous_field(self):
        self._form._continuous_field_spec = None
        self._form.chk_zones.setChecked(False)
        self.refresh_setup()

    @Slot()
    def refresh_setup(self):
        form = self._form
        is_3d = form.combo_dim.currentIndex() == 1
        lengths = [form.le_L.text(), form.le_H.text()]
        grids = [form.le_Nx.text(), form.le_Ny.text()]
        if is_3d:
            lengths.append(form.le_Lz.text())
            grids.append(form.le_Nz.text())
        self.public_summary.setText(f'公共工况 · {form.combo_tpms.currentText()} · '
            f'{form.combo_fluidA.currentText()} / {form.combo_fluidB.currentText()}\n'
            f'计算域 {" × ".join(lengths)} m · 网格 {" × ".join(grids)} · 材料、端口与求解设置沿用当前算例')
        self.depth.setVisible(not is_3d)
        self.depth_label.setVisible(not is_3d)
        self.controls['z'].setVisible(is_3d)
        self.control_z_label.setVisible(is_3d)
        counts = [self.controls[a].value() for a in ('xyz' if is_3d else 'xy')]
        fields = sum(self.bounds[name + '_min'].value() != self.bounds[name + '_max'].value()
                     for name in ('L', 't'))
        self.field_layout.setText(' × '.join(map(str, counts)) + f' · {fields * int(np.prod(counts))} 个变量 · '
                                  + ('XYZ' if is_3d else 'XY') + ' 连续场')
        rows, requirements = self.conditions, self.mass_requirements
        n = len(rows) if rows else 1
        self.condition_summary.setText(f'{n} 个工况 · ' + ('逐项限值：' if requirements else '等权：')
            + '、'.join(row['condition_id'] for row in rows) if rows else
            '单工况 · 当前窗口输入；总流量按实际入口速度分布与孔隙率积分换算')
        params = self.parameters
        budget = params['n_init'].value() + params['n_iter'].value() * params['q_batch'].value()
        objective = (f'目标：芯体质量最小；所有工况满足换热与两侧压降要求\n'
                     f'实体密度 {requirements["solid_density_kg_m3"]:g} kg/m³\n' if requirements else
                     '目标：平均换热增益最大，相对压降最小\n')
        if requirements and requirements.get('allow_nu_re_extrapolation'):
            objective += '本任务允许 Nu-Re 外推；结果保留超范围记录\n'
        self.eval_preview.setText(objective + f'{budget} 个候选 + 1 个均匀基准，最多 {(budget+1)*n} 次 '
                                  f'{"3D" if is_3d else "2D"} 工况求解')
        spec = form._continuous_field_spec
        self.selected_field.setText('当前计算使用完整 ' + ('XYZ' if 'n_ctrl_z' in spec else 'XY') + ' 连续场'
                                    if spec else '当前计算未加载优化连续场')
        form.zone_table.setEnabled(spec is None)
        form.combo_zone_axis.setEnabled(spec is None)
        self.fit_requested.emit()

    def is_idle(self):
        return self._job is None and not self._launching

    def _set_busy(self, busy):
        self.start_button.setEnabled(not busy)
        self.resume_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.pause_button.setEnabled(busy)
        self.activity_changed.emit()

    def set_stage(self, key, state):
        styles = {'idle': 0, 'active': 1, 'done': 2}
        self.stage_pills[key].setStyleSheet(self._pill_styles[styles[state]])
        if state == 'active':
            self.stack.setCurrentIndex({'config': 0, 'running': 1, 'result': 2}[key])

    @Slot()
    def _fit_page(self):
        self.fit_requested.emit()
        QTimer.singleShot(0, self, self.fit_requested.emit)

    def _set_kpi(self, *, gen, best_q, best_dp, eta):
        self.kpi_gen.setText(str(gen))
        self.kpi_q.setText(f'{best_q:.3g}' if isinstance(best_q, (int, float)) else str(best_q))
        self.kpi_dp.setText(f'{best_dp:.4g}' if isinstance(best_dp, (int, float)) else str(best_dp))
        self.kpi_eta.setText(str(eta))

    def _capture_input(self):
        return study.OptimizationInput(
            self.capture_case(), self.conditions, self.field_spec(), self.method.currentData(),
            **{key: edit.value() for key, edit in self.parameters.items()},
            mass_requirements=self.mass_requirements).validate()

    @Slot()
    def start(self, *, resume_file=None):
        if self._form._close_pending or not self.is_idle():
            return
        self._launching = True
        self._set_busy(True)
        try:
            inputs = (self._capture_input() if resume_file is None
                      else study.OptimizationInput.from_checkpoint(resume_file))
            if self._form._close_pending:
                return
            name = f'{inputs.method}_{time.strftime("%Y%m%d_%H%M%S")}_{time.time_ns()%1000000:06d}'
            output_dir = optimization_output_dir() / name
            self._job = OptimizationJob(inputs, output_dir, self._form.run_control, self._terminal, self)
            self._job.progress.connect(self._progress)
            self._job.updated.connect(self._update)
            self._job.settled.connect(self._settled)
            self._stop_requested = self._pause_requested = False
            self._last_drawn = -1
            self._live_update = None
            self.live_details.setText('正在准备工况；首次提案完成后可估算剩余时间。')
            self.live_details.setToolTip('')
            self.sparkline.clear_data()
            self._set_kpi(gen='starting', best_q='—', best_dp='—', eta='—')
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            self.set_stage('config', 'done')
            self.set_stage('running', 'active')
            self.set_stage('result', 'idle')
            self.summary_banner.hide()
            self.status.setText(f'{inputs.method} · {len(inputs.rows) if inputs.rows else 1} 个工况 · '
                                f'{"3D" if inputs.config.is_3d else "2D"}')
            self._job.start()
        except Exception as exc:
            if self._job is not None:
                self._job.deleteLater()
                self._job = None
            self.status.setText(f'启动失败：{exc}')
            self.set_stage('running', 'idle')
            self.set_stage('config', 'active')
        else:
            self._live_timer.start()
        finally:
            self._launching = False
            if self.is_idle():
                self._set_busy(False)

    def cancel(self):
        if self._job is not None:
            self._stop_requested = True
            self._job.requestInterruption()
            self.status.setText('正在取消；等待当前数值步骤结束并保存记录')

    def pause(self):
        if self._job is not None:
            self._pause_requested = True
            self._job.request_pause()
            self.pause_button.setEnabled(False)
            self.status.setText('正在暂停；等待保存原生检查点和搜索记录')

    def resume(self):
        from PySide6.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getOpenFileName(self, '继续已有优化任务',
            str(optimization_output_dir()), 'Optimization checkpoint (optimization.json)')
        if filename:
            self.start(resume_file=filename)

    @Slot(int)
    def _progress(self, percent):
        if not self._form._close_pending:
            self.progress_bar.setValue(percent)
            self.sparkline.push(percent)

    @Slot(object)
    def _update(self, state):
        if self._form._close_pending:
            return
        report = state['report']
        self.last_output_dir = self._job.output_dir
        if self._live_update is None:
            self.show_pareto(report, running=True)
            self._last_drawn = report['n_usable']
        self._live_update = (state, time.monotonic())
        self.show_live_update(state)

    def _draw_live(self):
        if self._form._close_pending or self._live_update is None:
            return
        state, received = self._live_update
        report = state['report']
        if report['status'] != 'running':
            return
        delta = time.monotonic() - received
        eta = state['eta_s']
        self.show_live_update({**state, 'elapsed_s': state['elapsed_s'] + delta,
                               'eta_s': max(0., eta - delta) if eta is not None else None})
        if report['n_usable'] != self._last_drawn:
            self.show_pareto(report, running=True)
            self._last_drawn = report['n_usable']

    def _terminal(self, report, error):
        self._live_timer.stop()
        if self._form._close_pending:
            return
        directory = self._job.output_dir
        if error and self._live_update is not None:
            published = self._live_update[0]['report']
            if published['status'] != 'running':
                report = published
        if report is not None:
            self.last_output_dir = directory
            self.show_pareto(report)
            detail = f' · {error}' if error else ''
            self.status.setText(f'{self.summary_banner.text()}{detail} · {directory}')
        else:
            label = 'ERROR' if error else '已取消'
            text = f'ERROR: {error} · 输出目录：{directory}' if error else '已取消 · 工况准备结束，尚未启动优化搜索'
            self.status.setText(text)
            self._set_kpi(gen=label, best_q='—', best_dp='—', eta='—')
            self.set_stage('running', 'idle')
            self.set_stage('config', 'active')

    @Slot()
    def _settled(self):
        self._job = None
        self._set_busy(False)

    def _objective_kpis(self, report, rows):
        constrained = 'mass_requirements' in report
        captions = ('最小合格芯体质量 [kg]', '满足全部约束的候选数') if constrained else (
            '最大换热提升 [%]', '最小相对压降 [1]')
        if constrained and report['mass_requirements'].get('allow_nu_re_extrapolation'):
            captions = ('最小达标芯体质量 [kg]（允许 Nu-Re 外推）', captions[1])
        self.kpi_q_caption.setText(captions[0])
        self.kpi_dp_caption.setText(captions[1])
        if constrained:
            feasible = [row for row in rows if row.get('feasible') is True]
            return dict(best_q=min((row['objectives']['core_mass_kg'] for row in feasible), default='—'),
                        best_dp=report['n_feasible'])
        return dict(best_q=max((row['objectives']['heat_gain_percent'] for row in rows), default='—'),
                    best_dp=min((row['objectives']['pressure_ratio'] for row in rows), default='—'))

    def show_live_update(self, update):
        """Show recorded state without changing the active workflow page."""
        report = update['report']
        self.report = report
        stages = {'baseline': '均匀基准', 'initial': '初始候选',
                  'model_fit': '拟合模型', 'proposal': '选择候选',
                  'evaluation': '候选计算', 'finished': '搜索结束'}
        stage = stages[report['stage']]
        active = next((row for row in report['history'] if row['status'] == 'running'), None)
        if active is not None:
            stage += f' {active["index"]+1}/{report["design_budget"]}'
        if report['status'] != 'running':
            stage = _termination_label(report)
        elif self._stop_requested:
            stage = '取消请求已收到；等待安全停止点 · ' + stage
        elif self._pause_requested:
            stage = '暂停请求已收到；等待保存检查点 · ' + stage
        self.status.setText(stage)
        usable = [row for row in report['history'] if row['status'] == 'completed']
        failed = [row for row in report['history'] if row['status'] == 'failed']
        eta = update['eta_s']
        self._set_kpi(gen=f'{report["n_evaluated"]}/{report["design_budget"]}',
            **self._objective_kpis(report, usable),
            eta=f'≈{eta/60:.1f} min' if eta is not None else '采样中')
        phases = {'input': '等待准备', 'prepare': '前处理', 'save_case': '保存输入',
                  'comparison': '核对基准', 'solve': '原生求解', 'validate_result': '核对结果',
                  'postprocess': '后处理', 'save_result': '保存结果', 'qualification': '资格检查',
                  'reuse': '读取已有结果', None: '等待'}
        states = {'completed': '合格', 'failed': '失败', 'cancelled': '已取消', 'paused': '已暂停', 'not_run': '等待'}
        conditions = update['conditions']
        priority = {'running': 0, 'computed': 0, 'failed': 1, 'cancelled': 1, 'paused': 1,
                    'not_run': 2, 'completed': 3}
        visible = sorted(conditions, key=lambda row: priority[row['status']])[:4]
        lines = [f'已评估 {report["n_evaluated"]}/{report["design_budget"]} · '
                 f'数值合格 {len(usable)} · 失败 {len(failed)} · Pareto {len(report["pareto_indices"])}',
                 f'已用时 {update["elapsed_s"]/60:.1f} min · 时间估算依据已完成的工况批次与提案']
        lines.extend(f'{row["condition_id"]}：'
                     + states.get(row['status'], phases.get(row['stage'], row['stage']))
                     for row in visible)
        if len(conditions) > 4:
            lines.append(f'另有 {len(conditions)-4} 个工况')
        reasons = [row['reason'] for row in (*failed, *conditions) if row.get('reason')]
        if report.get('baseline', {}).get('reason'):
            reasons.append(report['baseline']['reason'])
        if report.get('reason'):
            reasons.append(report['reason'])
        reasons = list(dict.fromkeys(reasons))
        lines.extend(reason[:240] for reason in reasons[-2:])
        self.live_details.setText('\n'.join(lines))
        self.live_details.setToolTip('\n'.join(reasons))
        self.fit_requested.emit()

    def export_pareto_data(self):
        """Save the archived plot data without re-evaluating a design."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from sjtu_tpmshx.applications.optimization.pareto_io import export_pareto_data as export

        report = self.report
        if report is None:
            self.status.setText('没有可导出的优化结果。')
            return
        default = Path(self.last_output_dir or '.') / 'pareto_data.xlsx'
        path, selected_filter = QFileDialog.getSaveFileName(
            self, '导出 Pareto 数据', str(default), 'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in ('.csv', '.xlsx'):
            target = target.with_suffix('.csv' if 'CSV' in selected_filter else '.xlsx')
        try:
            counts = export(report, target)
        except (KeyError, TypeError, ValueError, OSError, ImportError) as error:
            _log.exception('Could not export Pareto data')
            QMessageBox.warning(self, 'Pareto 导出失败', str(error))
            return
        self.status.setText(f'已导出 {counts["n_usable"]} 个有效点，'
                    f'{counts["n_pareto"]} 个前沿点：{target}')

    def export_geometry(self):
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                                      QFormLayout, QLabel, QMessageBox, QSpinBox)
        from sjtu_tpmshx.applications.optimization.export_ntop_csv import export_study_design, MAX_EXPORT_POINTS

        report = self.report
        index = self.selected_index
        if report is None or index is None:
            self.status.setText('请先在 Pareto 图中选择一个方案。')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('导出所选方案的建模坐标')
        layout = QFormLayout(dialog)
        layout.addRow(QLabel('各轴采样包含边界；单点取中面。坐标、L 和 t 均为 mm。'))
        counts = []
        for axis, default in zip('xyz'[:report['dimension']], (100, 50, 25)):
            edit = QSpinBox(dialog)
            edit.setRange(1, 999)
            edit.setValue(default)
            counts.append(edit)
            layout.addRow(f'{axis.upper()} 采样点', edit)
        size = QLabel()
        layout.addRow(size)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)

        def update_size():
            count = int(np.prod([edit.value() for edit in counts]))
            size.setText(f'{count:,} 个采样点 · 上限 {MAX_EXPORT_POINTS:,} · '
                         f'工作数组估算 {count * 128 / 1e6:.1f} MB')
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(count <= MAX_EXPORT_POINTS)
        for edit in counts:
            edit.valueChanged.connect(update_size)
        update_size()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target = QFileDialog.getExistingDirectory(self, '选择建模文件导出目录')
        if not target:
            return
        try:
            summary = export_study_design(report, index, target, tuple(edit.value() for edit in counts))
        except (ValueError, TypeError, KeyError, OSError) as error:
            QMessageBox.warning(self, '建模坐标导出失败', str(error))
            return
        self.status.setText(f'已导出方案 {report["history"][index]["index"]}：{summary["csv_geometry"]}')

    def pareto_ready(self):
        return bool(self._plot_indices)

    def field_ready(self):
        return sum(bool(axis.images) for axis in self.field_canvas.figure.axes) == 2

    def volume_ready(self):
        return self._volume_ready and self.volume_panel is not None and self.volume_panel._volume_actor is not None

    def _clear_preview(self):
        self.field_canvas.figure.clear()
        self.volume_data = None
        self._volume_ready = False
        self.result_tabs.setTabEnabled(1, False)
        self.result_tabs.setTabEnabled(2, False)
        if self.volume_panel is not None:
            self.volume_panel.hide()

    def show_pareto(self, report, *, running=False):
        self.report = report
        self.selected_index = None
        self.load_button.setEnabled(False)
        self.export_geometry_button.setEnabled(False)
        self._clear_preview()
        canvas = self.pareto_canvas
        self.result_tabs.setCurrentWidget(canvas)
        if self._pick_id is not None:
            canvas.mpl_disconnect(self._pick_id)
            self._pick_id = None
        self._front_line = None
        history = report['history']
        usable = [row for row in history if row['status'] == 'completed']
        constrained = 'mass_requirements' in report
        if constrained:
            from sjtu_tpmshx.applications.optimization.mass_design import constraint_keys
            keys = constraint_keys(report['mass_requirements'])

            def x_value(row):
                return 100. * max(row['objectives'][key] for key in keys)

            y_key = 'core_mass_kg'
        else:
            def x_value(row):
                return row['objectives']['pressure_ratio']

            y_key = 'heat_gain_percent'
        indices = sorted(report['pareto_indices'], key=lambda i: x_value(history[i]))
        rows = [history[i] for i in indices]
        render_error = None
        try:
            canvas.figure.clear()
            theme = get_theme()
            canvas.figure.set_facecolor(theme['fig_bg'])
            ax = canvas.figure.add_subplot(111)
            ax.set_facecolor(theme['ax_bg'])
            if usable:
                ax.scatter([x_value(row) for row in usable], [row['objectives'][y_key] for row in usable],
                           color=theme['mpl_subtitle'], label=f'usable ({len(usable)})')
            if rows:
                self._front_line, = ax.plot(
                    [x_value(row) for row in rows], [row['objectives'][y_key] for row in rows], 'o-',
                    color=theme['accent_orange'], picker=True, pickradius=6,
                    label=f'Best feasible ({len(rows)})' if constrained else f'Pareto ({len(rows)})')
                ax.legend(facecolor=theme['ax_bg'], edgecolor=theme['ax_spine'], labelcolor=theme['ax_text'])
            if constrained:
                ax.axvline(0., color=theme['ax_text'], linestyle='--', alpha=.5)
            ax.set_xlabel('Worst constraint residual [%] (<= 0 is feasible)' if constrained else
                          'Mean relative pressure drop [1]', color=theme['ax_text'])
            ax.set_ylabel('Core mass [kg]' if constrained else 'Mean useful heat gain [%]', color=theme['ax_text'])
            title = f'{report["method"]} · {report["n_evaluated"]} designs'
            if constrained and report['mass_requirements'].get('allow_nu_re_extrapolation'):
                title += ' · Nu Re extrapolation allowed'
            ax.set_title(title, color=theme['ax_text'])
            ax.tick_params(colors=theme['ax_text'])
            for spine in ax.spines.values():
                spine.set_edgecolor(theme['ax_spine'])
            ax.grid(True, alpha=.15, color=theme['ax_text'])
            canvas.draw()
            canvas.show()
            self._plot_indices = indices
            if rows and not running:
                self._pick_id = canvas.mpl_connect('pick_event', self.on_pareto_pick)
        except Exception as exc:
            _log.exception('Could not render optimization Pareto figure')
            render_error = f'{type(exc).__name__}: {exc}'
            self._plot_indices = []
            self._front_line = None
            canvas.figure.clear()
            canvas.hide()
        self.export_pareto_button.setEnabled(bool(usable) and not running)
        self.figures_changed.emit()
        if running:
            return render_error
        label = _termination_label(report)
        self._set_kpi(gen=label, **self._objective_kpis(report, rows), eta='—')
        self.set_stage('running', 'idle' if report['status'] == 'failed' else 'done')
        self.set_stage('result', 'active')
        baseline = report.get('baseline')
        if baseline and baseline['status'] == 'failed':
            summary = '均匀基准失败'
            try:
                reasons = study.baseline_failure_reasons(baseline, self.last_output_dir)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                reasons = [baseline['reason'], f'工况归档读取失败：{exc}']
            summary += ''.join(f' · {reason}' for reason in reasons if reason)
        else:
            selection = (f'{report["n_feasible"]} 个满足全部约束，{len(rows)} 个最轻方案' if constrained else
                         f'{len(rows)} 个 Pareto 方案')
            summary = f'{label} · {selection} · {report["n_usable"]}/{report["n_evaluated"]} 个候选数值合格'
        if report.get('reason'):
            summary += f' · {report["reason"]}'
        if render_error:
            summary += f' · Pareto 绘图失败：{render_error}'
        self.summary_banner.setText(summary)
        self.summary_banner.show()
        self.status.setText(summary)
        self.fit_requested.emit()
        return render_error

    def on_pareto_pick(self, event):
        if event.artist is not self._front_line or len(event.ind) == 0:
            return
        self.selected_index = self._plot_indices[int(event.ind[0])]
        self.load_button.setEnabled(True)
        self.export_geometry_button.setEnabled(True)
        self.show_field_preview(self.report['history'][self.selected_index]['x_decision'])

    def load_selected(self):
        form = self._form
        try:
            current = config_from_window(form, strict=True)
            config = study.archived_design(self.report, self.selected_index, self.last_output_dir, current)
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            self.status.setText(f'连续场载入失败：{exc}')
            return
        row = self.report['conditions'][0]
        form._continuous_field_spec = config.zones.config
        form._pareto_x_decision = None
        form.chk_zones.setChecked(True)
        for side in 'AB':
            fluid = getattr(config, f'fluid_{side}')
            if config.is_3d:
                getattr(form, 'le_mass_flow' + side).setText(format(row[f'mass_flow_{side}_kg_s'], '.17g'))
                getattr(form, 'combo_inlet_mode' + side).setCurrentIndex(1)
            form._set_temp_K(getattr(form, f'le_Tin{side}'), fluid.T_in_K)
            getattr(form, f'le_Pin{side}').setText(format(fluid.P_in_Pa, '.17g'))
            getattr(form, f'le_u{side}').setText(format(fluid.u_mps, '.17g'))
        form.case_files.invalidate_results_for_preset_load()
        form.case_files.resync_undo_baseline()
        self.refresh_setup()
        self.status.setText(f'已载入完整 {"XYZ" if config.is_3d else "XY"} 连续场 · '
                            f'工况 {row["condition_id"]} · 总质量流量保持不变')

    @Slot()
    def show_field_preview(self, x_decision=None):
        from matplotlib.ticker import MaxNLocator
        from sjtu_tpmshx.physical_models.continuous_field import from_decision_vector, decision_bounds
        try:
            current_spec = self._form._continuous_field_spec
            if x_decision is None and current_spec is not None and self._form.chk_zones.isChecked():
                cfg, spec = config_from_window(self._form, strict=True).validate(), deepcopy(current_spec)
                x_decision = spec.pop('x_decision')
            elif x_decision is None:
                cfg, spec = self.capture_case().validate(), self.field_spec()
                low, high = decision_bounds(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
                    spec['L_bounds'], spec['t_bounds'], n_ctrl_z=spec.get('n_ctrl_z'))
                x_decision = (low+high)/2
            else:
                cfg = ComputeConfig.from_dict(self.report['conditions'][0]['config'])
                spec = self.report['field_spec']
            geom = cfg.geometry
            field = from_decision_vector(x_decision, geom.tpms, geom.k_s_W_mK,
                geom.L_dom_m, geom.H_dom_m, **spec,
                **({'Lz_domain': geom.Lz_m} if 'n_ctrl_z' in spec else {}))
            volume = None
            if 'n_ctrl_z' in spec:
                # An odd sample count puts the center plane at half the physical depth.
                L_volume, t_volume = field.evaluate_volume(80, 40, 41)
                volume = dict(L_mm=L_volume, t_mm=t_volume,
                              dx=np.full(80, geom.L_dom_m/80),
                              dy=np.full(40, geom.H_dom_m/40),
                              dz=np.full(41, geom.Lz_m/41), flow_dir=None)
                L, t = L_volume[:, :, 20], t_volume[:, :, 20]
                suffix = f' · z = {geom.Lz_m*500:g} mm'
            else:
                L, t = field.evaluate_grid(80, 40)
                suffix = ''
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            self._clear_preview()
            self.figures_changed.emit()
            self.status.setText(f'连续场预览失败：{exc}')
            return
        canvas = self.field_canvas
        fig = canvas.figure
        fig.clear()
        theme = get_theme()
        fig.set_facecolor(theme['fig_bg'])
        axes = fig.subplots(2, 1, sharex=True)
        for ax, (name, values) in zip(axes, (('L', L), ('t', t))):
            ax.set_facecolor(theme['ax_bg'])
            im = ax.imshow(values.T, origin='lower', aspect='equal', cmap=resolve_cmap(f'{name}_mm'),
                           vmin=spec[f'{name}_bounds'][0], vmax=spec[f'{name}_bounds'][1],
                           extent=[0, geom.L_dom_m*1e3, 0, geom.H_dom_m*1e3])
            ax.set_title(f'{name}(x,y){suffix}', color=theme['ax_text'], fontsize=11,
                         loc='left')
            ax.set_ylabel('y [mm]', color=theme['ax_text'])
            ax.tick_params(colors=theme['ax_text'], labelsize=9, length=3)
            for spine in ax.spines.values():
                spine.set_edgecolor(theme['ax_spine'])
            cb = fig.colorbar(im, ax=ax, orientation='vertical',
                              fraction=.025, pad=.025, aspect=25,
                              ticks=MaxNLocator(nbins=4, steps=[1, 2, 5, 10]), format='%g')
            cb.set_label(f'{name} [mm]', color=theme['ax_text'], fontsize=9)
            cb.ax.tick_params(colors=theme['ax_text'], labelsize=8, length=2)
            cb.outline.set_visible(False)
        axes[-1].set_xlabel('x [mm]', color=theme['ax_text'])
        canvas.axes = [[ax] for ax in axes]
        self.volume_data = volume
        self._volume_ready = False
        self.result_tabs.setTabEnabled(2, volume is not None)
        self.result_tabs.setTabEnabled(1, True)
        self.result_tabs.setCurrentWidget(canvas)
        self.set_stage('result', 'active')
        self._form.workbench.switch_tab('pareto')
        canvas.draw_idle()
        self.figures_changed.emit()

    @Slot()
    def show_field_volume(self):
        """Populate the optimization volume only when its result tab is opened."""
        if self._form._close_pending:
            return
        if self.result_tabs.currentWidget() is not self.volume_host:
            return
        data = self.volume_data
        if data is None or self.volume_ready():
            return
        if self._volume_loading:
            return
        placeholder = self.volume_placeholder
        panel = self.volume_panel
        if panel is not None:
            panel.hide()
        placeholder.show()
        self._volume_ready = False
        self._volume_loading = True
        if panel is None:
            self._form.workbench.prepare_3d(self._show_prepared_field_volume)
        else:
            self._show_prepared_field_volume()


    def _show_prepared_field_volume(self):
        """Render the current preview after the imports finish."""
        placeholder = self.volume_placeholder
        try:
            if (self._form._close_pending
                    or self.result_tabs.currentWidget() is not self.volume_host
                    or self.volume_data is None):
                return
            data = self.volume_data
            panel = self.volume_panel
            if panel is None:
                if self._form.workbench.import_error:
                    raise RuntimeError(self._form.workbench.import_error)
                from .panel_vis_3d import ThreeDVisPanel
                panel = ThreeDVisPanel(self.volume_host)
                panel.restore_color_ranges(self._volume_ranges)
                panel.hide()
                self.volume_host.layout().addWidget(panel, 1)
                self.volume_panel = panel
            panel.set_fields(**data)
            if panel._volume_actor is None:
                raise RuntimeError('未能生成三维体图，请检查显示设备或重新打开预览')
            self._volume_ready = True
            placeholder.hide()
            panel.show()
        except Exception as exc:
            _log.exception('Could not render optimization volume')
            placeholder.setText(f'三维连续场显示失败：{exc}')
        finally:
            self._volume_loading = False
            self.figures_changed.emit()

    def restore_volume_ranges(self, ranges):
        self._volume_ranges = deepcopy(ranges)
        if self.volume_panel is not None:
            self.volume_panel.restore_color_ranges(ranges)


def _termination_label(report):
    label = {'completed': '完成', 'cancelled': '已取消', 'paused': '已暂停', 'failed': '失败'}.get(report['status'], '运行中')
    if report['status'] == 'completed' and report.get('stop_reason') == 'mass_lower_bound':
        label += '：达到模型质量下界'
    if report.get('mass_requirements', {}).get('allow_nu_re_extrapolation'):
        label += '（本任务允许 Nu-Re 外推）'
    return label
