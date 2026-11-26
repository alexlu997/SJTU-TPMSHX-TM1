"""Style P2 command palette (Ctrl+K) with grouped Chinese actions and shortcuts."""
from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .microanim import is_reduced_motion
from .theme import RADIUS_INPUT, get_theme

_ROLE_IS_HEADER = Qt.ItemDataRole.UserRole + 1


class Action:
    """One row in the command palette."""

    __slots__ = ("title", "category", "keywords", "callback", "shortcut", "score")

    def __init__(
        self,
        title: str,
        category: str,
        callback: Callable,
        keywords: Iterable[str] = (),
        shortcut: str = "",
    ) -> None:
        self.title = title
        self.category = category
        self.keywords = tuple(k.lower() for k in keywords)
        self.callback = callback
        self.shortcut = shortcut
        self.score = 0.0


def _fuzzy_score(query: str, action: Action) -> float:
    """Subsequence and keyword scorer; higher is better."""
    if not query:
        return 0.0
    q = query.lower().strip()
    title = action.title.lower()
    cat = action.category.lower()
    kw = " ".join(action.keywords)

    score = 0.0
    if title.startswith(q):
        score += 5.0
    if q in title:
        score += 3.0 + (2.0 if f" {q}" in f" {title}" else 0.0)
    if q in cat:
        score += 1.0
    if q in kw:
        score += 0.8

    idx = 0
    for ch in q:
        idx = title.find(ch, idx)
        if idx == -1:
            break
        score += 0.3
        if idx == 0 or title[idx - 1] in " -·—()[]/":
            score += 0.5
        idx += 1
    return score


class _ActionListModel(QAbstractListModel):
    """List model with non-selectable category header rows and action entries."""

    def __init__(self, actions: list[Action]) -> None:
        super().__init__()
        self._rows: list[str | Action] = []
        self.set_actions(actions, grouped=True)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def flags(self, index: QModelIndex):
        if not index.isValid() or index.row() >= len(self._rows):
            return Qt.ItemFlag.NoItemFlags
        if isinstance(self._rows[index.row()], str):
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == _ROLE_IS_HEADER:
            return isinstance(row, str)
        if isinstance(row, str):
            return row if role == Qt.ItemDataRole.DisplayRole else None
        if role == Qt.ItemDataRole.DisplayRole:
            return row.title
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def first_action_row(self) -> int:
        for i, row in enumerate(self._rows):
            if isinstance(row, Action):
                return i
        return -1

    def next_action_row(self, start: int, delta: int) -> int:
        n = len(self._rows)
        if n == 0:
            return -1
        pos = start + delta
        while 0 <= pos < n:
            if isinstance(self._rows[pos], Action):
                return pos
            pos += delta
        return start if 0 <= start < n and isinstance(self._rows[start], Action) else self.first_action_row()

    def set_actions(self, actions: list[Action], *, grouped: bool = True) -> None:
        self.beginResetModel()
        rows: list[str | Action] = []
        if grouped:
            seen_cats: dict[str, list[Action]] = {}
            for act in actions:
                seen_cats.setdefault(act.category, []).append(act)
            for cat, items in seen_cats.items():
                rows.append(cat)
                rows.extend(items)
        else:
            rows.extend(actions)
        self._rows = rows
        self.endResetModel()


class _ActionDelegate(QStyledItemDelegate):
    """Paints grouped category headers and action rows with right-aligned shortcut badges."""

    def sizeHint(self, option, index) -> QSize:
        if index.data(_ROLE_IS_HEADER):
            return QSize(0, 24)
        return QSize(0, 34)

    def paint(self, painter: QPainter, option, index) -> None:
        t = get_theme()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        if index.data(_ROLE_IS_HEADER):
            font = QFont(option.font)
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(t["tert"]))
            painter.drawText(
                rect.adjusted(10, 4, -10, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            )
            painter.restore()
            return

        action: Action | None = index.data(Qt.ItemDataRole.UserRole)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        bg = t["accent_soft"] if selected else (t["row_hover"] if hovered else None)
        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(
                QRectF(rect.adjusted(2, 1, -2, -1)), float(RADIUS_INPUT), float(RADIUS_INPUT)
            )

        right_edge = rect.right() - 10
        if action is not None and action.shortcut:
            kbd_font = QFont(option.font)
            kbd_font.setPixelSize(11)
            kbd_font.setWeight(QFont.Weight.Normal)
            painter.setFont(kbd_font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(action.shortcut)
            pill_w = tw + 12
            pill_h = 20
            pill_rect = QRectF(
                right_edge - pill_w,
                rect.top() + (rect.height() - pill_h) / 2.0,
                pill_w,
                pill_h,
            )
            painter.setBrush(QColor(t["sunken"]))
            painter.setPen(QPen(QColor(t["border"]), 0.5))
            painter.drawRoundedRect(pill_rect, 4.0, 4.0)
            painter.setPen(QColor(t["sub"] if hovered or selected else t["tert"]))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, action.shortcut)
            right_edge = int(pill_rect.left()) - 8

        title_font = QFont(option.font)
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(title_font)
        painter.setPen(QColor(t["accent_fg"] if selected else t["fg"]))
        title_rect = QRect(rect.left() + 10, rect.top(), max(20, right_edge - rect.left() - 10), rect.height())
        text = painter.fontMetrics().elidedText(
            action.title if action is not None else "",
            Qt.TextElideMode.ElideRight,
            title_rect.width(),
        )
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class _PaletteSurface(QWidget):
    """Crisp rounded surface painted with Style P2 popover tokens."""

    def paintEvent(self, event) -> None:
        t = get_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(t["popover"]))
        painter.setPen(QPen(QColor(t["border_strong"]), 0.5))
        painter.drawRoundedRect(rect, 11.0, 11.0)
        painter.end()


class _PaletteScrim(QWidget):
    """Translucent backdrop behind the centered Ctrl+K command palette."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(*get_theme()["scrim"]))
        painter.end()


class CommandPalette(QDialog):
    """Floating Ctrl+K palette styled with Style P2 tokens and AA placeholder contrast."""

    def __init__(self, window) -> None:
        super().__init__(window, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._window = window
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(580)
        self.setMinimumHeight(400)
        self._scrim = _PaletteScrim(window.centralWidget() or window)

        t = get_theme()
        self._frame = _PaletteSurface(self)
        self._frame.setObjectName("paletteFrame")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)

        lay = QVBoxLayout(self._frame)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setObjectName("search")
        self._input.setPlaceholderText("搜索命令、页面、预设或快捷键…（Esc 关闭）")
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {t['sunken']}; color: {t['fg']}; "
            f"border: 1px solid {t['border']}; border-radius: {RADIUS_INPUT}px; "
            f"padding: 9px 12px; font-size: 11pt; font-family: {t['sans_family']}; }}"
            f"QLineEdit:focus {{ border: 1px solid {t['accent']}; }}"
        )
        self._apply_placeholder_palette(t)
        lay.addWidget(self._input)

        self._list = QListView()
        self._list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setMouseTracking(True)
        self._list.setItemDelegate(_ActionDelegate(self._list))
        self._list.setMinimumHeight(290)
        self._apply_theme_styles(t)
        lay.addWidget(self._list, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        hint_css = (
            f"color: {t['tert']}; font-size: 8.5pt; background: transparent; border: none;"
        )
        hint_left = QLabel("↑↓ 选择 · Enter 执行 · Esc 关闭")
        hint_left.setStyleSheet(hint_css)
        hint_right = QLabel("SJTU-TPMSHX · Ctrl+K")
        hint_right.setStyleSheet(hint_css)
        footer.addWidget(hint_left, 0, Qt.AlignmentFlag.AlignLeft)
        footer.addStretch(1)
        footer.addWidget(hint_right, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(footer)

        self._model = _ActionListModel([])
        self._list.setModel(self._model)
        self._all_actions: list[Action] = []

        self._input.textChanged.connect(self._on_query_changed)
        self._list.clicked.connect(lambda _i: self._accept_current())

    def _apply_theme_styles(self, t: dict) -> None:
        from sjtu_tpmshx.applications.gui.ui.theme import _build_styles

        scrollbar = _build_styles()["SCROLLBAR"]
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {t['sunken']}; color: {t['fg']}; "
            f"border: 1px solid {t['border']}; border-radius: {RADIUS_INPUT}px; "
            f"padding: 9px 12px; font-size: 11pt; font-family: {t['sans_family']}; }}"
            f"QLineEdit:focus {{ border: 1px solid {t['accent']}; }}"
        )
        self._list.setStyleSheet(
            "QListView { background: transparent; border: none; outline: none; }"
            + scrollbar
        )
        self._apply_placeholder_palette(t)

    def _apply_placeholder_palette(self, t: dict) -> None:
        self._input.ensurePolished()
        pal = self._input.palette()
        ph = QColor(t["placeholder"])
        pal.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText, ph)
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.PlaceholderText, ph)
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.PlaceholderText, ph)
        self._input.setPalette(pal)

    def open_palette(self) -> None:
        self._apply_theme_styles(get_theme())
        self._all_actions = build_actions(self._window)
        self._input.blockSignals(True)
        self._input.clear()
        self._input.blockSignals(False)
        self._model.set_actions(self._all_actions, grouped=True)
        first = self._model.first_action_row()
        if first >= 0:
            self._list.setCurrentIndex(self._model.index(first, 0))
        par = self.parentWidget()
        if par is not None:
            cw = par.centralWidget() if hasattr(par, "centralWidget") and par.centralWidget() else par
            self._scrim.setParent(cw)
            self._scrim.setGeometry(cw.rect())
            self._scrim.show()
            self._scrim.raise_()
            g = par.geometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 120)
        rail = getattr(self._window, "nav_rail", None)
        if rail is not None:
            rail.set_open_action("search")
        self.show()
        self._apply_placeholder_palette(get_theme())
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def hideEvent(self, event) -> None:
        self._scrim.hide()
        rail = getattr(self._window, "nav_rail", None)
        if rail is not None and not self._window.appearance.is_rail_expanded():
            rail.set_open_action(None)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key == Qt.Key.Key_Down:
            self._move_selection(+1)
            return
        if key == Qt.Key.Key_Up:
            self._move_selection(-1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._accept_current()
            return
        super().keyPressEvent(event)

    def _move_selection(self, delta: int) -> None:
        cur = self._list.currentIndex().row()
        nxt = self._model.next_action_row(cur, delta)
        if nxt >= 0:
            self._list.setCurrentIndex(self._model.index(nxt, 0))

    def _on_query_changed(self, text: str) -> None:
        q = text.strip()
        if not q:
            self._model.set_actions(self._all_actions, grouped=True)
        else:
            scored = []
            for a in self._all_actions:
                sc = _fuzzy_score(q, a)
                if sc > 0:
                    a.score = sc
                    scored.append(a)
            scored.sort(key=lambda a: -a.score)
            self._model.set_actions(scored, grouped=False)
        first = self._model.first_action_row()
        if first >= 0:
            self._list.setCurrentIndex(self._model.index(first, 0))

    def _accept_current(self) -> None:
        idx = self._list.currentIndex()
        if not idx.isValid():
            return
        action = self._model.data(idx, Qt.ItemDataRole.UserRole)
        if not isinstance(action, Action):
            return
        self.accept()
        try:
            action.callback()
        except Exception as exc:
            QMessageBox.warning(self._window, f"执行失败：{action.title}", str(exc))


def build_actions(w) -> list[Action]:
    """Build dynamic command palette actions directly against window owners."""
    acts: list[Action] = []

    def add(title: str, cat: str, cb: Callable, **kw) -> None:
        acts.append(Action(title, cat, cb, **kw))

    # 计算与导出
    add(
        "开始计算",
        "计算",
        w.single_run.submit,
        keywords=("run", "compute", "solve", "simulate"),
        shortcut="Ctrl+R",
    )
    add(
        "继续已有任务…",
        "计算",
        w.optimization.resume,
        keywords=("resume", "optimization", "continue", "优化", "继续"),
    )
    add(
        "继续已保存的计算…",
        "计算",
        lambda: w.single_run.resume(),
        keywords=("resume", "checkpoint", "single", "继续"),
    )
    add(
        "重置为默认算例",
        "计算",
        w._reset_defaults,
        keywords=("reset", "default", "clear", "预设", "算例"),
        shortcut="Ctrl+Shift+R",
    )
    add(
        "导出计算结果（CSV / NPZ）…",
        "计算",
        w.result_export.export_results,
        keywords=("save", "csv", "export", "npz"),
    )
    add(
        "导出当前图像…",
        "计算",
        w.result_export.export_figure,
        keywords=("figure", "png", "svg", "pdf", "export"),
    )
    add(
        "打开运行目录",
        "计算",
        lambda: w.dialogs.open_output_folder(scope="auto"),
        keywords=("folder", "directory", "output", "open"),
    )
    add(
        "查看计算日志…",
        "计算",
        w.dialogs.show_solve_log,
        keywords=("log", "residual", "stdout", "debug"),
    )
    add(
        "查看诊断详情…",
        "计算",
        w.results.show_diag_dialog,
        keywords=("diagnostics", "warning", "closure"),
    )
    add(
        "会话总览…",
        "计算",
        w.dialogs.show_overview,
        keywords=("dashboard", "overview", "summary"),
        shortcut="Ctrl+D",
    )
    add(
        "复制输入为 Python 脚本",
        "计算",
        w.history.copy_inputs_as_python,
        keywords=("python", "reproduce", "snippet", "copy"),
    )
    add(
        "复制复现链接（TPMSHX::…）",
        "计算",
        w.history.copy_reproducible_link,
        keywords=("share", "link", "reproduce", "token", "copy"),
    )
    add(
        "载入可复现链接…",
        "计算",
        w.history.load_reproducible_link,
        keywords=("load", "paste", "token", "share"),
    )
    add(
        "开始连续场优化",
        "计算",
        w.optimization.start,
        keywords=("pareto", "qlognehvi", "bayesian", "optimize", "search"),
        shortcut="Ctrl+Enter",
    )

    def _open_sens() -> None:
        from sjtu_tpmshx.applications.gui.ui.sensitivity import open_sensitivity

        open_sensitivity(w)

    add(
        "双参数灵敏度扫描…",
        "计算",
        _open_sens,
        keywords=("sweep", "sensitivity", "heatmap", "parametric"),
    )

    # 页面与视图
    available_tabs = w.workbench.canvas_tab_availability()
    for tab, key, desc, sc in (
        ("layout", "layout", "切换到 算例计算", "Ctrl+1"),
        ("temp", "temp", "切换到 计算结果（温度）", "Ctrl+2"),
        ("pres", "pres", "切换到 计算结果（压力）", ""),
        ("vel", "vel", "切换到 计算结果（速度）", ""),
        ("3d", "3d", "切换到 计算结果（三维）", "Ctrl+4"),
        ("pareto", "pareto", "切换到 优化设计", "Ctrl+3"),
    ):
        if available_tabs.get(tab, False):
            add(
                desc,
                "页面",
                lambda t=tab: w.workbench.switch_tab(t),
                keywords=(key, "tab", "view"),
                shortcut=sc,
            )
    add(
        "切换到 快速设计",
        "页面",
        w.workbench.show_quick_design,
        keywords=("qd", "quick", "design"),
        shortcut="Ctrl+5",
    )

    add(
        "专注当前画布",
        "视图",
        w.appearance.toggle_focus,
        keywords=("focus", "immersive", "专注"),
        shortcut="F",
    )
    add(
        "收起 / 展开导航栏",
        "视图",
        w.appearance.toggle_rail,
        keywords=("rail", "nav", "navigation", "sidebar"),
        shortcut="Ctrl+\\",
    )
    add(
        "收起 / 展开检查器",
        "视图",
        w.appearance.toggle_drawer,
        keywords=("drawer", "inspector", "panel", "sidebar"),
        shortcut="Ctrl+]",
    )
    if hasattr(w, "_toggle_coord_inspector"):
        add(
            "切换坐标探针",
            "视图",
            w._toggle_coord_inspector,
            keywords=("inspector", "probe", "hover", "values"),
            shortcut="Ctrl+I",
        )

    # 外观与偏好
    add(
        "切换浅色 / 深色主题",
        "外观",
        w.appearance.toggle_theme,
        keywords=("dark", "light", "theme", "mode"),
    )
    for dens, label in (("compact", "紧凑"), ("cozy", "适中"), ("comfortable", "宽松")):
        add(
            f"界面密度：{label}",
            "外观",
            lambda name=dens: w.appearance.set_density(name),
            keywords=("density", "spacing", dens),
        )
    add(
        "关闭减少动态效果" if is_reduced_motion() else "开启减少动态效果",
        "外观",
        w.appearance.toggle_reduced_motion,
        keywords=("motion", "animation", "reduced", "动态"),
    )
    add(
        "切换温度单位（K / °C）",
        "外观",
        w._toggle_temp_unit,
        keywords=("kelvin", "celsius", "temperature", "unit"),
    )
    add(
        "选择强调色…",
        "外观",
        w.appearance.pick_accent_color,
        keywords=("accent", "color", "palette"),
    )

    # 预设
    from sjtu_tpmshx.applications.gui.ui.fmt import preset_display

    for name in w.case_files.BUILTIN_PRESETS:
        add(
            f"载入预设：{preset_display(name)}",
            "预设",
            lambda n=name: w.case_files.load_named_preset(n),
            keywords=("preset", "load", "算例", name.lower()),
        )

    # 流体切换
    if hasattr(w, "combo_fluidA"):
        for fluid_name in ("Air", "Water", "sCO₂", "CO₂"):
            add(
                f"流体 A → {fluid_name}",
                "流体",
                lambda n=fluid_name: w.shortcuts.set_fluid("A", n),
                keywords=("fluid", "a", fluid_name.lower()),
            )
            add(
                f"流体 B → {fluid_name}",
                "流体",
                lambda n=fluid_name: w.shortcuts.set_fluid("B", n),
                keywords=("fluid", "b", fluid_name.lower()),
            )

    # 工作区
    for ws in w.case_files.WORKSPACES:
        add(
            f"切换到工作区 {ws}",
            "工作区",
            lambda name=ws: w.case_files.switch_workspace(name),
            keywords=("workspace", "ws", ws.lower()),
        )

    # 3D 分离窗口
    if available_tabs.get("3d", False) and getattr(w, "canvas_3d", None) is not None:
        if w.workbench.detached_volume is None:
            add(
                "在新窗口中打开三维视图",
                "三维",
                w.workbench.detach_3d_window,
                keywords=("detach", "window", "3d"),
            )
        else:
            add(
                "将三维视图放回主窗口",
                "三维",
                w.workbench.reattach_3d_window,
                keywords=("redock", "reattach", "3d"),
            )

    # 历史
    add(
        "历史记录…",
        "历史",
        w.history.show_full_timeline,
        keywords=("timeline", "history", "log", "recent"),
    )
    for i, entry in enumerate(list(w.history.recent_runs)[:5]):
        add(
            f"恢复最近运行 #{i + 1} — {entry.get('label', '?')}  "
            f"(Q={entry.get('Q', '?')}, ΔP={entry.get('dP_A', '?')})",
            "历史",
            lambda e=entry: w.history.load_recent_run(e),
            keywords=("recent", "history", "restore", str(i + 1)),
        )

    # 帮助
    add(
        "快捷键列表…",
        "帮助",
        w.dialogs.show_shortcuts,
        keywords=("keys", "shortcut", "hotkey"),
        shortcut="Ctrl+?",
    )
    add("快速上手", "帮助", w.dialogs.show_quick_tour, keywords=("onboarding", "guide", "tour"))
    add("关于 SJTU-TPMSHX…", "帮助", w.dialogs.show_about, keywords=("about", "version", "info"))
    return acts


def install_command_palette(window) -> None:
    """Wire Ctrl+K to open the lazily-constructed command palette."""
    sh = QShortcut(QKeySequence("Ctrl+K"), window)
    sh.activated.connect(window.dialogs.open_command_palette)
    window.signals.adopt(sh.activated, window.dialogs.open_command_palette, sender=sh)
    window._command_palette_shortcut = sh
