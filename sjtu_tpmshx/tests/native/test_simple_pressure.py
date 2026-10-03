"""Qualification of current 2D/3D PPE, correction, BC and continuity algebra.

Frozen before comparison: rtol=3e-13 for primitives, absolute tolerances
2e-18 for CSR/rhs/face mass, 2e-11 Pa for P, 1e-12 m/s for velocity,
3e-13 for dimensionless mass diagnostics. Direct Pp uses rtol/atol=1e-10
and independently checked original relative residual <=1e-10. These are
porting tolerances, not physical F2 acceptance gates.
"""
from contextlib import contextmanager
from copy import deepcopy
import ctypes
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import spsolve

from sjtu_tpmshx.solvers import _kernels_simple_2d as k2
from sjtu_tpmshx.solvers import _kernels_simple_3d as k3
from sjtu_tpmshx.solvers.simple_solver_3d import _build_pp_sparsity_3d
from sjtu_tpmshx.tests.native.test_native_pressure import (
    pressure_executable as pressure_executable,
    request, run_requests,
)


NAMES = ('dx', 'dy', 'dz', 'u', 'v', 'w', 'du', 'dv', 'dw', 'rho_eps',
         'p', 'pp', 'rho', 'eps', 'inlet_velocity', 'inlet_fraction',
         'mass_u', 'mass_v', 'mass_w')
RTOL = 3e-13
DOUBLE_P = ctypes.POINTER(ctypes.c_double)
SIZE_P = ctypes.POINTER(ctypes.c_size_t)
BYTE_P = ctypes.POINTER(ctypes.c_ubyte)
INT_P = ctypes.POINTER(ctypes.c_int)
CHAR_P = ctypes.POINTER(ctypes.c_char)
MACOS_ARM64 = sys.platform == 'darwin' and platform.machine() == 'arm64'


class NativePressurePrimitives:
    def __init__(self, path):
        self.library = ctypes.CDLL(str(path))
        functions = {
            'test_simple_pressure_create': [ctypes.c_int, SIZE_P, ctypes.POINTER(DOUBLE_P), SIZE_P,
                BYTE_P, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p), CHAR_P, ctypes.c_size_t],
            'test_simple_pressure_assemble': [ctypes.c_void_p, SIZE_P, ctypes.POINTER(DOUBLE_P), SIZE_P,
                INT_P, INT_P, DOUBLE_P, DOUBLE_P, BYTE_P, ctypes.c_size_t, SIZE_P, CHAR_P, ctypes.c_size_t],
            'test_simple_pressure_primitive': [ctypes.c_int, ctypes.c_int, SIZE_P,
                ctypes.POINTER(DOUBLE_P), SIZE_P, BYTE_P, ctypes.c_size_t, BYTE_P, ctypes.c_size_t,
                ctypes.c_double, DOUBLE_P, CHAR_P, ctypes.c_size_t],
        }
        for name, arguments in functions.items():
            function = getattr(self.library, name)
            function.argtypes = arguments
            function.restype = ctypes.c_int
        self.library.test_simple_pressure_destroy.argtypes = [ctypes.c_void_p]
        self.library.test_simple_pressure_destroy.restype = None

    @staticmethod
    def views(case):
        arrays = [case[name] for name in NAMES]
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        return ((ctypes.c_size_t * 3)(*case['shape']),
                (DOUBLE_P * len(arrays))(*(a.ctypes.data_as(DOUBLE_P) for a in arrays)),
                (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays)))

    @contextmanager
    def assembly(self, case):
        handle = ctypes.c_void_p()
        error = ctypes.create_string_buffer(512)
        outlet = case['outlet']
        code = self.library.test_simple_pressure_create(case['dimension'], *self.views(case),
            outlet.ctypes.data_as(BYTE_P), outlet.size, ctypes.byref(handle), error, len(error))
        assert code == 0, (code, error.value)
        try:
            yield handle
        finally:
            self.library.test_simple_pressure_destroy(handle)

    def assemble(self, case, handle):
        n = int(np.prod(case['shape']))
        ptr, col = np.zeros(n + 1, np.int32), np.zeros(7 * n, np.int32)
        values, rhs, pins = np.zeros(7 * n), np.zeros(n), np.zeros(n, np.uint8)
        size = ctypes.c_size_t()
        error = ctypes.create_string_buffer(512)
        code = self.library.test_simple_pressure_assemble(handle, *self.views(case),
            ptr.ctypes.data_as(INT_P), col.ctypes.data_as(INT_P), values.ctypes.data_as(DOUBLE_P),
            rhs.ctypes.data_as(DOUBLE_P), pins.ctypes.data_as(BYTE_P), len(values), ctypes.byref(size),
            error, len(error))
        if code:
            return code, error.value.decode(), None
        matrix = sparse.csr_matrix((values[:size.value], col[:size.value], ptr), shape=(n, n))
        return code, '', (matrix, rhs, pins)

    def primitive(self, case, operation, *, excluded=None, alpha=.3):
        if excluded is None:
            excluded = python_pattern(case)['cell_kind'].astype(np.uint8)
        excluded = np.ascontiguousarray(excluded, dtype=np.uint8)
        metrics = np.full(8, np.nan)
        error = ctypes.create_string_buffer(512)
        outlet = case['outlet']
        code = self.library.test_simple_pressure_primitive(operation, case['dimension'], *self.views(case),
            outlet.ctypes.data_as(BYTE_P), outlet.size, excluded.ctypes.data_as(BYTE_P), excluded.size,
            alpha, metrics.ctypes.data_as(DOUBLE_P), error, len(error))
        return code, error.value.decode(), metrics


@pytest.fixture(scope='module')
def native_simple_pressure(tmp_path_factory):
    compiler = shlex.split(os.environ.get('CXX', 'cl' if os.name == 'nt' else 'c++'))
    if not compiler or not shutil.which(compiler[0]):
        message = 'SIMPLE primitive qualification requires CXX with C++17'
        if (os.environ.get('TPMSHX_REQUIRE_CPP_TESTS') == '1'
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail(message)
        pytest.skip(message)
    root = Path(__file__).resolve().parents[3]
    build = tmp_path_factory.mktemp('native-simple-pressure')
    suffix = '.dll' if os.name == 'nt' else ('.dylib' if sys.platform == 'darwin' else '.so')
    output = build / ('simple_pressure_test' + suffix)
    sources = [str(root / 'native/src/simple_pressure.cpp'),
               str(Path(__file__).with_name('simple_pressure_bridge.cpp'))]
    if os.name == 'nt':
        arguments = ['/nologo', '/std:c++17', '/O2', '/W4', '/WX', '/EHsc', '/MD', '/LD',
            '/DTPMSHX_THERMAL_BUILD_SHARED', '/I' + str(root / 'native/include'), *sources,
            '/Fe' + str(output), '/link', '/IMPLIB:' + str(build / 'simple_pressure_test.lib')]
    else:
        arguments = ['-std=c++17', '-O2', '-ffp-contract=off', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
            '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-fPIC',
            '-I', str(root / 'native/include'), *sources, '-o', str(output)]
    subprocess.run([*compiler, *arguments], cwd=build, check=True, text=True, capture_output=True)
    return NativePressurePrimitives(output)


def case_data(dimension, shape, *, weak=False, partial=True, seed=581031):
    rng = np.random.default_rng(seed)
    nx, ny, nz = shape
    case = dict(dimension=dimension, shape=shape,
                dx=rng.uniform(.002, .01, nx), dy=rng.uniform(.002, .01, ny),
                dz=np.ones(1) if dimension == 2 else rng.uniform(.002, .01, nz))
    case['rho'] = rng.uniform(.8, 1.5, shape)
    case['eps'] = rng.uniform(.4, .85, shape)
    case['rho_eps'] = case['rho'] * case['eps']
    for axis, name in enumerate(('u', 'v', 'w')):
        face_shape = list(shape)
        face_shape[axis] += 1
        if dimension == 2 and axis == 2:
            case[name] = case['d' + name] = case['mass_' + name] = np.empty(0)
            continue
        case[name] = (rng.uniform(.7, 1.3, face_shape) if axis == 1 else
                      rng.uniform(-1., 1., face_shape) * (1e-10 if weak else .03))
        case['d' + name] = rng.uniform(.001, .03, face_shape)
        case['mass_' + name] = np.zeros(face_shape)
    case['p'], case['pp'] = rng.uniform(10., 30., shape), rng.uniform(-.3, .3, shape)
    fraction = np.resize(np.array([0., .03, .6, 1.]), nx * nz).reshape(nx, nz)
    if not partial:
        fraction.fill(1.)
    fraction[-1, -1] = 1.
    case['inlet_fraction'] = fraction.copy() if dimension == 2 else np.empty(0)
    case['inlet_velocity'] = rng.uniform(.9, 1.1, (nx, nz)) * (fraction if dimension == 3 else 1.)
    case['outlet_fraction'] = np.flip(fraction).copy()
    case['outlet'] = np.ascontiguousarray(case['outlet_fraction'] > 0, dtype=np.uint8)
    return case


def python_pattern(case):
    nx, ny, nz = case['shape']
    if case['dimension'] == 2:
        return k2._build_pp_sparsity_pattern(nx, ny, case['outlet_fraction'][:, 0])
    return _build_pp_sparsity_3d(nx, ny, nz, case['outlet'].astype(bool))


def python_assembly(case):
    nx, ny, nz = case['shape']
    p = python_pattern(case)
    values, rhs = np.zeros(p['nnz']), np.zeros(nx * ny * nz)
    if case['dimension'] == 2:
        k2._assemble_pp_data_jit(values, rhs, case['u'][:, :, 0], case['v'][:, :, 0],
            case['du'][:, :, 0], case['dv'][:, :, 0], nx, ny, case['dx'], case['dy'],
            case['rho_eps'][:, :, 0], p['cell_base'], p['cell_kind'])
    else:
        k3._assemble_pp_3d(values, rhs, case['u'], case['v'], case['w'],
            case['du'], case['dv'], case['dw'], nx, ny, nz, case['dx'], case['dy'], case['dz'],
            case['rho_eps'], p['cell_base'], p['cell_kind'])
    matrix = sparse.csr_matrix((values, p['indices'], p['indptr']), shape=(len(rhs), len(rhs)))
    matrix.sum_duplicates(); matrix.sort_indices()
    return matrix, rhs, p['cell_kind']


def python_correct(case, alpha=.3):
    nx, ny, nz = case['shape']
    if case['dimension'] == 2:
        k2._correct_jit(case['u'][:, :, 0], case['v'][:, :, 0], case['p'][:, :, 0], case['pp'][:, :, 0],
            case['du'][:, :, 0], case['dv'][:, :, 0], case['inlet_fraction'][:, 0],
            case['inlet_velocity'][:, 0], case['outlet_fraction'][:, 0],
            nx, ny, case['dx'], case['dy'], alpha, case['rho'][:, :, 0], case['eps'][:, :, 0])
    else:
        k3._correct_jit_3d(case['u'], case['v'], case['w'], case['p'], case['pp'],
            case['du'], case['dv'], case['dw'], case['inlet_velocity'], nx, ny, nz, alpha,
            case['rho'], case['eps'], case['outlet'].astype(bool), case['dx'], case['dy'], case['dz'])


def python_boundary(case, *, inlet):
    nx, ny, nz = case['shape']
    if case['dimension'] == 2:
        if inlet:
            case['v'][:, 0, 0] = case['inlet_velocity'][:, 0] * case['inlet_fraction'][:, 0]
        k2._close_outlet_mass(case['u'][:, :, 0], case['v'][:, :, 0], case['outlet_fraction'][:, 0],
            nx, ny, case['dx'], case['dy'], case['rho'][:, :, 0], case['eps'][:, :, 0])
    else:
        original_inlet = case['v'][:, 0, :].copy()
        inlet_values = case['inlet_velocity'] if inlet else original_inlet
        k3._v_bc_3d(case['u'], case['v'], case['w'], inlet_values, case['rho'], case['eps'],
            case['outlet'].astype(bool), nx, ny, nz, case['dx'], case['dy'], case['dz'])


def python_diagnostics(case, excluded):
    nx, ny, nz = case['shape']
    if case['dimension'] == 2:
        u, v, er = (case[name][:, :, 0] for name in ('u', 'v', 'rho_eps'))
        local, count = k2._mass_res_solved_jit_2d(u, v, nx, ny, case['dx'], case['dy'], er, excluded)
        mi, mo, bf = k2._mass_global_jit_2d(v, nx, ny, case['dx'], er)
        legacy, reference = k2._mass_res_jit(v, nx, ny, case['dx'], er), 1.
    else:
        u, v, w, er = (case[name] for name in ('u', 'v', 'w', 'rho_eps'))
        local, count = k3._mass_res_solved_jit_3d(u, v, w, nx, ny, nz,
            case['dx'], case['dy'], case['dz'], er, excluded)
        mi, mo, bf = k3._mass_global_jit_3d(v, nx, ny, nz, case['dx'], case['dz'], er)
        inlet = np.sum(er[:, 0, :] * np.abs(v[:, 0, :]) * case['dx'][:, None] * case['dz'][None, :])
        reference = float(inlet) if inlet > 1e-12 else 1.
        legacy = k3._mass_res_jit_3d(u, v, w, nx, ny, nz,
            case['dx'], case['dy'], case['dz'], er) / reference
    global_mass = abs(mo - mi) / abs(mi) if abs(mi) > 1e-14 else 0.
    return np.array([local, count, mi, mo, global_mass, bf, legacy, reference])


def python_face_flux(case):
    # Independent array arithmetic with arithmetic face rho_eps and SI area.
    er, shape = case['rho_eps'], case['shape']
    output = []
    for axis, name in enumerate(('u', 'v', 'w')):
        if case['dimension'] == 2 and axis == 2:
            output.append(np.empty(0)); continue
        lo = np.take(er, [0], axis=axis)
        hi = np.take(er, [-1], axis=axis)
        lower, upper = [slice(None)] * 3, [slice(None)] * 3
        lower[axis], upper[axis] = slice(None, -1), slice(1, None)
        face_rho = np.concatenate((lo, .5 * (er[tuple(lower)] + er[tuple(upper)]), hi), axis=axis)
        area = np.ones([n + (i == axis) for i, n in enumerate(shape)])
        for other, widths in enumerate((case['dx'], case['dy'], case['dz'])):
            if other == axis:
                continue
            area *= widths.reshape([shape[other] if j == other else 1 for j in range(3)])
        output.append(face_rho * case[name] * area)
    return output


def check_assembly(native, case, handle):
    code, error, result = native.assemble(case, handle)
    assert code == 0, (code, error)
    expected = python_assembly(case)
    matrix, rhs, pins = result
    np.testing.assert_array_equal(matrix.indptr, expected[0].indptr)
    np.testing.assert_array_equal(matrix.indices, expected[0].indices)
    np.testing.assert_array_equal(pins, expected[2])
    np.testing.assert_allclose(matrix.data, expected[0].data, rtol=RTOL, atol=2e-18)
    np.testing.assert_allclose(rhs, expected[1], rtol=RTOL, atol=2e-18)
    if case['dimension'] == 3 and MACOS_ARM64:
        # Preserve the locked reference JIT's fused arithmetic: roundoff in a
        # pressure solve can alter later fixed-budget coupled exit decisions.
        np.testing.assert_array_equal(matrix.data, expected[0].data)
        np.testing.assert_array_equal(rhs, expected[1])
    return result


@pytest.mark.parametrize('dimension,shape', [
    (2, (5, 6, 1)), (3, (4, 5, 3)), (2, (1, 1, 1)),
    (3, (1, 1, 1)), (3, (1, 4, 3)), (3, (4, 1, 1)),
])
def test_canonical_ppe_assembly_matches_python(native_simple_pressure, dimension, shape):
    case = case_data(dimension, shape)
    with native_simple_pressure.assembly(case) as handle:
        check_assembly(native_simple_pressure, case, handle)


@pytest.mark.parametrize('dimension,shape', [(2, (5, 6, 1)), (3, (4, 5, 3))])
def test_cached_pattern_reassembles_values_and_recovers_after_bad_input(native_simple_pressure, dimension, shape):
    case = case_data(dimension, shape)
    with native_simple_pressure.assembly(case) as handle:
        initial = check_assembly(native_simple_pressure, case, handle)
        case['rho_eps'] *= 1.07
        case['du'] *= .83
        changed = check_assembly(native_simple_pressure, case, handle)
        assert not np.array_equal(initial[0].data, changed[0].data)
        case['dv'].flat[0] = np.nan
        code, error, _ = native_simple_pressure.assemble(case, handle)
        assert code == 1 and error
        case['dv'].flat[0] = 0.
        check_assembly(native_simple_pressure, case, handle)


@pytest.mark.parametrize('dimension,shape', [(2, (4, 5, 1)), (3, (3, 4, 2))])
def test_degenerate_unit_rows_preserve_original_outlet_cell_kind(native_simple_pressure, dimension, shape):
    case = case_data(dimension, shape)
    for name in ('du', 'dv', 'dw'):
        case[name].fill(0.)
    with native_simple_pressure.assembly(case) as handle:
        matrix, rhs, pins = check_assembly(native_simple_pressure, case, handle)
    np.testing.assert_array_equal(matrix.toarray(), np.eye(np.prod(shape)))
    assert np.all(rhs == 0.) and 0 < pins.sum() < len(pins)


@pytest.mark.parametrize('dimension,shape', [(2, (5, 6, 1)), (3, (4, 5, 3))])
@pytest.mark.parametrize('weak', [False, True])
def test_correction_preserves_pins_sidewalls_partial_ports_and_weak_crossflow(
        native_simple_pressure, dimension, shape, weak):
    case = case_data(dimension, shape, weak=weak)
    expected = deepcopy(case)
    python_correct(expected)
    code, error, _ = native_simple_pressure.primitive(case, 1)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['p'], expected['p'], rtol=RTOL, atol=2e-11)
    for name in ('u', 'v', 'w'):
        np.testing.assert_allclose(case[name], expected[name], rtol=RTOL, atol=1e-12)
    if dimension == 3 and MACOS_ARM64:
        for name in ('p', 'u', 'v', 'w'):
            np.testing.assert_array_equal(case[name], expected[name])
    pins = python_pattern(case)['cell_kind'].astype(bool).reshape(shape)
    original = case_data(dimension, shape, weak=weak)
    np.testing.assert_array_equal(case['p'][pins], original['p'][pins])
    assert np.all(case['u'][[0, -1], :, :] == 0.)
    if dimension == 3:
        assert np.all(case['w'][:, :, [0, -1]] == 0.)


@pytest.mark.parametrize('dimension,shape', [(2, (5, 4, 1)), (3, (4, 3, 2)), (3, (2, 1, 2))])
@pytest.mark.parametrize('inlet', [False, True])
def test_local_outlet_close_is_distinct_from_inlet_assignment(native_simple_pressure, dimension, shape, inlet):
    case = case_data(dimension, shape)
    expected = deepcopy(case)
    python_boundary(expected, inlet=inlet)
    original_inlet = case['v'][:, 0, :].copy()
    code, error, _ = native_simple_pressure.primitive(case, 3 if inlet else 2)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['v'], expected['v'], rtol=RTOL, atol=1e-12)
    if dimension == 3 and MACOS_ARM64:
        np.testing.assert_array_equal(case['v'], expected['v'])
    if not inlet:
        np.testing.assert_array_equal(case['v'][:, 0, :], original_inlet)
    # Count only open outlet CVs: their full physical continuity closes locally.
    excluded = np.ones(shape, np.uint8)
    excluded[:, -1, :] = 1 - case['outlet']
    code, error, metrics = native_simple_pressure.primitive(case, 4, excluded=excluded.ravel())
    assert code == 0, (code, error)
    assert metrics[0] <= 3e-13


@pytest.mark.parametrize('dimension,shape', [(2, (5, 4, 1)), (3, (4, 3, 2))])
@pytest.mark.parametrize('state', ['normal', 'backflow', 'zero', 'weak'])
def test_raw_flux_local_global_backflow_and_legacy_definitions(native_simple_pressure, dimension, shape, state):
    case = case_data(dimension, shape, weak=state == 'weak')
    if state == 'zero':
        for name in ('u', 'v', 'w'):
            case[name].fill(0.)
    elif state == 'backflow':
        case['v'][0, -1, :] = -2.
    for excluded in (python_pattern(case)['cell_kind'], np.zeros(np.prod(shape), np.uint8)):
        reference = python_diagnostics(case, excluded)
        code, error, metrics = native_simple_pressure.primitive(case, 4, excluded=excluded)
        assert code == 0, (code, error)
        np.testing.assert_allclose(metrics, reference, rtol=RTOL, atol=3e-13)
        assert metrics[1] == reference[1]
        for name, expected in zip(('mass_u', 'mass_v', 'mass_w'), python_face_flux(case)):
            np.testing.assert_allclose(case[name], expected, rtol=RTOL, atol=2e-18)
        if dimension == 3 and MACOS_ARM64:
            from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes

            thermal_faces = face_mass_fluxes(case['u'], case['v'], case['w'],
                case['rho'], case['eps'], case['dx'], case['dy'], case['dz'])
            for name, expected in zip(('mass_u', 'mass_v', 'mass_w'), thermal_faces):
                np.testing.assert_array_equal(case[name], expected)
        if state == 'backflow':
            assert metrics[5] > 0.
        elif state == 'zero':
            assert np.all(metrics[:7] == 0.) and metrics[7] == 1.


@pytest.mark.parametrize('bad', ['nan_velocity', 'zero_density', 'zero_porosity', 'negative_d',
                                  'invalid_fraction', 'invalid_mask', 'zero_width', 'wrong_extent'])
def test_invalid_input_rejected_before_correction_writes(native_simple_pressure, bad):
    case = case_data(2, (4, 5, 1))
    if bad == 'nan_velocity': case['u'].flat[0] = np.nan
    elif bad == 'zero_density': case['rho'].flat[0] = 0.
    elif bad == 'zero_porosity': case['eps'].flat[0] = 0.
    elif bad == 'negative_d': case['du'].flat[0] = -1.
    elif bad == 'invalid_fraction': case['inlet_fraction'].flat[0] = 1.01
    elif bad == 'invalid_mask': case['outlet'].flat[0] = 2
    elif bad == 'zero_width': case['dx'][0] = 0.
    elif bad == 'wrong_extent': case['pp'] = case['pp'].ravel()[:-1].copy()
    before = {name: case[name].copy() for name in ('p', 'u', 'v', 'w')}
    code, error, _ = native_simple_pressure.primitive(case, 1)
    assert code == 1 and error
    for name, expected in before.items():
        np.testing.assert_array_equal(case[name], expected)


def test_finite_input_arithmetic_overflow_is_not_reported_as_a_zero_residual(native_simple_pressure):
    case = case_data(3, (3, 4, 2))
    case['rho_eps'].fill(1e308)
    case['u'].fill(1e308)
    code, error, _ = native_simple_pressure.primitive(case, 4)
    assert code == 2 and 'nonfinite' in error
    correction = case_data(2, (4, 5, 1))
    correction['p'].fill(1e308); correction['pp'].fill(1e308)
    code, error, _ = native_simple_pressure.primitive(correction, 1, alpha=1.)
    assert code == 2 and 'nonfinite' in error


@pytest.mark.parametrize('dimension,shape', [(2, (5, 6, 1)), (3, (4, 5, 3))])
def test_native_assembled_equations_solve_then_correct_with_existing_candidate(
        native_simple_pressure, pressure_executable, dimension, shape):
    case = case_data(dimension, shape, weak=True)
    with native_simple_pressure.assembly(case) as handle:
        matrix, rhs, pins = check_assembly(native_simple_pressure, case, handle)
    row, = run_requests(pressure_executable, [request(matrix, rhs, pins, dimension=dimension)])
    assert row['status'] == 'solved' and row['method'] == 'superlu_colamd'
    pp = np.asarray(row['x'])
    np.testing.assert_allclose(pp, spsolve(matrix, rhs), rtol=1e-10, atol=1e-10)
    assert np.linalg.norm(matrix @ pp - rhs) / np.linalg.norm(rhs) <= 1e-10
    assert np.max(np.abs(pp[pins.astype(bool)])) <= 1e-10
    case['pp'][...] = pp.reshape(shape)
    expected = deepcopy(case)
    python_correct(expected)
    code, error, _ = native_simple_pressure.primitive(case, 1)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['p'], expected['p'], rtol=RTOL, atol=2e-11)
    for name in ('u', 'v', 'w'):
        np.testing.assert_allclose(case[name], expected[name], rtol=RTOL, atol=1e-12)
