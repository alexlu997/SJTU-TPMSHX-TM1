"""W6 + W7 guards (blind-spot audit, 2026-07-07).

W6: SurrogateV3's two calibration sources (local Excel vs committed
prebuilt CSV) must produce the same surrogate — the production GammaDF
anchor derives from this instance, so a silent divergence means two
machines compute different physics.

W7: two cache-key hazards —
  (a) get_geometry_lut's in-memory singleton ignored kwargs on a hit;
  (b) tpms_calc.compute's lru_cache ignored the DF-backend env state and
      returned the same mutable dict on every hit.
"""
import logging
import pathlib

import pytest


# ── W6: xlsx vs prebuilt-CSV source parity ──────────────────────────


def test_df_source_parity(monkeypatch):
    """Excel-calibrated and prebuilt-CSV surrogates must agree at the
    Shanghai gate point (and record which source they used)."""
    import sjtu_tpmshx.df_surrogate.surrogate_v3 as sv3mod
    if not sv3mod.XLSX.exists():
        pytest.skip("experiment Excel (gitignored data/) not present")

    m_xlsx = sv3mod.SurrogateV3(tpms='Gyroid')
    assert m_xlsx._source == 'xlsx'

    monkeypatch.setattr(sv3mod, 'XLSX',
                        pathlib.Path('__nonexistent_w6_probe__.xlsx'))
    m_csv = sv3mod.SurrogateV3(tpms='Gyroid')
    assert m_csv._source == 'prebuilt_csv'

    for (L, t) in ((7.0, 0.6), (5.0, 0.4), (6.0, 0.5)):
        K1, cF1 = m_xlsx.predict(L, t)
        K2, cF2 = m_csv.predict(L, t)
        assert K1 == pytest.approx(K2, rel=1e-6), \
            f"K diverged at (L={L}, t={t}): xlsx {K1:.6e} vs csv {K2:.6e}"
        assert cF1 == pytest.approx(cF2, rel=1e-6), \
            f"cF diverged at (L={L}, t={t}): xlsx {cF1:.6e} vs csv {cF2:.6e}"


def test_df_prebuilt_fallback_warns(monkeypatch, caplog):
    """The prebuilt-CSV fallback must be LOUD. The info-level version let a
    machine silently compute from a different calibration source (the
    riskiest trap of the 2026-07 server port, HANDOFF §8)."""
    import sjtu_tpmshx.df_surrogate.surrogate_v3 as sv3mod
    monkeypatch.setattr(sv3mod, 'XLSX',
                        pathlib.Path('__nonexistent_p03_probe__.xlsx'))
    # tpmshx's namespaced root logger has propagate=False, so caplog's
    # root-attached handler never sees these records — attach directly.
    sv3mod._log.addHandler(caplog.handler)
    try:
        m = sv3mod.SurrogateV3(tpms='Gyroid')
    finally:
        sv3mod._log.removeHandler(caplog.handler)
    assert m._source == 'prebuilt_csv'
    banner = [r for r in caplog.records
              if r.levelno >= logging.WARNING
              and 'CALIBRATION SOURCE FALLBACK' in r.getMessage()]
    assert banner, "prebuilt fallback must log a WARNING banner"


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
    assert compute_geometry.cache_info().maxsize == 4096


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
