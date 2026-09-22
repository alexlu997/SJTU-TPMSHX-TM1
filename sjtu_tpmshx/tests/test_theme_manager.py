"""Unit tests for ui.theme_manager.ThemeManager.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication

from sjtu_tpmshx.ui.theme_manager import ThemeManager


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


# ---------------------------------------------------------------- basics


def test_lazy_styles_build_on_first_call():
    _app()
    tm = ThemeManager()
    assert tm._styles is None
    s = tm.current_styles()
    assert isinstance(s, dict)
    assert 'BG' in s
    assert tm._styles is s   # cached


def test_style_accessor_returns_default_for_missing_key():
    _app()
    tm = ThemeManager()
    assert tm.style('NOPE_DOES_NOT_EXIST', 'fallback') == 'fallback'


def test_current_theme_name_returns_string():
    _app()
    tm = ThemeManager()
    assert isinstance(tm.current_theme_name(), str)


def test_palette_is_dict():
    _app()
    tm = ThemeManager()
    p = tm.palette()
    assert isinstance(p, dict)
    assert 'bg' in p


# ---------------------------------------------------------------- signal






# ---------------------------------------------------------------- repr


def test_repr_safe():
    _app()
    tm = ThemeManager()
    s = repr(tm)
    assert 'ThemeManager' in s
    assert tm.current_theme_name() in s
