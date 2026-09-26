"""ui/quick_design_panel.py — 快速设计面板绑定 (仿 optimize_panel.py)。

自由函数 + lazy QThread worker, 操作 duck-typed window 属性。后端不阻塞 UI。
公开 API: run_quick_design(window) / _gather_inputs(window) / _make_worker_class()。
"""
from __future__ import annotations
from math import isfinite
import sys

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_ENERGY_COLUMNS = ['构型', '工况', '热侧 Q [W]', '冷侧 Q [W]', '能量不平衡 [%]',
                   '诊断状态', '诊断原因', '数值收敛', '构型可行', '终验原因']

def _flist(text, cast=float):
    """'5, 6, 7' → [5.0,6.0,7.0]; 空 → []。"""
    return [cast(x) for x in str(text).replace("|", ",").split(",") if x.strip()]

def _gather_inputs(window) -> dict:
    """读面板控件 → dict。缺控件用安全默认 (供测试 duck-typed window)。"""
    def txt(attr, dflt=""):
        w = getattr(window, attr, None)
        return w.text() if (w is not None and hasattr(w, "text")) else dflt
    def cur(attr, dflt=""):
        w = getattr(window, attr, None)
        if w is None:
            return dflt
        # Display translations do not enter the worker/backend contract.
        # Existing text-only combos (including the topology) retain their values.
        return w.currentData() or w.currentText()
    def chk(attr, dflt=False):
        w = getattr(window, attr, None)
        return bool(w.isChecked()) if (w is not None and hasattr(w, "isChecked")) else dflt

    def positive(attr, default):
        value = float(txt(attr, str(default)))
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{attr} 必须为有限正数")
        return value

    rho_s = positive("le_qd_rho", 7900)
    k_s = positive("le_qd_ks", 16)
    # Keep the existing text-only property selector usable by scripted callers.
    pm_txt = cur("combo_qd_prop", "均温")
    prop_model = "const" if ("定" in pm_txt or pm_txt == "const") else "mean"
    # 矩形迎风 (固定高度) opt-in: 勾选 → 高 [mm]→[m]; 默认关 = 方形 (height=None)
    height = None
    if chk("chk_qd_rect"):
        height = positive("le_qd_height", 750) / 1e3
    mode = cur("combo_qd_mode", "auto")
    params = {
        "file": txt("le_qd_file"),
        "mode": mode,
        "arrangement": cur("combo_qd_arr", "counter"),
        "rho_s": rho_s,
        "k_s": k_s,
        "prop_model": prop_model,
        "height": height,
        "refine": chk("chk_qd_refine"),
    }
    if mode == "fixed":
        params["cell"] = (cur("combo_qd_cell_topo", "Diamond"),
                          positive("le_qd_cell_l", 7),
                          positive("le_qd_cell_t", 0.5))
    else:
        params["nodes"] = {
            "topo": [s.strip() for s in txt("le_qd_topo", "Diamond,Gyroid").split(",") if s.strip()],
            "l": _flist(txt("le_qd_l", "4,5,6,7,8")),
            "t": _flist(txt("le_qd_t", "0.3,0.4,0.5,0.6")),
        }
    return params

def _make_worker_class():
    """lazy QThread worker (Qt import 延迟, 非 GUI 工具可 import 本模块)。"""
    from PySide6.QtCore import QThread, Signal

    class _QDWorker(QThread):
        finished_with_result = Signal(object)   # {"feasible":[Design],"best":Design|None,"params":dict}
        error_signal = Signal(str)
        cancelled = Signal()

        def __init__(self, params):
            super().__init__()
            self.params = params
            # The first desktop bundle has no loky subprocess entry point.
            self.n_jobs = 1 if getattr(sys, 'frozen', False) else -1

        def run(self):
            from sjtu_tpmshx.domain.module_ports import RunControl
            from sjtu_tpmshx.domain.cancellation import CancelledError
            from sjtu_tpmshx.design.select import SelectionCancelled
            control = RunControl(cancel_check=self.isInterruptionRequested)
            results = []
            p = self.params

            def publish(termination_reason='completed'):
                feasible = [d for d in results if d.feasible]
                best = min(feasible, key=lambda d: d.V) if feasible else None
                self.finished_with_result.emit({
                    'feasible': feasible, 'all': results, 'best': best, 'params': p,
                    'termination_reason': termination_reason,
                    'partial': termination_reason != 'completed',
                })

            try:
                from sjtu_tpmshx.design.cases import load_cases
                from sjtu_tpmshx.design.sizing import size_fixed_cell
                from sjtu_tpmshx.design.select import enumerate_select
                control.check_cancelled()
                cases = load_cases(p["file"])
                ks = p.get("k_s", 16.0)
                pm = p.get("prop_model", "mean")
                ht = p.get("height", None)          # 矩形迎风高 [m]; None=方形 (默认)
                if p["mode"] == "fixed":
                    topo, l, t = p["cell"]
                    d = size_fixed_cell(cases, topo, l, t, p["arrangement"],
                                        rho_s=p["rho_s"], k_s=ks, prop_model=pm,
                                        height=ht, control=control)
                    results = [d]; best = d if d.feasible else None
                else:
                    results, best = enumerate_select(cases, p["arrangement"], p["nodes"],
                                                     rho_s=p["rho_s"], n_jobs=self.n_jobs, k_s=ks,
                                                     prop_model=pm, height=ht, control=control,
                                                     completed=results)
                    if p["refine"] and best is not None:
                        from sjtu_tpmshx.design.optimize import warm_start_joint
                        ref = warm_start_joint(cases, best, p["arrangement"],
                                               rho_s=p["rho_s"], k_s=ks, prop_model=pm,
                                               height=ht, control=control)
                        if ref is not best and ref.feasible:
                            results = list(results) + [ref]
                            if ref.V < best.V:
                                best = ref
                control.check_cancelled()
                publish()
            except CancelledError as exc:
                if isinstance(exc, SelectionCancelled):
                    results = exc.results
                publish('cancelled')
                self.cancelled.emit()
            except Exception as e:
                if results:
                    publish('failed')
                self.error_signal.emit(f"{type(e).__name__}: {e}")

    return _QDWorker

def _set_status(window, text):
    t = getattr(window, "_qd_status", None)
    if t is not None and hasattr(t, "setText"):
        try: t.setText(text); return
        except Exception: pass
    _log.info(f"[quick-design] {text}")

def _fill_table(window, feasible, *, partial=False):
    """把可行件按 V 排序填进 window._qd_table (QTableWidget)。无表则打印。"""
    rows = sorted(feasible, key=lambda d: d.V)
    from sjtu_tpmshx.design.select import pareto_tags
    from sjtu_tpmshx.design.report import warning_text
    tags = pareto_tags(feasible)
    if partial:
        tags = {key: [f'已完成候选内 {tag}' for tag in value] for key, value in tags.items()}
    def _hmm(d):                       # 矩形取固定高, 方形回退 W=s
        h = getattr(d, "height", 0.0) or d.s
        return f"{d.s*1e3:.0f}×{h*1e3:.0f}"
    tbl = getattr(window, "_qd_table", None)
    if tbl is None or not hasattr(tbl, "setRowCount"):
        for d in rows:
            vd = getattr(d, "validity", "")
            _log.info(f"  {d.topo} l={d.l} t={d.t} WxH={_hmm(d)} Lx={d.Lx*1e3:.1f} "
                      f"V={d.V*1e3:.3f}L wt={d.weight:.3f} dPh={d.dP_hot_max*100:.2f} "
                      f"dPc={d.dP_cold_max*100:.2f} Re_h={getattr(d,'Re_hot_max',0):.0f} "
                      f"Re_c={getattr(d,'Re_cold_max',0):.0f} "
                      f"{'⚠'+vd if vd else ''} {','.join(tags.get(id(d),[]))}")
            notices = warning_text(d)
            if notices:
                _log.info(notices)
        return
    cols = ["拓扑","l [mm]","t [mm]","W×H [mm]","Lx [mm]","体积 [L]","重量 [kg]","热侧压损%","冷侧压损%",
            "Re热","Re冷","验证域","标签"]
    tbl.setColumnCount(len(cols)); tbl.setRowCount(len(rows))
    tbl.setHorizontalHeaderLabels(cols)
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtGui import QColor
    from .theme import get_theme
    for i, d in enumerate(rows):
        vd = getattr(d, "validity", "")
        notices = warning_text(d)
        vals = [d.topo, f"{d.l:g}", f"{d.t:g}", _hmm(d),
                f"{d.Lx*1e3:.1f}", f"{d.V*1e3:.3f}", f"{d.weight:.3f}",
                f"{d.dP_hot_max*100:.2f}", f"{d.dP_cold_max*100:.2f}",
                f"{getattr(d,'Re_hot_max',0):.0f}", f"{getattr(d,'Re_cold_max',0):.0f}",
                (';'.join(filter(None, (vd, '有警告' if notices else ''))) or "域内"),
                ",".join(tags.get(id(d), []))]
        for j, v in enumerate(vals):
            it = QTableWidgetItem(str(v))
            if j == 11 and notices:
                it.setToolTip(notices)
            if vd or notices:           # Final-case warnings remain visible with validity.
                it.setForeground(QColor(get_theme()['warn']))
            tbl.setItem(i, j, it)


def _fill_energy_table(window, results):
    """Show existing final-case diagnostics for all completed candidates."""
    from sjtu_tpmshx.design.report import cid
    rows = []
    for design in results:
        for pc in getattr(design, 'percase', []):
            values = [pc.get('Q_W'), pc.get('Q_cold_W'), pc.get('energy_imbalance_rel')]
            numbers = ['—' if value is None else f'{value * scale:.6g}'
                       for value, scale in zip(values, (1, 1, 100))]
            rows.append([cid(design), str(pc['case']), *numbers,
                         pc.get('energy_imbalance_status', '未提供'),
                         pc.get('energy_imbalance_reason', '未提供能量不平衡诊断'),
                         str((pc.get('run_status') or {}).get('converged', 'unknown')),
                         '是' if design.feasible else '否',
                         '; '.join(pc.get('acceptance_reasons', []))])
    table = getattr(window, '_qd_energy_table', None)
    if table is None:
        for row in rows:
            _log.info(' · '.join(f'{label}={value}' for label, value in zip(_ENERGY_COLUMNS, row)))
        return
    from PySide6.QtWidgets import QTableWidgetItem
    table.setColumnCount(len(_ENERGY_COLUMNS))
    table.setHorizontalHeaderLabels(_ENERGY_COLUMNS)
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(i, j, item)


def run_quick_design(window) -> None:
    """点「运行设计」入口: 后台 worker 跑后端, 完成回填表。"""
    if getattr(window, '_close_pending', False):
        return
    if getattr(window, "_qd_worker", None) is not None:
        _set_status(window, "设计运行中…"); return
    # U3 (audit 2026-06-28): _gather_inputs parses free-text numeric fields
    # (node lists via _flist, the fixed-cell tuple — built even in auto mode).
    # A non-numeric token raises ValueError; left uncaught it escaped this
    # clicked slot, Qt swallowed it to stderr, and the Run button silently did
    # nothing with no _qd_status. Catch it and give feedback instead.
    try:
        params = _gather_inputs(window)
    except (ValueError, TypeError) as e:
        _set_status(window, f"输入解析失败: {e}"); return
    if not params["file"]:
        _set_status(window, "请先选工况文件"); return
    Worker = _make_worker_class()
    worker = Worker(params)

    def _on_done(res):
        feas, best = res["feasible"], res["best"]
        partial = res.get('partial', False)
        window._qd_last = res
        _fill_table(window, feas, partial=partial)
        _fill_energy_table(window, res['all'])
        if partial:
            state = '失败中止' if res.get('termination_reason') == 'failed' else '已取消'
            _set_status(window, f"{state} · 保留 {len(res['all'])} 个已完成候选，"
                        f"其中 {len(feas)} 个可行 · 部分结果，不代表完整搜索最优")
        elif not feas:
            _set_status(window, "无可行件 (≤450mm)")
        else:
            bt = f"{best.topo} l={best.l:g} t={best.t:g} V={best.V*1e3:.3f}L" if best else "—"
            _set_status(window, f"完成 · {len(feas)} 可行 · min-V: {bt}")

    def _on_err(msg):
        if getattr(window, '_close_pending', False):
            return
        last = getattr(window, '_qd_last', None)
        retained = (f" · 保留 {len(last['all'])} 个已完成候选 · 部分结果，不代表完整搜索最优"
                    if last and last.get('termination_reason') == 'failed' else '')
        _set_status(window, f"错误: {msg}{retained}")

    def _on_finished():
        if not worker.wait(0):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, _on_finished)
            return
        window._qd_worker = None
        for attr, enabled in (('_qd_run_btn', True), ('_qd_cancel_btn', False)):
            button = getattr(window, attr, None)
            if button is not None:
                button.setEnabled(enabled)
        worker.deleteLater()
        if getattr(window, '_close_pending', False):
            window._close_pending = False
            window.setEnabled(True)
            window.close()

    worker.finished_with_result.connect(_on_done)
    worker.error_signal.connect(_on_err)
    worker.finished.connect(_on_finished)
    window._qd_worker = worker
    window._qd_last = None
    for attr in ('_qd_table', '_qd_energy_table'):
        table = getattr(window, attr, None)
        if table is not None:
            table.setRowCount(0)
    for attr, enabled in (('_qd_run_btn', False), ('_qd_cancel_btn', True)):
        button = getattr(window, attr, None)
        if button is not None:
            button.setEnabled(enabled)
    execution = '单进程串行（桌面包）' if getattr(sys, 'frozen', False) else '并行候选'
    if params['mode'] == 'fixed':
        execution = '单候选定尺'
    _set_status(window, f"运行中 · {params['mode']} · {params['arrangement']} · {execution} …")
    worker.start()


def cancel_quick_design(window) -> None:
    worker = getattr(window, '_qd_worker', None)
    if worker is not None:
        worker.requestInterruption()
        _set_status(window, "正在取消 · 等待当前候选批次或计算步结束…")


def build_quick_design_dialog(parent=None):
    """构建并返回快速设计 QDialog。

    对话框实例即是 run_quick_design(window) 所期望的 duck-typed 'window'：
    所有合约属性 (le_qd_*, combo_qd_*, chk_qd_refine, _qd_table, _qd_status)
    直接附加在对话框对象上。

    调用方式::

        dlg = build_quick_design_dialog(parent=self)
        dlg.show()
    """
    # ── 延迟导入 Qt (保持模块可在非 GUI 环境导入) ──────────────
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
        QGroupBox, QLabel, QLineEdit, QPushButton,
        QComboBox, QCheckBox, QTableWidget, QFileDialog,
        QSizePolicy, QFrame, QWidget, QTabWidget,
    )
    from PySide6.QtCore import Qt

    def _pair(label, widget):
        """Keep each label beside its input within the grid."""
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        h.addWidget(QLabel(label)); h.addWidget(widget)
        return w

    class QuickDesignDialog(QDialog):
        def reject(self):
            if getattr(self, '_qd_worker', None) is not None:
                self.close()
            else:
                super().reject()

        def closeEvent(self, event):
            if getattr(self, '_qd_worker', None) is not None:
                event.ignore()
                self._close_pending = True
                cancel_quick_design(self)
                self.setEnabled(False)
                return
            super().closeEvent(event)

    dlg = QuickDesignDialog(parent)
    dlg.setWindowTitle("快速设计工具")
    dlg.resize(900, 700)
    dlg.setMinimumSize(640, 600)

    # ── Theme styling ────────────────────────────────────────────────
    # Quick-design previously used raw Qt defaults (it only inherited the
    # window palette, so it didn't match the app's design tokens and looked
    # wrong on the light theme). One cascading stylesheet from the active
    # theme styles every child widget to match the main UI in both palettes.
    from sjtu_tpmshx.ui.theme import get_theme as _gt_qd, _build_styles as _bs_qd
    _t = _gt_qd()
    _qd_styles = _bs_qd()
    dlg.setStyleSheet(
        f"QDialog{{background:{_t['bg']};}}"
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

    root = QVBoxLayout(dlg)
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
            dlg, "选择工况文件", "",
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
    combo_arr.addItem("逆流", "counter")
    combo_arr.addItem("交叉流", "cross")
    combo_arr.setToolTip("逆流：两股流体沿同轴反向流动。\n交叉流：两股流体沿相互垂直的方向流动。")
    le_rho = QLineEdit("7900"); le_rho.setFixedWidth(80)
    le_ks = QLineEdit("16"); le_ks.setFixedWidth(60)
    le_ks.setToolTip("固体热导率: 304SS=16, AlSi10Mg≈150, Cu≈300。"
                     "影响固体导热与两侧换热耦合，具体影响随工况和芯体尺寸变化。")
    combo_prop = QComboBox()
    combo_prop.addItem("均温物性", "mean")
    combo_prop.addItem("入口定物性", "const")
    combo_prop.setToolTip("均温物性：先按入口温度求解，再按各股流体的入口与出口平均温度更新物性并求解一次。\n"
                          "入口定物性：按入口温度取物性，只求解一次。\n"
                          "两种方案均在每次求解中保持各股物性均匀；压降均使用入口物性。")
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

    le_l = QLineEdit("4,5,6,7,8")
    le_l.setToolTip("胞元尺寸 l (mm) 列表，逗号分隔。当前 K/cF 的 CFD 节点为 4/5/6/7/8；"
                    "各流体 Nu 与实验修正的适用范围另行检查。")
    auto_form.addRow("l 列表 (mm):", le_l)

    le_t = QLineEdit("0.3,0.4,0.5,0.6")
    le_t.setToolTip("壁厚 t (mm) 列表，逗号分隔。当前 K/cF 的 CFD 节点为 0.3/0.4/0.5/0.6；"
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
    btn_run.clicked.connect(lambda: run_quick_design(dlg))
    btn_row.addWidget(btn_run)

    btn_cancel = QPushButton("取消")
    btn_cancel.setEnabled(False)
    btn_cancel.clicked.connect(lambda: cancel_quick_design(dlg))
    dlg._qd_cancel_btn = btn_cancel
    btn_row.addWidget(btn_cancel)

    btn_export = QPushButton("导出 xlsx")
    btn_export.setMinimumWidth(90)

    def _export():
        last = getattr(dlg, "_qd_last", None)
        if last is None:
            dlg._qd_status.setText("无结果可导出")
            return
        results = last.get("all") or last.get("feasible", [])
        if not results:
            dlg._qd_status.setText("无结果可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            dlg, "导出设计结果 (双 sheet)", "quick_design_results.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        try:
            from sjtu_tpmshx.design.report import write_xlsx          # CLI/UI 共用双 sheet
            partial = last.get('partial', False)
            reason = last.get('termination_reason', 'cancelled')
            n_total, n_feas, n_det = write_xlsx(path, results, partial=partial,
                                               termination_reason=reason)
            state = '失败中止' if reason == 'failed' else '已取消'
            dlg._qd_status.setText(
                f"{f'已导出部分结果（{state}）' if partial else '已导出'} → {path}  (构型汇总 {n_total}/可行 {n_feas} · "
                f"工况明细 {n_det} 行)")
        except Exception as exc:
            dlg._qd_status.setText(f"导出失败: {exc}")

    btn_export.clicked.connect(_export)
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
    dlg.le_qd_file         = le_file
    dlg.combo_qd_mode      = combo_mode
    dlg.combo_qd_arr       = combo_arr
    dlg.le_qd_rho          = le_rho
    dlg.le_qd_ks           = le_ks
    dlg.combo_qd_prop      = combo_prop
    dlg.chk_qd_rect        = chk_rect
    dlg.le_qd_height       = le_height
    dlg.le_qd_topo         = le_topo
    dlg.le_qd_l            = le_l
    dlg.le_qd_t            = le_t
    dlg.chk_qd_refine      = chk_refine
    dlg.combo_qd_cell_topo = combo_cell_topo
    dlg.le_qd_cell_l       = le_cell_l
    dlg.le_qd_cell_t       = le_cell_t
    dlg._qd_table          = tbl
    dlg._qd_energy_table   = energy_table
    dlg._qd_status         = lbl_status

    # ── 测试钩子属性 ─────────────────────────────────────────
    dlg._qd_run_btn    = btn_run
    dlg._qd_auto_group = auto_group
    dlg._qd_fixed_group = fixed_group

    return dlg
