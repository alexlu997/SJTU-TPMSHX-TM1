"""Projection checks independent of retired gamma calibration.

The retired gamma baseline is preserved in fixed Git history;
docs/history/README.md links its original file and numerical values.
"""
import numpy as np
import pytest

from sjtu_tpmshx.shared.models.df_projection import (
    project_fields_to_streamwise_K_cF as p2d,
)


@pytest.mark.parametrize('fluid', ['A', 'B'])
@pytest.mark.parametrize('nonuniform', [False, True])
def test_projection_coordinates(fluid, nonuniform, monkeypatch):
    from sjtu_tpmshx.shared.models import df_projection

    # Coefficients expose projected L/t directly; no calibration is involved.
    monkeypatch.setattr(df_projection, 'predict_K_cF_vec',
                        lambda topo, L, t, eps, **kwargs: (L * 1e-8, t * 1000.))
    L = np.array([[4., 5., 6.], [5., 6., 7.], [6., 7., 8.]])
    t = .1 + L / 20.
    widths = np.array([1., 3.]) if nonuniform else None
    if fluid == 'A':
        expected = np.array([5., 6. if nonuniform else 7.])
    else:
        expected = np.array([7., 6. if nonuniform else 5.])
    K, cF = p2d(L, t, 'Gyroid', 16., 2, 0 if fluid == 'A' else 3,
                 streamwise_dx=widths)
    np.testing.assert_allclose(K, expected * 1e-8, rtol=1e-12, atol=0.)
    np.testing.assert_allclose(cF, 100. + expected * 50., rtol=1e-12, atol=0.)


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
    with pytest.raises(ValueError, match="direction must be"):
        p2d(np.ones((2, 2)) * 5., np.ones((2, 2)) * .4,
            'Gyroid', 16., 2, 4)
