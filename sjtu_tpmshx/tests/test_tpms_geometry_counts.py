"""Indexed geometry must equal the existing voxel scans exactly."""
import numpy as np
import pytest

from sjtu_tpmshx.models import tpms_geometry as geometry


@pytest.mark.parametrize('tpms', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('n', [4, 13, 32, 128])
def test_index_matches_inclusive_scan_thresholds_and_geometry(tpms, n):
    ordered, faces = geometry._geometry_counts(tpms, n)
    phi = geometry._phi_grid(tpms, n)
    thresholds = np.r_[-1., 0., ordered[::max(1, ordered.size // 23)], ordered[-1], ordered[-1]+1.]
    for c in thresholds:
        occupied = np.searchsorted(ordered, c, side='right')
        assert float(1.0 - occupied / ordered.size) == geometry._eps_from_C(phi, c)
        area = faces[occupied] * (.007 / n)**2 / (2.0 * .007**3 * geometry._AREA_CORRECTION)
        assert area == geometry._A0_from_C(phi, c, .007, n)
    for L, t in ((4., .3), (5., .5), (6., .4), (7., .6), (8., .3)):
        c = geometry._C_from_tL(tpms, t/L)
        expected = dict(epsilon=geometry._eps_from_C(phi, c),
                        A_0=geometry._A0_from_C(phi, c, L/1000., n))
        assert geometry._compute_raw.__wrapped__(tpms, L, t, n) == expected


def test_equal_neighbors_and_domain_edges_keep_exact_face_counts(monkeypatch):
    phi = np.ones((2, 2, 2))
    phi[0, 0, 0], phi[1, 1, 1] = 0., 2.
    monkeypatch.setattr(geometry, '_phi_grid', lambda *_: phi)
    try:
        ordered, faces = geometry._geometry_counts('synthetic', 2)
        counts = np.searchsorted(ordered, [-1., 0., .5, 1., 2.], side='right')
        np.testing.assert_array_equal(counts, [0, 1, 1, 7, 8])
        np.testing.assert_array_equal(faces[counts], [0, 3, 3, 3, 0])
        for values in (ordered, faces):
            assert not values.flags.writeable
            with pytest.raises(ValueError):
                values[0] = 999
    finally:
        geometry._geometry_counts.cache_clear()
