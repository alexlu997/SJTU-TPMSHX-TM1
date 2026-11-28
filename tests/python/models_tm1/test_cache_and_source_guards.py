"""Geometry and production-compute cache isolation guards."""
import pytest


# ── P1.6 (2026-07-20): the remaining W7b-family cache hazards ────────


def test_compute_geometry_returns_unpoisonable_copy():
    """compute_geometry's lru_cache used to hand every caller the SAME dict;
    mutating a result poisoned all later hits (the exact W7b mechanism
    tpms_calc.compute was fixed for)."""
    from tm1.physical_models.tpms_geometry import compute_geometry
    a = compute_geometry('Diamond', 6.0, 0.4)
    a['D_h'] = -1.0                      # caller scribbles on its copy
    b = compute_geometry('Diamond', 6.0, 0.4)
    assert b['D_h'] > 0.0, "cache hit returned the poisoned shared dict"
    assert a is not b


def test_compute_geometry_cache_management_reexposed():
    from tm1.physical_models.tpms_geometry import compute_geometry
    assert callable(compute_geometry.cache_clear)
    assert compute_geometry.cache_info().maxsize == 32768


def test_phi_grid_cache_is_frozen():
    """The shared cached phi ndarray must be read-only: an in-place write
    would silently corrupt every later geometry computation at that
    (type, N) key."""
    import pytest
    from tm1.physical_models.tpms_geometry import _phi_grid
    phi = _phi_grid('Diamond', 32)
    assert phi.flags.writeable is False
    with pytest.raises((ValueError, RuntimeError)):
        phi[0, 0, 0] = 999.0


def test_chi_s_env_is_read_per_call(monkeypatch):
    """TPMSHX_CHI_S used to be read at import time only — setting it after
    the first import (monkeypatch.setenv included) was silently ignored
    (audit §5d). chi_s_eff must honor the CURRENT environment."""
    from tm1.physical_models.tpms_props import chi_s_eff
    from tests.python.geometry_reference import _CHI_S_FIT
    monkeypatch.delenv('TPMSHX_CHI_S', raising=False)
    c0, c1 = _CHI_S_FIT['Diamond']
    fit_val = chi_s_eff('Diamond', 0.6)
    assert fit_val == c0 + c1 * (1.0 - 0.6)
    monkeypatch.setenv('TPMSHX_CHI_S', '1.0')
    assert chi_s_eff('Diamond', 0.6) == 1.0
    monkeypatch.delenv('TPMSHX_CHI_S')
    assert chi_s_eff('Diamond', 0.6) == fit_val


def test_compute_cache_hits_use_current_chi_s(monkeypatch):
    from tm1.physical_models import tpms_calc
    monkeypatch.setattr(tpms_calc, '_tpms_geom', lambda *args: {
        'epsilon': .7, 'epsilon_A': .35, 'epsilon_B': .35, 'A_0': 1000., 'D_h': .002})
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




# ── W7a: geometry LUT cache honours kwargs ──────────────────────────


@pytest.mark.slow
def test_geometry_lut_cache_keys_on_kwargs(tmp_path):
    from tm1.physical_models.sigmoid_field import get_geometry_lut
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
    from tm1.physical_models import sigmoid_field

    package = tmp_path / 'installed' / 'tm1'
    (package / 'physical_models').mkdir(parents=True)
    (package / 'solvers').mkdir()
    monkeypatch.setattr(sigmoid_field, '__file__', str(package / 'physical_models' / 'sigmoid_field.py'))
    cache = tmp_path / 'user-cache'
    monkeypatch.setenv('XDG_CACHE_HOME', str(cache))
    (package / 'solvers').chmod(0o555)
    try:
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=2, N=24)
        expected = cache / 'tm1' / 'geometry' / 'lut_Gyroid_3x2_N24.npz'
        assert Path(lut._cache_path) == expected
        assert expected.is_file()
        assert list((package / 'solvers').iterdir()) == []
        monkeypatch.setattr(sigmoid_field, '_write_table', lambda *args: pytest.fail('rewrote a valid table'))
        restored = sigmoid_field.GeometryLUT('Gyroid', n_L=3, n_t=2, N=24)
        np.testing.assert_array_equal(restored.eps_table, lut.eps_table)
        np.testing.assert_array_equal(restored.A0_table, lut.A0_table)
    finally:
        (package / 'solvers').chmod(0o755)


@pytest.mark.parametrize('corruption', ['shape', 'nan', 'complex', 'object'])
def test_geometry_lut_rebuilds_invalid_cache(tmp_path, monkeypatch, corruption):
    import numpy as np
    from tm1.physical_models.sigmoid_field import GeometryLUT

    kwargs = dict(n_L=3, n_t=2, N=16, cache_dir=str(tmp_path))
    original = GeometryLUT('Gyroid', **kwargs)
    with np.load(original._cache_path, allow_pickle=False) as stored:
        data = dict(stored)
    if corruption == 'shape':
        data['eps_table'] = data['eps_table'].ravel()
    elif corruption == 'nan':
        data['A0_table'][0, 0] = np.nan
    elif corruption == 'complex':
        data['eps_table'] = data['eps_table'] + 1j
    else:
        data['tpms_type'] = np.array(['Gyroid'], dtype=object)
    np.savez_compressed(original._cache_path, **data)

    restored = GeometryLUT('Gyroid', **kwargs)
    np.testing.assert_array_equal(restored.eps_table, original.eps_table)
    np.testing.assert_array_equal(restored.A0_table, original.A0_table)
    with np.load(restored._cache_path, allow_pickle=False) as saved:
        assert saved['tpms_type'][0] == 'Gyroid'


def test_explicit_lut_directories_and_mutations_are_private(tmp_path):
    import numpy as np
    from tm1.physical_models.sigmoid_field import GeometryLUT
    from tm1.cpp_interface._native_lut import table_value

    table_value.cache_clear()
    kwargs = dict(n_L=3, n_t=2, N=16)
    generated = GeometryLUT('Gyroid', cache_dir=tmp_path / 'first', **kwargs)
    second = GeometryLUT('Gyroid', cache_dir=tmp_path / 'second', **kwargs)
    with np.load(second._cache_path, allow_pickle=False) as saved:
        custom = dict(saved)
    custom['eps_table'] = np.full((3, 2), .42, dtype=np.float32)
    np.savez_compressed(second._cache_path, **custom)
    imported = GeometryLUT('Gyroid', cache_dir=tmp_path / 'second', **kwargs)
    assert imported.eps_table.dtype == np.float32 and imported.preparation_arrays()[1] == (0, 1)
    np.testing.assert_array_equal(imported.eps_table, custom['eps_table'])
    imported.eps_table[:] = 1.
    third = GeometryLUT('Gyroid', cache_dir=tmp_path / 'third', **kwargs)
    np.testing.assert_array_equal(generated.eps_table, third.eps_table)
    assert not np.array_equal(generated.eps_table, imported.eps_table)


def test_concurrent_table_publishers_return_complete_tables(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import numpy as np
    from tm1.cpp_interface._native_lut import table_value
    from tm1.physical_models.sigmoid_field import GeometryLUT

    kwargs = dict(n_L=3, n_t=2, N=16)
    names = ('Gyroid', 'Gyroid', 'Diamond', 'Diamond')
    expected = {name: GeometryLUT(name, cache_dir=tmp_path / 'serial', **kwargs) for name in set(names)}
    table_value.cache_clear()
    barrier = Barrier(len(names))

    def publish(name):
        barrier.wait()
        return GeometryLUT(name, cache_dir=tmp_path / 'parallel', **kwargs)

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        concurrent = list(pool.map(publish, names))
    assert table_value.cache_info().currsize == 2
    for name, table in zip(names, concurrent):
        with np.load(table._cache_path, allow_pickle=False) as saved:
            for field in ('eps_table', 'A0_table'):
                np.testing.assert_array_equal(saved[field], getattr(expected[name], field))
                np.testing.assert_array_equal(getattr(table, field), saved[field])


def test_native_table_readers_keep_the_first_complete_publication_across_clear():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import numpy as np
    from tm1.cpp_interface._native_lut import table_value

    axes = np.array([4., 8.]), np.array([.3, .6])
    table_value.cache_clear()
    barrier = Barrier(4)

    def request(index):
        barrier.wait()
        if index < 2:
            pair = (np.full((2, 2), .7 + index / 10), np.full((2, 2), 1000. + index))
            held = table_value('Gyroid', 13, axes, tables=pair)
        else:
            held = table_value('Gyroid', 13, axes, find_only=True)
        barrier.wait()
        return held or table_value('Gyroid', 13, axes, find_only=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        readers = list(pool.map(request, range(4)))
    assert table_value.cache_info().currsize == 1
    table_value.cache_clear()
    for reader in readers:
        epsilon, area = reader.arrays()
        winner = int(area[0, 0] - 1000.)
        assert winner in (0, 1)
        np.testing.assert_array_equal(epsilon, np.full((2, 2), .7 + winner / 10))
        np.testing.assert_array_equal(area, readers[0].arrays()[1])


# ── compute() cache — fixed production DF + hit-copy poison guard ──


def test_compute_pins_fixed_df_backend(monkeypatch):
    from tm1.physical_models import tpms_calc
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
    from tm1.physical_models import tpms_calc
    args = ('Gyroid', 7.0, 0.6, 10.0, 422.0, 192362.0, 16.0)
    tpms_calc.compute.cache_clear()
    r1 = tpms_calc.compute(*args)
    eps_true = r1['epsilon']
    r1['epsilon'] = -999.0          # caller mutates its copy
    r2 = tpms_calc.compute(*args)   # cache hit
    assert r2['epsilon'] == eps_true, \
        "cache hit returned the mutated object — cache poisoned"
