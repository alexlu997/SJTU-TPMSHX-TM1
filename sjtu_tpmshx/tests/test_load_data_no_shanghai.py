"""Pytest guard for df_surrogate.load_data Shanghai-exclusion invariant.

C.5 of the 2026-05-06 audit fix campaign. The Nu / D-F surrogates fit
on this DataFrame are the *prediction model* for the Shanghai 16-case
validation. If Shanghai rows ever leak into the training set the
reported headline number (Q air RMSRE 1.71 %) loses its out-of-sample
meaning. This test asserts:

1. ``load_all()`` succeeds (no spurious leakage from current Excel).
2. The result contains zero rows with the Shanghai geometry
   ``(L=7 mm, t=0.6 mm)``.
3. ``_assert_no_shanghai_leakage`` raises on a synthetic contaminated
   frame (positive control — proves the guard isn't no-op).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

# Raw training Excel is a local asset (data/ is gitignored) — skip cleanly
# on checkouts without it (CI) instead of FileNotFoundError.
_RAW_XLSX = ROOT.parent / 'data' / 'raw_data' / 'experiments/air/air_DG_specimen_experiment_summary.xlsx'
requires_training_excel = pytest.mark.skipif(
    not _RAW_XLSX.exists(),
    reason='local training Excel (gitignored data/) not present')


# ---------------------------------------------------------------- live load


@requires_training_excel
def test_load_all_succeeds_with_real_excel():
    """If this test fails, either the Excel file moved or the leakage
    guard tripped. Either way: investigate, don't silence."""
    from sjtu_tpmshx.df_surrogate.load_data import load_all
    df = load_all()
    assert len(df) > 0, "training Excel returned 0 rows"
    assert {'tpms', 'L_mm', 't_mm', 'Re', 'u_mps', 'dP_Pa'} <= set(df.columns)


@requires_training_excel
def test_no_shanghai_geometry_in_training():
    from sjtu_tpmshx.df_surrogate.load_data import load_all
    df = load_all()
    n_t06 = int((df['t_mm'] == 0.6).sum())
    n_L7 = int((df['L_mm'] == 7.0).sum())
    assert n_t06 == 0, f"{n_t06} training rows have t_mm=0.6 (Shanghai)"
    assert n_L7 == 0, f"{n_L7} training rows have L_mm=7.0 (Shanghai)"


@requires_training_excel
def test_training_geometries_are_the_documented_set():
    """Lock in the exact geometry coverage of the training Excel."""
    from sjtu_tpmshx.df_surrogate.load_data import load_all
    df = load_all()
    pairs = sorted(set(zip(df['L_mm'], df['t_mm'])))
    expected = sorted([(L, t)
                       for L in (4.0, 5.0, 6.0, 8.0)
                       for t in (0.3, 0.4, 0.5)])
    assert pairs == expected, (
        f"training geometry coverage drift — got {pairs}, "
        f"expected {expected}")


# ---------------------------------------------------------------- positive control


@pytest.mark.parametrize('source', [
    'water-air_G7-t0p6_shanghai_experiment_20260401.xlsx',
    'water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx',
])
def test_renamed_shanghai_sources_remain_excluded(source):
    from sjtu_tpmshx.df_surrogate.load_data import _assert_no_shanghai_leakage
    clean = pd.DataFrame({'tpms': ['Diamond'], 'L_mm': [5.0], 't_mm': [0.4]})
    with pytest.raises(ValueError, match='Shanghai keyword'):
        _assert_no_shanghai_leakage(
            clean, source=Path('data/raw_data/experiments/water_air') / source)


def test_assert_helper_raises_on_t06_leakage():
    """Synthetic contaminated frame: guard must trip on t=0.6."""
    from sjtu_tpmshx.df_surrogate.load_data import _assert_no_shanghai_leakage
    bad = pd.DataFrame({
        'tpms': ['Gyroid'],
        'L_mm': [7.0],
        't_mm': [0.6],
    })
    with pytest.raises(ValueError, match=r't_mm=0\.6'):
        _assert_no_shanghai_leakage(bad)


def test_assert_helper_raises_on_L7_leakage_even_without_t06():
    """L=7 alone (without t=0.6) should also trip."""
    from sjtu_tpmshx.df_surrogate.load_data import _assert_no_shanghai_leakage
    bad = pd.DataFrame({
        'tpms': ['Diamond'],
        'L_mm': [7.0],
        't_mm': [0.4],   # not Shanghai's t, but L is
    })
    with pytest.raises(ValueError, match=r'L_mm=7'):
        _assert_no_shanghai_leakage(bad)


def test_assert_helper_passes_clean_training_frame():
    from sjtu_tpmshx.df_surrogate.load_data import _assert_no_shanghai_leakage
    ok = pd.DataFrame({
        'tpms': ['Diamond', 'Gyroid'],
        'L_mm': [5.0, 8.0],
        't_mm': [0.4, 0.3],
    })
    # Should not raise.
    _assert_no_shanghai_leakage(ok)
