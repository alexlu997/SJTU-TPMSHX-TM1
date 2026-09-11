"""Tests for the cF override mechanism in predict.py.

The override TABLE is empty in production (2026-06-11: a D_7_6-derived entry
was reverted — total-dP convention, production targets core-only dP).  These
tests verify (a) empty table == pure RBF bit-identical, and (b) the mechanism
works when a calibration entry is injected.
"""
import numpy as np
import pytest

import sjtu_tpmshx.df_surrogate.predict as P
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry

_EF_D7 = tpms_geometry('Diamond', 7.0, 0.6, 16.0)['epsilon'] / 2
_EF_G7 = tpms_geometry('Gyroid', 7.0, 0.6, 16.0)['epsilon'] / 2


def test_table_empty_in_production():
    assert all(len(v) == 0 for v in P._OVERRIDES.values()) or not P._OVERRIDES


def test_empty_table_is_pure_rbf(monkeypatch):
    """With the table empty, predict_K_cF must equal the raw surrogate."""
    K, cF = P.predict_K_cF('Diamond', 7.0, 0.6, _EF_D7,
                           method='gamma_df')
    K0, cF0 = P._get_model('Diamond', 'gamma_df').predict(7.0, 0.6, _EF_D7)
    assert (K, cF) == (K0, cF0)
    _, cFg = P.predict_K_cF('Gyroid', 7.0, 0.6, _EF_G7,
                            method='gamma_df')
    _, cFg0 = P._get_model('Gyroid', 'gamma_df').predict(7.0, 0.6, _EF_G7)
    assert cFg == cFg0


def test_mechanism_with_injected_entry(monkeypatch):
    monkeypatch.setitem(P._OVERRIDES, 'Diamond', [(7.0, 0.6, 454.3)])
    _, cF = P.predict_K_cF('Diamond', 7.0, 0.6, _EF_D7,
                           method='gamma_df')
    assert cF == pytest.approx(454.3, rel=1e-9)
    # far point untouched (w < cutoff)
    ef = tpms_geometry('Diamond', 5.0, 0.4, 16.0)['epsilon'] / 2
    _, cF_far = P.predict_K_cF('Diamond', 5.0, 0.4, ef,
                               method='gamma_df')
    _, cF_far0 = P._get_model('Diamond', 'gamma_df').predict(5.0, 0.4, ef)
    assert cF_far == cF_far0


def test_env_kill_switch(monkeypatch):
    monkeypatch.setitem(P._OVERRIDES, 'Diamond', [(7.0, 0.6, 454.3)])
    monkeypatch.setenv("TPMSHX_DF_OVERRIDES", "0")
    _, cF = P.predict_K_cF('Diamond', 7.0, 0.6, _EF_D7,
                           method='gamma_df')
    _, cF0 = P._get_model('Diamond', 'gamma_df').predict(7.0, 0.6, _EF_D7)
    assert cF == cF0


def test_blend_smooth_with_injected_entry(monkeypatch):
    monkeypatch.setitem(P._OVERRIDES, 'Diamond', [(7.0, 0.6, 454.3)])
    cfs = []
    for L in [6.6, 6.8, 6.9, 7.0]:
        ef = tpms_geometry('Diamond', L, 0.6, 16.0)['epsilon'] / 2
        _, cF = P.predict_K_cF('Diamond', L, 0.6, ef,
                               method='gamma_df')
        cfs.append(cF)
    diffs = np.diff([abs(c - 454.3) for c in cfs])
    assert (diffs <= 1e-9).all()
    assert cfs[-1] == pytest.approx(454.3, rel=1e-9)
