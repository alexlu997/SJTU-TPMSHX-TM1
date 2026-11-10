"""Indexed geometry must equal the existing voxel scans exactly."""
import numpy as np
import pytest
import ctypes as ct

from sjtu_tpmshx.shared.models import tpms_geometry as geometry
from sjtu_tpmshx.shared.models import _native_geometry as native
from sjtu_tpmshx.development.tests import geometry_reference as reference


@pytest.mark.parametrize('tpms', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('n', [4, 13, 32, 128])
def test_index_matches_inclusive_scan_thresholds_and_geometry(tpms, n):
    phi = reference._phi_grid(tpms, n)
    np.testing.assert_array_equal(geometry._phi_grid(tpms, n), phi)
    ordered = np.sort(np.abs(phi), axis=None)
    thresholds = np.r_[-1., 0., ordered[::max(1, ordered.size // 23)], ordered[-1], ordered[-1]+1.]
    actual = native.counts(tpms, thresholds, N=n)
    for row, c in zip(actual, thresholds):
        occupied = np.searchsorted(ordered, c, side='right')
        solid = np.abs(phi) <= c
        faces = sum(np.count_nonzero(np.diff(solid, axis=axis)) for axis in range(3))
        np.testing.assert_array_equal(row, [occupied, faces, phi.size])
        assert float(1.0 - occupied / ordered.size) == reference._eps_from_C(phi, c)
    for L, t in ((4., .3), (5., .5), (6., .4), (7., .6), (8., .3)):
        c = reference._C_from_tL(tpms, t/L)
        expected = dict(epsilon=reference._eps_from_C(phi, c),
                        A_0=reference._A0_from_C(phi, c, L/1000., n))
        values = native.raw_fields(tpms, L, t, N=n)
        assert {key: value[()] for key, value in values.items()} == expected


def test_equal_neighbors_and_domain_edges_keep_exact_face_counts():
    phi = np.ones((2, 2, 2))
    phi[0, 0, 0], phi[1, 1, 1] = 0., 2.
    library = native._library()
    owner = ct.c_void_p()
    native._call(library.index_create_from_phi, (ct.c_size_t*3)(*phi.shape),
                 native._pointer(phi), phi.size, ct.byref(owner))
    try:
        phi.fill(999.)
        levels = np.array([-1., 0., .5, 1., 2.])
        counts = np.empty((5, 3), dtype=np.int64)
        native._call(library.counts, owner, native._pointer(levels), levels.size,
                     counts.ctypes.data_as(ct.POINTER(ct.c_int64)), counts.size)
        np.testing.assert_array_equal(counts[:, 0], [0, 1, 1, 7, 8])
        np.testing.assert_array_equal(counts[:, 1], [0, 3, 3, 3, 0])
        np.testing.assert_array_equal(counts[:, 2], [8]*5)
    finally:
        library.index_destroy(owner)
