"""Micro-animation helpers.

Tiny state-change animations that make the UI feel alive without being
toy-like — one-shot pulses on compute completion, floating success toast,
brief form reveals, and opacity fades for toast transitions.

Native Qt animations release their temporary widgets or effects on completion.
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QPoint, QAbstractAnimation, QSequentialAnimationGroup,
    QParallelAnimationGroup, QPauseAnimation, QObject, QEvent, QElapsedTimer, QTimer,
)
from shiboken6 import isValid
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QLabel, QApplication,
    QGraphicsOpacityEffect,
)


class _AnimationClock(QObject):
    """Advance elapsed-time motion independently of Qt's default 60 Hz timer."""

    def __init__(self, window, animation):
        super().__init__(animation)
        self.window = window
        self.animation = animation
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.wake = QTimer(self)
        self.wake.setTimerType(Qt.TimerType.PreciseTimer)
        self.wake.timeout.connect(self._advance)
        window.installEventFilter(self)
        animation.stateChanged.connect(self._state_changed)
        # Native requestUpdate stalled near 12 ms with an embedded VTK window.
        # 8 ms gives painting headroom for 90 Hz; it is not a measured FPS.
        self.wake.start(8)

    def _state_changed(self, state, _old_state):
        if state == QAbstractAnimation.State.Stopped:
            self.wake.stop()
            if isValid(self.window):
                self.window.removeEventFilter(self)
            self.deleteLater()

    def _advance(self):
        animation = self.animation
        animation.setCurrentTime(min(self.elapsed.elapsed(), animation.totalDuration()))
        # Completion callbacks can delete the animation's owner and this clock.
        if isValid(self) and animation.state() != QAbstractAnimation.State.Stopped:
            current = (animation.currentAnimation()
                       if isinstance(animation, QSequentialAnimationGroup) else animation)
            delay = (current.duration() - current.currentTime()
                     if isinstance(current, QPauseAnimation) else 8)
            # A toast's stationary hold does not keep waking the event loop.
            if self.wake.interval() != delay:
                self.wake.setInterval(delay)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Hide:
            self.animation.setCurrentTime(self.animation.totalDuration())
        return False


def start_animation(widget, animation):
    """Play an owned Qt animation with a precise timer and elapsed-time progress.

    Elapsed time determines progress: a late frame is skipped, never queued.
    stop() and destruction cancel the driver with the ordinary Qt lifecycle.
    """
    animation.start()
    if animation.state() == QAbstractAnimation.State.Running:
        animation.pause()  # disable the default animation timer
        _AnimationClock(widget.window(), animation)


def reveal(widget):
    """Fade a newly shown form into place without delaying its input state.

    Use only on ordinary Qt panels, never Matplotlib or native OpenGL views.
    The effect owns its animation: replacing it cancels an earlier reveal.
    """
    if not widget.isVisible() or os.environ.get('QT_REDUCED_MOTION', '').lower() in ('1', 'true'):
        return
    # A live full-panel blur exceeded the 90 Hz frame budget at DPR 2.
    # Opacity preserves sharp text and does not re-filter every pixel each frame.
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.72)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", effect)
    animation.setStartValue(0.72)
    animation.setEndValue(1.0)
    animation.setDuration(200)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def finish():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    animation.finished.connect(finish)
    start_animation(widget, animation)


def pulse_glow(widget, color=None, blur_peak=20, duration_ms=260):
    """Wrap `widget` in a short glow pulse that fades fully at both ends.

    Replacing the effect also disposes of its animation, so a repeated pulse
    cannot later clear the new effect. No effect remains after completion.
    """
    if color is None:
        from .theme import get_theme
        color = get_theme().get('accent_green', '#22C55E')
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(min(c.alpha(), 180))
    transparent = QColor(c)
    transparent.setAlpha(0)
    eff.setColor(transparent)
    eff.setOffset(0, 0)
    eff.setBlurRadius(0)
    widget.setGraphicsEffect(eff)

    pulse = QParallelAnimationGroup(eff)
    a1 = QPropertyAnimation(eff, b"blurRadius")
    a1.setStartValue(0.0)
    a1.setKeyValueAt(0.4, float(blur_peak))
    a1.setEndValue(0.0)
    a1.setDuration(duration_ms)
    a1.setEasingCurve(QEasingCurve.Type.InOutSine)
    pulse.addAnimation(a1)

    fade = QPropertyAnimation(eff, b"color")
    fade.setStartValue(transparent)
    fade.setKeyValueAt(0.4, c)
    fade.setEndValue(transparent)
    fade.setDuration(duration_ms)
    fade.setEasingCurve(QEasingCurve.Type.InOutSine)
    pulse.addAnimation(fade)

    def _done():
        if widget.graphicsEffect() is eff:
            widget.setGraphicsEffect(None)
    pulse.finished.connect(_done)
    start_animation(widget, pulse)


def toast(parent, text, kind="success", duration_ms=2200, copy_payload=None):
    """Show a floating pill toast at the bottom-right of `parent`.

    kind ∈ {'success','info','warn','error'}. Error toasts linger longer
    (5 s total) and expose a "Copy" affordance via `copy_payload` — pass the
    traceback text so users can one-click grab it for bug reports.
    `duration_ms` includes entrance, stationary hold, and exit.
    """
    # Toast pill colors resolve from theme tokens at call time (ui-plan3a)
    # so light theme gets its darker semantic pair. The glyph is the third
    # element; the second (deep glow hint) is a dark-design asset kept
    # literal color instead of the theme token.
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
    y_start = y_off + 12  # short travel keeps the message easy to track
    pill.setGeometry(x, y_start, w, h)
    pill.show()
    pill.raise_()

    op = QGraphicsOpacityEffect(pill)
    op.setOpacity(0.0)
    pill.setGraphicsEffect(op)

    seq = QSequentialAnimationGroup(pill)

    # Slide + fade in
    entrance = QParallelAnimationGroup()
    a_in_pos = QPropertyAnimation(pill, b"pos")
    a_in_pos.setStartValue(QPoint(x, y_start))
    a_in_pos.setEndValue(QPoint(x, y_off))
    a_in_pos.setDuration(180)
    a_in_pos.setEasingCurve(QEasingCurve.Type.OutCubic)
    entrance.addAnimation(a_in_pos)

    a_in_op = QPropertyAnimation(op, b"opacity")
    a_in_op.setStartValue(0.0); a_in_op.setEndValue(1.0)
    a_in_op.setDuration(180)
    a_in_op.setEasingCurve(QEasingCurve.Type.OutCubic)
    entrance.addAnimation(a_in_op)

    hold = QPauseAnimation(max(0, duration_ms - 340))

    # Slide + fade out
    departure = QParallelAnimationGroup()
    a_out_pos = QPropertyAnimation(pill, b"pos")
    a_out_pos.setStartValue(QPoint(x, y_off))
    a_out_pos.setEndValue(QPoint(x, y_off + 8))
    a_out_pos.setDuration(160)
    a_out_pos.setEasingCurve(QEasingCurve.Type.InCubic)
    departure.addAnimation(a_out_pos)

    a_out_op = QPropertyAnimation(op, b"opacity")
    a_out_op.setStartValue(1.0); a_out_op.setEndValue(0.0)
    a_out_op.setDuration(160)
    a_out_op.setEasingCurve(QEasingCurve.Type.InCubic)
    departure.addAnimation(a_out_op)

    seq.addAnimation(entrance)
    seq.addAnimation(hold)
    seq.addAnimation(departure)
    seq.finished.connect(pill.deleteLater)
    start_animation(pill, seq)
    return pill
