"""Speed and Nu invariants of the shared local heat-transfer closure."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models.local_heat_transfer import local_nusselt, local_speed


def test_speed_is_axis_independent_and_has_the_2d_limit():
    u = np.array([3., 0., 0., -5.])
    v = np.array([4., 0., -5., 0.])
    w = np.array([12., 0., 0., 0.])
    originals = [field.copy() for field in (u, v, w)]
    np.testing.assert_array_equal(local_speed(u, v, w), [13., 0., 5., 5.])
    np.testing.assert_array_equal(local_speed(-w, u, -v), [13., 0., 5., 5.])
    np.testing.assert_array_equal(local_speed(u, v), [5., 0., 5., 5.])
    np.testing.assert_array_equal(local_speed(u, v, np.zeros_like(w)), local_speed(u, v))
    for field, original in zip((u, v, w), originals):
        np.testing.assert_array_equal(field, original)


def test_local_nusselt_clamps_both_bounds_without_mutating_inputs():
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR
    reynolds = np.array([[0., .5, 1., 2.]], dtype=np.float32)
    original = reynolds.copy()
    raw_nu = np.array([[0., 4., 5., 8.]], dtype=np.float32)

    def nu(topology, Re, eps_f, length, diameter, Pr):
        assert (topology, eps_f, length, diameter, Pr) == ('Gyroid', .4, 7., 2., 7.)
        np.testing.assert_array_equal(Re, [[1., 1., 1., 2.]])
        return raw_nu

    actual = local_nusselt(SimpleNamespace(nu=nu), 'Gyroid', reynolds, .4, 7., 2., 7.)
    assert actual.dtype == np.float64
    np.testing.assert_array_equal(actual, [[NU_LAM_FLOOR, NU_LAM_FLOOR, 5., 8.]])
    np.testing.assert_array_equal(reynolds, original)
    np.testing.assert_array_equal(raw_nu, [[0., 4., 5., 8.]])


@pytest.mark.parametrize('fluid,Pr', [('air', None), ('water', 7.)])
def test_local_nusselt_matches_real_scalar_model_calls(fluid, Pr):
    from sjtu_tpmshx.models.fluid_props import get
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR
    model = get(fluid)
    reynolds = np.array([[0., .9, 1.], [1.1, 100., 1000.]])
    actual = local_nusselt(model, 'Gyroid', reynolds, .4, 7., 2., Pr)
    expected = [max(float(model.nu('Gyroid', max(Re, 1.), .4, 7., 2., Pr)), NU_LAM_FLOOR)
                for Re in reynolds.flat]
    np.testing.assert_array_equal(actual, np.asarray(expected).reshape(reynolds.shape))
