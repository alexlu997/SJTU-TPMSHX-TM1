"""UI construction + install/setup handlers for ``Main_Menu``.

The main UI builder and row callback delegate to their owning modules;
page/tab/canvas assembly calls those module functions directly. This mixin
also installs the status bar, undo stack and field help. UI-only -- no solver
or numeric path. Adopted via
``class Main_Menu(..., UIBuilderMixin, ..., QMainWindow)``; methods
resolve on the live window through the MRO so external wiring keeps
working. Each body keeps its own local imports; the only top-level
imports needed are PySide6 widgets and ui.theme.get_theme.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit

from sjtu_tpmshx.ui.theme import get_theme


class UIBuilderMixin:
    """Page/tab/canvas builders + status-bar / undo / help installers."""

    def _build_ui(self):
        from sjtu_tpmshx.ui.ui_builders import build_ui
        return build_ui(self)

    def _row(self, g, row, text, default) -> QLineEdit:
        from sjtu_tpmshx.ui.builders_base import row as _row_impl
        return _row_impl(self, g, row, text, default)

    def _install_status_bar_widgets(self):
        """Mount permanent status-bar widgets on the right edge of the
        QMainWindow status bar: [Preset] | [Workspace] | [Re_A / Re_B] |
        [last compute clock]. These are **permanent widgets** — they
        survive transient showMessage() calls, giving the user a constant
        context strip like VSCode / JetBrains IDEs.
        """
        from sjtu_tpmshx.ui.theme import get_theme as _gt_sb
        _t = _gt_sb()
        _mono_css = (
            f"color:{_t.get('sub_fg', _t['fg'])};"
            f"font-family:{_t['mono_family']};"
            f"font-size:9pt; font-weight:500;"
            f"background:transparent; border:none; padding:0 6px;")

        def _mk(initial=""):
            l = QLabel(initial)
            l.setStyleSheet(_mono_css)
            return l

        sb = self.statusBar()
        sb.setStyleSheet(
            f"QStatusBar{{background:{_t.get('surface_raised', _t['card_bg'])};"
            f"color:{_t['fg']};"
            f"border-top:1px solid {_t['card_border']};}}"
            f"QStatusBar QLabel{{color:{_t['fg']};}}"
            "QStatusBar::item{border:none;}")
        self._sb_re = _mk("Re: —")
        self._sb_clock = _mk("⏱ —")

        # Visual separator pill between groups. Three identical widgets
        # (not one reused) because Qt requires each addPermanentWidget
        # call to get a distinct widget pointer.
        def _sep():
            s = QLabel("│")
            s.setStyleSheet(
                f"color:{_t.get('sub_fg', '#888')}; background:transparent;"
                "border:none; padding:0 2px; font-size:10pt;")
            return s

        for w in (self._sb_re, _sep(), self._sb_clock):
            sb.addPermanentWidget(w)
        self._refresh_status_bar()

    def _install_undo_stack(self):
        """Track every value change on a numeric input and push it onto a
        QUndoStack so Ctrl+Z / Ctrl+Y can sweep back and forth across
        *cross-field* edits. Qt's built-in per-widget undo only covers the
        currently focused field; this extends it to the whole form.
        """
        from PySide6.QtGui import QUndoStack, QUndoCommand, QShortcut, QKeySequence

        class _FieldEditCmd(QUndoCommand):
            def __init__(self, le, old, new, cache, name):
                super().__init__(f"edit {name}")
                self._le = le
                self._old = old
                self._new = new
                self._cache = cache
                self._name = name

            def _apply(self, value):
                # blockSignals(True) during setText prevents the editing-
                # Finished slot (_on_finished) from pushing a *new* undo
                # command for this programmatic change. We then update the
                # baseline cache to `value` and re-emit editingFinished
                # ourselves — because the cache now equals the field text,
                # _on_finished sees no diff and does NOT re-push, while the
                # OTHER editingFinished consumers (validator, edge-combo
                # refresh on L/H, quick-slider sync) still run. Tier 25:
                # fixes undo/redo silently bypassing that dependent logic.
                self._le.blockSignals(True)
                self._le.setText(value)
                self._le.blockSignals(False)
                self._cache[self._name] = value
                try:
                    self._le.editingFinished.emit()
                except Exception:
                    pass

            def undo(self):
                self._apply(self._old)

            def redo(self):
                self._apply(self._new)

        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(200)
        self._undo_last = {}

        for name in self._SESSION_LINE_EDITS:
            le = getattr(self, name, None)
            if le is None:
                continue
            self._undo_last[name] = le.text()

            def _on_finished(le=le, name=name):
                cur = le.text()
                prev = self._undo_last.get(name, cur)
                if cur != prev:
                    self._undo_stack.push(
                        _FieldEditCmd(le, prev, cur, self._undo_last, name))
            le.editingFinished.connect(_on_finished)
            self.signals.adopt(le.editingFinished, _on_finished,
                                sender=le)

        sc_u = QShortcut(QKeySequence.StandardKey.Undo, self)
        sc_u.activated.connect(self._undo_stack.undo)
        self.signals.adopt(sc_u.activated, self._undo_stack.undo,
                            sender=sc_u)
        sc_r = QShortcut(QKeySequence.StandardKey.Redo, self)
        sc_r.activated.connect(self._undo_stack.redo)
        self.signals.adopt(sc_r.activated, self._undo_stack.redo,
                            sender=sc_r)

    def _install_field_help(self):
        """Attach rich HTML tooltips to physics inputs. Tooltips include the
        symbol, units, typical range, and any surrogate-training caveats —
        the things the user can't derive from the UI label alone.
        """
        for attr, html in self._FIELD_HELP.items():
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                le.setToolTip(html)
            except Exception:
                pass

    def _install_status_log(self):
        """Capture every statusBar().showMessage into a rolling log and add a
        collapsible ▲ toggle on the right edge so users can review messages
        they missed during a long compute.

        Zero-touch for existing callers: QStatusBar emits `messageChanged`
        when showMessage is used, so we just listen for it.
        """
        from collections import deque
        from datetime import datetime
        from PySide6.QtWidgets import QPushButton
        self._log_history = deque(maxlen=50)

        def _on_msg(txt):
            if not txt:
                return
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_history.append(f"[{ts}] {txt}")

        self.statusBar().messageChanged.connect(_on_msg)
        self.signals.adopt(self.statusBar().messageChanged, _on_msg,
                            sender=self.statusBar())

        btn = QPushButton("▲  Log")
        btn.setFixedHeight(18)
        btn.setFixedWidth(70)
        btn.setStyleSheet(
            "QPushButton{background:transparent; border:none;"
            f"color:{get_theme().get('sub_fg', '#888')}; font-size:8pt;"
            "padding:0 6px;}"
            "QPushButton:hover{color:" + get_theme()['fg'] + ";}")
        btn.setToolTip("Show recent status messages")
        btn.clicked.connect(self._show_status_log)
        self.signals.adopt(btn.clicked, self._show_status_log,
                            sender=btn)
        self.statusBar().addPermanentWidget(btn)
