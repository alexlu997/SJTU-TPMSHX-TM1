"""Micro-animation helpers.

Tiny state-change animations that make the UI feel alive without being
toy-like — one-shot pulses on compute completion, floating success toast,
opacity fades for staged UI transitions.

Everything is cheap: QPropertyAnimation on QGraphicsEffects or geometry.
No timers that stick around, no CPU-heavy loops.
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QPoint, QAbstractAnimation, QSequentialAnimationGroup,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QLabel, QApplication,
    QGraphicsOpacityEffect,
)


def pulse_glow(widget, color=None, blur_peak=20, duration_ms=260):
    """Wrap `widget` in a short glow pulse. Sequential:
        0   → blur 0, alpha 0
        40% → blur peak, alpha 200
        100%→ blur 0, alpha 0

    Existing effect on the widget is replaced for the pulse, then restored
    to None on finish so layout stays cheap.
    """
    if color is None:
        from .theme import get_theme
        color = get_theme().get('accent_green', '#22C55E')
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    eff.setColor(c)
    eff.setOffset(0, 0)
    eff.setBlurRadius(0)
    widget.setGraphicsEffect(eff)

    a1 = QPropertyAnimation(eff, b"blurRadius", widget)
    a1.setStartValue(0.0)
    a1.setKeyValueAt(0.4, float(blur_peak))
    a1.setEndValue(0.0)
    a1.setDuration(duration_ms)
    a1.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
    a1.finished.connect(_done)
    a1.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def toast(parent, text, kind="success", duration_ms=2200, copy_payload=None):
    """Show a floating pill toast at the bottom-right of `parent`.

    kind ∈ {'success','info','warn','error'}. Error toasts linger longer
    (5 s) and expose a "Copy" affordance via `copy_payload` — pass the
    traceback text so users can one-click grab it for bug reports.
    """
    # Toast pill colors resolve from theme tokens at call time (ui-plan3a)
    # so light theme gets its darker semantic pair. The glyph is the third
    # element; the second (deep glow hint) is a dark-design asset kept
    # literal like glass_panel's gradient.
    from .theme import get_theme
    _tk = get_theme()
    _PALETTE = {
        'success': (_tk.get('accent_green', '#22C55E'), '#064E3B', '✓'),
        'info':    (_tk.get('accent_primary', '#3B82F6'), '#1E3A8A', '›'),
        'warn':    (_tk.get('search_hl', '#F59E0B'), '#78350F', '!'),
        'error':   (_tk.get('err', '#DC2626'), '#450A0A', '✕'),
    }
    fg_hint, _dark, glyph = _PALETTE.get(kind, _PALETTE['info'])
    # Errors deserve more screen time.
    if kind == 'error' and duration_ms < 5000:
        duration_ms = 5000

    # Error toasts get a clickable Copy hint appended; plain kind stays lean.
    suffix = "   ⧉ click to copy" if (kind == 'error' and copy_payload) else ""
    pill = QLabel(f"  {glyph}  {text}{suffix}  ", parent)
    if kind == 'error' and copy_payload:
        pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        pill.setCursor(Qt.CursorShape.PointingHandCursor)
        def _on_click(_ev, payload=copy_payload):
            QApplication.clipboard().setText(str(payload))
        pill.mousePressEvent = _on_click
    else:
        pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    pill.setStyleSheet(
        f"color:{_tk.get('tab_on_fg', '#FFFFFF')}; background:{fg_hint};"
        f"border:none; border-radius:18px; padding:10px 18px;"
        f"font-family:{_tk['sans_family']};"
        f"font-size:10pt; font-weight:700; letter-spacing:0.3px;")
    pill.adjustSize()

    # Position: 24 px off bottom-right edge of parent viewport.
    margin = 24
    w = pill.width(); h = pill.height()
    parent_w = parent.width(); parent_h = parent.height()
    x = parent_w - w - margin
    y_off = parent_h - h - margin - 40  # final rest pos
    y_start = parent_h - h - margin + 16  # slide start (below rest)
    pill.setGeometry(x, y_start, w, h)
    pill.show()
    pill.raise_()

    op = QGraphicsOpacityEffect(pill)
    op.setOpacity(0.0)
    pill.setGraphicsEffect(op)

    seq = QSequentialAnimationGroup(pill)

    # Slide + fade in
    a_in_pos = QPropertyAnimation(pill, b"pos")
    a_in_pos.setStartValue(QPoint(x, y_start))
    a_in_pos.setEndValue(QPoint(x, y_off))
    a_in_pos.setDuration(140)
    a_in_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

    a_in_op = QPropertyAnimation(op, b"opacity")
    a_in_op.setStartValue(0.0); a_in_op.setEndValue(1.0)
    a_in_op.setDuration(140)
    a_in_op.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # Hold — implemented as zero-value animation over `duration_ms - 280`
    hold = QPropertyAnimation(op, b"opacity")
    hold.setStartValue(1.0); hold.setEndValue(1.0)
    hold.setDuration(max(0, duration_ms - 280))

    # Slide + fade out
    a_out_op = QPropertyAnimation(op, b"opacity")
    a_out_op.setStartValue(1.0); a_out_op.setEndValue(0.0)
    a_out_op.setDuration(160)
    a_out_op.setEasingCurve(QEasingCurve.Type.InCubic)

    # Run pos + opacity concurrently by grouping into parallel — simpler
    # to keep sequential using two passes + Qt's built-in ability to
    # start multiple animations at once via separate objects.
    a_in_pos.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    seq.addAnimation(a_in_op)
    seq.addAnimation(hold)
    seq.addAnimation(a_out_op)
    seq.finished.connect(pill.deleteLater)
    seq.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return pill
