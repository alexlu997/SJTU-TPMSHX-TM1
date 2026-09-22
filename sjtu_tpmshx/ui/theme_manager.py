"""Theme styles shared by FieldFactory and GUI builders."""
from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal


class ThemeManager(QObject):
    """Centralised theme state with change notification.

    Pass the manager to FieldFactory so newly built widgets share its styles.

    Signals
    -------
    theme_changed(str name)
        Emitted when ``set_theme`` succeeds. Payload = new theme name.
    """

    theme_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Lazy-import the theme module so that this controller can be
        # imported even before Qt is initialised (e.g. during pytest
        # collection). The first ``current_styles`` call materialises it.
        self._styles: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ helpers

    def _theme_module(self):
        from sjtu_tpmshx.ui import theme as _theme
        return _theme

    # ------------------------------------------------------------------ state

    def current_styles(self) -> Dict[str, Any]:
        """Return the latest style dict; builds it lazily on first call."""
        if self._styles is None:
            self._styles = self._theme_module()._build_styles()
        return self._styles

    def current_theme_name(self) -> str:
        return self._theme_module().get_theme_name()

    def palette(self) -> Dict[str, Any]:
        """Raw colour palette (``ui.theme.get_theme()``) — separate from
        the *style* dict (which is fully-formed QSS strings).
        """
        return self._theme_module().get_theme()

    def style(self, key: str, default: Any = '') -> Any:
        """Single-key accessor: ``manager.style('BG')`` ≡ ``_S['BG']``.

        Returns ``default`` when the requested style key is absent.
        """
        return self.current_styles().get(key, default)

    # ------------------------------------------------------------------ rebuild

    def rebuild(self) -> Dict[str, Any]:
        """Re-evaluate Qt styles and the Matplotlib palette.

        Called after a theme switch or font/density change. Does **not**
        emit ``theme_changed`` by itself — that's reserved for explicit
        ``set_theme`` calls so that swap-and-restart prompts don't fire on
        every density tweak.
        """
        self._styles = self._theme_module()._build_styles()
        # mpl theme follows palette
        try:
            self._theme_module().apply_mpl_theme()
        except Exception:
            pass
        return self._styles

    def set_theme(self, name: str) -> bool:
        """Activate the named theme. Returns True on success.

        On success: rebuilds the style dict and fires
        ``theme_changed``. The actual GUI repaint is *not* automatic —
        callers must restart or rebuild widgets (Qt cannot live-swap QSS
        across all already-constructed widgets cleanly). AppearanceMixin
        owns saved preferences and the restart action.
        """
        try:
            self._theme_module().set_theme(name)
        except Exception:
            return False
        self.rebuild()
        self.theme_changed.emit(name)
        return True

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        return f'<ThemeManager theme={self.current_theme_name()!r}>'
