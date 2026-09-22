"""Context menu + value-history helpers for left-panel LineEdits.

* D2 — field focus shows "recent values" dropdown (last 5 distinct)
* D3 — right-click on field offers Revert + Copy as expression + Restore-recent
"""
from __future__ import annotations

from collections import deque

from PySide6.QtWidgets import QApplication


def install_field_menus(window):
    """Wire right-click + focus-pop to every session LineEdit.

    Stores `window._field_history = {attr: deque(maxlen=5)}` so the
    history survives across field focus events.
    """
    window._field_history = {}

    for attr in window._SESSION_LINE_EDITS:
        le = getattr(window, attr, None)
        if le is None:
            continue
        # Qt QLineEdit has a built-in context menu (cut/copy/paste). We add
        # our custom items via the contextMenuEvent override using property
        # injection (avoids subclassing every LineEdit).
        _attach_context_menu(window, le, attr)
        _attach_history_tracker(window, le, attr)


def _attach_context_menu(window, le, attr):

    def _ctx(event):
        # Pull the stock menu (cut/copy/paste/select-all) and append ours.
        menu = le.createStandardContextMenu()
        menu.addSeparator()

        act_revert = menu.addAction("恢复算例工况默认值")
        act_revert.triggered.connect(
            lambda: _revert_field_to_default(window, le, attr))

        # Copy as expression — pairs value with the stored unit from
        # _FIELD_UNITS so a user pasting into a notebook gets context.
        unit_family = window._FIELD_UNITS.get(attr, ('', ''))
        unit_txt = unit_family[1] if unit_family else ''
        unit_label = f" [{unit_txt}]" if unit_txt else ""
        act_expr = menu.addAction(f"Copy with unit{unit_label}")
        act_expr.triggered.connect(
            lambda: _copy_with_unit(le, unit_txt))

        # Recent-values submenu — only built when there's history.
        hist = list(window._field_history.get(attr, []))
        if hist:
            sub = menu.addMenu("Recent values")
            for v in hist:
                a = sub.addAction(v)
                # 2026-05-20 UI sweep (Tier 25): emit editingFinished after
                # the programmatic setText so this counts as a real edit —
                # captured by the global undo stack, re-validated, and
                # routed through the unit/expr parsers, exactly like a
                # manual commit. Without the emit the value landed silently
                # and Ctrl+Z could not revert it.
                a.triggered.connect(
                    lambda _c=False, val=v, _le=le:
                    (_le.setText(val), _le.editingFinished.emit()))

        menu.exec(le.mapToGlobal(event.pos()))
        event.accept()

    le.contextMenuEvent = _ctx


def _attach_history_tracker(window, le, attr):
    """Remember a field's last 5 distinct committed values.

    Tracks on `editingFinished` rather than every keystroke so mid-typing
    noise doesn't pollute the history. The deque is stored on the window
    and survives workspace switches."""
    def _push():
        txt = le.text().strip()
        if not txt:
            return
        hist = window._field_history.setdefault(attr, deque(maxlen=5))
        # Avoid duplicates and preserve most-recent-first order.
        if txt in hist:
            try:
                hist.remove(txt)
            except ValueError:
                pass
        hist.appendleft(txt)
    le.editingFinished.connect(_push)


def _revert_field_to_default(window, le, attr):
    """Look up the Shanghai preset default for this attr and write it back."""
    from .mixins.session_presets import shanghai_field_defaults
    defaults = shanghai_field_defaults(is_3d=window.combo_dim.currentIndex() == 1)
    val = defaults.get(attr)
    if val is None:
        window.statusBar().showMessage(
            f"No preset default for {attr}.", 3000)
        return
    # Temperature fields are authored in K; convert if UI shows °C.
    if attr in ('le_TinA', 'le_TinB') and val != '' and \
            getattr(window, '_temp_unit', 'K') == 'C':
        try:
            val = f"{float(val) - 273.15:.2f}"
        except Exception:
            pass
    le.setText(val)
    # Tier 25: emit editingFinished so Revert is a real, undoable edit
    # (same rationale as the Recent-values handler above).
    try:
        le.editingFinished.emit()
    except Exception:
        pass
    window.statusBar().showMessage(
        f"{attr} 已恢复算例工况默认值（{val}）。", 4000)


def _copy_with_unit(le, unit_txt):
    txt = le.text().strip()
    if not txt:
        return
    clip = QApplication.clipboard()
    clip.setText(f"{txt} {unit_txt}".strip())
