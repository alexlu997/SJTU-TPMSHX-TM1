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
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.linalg import spsolve

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
            excluded = reference_pattern(case)['cell_kind'].astype(np.uint8)
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


def reference_pattern(case):
    pins = np.zeros(case['shape'], dtype=np.uint8)
    pins[:, -1, :] = case['outlet']
    return dict(cell_kind=pins.ravel())


def reference_assembly(case):
    shape, dimensions = case['shape'], case['dimension']
    density, widths = case['rho_eps'], (case['dx'], case['dy'], case['dz'])
    pins = reference_pattern(case)['cell_kind']
    rows, columns, values = [], [], []
    rhs = np.zeros(np.prod(shape))
    for cell in np.ndindex(shape):
        row = np.ravel_multi_index(cell, shape)
        if pins[row]:
            rows.append(row); columns.append(row); values.append(1.)
            continue
        coefficients, neighbors = [], []
        net = 0.
        for axis, name in enumerate('uvw'[:dimensions]):
            area = np.prod([widths[a][cell[a]] for a in range(3) if a != axis])
            flux = []
            for sign in (1, -1):
                neighbor = list(cell)
                neighbor[axis] += sign
                internal = 0 <= neighbor[axis] < shape[axis]
                rho = .5*(density[cell]+density[tuple(neighbor)]) if internal else density[cell]
                face = list(cell)
                face[axis] += int(sign == 1)
                flux.append(rho*case[name][tuple(face)])
                if internal:
                    coefficients.append(rho*case['d'+name][tuple(face)]*area)
                    neighbors.append(np.ravel_multi_index(tuple(neighbor), shape))
            net += (flux[0]-flux[1])*area
        diagonal = sum(coefficients)
        degenerate = diagonal < 1e-30
        rows.extend([row]*(len(neighbors)+1))
        columns.extend([row, *neighbors])
        values.extend([1. if degenerate else diagonal,
                       *[0. if degenerate else -c for c in coefficients]])
        rhs[row] = 0. if degenerate else -net
    matrix = sparse.csr_matrix((values, (rows, columns)), shape=(len(rhs), len(rhs)))
    return matrix, rhs, pins


def reference_correct(case, alpha=.3):
    pins = reference_pattern(case)['cell_kind'].reshape(case['shape']).astype(bool)
    case['p'][~pins] += alpha*case['pp'][~pins]
    for axis, name in enumerate('uvw'[:case['dimension']]):
        faces, low, high = ([slice(None)]*3 for _ in range(3))
        faces[axis], low[axis], high[axis] = slice(1, -1), slice(None, -1), slice(1, None)
        case[name][tuple(faces)] += case['d'+name][tuple(faces)]*(
            case['pp'][tuple(low)] - case['pp'][tuple(high)])
        if axis != 1:
            edge = [slice(None)]*3
            edge[axis] = [0, -1]
            case[name][tuple(edge)] = 0.
    reference_boundary(case, inlet=True)


def reference_boundary(case, *, inlet):
    if inlet:
        case['v'][:, 0, :] = case['inlet_velocity'] * (
            case['inlet_fraction'] if case['dimension'] == 2 else 1.)
    faces = reference_face_flux(case)
    net = np.diff(faces[0], axis=0)[:, -1, :] - faces[1][:, -2, :]
    if case['dimension'] == 3:
        net += np.diff(faces[2], axis=2)[:, -1, :]
    area = case['dx'][:, None] * case['dz'][None, :]
    case['v'][:, -1, :] = np.where(case['outlet'], -net/(case['rho_eps'][:, -1, :]*area), 0.)


def reference_diagnostics(case, excluded):
    faces = reference_face_flux(case)
    net, through = np.zeros(case['shape']), np.zeros(case['shape'])
    for axis, flux in enumerate(faces[:case['dimension']]):
        low, high = [slice(None)]*3, [slice(None)]*3
        low[axis], high[axis] = slice(None, -1), slice(1, None)
        net += flux[tuple(high)] - flux[tuple(low)]
        through += np.abs(flux[tuple(high)]) + np.abs(flux[tuple(low)])
    counted = (through > 0.) & (excluded.reshape(case['shape']) == 0)
    local = np.max(np.abs(net[counted])/through[counted]) if counted.any() else 0.
    mi, mo = faces[1][:, 0, :].sum(), faces[1][:, -1, :].sum()
    absolute_out = np.abs(faces[1][:, -1, :]).sum()
    bf = np.maximum(-faces[1][:, -1, :], 0.).sum()/absolute_out if absolute_out else 0.
    inlet = np.abs(faces[1][:, 0, :]).sum()
    if case['dimension'] == 2:
        reference = 1.
        planes = faces[1][:, 1:, :].sum(axis=(0, 2))
        legacy = np.max(np.abs(planes-inlet))/inlet if inlet >= 1e-30 else 0.
    else:
        reference = float(inlet) if inlet > 1e-12 else 1.
        legacy = np.max(np.abs(net))/reference
    global_mass = abs(mo-mi)/abs(mi) if abs(mi) > 1e-14 else 0.
    return np.array([local, counted.sum(), mi, mo, global_mass, bf, legacy, reference])


def reference_face_flux(case):
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
    expected = reference_assembly(case)
    matrix, rhs, pins = result
    np.testing.assert_array_equal(matrix.indptr, expected[0].indptr)
    np.testing.assert_array_equal(matrix.indices, expected[0].indices)
    np.testing.assert_array_equal(pins, expected[2])
    np.testing.assert_allclose(matrix.data, expected[0].data, rtol=RTOL, atol=2e-18)
    np.testing.assert_allclose(rhs, expected[1], rtol=RTOL, atol=2e-18)
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
    reference_correct(expected)
    code, error, _ = native_simple_pressure.primitive(case, 1)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['p'], expected['p'], rtol=RTOL, atol=2e-11)
    for name in ('u', 'v', 'w'):
        np.testing.assert_allclose(case[name], expected[name], rtol=RTOL, atol=1e-12)
    pins = reference_pattern(case)['cell_kind'].astype(bool).reshape(shape)
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
    reference_boundary(expected, inlet=inlet)
    original_inlet = case['v'][:, 0, :].copy()
    code, error, _ = native_simple_pressure.primitive(case, 3 if inlet else 2)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['v'], expected['v'], rtol=RTOL, atol=1e-12)
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
    for excluded in (reference_pattern(case)['cell_kind'], np.zeros(np.prod(shape), np.uint8)):
        reference = reference_diagnostics(case, excluded)
        code, error, metrics = native_simple_pressure.primitive(case, 4, excluded=excluded)
        assert code == 0, (code, error)
        np.testing.assert_allclose(metrics, reference, rtol=RTOL, atol=3e-13)
        assert metrics[1] == reference[1]
        for name, expected in zip(('mass_u', 'mass_v', 'mass_w'), reference_face_flux(case)):
            np.testing.assert_allclose(case[name], expected, rtol=RTOL, atol=2e-18)
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
    reference_correct(expected)
    code, error, _ = native_simple_pressure.primitive(case, 1)
    assert code == 0, (code, error)
    np.testing.assert_allclose(case['p'], expected['p'], rtol=RTOL, atol=2e-11)
    for name in ('u', 'v', 'w'):
        np.testing.assert_allclose(case[name], expected[name], rtol=RTOL, atol=1e-12)
