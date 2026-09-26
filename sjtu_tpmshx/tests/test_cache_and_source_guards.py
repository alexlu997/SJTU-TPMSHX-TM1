"""Geometry and production-compute cache isolation guards."""
import pytest


# ── P1.6 (2026-07-20): the remaining W7b-family cache hazards ────────


def test_compute_geometry_returns_unpoisonable_copy():
    """compute_geometry's lru_cache used to hand every caller the SAME dict;
    mutating a result poisoned all later hits (the exact W7b mechanism
    tpms_calc.compute was fixed for)."""
    from sjtu_tpmshx.models.tpms_geometry import compute_geometry
    a = compute_geometry('Diamond', 6.0, 0.4)
    a['D_h'] = -1.0                      # caller scribbles on its copy
    b = compute_geometry('Diamond', 6.0, 0.4)
    assert b['D_h'] > 0.0, "cache hit returned the poisoned shared dict"
    assert a is not b


def test_compute_geometry_cache_management_reexposed():
    from sjtu_tpmshx.models.tpms_geometry import compute_geometry
    assert callable(compute_geometry.cache_clear)
    assert compute_geometry.cache_info().maxsize == 32768


def test_phi_grid_cache_is_frozen():
    """The shared cached phi ndarray must be read-only: an in-place write
    would silently corrupt every later geometry computation at that
    (type, N) key."""
    import pytest
    from sjtu_tpmshx.models.tpms_geometry import _phi_grid
    phi = _phi_grid('Diamond', 32)
    assert phi.flags.writeable is False
    with pytest.raises((ValueError, RuntimeError)):
        phi[0, 0, 0] = 999.0


def test_chi_s_env_is_read_per_call(monkeypatch):
    """TPMSHX_CHI_S used to be read at import time only — setting it after
    the first import (monkeypatch.setenv included) was silently ignored
    (audit §5d). chi_s_eff must honor the CURRENT environment."""
    from sjtu_tpmshx.models.tpms_props import chi_s_eff, _CHI_S_FIT
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    c0, c1 = _CHI_S_FIT['Diamond']
    fit_val = chi_s_eff('Diamond', 0.6)
    assert fit_val == c0 + c1 * (1.0 - 0.6)
    monkeypatch.setenv('TPMSHX_CHI_S', '1.0')
    assert chi_s_eff('Diamond', 0.6) == 1.0
    monkeypatch.delenv('TPMSHX_CHI_S')
    assert chi_s_eff('Diamond', 0.6) == fit_val


def test_compute_cache_hits_use_current_chi_s(monkeypatch):
    from sjtu_tpmshx.models import tpms_calc
    monkeypatch.setattr(tpms_calc, '_tpms_geom', lambda *args: {
        'epsilon': .7, 'A_0': 1000., 'D_h': .002})
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    args = ('Gyroid', 6., .4, 10., 300., 200000., 16.)
    tpms_calc.compute.cache_clear()
    try:
        fitted = tpms_calc.compute(*args)
        monkeypatch.setenv('TPMSHX_CHI_S', '.5')
        half = tpms_calc.compute(*args)
        assert half['K_ss'] == pytest.approx(2.4)
        monkeypatch.setenv('TPMSHX_CHI_S', '1.0')
        assert tpms_calc.compute(*args)['K_ss'] == pytest.approx(4.8)
        assert half['K_ss'] == pytest.approx(2.4)
        monkeypatch.delenv('TPMSHX_CHI_S')
        assert tpms_calc.compute(*args) == fitted
        assert tpms_calc.compute.cache_info().misses == 1
        assert tpms_calc.compute.cache_info().hits == 3
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
        with pytest.raises(ValueError):
            tpms_calc.compute(*args)
    finally:
        tpms_calc.compute.cache_clear()


def test_laplacian_amg_cache_reset_hook():
    from sjtu_tpmshx.solvers.ltne_energy_3d import (_LAPLACIAN_AMG_CACHE,
                                        clear_laplacian_amg_cache)
    _LAPLACIAN_AMG_CACHE[(2, 2, 2)] = {'probe': True}
    clear_laplacian_amg_cache()
    assert _LAPLACIAN_AMG_CACHE == {}


# ── W7a: geometry LUT cache honours kwargs ──────────────────────────


@pytest.mark.slow
def test_geometry_lut_cache_keys_on_kwargs(tmp_path):
    from sjtu_tpmshx.models.sigmoid_field import get_geometry_lut
    lut_a = get_geometry_lut('Gyroid', n_L=3, n_t=2, N=32,
                             cache_dir=str(tmp_path))
    lut_b = get_geometry_lut('Gyroid', n_L=4, n_t=2, N=32,
                             cache_dir=str(tmp_path))
    assert lut_a is not lut_b, \
        "different kwargs returned the same cached LUT (stale-geometry bug)"
    assert len(lut_a.L_vals) == 3 and len(lut_b.L_vals) == 4
    # same kwargs → same instance (the cache still caches)
    lut_a2 = get_geometry_lut('Gyroid', n_L=3, n_t=2, N=32,
                              cache_dir=str(tmp_path))
    assert lut_a2 is lut_a


def test_geometry_lut_uses_external_cache_with_read_only_package(tmp_path, monkeypatch):
    from pathlib import Path
    import numpy as np
    from sjtu_tpmshx.models import sigmoid_field

    package = tmp_path / 'installed' / 'sjtu_tpmshx'
    (package / 'models').mkdir(parents=True)
    (package / 'solvers').mkdir()
    monkeypatch.setattr(sigmoid_field, '__file__', str(package / 'models' / 'sigmoid_field.py'))
    cache = tmp_path / 'user-cache'
    monkeypatch.setenv('XDG_CACHE_HOME', str(cache))
    (package / 'solvers').chmod(0o555)
    try:
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=2, N=24)
        expected = cache / 'sjtu-tpmshx' / 'geometry' / 'lut_Gyroid_3x2_N24.npz'
        assert Path(lut._cache_path) == expected
        assert expected.is_file()
        assert list((package / 'solvers').iterdir()) == []
        def no_rebuild(self):
            pytest.fail('second load ignored the persistent user cache')
        monkeypatch.setattr(sigmoid_field.GeometryLUT, '_precompute', no_rebuild)
        restored = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=2, N=24)
        np.testing.assert_array_equal(restored.eps_table, lut.eps_table)
        np.testing.assert_array_equal(restored.A0_table, lut.A0_table)
    finally:
        (package / 'solvers').chmod(0o755)


# ── compute() cache — fixed production DF + hit-copy poison guard ──


def test_compute_pins_fixed_df_backend(monkeypatch):
    from sjtu_tpmshx.models import tpms_calc
    args = ('Gyroid', 7.0, 0.6, 10.0, 422.0, 192362.0, 16.0)

    monkeypatch.delenv('TPMSHX_DF_METHOD', raising=False)
    tpms_calc.compute.cache_clear()
    r_default = tpms_calc.compute(*args)
    info_after_first = tpms_calc.compute.cache_info()

    monkeypatch.setenv('TPMSHX_DF_METHOD', 'rbf')
    r_rbf = tpms_calc.compute(*args)
    info_after_switch = tpms_calc.compute.cache_info()

    assert info_after_switch.hits == info_after_first.hits + 1
    assert r_rbf['K_df'] == r_default['K_df']
    assert r_rbf['cF_df'] == r_default['cF_df']
    # A cold cache must pin the same model; a warm hit alone cannot prove it.
    tpms_calc.compute.cache_clear()
    assert tpms_calc.compute(*args) == r_default


def test_compute_hit_returns_unpoisonable_copy():
    from sjtu_tpmshx.models import tpms_calc
    args = ('Gyroid', 7.0, 0.6, 10.0, 422.0, 192362.0, 16.0)
    tpms_calc.compute.cache_clear()
    r1 = tpms_calc.compute(*args)
    eps_true = r1['epsilon']
    r1['epsilon'] = -999.0          # caller mutates its copy
    r2 = tpms_calc.compute(*args)   # cache hit
    assert r2['epsilon'] == eps_true, \
        "cache hit returned the mutated object — cache poisoned"
