"""Check Anderson candidates and restored histories without thermal model headers."""
import ctypes as ct
import sys

import numpy as np
import pytest

from tests.python.native.shared_library import kernel_test_path

D = ct.POINTER(ct.c_double)
S = ct.c_size_t
C = ct.POINTER(ct.c_char)


@pytest.fixture(scope='module')
def native():
    return ct.CDLL(str(kernel_test_path()))


@pytest.mark.parametrize('columns', [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize('scale', [1., 1e-7, 1e-12])
def test_original_candidate_svd_lstsq_and_condition_gate(native, scale, columns):
    rng = np.random.default_rng(321)
    x = np.ascontiguousarray(300.+rng.normal(size=(417, columns)))
    r = rng.normal(size=x.shape)
    r[:, 1:] = r[:, :1] + scale*(r[:, 1:]-r[:, :1])
    r = np.ascontiguousarray(r)
    g = np.ascontiguousarray(x[:, -1]+r[:, -1])
    dx, dr = np.diff(x, axis=1), np.diff(r, axis=1)
    singular = np.linalg.svd(dr, compute_uv=False)
    expected_applied = bool(singular.size and singular[0] > 0. and singular[0]/max(singular[-1], 1e-30) <= 1e10)
    expected = g
    if expected_applied:
        weights = np.linalg.lstsq(dr, r[:, -1], rcond=None)[0]
        expected = g - (dx+dr) @ weights
    call = native.test_anderson_candidate
    call.argtypes = [S, S, D, D, D, ct.c_double, D, ct.POINTER(ct.c_int), C, S]
    call.restype = ct.c_int
    actual, applied, error = np.empty_like(g), ct.c_int(), ct.create_string_buffer(512)
    code = call(*x.shape, x.ctypes.data_as(D), r.ctypes.data_as(D), g.ctypes.data_as(D), 1e10,
                actual.ctypes.data_as(D), ct.byref(applied), error, len(error))
    assert code == 0, error.value.decode()
    assert bool(applied.value) == expected_applied
    np.testing.assert_allclose(actual, expected, rtol=3e-10, atol=3e-12)
    if sys.platform == 'darwin':
        np.testing.assert_array_equal(actual, expected)
