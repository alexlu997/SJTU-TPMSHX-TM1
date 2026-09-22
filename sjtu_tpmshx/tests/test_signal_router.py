"""Unit tests for controllers.signal_router.SignalRouter.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QObject, Signal

from sjtu_tpmshx.controllers.signal_router import SignalRouter


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class _Emitter(QObject):
    """Minimal signal-emitting object for tests."""
    fired = Signal(int)


# ---------------------------------------------------------------- connect


def test_connect_records_and_invokes_slot():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    ok = router.connect(em.fired, lambda i: received.append(i),
                        sender=em)
    assert ok
    em.fired.emit(7)
    assert received == [7]
    assert router.count() == 1


def test_connect_records_no_tag_anonymous():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None)
    assert router.count() == 1




# ---------------------------------------------------------------- disconnect


def test_disconnect_all_breaks_connection():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    router.connect(em.fired, lambda i: received.append(i), sender=em)
    em.fired.emit(1)
    n = router.disconnect_all()
    assert n == 1
    em.fired.emit(2)
    assert received == [1]   # second emit did not fire


def test_disconnect_all_idempotent():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, sender=em)
    assert router.disconnect_all() == 1
    # Second pass: nothing alive, returns 0
    assert router.disconnect_all() == 0






# ---------------------------------------------------------------- adopt


def test_adopt_existing_connection_then_disconnect_all():
    """`.connect()` directly first, register via adopt, expect disconnect."""
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []

    def slot(i):
        received.append(i)

    em.fired.connect(slot)
    router.adopt(em.fired, slot, sender=em)

    em.fired.emit(1)
    n = router.disconnect_all()
    assert n == 1
    em.fired.emit(2)
    assert received == [1]


# ---------------------------------------------------------------- weakref


def test_weakref_skips_destroyed_sender():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, sender=em)
    # Drop the sender. weakref should now be dead.
    em.deleteLater()
    em = None
    import gc
    gc.collect()
    # Pumping the event loop for deleteLater — offscreen is fine without.
    # disconnect_all should not raise; sender_ref returns None → skipped.
    n = router.disconnect_all()
    # Either skipped (n==0) or success (n==1) acceptable depending on GC
    # timing; the key invariant is "no crash".
    assert n in (0, 1)


# ---------------------------------------------------------------- introspect


def test_count_alive_vs_total():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, sender=em)
    router.connect(em.fired, lambda i: None, sender=em)
    assert router.count() == 2
    assert router.count(alive_only=False) == 2
    router.disconnect_all()
    assert router.count() == 0
    assert router.count(alive_only=False) == 2




def test_repr_safe():
    _app()
    router = SignalRouter()
    s = repr(router)
    assert 'SignalRouter' in s
    assert 'alive=0' in s
