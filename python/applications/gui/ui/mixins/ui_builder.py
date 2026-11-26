"""Hide legacy desktop status bar and install undo stack and field help."""

from __future__ import annotations


class UIBuilderMixin:
    """Page/tab/canvas builders + status-bar / undo / help installers."""

    def _install_status_bar_widgets(self):
        """Hide the legacy QMainWindow status bar; Style P2 uses the readout strip."""
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setMaximumHeight(0)
        sb.hide()

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

        for name in self.case_files.SESSION_LINE_EDITS:
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
        """Capture every statusBar().showMessage into a rolling log without showing a bar."""
        from collections import deque
        from datetime import datetime
        self._log_history = deque(maxlen=50)

        def _on_msg(txt):
            if not txt:
                return
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_history.append(f"[{ts}] {txt}")

        self.statusBar().messageChanged.connect(_on_msg)
        self.signals.adopt(self.statusBar().messageChanged, _on_msg,
                            sender=self.statusBar())
