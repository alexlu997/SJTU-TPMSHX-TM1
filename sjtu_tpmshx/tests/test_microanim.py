"""Deterministic lifecycle and motion checks for one-shot UI feedback."""
import gc
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QParallelAnimationGroup, QPauseAnimation, QPropertyAnimation, QSequentialAnimationGroup, QVariantAnimation, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from sjtu_tpmshx.ui.microanim import _AnimationClock, pulse_glow, reveal, start_animation, toast  # noqa: E402


@pytest.fixture
def parent():
    widget = QWidget()
    widget.resize(640, 400)
    widget.show()
    yield widget
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_toast_moves_and_fades_together_then_holds_and_disposes(parent):
    pill = toast(parent, "Done", duration_ms=2200)
    seq = pill.findChild(QSequentialAnimationGroup)
    seq.pause()
    gc.collect()  # position animations must survive the helper returning
    y_start = pill.y()
    opacity = pill.graphicsEffect()

    seq.setCurrentTime(90)
    assert y_start - 12 < pill.y() < y_start
    assert 0 < opacity.opacity() < 1
    seq.setCurrentTime(180)
    assert pill.y() == y_start - 12
    assert opacity.opacity() == 1
    seq.setCurrentTime(2000)
    assert pill.y() == y_start - 12
    assert opacity.opacity() == 1
    seq.setCurrentTime(2160)
    assert y_start - 12 < pill.y() < y_start - 4
    assert 0 < opacity.opacity() < 1

    seq.setCurrentTime(seq.duration())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(pill)


def test_error_toast_keeps_copy_action_and_five_second_lifetime(parent):
    payload = "Error details\ntraceback"
    pill = toast(parent, "Failed", kind="error", duration_ms=100, copy_payload=payload)
    seq = pill.findChild(QSequentialAnimationGroup)
    seq.pause()
    assert seq.duration() == 5000
    seq.setCurrentTime(2500)
    assert pill.graphicsEffect().opacity() == 1
    QTest.mouseClick(pill, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == payload


def test_repeated_pulse_releases_previous_animation_and_cleans_up(parent):
    pulse_glow(parent, duration_ms=550)
    old_effect = parent.graphicsEffect()
    old_animation = old_effect.findChild(QParallelAnimationGroup)
    old_animation.pause()
    old_animation.setCurrentTime(200)
    assert old_effect.color().alpha() > 0

    pulse_glow(parent, duration_ms=700)
    assert not isValid(old_effect)
    assert not isValid(old_animation)
    effect = parent.graphicsEffect()
    animation = effect.findChild(QParallelAnimationGroup)
    animation.pause()
    animation.setCurrentTime(300)
    assert effect.color().alpha() > 0
    assert effect.blurRadius() > 0
    animation.setCurrentTime(animation.duration())
    assert parent.graphicsEffect() is None


def test_reveal_resolves_and_repeated_calls_cancel_previous_animation(parent):
    reveal(parent)
    old_effect = parent.graphicsEffect()
    old_animation = old_effect.findChild(QPropertyAnimation)
    old_animation.pause()
    old_animation.setCurrentTime(100)
    assert 0.72 < old_effect.opacity() < 1

    reveal(parent)
    assert not isValid(old_effect)
    assert not isValid(old_animation)
    effect = parent.graphicsEffect()
    animation = effect.findChild(QPropertyAnimation)
    animation.pause()
    animation.setCurrentTime(animation.duration())
    assert parent.graphicsEffect() is None


def test_reveal_respects_reduced_motion_and_parent_lifetime(parent, monkeypatch):
    monkeypatch.setenv('QT_REDUCED_MOTION', '1')
    reveal(parent)
    assert parent.graphicsEffect() is None
    monkeypatch.delenv('QT_REDUCED_MOTION')
    child = QWidget(parent)
    reveal(child)  # hidden setup / session restoration does not animate
    assert child.graphicsEffect() is None
    child.show()
    reveal(child)
    animation = child.graphicsEffect().findChild(QPropertyAnimation)
    child.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(animation)


def test_window_destruction_during_reveal_has_no_deleted_wrapper_errors(monkeypatch):
    import sys
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *error: errors.append(error))
    window = QWidget()
    child = QWidget(window)
    window.show()
    child.show()
    reveal(child)
    animation = child.graphicsEffect().findChild(QPropertyAnimation)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(window) and not isValid(animation)
    assert not errors


def test_animation_clock_uses_elapsed_time_and_stop_cancels_future_updates(parent):
    animation = QVariantAnimation(parent)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setDuration(200)
    start_animation(parent, animation)
    driver = animation.findChild(_AnimationClock)
    assert driver.wake.timerType() == Qt.TimerType.PreciseTimer
    assert driver.wake.interval() == 8
    driver.elapsed = SimpleNamespace(elapsed=lambda: 173)
    driver.wake.timeout.emit()
    assert animation.currentTime() == 173  # one late frame jumps ahead
    assert 0 < animation.currentValue() < 1
    animation.stop()
    assert not driver.wake.isActive()
    QTest.qWait(20)
    assert animation.currentTime() == 173
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(driver)


def test_animation_clock_finishes_and_does_not_spin_during_a_stationary_hold(parent):
    pill = toast(parent, 'Done', duration_ms=2200)
    seq = pill.findChild(QSequentialAnimationGroup)
    driver = seq.findChild(_AnimationClock)
    driver.elapsed = SimpleNamespace(elapsed=lambda: 400)
    for _ in range(3):
        driver.wake.timeout.emit()
    assert isinstance(seq.currentAnimation(), QPauseAnimation)
    assert driver.wake.remainingTime() > 1000
    driver.elapsed = SimpleNamespace(elapsed=lambda: 2300)
    driver.wake.timeout.emit()
    assert seq.state() == QAbstractAnimation.State.Stopped
    assert not driver.wake.isActive()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(pill)


def test_hiding_window_finishes_transient_effect(parent):
    reveal(parent)
    assert parent.graphicsEffect() is not None
    parent.hide()
    assert parent.graphicsEffect() is None
