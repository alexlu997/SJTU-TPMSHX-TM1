"""Native optional outer Anderson policy against the original Python owner.

Frozen comparison: normalized property output rtol=3e-10, atol=3e-12
(existing Eigen SVD versus NumPy LAPACK); residual norms rtol=5e-15,
atol=5e-14 for subtraction of nearly equal normalized fields.
Applied/rejected/reset decisions and running-history length must match.
Identical source x/G(x) pairs are supplied to both implementations each step.
"""
from contextlib import contextmanager
import ctypes as ct
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest

from scripts.generate_native_model_coefficients import header
from sjtu_tpmshx.solvers.anderson_acceleration import AndersonOuterCoupling, AndersonSIMPLE

D = ct.POINTER(ct.c_double)
S = ct.c_size_t
C = ct.POINTER(ct.c_char)


class Native:
    def __init__(self, path):
        self.lib = ct.CDLL(str(path))
        self.lib.test_outer_anderson_create.argtypes = [ct.c_int, ct.c_double, ct.c_int, ct.c_double,
                                                        ct.POINTER(ct.c_void_p), C, S]
        self.lib.test_outer_anderson_create.restype = ct.c_int
        self.lib.test_outer_anderson_destroy.argtypes = [ct.c_void_p]
        self.lib.test_outer_anderson_destroy.restype = None
        self.lib.test_outer_anderson_step.argtypes = [ct.c_void_p, S, ct.POINTER(S), ct.POINTER(D),
            ct.POINTER(D), ct.c_double, ct.POINTER(D), ct.POINTER(S), D, C, S]
        self.lib.test_outer_anderson_step.restype = ct.c_int

    @contextmanager
    def accelerator(self, *, m=3, trust=5., patience=3, cond_max=1e10):
        handle, error = ct.c_void_p(), ct.create_string_buffer(512)
        code = self.lib.test_outer_anderson_create(m, trust, patience, cond_max, ct.byref(handle), error, len(error))
        assert code == 0, error.value.decode()
        try:
            yield handle
        finally:
            self.lib.test_outer_anderson_destroy(handle)

    def step(self, handle, x, g, alpha):
        n = len(x)
        arrays = [np.ascontiguousarray(a, dtype=np.float64) for a in [*x, *g]]
        current, image = arrays[:n], arrays[n:]
        out = [np.empty_like(a) for a in current]
        ptrs = lambda values: (D * n)(*(a.ctypes.data_as(D) for a in values))
        statistics, residual, error = (S * 5)(), ct.c_double(), ct.create_string_buffer(512)
        code = self.lib.test_outer_anderson_step(handle, n, (S * n)(*(a.size for a in current)),
            ptrs(current), ptrs(image), alpha, ptrs(out), statistics, ct.byref(residual), error, len(error))
        assert code == 0, error.value.decode()
        return out, bool(statistics[0]), tuple(statistics)[1:], residual.value


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    root = Path(__file__).resolve().parents[3]
    eigen = root / '.cache/native-deps/src/CoolProp-7.2.0/externals/Eigen'
    compiler = shlex.split(os.environ.get('CXX', 'cl' if os.name == 'nt' else 'c++'))
    if not compiler or not shutil.which(compiler[0]):
        message = 'outer Anderson qualification requires a C++17 compiler'
        if (os.environ.get('TPMSHX_REQUIRE_CPP_TESTS') == '1'
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail(message)
        pytest.skip(message)
    if not (eigen / 'Eigen/Dense').is_file():
        message = 'outer Anderson qualification requires locked Eigen sources'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    build = tmp_path_factory.mktemp('native-outer-anderson')
    generated = build / 'tpmshx'
    generated.mkdir()
    (generated / 'model_coefficients.hpp').write_text(header(), encoding='utf-8')
    output = build / ('outer_anderson' + ('.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'))
    sources = [root / 'native/src/outer_anderson.cpp', Path(__file__).with_name('outer_anderson_bridge.cpp')]
    if os.name == 'nt':
        arguments = ['/nologo', '/std:c++17', '/O2', '/W4', '/WX', '/EHsc', '/MD', '/LD', '/fp:strict',
                     '/DTPMSHX_THERMAL_BUILD_SHARED', '/DEIGEN_MPL2_ONLY', '/I' + str(root / 'native/include'),
                     '/I' + str(build), '/external:I' + str(eigen), '/external:W0',
                     *sources, '/Fe' + str(output), '/link', '/IMPLIB:' + str(build / 'outer_anderson.lib')]
    else:
        arguments = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-ffp-contract=off',
                     '-DEIGEN_MPL2_ONLY', '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-fPIC',
                     '-I', root / 'native/include', '-I', build, '-isystem', eigen, *sources, '-o', output]
        if sys.platform == 'darwin':
            arguments += ['-framework', 'Accelerate']
    subprocess.run([*compiler, *arguments], cwd=build, check=True, text=True, capture_output=True)
    return Native(output)


@pytest.mark.parametrize('scale', [1., 1e-7, 1e-12])
def test_original_candidate_svd_lstsq_and_condition_gate(native, scale):
    rng = np.random.default_rng(321)
    x = np.ascontiguousarray(300.+rng.normal(size=(417, 6)))
    r = rng.normal(size=x.shape)
    r[:, 1:] = r[:, :1] + scale*(r[:, 1:]-r[:, :1])
    r = np.ascontiguousarray(r)
    g = np.ascontiguousarray(x[:, -1]+r[:, -1])
    original = AndersonSIMPLE()
    original._X.extend(x[:, j].copy() for j in range(6))
    original._R.extend(r[:, j].copy() for j in range(6))
    expected, expected_applied = original.candidate(g)
    call = native.lib.test_anderson_candidate
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


def check_step(native, handle, python, x, g, alpha=.6):
    expected, applied = python.step(x, g, alpha)
    actual, got_applied, statistics, residual = native.step(handle, x, g, alpha)
    assert got_applied == applied
    stats = python.stats()
    assert statistics == (stats['applied'], stats['rejected'], stats['resets'], len(stats['residuals']))
    np.testing.assert_allclose(residual, stats['residuals'][-1], rtol=5e-15, atol=5e-14, equal_nan=True)
    for a, e, scale in zip(actual, expected, python._scales):
        np.testing.assert_allclose(a / scale, e / scale, rtol=3e-10, atol=3e-12, equal_nan=True)
    return expected, applied


@pytest.mark.parametrize('m', [0, 1, 3, 5])
@pytest.mark.parametrize('alpha', [.25, .6, 1.])
def test_nonuniform_property_map_and_history_depth(native, m, alpha):
    rng = np.random.default_rng(1361)
    x = [rng.uniform(.8, 1.4, (4, 3)), rng.uniform(1.7e-5, 2.3e-5, (3, 2))]
    target = [np.full_like(x[0], 1.1), np.full_like(x[1], 2.1e-5)]
    contraction = [rng.uniform(.1, .7, b.shape) for b in x]
    python = AndersonOuterCoupling(m=m)
    with native.accelerator(m=m) as handle:
        for _ in range(16):
            g = [goal + factor * (value - goal) for goal, factor, value in zip(target, contraction, x)]
            x, _ = check_step(native, handle, python, x, g, alpha)
    assert python.applied_count > 0 if m else python.applied_count == 0


@pytest.mark.parametrize('trust', [0., 1., 1e6])
def test_hostile_map_preserves_acceptance_and_rejection(native, trust):
    rng = np.random.default_rng(0)
    python = AndersonOuterCoupling(m=4, trust=trust)
    x = [np.ones((4, 3)), np.full((4, 3), 2e-5)]
    with native.accelerator(m=4, trust=trust) as handle:
        for _ in range(25):
            g = [np.abs(b * (1 + 3 * rng.standard_normal(b.shape))) + 1e-6 for b in x]
            x, applied = check_step(native, handle, python, x, g)
            if applied:
                assert all(np.all(np.isfinite(b)) and np.min(b) > 0 for b in x)
    assert python.rejected_count + python.reset_count > 0


def test_positive_input_negative_candidate_rejected(native):
    python = AndersonOuterCoupling(m=3, trust=1e6)
    with native.accelerator(m=3, trust=1e6) as handle:
        check_step(native, handle, python, [np.array([1.])], [np.array([.5])])
        result, applied = check_step(native, handle, python, [np.array([.7])], [np.array([.3])])
        assert not applied and python.rejected_count == 1
        np.testing.assert_allclose(result[0], [.46])


@pytest.mark.parametrize('patience', [0, 2, 3])
def test_original_windowed_reset_keeps_full_residual_trace(native, patience):
    python = AndersonOuterCoupling(patience=patience)
    x = [np.ones((4, 3)), np.full((4, 3), 2e-5)]
    with native.accelerator(patience=patience) as handle:
        for factor in [1.5, 1.7, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6]:
            check_step(native, handle, python, x, [b * factor for b in x])
    assert python.reset_count > 0
    assert len(python.residuals) == 8


def test_custom_condition_gate_and_invariant_picard(native):
    python = AndersonOuterCoupling(cond_max=.5)
    with native.accelerator(cond_max=.5) as handle:
        for value in [1., 1.2, 1.1, 1.05]:
            check_step(native, handle, python, [np.array([value])], [np.array([.5 * value + .4])])
    assert python.applied_count == 0


@pytest.mark.parametrize('invalid', [np.nan, np.inf, -1.])
def test_fallback_retains_upstream_invalid_evidence(native, invalid):
    python = AndersonOuterCoupling()
    with native.accelerator() as handle:
        with np.errstate(invalid='ignore'):
            check_step(native, handle, python, [np.array([1., 2.])], [np.array([invalid, 2.2])])
