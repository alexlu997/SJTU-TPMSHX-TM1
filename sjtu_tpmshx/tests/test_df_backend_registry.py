"""B2 2.2 — DF backend registry equivalence + contract guards.

Golden tuples below were captured from the pre-registry dispatch on
2026-06-12 (gamma cF 534.8 == Shanghai gate point; Diamond-7 rbf cF 745
== the falsified extrapolation the D_7_6 gate documents). Any drift here
means the registry refactor changed numbers — it must not.
"""
import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate import predict as P
from sjtu_tpmshx.df_surrogate.backend import (DFBackend, available_methods,
                                  get_backend)
from sjtu_tpmshx.models.tpms_calc import geometry as _geom

_EF = {tp: _geom(tp, 7.0, 0.6, 16.0)['epsilon'] / 2
       for tp in ('Gyroid', 'Diamond')}

# (tpms, method) -> (K, cF) at L=7.0, t=0.6, eps_f=_EF — exact values.
# gamma_df K re-baselined 2026-06-30: SmoothDF Dh² trend -> CFD-refit surface
# (c_F unchanged). See gamma_df.py K UPDATE note + openspec/df-coeffs-cfd-refit.
_GOLDEN = {
    ('Gyroid', 'gamma_df'): (5.221645176691857e-08, 534.800000000008),
    ('Gyroid', 'rbf'):      (3.218806963975885e-08, 534.7664446055616),
    ('Diamond', 'gamma_df'): (5.1135209299724466e-08, 454.19001394852256),
    ('Diamond', 'rbf'):      (2.4688411110399566e-08, 745.0133131278383),
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


@pytest.mark.parametrize(
    'method', ('gamma_df', 'rbf', 'cfd_full_core_3cell_fixed_v2')
)
def test_scalar_vec_parity(method):
    """Vectorised path must agree with the scalar path (modulo the
    scalar-only override layer, empty since 2026-06-11).

    rbf tolerance note: the RBF kernel matmul sums in a different order
    for a 1-row query vs a batched query, giving a last-ulp difference
    between the scalar and vec paths. This is PRE-EXISTING behaviour of
    the retired inline dispatch (verified 2026-06-12), not a registry
    regression — hence rel=1e-12 instead of exact equality here.
    gamma_df is loop-based on both paths → exact.
    """
    L = np.array([5.0, 7.0, 6.0])
    t = np.array([0.4, 0.6, 0.5])
    ef = np.array([_geom('Gyroid', float(l), float(tt), 16.0)['epsilon'] / 2
                   for l, tt in zip(L, t)])
    Kv, cv = P.predict_K_cF_vec('Gyroid', L, t, ef, method=method)
    for i in range(L.size):
        Ks, cs = P.predict_K_cF('Gyroid', float(L[i]), float(t[i]),
                                float(ef[i]), method=method)
        if method != 'rbf':
            assert Kv[i] == Ks and cv[i] == cs
        else:
            assert Kv[i] == pytest.approx(Ks, rel=1e-12)
            assert cv[i] == pytest.approx(cs, rel=1e-12)


def test_rbf_clamp_engages_internally():
    """K clamp is RBF-backend-internal: low-permeability geometry floors
    at K_min exactly; gamma_df stays clamp-free at the same point."""
    ef = _geom('Diamond', 4.0, 0.5, 16.0)['epsilon'] / 2
    Kv, _ = P.predict_K_cF_vec('Diamond', np.array([4.0]), np.array([0.5]),
                               np.array([ef]), method='rbf')
    assert Kv[0] == get_backend('Diamond', 'rbf').K_min == 1e-8
    Kg, _ = P.predict_K_cF('Diamond', 4.0, 0.5, ef, method='gamma_df')
    assert Kg != 1e-8


def test_registry_surface():
    # 2026-06-30: the CFD-refit K surface was folded INTO gamma_df (it now is
    # the default K source); the transient 'cfd_refit' backend was removed.
    assert set(available_methods()) == {
        'gamma_df', 'rbf', 'cfd_full_core_3cell_fixed_v2'
    }
    with pytest.raises(ValueError, match='unknown DF method'):
        P.predict_K_cF('Gyroid', 7.0, 0.6, 0.36, method='plhub_gp_typo')
    b = get_backend('Gyroid', 'gamma_df')
    assert isinstance(b, DFBackend) and b.name == 'gamma_df'
    assert get_backend('Gyroid', 'gamma_df') is b   # cached


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


def test_diagnostics_passthrough():
    """Unknown attributes reach the wrapped model (existing introspection
    call sites: ._rbf_K, .K_min, .summary)."""
    b = get_backend('Gyroid', 'rbf')
    X = np.array([[7.0, 0.6, _EF['Gyroid']]])
    assert np.isfinite(b._rbf_K(X)[0])     # wrapped-model attribute
    assert b.K_min == 1e-8
    g = get_backend('Gyroid', 'gamma_df')
    assert hasattr(g, 'summary')
