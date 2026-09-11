"""Characterization test pinning nu_correlations to the legacy formulae bit-exact.

Future Nu refits should show up as clear deltas in this test.
Backward-compat note: existing test_review_fixes.py asserts the same numerical
contract through tpms_calc._NU_ROUGHNESS_FACTOR and sigmoid_field._nu_vec.

Per audit finding H1 (2026-05-28 4-perspective audit, plan Item 1).
"""
import numpy as np
import pytest


def _ref_diamond_smooth(Re, L_mm, D_h_mm, Pr=0.72):
    """Frozen Diamond Nu reference (refit 2026-04-28, was tpms_calc._nu_diamond)."""
    return 0.0944 * Pr ** (1/3) * Re ** 0.8273 * (D_h_mm / L_mm) ** 0.226


def _ref_gyroid_smooth(Re, L_mm, D_h_mm, Pr=0.72):
    """Frozen Gyroid Nu reference (refit 2026-04-28, was tpms_calc._nu_gyroid)."""
    return 0.126 * Pr ** (1/3) * Re ** 0.7898 * (D_h_mm / L_mm) ** 0.2409


@pytest.mark.parametrize("tpms,Re,L_mm,D_h_mm,ref_func", [
    ('Diamond', 500.0, 7.0, 1.5, _ref_diamond_smooth),
    ('Diamond', 2000.0, 8.0, 2.0, _ref_diamond_smooth),
    ('Diamond', 8000.0, 4.0, 0.8, _ref_diamond_smooth),
    ('Gyroid', 500.0, 7.0, 1.5, _ref_gyroid_smooth),
    ('Gyroid', 2000.0, 8.0, 2.0, _ref_gyroid_smooth),
    ('Gyroid', 8000.0, 4.0, 0.8, _ref_gyroid_smooth),
])
def test_nu_from_Re_matches_legacy_formula(tpms, Re, L_mm, D_h_mm, ref_func):
    """Scalar nu_from_Re must match frozen reference formula bit-exact."""
    from sjtu_tpmshx.models.nu_correlations import nu_from_Re, NU_ROUGHNESS_FACTOR
    expected = NU_ROUGHNESS_FACTOR * ref_func(Re, L_mm, D_h_mm)
    actual = nu_from_Re(tpms, Re, eps_f=0.4, L_mm=L_mm, D_h_mm=D_h_mm)
    np.testing.assert_allclose(actual, expected, rtol=1e-15)


def test_nu_vec_matches_scalar_path():
    """Vector path must produce identical values to scalar (modulo Re floor)."""
    from sjtu_tpmshx.models.nu_correlations import nu_from_Re, nu_vec
    Re_arr = np.array([500.0, 2000.0, 8000.0])
    L_mm, D_h_mm = 7.0, 1.5
    for tpms in ('Diamond', 'Gyroid'):
        vec_out = nu_vec(tpms, Re_arr, L_mm, D_h_mm)
        scalar_out = np.array([
            nu_from_Re(tpms, Re, eps_f=0.4, L_mm=L_mm, D_h_mm=D_h_mm)
            for Re in Re_arr
        ])
        np.testing.assert_allclose(vec_out, scalar_out, rtol=1e-15)


def test_nu_vec_applies_re_floor_at_10():
    """Re_floor=10 matches legacy sigmoid_field._nu_vec behavior."""
    from sjtu_tpmshx.models.nu_correlations import nu_vec
    Re_below = np.array([5.0, 1.0, 0.0])
    Re_at_10 = np.array([10.0, 10.0, 10.0])
    out_floored = nu_vec('Diamond', Re_below, 7.0, 1.5)
    out_at_10 = nu_vec('Diamond', Re_at_10, 7.0, 1.5)
    np.testing.assert_allclose(out_floored, out_at_10, rtol=1e-15)


def test_nu_water_pr_substitution():
    """Water Nu = air Nu × (Pr_water / Pr_air)^(1/3) (Reynolds analogy)."""
    from sjtu_tpmshx.models.nu_correlations import nu_from_Re, nu_water_from_Re, Pr_AIR
    Pr_w = 6.0
    air = nu_from_Re('Gyroid', 1000.0, eps_f=0.4, L_mm=7.0, D_h_mm=1.5)
    water = nu_water_from_Re('Gyroid', 1000.0, eps_f=0.4,
                              L_mm=7.0, D_h_mm=1.5, Pr_water=Pr_w)
    expected = air * (Pr_w / Pr_AIR) ** (1/3)
    np.testing.assert_allclose(water, expected, rtol=1e-15)


def test_legacy_tpms_calc_api_still_works():
    """Backward compat: tpms_calc.nu_from_Re + _NU_ROUGHNESS_FACTOR re-exported."""
    from sjtu_tpmshx.models import tpms_calc
    assert abs(tpms_calc._NU_ROUGHNESS_FACTOR - 1.28) < 1e-15
    Nu = tpms_calc.nu_from_Re('Diamond', 1000.0, 0.4, 7.0, 1.5)
    from sjtu_tpmshx.models.nu_correlations import nu_from_Re
    assert abs(Nu - nu_from_Re('Diamond', 1000.0, 0.4, 7.0, 1.5)) < 1e-15


def test_legacy_sigmoid_field_nu_vec_still_works():
    """Backward compat: sigmoid_field._nu_vec 5-arg signature unchanged.

    Existing test_review_fixes.py:194 also exercises this contract; this is
    a duplicate guard since the 5-arg signature is load-bearing.
    """
    from sjtu_tpmshx.models.sigmoid_field import _nu_vec
    Re_arr = np.array([1000.0, 2000.0])
    eps_arr = np.array([0.8, 0.8])   # unused but signature requires it
    L_arr = np.array([7.0, 7.0])
    D_h_arr = np.array([1.5, 1.5])
    Nu = _nu_vec('Gyroid', Re_arr, eps_arr, L_arr, D_h_arr)
    assert Nu.shape == (2,)
    assert np.all(Nu > 0)


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
def test_source_statistics_precede_floor_without_changing_nu(fluid):
    from sjtu_tpmshx.domain.run_warnings import warning_scope
    from sjtu_tpmshx.models import nu_correlations as nu

    raw = np.array([0., .1, 5000.])
    if fluid == 'air':
        evaluate = lambda re: nu.nu_vec('Diamond', re, 7., 2.)
        expected = nu.NU_ROUGHNESS_FACTOR * _ref_diamond_smooth(np.maximum(raw, 10.), 7., 2.)
    elif fluid == 'water':
        evaluate = lambda re: nu.nu_water_topo('Diamond', re, 3.)
        expected = .3201 * np.maximum(raw, 1.) ** .6679 * 3. ** (1 / 3)
    else:
        evaluate = lambda re: nu.nu_sco2_topo('Diamond', re, 3., 7., 2.)
        co = nu.SCO2_NU_COEFFS['Diamond']
        expected = co['c'] * np.maximum(raw, 1.) ** co['a'] * 3. ** (1 / 3) * (2. / 7.) ** co['d']
    with warning_scope({}) as records:
        actual = evaluate(raw)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(raw, [0., .1, 5000.])
    value, = records.values()
    assert value.minimum == (0., (0,))
    assert (value.low, value.high, value.size) == (2, 0, 3)
