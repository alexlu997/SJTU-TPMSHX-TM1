"""Quick Design page, Rule A input drawer, ranked dot plot, peek card, and result tables."""
from __future__ import annotations

from math import ceil, isfinite
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.model_configs.df_domain import TRAIN_L_NODES, TRAIN_T_NODES

from .colormap_popover import ToggleSwitch
from .design_peek import (
    DesignPeekCard,
    ObjectiveCell,
    PeekDesignData,
    SelectedQuickDesignData,
    SelectedQuickDesignPanel,
    SpecRow,
)
from .field_factory import UnitLineEdit
from .icons import icon
from .inspector_drawer import BandHeader
from .quick_design_job import QuickDesignJob
from .readout_strip import ReadoutItem, ReadoutNotice
from .symbols import ENDASH, NB_THIN, SYM, TIMES, val_unit
from .theme import RADIUS_BTN, RADIUS_INPUT, get_theme
from .volume_dp_view import CasePressureLimit, VolumeDpDesign, VolumeDpView

_FIELD_WIDTH_DESKTOP = 168
_FIELD_WIDTH_COMPACT = 150

_ENERGY_COLUMNS = [
    "构型",
    "算例",
    "热侧 Q [W]",
    "冷侧 Q [W]",
    "能量不平衡 [%]",
    "诊断状态",
    "诊断原因",
    "数值收敛",
    "构型可行",
    "终验原因",
]

_ENERGY_STATUS_LABELS: dict[str, str] = {
    "available": "可用",
    "insufficient_data": "数据不足",
    "unavailable": "不可用",
}

_QD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("拓扑", "拓扑", "l"),
    (f"{SYM['L']} [mm]", "L [mm]", "r"),
    (f"{SYM['t']} [mm]", "t [mm]", "r"),
    (f"{SYM['W_H']} [mm]", f"W {TIMES} H [mm]", "r"),
    (f"{SYM['L_x']} [mm]", "Lx [mm]", "r"),
    ("体积 [L]", "体积 [L]", "r"),
    ("重量 [kg]", "重量 [kg]", "r"),
    ("热侧压损 [%]", "热侧压损 [%]", "r"),
    ("冷侧压损 [%]", "冷侧压损 [%]", "r"),
    (f"{SYM['Re']} 热", "Re 热", "r"),
    (f"{SYM['Re']} 冷", "Re 冷", "r"),
    ("验证域", "验证域", "l"),
    ("标签", "标签", "l"),
)

_TAG_LABELS: dict[str, str] = {
    "min-V": "最小体积",
    "min-wt": "最轻",
    "min-dP": "最小压损",
}


def _flist(text: str) -> list[float]:
    return [float(value) for value in text.replace("|", ",").split(",") if value.strip()]


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


def _fmt_num(value: Any, fmt: str) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if not isfinite(num):
        return "—"
    return format(num, fmt)


def _format_tag_chip(raw_tag: str) -> str:
    prefix = "已完成候选内 "
    if raw_tag.startswith(prefix):
        inner = raw_tag[len(prefix):]
        return prefix + _TAG_LABELS.get(inner, inner)
    return _TAG_LABELS.get(raw_tag, raw_tag)


class RichHeaderView(QHeaderView):
    """Render ISO 80000-1 italic and subscripted rich-text table headers."""

    def __init__(self, cols: tuple[tuple[str, str, str], ...], parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._cols = cols
        self.setHighlightSections(False)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignVCenter)

    def _make_doc(self, html: str, align_ch: str) -> QTextDocument:
        theme = get_theme()
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        doc.setDefaultFont(font)
        opt = doc.defaultTextOption()
        opt.setAlignment(
            Qt.AlignmentFlag.AlignRight if align_ch == "r" else Qt.AlignmentFlag.AlignLeft
        )
        doc.setDefaultTextOption(opt)
        align = "right" if align_ch == "r" else "left"
        doc.setHtml(
            f'<div align="{align}" style="color:{theme["sub"]}; font-size:11.5px; '
            f'font-weight:600; white-space:nowrap;">{html}</div>'
        )
        return doc

    def rich_width_hint(self, idx: int) -> int:
        html, _, align_ch = self._cols[idx]
        doc = self._make_doc(html, align_ch)
        return int(ceil(doc.idealWidth())) + 18

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        theme = get_theme()
        painter.save()
        painter.fillRect(rect, QColor(theme["sunken"]))
        painter.setPen(QPen(QColor(theme["border"]), 0.5))
        painter.drawLine(
            QPointF(float(rect.left()), float(rect.bottom()) - 0.25),
            QPointF(float(rect.right()), float(rect.bottom()) - 0.25),
        )
        if 0 <= logicalIndex < len(self._cols):
            html, _, align_ch = self._cols[logicalIndex]
            doc = self._make_doc(html, align_ch)
            pad = 8
            doc.setTextWidth(max(12.0, float(rect.width() - 2 * pad)))
            dy = (rect.height() - doc.size().height()) / 2.0
            painter.translate(rect.left() + pad, rect.top() + dy)
            doc.drawContents(painter)
        painter.restore()


class _QdTableDelegate(QStyledItemDelegate):
    """Paint crisp row hairlines, validity dots, and tag pill chips for the 13-column table."""

    def paint(self, painter: QPainter, option, index) -> None:
        theme = get_theme()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        col = index.column()
        rect = option.rect

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected:
            painter.fillRect(rect, QColor(theme["accent_soft"]))
        else:
            painter.fillRect(rect, QColor(theme["canvas"]))

        painter.setPen(QPen(QColor(theme["border"]), 0.5))
        painter.drawLine(
            QPointF(float(rect.left()), float(rect.bottom()) - 0.25),
            QPointF(float(rect.right()), float(rect.bottom()) - 0.25),
        )

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if col == 11:
            is_ok = text == "域内"
            x = float(rect.left() + 8)
            cy = float(rect.center().y()) + 0.5
            painter.setPen(Qt.PenStyle.NoPen)
            if is_ok:
                painter.setBrush(QColor(theme["ok"]))
                painter.drawEllipse(QPointF(x + 3.25, cy), 3.1, 3.1)
            else:
                painter.setBrush(QColor(theme["warn"]))
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(x + 3.5, cy - 3.2),
                            QPointF(x + 6.8, cy + 2.8),
                            QPointF(x + 0.2, cy + 2.8),
                        ]
                    )
                )
            text_rect = QRect(rect.left() + 20, rect.top(), max(0, rect.width() - 26), rect.height())
            font = QFont(option.font)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(theme["fg"] if is_ok else theme["warn"]))
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
            painter.restore()
            return

        if col == 12:
            raw_tags = [part.strip() for part in text.split(",") if part.strip()]
            x = float(rect.left() + 8)
            font = QFont(option.font)
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
            painter.setFont(font)
            fm = QFontMetrics(font)
            chip_h = 20.0
            cy_top = rect.top() + (rect.height() - chip_h) / 2.0
            for raw_tag in raw_tags:
                label = _format_tag_chip(raw_tag)
                chip_w = float(fm.horizontalAdvance(label) + 12)
                if x + chip_w > rect.right() - 4:
                    break
                chip_rect = QRectF(x, cy_top, chip_w, chip_h)
                bg = theme["accent_soft"] if selected else theme["sunken"]
                fg = theme["accent_fg"] if selected else theme["sub"]
                painter.setBrush(QColor(bg))
                painter.setPen(QPen(QColor(theme["border"]), 0.5))
                painter.drawRoundedRect(chip_rect, 5.0, 5.0)
                painter.setPen(QColor(fg))
                painter.drawText(chip_rect, int(Qt.AlignmentFlag.AlignCenter), label)
                x += chip_w + 5.0
            painter.restore()
            return

        align = (
            Qt.AlignmentFlag.AlignRight
            if _QD_COLUMNS[col][2] == "r"
            else Qt.AlignmentFlag.AlignLeft
        )
        text_rect = rect.adjusted(8, 0, -8, 0)
        font = QFont(option.font)
        font.setFeature(QFont.Tag("tnum"), 1)
        if selected and col == 0:
            font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        fg_brush = index.data(Qt.ItemDataRole.ForegroundRole)
        if fg_brush is not None:
            painter.setPen(fg_brush.color())
        else:
            painter.setPen(QColor(theme["fg"]))
        painter.drawText(text_rect, int(align | Qt.AlignmentFlag.AlignVCenter), text)
        painter.restore()


class _PillIsland(QFrame):
    """Floating top-left segmented view switcher styled in Style P2."""

    current_changed = Signal(int)

    def __init__(self, labels: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels = labels
        self._current = 0
        self._buttons: list[QPushButton] = []
        self.setObjectName("qdPillIsland")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(0)

        self._track = QFrame()
        self._track.setObjectName("qdPillTrack")
        tl = QHBoxLayout(self._track)
        tl.setContentsMargins(2, 2, 2, 2)
        tl.setSpacing(2)

        for idx, text in enumerate(labels):
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, i=idx: self.set_current_index(i, emit=True))
            self._buttons.append(btn)
            tl.addWidget(btn)
        outer.addWidget(self._track)
        self.apply_theme()

    def current_index(self) -> int:
        return self._current

    def set_current_index(self, index: int, *, emit: bool = False) -> None:
        clamped = max(0, min(int(index), len(self._buttons) - 1))
        changed = clamped != self._current
        self._current = clamped
        self.apply_theme()
        if emit and changed:
            self.current_changed.emit(clamped)

    def apply_theme(self) -> None:
        t = get_theme()
        self.setStyleSheet(
            f"QFrame#qdPillIsland {{ background: {t['popover']}; "
            f"border: 1px solid {t['border']}; border-radius: {RADIUS_BTN}px; }}"
        )
        self._track.setStyleSheet(
            f"QFrame#qdPillTrack {{ background: {t['sunken']}; border: none; "
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
        )
        for idx, btn in enumerate(self._buttons):
            btn.setStyleSheet(on_qss if idx == self._current else off_qss)


class _SegmentedChoice(QFrame):
    """Style P2 segmented selector holding ``(label, backend_value)`` pairs directly."""

    value_changed = Signal(str)

    def __init__(
        self,
        items: Sequence[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._values: list[str] = [val for _, val in items]
        self._buttons: list[QPushButton] = []
        self._current = 0
        self.setObjectName("qdSegRow")
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        for idx, (cap, _val) in enumerate(items):
            btn = QPushButton(cap)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, i=idx: self.set_current_index(i))
            self._buttons.append(btn)
            lay.addWidget(btn, 1)
        self._apply_style()

    def current_index(self) -> int:
        return self._current

    def current_value(self) -> str:
        return self._values[self._current]

    def set_value(self, value: str) -> None:
        idx = self._values.index(value)
        self.set_current_index(idx)

    def set_current_index(self, index: int) -> None:
        if not 0 <= index < len(self._values):
            raise IndexError(index)
        changed = index != self._current
        self._current = index
        self._apply_style()
        if changed:
            self.value_changed.emit(self._values[self._current])

    def set_label(self, index: int, text: str) -> None:
        """Update display text without changing the backend value."""
        self._buttons[index].setText(text)

    def _apply_style(self) -> None:
        t = get_theme()
        self.setStyleSheet(
            f"QFrame#qdSegRow {{ background: {t['sunken']}; border: none; "
            f"border-radius: {RADIUS_INPUT}px; }}"
        )
        on_qss = (
            f"QPushButton {{ background: {t['seg_on']}; color: {t['fg']}; "
            f"border: 1px solid {t['border']}; border-radius: 5px; "
            "padding: 0 6px; font-size: 12px; font-weight: 600; }"
        )
        off_qss = (
            f"QPushButton {{ background: transparent; color: {t['sub']}; "
            "border: none; border-radius: 5px; padding: 0 6px; "
            "font-size: 12px; font-weight: 400; }"
            f"QPushButton:hover {{ color: {t['fg']}; }}"
        )
        for idx, btn in enumerate(self._buttons):
            btn.setStyleSheet(on_qss if idx == self._current else off_qss)


class _PlotWithPeek(QWidget):
    """Host VolumeDpView with a floating bottom-left DesignPeekCard."""

    def __init__(self, plot: VolumeDpView, peek: DesignPeekCard, parent: QWidget | None = None):
        super().__init__(parent)
        self._plot = plot
        self._peek = peek
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(plot, 1)
        peek.setParent(self)
        peek.raise_()

    def position_peek(self) -> None:
        self._peek.adjustSize()
        h = self.height()
        ph = self._peek.height()
        self._peek.move(4, max(4, h - ph - 4))
        self._peek.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.position_peek()


class QuickDesignPage(QWidget):
    """Keep the current design job, feasible table, ranked dot plot, and drawers."""

    activity_changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._worker = None
        self.last_result = None
        self._feasible_rows: list[Any] = []
        self._feasible_tags: dict[int, list[str]] = {}
        self._selected_row: int | None = None
        self._drawer_open = False
        self._compact = False
        self._shell_attached = False
        self._status_kind = "idle"
        self._status_short = "就绪"
        self._action_notice: ReadoutNotice | None = None
        self._rule_a_grids: list[QGridLayout] = []
        self._rule_a_fields: list[QWidget] = []
        self.setWindowTitle("快速设计工具")
        self.setMinimumSize(640, 520)
        self._build_controls()

    def is_idle(self) -> bool:
        return self._worker is None

    def drawer_tabs(self) -> tuple[tuple[str, QWidget], ...]:
        """Return ``(title, body_widget)`` pairs mounted into the shell InspectorDrawer."""
        return (
            ("输入", self._input_drawer_body),
            ("所选设计", self._selected_drawer_body),
        )

    def header_widgets(self) -> tuple[QWidget, QWidget, QWidget, QWidget]:
        """Return ``(status_badge, export_btn, cancel_btn, run_btn)`` for workbenchHeader."""
        return (
            self._qd_status_badge,
            self._qd_export_btn,
            self._qd_cancel_btn,
            self._qd_run_btn,
        )

    def attach_to_shell(self) -> None:
        """Mark the page as hosted inside the Style P2 Main_Menu shell."""
        self._shell_attached = True
        self._qd_status.hide()
        self._sync_peek_visibility()

    def status_badge_spec(self) -> tuple[str, str]:
        """Return ``(kind, label)`` for the workbench header status pill."""
        return self._status_kind, self._status_short

    def readout_spec(self) -> tuple[list[ReadoutItem], ReadoutNotice | None]:
        """Return bottom ReadoutStrip items and optional notice."""
        res = self.last_result
        if res is None:
            return [], self._action_notice
        feasible = res.get("feasible") or []
        best = res.get("best")
        elapsed = res.get("elapsed_s")

        if best is not None and getattr(best, "V", None) is not None and isfinite(best.V):
            min_v_text = f"{best.V * 1e3:.3f}"
            min_v_unit = "L"
        else:
            min_v_text = "—"
            min_v_unit = ""

        weights = [
            float(d.weight)
            for d in feasible
            if getattr(d, "weight", None) is not None and isfinite(d.weight)
        ]
        if weights:
            min_wt_text = f"{min(weights):.3f}"
            min_wt_unit = "kg"
        else:
            min_wt_text = "—"
            min_wt_unit = ""

        if isinstance(elapsed, (int, float)) and isfinite(elapsed):
            elapsed_text = f"{elapsed:.0f}" if elapsed >= 10.0 else f"{elapsed:.1f}"
            elapsed_unit = "s"
        else:
            elapsed_text = "—"
            elapsed_unit = ""

        items = [
            ReadoutItem("可行设计", str(len(feasible))),
            ReadoutItem(f"最小体积 {SYM['V']}", min_v_text, min_v_unit),
            ReadoutItem("最轻", min_wt_text, min_wt_unit),
            ReadoutItem("用时", elapsed_text, elapsed_unit),
        ]
        notice = self._action_notice
        if notice is None and res.get("partial"):
            reason = res.get("termination_reason")
            title = "失败中止" if reason == "failed" else "已取消"
            notice = ReadoutNotice(title, "部分结果，不代表完整搜索最优", kind="warn")
        return items, notice

    def select_view_tab(self, index: int) -> None:
        """Switch between Feasible Table (0), Volume-dP Dot Plot (1), and Energy Diagnostics (2)."""
        clamped = max(0, min(int(index), 2))
        self._view_pill.set_current_index(clamped, emit=False)
        self._view_stack.setCurrentIndex(clamped)
        if clamped == 0:
            QTimer.singleShot(0, self, self._balance_table_columns)
        elif clamped == 1:
            self._sync_peek_visibility()

    def on_drawer_visibility_changed(self, opened: bool) -> None:
        """Hide the floating peek card when the drawer is open; show it when closed."""
        self._drawer_open = bool(opened)
        self._sync_peek_visibility()

    def set_compact(self, compact: bool) -> None:
        """Adjust Rule A input column width for compact viewports."""
        compact = bool(compact)
        if self._compact == compact:
            return
        self._compact = compact
        width = _FIELD_WIDTH_COMPACT if compact else _FIELD_WIDTH_DESKTOP
        for grid in self._rule_a_grids:
            grid.setColumnMinimumWidth(1, width)
        for widget in self._rule_a_fields:
            widget.setFixedWidth(width)
        self.selected_panel.set_compact(compact)

    def _notify_shell(self) -> None:
        if not self._shell_attached:
            return
        from .builders_sidebar import refresh_header_status, update_result_sidebar_visibility

        refresh_header_status(self._window)
        update_result_sidebar_visibility(self._window)
        refresh_nav = getattr(self._window, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()

    def _set_status(self, full_text: str, *, kind: str, short_text: str) -> None:
        self._qd_status.setText(full_text)
        self._qd_status_badge.setToolTip(full_text)
        self._status_kind = kind
        self._status_short = short_text
        if kind in ("err", "warn"):
            self._action_notice = ReadoutNotice(short_text, full_text, kind=kind)
            if self._shell_attached:
                self._window.dialogs.notify(
                    full_text, kind="error" if kind == "err" else "warn"
                )
        else:
            self._action_notice = None
        self._notify_shell()

    def _sync_export_enabled(self) -> None:
        self._qd_export_btn.setEnabled(
            bool(self.last_result is not None and self.last_result.get("all"))
        )

    @Slot()
    def submit(self):
        if self._window._close_pending:
            return
        if not self.is_idle():
            if self._qd_cancel_btn.isEnabled():
                self._set_status("设计运行中…", kind="run", short_text="运行中")
            return
        try:
            params = self._gather_inputs()
        except (ValueError, TypeError) as error:
            self._set_status(f"输入解析失败: {error}", kind="err", short_text="输入错误")
            return
        if not params["file"]:
            self._set_status("请先选择算例文件", kind="warn", short_text="待选算例")
            return

        worker = QuickDesignJob(params, control=self._window.run_control)
        worker.finished_with_result.connect(self._show_result, Qt.ConnectionType.QueuedConnection)
        worker.error_signal.connect(self._show_error, Qt.ConnectionType.QueuedConnection)
        worker.settled.connect(self._release_worker)
        self._worker = worker
        self.last_result = None
        self._sync_export_enabled()
        self._feasible_rows = []
        self._feasible_tags = {}
        self._selected_row = None
        self._qd_table.setRowCount(0)
        self._qd_energy_table.setRowCount(0)
        self.volume_dp_view.clear()
        self.peek_card.set_design(None)
        self.selected_panel.set_data(None)
        self._qd_run_btn.setEnabled(False)
        self._qd_cancel_btn.setEnabled(True)
        execution = "单进程串行（桌面包）" if worker.n_jobs == 1 else "并行候选"
        if params["mode"] == "fixed":
            execution = "单候选定尺"
        self._set_status(
            f"运行中 · {params['mode']} · {params['arrangement']} · {execution} …",
            kind="run",
            short_text="运行中…",
        )
        worker.start()
        self.activity_changed.emit()

    @Slot()
    def cancel(self):
        if self._worker is not None:
            self._worker.requestInterruption()
            if self._qd_cancel_btn.isEnabled():
                self._qd_cancel_btn.setEnabled(False)
                self._set_status(
                    "正在取消 · 等待当前候选批次或计算步结束…",
                    kind="warn",
                    short_text="正在取消",
                )

    @Slot(object)
    def _show_result(self, result):
        self._qd_cancel_btn.setEnabled(False)
        self.last_result = result
        self._sync_export_enabled()
        feasible, best = result["feasible"], result["best"]
        self._fill_table(feasible, partial=result["partial"])
        self._fill_energy_table(result["all"])
        self._populate_volume_dp(result)
        if result["partial"]:
            state = "失败中止" if result["termination_reason"] == "failed" else "已取消"
            text = (
                f"{state} · 保留 {len(result['all'])} 个已完成候选，"
                f"其中 {len(feasible)} 个可行 · 部分结果，不代表完整搜索最优"
            )
            kind = "err" if result["termination_reason"] == "failed" else "warn"
            short_text = f"{state} · 部分结果"
        elif not feasible:
            text = "无可行件 (≤450mm)"
            kind = "warn"
            short_text = "无可行设计"
        else:
            description = f"{best.topo} l={best.l:g} t={best.t:g} V={best.V * 1e3:.3f}L"
            text = f"完成 · {len(feasible)} 可行 · min-V: {description}"
            kind = "ok"
            short_text = "完成"
        self._set_status(text, kind=kind, short_text=short_text)

    @Slot(str)
    def _show_error(self, message):
        self._qd_cancel_btn.setEnabled(False)
        retained = ""
        if self.last_result is not None:
            retained = (
                f" · 保留 {len(self.last_result['all'])} 个已完成候选"
                " · 部分结果，不代表完整搜索最优"
            )
        self._set_status(f"错误: {message}{retained}", kind="err", short_text="运行失败")

    @Slot()
    def _release_worker(self):
        self._worker.deleteLater()
        self._worker = None
        self._qd_run_btn.setEnabled(True)
        self._sync_export_enabled()
        self.activity_changed.emit()
        self._notify_shell()

    def _gather_inputs(self) -> dict:
        """Read the visible controls directly from the Quick Design page."""
        def positive(attr: str, label: str, divisor: float = 1.0) -> float:
            try:
                value = float(getattr(self, attr).text()) / divisor
            except ValueError as exc:
                raise ValueError(f"{label}须为数字") from exc
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{label}必须为有限正数")
            return value

        rho_s = positive("le_qd_rho", "密度 ρ_s")
        k_s = positive("le_qd_ks", "导热系数 k_s")
        height = (
            positive("le_qd_height", "固定迎风高度 H", 1e3)
            if self.chk_qd_rect.isChecked()
            else None
        )
        mode = self.mode_selector.current_value()
        params: dict[str, Any] = {
            "file": self.le_qd_file.text(),
            "mode": mode,
            "arrangement": self.arrangement_selector.current_value(),
            "rho_s": rho_s,
            "k_s": k_s,
            "prop_model": self.prop_model_selector.current_value(),
            "height": height,
            "refine": self.chk_qd_refine.isChecked(),
        }
        if mode == "fixed":
            params["cell"] = (
                self.combo_qd_cell_topo.currentText(),
                positive("le_qd_cell_l", "固定胞元尺寸 L"),
                positive("le_qd_cell_t", "固定壁厚 t"),
            )
        else:
            topos = [name for name, cb in self.topo_checks.items() if cb.isChecked()]
            if not topos:
                raise ValueError("请至少勾选一种拓扑")
            try:
                l_vals = _flist(self.le_qd_l.text())
            except ValueError as exc:
                raise ValueError(f"胞元尺寸 L 列表格式无效: {exc}") from exc
            try:
                t_vals = _flist(self.le_qd_t.text())
            except ValueError as exc:
                raise ValueError(f"壁厚 t 列表格式无效: {exc}") from exc
            params["nodes"] = {
                "topo": topos,
                "l": l_vals,
                "t": t_vals,
            }
        return params

    def _fill_table(self, feasible, *, partial: bool = False):
        """Show feasible designs in order of increasing volume."""
        from sjtu_tpmshx.applications.design.report import warning_text
        from sjtu_tpmshx.applications.design.select import pareto_tags

        rows = sorted(feasible, key=lambda d: d.V)
        tags = pareto_tags(feasible)
        if partial:
            tags = {key: [f"已完成候选内 {tag}" for tag in value] for key, value in tags.items()}
        self._feasible_rows = rows
        self._feasible_tags = tags

        def _wh_mm(d) -> str:
            h = d.height or d.s
            w_s = _fmt_num(d.s * 1e3 if d.s is not None else None, ".0f")
            h_s = _fmt_num(h * 1e3 if h is not None else None, ".0f")
            return "—" if "—" in (w_s, h_s) else f"{w_s} {TIMES} {h_s}"

        tbl = self._qd_table
        tbl.blockSignals(True)
        tbl.setRowCount(len(rows))
        theme = get_theme()
        for i, d in enumerate(rows):
            vd = d.validity
            notices = warning_text(d)
            validity_str = ";".join(filter(None, (vd, "有警告" if notices else ""))) or "域内"
            vals = [
                str(d.topo or "—"),
                _fmt_num(d.l, "g"),
                _fmt_num(d.t, "g"),
                _wh_mm(d),
                _fmt_num(d.Lx * 1e3 if d.Lx is not None else None, ".1f"),
                _fmt_num(d.V * 1e3 if d.V is not None else None, ".3f"),
                _fmt_num(d.weight, ".3f"),
                _fmt_num(d.dP_hot_max * 100.0 if d.dP_hot_max is not None else None, ".2f"),
                _fmt_num(d.dP_cold_max * 100.0 if d.dP_cold_max is not None else None, ".2f"),
                _fmt_num(d.Re_hot_max, ".0f"),
                _fmt_num(d.Re_cold_max, ".0f"),
                validity_str,
                ",".join(tags.get(id(d), [])),
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                align = (
                    Qt.AlignmentFlag.AlignRight
                    if _QD_COLUMNS[j][2] == "r"
                    else Qt.AlignmentFlag.AlignLeft
                )
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if j == 11 and notices:
                    item.setToolTip(notices)
                if vd or notices:
                    item.setForeground(QColor(theme["warn"]))
                tbl.setItem(i, j, item)
            tbl.setRowHeight(i, 36)
        tbl.blockSignals(False)
        if rows:
            self._select_feasible_row(0)
        else:
            self._selected_row = None
            self.peek_card.set_design(None)
            self.selected_panel.set_data(None)
        QTimer.singleShot(0, self, self._balance_table_columns)

    def _populate_volume_dp(self, result: dict[str, Any]) -> None:
        rows = self._feasible_rows
        tags = self._feasible_tags
        raw_limits = result.get("case_limits") or []
        case_limits: list[CasePressureLimit] = []
        limit_by_case: dict[str, tuple[float, float]] = {}
        for entry in raw_limits:
            cid = str(entry.get("case", ""))
            h_lim = entry.get("dPlim_h")
            c_lim = entry.get("dPlim_c")
            if h_lim is not None and c_lim is not None:
                case_limits.append(
                    CasePressureLimit(
                        case_id=cid,
                        hot_limit_frac=float(h_lim),
                        cold_limit_frac=float(c_lim),
                    )
                )
                limit_by_case[cid] = (float(h_lim), float(c_lim))

        designs: list[VolumeDpDesign] = []
        for idx, d in enumerate(rows):
            hot_lim = None
            cold_lim = None
            hot_cid = ""
            cold_cid = ""
            percase = getattr(d, "percase", None) or []
            if percase and limit_by_case:
                best_h = max(percase, key=lambda pc: pc.get("dP_hot_frac", -1.0))
                best_c = max(percase, key=lambda pc: pc.get("dP_cold_frac", -1.0))
                h_key = str(best_h.get("case", ""))
                c_key = str(best_c.get("case", ""))
                if h_key in limit_by_case:
                    hot_lim = limit_by_case[h_key][0]
                    hot_cid = h_key
                if c_key in limit_by_case:
                    cold_lim = limit_by_case[c_key][1]
                    cold_cid = c_key
            designs.append(
                VolumeDpDesign(
                    index=idx,
                    topo=str(d.topo),
                    l_mm=float(d.l),
                    t_mm=float(d.t),
                    V_m3=float(d.V),
                    dP_hot_max=float(d.dP_hot_max),
                    dP_cold_max=float(d.dP_cold_max),
                    tags=tuple(tags.get(id(d), ())),
                    feasible=bool(d.feasible),
                    hot_limit_frac=hot_lim,
                    cold_limit_frac=cold_lim,
                    hot_case_id=hot_cid,
                    cold_case_id=cold_cid,
                )
            )
        partial_text = ""
        if result.get("partial"):
            state = "失败中止" if result.get("termination_reason") == "failed" else "已取消"
            partial_text = f"{state} · 部分候选，不代表完整搜索最优"
        self.volume_dp_view.set_data(
            designs,
            selected_index=self._selected_row,
            case_limits=case_limits,
            partial_text=partial_text,
        )
        self._sync_peek_visibility()

    def _select_feasible_row(self, row_idx: int) -> None:
        if not (0 <= row_idx < len(self._feasible_rows)):
            return
        self._selected_row = row_idx
        self._qd_table.blockSignals(True)
        self._qd_table.selectRow(row_idx)
        self._qd_table.blockSignals(False)
        self.volume_dp_view.set_selected_index(row_idx)

        from sjtu_tpmshx.applications.design.report import warning_text

        d = self._feasible_rows[row_idx]
        d_tags = tuple(self._feasible_tags.get(id(d), ()))
        vd = d.validity
        notices = warning_text(d)
        ok = not (vd or notices)
        validity_text = ";".join(filter(None, (vd, "有警告" if notices else ""))) or "域内"
        self.peek_card.set_design(
            PeekDesignData(
                index=row_idx,
                topo=str(d.topo),
                l_mm=float(d.l),
                t_mm=float(d.t),
                V_m3=float(d.V),
                weight_kg=float(d.weight),
                dP_hot_max=float(d.dP_hot_max),
                dP_cold_max=float(d.dP_cold_max),
                Re_hot_max=float(d.Re_hot_max),
                Re_cold_max=float(d.Re_cold_max),
                tags=d_tags,
                validity_kind="ok" if ok else "warn",
                validity_text=validity_text,
            )
        )
        h_val = d.height or d.s
        wh_text = (
            f"{d.s * 1e3:.0f} {TIMES} {h_val * 1e3:.0f}{NB_THIN}mm"
            if d.s is not None and h_val is not None and isfinite(d.s) and isfinite(h_val)
            else "—"
        )
        case_rows: list[tuple[str, str]] = []
        for pc in getattr(d, "percase", None) or []:
            cid = f"算例 {pc.get('case', '—')}"
            q_kw = _fmt_num(
                pc["Q_W"] / 1e3 if pc.get("Q_W") is not None else None,
                ".2f",
            )
            dp_h = _fmt_num(
                pc["dP_hot_frac"] * 100.0 if pc.get("dP_hot_frac") is not None else None,
                ".2f",
            )
            dp_c = _fmt_num(
                pc["dP_cold_frac"] * 100.0 if pc.get("dP_cold_frac") is not None else None,
                ".2f",
            )
            case_rows.append(
                (cid, f"Q {val_unit(q_kw, 'kW')} · 热/冷压损 {dp_h} / {dp_c}{NB_THIN}%")
            )

        self.selected_panel.set_data(
            SelectedQuickDesignData(
                title_html=(
                    f"{d.topo} · {SYM['L']} {val_unit(_fmt_num(d.l, 'g'), 'mm')} · "
                    f"{SYM['t']} {val_unit(_fmt_num(d.t, 'g'), 'mm')}"
                ),
                tags=d_tags,
                objectives=(
                    ObjectiveCell(f"芯体体积 {SYM['V']}", val_unit(_fmt_num(d.V * 1e3, ".3f"), "L")),
                    ObjectiveCell("重量", val_unit(_fmt_num(d.weight, ".3f"), "kg")),
                ),
                spec_rows=(
                    SpecRow("验证域", validity_text, status_kind="ok" if ok else "warn", tone="fg" if ok else "warn"),
                    SpecRow(f"迎风尺寸 {SYM['W_H']}", wh_text),
                    SpecRow(f"流向长度 {SYM['L_x']}", val_unit(_fmt_num(d.Lx * 1e3, ".1f"), "mm")),
                    SpecRow(
                        f"热侧压损 {SYM['dP_rel']}",
                        val_unit(_fmt_num(d.dP_hot_max * 100.0, ".2f"), "%"),
                    ),
                    SpecRow(
                        f"冷侧压损 {SYM['dP_rel']}",
                        val_unit(_fmt_num(d.dP_cold_max * 100.0, ".2f"), "%"),
                    ),
                    SpecRow(f"{SYM['Re']} 热", _fmt_num(d.Re_hot_max, ".0f")),
                    SpecRow(f"{SYM['Re']} 冷", _fmt_num(d.Re_cold_max, ".0f")),
                ),
                case_rows=tuple(case_rows),
            )
        )
        self._sync_peek_visibility()

    def _sync_peek_visibility(self) -> None:
        show_peek = (
            self._selected_row is not None
            and not self._drawer_open
            and bool(self._feasible_rows)
        )
        self.peek_card.setVisible(show_peek)
        self.volume_dp_view.set_bottom_pad(152 if show_peek else 56)
        if show_peek:
            self._plot_host.position_peek()

    def _open_selected_details(self, index: int) -> None:
        self._select_feasible_row(index)
        appearance = getattr(self._window, "appearance", None)
        if appearance is not None and hasattr(appearance, "select_drawer_tab"):
            appearance.select_drawer_tab("qd", 1, open_drawer=True)

    def _fill_energy_table(self, results):
        """Show existing final-case diagnostics for all completed candidates."""
        from sjtu_tpmshx.applications.design.report import cid

        rows = []
        for design in results:
            for pc in design.percase:
                values = [pc.get("Q_W"), pc.get("Q_cold_W"), pc.get("energy_imbalance_rel")]
                numbers = [
                    "—" if value is None else f"{value * scale:.6g}"
                    for value, scale in zip(values, (1, 1, 100))
                ]
                raw_status = pc.get("energy_imbalance_status")
                status_text = (
                    _ENERGY_STATUS_LABELS.get(str(raw_status), str(raw_status))
                    if raw_status
                    else "—"
                )
                reason_text = (
                    pc["energy_imbalance_reason"]
                    if "energy_imbalance_reason" in pc
                    else "未提供能量不平衡诊断"
                )
                conv_raw = (pc.get("run_status") or {}).get("converged")
                if conv_raw is True:
                    conv_text = "是"
                elif conv_raw is False:
                    conv_text = "否"
                else:
                    conv_text = "—"
                rows.append(
                    [
                        cid(design),
                        str(pc["case"]),
                        *numbers,
                        status_text,
                        reason_text,
                        conv_text,
                        "是" if design.feasible else "否",
                        "; ".join(pc.get("acceptance_reasons", [])),
                    ]
                )
        table = self._qd_energy_table
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(value)
                if j in (2, 3, 4):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setToolTip(value)
                table.setItem(i, j, item)
            table.setRowHeight(i, 32)

    def export(self):
        last = self.last_result
        if last is None or not last["all"]:
            self._set_status("无结果可导出", kind="warn", short_text="无结果")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出设计结果 (双 sheet)", "quick_design_results.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            if Path(path).resolve() == Path(last["params"]["file"]).resolve():
                raise ValueError("导出文件不能覆盖输入算例文件")
            from sjtu_tpmshx.applications.design.report import write_xlsx

            partial = last["partial"]
            reason = last["termination_reason"]
            n_total, n_feas, n_det = write_xlsx(
                path, last["all"], partial=partial, termination_reason=reason
            )
            state = "失败中止" if reason == "failed" else "已取消"
            msg = (
                f"{f'已导出部分结果（{state}）' if partial else '已导出'} → {path}  "
                f"(构型汇总 {n_total}/可行 {n_feas} · 算例明细 {n_det} 行)"
            )
            self._qd_status.setText(msg)
            self._qd_status_badge.setToolTip(msg)
            self._action_notice = None
            if self._shell_attached:
                self._window.dialogs.notify(msg, kind="success")
                self._notify_shell()
        except Exception as exc:
            self._set_status(f"导出失败: {exc}", kind="err", short_text="导出失败")

    def _balance_table_columns(self) -> None:
        tbl = self._qd_table
        hh = self._qd_header
        avail = tbl.viewport().width()
        if avail <= 40:
            return
        tbl.resizeColumnsToContents()
        need = [
            max(tbl.sizeHintForColumn(j) + 12, hh.rich_width_hint(j))
            for j in range(len(_QD_COLUMNS))
        ]
        need[12] = max(need[12], 148)
        free = max(0, avail - sum(need) - 2)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        extra = free // len(need)
        for j, width in enumerate(need):
            hh.resizeSection(j, width + extra)
        hh.setStretchLastSection(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._balance_table_columns()

    def _make_rule_a_section(
        self,
        title: str,
        rows: list[tuple[Any, QWidget]],
        *,
        first: bool = False,
        actions: tuple[tuple[str, Any], ...] = (),
    ) -> QWidget:
        t = get_theme()
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(BandHeader(title, first=first, collapsible=False, actions=actions, tokens=t))

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        grid = QGridLayout(body)
        grid.setContentsMargins(16, 10, 16, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(
            1, _FIELD_WIDTH_COMPACT if self._compact else _FIELD_WIDTH_DESKTOP
        )
        self._rule_a_grids.append(grid)

        for r_i, (label_or_widget, field_widget) in enumerate(rows):
            if isinstance(label_or_widget, QWidget):
                grid.addWidget(label_or_widget, r_i, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            else:
                lbl = QLabel(str(label_or_widget))
                if "<" in str(label_or_widget):
                    lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setStyleSheet(
                    f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; "
                    "background: transparent; border: none;"
                )
                grid.addWidget(lbl, r_i, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(field_widget, r_i, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        vl.addWidget(body)
        return wrap

    def _style_input(self, edit: QLineEdit) -> None:
        t = get_theme()
        edit.setFixedHeight(28)
        edit.setFixedWidth(_FIELD_WIDTH_COMPACT if self._compact else _FIELD_WIDTH_DESKTOP)
        edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        edit.setStyleSheet(
            f"QLineEdit {{ background: {t['inp_bg']}; color: {t['inp_fg']}; "
            f"border: 1px solid {t['inp_border']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 2px 8px; font-size: 12.5px; }"
            f"QLineEdit:focus {{ border: 1.5px solid {t['inp_focus']}; }}"
            f"QLineEdit:disabled {{ color: {t['tert']}; background: {t['sunken']}; "
            f"border-color: {t['border']}; }}"
        )
        self._rule_a_fields.append(edit)

    def _build_controls(self) -> None:
        from sjtu_tpmshx.applications.design import sizing

        t = get_theme()
        self.setStyleSheet(f"QuickDesignPage {{ background: {t['canvas']}; border: none; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header controls (mounted into workbenchHeader by Main_Menu) ──
        self._qd_status_badge = QPushButton("就绪", self)
        self._qd_status_badge.setFixedHeight(28)
        self._qd_status_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._qd_status_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        btn_export = QPushButton("导出 xlsx", self)
        btn_export.setFixedHeight(30)
        btn_export.setEnabled(False)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setIcon(icon("download", t["sub"]))
        btn_export.setIconSize(QSize(14, 14))
        btn_export.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_BTN}px; "
            "padding: 0 12px; font-size: 12.5px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        btn_export.clicked.connect(self.export)
        self._qd_export_btn = btn_export

        btn_cancel = QPushButton("取消", self)
        btn_cancel.setFixedHeight(30)
        btn_cancel.setEnabled(False)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background: {t['panel']}; color: {t['fg']}; "
            f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_BTN}px; "
            "padding: 0 12px; font-size: 12.5px; font-weight: 500; }"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
            f"QPushButton:disabled {{ color: {t['tert']}; }}"
        )
        btn_cancel.clicked.connect(self.cancel)
        self._qd_cancel_btn = btn_cancel

        btn_run = QPushButton("运行设计", self)
        btn_run.setFixedHeight(30)
        btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_run.setIcon(icon("play", t["primary_fg"]))
        btn_run.setIconSize(QSize(13, 13))
        btn_run.setStyleSheet(
            f"QPushButton {{ background: {t['primary_bg']}; color: {t['primary_fg']}; "
            f"border: none; border-radius: {RADIUS_BTN}px; padding: 0 14px; "
            "font-size: 12.5px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {t['primary_hover']}; }}"
            f"QPushButton:disabled {{ background: {t['border']}; color: {t['tert']}; }}"
        )
        btn_run.clicked.connect(self.submit)
        self._qd_run_btn = btn_run

        # ── Top-left pill view switcher ──
        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(14, 6, 14, 2)
        pill_row.setSpacing(8)
        self._view_pill = _PillIsland(("可行设计", f"体积{ENDASH}压降", "算例能量诊断"))
        self._view_pill.current_changed.connect(self.select_view_tab)
        pill_row.addWidget(self._view_pill)
        pill_row.addStretch(1)
        root.addLayout(pill_row)

        # ── View stack (0: 13-col table, 1: ranked dot plot + peek, 2: energy diagnostics) ──
        self._view_stack = QStackedWidget()
        self._view_stack.setStyleSheet("background: transparent;")

        # View 0: Full-width 13-column feasible table (F11)
        table_wrap = QWidget()
        table_wrap.setStyleSheet("background: transparent;")
        tw_lay = QVBoxLayout(table_wrap)
        tw_lay.setContentsMargins(10, 4, 10, 0)
        tw_lay.setSpacing(0)

        tbl = QTableWidget(0, len(_QD_COLUMNS))
        hh = RichHeaderView(_QD_COLUMNS, tbl)
        self._qd_header = hh
        tbl.setHorizontalHeader(hh)
        tbl.setHorizontalHeaderLabels([plain for _, plain, _ in _QD_COLUMNS])
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tbl.setItemDelegate(_QdTableDelegate(tbl))
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {t['canvas']}; color: {t['fg']}; border: none; "
            "font-size: 12.5px; outline: 0; }"
            "QTableWidget::item { border: none; }"
            f"QScrollBar:vertical {{ width: 6px; background: transparent; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: {t['border_strong']}; "
            "border-radius: 3px; min-height: 36px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        hh.setFixedHeight(36)
        _enable_tnum(tbl)
        tbl.currentCellChanged.connect(
            lambda row, _c, _pr, _pc: self._select_feasible_row(row) if row >= 0 else None
        )
        tbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tw_lay.addWidget(tbl, 1)
        self._view_stack.addWidget(table_wrap)

        # View 1: Ranked Volume-dP dot plot + floating bottom-left DesignPeekCard (F12/F13)
        self.volume_dp_view = VolumeDpView(bottom_pad=152, tokens=t)
        self.volume_dp_view.design_picked.connect(self._select_feasible_row)
        self.peek_card = DesignPeekCard(None, shadow=True, tokens=t)
        self.peek_card.hide()
        self.peek_card.details_requested.connect(self._open_selected_details)
        self._plot_host = _PlotWithPeek(self.volume_dp_view, self.peek_card)
        self._view_stack.addWidget(self._plot_host)

        # View 2: Energy diagnostics table
        energy_page = QWidget()
        energy_page.setStyleSheet("background: transparent;")
        energy_layout = QVBoxLayout(energy_page)
        energy_layout.setContentsMargins(12, 4, 12, 8)
        energy_layout.setSpacing(6)
        energy_note = QLabel(
            "已完成候选的逐算例诊断（含不可行构型）；能量诊断不参与当前可行性筛选。"
        )
        energy_note.setWordWrap(True)
        energy_note.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px; background: transparent; border: none;"
        )
        energy_layout.addWidget(energy_note)
        energy_table = QTableWidget(0, len(_ENERGY_COLUMNS))
        energy_table.setHorizontalHeaderLabels(_ENERGY_COLUMNS)
        energy_table.verticalHeader().setVisible(False)
        energy_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        energy_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        energy_table.setShowGrid(False)
        _enable_tnum(energy_table)
        energy_table.setStyleSheet(
            f"QTableWidget {{ background: {t['canvas']}; color: {t['fg']}; "
            f"border: 1px solid {t['border']}; border-radius: {RADIUS_INPUT}px; font-size: 12px; }}"
            f"QHeaderView::section {{ background: {t['sunken']}; color: {t['sub']}; "
            f"border: none; border-bottom: 1px solid {t['border']}; padding: 6px 8px; "
            "font-size: 11.5px; font-weight: 600; }"
            f"QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {t['border']}; }}"
            f"QTableWidget::item:selected {{ background: {t['accent_soft']}; color: {t['fg']}; }}"
        )
        for index, width in enumerate((155, 65, 105, 105, 130, 130, 180, 85, 85, 180)):
            energy_table.setColumnWidth(index, width)
        energy_layout.addWidget(energy_table, 1)
        self._view_stack.addWidget(energy_page)

        root.addWidget(self._view_stack, 1)

        # ── Build Rule A Input Drawer Body (F13) ──
        self._input_drawer_body = QWidget(self)
        self._input_drawer_body.setStyleSheet("background: transparent;")
        in_lay = QVBoxLayout(self._input_drawer_body)
        in_lay.setContentsMargins(0, 0, 0, 0)
        in_lay.setSpacing(0)

        le_file = QLineEdit()
        le_file.setPlaceholderText("选择 .xlsx / .csv 算例文件…")
        le_file.setToolTip(
            "算例单位：温度 K · 绝压 kPa · 质量流量 kg/s · 换热量 kW；压降上限填比例（如 5% 填 0.05）。\n"
            "表头：case, hot_fluid, T_in_h_K, P_in_h_kPa, mdot_h, cold_fluid, "
            "T_in_c_K, P_in_c_kPa, mdot_c, dPlim_h, dPlim_c，另需 Q_kW 或 dT_h_K。"
        )
        self._style_input(le_file)

        def _browse() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择算例文件", "", "算例 (*.xlsx *.csv);;所有文件 (*)"
            )
            if path:
                le_file.setText(path)

        in_lay.addWidget(
            self._make_rule_a_section(
                "算例文件",
                [("文件", le_file)],
                first=True,
                actions=(("浏览…", _browse),),
            )
        )

        seg_mode = _SegmentedChoice((("自动搜索", "auto"), ("固定胞元", "fixed")))
        seg_mode.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        seg_mode.setToolTip(
            "自动搜索：枚举拓扑、胞元尺寸和壁厚，再为各候选定尺。\n"
            "固定胞元：使用指定的拓扑、胞元尺寸和壁厚，搜索芯体尺寸。"
        )
        self._rule_a_fields.append(seg_mode)

        seg_arr = _SegmentedChoice((("交叉流", "cross"), ("逆流", "counter")))
        seg_arr.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        seg_arr.setToolTip("交叉流：两股流体沿相互垂直的方向流动（默认）。\n逆流：两股流体沿同轴反向流动。")
        self._rule_a_fields.append(seg_arr)

        seg_prop = _SegmentedChoice((("均温", "mean"), ("入口定物性", "const")))
        seg_prop.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        seg_prop.setToolTip(
            "均温物性：先按入口温度求解，再按各股流体进出口平均温度更新物性并求解一次（默认）。\n"
            "入口定物性：按入口温度取物性，只求解一次。"
        )
        self._rule_a_fields.append(seg_prop)

        in_lay.addWidget(
            self._make_rule_a_section(
                "模式与物性",
                [("模式", seg_mode), ("排列", seg_arr), ("物性", seg_prop)],
            )
        )

        le_rho = UnitLineEdit(str(sizing.RHO_S).removesuffix(".0"), unit="kg/m³")
        self._style_input(le_rho)
        le_ks = UnitLineEdit(str(sizing.K_STEEL).removesuffix(".0"), unit="W/(m·K)")
        le_ks.setToolTip("固体热导率: 304SS=16, AlSi10Mg≈150, Cu≈300。")
        self._style_input(le_ks)

        chk_rect = QCheckBox()
        chk_rect.setChecked(False)
        chk_rect.setToolTip(
            "默认关 = 方形迎风 s×s。勾选 = 矩形：迎风高 H 固定、宽自由，求 min-V。"
        )
        chk_rect.setStyleSheet(
            f"QCheckBox {{ spacing: 0px; background: transparent; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; "
            f"border: 1px solid {t['chk_border']}; background: {t['chk_bg']}; }}"
            f"QCheckBox::indicator:checked {{ background: {t['chk_checked_bg']}; "
            f"border: 1px solid {t['chk_checked_border']}; }}"
        )
        chk_rect_row = QWidget()
        chk_rect_row.setStyleSheet("background: transparent;")
        cr_lay = QHBoxLayout(chk_rect_row)
        cr_lay.setContentsMargins(0, 0, 0, 0)
        cr_lay.setSpacing(7)
        cr_lay.addWidget(chk_rect)
        lbl_rect = QLabel(f"固定迎风高度 {SYM['H']}")
        lbl_rect.setTextFormat(Qt.TextFormat.RichText)
        lbl_rect.setStyleSheet(
            f"color: {t['sub']}; font-size: 12.5px; font-weight: 400; background: transparent;"
        )
        cr_lay.addWidget(lbl_rect)
        cr_lay.addStretch(1)

        le_height = UnitLineEdit("750", unit="mm")
        le_height.setEnabled(False)
        le_height.setToolTip("矩形迎风固定高 H [mm]（仅勾选固定迎风高度时生效）。")
        self._style_input(le_height)
        chk_rect.toggled.connect(le_height.setEnabled)

        in_lay.addWidget(
            self._make_rule_a_section(
                "材料与迎风面",
                [
                    (f"密度 {SYM['rho_s']}", le_rho),
                    (f"导热系数 {SYM['k_s']}", le_ks),
                    (chk_rect_row, le_height),
                ],
            )
        )

        # Auto search range band
        topo_row = QWidget()
        topo_row.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        topo_row.setStyleSheet("background: transparent;")
        self._rule_a_fields.append(topo_row)
        tl = QHBoxLayout(topo_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(12)
        topo_checks: dict[str, QCheckBox] = {}
        chk_qss = (
            f"QCheckBox {{ color: {t['fg']}; font-size: 12.5px; spacing: 6px; "
            "background: transparent; }"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; "
            f"border: 1px solid {t['chk_border']}; background: {t['chk_bg']}; }}"
            f"QCheckBox::indicator:checked {{ background: {t['chk_checked_bg']}; "
            f"border: 1px solid {t['chk_checked_border']}; }}"
        )
        for name in ("Diamond", "Gyroid"):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setStyleSheet(chk_qss)
            topo_checks[name] = cb
            tl.addWidget(cb)
        tl.addStretch(1)

        l_nodes = [str(value).removesuffix(".0") for value in TRAIN_L_NODES]
        le_l = UnitLineEdit(", ".join(l_nodes), unit="mm")
        le_l.setToolTip(
            f"胞元尺寸 L [mm] 列表，逗号分隔。当前 K/cF 的 CFD 节点为 {'/'.join(l_nodes)}。"
        )
        self._style_input(le_l)

        t_nodes = [str(value).removesuffix(".0") for value in TRAIN_T_NODES]
        le_t = UnitLineEdit(", ".join(t_nodes), unit="mm")
        le_t.setToolTip(
            f"壁厚 t [mm] 列表，逗号分隔。当前 K/cF 的 CFD 节点为 {'/'.join(t_nodes)}。"
        )
        self._style_input(le_t)

        # Unlabeled ToggleSwitch (Round 18 B6: tooltip only, no 'warm-start' text).
        chk_refine = ToggleSwitch(checked=False, tokens=t)
        chk_refine.setToolTip(
            "对枚举最优件再做连续 (L, t) Nelder-Mead 精修（warm-start），使用串行局部搜索。"
        )
        refine_wrap = QWidget()
        refine_wrap.setStyleSheet("background: transparent;")
        rw_lay = QHBoxLayout(refine_wrap)
        rw_lay.setContentsMargins(0, 0, 0, 0)
        rw_lay.addWidget(chk_refine)
        rw_lay.addStretch(1)

        auto_group = self._make_rule_a_section(
            "搜索范围",
            [
                ("拓扑", topo_row),
                (f"胞元 {SYM['L']}", le_l),
                (f"壁厚 {SYM['t']}", le_t),
                (f"连续 {SYM['L']}、{SYM['t']} 精修", refine_wrap),
            ],
        )
        in_lay.addWidget(auto_group)

        # Fixed cell band
        combo_cell_topo = QComboBox()
        combo_cell_topo.addItems(["Diamond", "Gyroid"])
        combo_cell_topo.setFixedHeight(28)
        combo_cell_topo.setFixedWidth(_FIELD_WIDTH_DESKTOP)
        combo_cell_topo.setStyleSheet(
            f"QComboBox {{ background: {t['inp_bg']}; color: {t['inp_fg']}; "
            f"border: 1px solid {t['inp_border']}; border-radius: {RADIUS_INPUT}px; "
            "padding: 2px 8px; font-size: 12.5px; }"
        )
        self._rule_a_fields.append(combo_cell_topo)

        le_cell_l = UnitLineEdit("7", unit="mm")
        le_cell_l.setToolTip("胞元尺寸 L [mm]")
        self._style_input(le_cell_l)

        le_cell_t = UnitLineEdit("0.5", unit="mm")
        le_cell_t.setToolTip("壁厚 t [mm]")
        self._style_input(le_cell_t)

        fixed_group = self._make_rule_a_section(
            "固定胞元",
            [
                ("拓扑", combo_cell_topo),
                (f"胞元 {SYM['L']}", le_cell_l),
                (f"壁厚 {SYM['t']}", le_cell_t),
            ],
        )
        fixed_group.setVisible(False)
        in_lay.addWidget(fixed_group)
        in_lay.addStretch(1)

        def _on_mode_changed(mode_value: str) -> None:
            is_auto = mode_value == "auto"
            auto_group.setVisible(is_auto)
            fixed_group.setVisible(not is_auto)

        seg_mode.value_changed.connect(_on_mode_changed)

        # Selected design drawer tab (Tab 1)
        self._selected_drawer_body = QWidget(self)
        self._selected_drawer_body.setStyleSheet("background: transparent;")
        sel_lay = QVBoxLayout(self._selected_drawer_body)
        sel_lay.setContentsMargins(0, 0, 0, 0)
        sel_lay.setSpacing(0)
        self.selected_panel = SelectedQuickDesignPanel(None, tokens=t)
        sel_lay.addWidget(self.selected_panel)
        sel_lay.addStretch(1)

        lbl_status = QLabel("就绪")
        lbl_status.setWordWrap(True)
        lbl_status.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px; padding: 4px 14px; background: transparent;"
        )
        root.addWidget(lbl_status)

        # Visible control attributes
        self.le_qd_file = le_file
        self.mode_selector = seg_mode
        self.arrangement_selector = seg_arr
        self.le_qd_rho = le_rho
        self.le_qd_ks = le_ks
        self.prop_model_selector = seg_prop
        self.chk_qd_rect = chk_rect
        self.le_qd_height = le_height
        self.topo_checks = topo_checks
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
