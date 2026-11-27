"""Optimization page, Style P2 Pareto front, failed-baseline card, and Rule A drawers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from math import isfinite
from pathlib import Path
import time
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.applications.gui.controllers.user_storage import optimization_output_dir
from sjtu_tpmshx.applications.optimization import optimization_job as study
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.model_configs.df_domain import TRAIN_L, TRAIN_T
from sjtu_tpmshx.run_control.logutil import get_logger

from .builders_base import collapsible_section
from .design_peek import (
    ConditionCell,
    FrontListItem,
    ObjectiveCell,
    SelectedDesignData,
    SelectedDesignPanel,
    SpecRow,
    format_objective_summary,
)
from .field_factory import UnitLineEdit
from .icons import icon
from .inspector_drawer import BandHeader
from .matplotlib_canvas import MatplotlibCanvas
from .optimize_job import OptimizationJob
from .pareto_view import ParetoPoint, ParetoView
from .readout_strip import ReadoutItem, ReadoutNotice
from .sparkline import Sparkline
from .symbols import SYM, TIMES, rng, signed, val_unit
from .theme import RADIUS_BTN, RADIUS_INPUT, get_theme, resolve_cmap
from .window_config import config_from_window

_log = get_logger(__name__)

_FIELD_WIDTH_DESKTOP = 196
_FIELD_WIDTH_COMPACT = 176

_FLUID_LABELS: dict[str, str] = {
    "air": "Air",
    "water": "Water",
    "sco2": "sCO₂",
    "co2": "CO₂",
}

_PHASE_LABELS: dict[str, str] = {
    "initial": "初始候选",
    "iteration": "迭代候选",
}


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


class _Hairline(QWidget):
    """Single-device-pixel horizontal divider."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(QColor(get_theme()["border"]), 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()


class _CrispPanel(QFrame):
    """Neutral Style P2 rounded panel with a 1-device-pixel border (no tinted fills)."""

    def __init__(self, radius: float = 11.0, bg_key: str = "panel", parent: QWidget | None = None):
        super().__init__(parent)
        self._radius = radius
        self._bg_key = bg_key
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        theme = get_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(theme[self._bg_key]))
        painter.setPen(QPen(QColor(theme["border"]), 0.5))
        painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.end()


class _OptPillIsland(QFrame):
    """Floating top-left segmented tab switch for Pareto / Field / 3D Field."""

    current_changed = Signal(int)

    def __init__(self, labels: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = 0
        self._buttons: list[QPushButton] = []
        self.setObjectName("optPillIsland")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(0)

        self._track = QFrame()
        self._track.setObjectName("optPillTrack")
        tl = QHBoxLayout(self._track)
        tl.setContentsMargins(2, 2, 2, 2)
        tl.setSpacing(2)

        for idx, text in enumerate(labels):
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, i=idx: self._pick(i))
            self._buttons.append(btn)
            tl.addWidget(btn)
        outer.addWidget(self._track)
        self.apply_theme()

    def _pick(self, idx: int) -> None:
        if 0 <= idx < len(self._buttons) and self._buttons[idx].isEnabled():
            self.set_current_index(idx, emit=True)

    def set_tab_enabled(self, idx: int, enabled: bool) -> None:
        if 0 <= idx < len(self._buttons):
            self._buttons[idx].setEnabled(bool(enabled))
            self._buttons[idx].setCursor(
                Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
            )

    def set_current_index(self, idx: int, *, emit: bool = False) -> None:
        clamped = max(0, min(int(idx), len(self._buttons) - 1))
        changed = clamped != self._current
        self._current = clamped
        self.apply_theme()
        if emit and changed:
            self.current_changed.emit(clamped)

    def apply_theme(self) -> None:
        t = get_theme()
        self.setStyleSheet(
            f"QFrame#optPillIsland {{ background: {t['popover']}; "
            f"border: 1px solid {t['border']}; border-radius: {RADIUS_BTN}px; }}"
        )
        self._track.setStyleSheet(
            f"QFrame#optPillTrack {{ background: {t['sunken']}; border: none; "
            f"border-radius: {RADIUS_INPUT}px; }}"
        )
        on_qss = (
            f"QPushButton {{ background: {t['seg_on']}; color: {t['fg']}; "
            f"border: 1px solid {t['border']}; border-radius: 5px; "
            "padding: 0 11px; font-size: 12px; font-weight: 600; }"
        )
        off_qss = (
            f"QPushButton {{ background: transparent; color: {t['sub']}; "
            "border: none; border-radius: 5px; padding: 0 11px; "
            "font-size: 12px; font-weight: 400; }"
            f"QPushButton:hover {{ color: {t['fg']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        for idx, btn in enumerate(self._buttons):
            btn.setStyleSheet(on_qss if idx == self._current else off_qss)


class OptimizationPage(QWidget):
    """Own the study controls, the active job, Pareto front, failed card, and drawers."""

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
        self._plot_indices: list[int] = []
        self._pick_id = None
        self.volume_panel = None
        self.volume_data = None
        self._volume_ready = False
        self._volume_loading = False
        self._volume_ranges: dict[str, Any] = {}
        self._job = None
        self._launching = False
        self._stop_requested = self._pause_requested = False
        self._live_update = None
        self._last_drawn = -1
        self._compact = False
        self._shell_attached = False
        self._status_kind = "idle"
        self._status_short = "空闲"
        self._rule_a_grids: list[QGridLayout] = []
        self._rule_a_fields: list[QWidget] = []
        self._pair_containers: list[tuple[QWidget, tuple[QWidget, ...]]] = []
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._draw_live)
        self._build(form)
        self.stack.currentChanged.connect(self._fit_page)
        self.refresh_setup()

    def drawer_tabs(self) -> tuple[tuple[str, QWidget], ...]:
        """Return ``(title, body_widget)`` pairs mounted into the shell InspectorDrawer."""
        return (
            ("搜索配置", self._config_drawer_body),
            ("所选方案", self._selected_drawer_body),
        )

    def header_widgets(self) -> tuple[QWidget, QWidget, QWidget, QWidget, QWidget]:
        """Return header controls mounted into workbenchHeader."""
        return (
            self._opt_status_badge,
            self.resume_button,
            self.pause_button,
            self.cancel_button,
            self.start_button,
        )

    def attach_to_shell(self) -> None:
        """Connect OptimizationPage to the Style P2 Main_Menu shell."""
        self._shell_attached = True
        btn_export = getattr(self._form, "btn_export", None)
        if btn_export is not None and btn_export.menu() is not None:
            menu = btn_export.menu()
            act = menu.addAction("导出 Pareto 数据 — CSV / XLSX", self.export_pareto_data)
            self._act_export_pareto = act
            menu.aboutToShow.connect(self._sync_export_menu_action)
        self._notify_shell()

    def _sync_export_menu_action(self) -> None:
        act = getattr(self, "_act_export_pareto", None)
        if act is None:
            return
        on_opt = self._form.workbench.active_tab == "pareto"
        act.setVisible(on_opt)
        act.setEnabled(on_opt and self.export_pareto_button.isEnabled())

    def status_badge_spec(self) -> tuple[str, str]:
        """Return ``(kind, label)`` for the header status pill."""
        return self._status_kind, self._status_short

    def has_exportable_result(self) -> bool:
        """Return True when the optimization header Export button should be visible."""
        return bool(
            self.pareto_ready()
            or self.field_ready()
            or self.volume_ready()
            or self.export_pareto_button.isEnabled()
        )

    def readout_spec(self) -> tuple[list[ReadoutItem], ReadoutNotice | None]:
        """Return bottom ReadoutStrip cells for the current optimization state."""
        rep = self.report
        if not isinstance(rep, dict):
            return [], None

        n_eval = rep.get("n_evaluated")
        budget = rep.get("design_budget")
        n_usable = rep.get("n_usable")
        pareto_ids = rep.get("pareto_indices") or []
        eval_text = (
            f"{n_eval} / {budget}"
            if isinstance(n_eval, int) and isinstance(budget, int)
            else (str(n_eval) if isinstance(n_eval, int) else "—")
        )
        usable_text = str(n_usable) if isinstance(n_usable, int) else "—"

        baseline = rep.get("baseline")
        if isinstance(baseline, dict) and baseline.get("status") == "failed":
            elapsed = rep.get("elapsed_s")
            if not isinstance(elapsed, (int, float)):
                elapsed = baseline.get("elapsed_s")
            if isinstance(elapsed, (int, float)) and isfinite(elapsed):
                el_val = f"{elapsed:.1f}"
                el_unit = "s"
            else:
                el_val = "—"
                el_unit = ""
            return [
                ReadoutItem("已评估", eval_text),
                ReadoutItem("合格", usable_text),
                ReadoutItem("用时", el_val, el_unit),
            ], None

        constrained = "mass_requirements" in rep
        items: list[ReadoutItem] = [
            ReadoutItem("已评估", eval_text),
            ReadoutItem("合格", usable_text),
        ]
        if constrained:
            n_feas = rep.get("n_feasible")
            items.append(ReadoutItem("可行", str(n_feas) if isinstance(n_feas, int) else "—"))
        else:
            items.append(ReadoutItem("前沿", str(len(pareto_ids))))

        history = rep.get("history") or []
        sel = None
        if self.selected_index is not None and 0 <= self.selected_index < len(history):
            sel = history[self.selected_index]
        if sel is not None and isinstance(sel.get("objectives"), dict):
            obj = sel["objectives"]
            idx = sel.get("index", self.selected_index)
            if constrained:
                mass = obj.get("core_mass_kg")
                items.append(
                    ReadoutItem(
                        f"方案 #{idx} 芯体质量",
                        f"{mass:.3f}" if isinstance(mass, (int, float)) and isfinite(mass) else "—",
                        "kg" if isinstance(mass, (int, float)) and isfinite(mass) else "",
                    )
                )
                from sjtu_tpmshx.applications.optimization.mass_design import constraint_keys

                keys = constraint_keys(rep["mass_requirements"])
                vals = [obj[k] for k in keys if k in obj and isinstance(obj[k], (int, float))]
                if vals:
                    res_pct = 100.0 * max(vals)
                    items.append(
                        ReadoutItem(
                            "最大残差",
                            signed(res_pct, "+.2f"),
                            "%",
                            tone="ok" if res_pct <= 0 else "warn",
                        )
                    )
            else:
                hg = obj.get("heat_gain_percent")
                pr = obj.get("pressure_ratio")
                if isinstance(hg, (int, float)) and isfinite(hg):
                    items.append(
                        ReadoutItem(
                            f"方案 #{idx} 换热提升",
                            signed(hg, "+.3f"),
                            "%",
                            tone="ok" if hg > 0 else "fg",
                        )
                    )
                else:
                    items.append(ReadoutItem(f"方案 #{idx} 换热提升", "—"))
                items.append(
                    ReadoutItem(
                        "相对压降",
                        f"{pr:.4f}" if isinstance(pr, (int, float)) and isfinite(pr) else "—",
                    )
                )
        elif not self.is_idle():
            items.append(ReadoutItem("剩余时间", self.kpi_eta.text()))

        notice = None
        if rep.get("status") == "cancelled":
            notice = ReadoutNotice("已取消", "保留已完成样本", kind="warn")
        elif rep.get("status") == "paused":
            notice = ReadoutNotice("已暂停", "已保存检查点，可继续任务", kind="warn")
        elif rep.get("status") == "failed":
            notice = ReadoutNotice("运行中止", str(rep.get("reason") or "详见状态记录"), kind="err")
        return items, notice

    def set_compact(self, compact: bool) -> None:
        """Adjust Rule A drawer widths, Pareto plot, and header labels for 1280x720."""
        compact = bool(compact)
        if self._compact == compact:
            return
        self._compact = compact
        width = _FIELD_WIDTH_COMPACT if compact else _FIELD_WIDTH_DESKTOP
        for grid in self._rule_a_grids:
            grid.setColumnMinimumWidth(1, width)
        for widget in self._rule_a_fields:
            widget.setFixedWidth(width)
        for container, children in self._pair_containers:
            container.setFixedWidth(width)
            n = len(children)
            gap = 4 if n == 3 else 6
            each = (width - gap * (n - 1)) // n
            for child in children:
                child.setFixedWidth(each)
        self.pareto_view.set_compact(compact)
        self.selected_panel.set_compact(compact)

    def _notify_shell(self) -> None:
        if not self._shell_attached:
            return
        from .builders_sidebar import refresh_header_status, update_result_sidebar_visibility

        refresh_header_status(self._form)
        update_result_sidebar_visibility(self._form)
        refresh_nav = getattr(self._form, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()

    def _open_output_dir(self) -> None:
        if self.last_output_dir is not None:
            self._form.dialogs.open_output_folder(self.last_output_dir)
        else:
            self._form.dialogs.open_output_folder(scope="optimization")

    def _open_status_menu(self) -> None:
        menu = QMenu(self._opt_status_badge)
        t = get_theme()
        menu.setStyleSheet(
            f"QMenu {{ background: {t['popover']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_INPUT}px; padding: 4px; }}"
            "QMenu::item { padding: 6px 14px; border-radius: 5px; }"
            f"QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['accent_fg']}; }}"
        )
        act_dir = menu.addAction("打开输出目录", self._open_output_dir)
        act_dir.setEnabled(
            self._form.dialogs.resolve_output_directory(scope="optimization") is not None
        )
        act_exp = menu.addAction("导出 Pareto 数据…", self.export_pareto_data)
        act_exp.setEnabled(self.export_pareto_button.isEnabled())
        menu.exec(self._opt_status_badge.mapToGlobal(self._opt_status_badge.rect().bottomLeft()))

    def _make_rule_a_section(
        self,
        title: str,
        rows: list[tuple[Any, QWidget]],
        *,
        first: bool = False,
        actions: tuple[tuple[str, Any], ...] = (),
        count: int | None = None,
    ) -> tuple[QWidget, BandHeader]:
        t = get_theme()
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        header = BandHeader(
            title, first=first, collapsible=False, count=count, actions=actions, tokens=t
        )
        vl.addWidget(header)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        grid = QGridLayout(body)
        grid.setContentsMargins(16, 8, 16, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(
            1, _FIELD_WIDTH_COMPACT if self._compact else _FIELD_WIDTH_DESKTOP
        )
        self._rule_a_grids.append(grid)

        for r_i, (label_text, field_widget) in enumerate(rows):
            if label_text:
                lbl = QLabel(str(label_text))
                if "<" in str(label_text):
                    lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setStyleSheet(
                    f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; "
                    "background: transparent; border: none;"
                )
                grid.addWidget(
                    lbl, r_i, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
            grid.addWidget(
                field_widget, r_i, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        vl.addWidget(body)
        return wrap, header

    def _build(self, form) -> None:
        t = get_theme()
        self.setStyleSheet(f"OptimizationPage {{ background: {t['canvas']}; border: none; }}")

        op_v = QVBoxLayout(self)
        op_v.setContentsMargins(0, 0, 0, 0)
        op_v.setSpacing(0)

        # ── Header controls (mounted into workbenchHeader by ui_builders.py) ──
        self._opt_status_badge = QPushButton("空闲")
        self._opt_status_badge.setFixedHeight(28)
        self._opt_status_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._opt_status_badge.clicked.connect(self._open_status_menu)

        self.resume_button = QPushButton("继续已有任务…")
        self.resume_button.setFixedHeight(30)
        self.resume_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_button.setIcon(icon("play", t["sub"]))
        self.resume_button.setIconSize(QSize(13, 13))
        self.resume_button.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_BTN}px; "
            "padding: 0 11px; font-size: 12.5px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        self.resume_button.setToolTip(
            "读取 optimization.json，在新目录继续；使用保存的工况和搜索设置。"
        )
        self.resume_button.clicked.connect(self.resume)

        self.pause_button = QPushButton("暂停并保存")
        self.pause_button.setFixedHeight(30)
        self.pause_button.setEnabled(False)
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_BTN}px; "
            "padding: 0 11px; font-size: 12.5px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        self.pause_button.clicked.connect(self.pause)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedHeight(30)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setToolTip("请求优雅取消当前搜索（保留已算样本）")
        self.cancel_button.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_BTN}px; "
            "padding: 0 11px; font-size: 12.5px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        self.cancel_button.clicked.connect(self.cancel)

        self.start_button = QPushButton("启动搜索  Ctrl+↵")
        self.start_button.setFixedHeight(30)
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setIcon(icon("play", t["primary_fg"]))
        self.start_button.setIconSize(QSize(13, 13))
        self.start_button.setStyleSheet(
            f"QPushButton {{ background: {t['primary_bg']}; color: {t['primary_fg']}; "
            f"border: none; border-radius: {RADIUS_BTN}px; padding: 0 13px; "
            "font-size: 12.5px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {t['primary_hover']}; }}"
            f"QPushButton:disabled {{ background: {t['border']}; color: {t['tert']}; }}"
        )
        self.start_button.setToolTip("启动多工况连续场搜索 (Ctrl+Enter)")
        self.start_button.clicked.connect(self.start)

        # Action buttons synced with drawer actions and header export menu.
        self.export_pareto_button = QPushButton("导出 Pareto 数据", self)
        self.export_pareto_button.setEnabled(False)
        self.export_pareto_button.clicked.connect(self.export_pareto_data)
        self.export_pareto_button.hide()

        self.load_button = QPushButton("载入所选方案", self)
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.load_selected)
        self.load_button.hide()

        self.export_geometry_button = QPushButton("导出所选方案建模坐标", self)
        self.export_geometry_button.setEnabled(False)
        self.export_geometry_button.clicked.connect(self.export_geometry)
        self.export_geometry_button.hide()

        self.status = QLabel("空闲 — 配置参数后点击启动")
        self.status.setWordWrap(True)
        self.status.hide()

        self.summary_banner = QLabel("")
        self.summary_banner.setWordWrap(True)
        self.summary_banner.hide()

        # ── Main 3-stage stack (0: ready/config, 1: running, 2: results/failed) ──
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stack.setStyleSheet("background: transparent;")
        op_v.addWidget(self.stack, 1)

        # Page 0: Ready canvas + collapsed single-run zone panel (kept reachable for zone edits).
        p1 = QWidget()
        p1.setStyleSheet(f"background: {t['canvas']};")
        p1v = QVBoxLayout(p1)
        p1v.setContentsMargins(20, 16, 20, 16)
        p1v.setSpacing(12)

        ready_card = _CrispPanel(radius=11.0, bg_key="panel")
        ready_card.setMaximumWidth(520)
        rc_lay = QVBoxLayout(ready_card)
        rc_lay.setContentsMargins(24, 22, 24, 22)
        rc_lay.setSpacing(8)
        rc_title = QLabel("多工况连续场优化")
        rc_title.setStyleSheet(
            f"color: {t['fg']}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        rc_desc = QLabel(
            "在右侧「搜索配置」检查器设置工况、算法预算与 L / t 连续场范围，"
            "点击页首「启动搜索」开始评估，或点击「继续已有任务…」恢复检查点。"
        )
        rc_desc.setWordWrap(True)
        rc_desc.setStyleSheet(
            f"color: {t['sub']}; font-size: 12.5px; background: transparent;"
        )
        rc_lay.addWidget(rc_title)
        rc_lay.addWidget(rc_desc)

        p1v.addStretch(2)
        p1v.addWidget(ready_card, 0, Qt.AlignmentFlag.AlignHCenter)
        p1v.addStretch(2)

        zone_grid, zone_card = collapsible_section(
            p1v,
            "单点计算分区（不参与优化搜索）",
            form.theme.style("T_NEUTRAL"),
            form.theme.style("F_NEUTRAL"),
            expanded=False,
        )
        zone_grid.addWidget(form._zone_panel, 0, 0, 1, 2)
        form.chk_zones.toggled.connect(zone_card._set_expanded)
        self.stack.addWidget(p1)

        # Page 1: Live running progress page
        p2 = QWidget()
        p2.setStyleSheet(f"background: {t['canvas']};")
        p2v = QVBoxLayout(p2)
        p2v.setContentsMargins(20, 16, 20, 16)
        p2v.setSpacing(14)

        def _mk_kpi(caption: str, initial: str = "—") -> tuple[QFrame, QLabel, QLabel]:
            card = _CrispPanel(radius=10.0, bg_key="panel")
            card.setFixedHeight(78)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cap = QLabel(caption)
            cap.setStyleSheet(
                f"color: {t['sub']}; font-size: 11px; font-weight: 600; background: transparent;"
            )
            val = QLabel(initial)
            _enable_tnum(val)
            val.setStyleSheet(
                f"color: {t['fg']}; font-size: 20px; font-weight: 600; background: transparent;"
            )
            cl.addWidget(cap)
            cl.addWidget(val)
            return card, val, cap

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(12)
        card_gen, self.kpi_gen, _ = _mk_kpi("已评估候选 / 预算")
        card_q, self.kpi_q, self.kpi_q_caption = _mk_kpi("最大换热提升 [%]")
        card_dp, self.kpi_dp, self.kpi_dp_caption = _mk_kpi("最小相对压降 [1]")
        card_eta, self.kpi_eta, _ = _mk_kpi("剩余时间")
        kpi_grid.addWidget(card_gen, 0, 0)
        kpi_grid.addWidget(card_q, 0, 1)
        kpi_grid.addWidget(card_dp, 1, 0)
        kpi_grid.addWidget(card_eta, 1, 1)

        spark_card = _CrispPanel(radius=10.0, bg_key="panel")
        spark_card.setFixedHeight(72)
        scl = QVBoxLayout(spark_card)
        scl.setContentsMargins(14, 8, 14, 8)
        scl.setSpacing(2)
        spark_cap = QLabel("总预算进度 [%]（含均匀基准）")
        spark_cap.setStyleSheet(
            f"color: {t['sub']}; font-size: 11px; font-weight: 600; background: transparent;"
        )
        self.sparkline = Sparkline(height=40)
        scl.addWidget(spark_cap)
        scl.addWidget(self.sparkline, 1)
        kpi_grid.addWidget(spark_card, 2, 0, 1, 2)
        p2v.addLayout(kpi_grid)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {t['sunken']}; border: 1px solid {t['border']}; "
            "border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}"
        )
        self.progress_bar.hide()
        p2v.addWidget(self.progress_bar)

        self.live_details = QLabel()
        self.live_details.setTextFormat(Qt.TextFormat.PlainText)
        self.live_details.setWordWrap(True)
        self.live_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.live_details.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; background: transparent;"
        )
        p2v.addWidget(self.live_details)
        p2v.addStretch(1)
        self.stack.addWidget(p2)

        # Page 2: Results (Pareto / Field / 3D Field) + Failed Baseline Card (F09)
        p3 = QWidget()
        p3.setStyleSheet(f"background: {t['canvas']};")
        p3v = QVBoxLayout(p3)
        p3v.setContentsMargins(0, 0, 0, 0)
        p3v.setSpacing(0)

        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(14, 10, 14, 4)
        pill_row.setSpacing(8)
        self._result_pill = _OptPillIsland(("Pareto 前沿", "尺寸 / 壁厚场", "三维场"))
        self._result_pill.set_tab_enabled(1, False)
        self._result_pill.set_tab_enabled(2, False)
        pill_row.addWidget(self._result_pill)
        pill_row.addStretch(1)
        p3v.addLayout(pill_row)

        self._result_body_stack = QStackedWidget()
        self._result_body_stack.setStyleSheet("background: transparent;")

        # Body 0: result_tabs (hidden native tab bar, driven by _result_pill)
        self.pareto_view = ParetoView(tokens=t)
        self.pareto_canvas = self.pareto_view

        self.field_canvas = MatplotlibCanvas(1, 1, figsize=(10.5, 6.8))
        self.field_canvas.fig.clear()
        self.field_canvas.fig.set_layout_engine("compressed")

        self.volume_host = QWidget()
        self.volume_host.setStyleSheet(f"background: {t['canvas']};")
        volume_layout = QVBoxLayout(self.volume_host)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(4)
        note = QLabel("连续设计场预览 · 可旋转、缩放和切片 · L / t 参数分布")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['sub']}; padding: 4px 14px; font-size: 12px;")
        volume_layout.addWidget(note)
        self.volume_placeholder = QLabel("选择三维连续场后可查看体视图")
        self.volume_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_placeholder.setWordWrap(True)
        self.volume_placeholder.setStyleSheet(f"color: {t['sub']}; font-size: 12.5px;")
        volume_layout.addWidget(self.volume_placeholder, 1)

        tabs = QTabWidget()
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tabs.setMinimumHeight(320)
        tabs.tabBar().hide()
        tabs.setStyleSheet(f"QTabWidget::pane {{ border: none; background: {t['canvas']}; }}")
        tabs.addTab(self.pareto_canvas, "Pareto 前沿")
        tabs.addTab(self.field_canvas, "尺寸 / 壁厚场")
        tabs.addTab(self.volume_host, "三维场")
        tabs.setTabEnabled(1, False)
        tabs.setTabEnabled(2, False)
        self.result_tabs = tabs
        self._result_pill.current_changed.connect(self._on_result_pill_changed)
        tabs.currentChanged.connect(self._on_result_tab_changed)
        self._result_body_stack.addWidget(tabs)

        # Body 1: F09 Centered neutral-panel baseline failure card
        self._failed_card_host = self._build_failed_card(t)
        self._result_body_stack.addWidget(self._failed_card_host)

        p3v.addWidget(self._result_body_stack, 1)
        self.stack.addWidget(p3)

        # ── Drawer Tab 0: 搜索配置 (Rule A, F09/F10) ──
        self._build_config_drawer(form, t)

        # ── Drawer Tab 1: 所选方案 (F08) ──
        self._selected_drawer_body = QWidget()
        self._selected_drawer_body.setStyleSheet("background: transparent;")
        sel_lay = QVBoxLayout(self._selected_drawer_body)
        sel_lay.setContentsMargins(0, 0, 0, 0)
        sel_lay.setSpacing(0)
        self.selected_panel = SelectedDesignPanel(None, tokens=t)
        self.selected_panel.load_requested.connect(lambda _idx: self.load_selected())
        self.selected_panel.export_requested.connect(lambda _idx: self.export_geometry())
        self.selected_panel.front_item_selected.connect(self.select_design)
        sel_lay.addWidget(self.selected_panel)
        sel_lay.addStretch(1)

        form.combo_dim.currentIndexChanged.connect(self.refresh_setup)
        form.chk_zones.toggled.connect(self._zone_changed)

    def _build_failed_card(self, t: dict[str, Any]) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet(f"background: {t['canvas']};")
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(24, 16, 24, 24)
        hl.setSpacing(0)

        box = QWidget()
        box.setStyleSheet("background: transparent;")
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        ico_lbl = QLabel()
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{t["err"]}" stroke-width="1.65" stroke-linecap="round" '
            f'stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
            '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
        )
        pm = QPixmap(90, 90)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        pm.setDevicePixelRatio(3)
        ico_lbl.setPixmap(pm)
        ico_lbl.setFixedSize(30, 30)
        ico_lbl.setStyleSheet("background: transparent;")
        v.addWidget(ico_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("搜索没有开始")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet(
            f"color: {t['fg']}; font-size: 16px; font-weight: 600; background: transparent;"
        )
        v.addWidget(title)

        card = _CrispPanel(radius=11.0, bg_key="panel")
        card.setFixedWidth(540)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        cl = QGridLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setHorizontalSpacing(18)
        cl.setVerticalSpacing(9)
        cl.setColumnMinimumWidth(0, 64)
        cl.setColumnStretch(1, 1)

        self._fail_cond_val = QLabel("—")
        self._fail_stage_val = QLabel("—")
        self._fail_reason_val = QLabel("—")
        for r_i, (k, val_lbl, is_err) in enumerate(
            (
                ("工况", self._fail_cond_val, False),
                ("失败阶段", self._fail_stage_val, False),
                ("原因", self._fail_reason_val, True),
            )
        ):
            kl = QLabel(k)
            kl.setFixedWidth(64)
            kl.setStyleSheet(
                f"color: {t['sub']}; font-size: 12.5px; font-weight: 500; background: transparent;"
            )
            val_lbl.setWordWrap(True)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            val_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            if is_err:
                val_lbl.setTextFormat(Qt.TextFormat.RichText)
            val_lbl.setStyleSheet(
                f"color: {t['err'] if is_err else t['fg']}; font-size: 12.5px; "
                f"font-weight: {500 if is_err else 400}; background: transparent;"
            )
            cl.addWidget(kl, r_i, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            cl.addWidget(val_lbl, r_i, 1)
        v.addSpacing(2)
        v.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        btn_qss = (
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 0 12px; font-size: 12px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        btn_edit = QPushButton("编辑公共工况")
        btn_edit.setFixedHeight(28)
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.setIcon(icon("sliders", t["sub"]))
        btn_edit.setIconSize(QSize(13, 13))
        btn_edit.setStyleSheet(btn_qss)
        btn_edit.clicked.connect(self.edit_common_settings)

        btn_folder = QPushButton("打开输出目录")
        btn_folder.setFixedHeight(28)
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setIcon(icon("folder-open", t["sub"]))
        btn_folder.setIconSize(QSize(13, 13))
        btn_folder.setStyleSheet(btn_qss)
        btn_folder.clicked.connect(self._open_output_dir)
        self._fail_open_dir_btn = btn_folder

        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_folder)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        hl.addStretch(2)
        hl.addWidget(box, 0, Qt.AlignmentFlag.AlignHCenter)
        hl.addStretch(3)
        return holder

    def _build_config_drawer(self, form, t: dict[str, Any]) -> None:
        self._config_drawer_body = QWidget()
        self._config_drawer_body.setStyleSheet("background: transparent;")
        v = QVBoxLayout(self._config_drawer_body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Band 1: 公共工况 (with 编辑 action)
        pub_header = BandHeader(
            "公共工况",
            first=True,
            collapsible=False,
            actions=(("编辑", self.edit_common_settings),),
            tokens=t,
        )
        self.edit_common_button = pub_header._action_buttons[0]
        v.addWidget(pub_header)

        pub_block = QWidget()
        pub_block.setStyleSheet("background: transparent;")
        pub_grid = QGridLayout(pub_block)
        pub_grid.setContentsMargins(16, 4, 16, 6)
        pub_grid.setHorizontalSpacing(10)
        pub_grid.setVerticalSpacing(0)
        pub_grid.setColumnStretch(0, 1)
        pub_grid.setColumnMinimumWidth(1, _FIELD_WIDTH_DESKTOP)
        self._rule_a_grids.append(pub_grid)

        self._pub_topo_val = QLabel("—")
        self._pub_dom_val = QLabel("—")
        self._pub_fluid_val = QLabel("—")
        for r_i, (k, val_lbl) in enumerate(
            (
                ("拓扑", self._pub_topo_val),
                ("计算域", self._pub_dom_val),
                ("流体", self._pub_fluid_val),
            )
        ):
            kl = QLabel(k)
            kl.setFixedHeight(28)
            kl.setStyleSheet(
                f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; background: transparent;"
            )
            val_lbl.setFixedHeight(28)
            _enable_tnum(val_lbl)
            val_lbl.setStyleSheet(
                f"color: {t['fg']}; font-size: 12.5px; font-weight: 400; "
                "padding-left: 8px; background: transparent;"
            )
            pub_grid.addWidget(kl, r_i, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            pub_grid.addWidget(val_lbl, r_i, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(pub_block)

        self.public_summary = QLabel()
        self.public_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.public_summary.hide()

        # Band 2: 工况 N (with 使用当前, 导入 JSON… actions)
        self._cond_header = BandHeader(
            "工况",
            collapsible=False,
            count=1,
            actions=(
                ("使用当前", self.use_current_condition),
                ("导入 JSON…", self.import_conditions),
            ),
            tokens=t,
        )
        v.addWidget(self._cond_header)

        cond_table_wrap = QWidget()
        cond_table_wrap.setStyleSheet("background: transparent;")
        ct_lay = QVBoxLayout(cond_table_wrap)
        ct_lay.setContentsMargins(16, 8, 16, 6)
        ct_lay.setSpacing(0)
        self._cond_table_box = _CrispPanel(radius=7.0, bg_key="canvas")
        self._cond_table_layout = QVBoxLayout(self._cond_table_box)
        self._cond_table_layout.setContentsMargins(1, 1, 1, 1)
        self._cond_table_layout.setSpacing(0)
        ct_lay.addWidget(self._cond_table_box)
        v.addWidget(cond_table_wrap)

        cond_extra = QWidget()
        cond_extra.setStyleSheet("background: transparent;")
        ce_grid = QGridLayout(cond_extra)
        ce_grid.setContentsMargins(16, 2, 16, 10)
        ce_grid.setHorizontalSpacing(10)
        ce_grid.setVerticalSpacing(6)
        ce_grid.setColumnStretch(0, 1)
        ce_grid.setColumnMinimumWidth(1, _FIELD_WIDTH_DESKTOP)
        self._rule_a_grids.append(ce_grid)

        obj_lbl = QLabel("目标")
        obj_lbl.setStyleSheet(
            f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        self._objective_val = QLabel("当前工况")
        self._objective_val.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 400; "
            "padding-left: 8px; background: transparent;"
        )
        ce_grid.addWidget(obj_lbl, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ce_grid.addWidget(
            self._objective_val, 0, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.depth_label = QLabel("二维深度")
        self.depth_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        self.depth = UnitLineEdit(
            form.le_Lz.text(), unit="m", display_unit="mm", display_scale=1000.0
        )
        self.depth.setFixedHeight(28)
        self.depth.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        self.depth.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.depth.setStyleSheet(
            f"QLineEdit {{ background: {t['inp_bg']}; color: {t['inp_fg']}; "
            f"border: 1px solid {t['inp_border']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 2px 8px; font-size: 12.5px; }"
            f"QLineEdit:focus {{ border: 1.5px solid {t['inp_focus']}; }}"
        )
        self.depth.setToolTip("物理厚度用于 kg/s 与二维单位深度流量换算；不改变二维网格。")
        self._rule_a_fields.append(self.depth)
        ce_grid.addWidget(
            self.depth_label, 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        ce_grid.addWidget(
            self.depth, 1, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        v.addWidget(cond_extra)

        self.condition_summary = QLabel()
        self.condition_summary.setWordWrap(True)
        self.condition_summary.hide()

        # Band 3: 方法与预算
        spin_qss = (
            f"QAbstractSpinBox {{ background: {t['inp_bg']}; color: {t['inp_fg']}; "
            f"border: 1px solid {t['inp_border']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 2px 6px; font-size: 12.5px; }"
            f"QAbstractSpinBox:focus {{ border: 1.5px solid {t['inp_focus']}; }}"
            "QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { "
            "subcontrol-origin: border; width: 0px; height: 0px; border: none; }"
        )
        self.method = QComboBox()
        for label, key in (
            ("qLogNEHVI", "qlognehvi"),
            ("qLogNParEGO", "qlognparego"),
            ("qLogNEI · 芯体减重", "qlognei"),
            ("Sobol", "sobol"),
        ):
            self.method.addItem(label, key)
        self.method.setFixedHeight(28)
        self.method.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        self.method.setStyleSheet(
            f"QComboBox {{ background: {t['inp_bg']}; color: {t['inp_fg']}; "
            f"border: 1px solid {t['inp_border']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 2px 8px; font-size: 12.5px; }"
        )
        self.method.currentIndexChanged.connect(self.refresh_setup)
        self._rule_a_fields.append(self.method)

        self.parameters: dict[str, QSpinBox] = {}
        method_rows: list[tuple[Any, QWidget]] = [("方法", self.method)]
        for key, label, low, high, default in (
            ("n_init", "初始候选", 1, 256, 16),
            ("n_iter", "迭代轮数", 0, 200, 8),
            ("q_batch", "每轮候选", 1, 8, 1),
            ("seed", "随机种子", 0, 9999, 0),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(default)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setFixedHeight(28)
            spin.setFixedWidth(_FIELD_WIDTH_DESKTOP)
            spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            spin.setStyleSheet(spin_qss)
            _enable_tnum(spin)
            spin.valueChanged.connect(self.refresh_setup)
            self.parameters[key] = spin
            self._rule_a_fields.append(spin)
            method_rows.append((label, spin))

        self._max_eval_val = QLabel("—")
        _enable_tnum(self._max_eval_val)
        self._max_eval_val.setStyleSheet(
            f"color: {t['fg']}; font-size: 12.5px; font-weight: 500; "
            "padding-left: 8px; background: transparent;"
        )
        method_rows.append(("最多评估", self._max_eval_val))

        method_sec, _ = self._make_rule_a_section("方法与预算", method_rows)
        v.addWidget(method_sec)

        self.eval_preview = QLabel()
        self.eval_preview.setWordWrap(True)
        self.eval_preview.hide()

        # Band 4: 搜索空间 (with 预览, 恢复均匀 actions)
        def _mk_bound_spin(lo: float, hi: float, val: float, step: float) -> QDoubleSpinBox:
            ds = QDoubleSpinBox()
            ds.setRange(lo, hi)
            ds.setValue(val)
            ds.setSingleStep(step)
            ds.setDecimals(2)
            ds.setSuffix(" mm")
            ds.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            ds.setFixedHeight(28)
            ds.setFixedWidth((_FIELD_WIDTH_DESKTOP - 6) // 2)
            ds.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            ds.setStyleSheet(spin_qss)
            _enable_tnum(ds)
            ds.valueChanged.connect(self.refresh_setup)
            return ds

        self.bounds = {
            "L_min": _mk_bound_spin(TRAIN_L[0], TRAIN_L[1], TRAIN_L[0], 0.5),
            "L_max": _mk_bound_spin(TRAIN_L[0], TRAIN_L[1], TRAIN_L[1], 0.5),
            "t_min": _mk_bound_spin(TRAIN_T[0], TRAIN_T[1], TRAIN_T[0], 0.05),
            "t_max": _mk_bound_spin(TRAIN_T[0], TRAIN_T[1], TRAIN_T[1], 0.05),
        }

        def _make_pair(widgets: tuple[QWidget, ...], gap: int = 6) -> QWidget:
            w = QWidget()
            w.setFixedWidth(_FIELD_WIDTH_DESKTOP)
            w.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(gap)
            for child in widgets:
                hl.addWidget(child, 1)
            self._pair_containers.append((w, widgets))
            return w

        pair_head = QWidget()
        pair_head.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        pair_head.setStyleSheet("background: transparent;")
        ph_lay = QHBoxLayout(pair_head)
        ph_lay.setContentsMargins(2, 0, 0, 0)
        ph_lay.setSpacing(6)
        for cap in ("最小", "最大"):
            lb = QLabel(cap)
            lb.setStyleSheet(
                f"color: {t['tert']}; font-size: 11px; font-weight: 500; background: transparent;"
            )
            ph_lay.addWidget(lb, 1)
        self._rule_a_fields.append(pair_head)

        self.controls: dict[str, QSpinBox] = {}
        for axis in "xyz":
            edit = QSpinBox()
            edit.setRange(1, 99)
            edit.setValue(3)
            edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            edit.setFixedHeight(28)
            edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            edit.setStyleSheet(spin_qss)
            edit.setToolTip("1 点为该轴恒定；2 点线性；更多点使用当前样条阶数。")
            _enable_tnum(edit)
            edit.valueChanged.connect(self.refresh_setup)
            self.controls[axis] = edit

        self._ctrl_row = QWidget()
        self._ctrl_row.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        self._ctrl_row.setStyleSheet("background: transparent;")
        ctrl_lay = QHBoxLayout(self._ctrl_row)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(4)
        for axis in "xyz":
            ctrl_lay.addWidget(self.controls[axis], 1)
        self._rule_a_fields.append(self._ctrl_row)

        self._ctrl_label = QLabel(f"控制点 {SYM['x']} / {SYM['y']} / {SYM['z']}")
        self._ctrl_label.setTextFormat(Qt.TextFormat.RichText)
        self._ctrl_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        self.control_z_label = self._ctrl_label

        space_sec, _ = self._make_rule_a_section(
            "搜索空间",
            [
                ("", pair_head),
                (f"胞元 {SYM['L']}", _make_pair((self.bounds["L_min"], self.bounds["L_max"]))),
                (f"壁厚 {SYM['t']}", _make_pair((self.bounds["t_min"], self.bounds["t_max"]))),
            ],
            actions=(
                ("预览", lambda: self.show_field_preview()),
                ("恢复均匀", self.clear_continuous_field),
            ),
        )
        # Insert control-points row directly so the rich-text label can switch 2D/3D cleanly.
        space_grid = self._rule_a_grids[-1]
        space_grid.addWidget(
            self._ctrl_label, 3, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        space_grid.addWidget(
            self._ctrl_row, 3, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.field_layout = QLabel()
        self.field_layout.setWordWrap(True)
        self.field_layout.setStyleSheet(
            f"color: {t['tert']}; font-size: 11px; padding: 0 16px 4px 16px; background: transparent;"
        )
        self.selected_field = QLabel()
        self.selected_field.setWordWrap(True)
        self.selected_field.setStyleSheet(
            f"color: {t['sub']}; font-size: 11px; padding: 0 16px 10px 16px; background: transparent;"
        )

        v.addWidget(space_sec)
        v.addWidget(self.field_layout)
        v.addWidget(self.selected_field)
        v.addStretch(1)

    def _rebuild_condition_table(self) -> None:
        t = get_theme()
        lay = self._cond_table_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        hdr = QFrame()
        hdr.setFixedHeight(25)
        hdr.setStyleSheet(
            f"background: {t['sunken']}; border: none; "
            f"border-top-left-radius: {RADIUS_INPUT}px; border-top-right-radius: {RADIUS_INPUT}px;"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(4)
        nm_h = QLabel("名称")
        nm_h.setStyleSheet(
            f"color: {t['sub']}; font-size: 11px; font-weight: 600; background: transparent;"
        )
        hl.addWidget(nm_h, 1)
        for ch in (f"{SYM['m_A']} [kg/s]", f"{SYM['m_B']} [kg/s]"):
            lb = QLabel(ch)
            lb.setTextFormat(Qt.TextFormat.RichText)
            lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lb.setFixedWidth(74)
            lb.setStyleSheet(
                f"color: {t['sub']}; font-size: 11px; font-weight: 600; background: transparent;"
            )
            hl.addWidget(lb)
        lay.addWidget(hdr)

        rows_data: list[tuple[str, float | None, float | None]] = []
        if self.conditions:
            for row in self.conditions:
                cid = "当前工况" if row["condition_id"] == "current" else str(row["condition_id"])
                rows_data.append(
                    (cid, row.get("mass_flow_A_kg_s"), row.get("mass_flow_B_kg_s"))
                )
        elif isinstance(self.report, dict) and self.report.get("conditions"):
            for row in self.report["conditions"]:
                cid = "当前工况" if row.get("condition_id") == "current" else str(row.get("condition_id", "—"))
                rows_data.append(
                    (cid, row.get("mass_flow_A_kg_s"), row.get("mass_flow_B_kg_s"))
                )
        else:
            form = self._form
            is_3d = form.combo_dim.currentIndex() == 1
            mf_a = mf_b = None
            if is_3d:
                if hasattr(form, "combo_inlet_modeA") and form.combo_inlet_modeA.currentIndex() == 1:
                    try:
                        mf_a = float(form.le_mass_flowA.text())
                    except ValueError:
                        mf_a = None
                if hasattr(form, "combo_inlet_modeB") and form.combo_inlet_modeB.currentIndex() == 1:
                    try:
                        mf_b = float(form.le_mass_flowB.text())
                    except ValueError:
                        mf_b = None
            rows_data.append(("当前工况", mf_a, mf_b))

        self._cond_header.set_count(len(rows_data))
        for cid, ma, mb in rows_data:
            lay.addWidget(_Hairline())
            rw = QWidget()
            rw.setFixedHeight(26)
            rw.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(10, 0, 10, 0)
            rl.setSpacing(4)
            nl = QLabel(cid)
            nl.setStyleSheet(
                f"color: {t['fg']}; font-size: 12px; font-weight: 500; background: transparent;"
            )
            rl.addWidget(nl, 1)
            for val in (ma, mb):
                txt = f"{val:.4f}" if isinstance(val, (int, float)) and isfinite(val) else "—"
                vl = QLabel(txt)
                _enable_tnum(vl)
                vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                vl.setFixedWidth(74)
                vl.setStyleSheet(
                    f"color: {t['fg']}; font-size: 12px; font-weight: 400; background: transparent;"
                )
                rl.addWidget(vl)
            lay.addWidget(rw)

    def _on_result_pill_changed(self, idx: int) -> None:
        self.result_tabs.setCurrentIndex(idx)

    def _on_result_tab_changed(self, idx: int) -> None:
        self._result_pill.set_current_index(idx, emit=False)
        self.show_field_volume()

    def capture_case(self):
        config = config_from_window(self._form, strict=True)
        if config.is_3d:
            return config
        depth = study.positive_number(self.depth.text(), "2D total-flow depth [m]")
        return replace(config, geometry=replace(config.geometry, Lz_m=depth))

    def field_spec(self):
        from scipy.stats import qmc
        from sjtu_tpmshx.physical_models.continuous_field import decision_bounds, decision_dim

        widgets = self.bounds
        controls = self.controls
        spec = dict(
            n_ctrl_x=controls["x"].value(),
            n_ctrl_y=controls["y"].value(),
            symmetric_y=False,
            spline_order=2,
            L_bounds=[widgets["L_min"].value(), widgets["L_max"].value()],
            t_bounds=[widgets["t_min"].value(), widgets["t_max"].value()],
        )
        if self._form.combo_dim.currentIndex() == 1:
            spec["n_ctrl_z"] = controls["z"].value()
        count = decision_dim(
            spec["n_ctrl_x"], spec["n_ctrl_y"], False, n_ctrl_z=spec.get("n_ctrl_z")
        )
        if count > qmc.Sobol.MAXDIM:
            raise ValueError(
                f"当前控制点包含 {count} 个变量；优化初始化最多支持 {qmc.Sobol.MAXDIM} 个"
            )
        low, high = decision_bounds(
            spec["n_ctrl_x"],
            spec["n_ctrl_y"],
            False,
            spec["L_bounds"],
            spec["t_bounds"],
            n_ctrl_z=spec.get("n_ctrl_z"),
        )
        ZoneInputConfig(
            enabled=True, axis="continuous", config={**spec, "x_decision": ((low + high) / 2).tolist()}
        ).validate()
        return spec

    def import_conditions(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "导入优化工况表", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as source:
                payload = json.load(source)
                rows = study.validate_condition_table(payload)
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f"工况导入失败：{exc}")
            return
        self.conditions = rows
        self.mass_requirements = deepcopy(payload.get("mass_requirements"))
        if self.mass_requirements is not None:
            self.method.setCurrentIndex(self.method.findData("qlognei"))
        elif self.method.currentData() == "qlognei":
            self.method.setCurrentIndex(self.method.findData("qlognehvi"))
        self.refresh_setup()
        self.status.setText(f"已导入 {len(rows)} 个工况：{Path(path).name}")

    def use_current_condition(self):
        self.conditions = None
        self.mass_requirements = None
        if self.method.currentData() == "qlognei":
            self.method.setCurrentIndex(self.method.findData("qlognehvi"))
        self.refresh_setup()

    def capture_study(self):
        state: dict[str, Any] = {}
        if self.conditions is not None:
            state["optimization_conditions"] = deepcopy(self.conditions)
        if self.mass_requirements is not None:
            state["optimization_mass_requirements"] = deepcopy(self.mass_requirements)
        state["optimization_controls"] = {
            axis: edit.value() for axis, edit in self.controls.items()
        }
        state["optimization_bounds"] = {
            name: [self.bounds[name + "_" + end].value() for end in ("min", "max")]
            for name in ("L", "t")
        }
        return state

    def restore_study(self, preset, *, partial=False):
        self.conditions = deepcopy(preset.get("optimization_conditions"))
        self.mass_requirements = deepcopy(preset.get("optimization_mass_requirements"))
        if self.mass_requirements is not None:
            if not partial or self.method.currentData() not in ("qlognei", "sobol"):
                self.method.setCurrentIndex(self.method.findData("qlognei"))
        elif self.method.currentData() == "qlognei":
            self.method.setCurrentIndex(self.method.findData("qlognehvi"))
        controls = preset.get("optimization_controls", {})
        for axis, edit in self.controls.items():
            edit.setValue(controls.get(axis, 3))
        bounds = preset.get("optimization_bounds", {"L": TRAIN_L, "t": TRAIN_T})
        for name in ("L", "t"):
            for end, value in zip(("min", "max"), bounds[name]):
                self.bounds[name + "_" + end].setValue(value)
        self.refresh_setup()

    def edit_common_settings(self):
        form = self._form
        if form.appearance.is_focused():
            form.appearance.toggle_focus()
        form.workbench.switch_tab("layout")
        if not form.appearance.is_drawer_open():
            form.appearance.set_drawer_open(True)
        form.inspector_drawer.setFocus()

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
        raw_lengths = [form.le_L.text(), form.le_H.text()]
        grids = [form.le_Nx.text(), form.le_Ny.text()]
        if is_3d:
            raw_lengths.append(form.le_Lz.text())
            grids.append(form.le_Nz.text())

        mm_parts: list[str] = []
        for s in raw_lengths:
            try:
                v = float(s) * 1e3
                mm_parts.append(f"{v:g}" if isfinite(v) else "—")
            except (TypeError, ValueError):
                mm_parts.append("—")
        dim_tag = "3D" if is_3d else "2D"
        self._pub_topo_val.setText(form.combo_tpms.currentText() or "—")
        self._pub_dom_val.setText(f"{f' {TIMES} '.join(mm_parts)} mm · {dim_tag}")
        self._pub_fluid_val.setText(
            f"{form.combo_fluidA.currentText()} / {form.combo_fluidB.currentText()}"
        )
        self.public_summary.setText(
            f"公共工况 · {form.combo_tpms.currentText()} · "
            f"{form.combo_fluidA.currentText()} / {form.combo_fluidB.currentText()}\n"
            f"计算域 {' × '.join(raw_lengths)} m · 网格 {' × '.join(grids)} · 材料、端口与求解设置沿用当前算例"
        )

        self.depth.setVisible(not is_3d)
        self.depth_label.setVisible(not is_3d)
        self.controls["z"].setVisible(is_3d)
        self._ctrl_label.setText(
            f"控制点 {SYM['x']} / {SYM['y']} / {SYM['z']}"
            if is_3d
            else f"控制点 {SYM['x']} / {SYM['y']}"
        )

        counts = [self.controls[a].value() for a in ("xyz" if is_3d else "xy")]
        fields = sum(
            self.bounds[name + "_min"].value() != self.bounds[name + "_max"].value()
            for name in ("L", "t")
        )
        self.field_layout.setText(
            " × ".join(map(str, counts))
            + f" · {fields * int(np.prod(counts))} 个变量 · "
            + ("XYZ" if is_3d else "XY")
            + " 连续场"
        )

        rows, requirements = self.conditions, self.mass_requirements
        n = len(rows) if rows else 1
        obj_mode = "mass_requirements" if requirements else "mean"
        obj_word = format_objective_summary(n, obj_mode)
        self._objective_val.setText(obj_word)
        self.condition_summary.setText(
            f"目标：{obj_word} · " + "、".join(row["condition_id"] for row in rows)
            if rows
            else f"目标：{obj_word} · 窗口输入；总流量按实际入口速度分布与孔隙率积分换算"
        )
        self._rebuild_condition_table()

        params = self.parameters
        budget = params["n_init"].value() + params["n_iter"].value() * params["q_batch"].value()
        max_eval = (budget + 1) * n
        self._max_eval_val.setText(f"{max_eval} 次")
        objective = (
            f"目标：芯体质量最小；所有工况满足换热与两侧压降要求\n"
            f"实体密度 {requirements['solid_density_kg_m3']:g} kg/m³\n"
            if requirements
            else "目标：平均换热增益最大，相对压降最小\n"
        )
        if requirements and requirements.get("allow_nu_re_extrapolation"):
            objective += "本任务允许 Nu-Re 外推；结果保留超范围记录\n"
        self.eval_preview.setText(
            objective
            + f"{budget} 个候选 + 1 个均匀基准，最多 {max_eval} 次 {'3D' if is_3d else '2D'} 工况求解"
        )

        spec = form._continuous_field_spec
        self.selected_field.setText(
            "当前计算使用完整 " + ("XYZ" if "n_ctrl_z" in spec else "XY") + " 连续场"
            if spec
            else "当前计算未加载优化连续场"
        )
        form.zone_table.setEnabled(spec is None)
        form.combo_zone_axis.setEnabled(spec is None)
        self.fit_requested.emit()

    def is_idle(self) -> bool:
        return self._job is None and not self._launching

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.resume_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.pause_button.setEnabled(busy)
        self.activity_changed.emit()
        self._notify_shell()

    def set_stage(self, key: str, state: str) -> None:
        if state == "active":
            self.stack.setCurrentIndex({"config": 0, "running": 1, "result": 2}[key])

    @Slot()
    def _fit_page(self) -> None:
        if self.stack.currentIndex() == 0 and self._shell_attached:
            self._form.appearance.select_drawer_tab("opt", 0)
        self.fit_requested.emit()
        QTimer.singleShot(0, self, self.fit_requested.emit)

    def _set_kpi(self, *, gen, best_q, best_dp, eta) -> None:
        self.kpi_gen.setText(str(gen))
        self.kpi_q.setText(f"{best_q:.3g}" if isinstance(best_q, (int, float)) else str(best_q))
        self.kpi_dp.setText(f"{best_dp:.4g}" if isinstance(best_dp, (int, float)) else str(best_dp))
        self.kpi_eta.setText(str(eta))

    def _capture_input(self):
        return study.OptimizationInput(
            self.capture_case(),
            self.conditions,
            self.field_spec(),
            self.method.currentData(),
            **{key: edit.value() for key, edit in self.parameters.items()},
            mass_requirements=self.mass_requirements,
        ).validate()

    @Slot()
    def start(self, *, resume_file=None):
        if self._form._close_pending or not self.is_idle():
            return
        self._launching = True
        self._set_busy(True)
        try:
            inputs = (
                self._capture_input()
                if resume_file is None
                else study.OptimizationInput.from_checkpoint(resume_file)
            )
            if self._form._close_pending:
                return
            name = f'{inputs.method}_{time.strftime("%Y%m%d_%H%M%S")}_{time.time_ns() % 1000000:06d}'
            output_dir = optimization_output_dir() / name
            self._job = OptimizationJob(
                inputs, output_dir, self._form.run_control, self._terminal, self
            )
            self._job.progress.connect(self._progress)
            self._job.updated.connect(self._update)
            self._job.settled.connect(self._settled)
            self._stop_requested = self._pause_requested = False
            self._last_drawn = -1
            self._live_update = None
            self.live_details.setText("正在准备工况；首次提案完成后可估算剩余时间。")
            self.live_details.setToolTip("")
            self.sparkline.clear_data()
            self._set_kpi(gen="starting", best_q="—", best_dp="—", eta="—")
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            self.set_stage("config", "done")
            self.set_stage("running", "active")
            self.set_stage("result", "idle")
            self.summary_banner.hide()
            self._status_kind = "run"
            self._status_short = "搜索中…"
            self.status.setText(
                f"{inputs.method} · {len(inputs.rows) if inputs.rows else 1} 个工况 · "
                f"{'3D' if inputs.config.is_3d else '2D'}"
            )
            self._job.start()
        except Exception as exc:
            if self._job is not None:
                self._job.deleteLater()
                self._job = None
            self._status_kind = "err"
            self._status_short = "启动失败"
            self.status.setText(f"启动失败：{exc}")
            self.set_stage("running", "idle")
            self.set_stage("config", "active")
        else:
            self._live_timer.start()
        finally:
            self._launching = False
            if self.is_idle():
                self._set_busy(False)
            else:
                self._notify_shell()

    def cancel(self):
        if self._job is not None:
            self._stop_requested = True
            self._job.requestInterruption()
            self._status_kind = "warn"
            self._status_short = "正在取消"
            self.status.setText("正在取消；等待当前数值步骤结束并保存记录")
            self._notify_shell()

    def pause(self):
        if self._job is not None:
            self._pause_requested = True
            self._job.request_pause()
            self.pause_button.setEnabled(False)
            self._status_kind = "warn"
            self._status_short = "正在暂停"
            self.status.setText("正在暂停；等待保存原生检查点和搜索记录")
            self._notify_shell()

    def resume(self):
        from PySide6.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "继续已有优化任务",
            str(optimization_output_dir()),
            "Optimization checkpoint (optimization.json)",
        )
        if filename:
            self.start(resume_file=filename)

    @Slot(int)
    def _progress(self, percent: int) -> None:
        if not self._form._close_pending:
            self.progress_bar.setValue(percent)
            self.sparkline.push(percent)

    @Slot(object)
    def _update(self, state) -> None:
        if self._form._close_pending:
            return
        report = state["report"]
        self.last_output_dir = self._job.output_dir
        if self._live_update is None:
            self.show_pareto(report, running=True)
            self._last_drawn = report["n_usable"]
        self._live_update = (state, time.monotonic())
        self.show_live_update(state)

    def _draw_live(self) -> None:
        if self._form._close_pending or self._live_update is None:
            return
        state, received = self._live_update
        report = state["report"]
        if report["status"] != "running":
            return
        delta = time.monotonic() - received
        eta = state["eta_s"]
        self.show_live_update(
            {
                **state,
                "elapsed_s": state["elapsed_s"] + delta,
                "eta_s": max(0.0, eta - delta) if eta is not None else None,
            }
        )
        if report["n_usable"] != self._last_drawn:
            self.show_pareto(report, running=True)
            self._last_drawn = report["n_usable"]

    def _terminal(self, report, error: str) -> None:
        self._live_timer.stop()
        if self._form._close_pending:
            return
        directory = self._job.output_dir
        if error and self._live_update is not None:
            published = self._live_update[0]["report"]
            if published["status"] != "running":
                report = published
        if report is not None:
            self.last_output_dir = directory
            self.show_pareto(report)
            detail = f" · {error}" if error else ""
            self.status.setText(f"{self.summary_banner.text()}{detail} · {directory}")
        else:
            label = "ERROR" if error else "已取消"
            text = (
                f"ERROR: {error} · 输出目录：{directory}"
                if error
                else "已取消 · 工况准备结束，尚未启动优化搜索"
            )
            self._status_kind = "err" if error else "warn"
            self._status_short = "运行失败" if error else "已取消"
            self.status.setText(text)
            self._set_kpi(gen=label, best_q="—", best_dp="—", eta="—")
            self.set_stage("running", "idle")
            self.set_stage("config", "active")
            self._notify_shell()

    @Slot()
    def _settled(self) -> None:
        self._job = None
        self._set_busy(False)

    def _objective_kpis(self, report, rows):
        constrained = "mass_requirements" in report
        captions = (
            ("最小合格芯体质量 [kg]", "满足全部约束的候选数")
            if constrained
            else ("最大换热提升 [%]", "最小相对压降 [1]")
        )
        if constrained and report["mass_requirements"].get("allow_nu_re_extrapolation"):
            captions = ("最小达标芯体质量 [kg]（允许 Nu-Re 外推）", captions[1])
        self.kpi_q_caption.setText(captions[0])
        self.kpi_dp_caption.setText(captions[1])
        if constrained:
            feasible = [row for row in rows if row.get("feasible") is True]
            return dict(
                best_q=min((row["objectives"]["core_mass_kg"] for row in feasible), default="—"),
                best_dp=report["n_feasible"],
            )
        return dict(
            best_q=max((row["objectives"]["heat_gain_percent"] for row in rows), default="—"),
            best_dp=min((row["objectives"]["pressure_ratio"] for row in rows), default="—"),
        )

    def show_live_update(self, update):
        """Show recorded state without changing the active workflow page."""
        report = update["report"]
        self.report = report
        stages = {
            "baseline": "均匀基准",
            "initial": "初始候选",
            "model_fit": "拟合模型",
            "proposal": "选择候选",
            "evaluation": "候选计算",
            "finished": "搜索结束",
        }
        stage = stages[report["stage"]]
        active = next((row for row in report["history"] if row["status"] == "running"), None)
        if active is not None:
            stage += f' {active["index"] + 1}/{report["design_budget"]}'
        if report["status"] != "running":
            stage = _termination_label(report)
        elif self._stop_requested:
            stage = "取消请求已收到；等待安全停止点 · " + stage
        elif self._pause_requested:
            stage = "暂停请求已收到；等待保存检查点 · " + stage
        self.status.setText(stage)
        usable = [row for row in report["history"] if row["status"] == "completed"]
        failed = [row for row in report["history"] if row["status"] == "failed"]
        eta = update["eta_s"]
        self._set_kpi(
            gen=f'{report["n_evaluated"]}/{report["design_budget"]}',
            **self._objective_kpis(report, usable),
            eta=f"≈{eta / 60:.1f} min" if eta is not None else "采样中",
        )
        phases = {
            "input": "等待准备",
            "prepare": "前处理",
            "save_case": "保存输入",
            "comparison": "核对基准",
            "solve": "原生求解",
            "validate_result": "核对结果",
            "postprocess": "后处理",
            "save_result": "保存结果",
            "qualification": "资格检查",
            "reuse": "读取已有结果",
            None: "等待",
        }
        states = {
            "completed": "合格",
            "failed": "失败",
            "cancelled": "已取消",
            "paused": "已暂停",
            "not_run": "等待",
        }
        conditions = update["conditions"]
        priority = {
            "running": 0,
            "computed": 0,
            "failed": 1,
            "cancelled": 1,
            "paused": 1,
            "not_run": 2,
            "completed": 3,
        }
        visible = sorted(conditions, key=lambda row: priority[row["status"]])[:4]
        lines = [
            f'已评估 {report["n_evaluated"]}/{report["design_budget"]} · '
            f'数值合格 {len(usable)} · 失败 {len(failed)} · Pareto {len(report["pareto_indices"])}',
            f'已用时 {update["elapsed_s"] / 60:.1f} min · 时间估算依据已完成的工况批次与提案',
        ]
        lines.extend(
            f'{row["condition_id"]}：' + states.get(row["status"], phases.get(row["stage"], row["stage"]))
            for row in visible
        )
        if len(conditions) > 4:
            lines.append(f"另有 {len(conditions) - 4} 个工况")
        reasons = [row["reason"] for row in (*failed, *conditions) if row.get("reason")]
        if report.get("baseline", {}).get("reason"):
            reasons.append(report["baseline"]["reason"])
        if report.get("reason"):
            reasons.append(report["reason"])
        reasons = list(dict.fromkeys(reasons))
        lines.extend(reason[:240] for reason in reasons[-2:])
        self.live_details.setText("\n".join(lines))
        self.live_details.setToolTip("\n".join(reasons))
        self.fit_requested.emit()
        self._notify_shell()

    def export_pareto_data(self):
        """Save the archived plot data without re-evaluating a design."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from sjtu_tpmshx.applications.optimization.pareto_io import export_pareto_data as export

        report = self.report
        if report is None:
            self.status.setText("没有可导出的优化结果。")
            return
        default = Path(self.last_output_dir or ".") / "pareto_data.xlsx"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出 Pareto 数据", str(default), "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in (".csv", ".xlsx"):
            target = target.with_suffix(".csv" if "CSV" in selected_filter else ".xlsx")
        try:
            counts = export(report, target)
        except (KeyError, TypeError, ValueError, OSError, ImportError) as error:
            _log.exception("Could not export Pareto data")
            QMessageBox.warning(self, "Pareto 导出失败", str(error))
            return
        self.status.setText(
            f'已导出 {counts["n_usable"]} 个有效点，{counts["n_pareto"]} 个前沿点：{target}'
        )

    def export_geometry(self):
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QLabel,
            QMessageBox,
            QSpinBox,
        )
        from sjtu_tpmshx.applications.optimization.export_ntop_csv import (
            MAX_EXPORT_POINTS,
            export_study_design,
        )

        report = self.report
        index = self.selected_index
        if report is None or index is None:
            self.status.setText("请先在 Pareto 图中选择一个方案。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("导出所选方案的建模坐标")
        layout = QFormLayout(dialog)
        layout.addRow(QLabel("各轴采样包含边界；单点取中面。坐标、L 和 t 均为 mm。"))
        counts = []
        for axis, default in zip("xyz"[: report["dimension"]], (100, 50, 25)):
            edit = QSpinBox(dialog)
            edit.setRange(1, 999)
            edit.setValue(default)
            counts.append(edit)
            layout.addRow(f"{axis.upper()} 采样点", edit)
        size = QLabel()
        layout.addRow(size)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addRow(buttons)

        def update_size():
            count = int(np.prod([edit.value() for edit in counts]))
            size.setText(
                f"{count:,} 个采样点 · 上限 {MAX_EXPORT_POINTS:,} · "
                f"工作数组估算 {count * 128 / 1e6:.1f} MB"
            )
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(
                count <= MAX_EXPORT_POINTS
            )

        for edit in counts:
            edit.valueChanged.connect(update_size)
        update_size()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target = QFileDialog.getExistingDirectory(self, "选择建模文件导出目录")
        if not target:
            return
        try:
            summary = export_study_design(
                report, index, target, tuple(edit.value() for edit in counts)
            )
        except (ValueError, TypeError, KeyError, OSError) as error:
            QMessageBox.warning(self, "建模坐标导出失败", str(error))
            return
        self.status.setText(
            f'已导出方案 {report["history"][index]["index"]}：{summary["csv_geometry"]}'
        )

    def pareto_ready(self) -> bool:
        return bool(self._plot_indices)

    def field_ready(self) -> bool:
        return sum(bool(axis.images) for axis in self.field_canvas.figure.axes) == 2

    def volume_ready(self) -> bool:
        return (
            self._volume_ready
            and self.volume_panel is not None
            and self.volume_panel._volume_actor is not None
        )

    def _clear_preview(self) -> None:
        self.field_canvas.figure.clear()
        self.volume_data = None
        self._volume_ready = False
        self.result_tabs.setTabEnabled(1, False)
        self.result_tabs.setTabEnabled(2, False)
        self._result_pill.set_tab_enabled(1, False)
        self._result_pill.set_tab_enabled(2, False)
        if self.volume_panel is not None:
            self.volume_panel.hide()

    def _disconnect_pick(self) -> None:
        if self._pick_id is not None:
            try:
                self.pareto_view.point_picked.disconnect(self._on_pareto_point_picked)
            except (RuntimeError, TypeError):
                pass
            self._pick_id = None

    def _is_uniform_baseline(self, row: dict[str, Any], *, constrained: bool) -> bool:
        if row.get("is_baseline") is True:
            return True
        if constrained:
            return False
        obj = row.get("objectives") or {}
        pr = obj.get("pressure_ratio")
        hg = obj.get("heat_gain_percent")
        return (
            row.get("index") == 0
            and isinstance(pr, (int, float))
            and isinstance(hg, (int, float))
            and abs(float(pr) - 1.0) <= 1e-9
            and abs(float(hg)) <= 1e-9
        )

    def _build_selected_panel_data(
        self,
        report: dict[str, Any],
        history_pos: int,
        *,
        l_range: tuple[float, float] | None = None,
        t_range: tuple[float, float] | None = None,
    ) -> SelectedDesignData:
        history = report["history"]
        row = history[history_pos]
        obj = row.get("objectives") or {}
        constrained = "mass_requirements" in report
        pareto_set = set(report.get("pareto_indices") or ())
        on_front = history_pos in pareto_set
        is_3d = report.get("dimension") == 3
        plane_suffix = f"（{SYM['z']} 中面）" if is_3d else ""

        if constrained:
            from sjtu_tpmshx.applications.optimization.mass_design import constraint_keys

            keys = constraint_keys(report["mass_requirements"])
            vals = [obj[k] for k in keys if k in obj and isinstance(obj[k], (int, float))]
            res_pct = 100.0 * max(vals) if vals else None
            mass = obj.get("core_mass_kg")
            objectives = (
                ObjectiveCell(
                    "芯体质量",
                    val_unit(f"{mass:.3f}", "kg") if isinstance(mass, (int, float)) else "—",
                    tone="fg",
                ),
                ObjectiveCell(
                    "最大约束残差",
                    val_unit(signed(res_pct, "+.2f"), "%") if res_pct is not None else "—",
                    tone="ok" if (res_pct is not None and res_pct <= 0) else "warn",
                ),
            )
            front_title = "可行方案"
            front_sort = "质量 ↑"
            tag = "最轻可行" if on_front else ("可行" if row.get("feasible") else "未达标")
            mass_constraint_text = "逐项达标" if row.get("feasible") else "未达标"
        else:
            hg = obj.get("heat_gain_percent")
            pr = obj.get("pressure_ratio")
            objectives = (
                ObjectiveCell(
                    "平均有效换热提升",
                    val_unit(signed(hg, "+.3f"), "%") if isinstance(hg, (int, float)) else "—",
                    tone="ok" if (isinstance(hg, (int, float)) and hg > 0) else "fg",
                ),
                ObjectiveCell(
                    "平均相对压降",
                    f"{pr:.4f}" if isinstance(pr, (int, float)) else "—",
                    tone="fg",
                ),
            )
            front_title = "前沿方案"
            front_sort = "压降比 ↑"
            tag = "Pareto 前沿" if on_front else ""
            mass_constraint_text = "未设置"

        status_val = "数值合格" if row.get("status") == "completed" else str(row.get("status", "—"))
        status_kind = "ok" if row.get("status") == "completed" else "warn"
        phase_raw = row.get("phase")
        phase_val = _PHASE_LABELS.get(str(phase_raw), str(phase_raw)) if phase_raw else "—"
        l_text = rng(f"{l_range[0]:.2f}", f"{l_range[1]:.2f}", "mm") if l_range is not None else "—"
        t_text = rng(f"{t_range[0]:.3f}", f"{t_range[1]:.3f}", "mm") if t_range is not None else "—"

        spec_rows = (
            SpecRow("状态", status_val, status_kind=status_kind),
            SpecRow("阶段", phase_val),
            SpecRow(f"胞元 {SYM['L']}{plane_suffix}", l_text),
            SpecRow(f"壁厚 {SYM['t']}{plane_suffix}", t_text),
            SpecRow("质量约束", mass_constraint_text),
        )

        front_items: list[FrontListItem] = []
        for idx in self._plot_indices:
            h_row = history[idx]
            h_obj = h_row.get("objectives") or {}
            h_id = h_row.get("index", idx)
            if constrained:
                from sjtu_tpmshx.applications.optimization.mass_design import constraint_keys

                keys = constraint_keys(report["mass_requirements"])
                m_val = float(h_obj.get("core_mass_kg", 0.0))
                r_pct = 100.0 * max(float(h_obj[k]) for k in keys if k in h_obj)
                front_items.append(
                    FrontListItem(
                        index=h_id,
                        primary_value=m_val,
                        primary_text=f"{m_val:.3f}",
                        secondary_text=val_unit(signed(r_pct, "+.2f"), "%"),
                        secondary_tone="ok" if r_pct <= 0 else "sub",
                    )
                )
            else:
                pr_v = float(h_obj.get("pressure_ratio", 0.0))
                hg_v = float(h_obj.get("heat_gain_percent", 0.0))
                front_items.append(
                    FrontListItem(
                        index=h_id,
                        primary_value=pr_v,
                        primary_text=f"{pr_v:.4f}",
                        secondary_text=val_unit(signed(hg_v, "+.3f"), "%"),
                        secondary_tone="ok" if hg_v > 0 else "sub",
                    )
                )

        cond_cells = tuple(
            ConditionCell(
                condition_id=(
                    "当前工况" if c.get("condition_id") == "current" else str(c.get("condition_id", "—"))
                ),
                mass_flow_a_kg_s=c.get("mass_flow_A_kg_s"),
                mass_flow_b_kg_s=c.get("mass_flow_B_kg_s"),
            )
            for c in (report.get("conditions") or ())
        )
        can_load = on_front and row.get("status") == "completed"
        return SelectedDesignData(
            index=row.get("index", history_pos),
            objectives=objectives,
            spec_rows=spec_rows,
            front_items=tuple(front_items),
            conditions=cond_cells,
            tag=tag,
            front_title=front_title,
            front_sort_label=front_sort,
            objective_mode="mass_requirements" if constrained else "mean",
            can_load=can_load,
            can_export=row.get("status") == "completed",
        )

    def _populate_failed_card(self, baseline: dict[str, Any]) -> list[str]:
        try:
            details = study.baseline_failure_details(baseline, self.last_output_dir)
            reasons = study.baseline_failure_reasons(baseline, self.last_output_dir)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            details = {
                "condition": "—",
                "stage": "均匀基准",
                "checks": [],
                "reasons": [baseline.get("reason") or "", f"工况归档读取失败：{exc}"],
            }
            reasons = [r for r in details["reasons"] if r]

        self._fail_cond_val.setText(details["condition"])
        self._fail_stage_val.setText(details["stage"])
        if details["checks"]:
            html_items = [
                text.replace("Re", SYM["Re"]).replace("Nu", SYM["Nu"])
                for text in details["checks"]
            ]
            self._fail_reason_val.setText("；".join(html_items))
        elif details["reasons"]:
            self._fail_reason_val.setText("；".join(details["reasons"]))
        else:
            self._fail_reason_val.setText("—")
        self._fail_open_dir_btn.setEnabled(
            self._form.dialogs.resolve_output_directory(scope="optimization") is not None
        )
        return reasons

    def show_pareto(self, report, *, running: bool = False):
        self.report = report
        self.selected_index = None
        self.load_button.setEnabled(False)
        self.export_geometry_button.setEnabled(False)
        self.selected_panel.set_data(None)
        self._clear_preview()
        self._disconnect_pick()
        self.result_tabs.setCurrentWidget(self.pareto_canvas)
        self._result_pill.set_current_index(0, emit=False)

        history = report["history"]
        usable = [row for row in history if row["status"] == "completed"]
        constrained = "mass_requirements" in report
        if constrained:
            from sjtu_tpmshx.applications.optimization.mass_design import constraint_keys

            keys = constraint_keys(report["mass_requirements"])

            def x_value(row):
                return 100.0 * max(row["objectives"][key] for key in keys)

            y_key = "core_mass_kg"
            plot_mode = "mass"
        else:
            def x_value(row):
                return row["objectives"]["pressure_ratio"]

            y_key = "heat_gain_percent"
            plot_mode = "heat_pressure"

        pareto_set = set(report["pareto_indices"])
        indices = sorted(report["pareto_indices"], key=lambda i: x_value(history[i]))
        rows = [history[i] for i in indices]

        baseline = report.get("baseline")
        baseline_failed = isinstance(baseline, dict) and baseline.get("status") == "failed"

        points: list[ParetoPoint] = []
        for pos, row in enumerate(history):
            if row.get("status") != "completed":
                continue
            is_base = self._is_uniform_baseline(row, constrained=constrained)
            points.append(
                ParetoPoint(
                    index=row.get("index", pos),
                    x=float(x_value(row)),
                    y=float(row["objectives"][y_key]),
                    phase=str(row.get("phase") or "initial"),
                    on_front=(pos in pareto_set),
                    is_baseline=is_base,
                    feasible=bool(row.get("feasible", True)),
                )
            )

        title_note = ""
        if constrained and report["mass_requirements"].get("allow_nu_re_extrapolation"):
            title_note = "允许 Nu-Re 外推"

        render_error = None
        if baseline_failed and not running:
            self._plot_indices = []
            self.pareto_view.clear()
            self._result_body_stack.setCurrentWidget(self._failed_card_host)
        else:
            self._result_body_stack.setCurrentWidget(self.result_tabs)
            try:
                self.pareto_view.apply_theme(get_theme())
                self.pareto_view.set_data(
                    points,
                    selected_index=None,
                    mode=plot_mode,
                    interactive=bool(rows) and not running,
                    title_note=title_note,
                    draw_now=True,
                )
                self.pareto_canvas.show()
                self._plot_indices = indices
                if rows and not running:
                    self.pareto_view.point_picked.connect(self._on_pareto_point_picked)
                    self._pick_id = True
            except Exception as exc:
                _log.exception("Could not render optimization Pareto figure")
                render_error = f"{type(exc).__name__}: {exc}"
                self._plot_indices = []
                self._disconnect_pick()
                self.pareto_canvas.figure.clear()
                self.pareto_canvas.hide()

        self.export_pareto_button.setEnabled(bool(usable) and not running)
        self.figures_changed.emit()
        if running:
            return render_error

        label = _termination_label(report)
        self._set_kpi(gen=label, **self._objective_kpis(report, rows), eta="—")
        self.set_stage("running", "idle" if report["status"] == "failed" else "done")
        self.set_stage("result", "active")

        if baseline_failed:
            reasons = self._populate_failed_card(baseline)
            summary = "均匀基准失败" + "".join(f" · {r}" for r in reasons if r)
            self._status_kind = "err"
            self._status_short = "失败 · 均匀基准未通过"
            if self._shell_attached:
                self._form.appearance.select_drawer_tab("opt", 0, open_drawer=True)
        else:
            selection = (
                f'{report["n_feasible"]} 个满足全部约束，{len(rows)} 个最轻方案'
                if constrained
                else f"{len(rows)} 个 Pareto 方案"
            )
            summary = f'{label} · {selection} · {report["n_usable"]}/{report["n_evaluated"]} 个候选数值合格'
            if report["status"] == "completed":
                self._status_kind = "ok"
                self._status_short = "完成"
            elif report["status"] in ("cancelled", "paused"):
                self._status_kind = "warn"
                self._status_short = label
            else:
                self._status_kind = "err"
                self._status_short = label

        if report.get("reason"):
            summary += f' · {report["reason"]}'
        if render_error:
            summary += f" · Pareto 绘图失败：{render_error}"
        self.summary_banner.setText(summary)
        self.status.setText(summary)
        self._rebuild_condition_table()
        self.fit_requested.emit()
        self._notify_shell()
        return render_error

    def _history_pos_for_id(self, design_id: int) -> int | None:
        if not isinstance(self.report, dict):
            return None
        history = self.report.get("history") or []
        for pos, row in enumerate(history):
            if row.get("index") == design_id:
                return pos
        if 0 <= design_id < len(history):
            return design_id
        return None

    def _on_pareto_point_picked(self, design_id: int) -> None:
        self.select_design(design_id)

    def select_design(self, design_id: int) -> None:
        """Select and preview one design without modifying the active case (decision 7)."""
        if not isinstance(self.report, dict):
            return
        pos = self._history_pos_for_id(design_id)
        if pos is None:
            return
        row = self.report["history"][pos]
        if row.get("status") != "completed":
            return
        self.selected_index = pos
        on_front = pos in set(self.report.get("pareto_indices") or ())
        self.load_button.setEnabled(on_front)
        self.export_geometry_button.setEnabled(True)
        self.pareto_view.set_selected_index(row.get("index", pos))

        l_range, t_range = self._preview_selected_design(row.get("x_decision"))
        self.selected_panel.set_data(
            self._build_selected_panel_data(self.report, pos, l_range=l_range, t_range=t_range)
        )
        if self._shell_attached:
            self._form.appearance.select_drawer_tab("opt", 1, open_drawer=True)
        self._notify_shell()

    def _preview_selected_design(
        self, x_decision
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        """Render the 2D/3D field preview in the background without leaving Pareto."""
        if x_decision is None:
            return None, None
        return self.show_field_preview(x_decision, switch_to_field=False)

    def load_selected(self):
        form = self._form
        try:
            current = config_from_window(form, strict=True)
            config = study.archived_design(
                self.report, self.selected_index, self.last_output_dir, current
            )
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            self.status.setText(f"连续场载入失败：{exc}")
            return
        row = self.report["conditions"][0]
        form._continuous_field_spec = config.zones.config
        form._pareto_x_decision = None
        form.chk_zones.setChecked(True)
        for side in "AB":
            fluid = getattr(config, f"fluid_{side}")
            if config.is_3d:
                getattr(form, "le_mass_flow" + side).setText(
                    format(row[f"mass_flow_{side}_kg_s"], ".17g")
                )
                getattr(form, "combo_inlet_mode" + side).setCurrentIndex(1)
            form._set_temp_K(getattr(form, f"le_Tin{side}"), fluid.T_in_K)
            getattr(form, f"le_Pin{side}").setText(format(fluid.P_in_Pa, ".17g"))
            getattr(form, f"le_u{side}").setText(format(fluid.u_mps, ".17g"))
        form.case_files.invalidate_results_for_preset_load()
        form.case_files.resync_undo_baseline()
        self.refresh_setup()
        self.status.setText(
            f'已载入完整 {"XYZ" if config.is_3d else "XY"} 连续场 · '
            f'工况 {row["condition_id"]} · 总质量流量保持不变'
        )
        form.dialogs.notify(
            f'已载入方案 #{self.report["history"][self.selected_index]["index"]} 到算例计算',
            kind="success",
            duration_ms=3500,
        )

    @Slot()
    def show_field_preview(self, x_decision=None, *, switch_to_field: bool = True):
        from matplotlib.ticker import MaxNLocator
        from sjtu_tpmshx.physical_models.continuous_field import (
            decision_bounds,
            from_decision_vector,
        )

        try:
            current_spec = self._form._continuous_field_spec
            if x_decision is None and current_spec is not None and self._form.chk_zones.isChecked():
                cfg = config_from_window(self._form, strict=True).validate()
                spec = deepcopy(current_spec)
                x_decision = spec.pop("x_decision")
            elif x_decision is None:
                cfg, spec = self.capture_case().validate(), self.field_spec()
                low, high = decision_bounds(
                    spec["n_ctrl_x"],
                    spec["n_ctrl_y"],
                    spec["symmetric_y"],
                    spec["L_bounds"],
                    spec["t_bounds"],
                    n_ctrl_z=spec.get("n_ctrl_z"),
                )
                x_decision = (low + high) / 2
            else:
                cfg = ComputeConfig.from_dict(self.report["conditions"][0]["config"])
                spec = self.report["field_spec"]
            geom = cfg.geometry
            field = from_decision_vector(
                x_decision,
                geom.tpms,
                geom.k_s_W_mK,
                geom.L_dom_m,
                geom.H_dom_m,
                **spec,
                **({"Lz_domain": geom.Lz_m} if "n_ctrl_z" in spec else {}),
            )
            volume = None
            if "n_ctrl_z" in spec:
                # An odd sample count puts the center plane at half the physical depth.
                L_volume, t_volume = field.evaluate_volume(80, 40, 41)
                volume = dict(
                    L_mm=L_volume,
                    t_mm=t_volume,
                    dx=np.full(80, geom.L_dom_m / 80),
                    dy=np.full(40, geom.H_dom_m / 40),
                    dz=np.full(41, geom.Lz_m / 41),
                    flow_dir=None,
                )
                L, t_arr = L_volume[:, :, 20], t_volume[:, :, 20]
                suffix = f" · z = {geom.Lz_m * 500:g} mm"
            else:
                L, t_arr = field.evaluate_grid(80, 40)
                suffix = ""
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            self._clear_preview()
            self.figures_changed.emit()
            self.status.setText(f"连续场预览失败：{exc}")
            return None, None

        l_range = (float(np.min(L)), float(np.max(L)))
        t_range = (float(np.min(t_arr)), float(np.max(t_arr)))

        canvas = self.field_canvas
        fig = canvas.figure
        fig.clear()
        theme = get_theme()
        fig.set_facecolor(theme["fig_bg"])
        axes = fig.subplots(2, 1, sharex=True)
        for ax, (name, values) in zip(axes, (("L", L), ("t", t_arr))):
            ax.set_facecolor(theme["ax_bg"])
            im = ax.imshow(
                values.T,
                origin="lower",
                aspect="equal",
                cmap=resolve_cmap(f"{name}_mm"),
                vmin=spec[f"{name}_bounds"][0],
                vmax=spec[f"{name}_bounds"][1],
                extent=[0, geom.L_dom_m * 1e3, 0, geom.H_dom_m * 1e3],
            )
            ax.set_title(f"{name}(x,y){suffix}", color=theme["ax_text"], fontsize=11, loc="left")
            ax.set_ylabel("y [mm]", color=theme["ax_text"])
            ax.tick_params(colors=theme["ax_text"], labelsize=9, length=3)
            for spine in ax.spines.values():
                spine.set_edgecolor(theme["ax_spine"])
            cb = fig.colorbar(
                im,
                ax=ax,
                orientation="vertical",
                fraction=0.025,
                pad=0.025,
                aspect=25,
                ticks=MaxNLocator(nbins=4, steps=[1, 2, 5, 10]),
                format="%g",
            )
            cb.set_label(f"{name} [mm]", color=theme["ax_text"], fontsize=9)
            cb.ax.tick_params(colors=theme["ax_text"], labelsize=8, length=2)
            cb.outline.set_visible(False)
        axes[-1].set_xlabel("x [mm]", color=theme["ax_text"])
        canvas.axes = [[ax] for ax in axes]
        self.volume_data = volume
        self._volume_ready = False
        self.result_tabs.setTabEnabled(2, volume is not None)
        self.result_tabs.setTabEnabled(1, True)
        self._result_pill.set_tab_enabled(2, volume is not None)
        self._result_pill.set_tab_enabled(1, True)
        if switch_to_field:
            self._result_body_stack.setCurrentWidget(self.result_tabs)
            self.result_tabs.setCurrentWidget(canvas)
            self._result_pill.set_current_index(1, emit=False)
            self.set_stage("result", "active")
            self._form.workbench.switch_tab("pareto")
        canvas.draw_idle()
        self.figures_changed.emit()
        return l_range, t_range

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
            if (
                self._form._close_pending
                or self.result_tabs.currentWidget() is not self.volume_host
                or self.volume_data is None
            ):
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
                raise RuntimeError("未能生成三维体图，请检查显示设备或重新打开预览")
            self._volume_ready = True
            placeholder.hide()
            panel.show()
        except Exception as exc:
            _log.exception("Could not render optimization volume")
            placeholder.setText(f"三维连续场显示失败：{exc}")
        finally:
            self._volume_loading = False
            self.figures_changed.emit()

    def restore_volume_ranges(self, ranges):
        self._volume_ranges = deepcopy(ranges)
        if self.volume_panel is not None:
            self.volume_panel.restore_color_ranges(ranges)


def _termination_label(report):
    label = {
        "completed": "完成",
        "cancelled": "已取消",
        "paused": "已暂停",
        "failed": "失败",
    }.get(report["status"], "运行中")
    if report["status"] == "completed" and report.get("stop_reason") == "mass_lower_bound":
        label += "：达到模型质量下界"
    if report.get("mass_requirements", {}).get("allow_nu_re_extrapolation"):
        label += "（本任务允许 Nu-Re 外推）"
    return label
