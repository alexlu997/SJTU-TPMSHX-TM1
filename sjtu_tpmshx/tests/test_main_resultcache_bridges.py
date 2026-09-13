"""Tests for the ``Main_Menu`` ResultCache property bridges — audit
C5 Phase 5 (L-b, 2026-05-28).

Before Phase 5, ``main.py`` carried 6 inline attributes
(``_compute_results``, ``_result_3d``, ``_has_results_2d``,
``_has_results_3d``, ``_has_results``, ``_drawn_tabs``) that were
dual-written alongside ``self.cache`` (ResultCache).  Phase 5 turns
each name into an @property that delegates read/write to
``self.cache``, eliminating the dual-write pattern.

Tests verify the property semantics on a lite stand-in that owns a
real ``ResultCache``: setting / reading / clearing / consistent
flag derivation.
"""
from __future__ import annotations

import pytest

# Importing ResultCache requires PySide6 (QObject base) — these tests
# skip cleanly if PySide6 is not available, matching the rest of the
# Qt-adjacent test suite.
pytest.importorskip('PySide6')

from sjtu_tpmshx.controllers.result_cache import ResultCache  # noqa: E402


# ── lite Main_Menu stub — keeps only the @property bridges ──────────


def _make_bridge_class():
    from sjtu_tpmshx.ui.mixins.result_bridge import ResultBridgeMixin

    class _BridgedMenu(ResultBridgeMixin):
        def __init__(self):
            self.cache = ResultCache()

    return _BridgedMenu


@pytest.fixture
def m():
    return _make_bridge_class()()


# ── 2D result bridge ────────────────────────────────────────────────


def test_compute_results_empty_by_default(m):
    assert m._compute_results == {}
    assert m._has_results_2d is False


def test_compute_results_set_and_read(m):
    payload = {'Ta': [1, 2, 3], 'Q_total': 100.0}
    m._compute_results = payload
    assert m._compute_results == payload
    # Flag derives from cache, not a separate field.
    assert m._has_results_2d is True
    # Aggregate flag covers 2D.
    assert m._has_results is True


def test_compute_results_empty_dict_clears(m):
    m._compute_results = {'foo': 'bar'}
    assert m._has_results_2d is True
    m._compute_results = {}   # legacy "clear" sentinel
    assert m._has_results_2d is False
    assert m._compute_results == {}


def test_compute_results_none_clears(m):
    m._compute_results = {'foo': 'bar'}
    m._compute_results = None
    assert m._has_results_2d is False


# ── 3D result bridge ────────────────────────────────────────────────


def test_result_3d_default_none(m):
    assert m._result_3d is None
    assert m._has_results_3d is False


def test_result_3d_set_and_read(m):
    res = {'Q': 250.0, 'dP': 1200.0}
    m._result_3d = res
    assert m._result_3d == res
    assert m._has_results_3d is True
    assert m._has_results is True


# ── flag setter behaviour ───────────────────────────────────────────


def test_has_results_2d_setter_false_clears(m):
    m._compute_results = {'foo': 'bar'}
    assert m._has_results_2d is True
    m._has_results_2d = False
    assert m._has_results_2d is False
    assert m._compute_results == {}


def test_has_results_3d_setter_false_clears(m):
    m._result_3d = {'Q': 100}
    assert m._has_results_3d is True
    m._has_results_3d = False
    assert m._has_results_3d is False
    assert m._result_3d is None


def test_has_results_setter_false_clears_all(m):
    m._compute_results = {'a': 1}
    m._result_3d = {'b': 2}
    assert m._has_results is True
    m._has_results = False
    assert m._has_results is False
    assert m._compute_results == {}
    assert m._result_3d is None


def test_has_results_setter_true_is_noop_without_payload(m):
    # Setting True without paired payload write does NOT fabricate
    # a result — flag derives from cache, not from setter argument.
    m._has_results_2d = True
    assert m._has_results_2d is False  # still no cache payload


# ── drawn_tabs bridge ───────────────────────────────────────────────


def test_drawn_tabs_default_empty(m):
    assert m._drawn_tabs == set()


def test_drawn_tabs_replace(m):
    m._drawn_tabs = {'temp', 'vel'}
    assert m._drawn_tabs == {'temp', 'vel'}


def test_drawn_tabs_cleared_by_set_result(m):
    """Setting a new 2D result resets the drawn-tabs set so each
    canvas repaints when the user navigates to its tab."""
    m._drawn_tabs = {'temp', 'vel'}
    assert m._drawn_tabs == {'temp', 'vel'}
    m._compute_results = {'Ta': [1]}
    # Per ResultCache.set_result, drawn_tabs cleared on new result.
    assert m._drawn_tabs == set()


# ── single source of truth invariant ────────────────────────────────


def test_no_dual_storage(m):
    """The @property bridge means ``_compute_results`` is NOT a
    regular instance attribute.  Assignment goes through the setter
    + lands in ``self.cache``, not in ``self.__dict__``."""
    m._compute_results = {'foo': 1}
    assert '_compute_results' not in m.__dict__
    # And the cache really has it.
    assert m.cache.get_result('2d') == {'foo': 1}
