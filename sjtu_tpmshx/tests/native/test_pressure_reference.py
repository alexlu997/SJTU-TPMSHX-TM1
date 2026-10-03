"""Original pressure shooting, port geometry and final-envelope parity.

Frozen tolerances before comparison: rtol=4e-15 and atol=2e-10 Pa for
pressure states; rtol=4e-15 for squared-pressure/history arithmetic;
exact overlap fractions, validity decisions and reason/exception messages.
These porting checks do not relax physical convergence thresholds.
"""
import ctypes as ct
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.generate_native_model_coefficients import header
from sjtu_tpmshx.models import envelope
from sjtu_tpmshx.models.grid import _port_fractions_1d, _port_overlap_1d
from sjtu_tpmshx.solvers import _solve_common as original

D = ct.POINTER(ct.c_double)
C = ct.POINTER(ct.c_char)
S = ct.c_size_t


def data(values):
    return np.ascontiguousarray(values, dtype=np.float64)


def pointer(values):
    return values.ctypes.data_as(D)


class Native:
    def __init__(self, path):
        self.lib = ct.CDLL(str(path))
        declarations = {
            'test_pressure_state': [ct.POINTER(S), ct.POINTER(D), ct.c_double, ct.c_double, D, C, C, S],
            'test_pressure_step': [ct.c_int, D, D, C, C, S],
            'test_pressure_envelope': [D, ct.c_int, ct.c_char_p, ct.c_char_p, ct.POINTER(ct.c_int), C, C, S],
            'test_pressure_mach': [ct.c_int, D, S, D, S, D, D, C, S],
            'test_port_overlap': [D, S, ct.c_double, ct.c_double, ct.c_int, D, C, S],
            'test_port_fractions': [D, S, ct.c_double, ct.c_double, ct.c_int, D, D, C, S],
        }
        for name, signature in declarations.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = signature, ct.c_int

    def state(self, shape, arrays, reference, specified):
        result, definition, error = np.empty(8), ct.create_string_buffer(1024), ct.create_string_buffer(1024)
        code = self.lib.test_pressure_state((S * 3)(*shape), (D * 6)(*map(pointer, arrays)),
                                           reference, specified, pointer(result), definition, error, len(error))
        return code, result, definition.value.decode(), error.value.decode()

    def step(self, operation, values):
        result, history, error = np.empty(2), ct.create_string_buffer(2048), ct.create_string_buffer(2048)
        code = self.lib.test_pressure_step(operation, pointer(data(values)), pointer(result), history, error, len(error))
        return code, result, json.loads(history.value or '[]'), error.value.decode()

    def envelope(self, pressure, vmax, temperature, mode, *, ma=None, limit=1., r=287.05, gamma=1.4, dims='3D'):
        valid, reasons, error = ct.c_int(), ct.create_string_buffer(2048), ct.create_string_buffer(2048)
        values = data([pressure, vmax, temperature, limit, r, gamma, 0 if ma is None else ma])
        code = self.lib.test_pressure_envelope(pointer(values), int(ma is not None), mode.encode(), dims.encode(),
                                              ct.byref(valid), reasons, error, len(error))
        return code, bool(valid.value), reasons.value.decode().splitlines(), error.value.decode()

    def mach(self, operation, speeds, temperatures, *, r=287.05, gamma=1.4, pin=2e5, drag=8000., length=.1):
        speed, temperature = data(speeds), data(temperatures)
        values, result, error = data([r, gamma, pin, drag, length]), ct.c_double(), ct.create_string_buffer(1024)
        code = self.lib.test_pressure_mach(operation, pointer(speed), speed.size, pointer(temperature), temperature.size,
                                          pointer(values), ct.byref(result), error, len(error))
        return code, result.value, error.value.decode()


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    compiler = shlex.split(os.environ.get('CXX', 'cl' if os.name == 'nt' else 'c++'))
    if not compiler or not shutil.which(compiler[0]):
        if (os.environ.get('TPMSHX_REQUIRE_CPP_TESTS') == '1'
                or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1'):
            pytest.fail('pressure reference qualification requires C++17')
        pytest.skip('pressure reference qualification requires C++17')
    root = Path(__file__).resolve().parents[3]
    build = tmp_path_factory.mktemp('native-pressure-reference')
    generated = build / 'tpmshx'
    generated.mkdir()
    (generated / 'model_coefficients.hpp').write_text(header(), encoding='utf-8')
    output = build / ('pressure_reference' + ('.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'))
    sources = [root / 'native/src/pressure_reference.cpp', Path(__file__).with_name('pressure_reference_bridge.cpp')]
    if os.name == 'nt':
        arguments = ['/nologo', '/std:c++17', '/O2', '/W4', '/WX', '/EHsc', '/MD', '/LD', '/fp:strict',
                     '/DTPMSHX_THERMAL_BUILD_SHARED', '/I' + str(root / 'native/include'), '/I' + str(build),
                     *sources, '/Fe' + str(output), '/link', '/IMPLIB:' + str(build / 'pressure_reference.lib')]
    else:
        arguments = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-ffp-contract=off',
                     '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-fPIC',
                     '-I', root / 'native/include', '-I', build, *sources, '-o', output]
    subprocess.run([*compiler, *arguments], cwd=build, check=True, text=True, capture_output=True)
    return Native(output)


@pytest.mark.parametrize('shape', [(5, 7, 1), (5, 1, 1), (4, 6, 3), (4, 1, 3)])
@pytest.mark.parametrize('partial', [False, True])
def test_geometric_physical_face_pressure(native, shape, partial):
    nx, ny, nz = shape
    rng = np.random.default_rng(602011 + ny)
    dx, dy, dz = [data(rng.uniform(.0002, .02, n)) for n in shape]
    if nz == 1:
        dz[:] = 1
    pressure = data(rng.uniform(-900, 3500, shape))
    inlet, outlet = (np.ones((nx, nz)) for _ in range(2))
    if partial:
        inlet[0], outlet[-1] = 0, 0
        inlet[1], outlet[-2] = .14, .83
    solver = SimpleNamespace(fluid_type='ideal_gas', P=pressure if nz > 1 else pressure[..., 0],
        P_ref_abs=102503., dx=dx, dy=dy, dz=dz, dx_arr=dx, dy_arr=dy,
        inlet_frac=inlet, outlet_frac=outlet, inlet_geom_frac=inlet[:, 0], outlet_geom_frac=outlet[:, 0],
        pressure_iterations=[])
    expected = original.inlet_pressure_state(solver, 104000.)
    code, actual, definition, error = native.state(shape, [dx, dy, dz, pressure, inlet, outlet], 102503., 104000.)
    assert code == 0, error
    keys = ['specified_Pa', 'realized_Pa', 'outlet_Pa', 'outlet_gauge_Pa', 'minimum_Pa',
            'relative_error', 'relative_tolerance', 'passed']
    np.testing.assert_allclose(actual, [expected[key] for key in keys], rtol=4e-15, atol=2e-10)
    assert bool(actual[-1]) == expected['passed']
    assert definition == expected['definition']


@pytest.mark.parametrize('partial', [False, True])
def test_pressure_shooting_preserves_large_port_reduction_order(native, partial):
    # A wide physical port exposes reduction roundoff that can change a later
    # SIMPLE stopping iteration in an otherwise identical coupled solve.
    shape = (14, 92, 10)
    nx, ny, nz = shape
    dx = data(np.linspace(.001, .005, nx))
    dy = data(np.linspace(.0003, .003, ny))
    dz = data(np.linspace(.001, .006, nz))
    i, j, k = np.indices(shape)
    pressure = data(103000. - 1100. * j + 19. * i * i - 3. * k * k + .1 * i * k)
    inlet, outlet = (np.ones((nx, nz)) for _ in range(2))
    if partial:
        inlet[:3], outlet[-4:] = 0., 0.
        inlet[3], outlet[-5] = .31, .57
    reference, specified = 89000., 192000.
    solver = SimpleNamespace(fluid_type='ideal_gas', P=pressure, P_ref_abs=reference,
        dx=dx, dy=dy, dz=dz, inlet_frac=inlet, outlet_frac=outlet, pressure_iterations=[])
    expected = original.inlet_pressure_state(solver, specified)
    code, actual, _, error = native.state(shape, [dx, dy, dz, pressure, inlet, outlet],
                                          reference, specified)
    assert code == 0, error
    keys = ['specified_Pa', 'realized_Pa', 'outlet_Pa', 'outlet_gauge_Pa', 'minimum_Pa',
            'relative_error', 'relative_tolerance', 'passed']
    np.testing.assert_array_equal(actual, [expected[key] for key in keys])
    code, step, history, error = native.step(1, actual[:7])
    assert code == 0, error
    assert step[0] == original.pressure_shooting_reference(expected)
    assert history == expected['iterations']


@pytest.mark.parametrize('residual', [0., 1e-4, -1e-4, .9999e-4, -.9999e-4, 1.0001e-4])
def test_inlet_tolerance_is_original_strict_boundary(native, residual):
    pin = 100000.
    arrays = [data([1.])] * 3 + [data([pin * residual]), data([1.]), data([1.])]
    code, actual, _, error = native.state((1, 1, 1), arrays, pin, pin)
    assert code == 0, error
    assert bool(actual[-1]) == (abs((pin + pin * residual - pin) / pin) < original.INLET_PRESSURE_REL_TOL)


@pytest.mark.parametrize('estimate,pin', [(9e10, 3.1e5), (-4e9, 2e5), (1e6, 2e5), (1e6 + 1, 2e5),
                                        (np.nan, 2e5), (1e10, np.inf), (1e10, 1000.)])
def test_initial_reference_and_history(native, estimate, pin):
    history = []
    code, actual, native_history, error = native.step(0, [estimate, pin])
    try:
        expected = original.pressure_initial_reference(estimate, pin, history=history)
    except ValueError as exc:
        assert code == 1 and error == str(exc)
    else:
        assert code == 0, error
        assert actual[0] == expected
        assert native_history == history


@pytest.mark.parametrize('pin,realized,pout,gauge,minimum', [
    (110000., 100000., 90000., -120., 85000.),
    (100000., 110000., 95000., 111., 90000.),
    (2000., 200000., 5000., -501., 2000.),
    (2000., 200000., 1000., 0., 1000.),
    (1000., 1000., 1000., 0., 1000.),
    (200000., np.nan, 90000., 0., 85000.),
])
def test_shooting_original_floor_damping_and_history(native, pin, realized, pout, gauge, minimum):
    state = dict(specified_Pa=pin, realized_Pa=realized, outlet_Pa=pout, outlet_gauge_Pa=gauge,
                 minimum_Pa=minimum, relative_error=(realized - pin) / pin, iterations=[])
    values = [pin, realized, pout, gauge, minimum, state['relative_error'], 1e-4]
    code, actual, history, error = native.step(1, values)
    try:
        expected = original.pressure_shooting_reference(state)
    except RuntimeError as exc:
        assert code == 3 and error == str(exc)
    else:
        assert code == 0, error
        np.testing.assert_allclose(actual, [expected, original.pressure_shooting_target_sq(state)], rtol=4e-15)
        assert history == state['iterations']


def test_pressure_history_retains_initialization_and_update(native):
    state = dict(specified_Pa=110000., realized_Pa=100000., outlet_Pa=90000., outlet_gauge_Pa=-123.,
                 minimum_Pa=85000., relative_error=-1/11, iterations=[])
    original.pressure_initial_reference(-100., state['specified_Pa'], history=state['iterations'])
    original.pressure_shooting_reference(state)
    code, _, history, error = native.step(2, [110000., 100000., 90000., -123., 85000., -1/11, 1e-4, -100.])
    assert code == 0, error
    assert history == state['iterations']


@pytest.mark.parametrize('mode', ['raise', 'warn', 'off'])
@pytest.mark.parametrize('pressure,ma', [(2e5, .2), (1000.001, .2), (1000.00101, .2),
                                       (2e5, 1.), (2e5, .999999), (np.nan, np.nan),
                                       (np.inf, np.inf), (-10., 1.2)])
def test_final_envelope_modes_thresholds_and_evidence(native, mode, pressure, ma):
    code, valid, reasons, error = native.envelope(pressure, 200., 300., mode, ma=ma, dims='2D')
    try:
        expected = envelope.gate_solution(pressure, 200., 300., mode=mode, dims='2D', ma_max=ma)
    except envelope.ChokedFlowError as exc:
        assert code == 4 and error == str(exc)
    else:
        assert code == 0, error
        assert (valid, reasons) == expected


def test_invalid_envelope_mode_rejected_before_assessment(native):
    with pytest.raises(ValueError) as expected:
        envelope.gate_solution(np.nan, 100., 0., mode='raised')
    code, _, _, error = native.envelope(np.nan, 100., 0., 'raised')
    assert code == 1 and error == str(expected.value)


@pytest.mark.parametrize('speeds,temperatures', [([], []), ([100., 200.], [300., 150.]),
    ([100., 200.], [300.]), ([.1, 2.], [-20., 0.]), ([np.nan, 200.], [300., 300.]),
    ([100., 200.], [np.nan, 300.]), ([np.inf], [300.]), ([100.], [np.inf])])
def test_local_temperature_mach_field(native, speeds, temperatures):
    code, actual, error = native.mach(0, speeds, temperatures)
    assert code == 0, error
    expected = envelope.mach_field_max(speeds, temperatures)
    np.testing.assert_allclose(actual, expected, rtol=4e-15, equal_nan=True)


def test_scalar_custom_gas_and_pressure_estimate(native):
    code, actual, error = native.mach(1, [240.], [390.], r=298., gamma=1.33)
    assert code == 0, error
    assert actual == envelope.mach(240., 390., R=298., gamma=1.33)
    code, actual, error = native.mach(2, [0.], [390.], r=298., pin=150000., drag=98700., length=1.7)
    assert code == 0, error
    assert actual == envelope.predict_outlet_p_sq(150000., 390., 98700., 1.7, R=298.)
    code, valid, reasons, error = native.envelope(2e5, 240., 390., 'warn', r=298., gamma=1.33, limit=.5)
    assert code == 0, error
    assert (valid, reasons) == envelope.gate_solution(2e5, 240., 390., mode='warn', R=298., gamma=1.33, mach_limit=.5)


@pytest.mark.parametrize('staggered', [False, True])
@pytest.mark.parametrize('widths,lo,hi', [([.1] * 10, .2, .7), ([.1, .15, .23, .031], .06, .404),
    ([.1] * 10, .3, .4), ([.1] * 10, .3, .3 + 1e-10), ([.2], 0., .2), ([.2], -.1, .3)])
def test_partial_port_overlap_preserves_spatial_ulp_wall_rule(native, staggered, widths, lo, hi):
    widths = data(widths)
    result, error = np.empty(widths.size + staggered), ct.create_string_buffer(1024)
    code = native.lib.test_port_overlap(pointer(widths), widths.size, lo, hi, staggered,
                                        pointer(result), error, len(error))
    assert code == 0, error.value.decode()
    np.testing.assert_array_equal(result, _port_overlap_1d(widths, lo, hi, staggered=staggered))


@pytest.mark.parametrize('uniform', [False, True])
@pytest.mark.parametrize('widths,lo,hi', [([.1] * 20, .2, 1.7), ([.1, .15, .23, .031], .06, .404),
    ([.1] * 10, .3, .4), ([.1] * 10, .3, .3 + 1e-10), ([.2], 0., .2)])
def test_original_port_profile(native, uniform, widths, lo, hi):
    widths = data(widths)
    geometric, profile, error = np.empty(widths.size), np.empty(widths.size), ct.create_string_buffer(1024)
    code = native.lib.test_port_fractions(pointer(widths), widths.size, lo, hi, uniform,
                                         pointer(geometric), pointer(profile), error, len(error))
    assert code == 0, error.value.decode()
    expected_geom, expected_profile = _port_fractions_1d(widths, lo, hi, uniform=uniform)
    np.testing.assert_array_equal(geometric, expected_geom)
    np.testing.assert_allclose(profile, expected_profile, rtol=4e-15, atol=0.)


@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_pressure_is_preserved_for_physical_gate(native, bad):
    pressure = data([[[20.], [bad], [0.]], [[20.], [10.], [0.]]])
    arrays = [data([.1, .1]), data([.1, .1, .1]), data([1.]), pressure,
              data([0., 1.]), data([0., 1.])]
    code, actual, _, error = native.state((2, 3, 1), arrays, 1e5, 100025.)
    assert code == 0, error
    solver = SimpleNamespace(fluid_type='ideal_gas', P=pressure[..., 0], P_ref_abs=1e5,
        dx_arr=arrays[0], dy_arr=arrays[1], inlet_geom_frac=arrays[4], outlet_geom_frac=arrays[5])
    expected = original.inlet_pressure_state(solver, 100025.)
    np.testing.assert_allclose(actual[4], expected['minimum_Pa'], equal_nan=True)
    # NaN is not erased even when its row has no geometric opening; +inf is
    # intentionally absent from np.min evidence, matching the original helper.
    assert bool(actual[-1]) == expected['passed']
