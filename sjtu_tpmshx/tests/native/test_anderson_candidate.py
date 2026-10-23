"""Check Anderson candidates and restored histories without thermal model headers."""
import ctypes as ct
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest

D = ct.POINTER(ct.c_double)
S = ct.c_size_t
C = ct.POINTER(ct.c_char)


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    root = Path(__file__).resolve().parents[3]
    eigen = root / '.cache/native-deps/src/Eigen-5.0.1'
    compiler = shlex.split(os.environ.get('CXX', 'cl' if os.name == 'nt' else 'c++'))
    if not compiler or not shutil.which(compiler[0]):
        message = 'thermal Anderson qualification requires a C++17 compiler'
        if (os.environ.get('TPMSHX_REQUIRE_CPP_TESTS') == '1'
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail(message)
        pytest.skip(message)
    if not (eigen / 'Eigen/Dense').is_file():
        message = 'thermal Anderson qualification requires locked Eigen sources'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    build = tmp_path_factory.mktemp('native-anderson-candidate')
    output = build / ('anderson_candidate' + ('.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'))
    sources = [Path(__file__).with_name('anderson_candidate_bridge.cpp')]
    if os.name == 'nt':
        arguments = ['/nologo', '/std:c++17', '/O2', '/W4', '/WX', '/EHsc', '/MD', '/LD', '/fp:strict',
                     '/DTPMSHX_THERMAL_BUILD_SHARED', '/DEIGEN_MPL2_ONLY', '/I' + str(root / 'native/include'),
                     '/external:I' + str(eigen), '/external:W0',
                     *sources, '/Fe' + str(output), '/link', '/IMPLIB:' + str(build / 'anderson_candidate.lib')]
    else:
        arguments = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-ffp-contract=off',
                     '-DEIGEN_MPL2_ONLY', '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-fPIC',
                     '-I', root / 'native/include', '-isystem', eigen, *sources, '-o', output]
        if sys.platform == 'darwin':
            arguments += ['-framework', 'Accelerate']
    subprocess.run([*compiler, *arguments], cwd=build, check=True, text=True, capture_output=True)
    return ct.CDLL(str(output))


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
