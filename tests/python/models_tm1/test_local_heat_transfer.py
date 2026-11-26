"""Speed, Nu and local-property invariants of the shared local heat-transfer closure."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.python.local_heat_transfer_reference import local_nusselt, local_speed


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
    from sjtu_tpmshx.physical_models.nu_correlations import NU_LAM_FLOOR
    reynolds = np.array([[0., .5, 1., 2.]], dtype=np.float32)
    original = reynolds.copy()
    raw_nu = np.array([[0., 4., 5., 8.]], dtype=np.float32)

    def nu(topology, Re, eps_f, length, diameter, Pr):
        assert (topology, eps_f, length, diameter, Pr) == ('Gyroid', .4, 7., 2., 7.)
        np.testing.assert_array_equal(Re, [[1., 1., 1., 2.]])
        return raw_nu

    actual = local_nusselt(SimpleNamespace(nu=nu, nu_floor_multiplier=1.),
                           'Gyroid', reynolds, .4, 7., 2., 7.)
    assert actual.dtype == np.float64
    np.testing.assert_array_equal(actual, [[NU_LAM_FLOOR, NU_LAM_FLOOR, 5., 8.]])
    np.testing.assert_array_equal(reynolds, original)
    np.testing.assert_array_equal(raw_nu, [[0., 4., 5., 8.]])


@pytest.mark.parametrize('fluid,Pr', [('air', None), ('water', 7.)])
def test_local_nusselt_matches_real_scalar_model_calls(fluid, Pr):
    from sjtu_tpmshx.physical_models.fluid_props import get
    from tests.python.property_reference import fluid_model
    from sjtu_tpmshx.physical_models.nu_correlations import NU_LAM_FLOOR
    model = get(fluid)
    reynolds = np.array([[0., .9, 1.], [1.1, 100., 1000.]])
    expected = local_nusselt(fluid_model(fluid), 'Gyroid', reynolds, .4, 7., 2., Pr)
    actual = [max(float(model.nu('Gyroid', max(Re, 1.), .4, 7., 2., Pr)), NU_LAM_FLOOR)
              for Re in reynolds.flat]
    np.testing.assert_array_equal(np.asarray(actual).reshape(reynolds.shape), expected)


def test_d3_sco2_hv_uses_local_temperature_props():
    # No effective parameter selection: both paths use the smooth CFD base.
    from tests.python.local_heat_transfer_reference import real_fluid_hv_local_field
    from tests.python.nu_reference import nu_sco2_topo
    from tests.python import eos_reference

    pressure = 8.0e6  # Pa — CO2 pseudocritical T ≈ 307.7 K at this pressure
    A_0, D_h_m = 500.0, 1.0e-3
    u_abs = np.full((2, 2, 2), 1.5)
    T_in = 320.0
    T_field = np.full((2, 2, 2), T_in)
    T_field[1, 1, 1] = 450.0               # a cell far from the inlet state

    hv = real_fluid_hv_local_field(T_field, pressure, u_abs, A_0, D_h_m, 'Diamond', 7.0)

    # frozen-at-inlet h_v (what the buggy scalar path applies to EVERY cell)
    rho_i = eos_reference.sco2_prop('D', T_in, pressure)
    mu_i = eos_reference.sco2_prop('V', T_in, pressure)
    k_i = eos_reference.sco2_prop('L', T_in, pressure)
    Pr_i = eos_reference.sco2_prop('C', T_in, pressure) * mu_i / k_i
    Re_i = rho_i * 1.5 * D_h_m / mu_i
    Nu_i = nu_sco2_topo('Diamond', max(Re_i, 1.0), Pr_i, 7.0, D_h_m * 1000.0)
    hv_frozen = A_0 * Nu_i * k_i / D_h_m

    # cells at the inlet state match the frozen value (no spurious change)
    assert hv[0, 0, 0] == pytest.approx(hv_frozen, rel=1e-9)
    # the departed cell differs by a large factor (the frozen-prop bias)
    assert abs(hv[1, 1, 1] - hv_frozen) / hv_frozen > 0.20
