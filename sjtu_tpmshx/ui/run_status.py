"""Compact, expandable view of the existing compute callbacks."""
from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)

from .fmt import duration
from .icons import icon
from .responsive import ResponsiveRow
from .sparkline import Sparkline
from .theme import RADIUS_CARD, get_theme


class RunStatusCard(QFrame):
    cancel_requested = Signal()
    log_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("runStatusCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.state = "idle"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        header = ResponsiveRow(threshold=480, spacing=8)
        summary = QWidget()
        summary_row = QHBoxLayout(summary)
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        self.title = QLabel("准备计算")
        self.title.setObjectName("runStatusTitle")
        self.elapsed = QLabel("设置工况后开始")
        self.elapsed.setObjectName("runStatusElapsed")
        self.elapsed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        summary_row.addWidget(self.title)
        summary_row.addWidget(self.elapsed, 1)
        header.addWidget(summary)
        actions = QWidget()
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addStretch(1)
        self.log_button = QPushButton("计算日志")
        self.log_button.clicked.connect(self.log_requested)
        self.log_button.hide()
        action_row.addWidget(self.log_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()
        action_row.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.toggle = QToolButton()
        self.toggle.setText("详情")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.toggle.setAccessibleName("展开计算详情")
        self.toggle.setToolTip("展开迭代与残差")
        action_row.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(actions)
        layout.addWidget(header)

        self.details = QWidget()
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)
        self.iteration = QLabel("尚未开始")
        self.iteration.setWordWrap(True)
        detail_layout.addWidget(self.iteration)
        self.trails = {}
        self.residual_labels = {}
        residual_row = QHBoxLayout()
        residual_row.setSpacing(18)
        for side in ("A", "B"):
            column = QVBoxLayout()
            label = QLabel(f"流体 {side} · 等待残差")
            label.setWordWrap(True)
            trail = Sparkline(height=44)
            trail.setFixedHeight(44)
            trail.setToolTip(f"流体 {side} 残差趋势 · 纵轴为 log₁₀ · 最近 500 个样本")
            column.addWidget(label)
            column.addWidget(trail)
            residual_row.addLayout(column, 1)
            self.residual_labels[side] = label
            self.trails[side] = trail
        detail_layout.addLayout(residual_row)
        self.note = QLabel("迭代和残差由求解器发布；完整日志在计算结束后提供。")
        self.note.setWordWrap(True)
        detail_layout.addWidget(self.note)
        self.details.hide()
        layout.addWidget(self.details)
        self.toggle.toggled.connect(self._set_expanded)
        self.set_theme()

    def _set_expanded(self, expanded):
        reveal_details = expanded and self.details.isHidden() and self.isVisible()
        self.details.setVisible(expanded)
        self.toggle.setIcon(icon('chevron-up' if expanded else 'chevron-down', get_theme()['sub_fg']))
        self.toggle.setAccessibleName("收起计算详情" if expanded else "展开计算详情")
        self.toggle.setToolTip("收起计算详情" if expanded else "展开迭代与残差")
        if reveal_details:
            from .microanim import reveal
            reveal(self.details)

    def set_theme(self, theme=None):
        t = theme or get_theme()
        self.setStyleSheet(
            "QWidget { background:transparent; }"
            f"QFrame#runStatusCard {{ background:{t['card_bg']}; "
            f"border:1px solid {t['card_border']}; border-radius:{RADIUS_CARD}px; }}"
            f"QLabel {{ color:{t['sub_fg']}; border:0; background:transparent; font-size:10pt; }}"
            f"QLabel#runStatusTitle {{ color:{t['fg']}; font-weight:600; }}"
            f"QPushButton, QToolButton {{ color:{t['fg']}; background:transparent; "
            "border:1px solid transparent; border-radius:6px; padding:3px 8px; font-size:10pt; }"
            f"QPushButton:hover, QToolButton:hover {{ background:{t['surface_elevated']}; "
            f"border-color:{t['border_subtle']}; }}"
            f"QPushButton:disabled {{ color:{t['sub_fg']}; }}"
        )
        self._set_title_color(t)
        for button, name in ((self.log_button, 'file-text'), (self.cancel_button, 'square'),
                             (self.toggle, 'chevron-up' if self.toggle.isChecked() else 'chevron-down')):
            button.setFixedHeight(32)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.setIcon(icon(name, t['sub_fg']))
            button.setIconSize(QSize(14, 14) if button is self.toggle else QSize(16, 16))
        for trail in self.trails.values():
            trail.update()

    def _set_title_color(self, theme=None):
        t = theme or get_theme()
        color = t['err_soft'] if self.state in ('error', 'unconverged') else (
            t['warn'] if self.state == 'warning' else (
                t['accent_green'] if self.state == 'success' else t['fg']))
        self.title.setStyleSheet(f"color:{color}; font-weight:600;")

    def start(self, mode):
        self.state = "running"
        self.title.setText(f"{mode.upper()} 计算中")
        self.set_elapsed(0)
        self.iteration.setText("等待求解器迭代信息")
        self.note.setText("迭代和残差由求解器发布；完整日志在计算结束后提供。")
        for side, trail in self.trails.items():
            trail.clear_data()
            self.residual_labels[side].setText(f"流体 {side} · 等待残差")
        self.log_button.hide()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self._set_title_color()
        self.show()

    def set_elapsed(self, seconds):
        self.elapsed.setText(f"已用时 {duration(max(0., seconds))}")

    def set_iteration(self, label):
        self.iteration.setText(str(label) if label else "等待求解器迭代信息")

    def push_residuals(self, side, samples):
        """Consume actual solver samples, retaining the existing bounded sparkline."""
        for index, residual in samples:
            if not math.isfinite(residual) or residual < 0:
                continue
            self.trails[side].push(math.log10(max(residual, 1e-20)))
            self.residual_labels[side].setText(
                f"流体 {side} · 迭代 {index} · 残差 {residual:.2e}")

    def request_cancel(self):
        self.state = "cancelling"
        self.title.setText("正在取消")
        self.cancel_button.setEnabled(False)
        self.note.setText("等待求解器完成当前计算步。")

    def finish(self, state, elapsed, *, log_available=False, message=""):
        self.state = state
        self.title.setText({"success": "计算完成", "warning": "完成 · 有提示",
                            "unconverged": "完成 · 未收敛", "error": "计算未完成",
                            "cancelled": "已取消"}[state])
        self.set_elapsed(elapsed)
        self.cancel_button.hide()
        self.log_button.setVisible(log_available)
        self.note.setText(message or ("可展开查看本次迭代与残差。" if state == 'success'
                                     else "本次计算已结束。"))
        if self.iteration.text().startswith("等待"):
            self.iteration.setText("本次未发布迭代信息")
        for side, trail in self.trails.items():
            if not trail._data:
                self.residual_labels[side].setText(f"流体 {side} · 本次未发布实时残差")
        self._set_title_color()
