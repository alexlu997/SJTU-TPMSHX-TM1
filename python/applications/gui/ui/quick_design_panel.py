"""Quick Design page, input controls and result tables."""
from __future__ import annotations

from math import isfinite
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from sjtu_tpmshx.model_configs.df_domain import TRAIN_L_NODES, TRAIN_T_NODES

from .quick_design_job import QuickDesignJob

_ENERGY_COLUMNS = ['构型', '工况', '热侧 Q [W]', '冷侧 Q [W]', '能量不平衡 [%]',
                   '诊断状态', '诊断原因', '数值收敛', '构型可行', '终验原因']

def _flist(text):
    return [float(value) for value in text.replace("|", ",").split(",") if value.strip()]


def _pair(label, widget):
    """Keep each label beside its input within the grid."""
    pair = QWidget()
    row = QHBoxLayout(pair)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(QLabel(label))
    row.addWidget(widget)
    return pair


class QuickDesignPage(QWidget):
    """Keep the current design job and its results across page changes."""

    activity_changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._worker = None
        self.last_result = None
        self.setWindowTitle("快速设计工具")
        self.setMinimumSize(640, 600)
        self._build_controls()

    def is_idle(self):
        return self._worker is None

    @Slot()
    def submit(self):
        if self._window._close_pending:
            return
        if not self.is_idle():
            if self._qd_cancel_btn.isEnabled():
                self._qd_status.setText("设计运行中…")
            return
        try:
            params = self._gather_inputs()
        except (ValueError, TypeError) as error:
            self._qd_status.setText(f"输入解析失败: {error}")
            return
        if not params['file']:
            self._qd_status.setText("请先选工况文件")
            return

        worker = QuickDesignJob(params, control=self._window.run_control)
        worker.finished_with_result.connect(self._show_result, Qt.ConnectionType.QueuedConnection)
        worker.error_signal.connect(self._show_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._release_worker, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        self.last_result = None
        self._qd_table.setRowCount(0)
        self._qd_energy_table.setRowCount(0)
        self._qd_run_btn.setEnabled(False)
        self._qd_cancel_btn.setEnabled(True)
        execution = '单进程串行（桌面包）' if worker.n_jobs == 1 else '并行候选'
        if params['mode'] == 'fixed':
            execution = '单候选定尺'
        self._qd_status.setText(f"运行中 · {params['mode']} · {params['arrangement']} · {execution} …")
        worker.start()
        self.activity_changed.emit()

    @Slot()
    def cancel(self):
        if self._worker is not None:
            self._worker.requestInterruption()
            if self._qd_cancel_btn.isEnabled():
                self._qd_cancel_btn.setEnabled(False)
                self._qd_status.setText("正在取消 · 等待当前候选批次或计算步结束…")

    @Slot(object)
    def _show_result(self, result):
        self._qd_cancel_btn.setEnabled(False)
        self.last_result = result
        feasible, best = result['feasible'], result['best']
        self._fill_table(feasible, partial=result['partial'])
        self._fill_energy_table(result['all'])
        if result['partial']:
            state = '失败中止' if result['termination_reason'] == 'failed' else '已取消'
            text = (f"{state} · 保留 {len(result['all'])} 个已完成候选，"
                    f"其中 {len(feasible)} 个可行 · 部分结果，不代表完整搜索最优")
        elif not feasible:
            text = "无可行件 (≤450mm)"
        else:
            description = f"{best.topo} l={best.l:g} t={best.t:g} V={best.V*1e3:.3f}L"
            text = f"完成 · {len(feasible)} 可行 · min-V: {description}"
        self._qd_status.setText(text)

    @Slot(str)
    def _show_error(self, message):
        self._qd_cancel_btn.setEnabled(False)
        retained = ''
        if self.last_result is not None:
            retained = (f" · 保留 {len(self.last_result['all'])} 个已完成候选"
                        " · 部分结果，不代表完整搜索最优")
        self._qd_status.setText(f"错误: {message}{retained}")

    @Slot()
    def _release_worker(self):
        # QThread emits finished before thread-local cleanup has ended.
        if not self._worker.wait(0):
            QTimer.singleShot(10, self, self._release_worker)
            return
        self._worker.deleteLater()
        self._worker = None
        self._qd_run_btn.setEnabled(True)
        self.activity_changed.emit()

    def _gather_inputs(self) -> dict:
        """Read the selected controls from the Quick Design page."""
        def positive(attr, divisor=1.):
            value = float(getattr(self, attr).text()) / divisor
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{attr} 必须为有限正数")
            return value

        rho_s = positive("le_qd_rho")
        k_s = positive("le_qd_ks")
        height = positive("le_qd_height", 1e3) if self.chk_qd_rect.isChecked() else None
        mode = self.combo_qd_mode.currentData()
        params = {
            "file": self.le_qd_file.text(),
            "mode": mode,
            "arrangement": self.combo_qd_arr.currentData(),
            "rho_s": rho_s,
            "k_s": k_s,
            "prop_model": self.combo_qd_prop.currentData(),
            "height": height,
            "refine": self.chk_qd_refine.isChecked(),
        }
        if mode == "fixed":
            params["cell"] = (self.combo_qd_cell_topo.currentText(),
                              positive("le_qd_cell_l"),
                              positive("le_qd_cell_t"))
        else:
            params["nodes"] = {
                "topo": [s.strip() for s in self.le_qd_topo.text().split(",") if s.strip()],
                "l": _flist(self.le_qd_l.text()),
                "t": _flist(self.le_qd_t.text()),
            }
        return params

    def _fill_table(self, feasible, *, partial=False):
        """Show feasible designs in order of increasing volume."""
        rows = sorted(feasible, key=lambda d: d.V)
        from sjtu_tpmshx.applications.design.select import pareto_tags
        from sjtu_tpmshx.applications.design.report import warning_text
        tags = pareto_tags(feasible)
        if partial:
            tags = {key: [f'已完成候选内 {tag}' for tag in value] for key, value in tags.items()}
        def _hmm(d):                       # 矩形取固定高, 方形回退 W=s
            h = d.height or d.s
            return f"{d.s*1e3:.0f}×{h*1e3:.0f}"
        tbl = self._qd_table
        tbl.setRowCount(len(rows))
        from PySide6.QtGui import QColor
        from .theme import get_theme
        for i, d in enumerate(rows):
            vd = d.validity
            notices = warning_text(d)
            vals = [d.topo, f"{d.l:g}", f"{d.t:g}", _hmm(d),
                    f"{d.Lx*1e3:.1f}", f"{d.V*1e3:.3f}", f"{d.weight:.3f}",
                    f"{d.dP_hot_max*100:.2f}", f"{d.dP_cold_max*100:.2f}",
                    f"{d.Re_hot_max:.0f}", f"{d.Re_cold_max:.0f}",
                    (';'.join(filter(None, (vd, '有警告' if notices else ''))) or "域内"),
                    ",".join(tags.get(id(d), []))]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 11 and notices:
                    it.setToolTip(notices)
                if vd or notices:           # Final-case warnings remain visible with validity.
                    it.setForeground(QColor(get_theme()['warn']))
                tbl.setItem(i, j, it)


    def _fill_energy_table(self, results):
        """Show existing final-case diagnostics for all completed candidates."""
        from sjtu_tpmshx.applications.design.report import cid
        rows = []
        for design in results:
            for pc in design.percase:
                values = [pc.get('Q_W'), pc.get('Q_cold_W'), pc.get('energy_imbalance_rel')]
                numbers = ['—' if value is None else f'{value * scale:.6g}'
                           for value, scale in zip(values, (1, 1, 100))]
                rows.append([cid(design), str(pc['case']), *numbers,
                             pc.get('energy_imbalance_status', '未提供'),
                             pc.get('energy_imbalance_reason', '未提供能量不平衡诊断'),
                             str((pc.get('run_status') or {}).get('converged', 'unknown')),
                             '是' if design.feasible else '否',
                             '; '.join(pc.get('acceptance_reasons', []))])
        table = self._qd_energy_table
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(i, j, item)

    def export(self):
        last = self.last_result
        if last is None or not last["all"]:
            self._qd_status.setText("无结果可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出设计结果 (双 sheet)", "quick_design_results.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        try:
            if Path(path).resolve() == Path(last['params']['file']).resolve():
                raise ValueError('导出文件不能覆盖输入工况文件')
            from sjtu_tpmshx.applications.design.report import write_xlsx          # CLI/UI 共用双 sheet
            partial = last['partial']
            reason = last['termination_reason']
            n_total, n_feas, n_det = write_xlsx(path, last['all'], partial=partial,
                                               termination_reason=reason)
            state = '失败中止' if reason == 'failed' else '已取消'
            self._qd_status.setText(
                f"{f'已导出部分结果（{state}）' if partial else '已导出'} → {path}  (构型汇总 {n_total}/可行 {n_feas} · "
                f"工况明细 {n_det} 行)")
        except Exception as exc:
            self._qd_status.setText(f"导出失败: {exc}")

    def _build_controls(self):
        from sjtu_tpmshx.applications.gui.ui.theme import get_theme as _gt_qd, _build_styles as _bs_qd
        _t = _gt_qd()
        _qd_styles = _bs_qd()
        self.setStyleSheet(
            f"QuickDesignPage{{background:{_t['bg']};}}"
            f"QWidget{{color:{_t['fg']}; font-size:10pt;}}"
            f"QLabel{{color:{_t['fg']}; background:transparent;}}"
            f"QToolTip{{color:{_t['fg']}; background:{_t['surface_elevated']};"
            f" border:1px solid {_t['card_border']}; padding:4px;}}"
            f"QLineEdit{{background:{_t['inp_bg']}; color:{_t['inp_fg']};"
            f" border:1px solid {_t['inp_border']}; border-radius:6px; padding:4px 8px;}}"
            f"QLineEdit:focus{{border:1px solid {_t['inp_focus']};}}"
            f"QLineEdit:disabled{{color:{_t['val_empty_fg']}; background:{_t['scroll_bg']};}}"
            f"QGroupBox{{color:{_t['fg']}; background:{_t['surface_raised']};"
            f" border:1px solid {_t['card_border']}; border-radius:6px;"
            f" margin-top:12px; padding:12px 8px 8px 8px; font-weight:600;}}"
            f"QGroupBox::title{{subcontrol-origin:margin; subcontrol-position:top left;"
            f" left:10px; padding:0 5px; color:{_t['sub_fg']};}}"
            f"QCheckBox{{color:{_t['fg']}; spacing:6px;}}"
            f"QCheckBox::indicator{{width:15px; height:15px; border-radius:4px;"
            f" border:1px solid {_t['chk_border']}; background:{_t['chk_bg']};}}"
            f"QCheckBox::indicator:hover{{border:1px solid {_t['chk_hover_border']};}}"
            f"QCheckBox::indicator:checked{{background:{_t['chk_checked_bg']};"
            f" border:1px solid {_t['chk_checked_border']};}}"
            f"QPushButton{{background:transparent; color:{_t['btn_sec_fg']};"
            f" border:1px solid {_t['btn_sec_border']}; border-radius:6px;"
            f" padding:5px 14px; font-weight:600;}}"
            f"QPushButton:hover{{background:{_t['btn_sec_hover_bg']};}}"
            f"QTableWidget{{background:{_t['surface_raised']}; color:{_t['fg']};"
            f" gridline-color:{_t['card_border']}; border:1px solid {_t['card_border']};"
            f" border-radius:6px;}}"
            f"QTableWidget::item:selected{{background:{_t['combo_sel']};}}"
            f"QTabWidget::pane{{border:none;}}"
            f"QTabBar::tab{{background:{_t['surface_raised']}; color:{_t['sub_fg']};"
            f" padding:6px 12px; border-bottom:2px solid transparent;}}"
            f"QTabBar::tab:selected{{color:{_t['fg']}; border-bottom:2px solid {_t['accent_primary']};}}"
            f"QHeaderView{{background:{_t['surface_elevated']};}}"
            f"QTableCornerButton::section{{background:{_t['surface_elevated']}; border:none;}}"
            f"QHeaderView::section{{background:{_t['surface_elevated']}; color:{_t['fg']};"
            f" border:none; border-right:1px solid {_t['card_border']};"
            f" border-bottom:1px solid {_t['card_border']}; padding:5px 8px; font-weight:600;}}"
            f"QScrollBar:vertical, QScrollBar:horizontal{{background:transparent; border:none;}}"
            f"QScrollBar::handle{{background:{_t['scroll_handle']}; border-radius:4px;"
            f" min-height:24px; min-width:24px;}}"
            f"QScrollBar::add-line, QScrollBar::sub-line{{height:0; width:0;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── 工况文件选择 ──────────────────────────────────────────
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        lbl_file = QLabel("工况文件:")
        file_row.addWidget(lbl_file)
        le_file = QLineEdit()
        le_file.setPlaceholderText("选择 .xlsx / .csv 工况文件…")
        le_file.setReadOnly(False)
        file_row.addWidget(le_file, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.setFixedWidth(68)

        def _browse():
            path, _ = QFileDialog.getOpenFileName(
                self, "选择工况文件", "",
                "工况 (*.xlsx *.csv);;所有文件 (*)")
            if path:
                le_file.setText(path)

        btn_browse.clicked.connect(_browse)
        file_row.addWidget(btn_browse)
        root.addLayout(file_row)
        file_help = QLabel(
            "工况单位：温度 K · 绝压 kPa · 质量流量 kg/s · 换热量 kW；压降上限填比例。")
        file_help.setWordWrap(True)
        file_help.setStyleSheet(_qd_styles['SUB'])
        file_help.setToolTip(
            "CSV 表头或 Excel 首张工作表首行：\n"
            "case, hot_fluid, T_in_h_K, P_in_h_kPa, mdot_h,\n"
            "cold_fluid, T_in_c_K, P_in_c_kPa, mdot_c, dPlim_h, dPlim_c。\n"
            "另需 Q_kW 或 dT_h_K 至少一列；两者均填写时优先使用热侧温降 dT_h_K。\n"
            "例如 5% 压降上限填 0.05。此格式与 GUI 预设及 CLI 配置不同。")
        root.addWidget(file_help)

        # ── 模式 / 排列 / 材料 / 物性 ────────────────────────────
        combo_mode = QComboBox()
        combo_mode.addItem("自动搜索", "auto")
        combo_mode.addItem("固定胞元", "fixed")
        combo_mode.setToolTip("自动搜索：枚举拓扑、胞元尺寸和壁厚，再为各候选定尺。\n"
                             "固定胞元：使用指定的拓扑、胞元尺寸和壁厚，搜索芯体尺寸。")
        combo_arr = QComboBox()
        combo_arr.addItem("交叉流", "cross")
        combo_arr.addItem("逆流", "counter")
        combo_arr.setToolTip("交叉流：两股流体沿相互垂直的方向流动（默认）。\n逆流：两股流体沿同轴反向流动。")
        from sjtu_tpmshx.applications.design import sizing
        le_rho = QLineEdit(str(sizing.RHO_S).removesuffix(".0")); le_rho.setFixedWidth(80)
        le_ks = QLineEdit(str(sizing.K_STEEL).removesuffix(".0")); le_ks.setFixedWidth(60)
        le_ks.setToolTip("固体热导率: 304SS=16, AlSi10Mg≈150, Cu≈300。"
                         "影响固体导热与两侧换热耦合，具体影响随工况和芯体尺寸变化。")
        combo_prop = QComboBox()
        combo_prop.addItem("均温物性", "mean")
        combo_prop.addItem("入口定物性", "const")
        combo_prop.setToolTip("均温物性：先按入口温度求解，再按各股流体的入口与出口平均温度更新物性并求解一次（默认）。\n"
                              "入口定物性：按入口温度取物性，只求解一次。\n"
                              "两种方案均在每次求解中保持各股物性均匀；压降均使用入口物性。\n"
                              "水侧 Nu 中的 Pr 均固定取 320 K / 0.2 MPa，未随入口或均温物性更新。")
        # 矩形迎风 (固定高度) opt-in — 默认关 = 方形 s×s (UI 现状不变)
        chk_rect = QCheckBox("固定高度迎风")
        chk_rect.setChecked(False)
        chk_rect.setToolTip("默认关 = 方形迎风 s×s (现状)。勾选 = 矩形: 迎风高 H 固定、宽自由, "
                            "求 min-V。适合给定迎风高度的工况 (如 H=750mm)。")
        le_height = QLineEdit("750"); le_height.setFixedWidth(64); le_height.setEnabled(False)
        le_height.setToolTip("矩形迎风固定高 H [mm] (仅勾选「固定高度迎风」时生效)。")
        chk_rect.toggled.connect(le_height.setEnabled)

        # Three columns keep complete labels visible at the minimum width.
        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(16); mode_grid.setVerticalSpacing(6)
        _al = Qt.AlignLeft | Qt.AlignVCenter
        mode_grid.addWidget(_pair("模式:", combo_mode),         0, 0, _al)
        mode_grid.addWidget(_pair("排列:", combo_arr),          0, 1, _al)
        mode_grid.addWidget(_pair("物性模型:", combo_prop),     0, 2, _al)
        mode_grid.addWidget(_pair("密度 (kg/m³):", le_rho),     1, 0, _al)
        mode_grid.addWidget(_pair("热导率 (W/m·K):", le_ks),    1, 1, _al)
        mode_grid.addWidget(chk_rect,                           2, 0, _al)
        mode_grid.addWidget(_pair("迎风高 (mm):", le_height),   2, 1, _al)
        mode_grid.setColumnStretch(3, 1)
        root.addLayout(mode_grid)

        # ── Auto 参数组 ───────────────────────────────────────────
        auto_group = QGroupBox("自动搜索参数")
        auto_form = QFormLayout(auto_group)
        auto_form.setSpacing(6)

        le_topo = QLineEdit("Diamond,Gyroid")
        le_topo.setToolTip("拓扑列表，逗号分隔")
        auto_form.addRow("拓扑 (topo):", le_topo)

        l_nodes = [str(value).removesuffix(".0") for value in TRAIN_L_NODES]
        le_l = QLineEdit(",".join(l_nodes))
        le_l.setToolTip(f"胞元尺寸 l (mm) 列表，逗号分隔。当前 K/cF 的 CFD 节点为 {'/'.join(l_nodes)}；"
                        "各流体 Nu 与实验修正的适用范围另行检查。")
        auto_form.addRow("l 列表 (mm):", le_l)

        t_nodes = [str(value).removesuffix(".0") for value in TRAIN_T_NODES]
        le_t = QLineEdit(",".join(t_nodes))
        le_t.setToolTip(f"壁厚 t (mm) 列表，逗号分隔。当前 K/cF 的 CFD 节点为 {'/'.join(t_nodes)}；"
                        "各流体 Nu 与实验修正的适用范围另行检查。")
        auto_form.addRow("t 列表 (mm):", le_t)

        chk_refine = QCheckBox("连续 l、t 精修（warm-start）")
        chk_refine.setChecked(False)
        chk_refine.setToolTip("可选: 对枚举最优件再做连续 (l,t) Nelder-Mead 精修。"
                              "使用串行局部搜索，可能增加计算时间；改善幅度取决于当前搜索网格。"
                              "需要进一步比较连续尺寸候选时可开启。")
        auto_form.addRow("精细化:", chk_refine)

        root.addWidget(auto_group)

        # ── Fixed 参数组 ──────────────────────────────────────────
        fixed_group = QGroupBox("固定胞元参数")
        fixed_form = QFormLayout(fixed_group)
        fixed_form.setSpacing(6)

        combo_cell_topo = QComboBox()
        combo_cell_topo.addItems(["Diamond", "Gyroid"])
        for combo in (combo_mode, combo_arr, combo_prop, combo_cell_topo):
            combo.setStyleSheet(_qd_styles['COMBO'])
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        fixed_form.addRow("拓扑:", combo_cell_topo)

        le_cell_l = QLineEdit("7")
        le_cell_l.setToolTip("胞元尺寸 l (mm)")
        fixed_form.addRow("l (mm):", le_cell_l)

        le_cell_t = QLineEdit("0.5")
        le_cell_t.setToolTip("壁厚 t (mm)")
        fixed_form.addRow("t (mm):", le_cell_t)

        root.addWidget(fixed_group)

        # ── 初始可见性 & 切换 ─────────────────────────────────────
        fixed_group.setVisible(False)   # 默认 auto 模式

        def _on_mode_changed(_index):
            is_auto = combo_mode.currentData() == "auto"
            auto_group.setVisible(is_auto)
            fixed_group.setVisible(not is_auto)

        combo_mode.currentIndexChanged.connect(_on_mode_changed)

        # ── 操作按钮行 ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_run = QPushButton("▶ 运行设计")
        btn_run.setMinimumWidth(120)
        btn_run.setStyleSheet(_qd_styles['BTN_PRIMARY'])   # main action — blue CTA
        btn_run.clicked.connect(self.submit)
        btn_row.addWidget(btn_run)

        btn_cancel = QPushButton("取消")
        btn_cancel.setEnabled(False)
        btn_cancel.clicked.connect(self.cancel)
        self._qd_cancel_btn = btn_cancel
        btn_row.addWidget(btn_cancel)

        btn_export = QPushButton("导出 xlsx")
        btn_export.setMinimumWidth(90)

        btn_export.clicked.connect(self.export)
        btn_row.addWidget(btn_export)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # ── 结果表 ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        result_tabs = QTabWidget()

        tbl = QTableWidget(0, 13)
        tbl.setHorizontalHeaderLabels(
            ["拓扑", "l [mm]", "t [mm]", "W×H [mm]", "Lx [mm]", "体积 [L]", "重量 [kg]",
             "热侧压损%", "冷侧压损%", "Re热", "Re冷", "验证域", "标签"])
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.horizontalHeader().setStretchLastSection(True)
        # Visual order only: retain logical column indices for table writers.
        tbl.horizontalHeader().moveSection(5, 1)
        tbl.setColumnWidth(0, 90)
        tbl.setColumnWidth(1, 64)
        tbl.setColumnWidth(2, 64)
        tbl.setColumnWidth(5, 88)
        tbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_tabs.addTab(tbl, '可行设计')

        energy_page = QWidget()
        energy_layout = QVBoxLayout(energy_page)
        energy_layout.setContentsMargins(0, 6, 0, 0)
        energy_note = QLabel('已完成候选的逐工况诊断（含不可行构型）；能量诊断不参与当前可行性筛选。')
        energy_note.setWordWrap(True)
        energy_note.setStyleSheet(_qd_styles['SUB'])
        energy_layout.addWidget(energy_note)
        energy_table = QTableWidget(0, len(_ENERGY_COLUMNS))
        energy_table.setHorizontalHeaderLabels(_ENERGY_COLUMNS)
        energy_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        energy_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for index, width in enumerate((155, 65, 105, 105, 130, 130, 180, 85, 85, 180)):
            energy_table.setColumnWidth(index, width)
        energy_layout.addWidget(energy_table, 1)
        result_tabs.addTab(energy_page, '工况能量诊断')
        root.addWidget(result_tabs, 1)

        # ── 状态标签 ─────────────────────────────────────────────
        lbl_status = QLabel("就绪")
        lbl_status.setWordWrap(True)
        root.addWidget(lbl_status)

        # ── 绑定合约属性 ──────────────────────────────────────────
        self.le_qd_file = le_file
        self.combo_qd_mode = combo_mode
        self.combo_qd_arr = combo_arr
        self.le_qd_rho = le_rho
        self.le_qd_ks = le_ks
        self.combo_qd_prop = combo_prop
        self.chk_qd_rect = chk_rect
        self.le_qd_height = le_height
        self.le_qd_topo = le_topo
        self.le_qd_l = le_l
        self.le_qd_t = le_t
        self.chk_qd_refine = chk_refine
        self.combo_qd_cell_topo = combo_cell_topo
        self.le_qd_cell_l = le_cell_l
        self.le_qd_cell_t = le_cell_t
        self._qd_table = tbl
        self._qd_energy_table = energy_table
        self._qd_status = lbl_status
        self._qd_run_btn = btn_run
