"""Projection checks independent of retired gamma calibration.

The retired gamma baseline is preserved in fixed Git history;
docs/history/README.md links its original file and numerical values.
"""
import numpy as np
import pytest

from sjtu_tpmshx.models.df_projection import _cell_centre_fracs, _nearest_src_idx, project_fields_to_streamwise_K_cF as p2d, project_fields_to_streamwise_K_cF_3d as p3d


@pytest.mark.parametrize('fluid', ['A', 'B'])
@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('nonuniform', [False, True])
def test_projection_coordinates(fluid, dimension, nonuniform, monkeypatch):
    from sjtu_tpmshx.models import df_projection

    # Coefficients expose projected L/t directly; no calibration is involved.
    monkeypatch.setattr(df_projection, 'predict_K_cF_vec',
                        lambda topo, L, t, eps: (L * 1e-8, t * 1000.))
    L = np.array([[4., 5., 6.], [5., 6., 7.], [6., 7., 8.]])
    t = .1 + L / 20.
    widths = np.array([1., 3.]) if nonuniform else None
    if fluid == 'A':
        expected = np.array([5., 6. if nonuniform else 7.])
    else:
        expected = np.array([7., 6. if nonuniform else 5.])
    if dimension == 2:
        K, cF = p2d(L, t, 'Gyroid', 16., 2, fluid,
                     streamwise_dx=widths)
    else:
        L3 = np.stack([L, L + .5, L + 1.], axis=2)
        t3 = .1 + L3 / 20.
        K, cF = p3d(L3, t3, np.full_like(L3, .4), 'Gyroid', 2, 2, fluid,
                     streamwise_dx=widths,
                     z_dx=widths)
        expected = np.stack([expected, expected + (.5 if nonuniform else 1.)], axis=1)
    np.testing.assert_allclose(K, expected * 1e-8, rtol=1e-12, atol=0.)
    np.testing.assert_allclose(cF, 100. + expected * 50., rtol=1e-12, atol=0.)


def test_helper_semantics():
    """Uniform fracs == (i+0.5)/n; non-uniform integrate widths; index
    mapping reproduces the retired int(min(...)) form for in-range fracs."""
    f = _cell_centre_fracs(4, None)
    assert np.allclose(f, [0.125, 0.375, 0.625, 0.875])
    fn = _cell_centre_fracs(2, np.array([3.0, 1.0]))
    assert np.allclose(fn, [0.375, 0.875])
    idx = _nearest_src_idx(np.array([0.0, 0.49, 0.99, 1.0]), 10)
    assert idx.tolist() == [0, 4, 9, 9]



def test_invalid_fluid_raises():
    with pytest.raises(ValueError, match="fluid must be"):
        p2d(np.ones((2, 2)) * 5., np.ones((2, 2)) * .4,
            'Gyroid', 16., 2, 'C')
