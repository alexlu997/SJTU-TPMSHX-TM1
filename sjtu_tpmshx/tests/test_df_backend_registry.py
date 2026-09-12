"""Fixed CFD values, broadcast parity, and retired-method rejection."""
import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate import predict as P
from sjtu_tpmshx.df_surrogate.backend import (available_methods,
                                  get_backend)
from sjtu_tpmshx.models.tpms_calc import geometry as _geom

_EF = {tp: _geom(tp, 7.0, 0.6, 16.0)['epsilon'] / 2
       for tp in ('Gyroid', 'Diamond')}

# (tpms, method) -> (K, cF) at L=7.0, t=0.6, eps_f=_EF — exact values.
_GOLDEN = {
    ('Gyroid', 'cfd_full_core_3cell_fixed_v2'):
        (5.3704042886967827e-08, 199.05002405781562),
    ('Diamond', 'cfd_full_core_3cell_fixed_v2'):
        (4.4351442017543415e-08, 241.08433725023596),
}


@pytest.mark.parametrize('tpms,method', list(_GOLDEN))
def test_golden_point_values_cross_platform(tpms, method):
    K, cF = P.predict_K_cF(tpms, 7.0, 0.6, _EF[tpms], method=method)
    K_ref, cF_ref = _GOLDEN[(tpms, method)]
    np.testing.assert_allclose(K, K_ref, rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(cF, cF_ref, rtol=1e-12, atol=0.0)


def test_scalar_vec_parity():
    L = np.array([5.0, 7.0, 6.0])
    t = np.array([0.4, 0.6, 0.5])
    Kv, cv = P.predict_K_cF_vec('Gyroid', L, t, _EF['Gyroid'])
    for i in range(L.size):
        Ks, cs = P.predict_K_cF('Gyroid', L[i], t[i], _EF['Gyroid'])
        assert Kv[i] == Ks and cv[i] == cs


@pytest.mark.parametrize('method', ['gamma_df', 'rbf', 'plhub_gp_typo'])
def test_retired_or_unknown_method_rejected(method, monkeypatch):
    with pytest.raises(ValueError, match='unknown DF method'):
        P.predict_K_cF('Gyroid', 7.0, 0.6, .36, method=method)
    monkeypatch.setenv('TPMSHX_DF_METHOD', method)
    with pytest.raises(ValueError, match='unknown DF method'):
        P.predict_K_cF_vec('Gyroid', np.array([7.0]), .6, .36)
    assert P.predict_K_cF('Gyroid', 7.0, .6, .36, method=P.SCO2_DF_METHOD) == _GOLDEN[('Gyroid', P.SCO2_DF_METHOD)]


def test_supported_method_surface():
    assert available_methods() == ('cfd_full_core_3cell_fixed_v2',)
    b = get_backend('Gyroid', P.SCO2_DF_METHOD)
    assert get_backend('Gyroid', P.SCO2_DF_METHOD) is b


def test_fixed_sco2_backend_interpolates_geometry_and_rejects_extrapolation():
    got = P.predict_K_cF(
        'Diamond', 7.5, 0.55, _EF['Diamond'],
        method='cfd_full_core_3cell_fixed_v2',
    )
    corners = [
        P.predict_K_cF('Diamond', L, t, _EF['Diamond'],
                       method='cfd_full_core_3cell_fixed_v2')
        for L in (7.0, 8.0) for t in (0.5, 0.6)
    ]
    assert got == pytest.approx(tuple(np.mean(corners, axis=0)))
    with pytest.raises(ValueError, match='outside the fixed sCO2 CFD grid'):
        P.predict_K_cF(
            'Diamond', 8.1, 0.6, _EF['Diamond'],
            method='cfd_full_core_3cell_fixed_v2',
        )


def test_production_fixed_df_is_independent_of_fluid_and_reynolds():
    from sjtu_tpmshx.models.tpms_calc import compute

    compute.cache_clear()
    cases = (
        ('air', 2.0, 320.0, 101325.0),
        ('water', 0.2, 320.0, 200000.0),
        ('sco2', 8.0, 320.0, 12e6),
    )
    coeffs = []
    for fluid, velocity, temperature, pressure in cases:
        result = compute(
            'Gyroid', 7.0, 0.6, velocity, temperature, pressure, 16.0,
            fluid_type=fluid,
        )
        coeffs.append((result['K_df'], result['cF_df']))
    assert coeffs[0] == coeffs[1] == coeffs[2]
