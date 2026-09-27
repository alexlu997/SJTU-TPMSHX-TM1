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


def test_dialog_theme_applies_first_and_changed_styles_only(monkeypatch):
    from unittest.mock import Mock
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.ui.mixins.dialogs import DialogsMixin
    from sjtu_tpmshx.ui.theme import get_theme, get_theme_name, set_theme

    app = QApplication.instance()
    previous_style, previous_theme = app.styleSheet(), get_theme_name()
    dialogs = DialogsMixin()
    try:
        app.setStyleSheet('')
        set_theme('light')
        with monkeypatch.context() as patch:
            setter = Mock(wraps=app.setStyleSheet)
            patch.setattr(app, 'setStyleSheet', setter)
            dialogs._install_dialog_theme()
            assert setter.call_count == 1
            assert f"QMessageBox{{background:{get_theme()['bg']};}}" in app.styleSheet()
            light_style = app.styleSheet()
            dialogs._install_dialog_theme()
            assert setter.call_count == 1

            set_theme('dark')
            dialogs._install_dialog_theme()
            assert setter.call_count == 2
            assert app.styleSheet() != light_style
            assert f"QMessageBox{{background:{get_theme()['bg']};}}" in app.styleSheet()
            dialogs._install_dialog_theme()
            assert setter.call_count == 2
    finally:
        set_theme(previous_theme)
        app.setStyleSheet(previous_style)


# ---------------------------------------------------------------- signal






# ---------------------------------------------------------------- repr


def test_repr_safe():
    _app()
    tm = ThemeManager()
    s = repr(tm)
    assert 'ThemeManager' in s
    assert tm.current_theme_name() in s
