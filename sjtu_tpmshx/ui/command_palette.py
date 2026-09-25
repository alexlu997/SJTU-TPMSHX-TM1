"""Command palette (Ctrl+K) — fuzzy-search floating modal over all actions.

Inspired by Linear / Raycast / Figma / VSCode patterns. Presents a single
entry point the user can memorise in place of a dozen menu locations:
    Ctrl+K → type a few chars → Enter.

Action source is dynamic — `build_actions(window)` walks the current
Main_Menu state each time the palette opens so disabled items (e.g.,
"Re-dock 3D panel" when nothing is detached) are omitted rather than
shown greyed-out and half-working.
"""
from __future__ import annotations

from typing import Callable, Iterable
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListView, QLabel,
    QWidget,
)

from .theme import get_theme


class Action:
    """One row in the palette — cheap pure-data holder."""
    __slots__ = ('title', 'category', 'keywords', 'shortcut', 'callback',
                 'score', 'match_spans')

    def __init__(self, title: str, category: str, callback: Callable,
                 keywords: Iterable[str] = (), shortcut: str = ""):
        self.title = title
        self.category = category
        self.keywords = tuple(k.lower() for k in keywords)
        self.shortcut = shortcut
        self.callback = callback
        self.score = 0.0
        self.match_spans: list[tuple[int, int]] = []


def _fuzzy_score(query: str, action: Action) -> float:
    """Simple subsequence scorer. Higher is better.

    Rules:
      - empty query   → 0.0 (keep insertion order)
      - exact prefix  → +5.0
      - contiguous substring → +3.0
      - each subsequence hit → +1.0
      - bonus when letters land at word boundaries
      - category/keyword matches add half weight
    """
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

    # Subsequence points per letter
    i = 0
    for ch in q:
        i = title.find(ch, i)
        if i == -1:
            break
        score += 0.3
        if i == 0 or title[i - 1] in ' -·—()[]/':
            score += 0.5
        i += 1
    return score


# ────────────────────────────────────────────────────────────────────────

class _ActionListModel(QAbstractListModel):
    def __init__(self, actions: list[Action]):
        super().__init__()
        self._actions = actions

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._actions)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._actions):
            return None
        a = self._actions[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{a.title} — {a.category}"
        if role == Qt.ItemDataRole.UserRole:
            return a
        return None

    def set_actions(self, actions: list[Action]):
        self.beginResetModel()
        self._actions = actions
        self.endResetModel()


# ────────────────────────────────────────────────────────────────────────

class CommandPalette(QDialog):
    """Floating Ctrl+K palette.

    Lifecycle: a single instance is cached on `window._command_palette`;
    reopening resets the query and rebuilds actions against current state.
    """

    def __init__(self, window):
        super().__init__(window, Qt.WindowType.Dialog
                          | Qt.WindowType.FramelessWindowHint)
        self._window = window
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(640)
        self.setMinimumHeight(380)

        _t = get_theme()
        _surface = _t.get('surface_elevated', _t['card_bg'])
        _border = _t.get('border_strong', _t['card_border'])
        _sub = _t.get('sub_fg', _t['fg'])

        # Root frame gets the rounded border — QDialog itself stays
        # transparent so the corner radius reads cleanly.
        self._frame = QWidget(self)
        self._frame.setObjectName("paletteFrame")
        self._frame.setStyleSheet(
            f"#paletteFrame{{background:{_surface};"
            f"border:1px solid {_border}; border-radius:6px;}}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)

        lay = QVBoxLayout(self._frame)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Type to search actions, presets, shortcuts…  (Esc to close)")
        self._input.setStyleSheet(
            f"QLineEdit{{background:{_t.get('surface_raised', _t['card_bg'])};"
            f"color:{_t['fg']}; border:1px solid {_border};"
            f"border-radius:6px; padding:10px 14px; font-size:12pt;"
            f"font-family:{_t['sans_family']};}}"
            f"QLineEdit:focus{{border:1px solid {_t.get('accent_primary', '#3B82F6')};}}")
        lay.addWidget(self._input)

        self._list = QListView()
        self._list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet(
            f"QListView{{background:transparent; border:none; outline:none;"
            f"color:{_t['fg']}; font-size:10pt;}}"
            f"QListView::item{{padding:8px 10px; border-radius:6px;}}"
            f"QListView::item:selected{{"
            f"background:{_t.get('accent_primary', '#3B82F6')};"
            f"color:white;}}"
            f"QListView::item:hover{{background:{_border};}}")
        self._list.setMinimumHeight(280)
        lay.addWidget(self._list, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        hint_css = (
            f"color:{_sub}; font-size:8pt; background:transparent;"
            "border:none; letter-spacing:0.3px;")
        hint_left = QLabel("↑↓ navigate · Enter to run · Esc to close")
        hint_left.setStyleSheet(hint_css)
        hint_right = QLabel("SJTU-TPMSHX · ⌘K")
        hint_right.setStyleSheet(hint_css + " font-style:italic;")
        footer.addWidget(hint_left, 0, Qt.AlignmentFlag.AlignLeft)
        footer.addStretch(1)
        footer.addWidget(hint_right, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(footer)

        self._model = _ActionListModel([])
        self._list.setModel(self._model)
        self._all_actions: list[Action] = []

        self._input.textChanged.connect(self._on_query_changed)
        self._input.returnPressed.connect(self._accept_current)
        self._list.doubleClicked.connect(lambda _i: self._accept_current())

    # ── Public API ──────────────────────────────────────────────────
    def open_palette(self):
        self._all_actions = build_actions(self._window)
        self._input.blockSignals(True)
        self._input.clear()
        self._input.blockSignals(False)
        self._model.set_actions(self._all_actions)
        if self._all_actions:
            self._list.setCurrentIndex(self._model.index(0, 0))
        # Center over the parent window.
        par = self.parentWidget()
        if par is not None:
            g = par.geometry()
            self.move(g.x() + (g.width() - self.width()) // 2,
                      g.y() + 140)
        self.show()
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    # ── Keyboard navigation ─────────────────────────────────────────
    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Escape,):
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

    def _move_selection(self, delta):
        n = self._model.rowCount()
        if n == 0:
            return
        cur = self._list.currentIndex().row()
        new = max(0, min(n - 1, (cur if cur >= 0 else 0) + delta))
        self._list.setCurrentIndex(self._model.index(new, 0))

    def _on_query_changed(self, text):
        q = text.strip()
        if not q:
            self._model.set_actions(self._all_actions)
            if self._all_actions:
                self._list.setCurrentIndex(self._model.index(0, 0))
            return
        scored = []
        for a in self._all_actions:
            s = _fuzzy_score(q, a)
            if s > 0:
                a.score = s
                scored.append(a)
        scored.sort(key=lambda a: a.score, reverse=True)
        self._model.set_actions(scored[:25])
        if scored:
            self._list.setCurrentIndex(self._model.index(0, 0))

    def _accept_current(self):
        idx = self._list.currentIndex()
        if not idx.isValid():
            return
        a: Action = self._model.data(idx, Qt.ItemDataRole.UserRole)
        self.accept()
        if a is not None:
            try:
                a.callback()
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self._window,
                                     f"Action failed: {a.title}", str(e))


# ────────────────────────────────────────────────────────────────────────
#  Action catalogue — built dynamically each open so it reflects current
#  state (e.g., "Re-dock 3D panel" only appears when a detached window exists).
# ────────────────────────────────────────────────────────────────────────

def build_actions(w) -> list[Action]:
    acts: list[Action] = []
    def add(title, cat, cb, **kw):
        acts.append(Action(title, cat, cb, **kw))

    # Compute & export
    add("Run Compute", "Compute", w.run_calculation,
        shortcut="Ctrl+R", keywords=("solve", "simulate", "run"))
    add("Reset parameters to preset", "Compute", w._reset_defaults,
        shortcut="Ctrl+Shift+R", keywords=("reset", "default", "clear"))
    if hasattr(w, '_export_results'):
        add("Export results to CSV…", "Compute", w._export_results,
            keywords=("save", "csv", "export"))
    if hasattr(w, '_copy_inputs_as_python'):
        add("Copy inputs as Python code", "Compute",
            w._copy_inputs_as_python,
            keywords=("python", "reproduce", "bundle", "snippet", "copy"))
    if hasattr(w, '_copy_reproducible_link'):
        add("Copy reproducible link (TPMSHX::…)", "Compute",
            w._copy_reproducible_link,
            keywords=("share", "link", "reproduce", "token", "copy"))
    if hasattr(w, '_load_reproducible_link'):
        add("Load reproducible link…", "Compute",
            w._load_reproducible_link,
            keywords=("load", "paste", "token", "share"))
    if hasattr(w, '_show_full_timeline'):
        add("Show full session timeline…", "Recent",
            w._show_full_timeline,
            keywords=("timeline", "history", "log", "all", "full"))
    if hasattr(w, '_show_solve_log'):
        add("Show solve log…", "Compute", w._show_solve_log,
            keywords=("log", "residual", "stdout", "debug"))
    if hasattr(w, '_show_overview'):
        add("Overview dashboard…", "Compute", w._show_overview,
            shortcut="Ctrl+D",
            keywords=("dashboard", "overview", "summary", "home"))
    if hasattr(w, '_run_optimize'):
        add("Optimize (continuous field)", "Compute", w._run_optimize,
            keywords=("pareto", "qlognehvi", "bayesian", "optimise", "search"))
    def _open_sens():
        from sjtu_tpmshx.ui.sensitivity import open_sensitivity
        open_sensitivity(w)
    add("Sensitivity sweep (2-param heatmap)…", "Compute", _open_sens,
        keywords=("sweep", "sensitivity", "heatmap", "parametric"))

    # Theme / units / panels
    add("Toggle theme (light / dark)", "Appearance", w._toggle_theme,
        keywords=("dark", "light", "mode"))
    for dens in ("compact", "cozy", "comfortable"):
        add(f"Density: {dens.capitalize()}", "Appearance",
            (lambda name=dens: w._set_density(name)),
            keywords=("density", "spacing", "compact", "comfortable", dens))
    if hasattr(w, '_pick_accent_color'):
        add("Pick accent colour…", "Appearance", w._pick_accent_color,
            keywords=("accent", "color", "brand", "palette"))
    add("Toggle Kelvin / Celsius", "Appearance", w._toggle_temp_unit,
        keywords=("kelvin", "celsius", "degc", "temperature", "unit"))
    add("Collapse / expand parameter panel", "Appearance",
        w._toggle_left_panel, keywords=("sidebar", "hide", "focus"))
    if hasattr(w, '_toggle_coord_inspector'):
        add("Toggle coordinate inspector", "Appearance",
            w._toggle_coord_inspector,
            shortcut="Ctrl+I",
            keywords=("inspector", "probe", "hover", "values"))

    # Tabs: list only views backed by currently available result state.
    _available_tabs = w._canvas_tab_availability()
    # ui-shortcuts-persist: labels in Chinese to match the toolbar chrome;
    # the English keywords stay so "temp"/"pareto" still find the entries.
    for tab, key, desc in [
        ('layout', 'layout', '显示 几何布局 页签'),
        ('temp',   'temp',   '显示 温度 视图（结果）'),
        ('pres',   'pres',   '显示 压力 视图（结果）'),
        ('vel',    'vel',    '显示 速度 视图（结果）'),
        ('3d',     '3d',     '显示 3D 视图（结果）'),
        ('pareto', 'pareto', '显示 优化 页签'),
    ]:
        if not _available_tabs.get(tab, False):
            continue
        add(desc, "Tabs",
            (lambda t=tab: w._switch_tab(t)),
            keywords=(key, "tab", "view"))

    # Presets — display de-branded (ui.fmt.preset_display); the internal
    # key passed to _load_named_preset keeps the historical spelling.
    from sjtu_tpmshx.ui.fmt import preset_display as _pd
    for name in getattr(w, '_BUILTIN_PRESETS', ()):
        add(f"Preset: {_pd(name)}", "Preset",
            (lambda n=name: w._load_named_preset(n)),
            keywords=("preset", "load", "算例", name.lower()))

    # Fluid type switches
    if hasattr(w, 'combo_fluidA'):
        for fluid_name in ("Air", "Water", "sCO₂"):
            def _set_fluid(side, n=fluid_name):
                combo = getattr(w, f'combo_fluid{side}', None)
                if combo is None:
                    return
                idx = combo.findText(n)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            add(f"Fluid A → {fluid_name}", "Fluids",
                (lambda n=fluid_name: _set_fluid('A', n)),
                keywords=("fluid", "a", fluid_name.lower()))
            add(f"Fluid B → {fluid_name}", "Fluids",
                (lambda n=fluid_name: _set_fluid('B', n)),
                keywords=("fluid", "b", fluid_name.lower()))

    # Workspaces
    for ws in getattr(w, '_WORKSPACES', ('A', 'B', 'C')):
        add(f"Switch to workspace {ws}", "Workspace",
            (lambda name=ws: w._switch_workspace(name)),
            keywords=("workspace", "ws", ws.lower()))

    # Help surface
    if hasattr(w, '_show_about'):
        add("About SJTU-TPMSHX", "Help", w._show_about,
            keywords=("version", "credits", "info"))
    if hasattr(w, '_show_shortcuts'):
        add("Keyboard shortcuts cheat sheet", "Help", w._show_shortcuts,
            shortcut="Ctrl+?", keywords=("keys", "shortcut", "hotkey"))
    if hasattr(w, '_show_quick_tour'):
        add("Show quick tour", "Help", w._show_quick_tour,
            keywords=("onboarding", "guide"))

    add("Toggle canvas focus", "View", w._toggle_3d_immersive,
        shortcut="F", keywords=("focus", "immersive", "专注"))
    # 3D commands require both an available result and an initialized panel.
    _3d_tab_ready = _available_tabs.get('3d', False)
    _3d_panel_ready = getattr(w, 'canvas_3d', None) is not None
    if _3d_tab_ready and _3d_panel_ready:
        if getattr(w, '_3d_detached_window', None) is None:
            add("Open 3D in new window", "3D", w._detach_3d_window,
                keywords=("detach", "window", "multi-monitor"))
        else:
            add("Re-dock 3D panel", "3D", w._reattach_3d_window,
                keywords=("redock", "reattach"))

    # Recent runs (top 5)
    recents = list(getattr(w, '_recent_runs', []) or [])[:5]
    for i, e in enumerate(recents):
        def _load_run(entry=e):
            w._load_recent_run(entry)
        add(f"Restore recent run #{i+1} — {e.get('label','?')}  "
            f"(Q={e.get('Q','?')}, ΔP={e.get('dP_A','?')})",
            "Recent", _load_run,
            keywords=("recent", "history", "restore", str(i+1)))

    return acts


def install_command_palette(window):
    """Wire the Ctrl+K shortcut on the given main window. Palette is lazy
    — constructed on first open, cached for reuse."""
    def _open():
        pal = getattr(window, '_command_palette', None)
        if pal is None:
            pal = CommandPalette(window)
            window._command_palette = pal
        pal.open_palette()
    sh = QShortcut(QKeySequence("Ctrl+K"), window)
    sh.activated.connect(_open)
    window._command_palette_shortcut = sh
