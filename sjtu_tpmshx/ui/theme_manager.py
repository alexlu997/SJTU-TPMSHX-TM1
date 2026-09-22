"""Theme styles shared by FieldFactory and GUI builders."""
from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QObject


class ThemeManager(QObject):
    """Shared style cache for FieldFactory and GUI builders."""

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

        Called after font/density changes or during startup.
        """
        self._styles = self._theme_module()._build_styles()
        # mpl theme follows palette
        try:
            self._theme_module().apply_mpl_theme()
        except Exception:
            pass
        return self._styles


    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        return f'<ThemeManager theme={self.current_theme_name()!r}>'
