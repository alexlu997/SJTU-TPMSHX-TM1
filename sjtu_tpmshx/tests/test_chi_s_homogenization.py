"""B2 chi_S homogenization (2026-07-06).

Covers:
  * homogenizer analytic exactness (full solid, laminate series/parallel)
    and cubic-symmetry isotropy on a small grid;
  * the baked chi_s_eff(type, eps) fit — pinned Shanghai value, monotone
    trend, ndarray vectorization;
  * priority chain: explicit geometry(chi_s=...) > env constant > fit;
  * K_ss integration through tpms_calc.compute().
"""
import importlib.util
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent

from sjtu_tpmshx.models.tpms_props import chi_s_eff, geometry
from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute

_HOM_PATH = _PROJECT_ROOT / 'runs' / 'tools' / 'homogenize_chi_s.py'
_spec = importlib.util.spec_from_file_location('homogenize_chi_s', _HOM_PATH)
hom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hom)


# ── homogenizer numerics ─────────────────────────────────────────

def test_full_solid_keff_is_one():
    solid = np.ones((24, 24, 24), dtype=bool)
    k_eff, it, _ = hom._solve_chi(solid, 0)
    assert abs(k_eff - 1.0) < 1e-9 and it == 0


def test_laminate_series_and_parallel():
    N = 32
    solid = np.zeros((N, N, N), dtype=bool)
    solid[: N // 2] = True
    k_series, *_ = hom._solve_chi(solid, 0)     # normal to slabs
    k_par, *_ = hom._solve_chi(solid, 1)        # along slabs
    k_series_exact = 1.0 / (0.5 + 0.5 / hom.K_VOID)
    k_par_exact = 0.5 * (1.0 + hom.K_VOID)
    assert abs(k_series - k_series_exact) / k_series_exact < 0.05
    assert abs(k_par - k_par_exact) / k_par_exact < 1e-4


def test_gyroid_isotropy_small_grid():
    """Cubic symmetry → identical chi on all three axes."""
    eps, chis, _ = hom.chi_s('Gyroid', 0.6 / 7.0, N=32, axes=(0, 1, 2))
    v = list(chis.values())
    assert max(v) - min(v) < 1e-6 * max(v), v
    assert 0.4 < v[0] < 0.9


# ── baked fit ────────────────────────────────────────────────────

def test_chi_s_eff_pinned_shanghai():
    """Gyroid at the Shanghai point (eps=0.7367): chi ≈ 0.650."""
    chi = chi_s_eff('Gyroid', 0.7367)
    assert abs(chi - 0.650) < 0.005, chi
    chi_d = chi_s_eff('Diamond', 0.7367)
    assert abs(chi_d - 0.6437) < 0.005, chi_d


def test_chi_s_eff_monotone_and_bounded():
    eps = np.linspace(0.27, 0.91, 20)
    for tp in ('Diamond', 'Gyroid'):
        chi = chi_s_eff(tp, eps)
        assert chi.shape == eps.shape           # vectorized
        assert np.all(np.diff(chi) < 0)         # decreasing with eps
        assert np.all((chi > 0.5) & (chi < 0.9))


def test_priority_explicit_over_env_over_fit(monkeypatch):
    # env constant overrides fit — patch the ENVIRONMENT: chi_s_eff reads
    # TPMSHX_CHI_S per call since P1.6 (2026-07-20). The old import-frozen
    # _CHI_S_ENV snapshot forced this test to patch a module global; that
    # mechanism is gone (and setenv now works the way a reader expects).
    monkeypatch.setenv('TPMSHX_CHI_S', '0.42')
    assert chi_s_eff('Gyroid', 0.7) == 0.42
    arr = chi_s_eff('Gyroid', np.array([0.5, 0.7]))
    assert np.all(arr == 0.42)
    # explicit geometry(chi_s=...) wins over env
    g = geometry('Gyroid', 7.0, 0.6, k_s=16.0, chi_s=0.9)
    assert abs(g['K_ss'] - 0.9 * (1 - g['epsilon']) * 16.0) < 1e-12
    monkeypatch.delenv('TPMSHX_CHI_S')
    # fit path again
    assert abs(chi_s_eff('Gyroid', 0.7367) - 0.650) < 0.005


def test_kss_integration_tpms_compute():
    """tpms_calc.compute() K_ss must equal chi_s_eff*(1-eps)*k_s."""
    r = tpms_compute('Gyroid', 7.0, 0.6, u=5.0,
                     T_in_K=322.0, P_in_Pa=101325.0, k_s=16.0)
    eps = r['epsilon']
    expected = chi_s_eff('Gyroid', eps) * (1.0 - eps) * 16.0
    assert abs(r['K_ss'] - expected) / expected < 1e-12
    # sanity: ~35% below the old uncalibrated value
    assert r['K_ss'] < 0.75 * (1.0 - eps) * 16.0


if __name__ == '__main__':
    test_full_solid_keff_is_one()
    test_laminate_series_and_parallel()
    test_gyroid_isotropy_small_grid()
    test_chi_s_eff_pinned_shanghai()
    test_chi_s_eff_monotone_and_bounded()
    test_kss_integration_tpms_compute()
    print("ALL DIRECT-RUN TESTS PASS")
