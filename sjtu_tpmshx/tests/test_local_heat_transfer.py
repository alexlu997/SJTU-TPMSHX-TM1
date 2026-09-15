"""Speed invariants of the shared scalar heat-transfer closure."""
import numpy as np

from sjtu_tpmshx.models.local_heat_transfer import local_speed


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
