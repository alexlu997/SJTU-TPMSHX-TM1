"""Projection checks independent of retired gamma calibration.

The retired gamma baseline is preserved in fixed Git history;
docs/history/README.md links its original file and numerical values.
"""
import numpy as np
import pytest

from sjtu_tpmshx.shared.models._native_df import project_rows


@pytest.mark.parametrize('fluid', ['A', 'B'])
@pytest.mark.parametrize('nonuniform', [False, True])
def test_projection_coordinates(fluid, nonuniform):
    L = np.array([[4., 5., 6.], [5., 6., 7.], [6., 7., 8.]])
    t = .1 + L / 20.
    widths = np.array([1., 3.]) if nonuniform else None
    if fluid == 'A':
        expected = np.array([5., 6. if nonuniform else 7.])
    else:
        expected = np.array([7., 6. if nonuniform else 5.])
    cells, walls, _ = project_rows(L, t, 2, 0 if fluid == 'A' else 3, widths)
    np.testing.assert_allclose(cells, expected, rtol=1e-12, atol=0.)
    np.testing.assert_allclose(walls, .1 + expected / 20., rtol=1e-12, atol=0.)


def test_native_projection_coordinate_rules():
    from sjtu_tpmshx.shared.models import _native_df

    lengths = np.broadcast_to(np.arange(4., 8.)[:, None], (4, 2))
    walls = np.full_like(lengths, .4)
    uniform = _native_df.project_rows(lengths, walls, 4, 0)
    np.testing.assert_array_equal(uniform[0], [4., 5., 6., 7.])
    nonuniform = _native_df.project_rows(lengths, walls, 2, 0, [3., 1.])
    np.testing.assert_array_equal(nonuniform[0], [5., 7.])
    np.testing.assert_array_equal(nonuniform[2], [1, 3])


def test_invalid_direction_raises():
    with pytest.raises(ValueError, match="direction 0, 1, 2 or 3"):
        project_rows(np.ones((2, 2)) * 5., np.ones((2, 2)) * .4, 2, 4)
