"""Unit tests for controllers.result_cache.ResultCache.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication

from sjtu_tpmshx.controllers.result_cache import ResultCache


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


# ---------------------------------------------------------------- result API


def test_set_get_result_per_mode():
    _app()
    c = ResultCache()
    assert c.get_result('2d') is None
    payload = {'Q': 1234.5, 'dP': 6789.0}
    c.set_result('2d', payload)
    assert c.get_result('2d') == payload
    assert c.get_result('3d') is None   # mode isolation


def test_set_result_with_none_clears():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    assert c.has_results('2d')
    c.set_result('2d', None)
    assert not c.has_results('2d')


@pytest.mark.parametrize('mode', ['quantum', 'poly'])
def test_invalid_mode_raises(mode):
    _app()
    c = ResultCache()
    with pytest.raises(ValueError, match='unknown mode'):
        c.set_result(mode, {})
    with pytest.raises(ValueError, match='unknown mode'):
        c.get_result(mode)


def test_has_results_aggregate():
    _app()
    c = ResultCache()
    assert not c.has_any_results()
    assert not c.has_results()
    c.set_result('3d', {'x': 1})
    assert c.has_any_results()
    assert c.has_results('3d')
    assert not c.has_results('2d')


def test_clear_one_or_all():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    c.set_result('3d', {'b': 2})

    c.clear('2d')
    assert not c.has_results('2d')
    assert c.has_results('3d')

    c.clear()   # clear all
    assert not c.has_any_results()


# ---------------------------------------------------------------- signals


def test_results_changed_signal_emits():
    _app()
    c = ResultCache()
    received = []
    c.results_changed.connect(lambda m: received.append(m))

    c.set_result('2d', {'a': 1})
    c.set_result('3d', {'b': 2})
    c.clear('2d')

    assert received == ['2d', '3d', '2d']


# ---------------------------------------------------------------- tabs


def test_drawn_tabs_tracking():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})

    assert c.get_drawn_tabs() == set()
    assert not c.is_drawn('temp')
    c.mark_drawn('temp')
    c.mark_drawn('pres')
    assert c.is_drawn('temp')
    assert c.is_drawn('pres')
    assert c.get_drawn_tabs() == {'temp', 'pres'}


def test_set_result_clears_drawn_tabs():
    """New results invalidate prior tab renders."""
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    c.mark_drawn('temp')
    c.mark_drawn('vel')
    assert c.get_drawn_tabs() == {'temp', 'vel'}

    c.set_result('2d', {'a': 2})
    assert c.get_drawn_tabs() == set()


def test_replace_drawn_tabs_legacy():
    """Legacy assignment pattern: window._drawn_tabs = some_set."""
    _app()
    c = ResultCache()
    c.replace_drawn_tabs({'temp', 'pres', '3d'})
    assert c.get_drawn_tabs() == {'temp', 'pres', '3d'}


# ---------------------------------------------------------------- repr


def test_repr_shows_state():
    _app()
    c = ResultCache()
    s = repr(c)
    assert '2d=-' in s and '3d=-' in s
    c.set_result('2d', {'x': 1})
    s = repr(c)
    assert '2d=+' in s and '3d=-' in s
