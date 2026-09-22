"""Track bound Qt signal/slot pairs and disconnect them on window shutdown.

Use ``router.connect(widget.clicked, slot, sender=widget)`` for new pairs,
or ``adopt`` for connections made by a builder. Qt objects remain parent-owned.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QObject


SignalLike = Any   # bound signal object — Qt offers no public type alias


@dataclass
class _Connection:
    """One registered signal/slot pair, retained until disconnected."""
    signal_obj: SignalLike
    slot: Callable[..., Any]
    sender_ref: Optional[weakref.ReferenceType] = None
    alive: bool = True


class SignalRouter(QObject):
    """Holds connections until shutdown."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._connections: List[_Connection] = []

    # ------------------------------------------------------------------ register

    def connect(self, signal: SignalLike, slot: Callable[..., Any],
                sender: Optional[QObject] = None) -> bool:
        """Register and connect a signal/slot pair.

        Returns True on success, False if Qt rejects the connection
        (mismatched signature, already-deleted widget, etc.). Logs
        nothing on failure — caller decides whether to warn.

        ``sender`` is optional; if supplied a weakref is held so
        ``disconnect_all`` can skip slots whose widget has already been
        destroyed (avoids ``RuntimeError: wrapped C/C++ object deleted``).
        """
        try:
            signal.connect(slot)
        except (TypeError, RuntimeError):
            return False
        ref = weakref.ref(sender) if sender is not None else None
        self._connections.append(_Connection(
            signal_obj=signal, slot=slot, sender_ref=ref))
        return True

    def adopt(self, signal: SignalLike, slot: Callable[..., Any],
              sender: Optional[QObject] = None) -> None:
        """Record an *already-connected* pair so ``disconnect_all`` covers it.

        Lets you migrate existing ``.connect()`` call sites incrementally
        without flipping them to ``router.connect`` in one big diff.
        """
        ref = weakref.ref(sender) if sender is not None else None
        self._connections.append(_Connection(
            signal_obj=signal, slot=slot, sender_ref=ref))

    # ------------------------------------------------------------------ release


    def disconnect_all(self) -> int:
        """Disconnect every registered pair. Returns count of successes.

        Idempotent — calling twice is a no-op on the second pass.
        """
        n = 0
        for c in self._connections:
            if not c.alive:
                continue
            if self._safe_disconnect(c):
                n += 1
        return n

    def _safe_disconnect(self, c: _Connection) -> bool:
        # Skip if the sender widget was already torn down. The weakref
        # check is cheap and avoids a noisy RuntimeError under teardown.
        if c.sender_ref is not None and c.sender_ref() is None:
            c.alive = False
            return False
        try:
            c.signal_obj.disconnect(c.slot)
        except (TypeError, RuntimeError):
            # Already disconnected, or signal-object deleted — both fine.
            c.alive = False
            return False
        c.alive = False
        return True

    # ------------------------------------------------------------------ inspect

    def count(self, alive_only: bool = True) -> int:
        if alive_only:
            return sum(1 for c in self._connections if c.alive)
        return len(self._connections)



    def __repr__(self) -> str:
        return (f'<SignalRouter alive={self.count()} '
                f'total={self.count(alive_only=False)}>')
